"""Cookie management for authenticated downloads."""

import os
import shutil
import logging
from typing import Dict, Optional


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
    
    def save_cookie_file(self, user_id: str, platform: str, file_path: str) -> Dict:
        """
        Save uploaded cookie file for user.
        
        Args:
            user_id: User identifier (e.g., Telegram user ID)
            platform: Platform name (e.g., "instagram")
            file_path: Path to uploaded cookie file
            
        Returns:
            Dict with success status
        """
        try:
            # Validate cookie file
            if not self._validate_cookie_file(file_path):
                return {
                    'success': False,
                    'error': 'Invalid cookie file format. Expected Netscape cookie format.'
                }
            
            # Destination path
            dest_file = os.path.join(
                self.cookie_path,
                f"{platform.lower()}_{user_id}.txt"
            )
            
            # Copy file
            shutil.copy2(file_path, dest_file)
            
            logging.info(f"✅ Cookie file saved for user {user_id}")
            return {
                'success': True,
                'cookie_file': dest_file
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
            True if valid, False otherwise
        """
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                # Basic validation: check for cookie structure
                # Netscape format has tab-separated values
                return '# Netscape HTTP Cookie File' in content or '\t' in content
        except Exception:
            return False
    
    def get_cookie_file(self, user_id: str, platform: str) -> Optional[str]:
        """
        Get cookie file path for user if exists.
        
        Args:
            user_id: User identifier
            platform: Platform name
            
        Returns:
            Cookie file path or None if not found
        """
        cookie_file = os.path.join(
            self.cookie_path,
            f"{platform.lower()}_{user_id}.txt"
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
            List of cookie file info dicts
        """
        cookies = []
        for filename in os.listdir(self.cookie_path):
            if filename.endswith('.txt'):
                parts = filename[:-4].split('_', 1)  # Remove .txt and split
                if len(parts) == 2:
                    platform, uid = parts
                    if user_id is None or uid == user_id:
                        cookies.append({
                            'platform': platform,
                            'user_id': uid,
                            'path': os.path.join(self.cookie_path, filename)
                        })
        return cookies
