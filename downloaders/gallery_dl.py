"""Gallery-dl wrapper for Instagram, TikTok, Twitter, and Facebook downloads."""

import os
import re
import asyncio
import logging
from typing import Dict, Optional, Callable
from core.config import _env_int

# Max file size limit from env (applied to both gallery-dl and yt-dlp)
_MAX_FILE_SIZE_MB = _env_int('MAX_FILE_SIZE_MB', 500, 1, 10000)

# Admin cookie fallback is opt-in (item 8).
# Default is disabled to prevent inadvertently sharing admin credentials.
_ALLOW_ADMIN_COOKIE_FALLBACK = os.getenv('ALLOW_ADMIN_COOKIE_FALLBACK', 'false').lower() == 'true'


from downloaders.base import BaseDownloader


def _mask_cookie_filename(filename: Optional[str]) -> str:
    """Mask user_id in cookie filenames (e.g. tiktok_618026357.txt -> tiktok_618***357.txt)."""
    if not filename:
        return ""
    base = os.path.basename(filename)
    if "_" in base and "." in base:
        parts = base.split("_", 1)
        platform_part = parts[0]
        rest = parts[1]
        if "." in rest:
            uid_part, ext = rest.rsplit(".", 1)
            if len(uid_part) > 6:
                masked_uid = f"{uid_part[:3]}***{uid_part[-3:]}"
            else:
                masked_uid = "***"
            return f"{platform_part}_{masked_uid}.{ext}"
    return base


class GalleryDLDownloader(BaseDownloader):
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies', admin_id: Optional[str] = None):
        """
        Initialize gallery-dl downloader.
        
        Args:
            output_path: Directory to save downloaded media
            cookie_path: Directory containing cookie files
            admin_id: Admin User ID for fallback cookies
        """
        super().__init__(output_path)
        self.cookie_path = cookie_path
        self.admin_ids = [aid.strip() for aid in str(admin_id).split(",") if aid.strip()] if admin_id else []
        self.admin_id = self.admin_ids[0] if self.admin_ids else (str(admin_id) if admin_id else None)
        os.makedirs(cookie_path, exist_ok=True)
    
    async def download(self, url: str, platform: str, user_id: Optional[str] = None, job_id: Optional[str] = None, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Download media using gallery-dl with optional cookie support (Async).
        
        Args:
            url: Media URL
            platform: Platform name (Instagram, TikTok, etc.)
            user_id: User ID for cookie lookup (optional)
            job_id: Unique job identifier for directory isolation (optional)
            
        Returns:
            Dict containing status and download information
        """
        try:
            # Determine job-specific output path
            job_output_path = os.path.join(self.output_path, job_id) if job_id else self.output_path
            os.makedirs(job_output_path, exist_ok=True)

            # Get list of files before download (only in this job's folder)
            files_before = self._get_download_files(job_output_path)
            
            cookie_file = self._get_cookie_file(platform, user_id)
            
            # 1. Try download without cookies first
            command = self._build_command(url, platform, user_id, job_output_path, use_cookies=False)
            
            logging.info(f"📥 Downloading {platform} content via gallery-dl...")
            logging.debug(f"Command: {' '.join(command)}")
            
            # Execute gallery-dl with retry logic (Async)
            result = await self._execute_with_retry(command, progress_callback=progress_callback)
            
            # Find new files after gallery-dl attempt
            files_after = self._get_download_files(job_output_path)
            new_files = [f for f in files_after if f not in files_before]
            
            if result['success']:
                if new_files:
                    logging.info(f"✅ {platform} content downloaded successfully! ({len(new_files)} files)")
                    result['files'] = new_files
                    return result
                
                # Check for cached files (if any were already in the folder)
                if files_after:
                    logging.info(f"📂 Found {len(files_after)} files in the job directory")
                    result['files'] = list(files_after)
                    return result
                
                logging.warning(f"⚠️ No files found after gallery-dl success in folder: {job_output_path}")
            
            # Check for partial success (files downloaded despite error)
            if new_files:
                logging.info(f"✅ {platform} images downloaded successfully (despite stderr)")
                result['success'] = True
                result['files'] = new_files
                result['message'] = "Downloads completed (with some errors)"
                return result

            # 2. When download without cookies fails, retry with best available cookie.
            retry_cookie = cookie_file or self._get_any_cookie(platform)
            if retry_cookie:
                logging.info(f"🔄 Retrying {platform} via gallery-dl with cookies: {_mask_cookie_filename(retry_cookie)}...")
                command_with_cookies = self._build_command(url, platform, user_id, job_output_path, use_cookies=True, cookie_override=retry_cookie)
                result = await self._execute_with_retry(command_with_cookies, progress_callback=progress_callback)

                files_after = self._get_download_files(job_output_path)
                new_files = [f for f in files_after if f not in files_before]

                if result['success']:
                    if new_files:
                        logging.info(f"✅ {platform} content downloaded successfully with cookies! ({len(new_files)} files)")
                        result['files'] = new_files
                        return result
                    if files_after:
                        logging.info(f"📂 Found {len(files_after)} files in the job directory")
                        result['files'] = list(files_after)
                        return result

                if new_files:
                    logging.info(f"✅ {platform} images downloaded successfully with cookies")
                    result['success'] = True
                    result['files'] = new_files
                    return result
                
            # 3. If that fails too, retry with yt-dlp (which automatically uses cookies if available)
            fallback_platforms = ["Facebook", "TikTok", "Twitter", "Snapchat", "Instagram", "Generic"]
            if platform in fallback_platforms:
                logging.info(f"🔄 Trying yt-dlp fallback for {platform}...")
                fallback_result = await self._download_with_ytdlp(url, platform, user_id, job_output_path, files_before, progress_callback=progress_callback, cookie_override=retry_cookie)
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
                'details': 'An unexpected error occurred during download',
                'platform': platform
            }
    
    async def _download_with_ytdlp(self, url: str, platform: str, user_id: Optional[str], output_path: str, files_before: set, progress_callback: Optional[Callable] = None, cookie_override: Optional[str] = None) -> Dict:
        """
        Fallback download using yt-dlp for platforms where gallery-dl fails (Async).
        
        Args:
            url: Media URL
            platform: Platform name
            user_id: User ID for cookie lookup
            output_path: Isolated output directory
            files_before: Set of files before request started
            progress_callback: Optional progress callback
            cookie_override: Optional explicit cookie file path to use
            
        Returns:
            Dict with download result
        """
        try:
            # Build yt-dlp command
            # Use specific directory based on platform or direct output_path
            output_template = os.path.join(output_path, '%(id)s.%(ext)s')
            command = [
                'yt-dlp',
                '--no-config',
                '-o', output_template,
                '--no-warnings',
                '--no-playlist',
                '--max-filesize', f'{_MAX_FILE_SIZE_MB}m',
            ]
            
            # Add cookies if available
            cookie_file = cookie_override or self._get_cookie_file(platform, user_id)
            if cookie_file:
                logging.info(f"🍪 Using {platform} cookies with yt-dlp: {_mask_cookie_filename(cookie_file)}")
                command.extend(['--cookies', cookie_file])

            # URL must come after '--' to prevent argument injection
            command.extend(['--', url])
            
            # Run yt-dlp asynchronously using the shared execution method
            # This handles streaming output and progress parsing
            logging.info(f"📥 Downloading {platform} content via yt-dlp...")
            
            # Re-use _execute_with_retry since it now supports streaming and progress
            result = await self._execute_with_retry(command, progress_callback=progress_callback)
            
            if result['success']:
                # Find new files
                files_after = self._get_download_files(output_path)
                
                # Use files_before as baseline to capture all files new since request start, 
                # regardless of which downloader produced them.
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
                return result
                
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
                'error': 'Download failed',
                'details': 'An unexpected error occurred during media extraction',
                'platform': platform
            }
    
    def _build_command(self, url: str, platform: str, user_id: Optional[str], output_path: str, use_cookies: bool = True, cookie_override: Optional[str] = None) -> list:
        """Build gallery-dl command with appropriate options."""
        command = [
            'gallery-dl',
            '-d', output_path,
            '--no-mtime',  # Don't set file modification time
            f'--filesize-max={_MAX_FILE_SIZE_MB}m',
        ]
        
        # Add cookie support
        if use_cookies:
            # Prefer explicit override (e.g., admin/default cookie for retry path)
            cookie_file = cookie_override or self._get_cookie_file(platform, user_id)
            if cookie_file:
                logging.info(f"🍪 Using {platform} cookies: {_mask_cookie_filename(cookie_file)}")
                command.extend(['--cookies', cookie_file])
            else:
                # Only warn if it's a platform that typically needs cookies
                if platform in ["Instagram", "Facebook", "TikTok"]:
                    logging.debug(f"⚠️ No cookies found for {platform}")

        # URL must come after '--' to prevent argument injection
        command.extend(['--', url])
        
        return command

    def _get_any_cookie(self, platform: str) -> Optional[str]:
        """
        Find any available cookie for the platform (admin, default, or first existing),
        to retry downloads that failed without credentials.
        """
        platform_lower = re.sub(r'[^\w\-]', '', platform.lower()) or 'unknown'

        # 1. Admin cookie
        if self.admin_ids:
            for aid in self.admin_ids:
                s_admin = re.sub(r'[^\w\-]', '', str(aid)) or 'unknown'
                admin_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{s_admin}.txt")
                if os.path.exists(admin_cookie):
                    return admin_cookie
        elif self.admin_id:
            s_admin = re.sub(r'[^\w\-]', '', str(self.admin_id)) or 'unknown'
            admin_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{s_admin}.txt")
            if os.path.exists(admin_cookie):
                return admin_cookie

        # 2. Legacy default cookie (e.g. instagram.txt)
        default_cookie = os.path.join(self.cookie_path, f"{platform_lower}.txt")
        if os.path.exists(default_cookie):
            return default_cookie

        # 3. Any available platform cookie in cookie_path
        try:
            prefix = f"{platform_lower}_"
            for fname in sorted(os.listdir(self.cookie_path)):
                if fname.startswith(prefix) and fname.endswith(".txt"):
                    return os.path.join(self.cookie_path, fname)
        except OSError:
            pass

        return None

    def _get_cookie_file(self, platform: str, user_id: Optional[str]) -> Optional[str]:
        """
        Get the best available cookie file:
        1. Specific user cookies
        2. Admin fallback cookies (only when ALLOW_ADMIN_COOKIE_FALLBACK=true)
        3. Legacy default cookies

        Cookie filenames use the same sanitisation as CookieManager to guarantee
        the two code paths resolve identical file paths for any user_id.
        """
        platform_lower = re.sub(r'[^\w\-]', '', platform.lower()) or 'unknown'

        def _sanitize_id(uid: str) -> str:
            """Mirror CookieManager._sanitize_name exactly."""
            return re.sub(r'[^\w\-]', '', uid) or 'unknown'

        # 1. Specific User Cookies
        if user_id:
            s_uid = _sanitize_id(user_id)
            user_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{s_uid}.txt")
            if os.path.exists(user_cookie):
                return user_cookie

        # 2. Admin Fallback — only when explicitly opted in
        if _ALLOW_ADMIN_COOKIE_FALLBACK and self.admin_ids:
            for aid in self.admin_ids:
                if str(aid) != str(user_id):
                    s_admin = _sanitize_id(aid)
                    admin_cookie = os.path.join(self.cookie_path, f"{platform_lower}_{s_admin}.txt")
                    if os.path.exists(admin_cookie):
                        logging.info(f"💡 using Admin cookies for {platform} (Fallback)")
                        return admin_cookie

        # 3. Legacy Default
        default_cookie = os.path.join(self.cookie_path, f"{platform_lower}.txt")
        if os.path.exists(default_cookie):
            return default_cookie

        return None
