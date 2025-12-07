"""Snapchat story downloader using SnapStory DL API."""

import os
import time
import logging
import requests
from typing import Dict, List, Optional

from core.rate_limiter import RateLimiter


class SnapchatDownloader:
    """Handler for Snapchat downloads using SnapStory DL API."""
    
    def __init__(self, api_base_url: str, output_path: str = './downloads'):
        """
        Initialize Snapchat downloader.
        
        Args:
            api_base_url: Base URL for SnapStory DL API
            output_path: Directory to save downloaded media
        """
        self.api_base_url = api_base_url.rstrip('/')
        self.output_path = output_path
        self.rate_limiter = RateLimiter(
            max_requests=int(os.getenv('MAX_REQUESTS_PER_MINUTE', 30))
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StoryFlow/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        # Ensure output directory exists
        os.makedirs(output_path, exist_ok=True)
    
    def download_stories(self, username: str) -> Dict:
        """
        Download all Snapchat stories for a username.
        
        Args:
            username: Snapchat username
            
        Returns:
            Dict containing status and download information
        """
        self.rate_limiter.wait_if_needed()
        
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
                    'success': True,
                    'platform': 'Snapchat',
                    'username': username,
                    'message': 'No active stories found',
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
                    timestamp=timestamp
                )
                
                if filename:
                    downloaded_files.append(filename)
                    logging.info(f"✅ Downloaded story {i}/{count}: {os.path.basename(filename)}")
            
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
        timestamp: str
    ) -> Optional[str]:
        """Download individual media file."""
        try:
            # Determine file extension based on media type
            extension = 'mp4' if media_type == 1 else 'jpg'
            
            # Create filename
            ts = timestamp if timestamp else int(time.time())
            filename = os.path.join(
                self.output_path,
                f"snapchat_{username}_{ts}_{index}.{extension}"
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
