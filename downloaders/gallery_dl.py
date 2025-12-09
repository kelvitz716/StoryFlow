"""Gallery-dl wrapper for Instagram, TikTok, Twitter, and Facebook downloads."""

import os
import time
import asyncio
import logging
from typing import Dict, Optional


class GalleryDLDownloader:
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies'):
        """
        Initialize gallery-dl downloader.
        
        Args:
            output_path: Directory to save downloaded media
            cookie_path: Directory containing cookie files
        """
        self.output_path = output_path
        self.cookie_path = cookie_path
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(cookie_path, exist_ok=True)
    
    async def download(self, url: str, platform: str, user_id: Optional[str] = None) -> Dict:
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
            result = await self._execute_with_retry(command)
            
            if result['success']:
                # Find new files
                files_after = self._get_download_files()
                new_files = [f for f in files_after if f not in files_before]
                
                if new_files:
                    logging.info(f"✅ {platform} content downloaded successfully! ({len(new_files)} files)")
                    result['files'] = new_files
                else:
                    # No new files - but gallery-dl succeeded, so content might be cached
                    # Return all existing files in the download directory
                    all_files = list(files_after)
                    if all_files:
                        logging.info(f"📂 Content already downloaded, returning {len(all_files)} cached file(s)")
                        result['files'] = all_files
                    else:
                        logging.warning(f"⚠️ No files found in download directory")
                        result['files'] = []
                        result['message'] = "No content available"
                    
                return result
            else:
                # gallery-dl failed - try yt-dlp as fallback for supported platforms
                fallback_platforms = ["Facebook", "TikTok", "Twitter"]
                if platform in fallback_platforms:
                    logging.info(f"🔄 Trying yt-dlp fallback for {platform}...")
                    fallback_result = await self._download_with_ytdlp(url, platform, user_id, files_before)
                    if fallback_result['success']:
                        return fallback_result
                
                logging.error(f"❌ Download failed: {result.get('error')}")
                return result
                
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
    
    async def _download_with_ytdlp(self, url: str, platform: str, user_id: Optional[str], files_before: set) -> Dict:
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
            cookie_file = os.path.join(self.cookie_path, f"{platform.lower()}_{user_id}.txt") if user_id else None
            if cookie_file and os.path.exists(cookie_file):
                logging.info(f"🍪 Using {platform} cookies with yt-dlp")
                command.extend(['--cookies', cookie_file])
            
            command.append(url)
            
            logging.info(f"📥 Downloading {platform} content via yt-dlp...")
            
            # Run yt-dlp asynchronously
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
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
                    return {
                        'success': False,
                        'error': 'No files downloaded',
                        'platform': platform
                    }
            else:
                stderr_text = stderr.decode().strip()
                logging.warning(f"⚠️ yt-dlp failed: {stderr_text[:200]}")
                return {
                    'success': False,
                    'error': 'yt-dlp download failed',
                    'stderr': stderr_text,
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
        
        # Add cookie support for Instagram
        if platform == "Instagram" and user_id:
            cookie_file = os.path.join(self.cookie_path, f"instagram_{user_id}.txt")
            if os.path.exists(cookie_file):
                logging.info(f"🍪 Using Instagram cookies for authentication")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No Instagram cookie file found for user {user_id}")
        
        # Check for general Instagram cookies
        elif platform == "Instagram":
            default_cookie = os.path.join(self.cookie_path, "instagram.txt")
            if os.path.exists(default_cookie):
                logging.info("🍪 Using default Instagram cookies")
                command.extend(['--cookies', default_cookie])
        
        # Add cookie support for Facebook
        if platform == "Facebook" and user_id:
            cookie_file = os.path.join(self.cookie_path, f"facebook_{user_id}.txt")
            if os.path.exists(cookie_file):
                logging.info(f"🍪 Using Facebook cookies for authentication")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No Facebook cookie file found for user {user_id}")
        
        # Check for general Facebook cookies
        elif platform == "Facebook":
            default_cookie = os.path.join(self.cookie_path, "facebook.txt")
            if os.path.exists(default_cookie):
                logging.info("🍪 Using default Facebook cookies")
                command.extend(['--cookies', default_cookie])
        
        # Add URL as final argument
        command.append(url)
        
        return command
    
    async def _execute_with_retry(self, command: list, max_attempts: int = 3) -> Dict:
        """Execute command with retry logic (Async)."""
        for attempt in range(1, max_attempts + 1):
            try:
                # Async subprocess execution
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Wait for completion with timeout
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
                    
                    stdout_text = stdout.decode()
                    stderr_text = stderr.decode()
                    
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
                        'platform': 'gallery-dl'
                    }
                
                # Exit code 64 = extractor failure
                if 'returncode' in locals() and process.returncode == 64:
                    return {
                        'success': False,
                        'error': 'Platform not supported or restricted',
                        'details': 'This video may require login, be private, or from an unsupported format',
                        'stderr': stderr_content,
                        'platform': 'gallery-dl'
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
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies'):
        """
        Initialize gallery-dl downloader.
        
        Args:
            output_path: Directory to save downloaded media
            cookie_path: Directory containing cookie files
        """
        self.output_path = output_path
        self.cookie_path = cookie_path
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(cookie_path, exist_ok=True)
    
    def download(self, url: str, platform: str, user_id: Optional[str] = None) -> Dict:
        """
        Download media using gallery-dl with optional cookie support.
        
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
            
            # Execute gallery-dl with retry logic
            result = self._execute_with_retry(command)
            
            if result['success']:
                # Find new files
                files_after = self._get_download_files()
                new_files = [f for f in files_after if f not in files_before]
                
                if new_files:
                    logging.info(f"✅ {platform} content downloaded successfully! ({len(new_files)} files)")
                    result['files'] = new_files
                else:
                    # No new files - but gallery-dl succeeded, so content might be cached
                    # Return all existing files in the download directory
                    all_files = list(files_after)
                    if all_files:
                        logging.info(f"📂 Content already downloaded, returning {len(all_files)} cached file(s)")
                        result['files'] = all_files
                    else:
                        logging.warning(f"⚠️ No files found in download directory")
                        result['files'] = []
                        result['message'] = "No content available"
                    
                return result
            else:
                # gallery-dl failed - try yt-dlp as fallback for supported platforms
                fallback_platforms = ["Facebook", "TikTok", "Twitter"]
                if platform in fallback_platforms:
                    logging.info(f"🔄 Trying yt-dlp fallback for {platform}...")
                    fallback_result = self._download_with_ytdlp(url, platform, user_id, files_before)
                    if fallback_result['success']:
                        return fallback_result
                
                logging.error(f"❌ Download failed: {result.get('error')}")
                return result
                
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
    
    def _download_with_ytdlp(self, url: str, platform: str, user_id: Optional[str], files_before: set) -> Dict:
        """
        Fallback download using yt-dlp for platforms where gallery-dl fails.
        
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
            cookie_file = os.path.join(self.cookie_path, f"{platform.lower()}_{user_id}.txt") if user_id else None
            if cookie_file and os.path.exists(cookie_file):
                logging.info(f"🍪 Using {platform} cookies with yt-dlp")
                command.extend(['--cookies', cookie_file])
            
            command.append(url)
            
            logging.info(f"📥 Downloading {platform} content via yt-dlp...")
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
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
                    return {
                        'success': False,
                        'error': 'No files downloaded',
                        'platform': platform
                    }
            else:
                logging.warning(f"⚠️ yt-dlp failed: {result.stderr[:200]}")
                return {
                    'success': False,
                    'error': 'yt-dlp download failed',
                    'stderr': result.stderr,
                    'platform': platform
                }
                
        except subprocess.TimeoutExpired:
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
        
        # Add cookie support for Instagram
        if platform == "Instagram" and user_id:
            cookie_file = os.path.join(self.cookie_path, f"instagram_{user_id}.txt")
            if os.path.exists(cookie_file):
                logging.info(f"🍪 Using Instagram cookies for authentication")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No Instagram cookie file found for user {user_id}")
        
        # Check for general Instagram cookies
        elif platform == "Instagram":
            default_cookie = os.path.join(self.cookie_path, "instagram.txt")
            if os.path.exists(default_cookie):
                logging.info("🍪 Using default Instagram cookies")
                command.extend(['--cookies', default_cookie])
        
        # Add cookie support for Facebook
        if platform == "Facebook" and user_id:
            cookie_file = os.path.join(self.cookie_path, f"facebook_{user_id}.txt")
            if os.path.exists(cookie_file):
                logging.info(f"🍪 Using Facebook cookies for authentication")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No Facebook cookie file found for user {user_id}")
        
        # Check for general Facebook cookies
        elif platform == "Facebook":
            default_cookie = os.path.join(self.cookie_path, "facebook.txt")
            if os.path.exists(default_cookie):
                logging.info("🍪 Using default Facebook cookies")
                command.extend(['--cookies', default_cookie])
        
        # Add URL as final argument
        command.append(url)
        
        return command
    
    def _execute_with_retry(self, command: list, max_attempts: int = 3) -> Dict:
        """Execute command with retry logic."""
        for attempt in range(1, max_attempts + 1):
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=300  # 5 minutes timeout
                )
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'platform': 'gallery-dl'
                }
                
            except subprocess.CalledProcessError as e:
                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed")
                logging.debug(f"Exit code: {e.returncode}")
                logging.debug(f"STDERR: {e.stderr}")
                
                # Check if it's an authentication error
                if 'login' in e.stderr.lower() or 'authentication' in e.stderr.lower():
                    return {
                        'success': False,
                        'error': 'Authentication required',
                        'details': 'Please provide cookies.txt file for Instagram',
                        'stderr': e.stderr,
                        'platform': 'gallery-dl'
                    }
                
                # Check for 404 or content not found
                if '404' in e.stderr or 'not found' in e.stderr.lower():
                    return {
                        'success': False,
                        'error': 'Content not found',
                        'details': 'The content may have been deleted or is private',
                        'stderr': e.stderr,
                        'platform': 'gallery-dl'
                    }
                
                # Exit code 64 = extractor failure (common with Facebook, some TikTok)
                if e.returncode == 64:
                    return {
                        'success': False,
                        'error': 'Platform not supported or restricted',
                        'details': 'This video may require login, be private, or from an unsupported format',
                        'stderr': e.stderr,
                        'platform': 'gallery-dl'
                    }
                
                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(e.stderr):
                    wait_time = 2 ** attempt  # Exponential backoff
                    logging.info(f"⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                return {
                    'success': False,
                    'error': f'Download failed (code {e.returncode})',
                    'stderr': e.stderr,
                    'platform': 'gallery-dl'
                }
                
            except subprocess.TimeoutExpired:
                logging.error("❌ Timeout after 5 minutes")
                return {
                    'success': False,
                    'error': 'Download timeout',
                    'details': 'Process exceeded 5 minute limit',
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
