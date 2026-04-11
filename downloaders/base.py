"""Base class for media downloaders providing shared networking and parsing functionality."""

import os
import asyncio
import logging
from typing import Optional, Callable, Dict

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
        """Execute command with unified async retry logic, stdout parsing, and timeouts."""
        for attempt in range(1, max_attempts + 1):
            process = None
            stderr_text = ""
            returncode = None
            try:
                # Async subprocess execution
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Stream output for progress updates
                stdout_lines = []
                
                try:
                    while True:
                        # Wait for line with timeout
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=300)
                        if not line:
                            break
                            
                        line_text = line.decode().strip()
                        if line_text:
                            stdout_lines.append(line_text)
                            
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
                                    except:
                                        pass
                                
                                # gallery-dl style (usually just filenames outputted)
                                elif line_text.startswith('#'):
                                    pass
                                elif "." in line_text and "/" in line_text:
                                    progress_callback(f"Downloading: {os.path.basename(line_text)}")

                    # Gather remaining streams
                    stderr_data = await process.stderr.read()
                    
                    stdout_text = "\n".join(stdout_lines)
                    stderr_text = stderr_data.decode()
                    
                    await process.wait()
                    returncode = process.returncode
                    
                    if returncode == 0:
                        return {
                            'success': True,
                            'stdout': stdout_text,
                            'stderr': stderr_text,
                            'platform': process_name
                        }
                    else:
                        raise ValueError(f"Process failed using status {process.returncode}")
                        
                except asyncio.TimeoutError:
                    if process:
                        try:
                            process.kill()
                        except:
                            pass
                    raise TimeoutError("Process exceeded 5 minutes")
                
            except (ValueError, TimeoutError) as e:
                error_msg = str(e)
                stderr_content = stderr_text
                
                if process is not None and returncode is None:
                    returncode = process.returncode
                
                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed for {process_name}")
                if stderr_content:
                    logging.debug(f"STDERR ({process_name}): {stderr_content}")
                
                # Check if it's an authentication error
                if 'login' in stderr_content.lower() or 'authentication' in stderr_content.lower():
                    return {
                        'success': False,
                        'error': 'Authentication required',
                        'details': 'Please provide cookies for this platform',
                        'stderr': stderr_content,
                        'platform': process_name
                    }
                
                # Check for 404 or content not found
                if '404' in stderr_content or 'not found' in stderr_content.lower():
                    return {
                        'success': False,
                        'error': 'Content not found',
                        'details': 'The content may have been deleted or is private',
                        'stderr': stderr_content,
                        'platform': process_name,
                        'returncode': returncode
                    }
                
                # Exit code 64 = extractor failure (gallery-dl)
                if returncode == 64:
                    return {
                        'success': False,
                        'error': 'Platform not supported or restricted',
                        'details': 'This video may require login, be private, or from an unsupported format',
                        'stderr': stderr_content,
                        'platform': process_name,
                        'returncode': 64
                    }

                # Exit code 4 = No Downloads / Nothing found
                if returncode == 4:
                    return {
                        'success': False,
                        'error': 'No active stories/spotlights found',
                        'details': 'The user has no content available or it is private',
                        'stderr': stderr_content,
                        'platform': process_name,
                        'returncode': 4
                    }
                
                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(stderr_content):
                    wait_time = 2 ** attempt
                    logging.info(f"⏳ Retrying {process_name} in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                
                return {
                    'success': False,
                    'error': f'Download failed (code {returncode if returncode is not None else "?"})',
                    'stderr': stderr_content,
                    'platform': process_name
                }
                
            except Exception as e:
                logging.error(f"❌ Execution error: {e}")
                return {
                    'success': False,
                    'error': f'Internal error: {e}',
                    'platform': process_name
                }
        
        return {
            'success': False,
            'error': 'Max retry attempts reached',
            'platform': process_name
        }
