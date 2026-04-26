"""Snapchat story downloader via Apify (crawlerbros/snapchat-user-stories-scraper)."""

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

# Apify actor endpoint — runs synchronously and returns dataset items in one response
_APIFY_ACTOR = "crawlerbros~snapchat-user-stories-scraper"
_APIFY_SYNC_URL = (
    f"https://api.apify.com/v2/acts/{_APIFY_ACTOR}"
    "/run-sync-get-dataset-items"
)


class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads using the Apify actor."""

    def __init__(self, apify_token: str, output_path: str = "./downloads"):
        """
        Initialize Snapchat downloader.

        Args:
            apify_token: Apify API token (APIFY_TOKEN env var)
            output_path: Directory to save downloaded media
        """
        super().__init__(output_path)
        self.apify_token = apify_token
        self.rate_limiter = RateLimiter(
            max_requests=int(os.getenv("MAX_REQUESTS_PER_MINUTE", 30))
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "StoryFlow/2.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Public async entry point (Queue-compatible)
    # ------------------------------------------------------------------

    async def download(
        self,
        url: str,
        user_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict:
        """
        Adapter method for Queue compatibility.

        Args:
            url: Snapchat profile URL (e.g. snapchat.com/add/username)
            user_id: Telegram user ID
            job_id: Unique job identifier for directory isolation
        """
        if "/spotlight/" in url:
            return {
                "success": False,
                "error": "Spotlight URLs must be routed to gallery-dl, not SnapchatDownloader",
                "platform": "Snapchat",
            }

        username = extract_snapchat_username(url)
        if not username:
            return {
                "success": False,
                "error": "Could not extract username from Snapchat URL",
                "platform": "Snapchat",
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.download_stories, username, job_id
        )

    # ------------------------------------------------------------------
    # Synchronous download logic
    # ------------------------------------------------------------------

    def download_stories(
        self, username: str, job_id: Optional[str] = None
    ) -> Dict:
        """
        Download all public Snapchat stories for a username via Apify.

        Returns a dict with the same shape as the old implementation so
        the rest of the bot (uploader, queue, Telegram handlers) requires
        zero changes.
        """
        self.rate_limiter.wait_if_needed()

        job_output_path = (
            os.path.join(self.output_path, job_id) if job_id else self.output_path
        )
        os.makedirs(job_output_path, exist_ok=True)

        try:
            logging.info(f"📡 Fetching Snapchat stories for @{username} via Apify…")
            stories = self._fetch_stories(username)

            if not stories:
                return {
                    "success": False,
                    "platform": "Snapchat",
                    "username": username,
                    "error": "No active public stories found",
                    "files": [],
                }

            count = len(stories)
            logging.info(f"📸 Found {count} stories for @{username}")

            downloaded_files: List[str] = []
            for i, story in enumerate(stories, 1):
                media_url = story.get("mediaUrl")
                media_type = story.get("mediaType", 0)  # 0=image, 1=video
                timestamp = story.get("timestamp", "")

                if not media_url:
                    logging.warning(f"⚠️  Story {i} has no mediaUrl, skipping")
                    continue

                filename = self._download_media(
                    media_url=media_url,
                    username=username,
                    index=i,
                    media_type=media_type,
                    timestamp=timestamp,
                    output_path=job_output_path,
                )

                if filename:
                    downloaded_files.append(filename)
                    logging.info(
                        f"✅ Downloaded story {i}/{count}: {os.path.basename(filename)}"
                    )

                    is_critical, current_usage = is_storage_critical(
                        job_output_path, threshold=90.0
                    )
                    if is_critical:
                        logging.warning(
                            f"⚠️  Storage threshold reached ({current_usage}%). "
                            f"Stopping download for @{username}."
                        )
                        return {
                            "success": True,
                            "platform": "Snapchat",
                            "username": username,
                            "total_stories": count,
                            "downloaded": len(downloaded_files),
                            "files": downloaded_files,
                            "message": f"Partially completed. Storage threshold reached ({current_usage}%).",
                        }

            return {
                "success": True,
                "platform": "Snapchat",
                "username": username,
                "total_stories": count,
                "downloaded": len(downloaded_files),
                "files": downloaded_files,
            }

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 402:
                msg = "Apify quota exhausted — please top up your Apify account."
            elif status == 429:
                msg = "Apify rate limit hit — please try again shortly."
            else:
                msg = f"HTTP {status}"
            logging.error(f"❌ Apify HTTP error {status}: {e.response.text}")
            return {
                "success": False,
                "error": msg,
                "details": e.response.text,
                "platform": "Snapchat",
            }

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return {
                "success": False,
                "error": "Network error",
                "details": str(e),
                "platform": "Snapchat",
            }

        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {
                "success": False,
                "error": "Unexpected error",
                "details": str(e),
                "platform": "Snapchat",
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_stories(self, username: str) -> List[Dict]:
        """
        Call the Apify actor synchronously and return a normalised list of
        story dicts, each containing:
          - mediaUrl   (str)  direct download URL
          - mediaType  (int)  0=image, 1=video
          - timestamp  (str)  ISO8601 or epoch string
        """
        response = self.session.post(
            _APIFY_SYNC_URL,
            params={"token": self.apify_token},
            json={"usernames": [username], "maxSnapsPerUser": 50},
            timeout=120,  # Apify actor may take ~30-60 s to cold-start
        )
        response.raise_for_status()

        raw_items: List[Dict] = response.json()  # list of dataset items

        normalised: List[Dict] = []
        for item in raw_items:
            # The actor returns one item per story snap.
            # Field names from crawlerbros actor schema:
            media_url = (
                item.get("mediaUrl")
                or item.get("url")
                or item.get("videoUrl")
                or item.get("imageUrl")
            )
            if not media_url:
                continue

            # Determine media type: prefer explicit field, fall back to URL sniff
            raw_type = item.get("mediaType") or item.get("type", "")
            if isinstance(raw_type, int):
                media_type = raw_type  # already 0/1
            elif "video" in str(raw_type).lower() or media_url.endswith(".mp4"):
                media_type = 1
            else:
                media_type = 0

            timestamp = (
                item.get("timestamp")
                or item.get("createdAt")
                or item.get("capturedAt")
                or str(int(time.time()))
            )

            normalised.append(
                {
                    "mediaUrl": media_url,
                    "mediaType": media_type,
                    "timestamp": timestamp,
                }
            )

        return normalised

    def _download_media(
        self,
        media_url: str,
        username: str,
        index: int,
        media_type: int,
        timestamp: str,
        output_path: str,
    ) -> Optional[str]:
        """Download an individual media file to disk."""
        try:
            extension = "mp4" if media_type == 1 else "jpg"
            ts = timestamp if timestamp else str(int(time.time()))
            safe_username = sanitize_filename(username)
            filename = os.path.join(
                output_path,
                f"snapchat_{safe_username}_{ts}_{index}.{extension}",
            )

            response = self.session.get(media_url, stream=True, timeout=60)
            response.raise_for_status()

            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return filename

        except Exception as e:
            logging.error(f"❌ Failed to download media: {e}")
            return None
