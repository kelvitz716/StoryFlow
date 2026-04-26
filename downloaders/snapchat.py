"""Snapchat downloader via Apify cloud actors.

Content-type coverage:
  - Stories (active 24h)  → igview-owner/snapchat-story-viewer
  - Highlights (saved)    → crawlerbros/snapchat-user-stories-scraper
  - Spotlight             → NOT handled here; queue.py routes /spotlight/ URLs
                            directly to gallery-dl / yt-dlp (SnapchatSpotlight extractor)
"""

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

# ---------------------------------------------------------------------------
# Apify actor endpoints (synchronous run — returns dataset items in one call)
# ---------------------------------------------------------------------------
_APIFY_BASE = "https://api.apify.com/v2/acts"
_ACTOR_HIGHLIGHTS = "crawlerbros~snapchat-user-stories-scraper"   # saved story albums
_ACTOR_STORIES    = "igview-owner~snapchat-story-viewer"          # active 24-h stories
_SYNC_SUFFIX      = "/run-sync-get-dataset-items"


class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads via Apify cloud actors.

    Fetches both active stories and saved highlights in a single call to the
    bot, merging the results and deduplicating by mediaUrl so the user gets
    everything available on the public profile.
    """

    def __init__(self, apify_token: str, output_path: str = "./downloads"):
        """
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
        """Queue-compatible async entry point.

        Note: Spotlight URLs (/spotlight/...) are NOT routed here — queue.py
        sends them directly to gallery-dl which uses yt-dlp's SnapchatSpotlight
        extractor. If one somehow arrives here, return a clear error.
        """
        if "/spotlight/" in url:
            return {
                "success": False,
                "error": "Spotlight URLs are handled by yt-dlp, not the Apify downloader. "
                         "Please check the URL routing.",
                "platform": "Snapchat",
            }

        username = extract_snapchat_username(url)
        if not username:
            return {
                "success": False,
                "error": "Could not extract username from Snapchat URL. "
                         "Expected: snapchat.com/add/<username>",
                "platform": "Snapchat",
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.download_stories, username, url, job_id
        )

    # ------------------------------------------------------------------
    # Synchronous download logic
    # ------------------------------------------------------------------

    def download_stories(
        self, username: str, url: str, job_id: Optional[str] = None
    ) -> Dict:
        """Fetch stories + highlights from Apify, download all media files.

        Returns a dict with the same shape as before so the rest of the bot
        (uploader, queue, Telegram handlers) needs zero changes.
        """
        self.rate_limiter.wait_if_needed()

        job_output_path = (
            os.path.join(self.output_path, job_id) if job_id else self.output_path
        )
        os.makedirs(job_output_path, exist_ok=True)

        try:
            logging.info(f"📡 Fetching content for @{username} via Apify…")

            stories_items = []
            highlights_items = []

            # 1. Active Stories (now defaults to /add/ as well)
            if "/stories/" in url.lower() or "/story." in url.lower() or "story.snapchat.com" in url.lower() or "/add/" in url.lower():
                logging.info(f"🔍 URL mapped to ACTIVE STORIES for @{username}")
                stories_items = self._fetch_actor(_ACTOR_STORIES, username, "stories")

            # 2. Saved Highlights (custom trigger)
            elif "/highlight/" in url.lower():
                logging.info(f"🔍 URL mapped to SAVED HIGHLIGHTS for @{username}")
                highlights_items = self._fetch_actor(_ACTOR_HIGHLIGHTS, username, "highlights")

            # 3. Fallback (Call Stories if format is unknown)
            else:
                logging.info(f"🔍 URL format ambiguous — defaulting to ACTIVE STORIES for @{username}")
                stories_items = self._fetch_actor(_ACTOR_STORIES, username, "stories")

            # Merge and deduplicate by mediaUrl
            all_items = self._merge(stories_items, highlights_items)

            if not all_items:
                return {
                    "success": False,
                    "platform": "Snapchat",
                    "username": username,
                    "error": "No active stories or highlights found for this profile.",
                    "files": [],
                }

            count = len(all_items)
            logging.info(
                f"📸 Found {count} items for @{username} "
                f"({len(stories_items)} stories, {len(highlights_items)} highlights)"
            )

            # --- Download each media file --------------------------------
            downloaded_files: List[str] = []
            for i, item in enumerate(all_items, 1):
                media_url  = item.get("mediaUrl")
                media_type = item.get("mediaType", 0)   # 0=image, 1=video
                timestamp  = item.get("timestamp", "")

                if not media_url:
                    logging.warning(f"⚠️  Item {i} has no mediaUrl, skipping")
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
                        f"✅ Downloaded {i}/{count}: {os.path.basename(filename)}"
                    )

                    is_critical, usage = is_storage_critical(
                        job_output_path, threshold=90.0
                    )
                    if is_critical:
                        logging.warning(
                            f"⚠️  Storage threshold reached ({usage}%). "
                            f"Stopping download for @{username}."
                        )
                        return {
                            "success": True,
                            "platform": "Snapchat",
                            "username": username,
                            "total_stories": count,
                            "downloaded": len(downloaded_files),
                            "files": downloaded_files,
                            "message": f"Partially completed — storage at {usage}%.",
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
            return {"success": False, "error": msg, "details": e.response.text, "platform": "Snapchat"}

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return {"success": False, "error": "Network error", "details": str(e), "platform": "Snapchat"}

        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {"success": False, "error": "Unexpected error", "details": str(e), "platform": "Snapchat"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_actor(
        self, actor_id: str, username: str, label: str
    ) -> List[Dict]:
        """Call one Apify actor synchronously and return normalised items.

        Returns an empty list (not an exception) on actor-level failures so
        the other actor's results are still usable.
        """
        url = f"{_APIFY_BASE}/{actor_id}{_SYNC_SUFFIX}"
        try:
            resp = self.session.post(
                url,
                params={"token": self.apify_token},
                json={"usernames": [username], "maxSnapsPerUser": 50},
                timeout=120,
            )
            resp.raise_for_status()
            raw: List[Dict] = resp.json()
            normalised = self._normalise(raw)
            logging.info(
                f"  └── {label}: {len(normalised)} item(s) from {actor_id}"
            )
            return normalised
        except requests.exceptions.HTTPError as e:
            # 4xx from one actor shouldn't kill the whole request
            logging.warning(
                f"⚠️  {label} actor ({actor_id}) returned HTTP "
                f"{e.response.status_code} — skipping."
            )
            return []
        except Exception as e:
            logging.warning(f"⚠️  {label} actor ({actor_id}) failed: {e} — skipping.")
            return []

    def _normalise(self, raw_items: List[Dict]) -> List[Dict]:
        """Map any actor's output to a common schema.

        Common output schema:
          mediaUrl  (str)  — direct download URL
          mediaType (int)  — 0=image, 1=video
          timestamp (str)  — ISO8601 or epoch string
        """
        result: List[Dict] = []
        
        # Flatten nested 'snaps' arrays if present (igview-owner structure)
        flat_items = []
        for item in raw_items:
            if "snaps" in item and isinstance(item["snaps"], list):
                # Inherit top-level metadata if useful later, but mediaUrl is in the snap
                flat_items.extend(item["snaps"])
            else:
                flat_items.append(item)

        for item in flat_items:
            media_url = (
                item.get("mediaUrl")
                or item.get("url")
                or item.get("videoUrl")
                or item.get("imageUrl")
            )
            if not media_url:
                continue

            raw_type = item.get("mediaType") or item.get("type", "")
            if isinstance(raw_type, int):
                media_type = raw_type
            elif "video" in str(raw_type).lower() or str(media_url).endswith(".mp4"):
                media_type = 1
            else:
                media_type = 0

            timestamp = (
                item.get("timestamp")
                or item.get("postedAt")
                or item.get("createdAt")
                or item.get("capturedAt")
                or str(int(time.time()))
            )

            result.append(
                {"mediaUrl": media_url, "mediaType": media_type, "timestamp": timestamp}
            )
        return result

    def _merge(self, stories: List[Dict], highlights: List[Dict]) -> List[Dict]:
        """Merge two item lists, deduplicating by mediaUrl."""
        seen: set = set()
        merged: List[Dict] = []
        for item in stories + highlights:
            url = item.get("mediaUrl", "")
            if url and url not in seen:
                seen.add(url)
                merged.append(item)
        return merged

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
