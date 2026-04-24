"""Snapchat story downloader using SnapStory DL API."""

import os
import time
import logging
import requests
import asyncio
from typing import Dict, List, Optional

from core.rate_limiter import RateLimiter
from core.storage import is_storage_critical


from core.platform import extract_snapchat_username
from core.security import sanitize_filename

from downloaders.base import BaseDownloader

class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads using SnapStory DL API."""
    
    def __init__(self, api_base_url: str, output_path: str = './downloads'):
        """
        Initialize Snapchat downloader.
        
        Args:
            api_base_url: Base URL for SnapStory DL API
            output_path: Directory to save downloaded media
        """
        super().__init__(output_path)
        self.api_base_url = api_base_url.rstrip('/')
        self.rate_limiter = RateLimiter(
            max_requests=int(os.getenv('MAX_REQUESTS_PER_MINUTE', 30))
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StoryFlow/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    async def download(self, url: str, user_id: Optional[str] = None, job_id: Optional[str] = None) -> Dict:
        """
        Adapter method for Queue compatibility.
        
        Args:
            url: Snapchat URL
            user_id: Telegram user ID
            job_id: Unique job identifier for directory isolation
        """
        # Spotlight links are public and might be handled differently, 
        # but for now we try to extract username or handle special cases
        if "/spotlight/" in url:
             # Spotlight usually requires gallery-dl as per previous logic in bot
             # But if we are here, we are using SnapchatDownloader.
             # If SnapchatDownloader doesn't support Spotlight, we should fail or fallback.
             # Ideally, the bot routing should have sent this to gallery-dl.
             # However, let's assume this downloader is for User Stories.
             pass

        username = extract_snapchat_username(url)
        if not username:
            return {
                'success': False,
                'error': 'Could not extract username from Snapchat URL',
                'platform': 'Snapchat'
            }
            
        # Run sync method in executor effectively (though here we just call it since it uses requests)
        # Ideally we should run this in a thread if it blocks, but requests is blocking.
        # Given the existing code structure, we can wrap it or just call it if it's fast enough.
        # But wait, download_stories is synchronous (uses requests).
        # We should make this async or run in executor.
        
        # Simple fix: wrap in asyncio.to_thread for Py3.9+ or run_in_executor
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.download_stories, username, job_id)
    
    def download_stories(self, username: str, job_id: Optional[str] = None) -> Dict:
        """
        Download all Snapchat stories for a username.
        
        Args:
            username: Snapchat username
            job_id: Unique job identifier for directory isolation
            
        Returns:
            Dict containing status and download information
        """
        self.rate_limiter.wait_if_needed()
        
        # Determine job-specific output path
        job_output_path = os.path.join(self.output_path, job_id) if job_id else self.output_path
        os.makedirs(job_output_path, exist_ok=True)
        
        try:
            # Fetch story metadata from API
            logging.info(f"📡 Fetching stories for @{username}...")
            stories_data = self._fetch_stories(username)
            
            if not stories_data.get('status'):
                error_msg = stories_data.get('message', 'Unknown API error')
                return {
                    'success': False,
                    'error': error_msg,
                    'platform': 'Snapchat'
                }
            
            stories = stories_data.get('data', [])
            count = stories_data.get('count', len(stories))
            
            if count == 0:
                return {
                    'success': False,
                    'platform': 'Snapchat',
                    'username': username,
                    'error': 'No active public stories found',
                    'files': []
                }
            
            logging.info(f"📸 Found {count} stories for @{username}")
            
            # Download each story
            downloaded_files = []
            for i, story in enumerate(stories, 1):
                media_url = story.get('mediaUrl')
                media_type = story.get('mediaType', 0)  # 0=image, 1=video
                timestamp = story.get('timestamp', '')
                
                if not media_url:
                    logging.warning(f"⚠️ Story {i} has no media URL, skipping")
                    continue
                
                filename = self._download_media(
                    media_url=media_url,
                    username=username,
                    index=i,
                    media_type=media_type,
                    timestamp=timestamp,
                    output_path=job_output_path
                )
                
                if filename:
                    downloaded_files.append(filename)
                    logging.info(f"✅ Downloaded story {i}/{count}: {os.path.basename(filename)}")
                    
                    # Security/Stability check: stop if storage hits critical levels during bulk download
                    is_critical, current_usage = is_storage_critical(job_output_path, threshold=90.0)
                    if is_critical:
                        logging.warning(f"⚠️ Storage threshold reached ({current_usage}%). Stopping download for @{username}.")
                        return {
                            'success': True,
                            'platform': 'Snapchat',
                            'username': username,
                            'total_stories': count,
                            'downloaded': len(downloaded_files),
                            'files': downloaded_files,
                            'message': f"Partially completed. Storage threshold reached ({current_usage}%)."
                        }
            
            return {
                'success': True,
                'platform': 'Snapchat',
                'username': username,
                'total_stories': count,
                'downloaded': len(downloaded_files),
                'files': downloaded_files
            }
            
        except requests.exceptions.HTTPError as e:
            logging.error(f"❌ HTTP Error {e.response.status_code}: {e.response.text}")
            return {
                'success': False,
                'error': f"HTTP {e.response.status_code}",
                'details': e.response.text,
                'platform': 'Snapchat'
            }
            
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return {
                'success': False,
                'error': 'Network error',
                'details': str(e),
                'platform': 'Snapchat'
            }
            
        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {
                'success': False,
                'error': 'Unexpected error',
                'details': str(e),
                'platform': 'Snapchat'
            }
    
    def _fetch_stories(self, username: str) -> Dict:
        """Fetch stories metadata from SnapStory DL API."""
        endpoint = f"{self.api_base_url}/story"
        
        response = self.session.post(
            endpoint,
            json={'username': username},
            timeout=30
        )
        
        # Parse JSON response even for error status codes
        # The API returns meaningful JSON for 400 errors
        try:
            data = response.json()
        except Exception:
            # If JSON parsing fails, raise the HTTP error
            response.raise_for_status()
            return {}
        
        # For non-200 responses, the API still returns valid JSON with error info
        # Don't raise_for_status, just return the parsed data
        return data
    
    def _download_media(
        self,
        media_url: str,
        username: str,
        index: int,
        media_type: int,
        timestamp: str,
        output_path: str
    ) -> Optional[str]:
        """Download individual media file."""
        try:
            # Determine file extension based on media type
            extension = 'mp4' if media_type == 1 else 'jpg'
            

            # Create filename causing sanitization
            ts = timestamp if timestamp else int(time.time())
            safe_username = sanitize_filename(username)
            filename = os.path.join(
                output_path,
                f"snapchat_{safe_username}_{ts}_{index}.{extension}"
            )
            
            # Download file
            response = self.session.get(media_url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return filename
            
        except Exception as e:
            logging.error(f"❌ Failed to download media: {e}")
            return None
