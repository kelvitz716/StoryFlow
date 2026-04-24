"""Cookie management for authenticated downloads."""

import os
import shutil
import logging
import re
from typing import Dict, Optional
from datetime import datetime, timezone


class CookieManager:
    """Manage cookie files for authenticated downloads."""
    
    def __init__(self, cookie_path: str = './cookies'):
        """
        Initialize cookie manager.
        
        Args:
            cookie_path: Directory to store cookie files
        """
        self.cookie_path = cookie_path
        os.makedirs(cookie_path, exist_ok=True)
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name to prevent directory traversal (only allow alphanumeric, underscore, and dash)."""
        # Remove any characters that aren't alphanumeric, underscore, or dash
        sanitized = re.sub(r'[^\w\-]', '', name)
        # Fallback to 'unknown' if empty
        return sanitized or 'unknown'

    def save_cookie_file(self, user_id: str, platform: str, file_path: str) -> Dict:
        """
        Save uploaded cookie file for user.
        
        Args:
            user_id: User identifier (e.g., Telegram user ID)
            platform: Platform name (e.g., "instagram")
            file_path: Path to uploaded cookie file
            
        Returns:
            Dict with success status and expiry info
        """
        try:
            # Validate cookie file
            if not self._validate_cookie_file(file_path):
                return {
                    'success': False,
                    'error': 'Invalid cookie file format. Expected Netscape cookie format.'
                }
            
            # Check cookie expiry
            expiry_info = self._get_cookie_expiry(file_path, platform)
            
            # Destination path
            s_platform = self._sanitize_name(platform.lower())
            s_user_id = self._sanitize_name(user_id)
            dest_file = os.path.join(
                self.cookie_path,
                f"{s_platform}_{s_user_id}.txt"
            )
            
            # Copy file
            shutil.copy2(file_path, dest_file)
            
            logging.info(f"✅ Cookie file saved for user {user_id}")
            return {
                'success': True,
                'cookie_file': dest_file,
                'expiry': expiry_info.get('expiry'),
                'expiry_str': expiry_info.get('expiry_str'),
                'is_expired': expiry_info.get('is_expired', False)
            }
            
        except Exception as e:
            logging.error(f"❌ Failed to save cookie file: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _validate_cookie_file(self, file_path: str) -> bool:
        """
        Validate cookie file format (Netscape format).
        
        Args:
            file_path: Path to cookie file
            
        Returns:
            True if valid Netscape cookie file with at least one well-formed entry.
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Must have the Netscape header
            if '# Netscape HTTP Cookie File' not in content:
                return False
            
            # Must have at least one well-formed cookie line (7 tab-separated fields)
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    return True
            
            return False
        except Exception:
            return False
    
    def _get_cookie_expiry(self, file_path: str, platform: str) -> Dict:
        """
        Extract expiry date from session cookie.
        
        Args:
            file_path: Path to cookie file
            platform: Platform name
            
        Returns:
            Dict with expiry info
        """
        try:
            # Session cookie names by platform
            session_cookies = {
                'instagram': 'sessionid',
                'facebook': 'c_user',  # Facebook uses c_user for login state
                'tiktok': 'sessionid_ss',  # TikTok uses sessionid_ss for login state
            }
            
            target_cookie = session_cookies.get(platform.lower(), 'sessionid')
            
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        cookie_name = parts[5]
                        expiry_ts = parts[4]
                        
                        if cookie_name == target_cookie:
                            try:
                                expiry_unix = int(expiry_ts)
                                if expiry_unix == 0:
                                    return {'expiry': None, 'expiry_str': 'Session (browser close)', 'is_expired': False}
                                
                                expiry_date = datetime.fromtimestamp(expiry_unix, tz=timezone.utc)
                                is_expired = expiry_date < datetime.now(tz=timezone.utc)
                                
                                return {
                                    'expiry': expiry_date,
                                    'expiry_str': expiry_date.strftime('%Y-%m-%d %H:%M'),
                                    'is_expired': is_expired
                                }
                            except (ValueError, OSError):
                                pass
            
            return {'expiry': None, 'expiry_str': 'Unknown', 'is_expired': False}
            
        except Exception as e:
            logging.warning(f"Could not parse cookie expiry: {e}")
            return {'expiry': None, 'expiry_str': 'Unknown', 'is_expired': False}
    
    def check_cookie_status(self, user_id: str, platform: str) -> Dict:
        """
        Check if user's cookie is valid and not expired.
        
        Args:
            user_id: User identifier
            platform: Platform name
            
        Returns:
            Dict with status info
        """
        cookie_file = self.get_cookie_file(user_id, platform)
        if not cookie_file:
            return {'exists': False, 'expired': False, 'message': 'No cookie found'}
        
        expiry_info = self._get_cookie_expiry(cookie_file, platform)
        
        if expiry_info.get('is_expired'):
            return {
                'exists': True,
                'expired': True,
                'expiry_str': expiry_info.get('expiry_str'),
                'message': f'Cookie expired on {expiry_info.get("expiry_str")}'
            }
        
        return {
            'exists': True,
            'expired': False,
            'expiry_str': expiry_info.get('expiry_str'),
            'message': f'Valid until {expiry_info.get("expiry_str")}'
        }
    
    def get_cookie_file(self, user_id: str, platform: str) -> Optional[str]:
        """
        Get cookie file path for user if exists.
        
        Args:
            user_id: User identifier
            platform: Platform name
            
        Returns:
            Cookie file path or None if not found
        """
        s_platform = self._sanitize_name(platform.lower())
        s_user_id = self._sanitize_name(user_id)
        cookie_file = os.path.join(
            self.cookie_path,
            f"{s_platform}_{s_user_id}.txt"
        )
        return cookie_file if os.path.exists(cookie_file) else None
    
    def delete_cookie_file(self, user_id: str, platform: str) -> bool:
        """
        Delete cookie file for user.
        
        Args:
            user_id: User identifier
            platform: Platform name
            
        Returns:
            True if deleted, False if not found
        """
        cookie_file = self.get_cookie_file(user_id, platform)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
            logging.info(f"🗑️ Deleted cookie file for user {user_id}")
            return True
        return False
    
    def list_cookies(self, user_id: Optional[str] = None) -> list:
        """
        List all cookie files, optionally filtered by user.
        
        Args:
            user_id: Optional user ID to filter by
            
        Returns:
            List of cookie file info dicts with expiry info
        """
        cookies = []
        try:
            filenames = os.listdir(self.cookie_path)
        except OSError:
            return cookies

        for filename in filenames:
            if not filename.endswith('.txt'):
                continue
            # Expected format: {platform}_{user_id}.txt
            # Skip files that don't match (e.g. 'instagram.txt', '.gitkeep')
            stem = filename[:-4]  # strip .txt
            if '_' not in stem:
                continue
            platform, uid = stem.split('_', 1)
            if not platform or not uid:
                continue
            if user_id is not None and uid != self._sanitize_name(user_id):
                continue
            cookie_path = os.path.join(self.cookie_path, filename)
            expiry_info = self._get_cookie_expiry(cookie_path, platform)
            cookies.append({
                'platform': platform,
                'user_id': uid,
                'path': cookie_path,
                'expiry_str': expiry_info.get('expiry_str', 'Unknown'),
                'is_expired': expiry_info.get('is_expired', False)
            })
        return cookies
