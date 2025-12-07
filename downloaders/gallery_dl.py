"""Gallery-dl wrapper for Instagram, TikTok, Twitter, and Facebook downloads."""

import os
import time
import logging
import subprocess
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
            command = self._build_command(url, platform, user_id)
            
            logging.info(f"📥 Downloading {platform} content via gallery-dl...")
            logging.debug(f"Command: {' '.join(command)}")
            
            # Execute gallery-dl with retry logic
            result = self._execute_with_retry(command)
            
            if result['success']:
                logging.info(f"✅ {platform} content downloaded successfully!")
                return result
            else:
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
                logging.info(f"🍪 Using cookies for authentication")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No cookie file found for user {user_id}")
        
        # Check for general Instagram cookies
        elif platform == "Instagram":
            # Look for default Instagram cookies
            default_cookie = os.path.join(self.cookie_path, "instagram.txt")
            if os.path.exists(default_cookie):
                logging.info("🍪 Using default Instagram cookies")
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
                
                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(e.stderr):
                    wait_time = 2 ** attempt  # Exponential backoff
                    logging.info(f"⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                return {
                    'success': False,
                    'error': f'gallery-dl failed (exit code {e.returncode})',
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
