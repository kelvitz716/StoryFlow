"""Gallery-dl wrapper for Instagram, TikTok, Twitter, and Facebook downloads."""

import os
import time
import asyncio
import logging
from typing import Dict, Optional, Callable


class GalleryDLDownloader:
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies', admin_id: Optional[str] = None):
        """
        Initialize gallery-dl downloader.
        
        Args:
            output_path: Directory to save downloaded media
            cookie_path: Directory containing cookie files
            admin_id: Admin User ID for fallback cookies
        """
        self.output_path = output_path
        self.cookie_path = cookie_path
        self.admin_id = admin_id
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(cookie_path, exist_ok=True)
    
    async def download(self, url: str, platform: str, user_id: Optional[str] = None, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Download media using gallery-dl with optional cookie support (Async).
        
        Args:
            url: Media URL
            platform: Platform name (Instagram, TikTok, etc.)
            user_id: User ID for cookie lookup (optional)
            
        Returns:
            Dict containing status and download information
        """
        try:
            # Get list of files before download
            files_before = self._get_download_files()
            
            command = self._build_command(url, platform, user_id)
            
            logging.info(f"📥 Downloading {platform} content via gallery-dl...")
            logging.debug(f"Command: {' '.join(command)}")
            
            # Execute gallery-dl with retry logic (Async)
            result = await self._execute_with_retry(command, progress_callback=progress_callback)
            
            if result['success']:
                # Find new files
                files_after = self._get_download_files()
                new_files = [f for f in files_after if f not in files_before]
                
                if new_files:
                    logging.info(f"✅ {platform} content downloaded successfully! ({len(new_files)} files)")
                    result['files'] = new_files
                    return result
                
                # Check for cached files (if any were already in the folder)
                all_files = list(files_after)
                if all_files:
                    logging.info(f"📂 Content already downloaded, returning {len(all_files)} cached file(s)")
                    result['files'] = all_files
                    return result
                
                logging.warning(f"⚠️ No files found after gallery-dl success.")
            
            # If we are here, it's either result['success'] is False OR it's True but no files were found.
            # Check for partial success (files downloaded despite error)
            files_after = self._get_download_files()
            new_files = [f for f in files_after if f not in files_before]
            
            if new_files:
                # TikTok specific: Images often download fine but audio fails. Treat this as success/feature.
                logging.info(f"✅ {platform} images downloaded successfully (despite stderr)")
                result['success'] = True
                result['files'] = new_files
                result['message'] = "Downloads completed (with some errors)"
                return result
                
            # Try yt-dlp as fallback for supported platforms
            fallback_platforms = ["Facebook", "TikTok", "Twitter", "Snapchat", "Instagram"]
            if platform in fallback_platforms:
                logging.info(f"🔄 Trying yt-dlp fallback for {platform}...")
                fallback_result = await self._download_with_ytdlp(url, platform, user_id, files_before)
                if fallback_result and fallback_result['success']:
                    return fallback_result
                elif fallback_result:
                    # Return fallback error if we tried it
                    logging.warning(f"⚠️ Fallback failed: {fallback_result.get('error')}")
                    return fallback_result
            
            logging.error(f"❌ Download failed: {result.get('error') if result else 'Unknown error'}")
            return result or {'success': False, 'error': 'Unknown failure', 'platform': platform}

                
        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {
                'success': False,
                'error': 'Unexpected error',
                'details': str(e),
                'platform': platform
            }
    
    def _get_download_files(self) -> set:
        """Get set of all files currently in download directory."""
        files = set()
        for root, dirs, filenames in os.walk(self.output_path):
            for filename in filenames:
                if not filename.startswith('.'):  # Skip hidden files
                    files.add(os.path.join(root, filename))
        return files
    
    async def _download_with_ytdlp(self, url: str, platform: str, user_id: Optional[str], files_before: set, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Fallback download using yt-dlp for platforms where gallery-dl fails (Async).
        
        Args:
            url: Media URL
            platform: Platform name
            user_id: User ID for cookie lookup
            files_before: Set of files before download
            
        Returns:
            Dict with download result
        """
        try:
            # Build yt-dlp command
            output_template = os.path.join(self.output_path, f'{platform.lower()}', '%(id)s.%(ext)s')
            command = [
                'yt-dlp',
                '-o', output_template,
                '--no-warnings',
                '--no-playlist',
            ]
            
            # Add cookies if available
            cookie_file = self._get_cookie_file(platform, user_id)
            if cookie_file:
                logging.info(f"🍪 Using {platform} cookies with yt-dlp: {os.path.basename(cookie_file)}")
                command.extend(['--cookies', cookie_file])
            
            command.append(url)
            
            # Run yt-dlp asynchronously using the shared execution method
            # This handles streaming output and progress parsing
            logging.info(f"📥 Downloading {platform} content via yt-dlp...")
            
            # Re-use _execute_with_retry since it now supports streaming and progress
            result = await self._execute_with_retry(command, progress_callback=progress_callback)
            
            if result['success']:
                # Find new files
                files_after = self._get_download_files()
                new_files = [f for f in files_after if f not in files_before]
                
                if new_files:
                    logging.info(f"✅ {platform} content downloaded via yt-dlp! ({len(new_files)} files)")
                    return {
                        'success': True,
                        'files': new_files,
                        'platform': platform
                    }
                else:
                    # If yt-dlp succeeded but no *new* files, content might be cached/already downloaded
                    return {
                        'success': True,
                        'files': [], # Caller handles empty file check if needed, or we check existing
                        'message': "No new files found",
                        'platform': platform
                    }
            else:
                 return {
                    'success': False,
                    'error': result.get('stderr', 'yt-dlp download failed'),
                    'platform': platform
                }
                
        except asyncio.TimeoutError:
            return {
                'success': False,
                'error': 'Download timeout',
                'platform': platform
            }
        except FileNotFoundError:
            logging.warning("⚠️ yt-dlp not installed, skipping fallback")
            return {
                'success': False,
                'error': 'yt-dlp not installed',
                'platform': platform
            }
        except Exception as e:
            logging.error(f"yt-dlp error: {e}")
            return {
                'success': False,
                'error': str(e),
                'platform': platform
            }
    
    def _build_command(self, url: str, platform: str, user_id: Optional[str]) -> list:
        """Build gallery-dl command with appropriate options."""
        command = [
            'gallery-dl',
            '-d', self.output_path,
            '--no-mtime',  # Don't set file modification time
        ]
        
        # Add cookie support
        cookie_file = self._get_cookie_file(platform, user_id)
        if cookie_file:
            logging.info(f"🍪 Using {platform} cookies: {os.path.basename(cookie_file)}")
            command.extend(['--cookies', cookie_file])
        else:
            # Only warn if it's a platform that typically needs cookies
            if platform in ["Instagram", "Facebook", "TikTok"]:
                logging.debug(f"⚠️ No cookies found for {platform}")

        # Add URL as final argument
        command.append(url)
        
        return command

    def _get_cookie_file(self, platform: str, user_id: Optional[str]) -> Optional[str]:
        """
        Get the best available cookie file:
        1. Specific user cookies
        2. Admin fallback cookies
        3. Legacy default cookies
        """
        platform_lower = platform.lower()
        
        # 1. Specific User Cookies
        if user_id:
            user_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{user_id}.txt")
            if os.path.exists(user_cookie):
                return user_cookie
        
        # 2. Admin Fallback
        if self.admin_id and self.admin_id != user_id:
            admin_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{self.admin_id}.txt")
            if os.path.exists(admin_cookie):
                logging.info(f"💡 using Admin cookies for {platform} (Fallback)")
                return admin_cookie

        # 3. Legacy Default
        default_cookie = os.path.join(self.cookie_path, f"{platform_lower}.txt")
        if os.path.exists(default_cookie):
            return default_cookie
            
        return None
    
    async def _execute_with_retry(self, command: list, max_attempts: int = 3, progress_callback: Optional[Callable] = None) -> Dict:
        """Execute command with retry logic (Async)."""
        for attempt in range(1, max_attempts + 1):
            try:
                # Async subprocess execution
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Stream output for progress updates
                stdout_lines = []
                stderr_lines = []
                
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
                                    # Extract percentage
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
                                
                                # gallery-dl style (usually just filenames)
                                elif line_text.startswith('#'):
                                    # Info lines
                                    pass
                                elif "." in line_text and "/" in line_text:
                                    # Just say downloading...
                                    progress_callback(f"Downloading: {os.path.basename(line_text)}")

                    # Read remaining strings
                    stderr_data = await process.stderr.read()
                    
                    stdout_text = "\n".join(stdout_lines)
                    stderr_text = stderr_data.decode()
                    
                    await process.wait()
                    
                    if process.returncode == 0:
                        return {
                            'success': True,
                            'stdout': stdout_text,
                            'stderr': stderr_text,
                            'platform': 'gallery-dl'
                        }
                    else:
                        raise ValueError(f"Process failed using status {process.returncode}")
                        
                except asyncio.TimeoutError:
                    process.kill()
                    raise TimeoutError("Process exceeded 5 minutes")
                
            except (ValueError, TimeoutError) as e:
                # Need to handle non-process errors or non-zero exits here
                # Re-parse stderr from the failed process call if it was a non-zero exit
                error_msg = str(e)
                stderr_content = stderr_text if 'stderr_text' in locals() else ""
                
                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed")
                if stderr_content:
                    logging.debug(f"STDERR: {stderr_content}")
                
                # Check if it's an authentication error
                if 'login' in stderr_content.lower() or 'authentication' in stderr_content.lower():
                    return {
                        'success': False,
                        'error': 'Authentication required',
                        'details': 'Please provide cookies.txt file for Instagram',
                        'stderr': stderr_content,
                        'platform': 'gallery-dl'
                    }
                
                # Check for 404 or content not found
                if '404' in stderr_content or 'not found' in stderr_content.lower():
                    return {
                        'success': False,
                        'error': 'Content not found',
                        'details': 'The content may have been deleted or is private',
                        'stderr': stderr_content,
                        'platform': 'gallery-dl',
                        'returncode': process.returncode if 'process' in locals() else None
                    }
                
                # Exit code 64 = extractor failure
                if 'returncode' in locals() and process.returncode == 64:
                    return {
                        'success': False,
                        'error': 'Platform not supported or restricted',
                        'details': 'This video may require login, be private, or from an unsupported format',
                        'stderr': stderr_content,
                        'platform': 'gallery-dl',
                        'returncode': 64
                    }

                # Exit code 4 = No Downloads / Nothing found (User has no stories)
                if 'returncode' in locals() and process.returncode == 4:
                    return {
                        'success': False,
                        'error': 'No active stories/spotlights found',
                        'details': 'The user has no content available or it is private',
                        'stderr': stderr_content,
                        'platform': 'gallery-dl',
                        'returncode': 4
                    }
                
                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(stderr_content):
                    wait_time = 2 ** attempt  # Exponential backoff
                    logging.info(f"⏳ Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                
                return {
                    'success': False,
                    'error': f'Download failed (code {process.returncode if "process" in locals() else "?"})',
                    'stderr': stderr_content,
                    'platform': 'gallery-dl'
                }
                
            except Exception as e:
                logging.error(f"❌ Execution error: {e}")
                return {
                    'success': False,
                    'error': f'Internal error: {e}',
                    'platform': 'gallery-dl'
                }
        
        return {
            'success': False,
            'error': 'Max retry attempts reached',
            'platform': 'gallery-dl'
        }
    
    def _is_retryable_error(self, stderr: str) -> bool:
        """Check if error is retryable."""
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
