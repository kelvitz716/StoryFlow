"""Snapchat downloader via story.snapchat.com web scraping.

Scrapes __NEXT_DATA__ JSON embedded in the Snapchat story page — no Apify or
API key required.

Content-type coverage:
  - Stories (active 24h)  → story.snapList
  - Highlights (saved)    → curatedHighlights[*].snapList
  - Spotlight             → NOT handled here; queue.py routes /spotlight/ URLs
                            directly to gallery-dl / yt-dlp (SnapchatSpotlight extractor)
"""

import os
import re
import time
import json
import logging
import asyncio
import requests
from typing import Dict, List, Optional

from core.rate_limiter import RateLimiter
from core.storage import is_storage_critical
from core.platform import extract_snapchat_username
from core.security import sanitize_filename
from downloaders.base import BaseDownloader

# ---------------------------------------------------------------------------
# Snapchat web endpoint — no auth required for public profiles
# ---------------------------------------------------------------------------
_STORY_URL = "https://story.snapchat.com/s/{username}"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads via direct story page scraping.

    Fetches both active stories and saved highlights from the public
    story.snapchat.com page, merging all snaps and deduplicating by mediaUrl.
    Zero external API accounts or tokens required.
    """

    def __init__(self, apify_token: str = "", output_path: str = "./downloads"):
        """
        Args:
            apify_token: Ignored — kept for API compatibility with existing bot init.
            output_path: Directory to save downloaded media.
        """
        super().__init__(output_path)
        # apify_token intentionally unused; kept so telegram_bot.py needs zero changes
        self.rate_limiter = RateLimiter(
            max_requests=int(os.getenv("MAX_REQUESTS_PER_MINUTE", 30))
        )
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

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

        Spotlight URLs (/spotlight/...) are NOT routed here — queue.py sends
        them to gallery-dl. If one somehow arrives, return a clear error.
        """
        if "/spotlight/" in url:
            return {
                "success": False,
                "error": "Spotlight URLs are handled by yt-dlp, not the web scraper. "
                         "Please check the URL routing.",
                "platform": "Snapchat",
            }

        username = extract_snapchat_username(url)
        if not username:
            return {
                "success": False,
                "error": "Could not extract username from Snapchat URL. "
                         "Expected: snapchat.com/add/<username> or snapchat.com/@<username>",
                "platform": "Snapchat",
            }

        # Derive fetch mode from URL path
        url_lower = url.lower()
        if "/highlight/" in url_lower or "/highlights/" in url_lower:
            mode = "highlights"
        else:
            # /add/<user>, /@<user>, /stories/<user> — stories only
            mode = "stories"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._download_stories, username, job_id, mode
        )

    # ------------------------------------------------------------------
    # Synchronous download logic
    # ------------------------------------------------------------------

    def _download_stories(
        self, username: str, job_id: Optional[str] = None, mode: str = "both"
    ) -> Dict:
        """Scrape story.snapchat.com and download all media files.

        Args:
            mode: ``"stories"`` — active 24h story only;
                  ``"highlights"`` — curated highlight albums only;
                  ``"both"`` — everything (default).
        """
        self.rate_limiter.wait_if_needed()

        job_output_path = (
            os.path.join(self.output_path, job_id) if job_id else self.output_path
        )
        os.makedirs(job_output_path, exist_ok=True)

        try:
            logging.info(f"📡 Scraping story page for @{username} (mode={mode})…")
            all_items = self._scrape_page(username, mode=mode)

            if not all_items:
                mode_label = {
                    "stories": "active stories",
                    "highlights": "highlights",
                    "both": "stories or highlights",
                }.get(mode, "content")
                return {
                    "success": False,
                    "platform": "Snapchat",
                    "username": username,
                    "error": f"No {mode_label} found for this profile.",
                    "files": [],
                }

            count = len(all_items)
            logging.info(f"📸 Found {count} snap(s) for @{username}")

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

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return {"success": False, "error": "Network error", "details": str(e), "platform": "Snapchat"}

        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {"success": False, "error": "Unexpected error", "details": str(e), "platform": "Snapchat"}

    # ------------------------------------------------------------------
    # Scraping helpers
    # ------------------------------------------------------------------

    def _scrape_page(self, username: str, mode: str = "both") -> List[Dict]:
        """Fetch story.snapchat.com and return normalised snap items.

        Args:
            mode: ``"stories"`` — active story only;
                  ``"highlights"`` — curated highlights only;
                  ``"both"`` — everything (default).
        """
        url = _STORY_URL.format(username=username)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()

        match = _NEXT_DATA_RE.search(resp.text)
        if not match:
            logging.warning(f"⚠️  No __NEXT_DATA__ found for @{username}")
            return []

        try:
            page_props = json.loads(match.group(1))["props"]["pageProps"]
        except (json.JSONDecodeError, KeyError) as e:
            logging.error(f"❌ Failed to parse page JSON for @{username}: {e}")
            return []

        snap_lists: List[List[Dict]] = []

        # Active 24-h story
        if mode in ("stories", "both"):
            story = page_props.get("story") or {}
            if story.get("snapList"):
                snap_lists.append(story["snapList"])
                logging.info(
                    f"  └── active story: {len(story['snapList'])} snap(s)"
                )

        # Curated highlight albums
        if mode in ("highlights", "both"):
            highlights = page_props.get("curatedHighlights") or []
            for h in highlights:
                snaps = h.get("snapList") or []
                if snaps:
                    title = (h.get("storyTitle") or {}).get("value", "untitled")
                    snap_lists.append(snaps)
                    logging.info(f"  └── highlight '{title}': {len(snaps)} snap(s)")

        # Flatten and normalise
        all_snaps = [snap for sl in snap_lists for snap in sl]
        return self._normalise_and_dedupe(all_snaps)

    def _normalise_and_dedupe(self, raw_snaps: List[Dict]) -> List[Dict]:
        """Map Snapchat's snap schema to the common internal schema.

        Common output schema:
          mediaUrl  (str)  — direct CDN download URL
          mediaType (int)  — 0=image, 1=video
          timestamp (str)  — epoch seconds string
        """
        seen: set = set()
        result: List[Dict] = []

        for snap in raw_snaps:
            snap_urls = snap.get("snapUrls") or {}
            media_url = snap_urls.get("mediaUrl")
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)

            # snapMediaType: 0=image, 1=video
            raw_type = snap.get("snapMediaType", 0)
            media_type = 1 if raw_type == 1 else 0

            # timestampInSec is a nested {value: "..."} object
            ts_obj = snap.get("timestampInSec") or {}
            timestamp = ts_obj.get("value") or str(int(time.time()))

            result.append(
                {"mediaUrl": media_url, "mediaType": media_type, "timestamp": timestamp}
            )

        return result

    # ------------------------------------------------------------------
    # Media download helper (unchanged from previous version)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Backwards-compat alias (queue.py calls download_stories directly
    # in some recovery code paths)
    # ------------------------------------------------------------------

    def download_stories(
        self, username: str, url: str = "", job_id: Optional[str] = None
    ) -> Dict:
        """Synchronous alias kept for queue recovery compatibility."""
        return self._download_stories(username, job_id, mode="both")
