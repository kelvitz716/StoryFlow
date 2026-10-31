"""Base class for media downloaders providing shared networking and parsing functionality."""

import os
import re
import signal
import asyncio
import logging
from collections import deque
from typing import Optional, Callable, Dict
from core.queue import _env_int
from utils.log_sanitizer import sanitize_string

# Wall-clock timeout for every subprocess call (seconds).
_DOWNLOAD_TIMEOUT = _env_int('DOWNLOAD_TIMEOUT_SECONDS', 600, 10, 86400)

# Cumulative download size limit per job in MB (G4).
_MAX_JOB_SIZE_MB = _env_int('MAX_JOB_SIZE_MB', 2048, 10, 100000)

# Maximum files downloaded per job (G4).
_MAX_FILES_PER_JOB = _env_int('MAX_FILES_PER_JOB', 500, 1, 10000)

# Maximum stderr tail to keep in memory (bytes). Prevents OOM on a phone.
_STDERR_TAIL_BYTES = 65_536  # 64 KB

# Maximum stdout lines/bytes to keep in memory (item 1).
_STDOUT_MAX_LINES = 200
_STDOUT_MAX_BYTES = 65_536  # 64 KB

# Pipe buffer size — 1 MB avoids ValueError on very long gallery-dl JSON lines.
_PIPE_LIMIT = 1_048_576  # 1 MB


def _clean_partial_files(directory: str) -> None:
    """Delete partial and temporary files (e.g. .part, .ytdl, .tmp) in directory."""
    if not os.path.isdir(directory):
        return
    for root, _, filenames in os.walk(directory):
        for fname in filenames:
            fname_lower = fname.lower()
            if (
                fname_lower.endswith('.part')
                or fname_lower.endswith('.ytdl')
                or fname_lower.endswith('.tmp')
                or '.part-' in fname_lower
            ):
                try:
                    os.remove(os.path.join(root, fname))
                except OSError:
                    pass


async def _drain_stderr(stderr_stream: asyncio.StreamReader) -> bytes:
    """
    Continuously drain a stderr stream, keeping only the last _STDERR_TAIL_BYTES
    bytes in memory.  This prevents a full stderr pipe from deadlocking the
    process and prevents unbounded memory growth on a RAM-constrained device.
    """
    tail = bytearray()
    try:
        while True:
            chunk = await stderr_stream.read(8192)
            if not chunk:
                break
            tail.extend(chunk)
            # Trim to keep only the last _STDERR_TAIL_BYTES
            if len(tail) > _STDERR_TAIL_BYTES:
                del tail[:len(tail) - _STDERR_TAIL_BYTES]
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logging.debug(f"_drain_stderr: read error: {exc}")
    return bytes(tail)


class BaseDownloader:
    """
    Abstract base class for platform downloaders.
    Provides shared methods for execution, directory preparation, and error tracking.
    """

    def __init__(self, output_path: str):
        self.output_path = output_path
        os.makedirs(self.output_path, exist_ok=True)

    def _prepare_job_directory(self, job_id: str) -> str:
        """Create and return an isolated directory for a specific download job."""
        job_dir = os.path.join(self.output_path, job_id)
        os.makedirs(job_dir, exist_ok=True)
        return job_dir

    def _get_download_files(self, path: Optional[str] = None) -> set:
        """Get set of all files currently in specified directory. Useful for diffing new downloads."""
        target_path = path or self.output_path
        files = set()
        for root, dirs, filenames in os.walk(target_path):
            for filename in filenames:
                if not filename.startswith('.'):  # Skip hidden files
                    files.add(os.path.join(root, filename))
        return files

    def _is_retryable_error(self, stderr: str) -> bool:
        """Check if error output indicates a network or temporary failure."""
        retryable_keywords = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'rate limit',
            'try again',
            'too many requests',
        ]
        stderr_lower = stderr.lower()
        if any(keyword in stderr_lower for keyword in retryable_keywords):
            return True
        # Match HTTP 429 and 5xx (e.g., 500, 502, 503, 504)
        if re.search(r'\b(429|5\d{2})\b', stderr_lower):
            return True
        return False

    async def _execute_with_retry(
        self,
        command: list,
        process_name: str = "subprocess",
        max_attempts: int = 3,
        progress_callback: Optional[Callable] = None,
        job_dir: Optional[str] = None,
        check_interval: float = 2.0,
    ) -> Dict:
        """
        Execute command with unified async retry logic, concurrent stderr drain,
        wall-clock timeout, size/file-count watchdog, and process-group cleanup.

        Key safety properties (item 4, G4):
        - start_new_session=True: subprocess gets its own process group so we can
          killpg the whole tree on timeout or size limit.
        - limit=_PIPE_LIMIT: prevents ValueError on very long stdout lines
          (e.g. gallery-dl JSON output). ValueError is caught and treated as a
          regular line read error rather than crashing the job.
        - Concurrent stderr drain: _drain_stderr runs as a task alongside the
        - Watchdog task: every 2s checks cumulative file size and file count in
          job_dir. If MAX_JOB_SIZE_MB or MAX_FILES_PER_JOB is exceeded, kills
          process group, cleans partial files, and terminates without retry.
        - Wall-clock timeout (DOWNLOAD_TIMEOUT_SECONDS, default 600 s): on
          expiry the whole process group is killed and the drain task is
          cancelled.
        - Raw stderr is NEVER returned in result dicts; only generic messages
          are surfaced to callers. Full stderr is logged at DEBUG level.
        """
        last_stderr_text = ""
        target_dir = job_dir or self.output_path
        max_job_bytes = _MAX_JOB_SIZE_MB * 1024 * 1024

        for attempt in range(1, max_attempts + 1):
            process = None
            stderr_task = None
            watchdog_task = None
            stderr_text = ""
            returncode = None
            limit_hit = False
            limit_reason = ""

            try:
                # Async subprocess execution with process group isolation
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    limit=_PIPE_LIMIT,
                )

                # Start concurrent stderr drain BEFORE reading stdout
                stderr_task = asyncio.create_task(_drain_stderr(process.stderr))

                # G4 watchdog task: checks job_dir total size and file count every check_interval seconds
                async def _watchdog():
                    nonlocal limit_hit, limit_reason
                    try:
                        while process.returncode is None:
                            await asyncio.sleep(check_interval)
                            if not os.path.exists(target_dir):
                                continue
                            total_size = 0
                            file_count = 0
                            for root, _, files in os.walk(target_dir):
                                for f in files:
                                    if not f.startswith('.'):
                                        file_count += 1
                                    fp = os.path.join(root, f)
                                    try:
                                        total_size += os.path.getsize(fp)
                                    except OSError:
                                        pass

                            if total_size > max_job_bytes:
                                limit_hit = True
                                limit_reason = f"Download size limit reached ({_MAX_JOB_SIZE_MB} MB cap)"
                                logging.warning(f"⚠️ {process_name}: {limit_reason}")
                                try:
                                    pgid = os.getpgid(process.pid)
                                    os.killpg(pgid, signal.SIGKILL)
                                except (ProcessLookupError, OSError):
                                    pass
                                break

                            if file_count > _MAX_FILES_PER_JOB:
                                limit_hit = True
                                limit_reason = f"File count limit reached ({_MAX_FILES_PER_JOB} files cap)"
                                logging.warning(f"⚠️ {process_name}: {limit_reason}")
                                try:
                                    pgid = os.getpgid(process.pid)
                                    os.killpg(pgid, signal.SIGKILL)
                                except (ProcessLookupError, OSError):
                                    pass
                                break
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logging.debug(f"Watchdog error: {exc}")

                watchdog_task = asyncio.create_task(_watchdog())

                stdout_lines: deque[str] = deque(maxlen=_STDOUT_MAX_LINES)
                stdout_bytes = 0

                try:
                    async with asyncio.timeout(_DOWNLOAD_TIMEOUT):
                        # Stream stdout line-by-line for progress callbacks
                        while True:
                            try:
                                line = await process.stdout.readline()
                            except ValueError:
                                # Line exceeded limit — skip this line, keep reading
                                logging.debug(f"{process_name}: skipped oversized stdout line")
                                continue

                            if not line:
                                break

                            line_text = line.decode(errors='replace').strip()
                            if line_text:
                                # Parse progress
                                if progress_callback:
                                    # Ensure progress text never surfaces a URL or query string
                                    if line_text.lower().startswith('http') or '://' in line_text:
                                        pass
                                    # yt-dlp style: [download]  23.5% of ...
                                    elif "[download]" in line_text and "%" in line_text:
                                        try:
                                            parts = line_text.split()
                                            percent = next((p for p in parts if "%" in p), "0%")
                                            if "ETA" in line_text:
                                                eta = next((p for p in parts if ":" in p and len(p) <= 8 and p[0].isdigit()), "")
                                                progress_callback(f"Downloading: {percent} (ETA {eta})")
                                            else:
                                                progress_callback(f"Downloading: {percent}")
                                        except Exception:
                                            pass

                                    # gallery-dl style (usually just filenames)
                                    elif line_text.startswith('#'):
                                        pass
                                    elif "." in line_text and ("/" in line_text or "\\" in line_text):
                                        if '?' not in line_text and not line_text.lower().startswith('http') and '://' not in line_text:
                                            base = os.path.basename(line_text)
                                            if base and '?' not in base and not base.lower().startswith('http'):
                                                progress_callback(f"Downloading: {base}")

                                # Store at most the last 200 lines (or 64 KB)
                                if len(line_text) > _STDOUT_MAX_BYTES:
                                    line_text = line_text[-_STDOUT_MAX_BYTES:]

                                if len(stdout_lines) == _STDOUT_MAX_LINES:
                                    stdout_bytes -= len(stdout_lines[0])

                                stdout_lines.append(line_text)
                                stdout_bytes += len(line_text)

                                while stdout_bytes > _STDOUT_MAX_BYTES and stdout_lines:
                                    dropped = stdout_lines.popleft()
                                    stdout_bytes -= len(dropped)

                        # Wait for process to finish, then collect stderr
                        await process.wait()
                        returncode = process.returncode
                        stderr_bytes = await stderr_task
                        stderr_task = None
                        stderr_text = stderr_bytes.decode(errors='replace')

                except asyncio.TimeoutError:
                    # Kill the entire process group on wall-clock timeout
                    if process and process.returncode is None:
                        try:
                            pgid = os.getpgid(process.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            pass
                    # Cancel and drain the stderr task so nothing leaks
                    if stderr_task and not stderr_task.done():
                        stderr_task.cancel()
                        try:
                            await stderr_task
                        except asyncio.CancelledError:
                            pass
                    raise TimeoutError(f"Process exceeded {_DOWNLOAD_TIMEOUT}s wall-clock timeout")
                finally:
                    if watchdog_task and not watchdog_task.done():
                        watchdog_task.cancel()
                        try:
                            await watchdog_task
                        except asyncio.CancelledError:
                            pass

                stdout_text = "\n".join(stdout_lines)

                # If the watchdog killed the process due to size/file count limit
                if limit_hit:
                    _clean_partial_files(target_dir)
                    return {
                        'success': False,
                        'limit_reached': True,
                        'error': limit_reason,
                        'message': "Download stopped: limit reached",
                        'platform': process_name,
                        'stdout': stdout_text,
                    }

                # Log full stderr for debugging; never return it to callers
                if stderr_text:
                    logging.debug(f"STDERR ({process_name}):\n{stderr_text}")

                if returncode == 0:
                    return {
                        'success': True,
                        'stdout': stdout_text,
                        'platform': process_name
                    }
                else:
                    raise ValueError(f"Process failed with exit code {returncode}")

            except (ValueError, TimeoutError) as e:
                error_msg = str(e)
                last_stderr_text = stderr_text

                # Make sure stderr_task is cleaned up if still running
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass

                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed for {process_name}: {error_msg}")
                if stderr_text:
                    logging.debug(f"STDERR ({process_name}): {stderr_text}")

                # Check if it's an authentication error
                # gallery-dl: only exit code 16 (AuthRequired/AuthenticationError/AuthorizationError)
                stderr_lower = stderr_text.lower()
                is_auth_error = (
                    returncode == 16
                    or bool(re.search(r'login|log in|logged-in|accounts/login|audience|restrict|\bage\b|age-', stderr_lower))
                    or 'use --cookies' in stderr_lower
                    or bool(re.search(r'(?:http\s*(?:error\s*)?|\b)401\b', stderr_lower))
                    or 'sign in to confirm' in stderr_lower
                )
                if is_auth_error:
                    return {
                        'success': False,
                        'error': 'Authentication required',
                        'details': 'This content needs a logged-in session. Ask the admin to add cookies for this platform.',
                        'platform': process_name,
                        'returncode': returncode
                    }

                # Check for 404 or content not found
                if '404' in stderr_text or 'not found' in stderr_text.lower():
                    return {
                        'success': False,
                        'error': 'Content not found',
                        'details': 'The content may have been deleted or is private',
                        'platform': process_name,
                        'returncode': returncode
                    }

                # Exit code 64 = extractor failure (gallery-dl)
                if returncode == 64:
                    return {
                        'success': False,
                        'error': 'Platform not supported or restricted',
                        'details': 'This video may require login, be private, or from an unsupported format',
                        'platform': process_name,
                        'returncode': 64
                    }

                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(stderr_text):
                    wait_time = 2 ** attempt
                    logging.info(f"⏳ Retrying {process_name} in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                if stderr_text:
                    tail = sanitize_string(stderr_text[-500:])
                    logging.warning(f"Final failure for {process_name} after {attempt}/{max_attempts} attempts. Stderr tail: {tail}")

                return {
                    'success': False,
                    'error': f'Download failed (code {returncode if returncode is not None else "?"})',
                    'platform': process_name
                }

            except Exception as e:
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass
                logging.error(f"❌ Execution error: {e}")
                return {
                    'success': False,
                    'error': 'Internal error during download',
                    'platform': process_name
                }

        if last_stderr_text:
            tail = sanitize_string(last_stderr_text[-500:])
            logging.warning(f"Final failure for {process_name} after {max_attempts} attempts. Stderr tail: {tail}")

        return {
            'success': False,
            'error': 'Max retry attempts reached',
            'platform': process_name
        }
