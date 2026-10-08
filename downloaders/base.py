"""Base class for media downloaders providing shared networking and parsing functionality."""

import os
import signal
import asyncio
import logging
from collections import deque
from typing import Optional, Callable, Dict

# Wall-clock timeout for every subprocess call (seconds).
_DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT_SECONDS', '600'))

# Maximum stderr tail to keep in memory (bytes). Prevents OOM on a phone.
_STDERR_TAIL_BYTES = 65_536  # 64 KB

# Maximum stdout lines/bytes to keep in memory (item 1).
_STDOUT_MAX_LINES = 200
_STDOUT_MAX_BYTES = 65_536  # 64 KB

# Pipe buffer size — 1 MB avoids ValueError on very long gallery-dl JSON lines.
_PIPE_LIMIT = 1_048_576  # 1 MB


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
            'try again'
        ]
        stderr_lower = stderr.lower()
        return any(keyword in stderr_lower for keyword in retryable_keywords)

    async def _execute_with_retry(self, command: list, process_name: str = "subprocess", max_attempts: int = 3, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Execute command with unified async retry logic, concurrent stderr drain,
        wall-clock timeout, and process-group cleanup.

        Key safety properties (item 4):
        - start_new_session=True: subprocess gets its own process group so we can
          killpg the whole tree on timeout.
        - limit=_PIPE_LIMIT: prevents ValueError on very long stdout lines
          (e.g. gallery-dl JSON output). ValueError is caught and treated as a
          regular line read error rather than crashing the job.
        - Concurrent stderr drain: _drain_stderr runs as a task alongside the
          stdout readline loop. Keeps only the last 64 KB to protect RAM.
        - Wall-clock timeout (DOWNLOAD_TIMEOUT_SECONDS, default 600 s): on
          expiry the whole process group is killed and the drain task is
          cancelled.
        - Raw stderr is NEVER returned in result dicts; only generic messages
          are surfaced to callers. Full stderr is logged at DEBUG level.
        """
        for attempt in range(1, max_attempts + 1):
            process = None
            stderr_task = None
            stderr_text = ""
            returncode = None
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
                                    # yt-dlp style: [download]  23.5% of ...
                                    if "[download]" in line_text and "%" in line_text:
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

                                    # gallery-dl style (usually file paths)
                                    elif line_text.startswith('#'):
                                        pass
                                    elif "." in line_text and "/" in line_text:
                                        progress_callback("Fetching media files...")

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

                stdout_text = "\n".join(stdout_lines)

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

                # Make sure stderr_task is cleaned up if still running
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    try:
                        await stderr_task
                    except asyncio.CancelledError:
                        pass

                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed for {process_name}: {error_msg}")
                # Check if it's an authentication / login required error
                # Note: gallery-dl exit code 4 is HttpError (401 Unauthorized / 403 Forbidden / Login redirect)
                is_auth_error = (
                    returncode == 4
                    or 'login' in stderr_text.lower()
                    or 'authentication' in stderr_text.lower()
                    or 'cookie' in stderr_text.lower()
                    or 'sign in' in stderr_text.lower()
                    or 'unauthorized' in stderr_text.lower()
                    or 'forbidden' in stderr_text.lower()
                    or 'redirect' in stderr_text.lower()
                )
                if is_auth_error:
                    return {
                        'success': False,
                        'error': f'Login required for {process_name}. Please upload cookies via /start -> Manage Cookies',
                        'details': 'Login cookies are required to download content from this platform',
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

        return {
            'success': False,
            'error': 'Max retry attempts reached',
            'platform': process_name
        }
