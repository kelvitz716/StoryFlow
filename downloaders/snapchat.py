"""Snapchat downloader via story.snapchat.com web scraping.

Scrapes __NEXT_DATA__ JSON embedded in the Snapchat story page.
Zero external API accounts or tokens required.

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
from urllib.parse import urlparse, urljoin
import requests
from typing import Dict, List, Optional, Callable

from core.rate_limiter import RateLimiter
from core.queue import _env_int
from core.storage import is_storage_critical
from core.platform import extract_snapchat_username, _valid_snapchat_username
from core.security import sanitize_filename, is_safe_url
from downloaders.base import BaseDownloader

_ALLOWED_MEDIA_HOST_SUFFIXES = ("sc-cdn.net", "snapchat.com")
_MAX_FILE_SIZE_MB = _env_int('MAX_FILE_SIZE_MB', 500, 1, 10000)
_DOWNLOAD_TIMEOUT_SECONDS = _env_int('DOWNLOAD_TIMEOUT_SECONDS', 600, 10, 86400)
_MAX_JOB_SIZE_MB = _env_int('MAX_JOB_SIZE_MB', 2048, 10, 100000)
_MAX_FILES_PER_JOB = _env_int('MAX_FILES_PER_JOB', 500, 1, 10000)

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


def _safe_get(
    url: str,
    session: Optional[requests.Session] = None,
    timeout: Optional[float] = None,
) -> Optional[requests.Response]:
    """Safely fetch media URL:
    - Require https, host in _ALLOWED_MEDIA_HOST_SUFFIXES, and is_safe_url(url).
    - Use allow_redirects=False and follow at most 3 redirects manually,
      re-validating every hop the same way.
    """
    sess = session or requests.Session()
    current_url = url
    max_redirects = 3
    req_timeout = timeout if timeout is not None else _DOWNLOAD_TIMEOUT_SECONDS

    for hop in range(max_redirects + 1):
        try:
            parsed = urlparse(current_url)
            if parsed.scheme != 'https':
                logging.warning(f"Rejected non-HTTPS media URL: {current_url}")
                return None

            hostname = parsed.hostname
            if not hostname:
                logging.warning(f"Rejected media URL with no hostname: {current_url}")
                return None

            hostname = hostname.rstrip('.').lower()
            logging.info(f"Observed Snapchat media hostname: {hostname}")

            allowed = any(
                hostname == suffix or hostname.endswith('.' + suffix)
                for suffix in _ALLOWED_MEDIA_HOST_SUFFIXES
            )
            if not allowed:
                logging.warning(
                    f"Disallowed Snapchat media hostname: {hostname} "
                    f"(must end with one of {_ALLOWED_MEDIA_HOST_SUFFIXES})"
                )
                return None

            if not is_safe_url(current_url):
                logging.warning(f"SSRF check failed for media URL: {current_url}")
                return None

            response = sess.get(
                current_url,
                stream=True,
                allow_redirects=False,
                timeout=req_timeout,
                headers=_HEADERS,
            )
        except Exception as e:
            logging.warning(f"Request failed for {current_url}: {e}")
            return None

        if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                logging.warning(f"Redirect without Location header from {current_url}")
                return None
            current_url = urljoin(current_url, location)
            if hop >= max_redirects:
                logging.warning(f"Too many redirects ({max_redirects}) for media URL: {url}")
                return None
            continue

        return response

    return None


class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads via direct story page scraping.

    Fetches both active stories and saved highlights from the public
    story.snapchat.com page, merging all snaps and deduplicating by mediaUrl.
    Zero external API accounts or tokens required.
    """

    def __init__(self, output_path: str = "./downloads"):
        """
        Args:
            output_path: Directory to save downloaded media.
        """
        super().__init__(output_path)
        self.rate_limiter = RateLimiter(
            max_requests=_env_int("MAX_REQUESTS_PER_MINUTE", 30, 1, 600)
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
            cumulative_bytes = 0
            max_job_bytes = _MAX_JOB_SIZE_MB * 1024 * 1024

            for i, item in enumerate(all_items, 1):
                if len(downloaded_files) >= _MAX_FILES_PER_JOB:
                    logging.warning(
                        f"⚠️ Reached MAX_FILES_PER_JOB ({_MAX_FILES_PER_JOB}). "
                        f"Stopping download for @{username}."
                    )
                    return {
                        "success": True,
                        "platform": "Snapchat",
                        "username": username,
                        "total_stories": count,
                        "downloaded": len(downloaded_files),
                        "files": downloaded_files,
                        "message": "Download stopped: limit reached",
                        "limit_reached": True,
                    }

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
                    try:
                        cumulative_bytes += os.path.getsize(filename)
                    except OSError:
                        pass
                    logging.info(
                        f"✅ Downloaded {i}/{count}: {os.path.basename(filename)}"
                    )

                    if cumulative_bytes >= max_job_bytes:
                        logging.warning(
                            f"⚠️ Reached MAX_JOB_SIZE_MB ({_MAX_JOB_SIZE_MB} MB). "
                            f"Stopping download for @{username}."
                        )
                        return {
                            "success": True,
                            "platform": "Snapchat",
                            "username": username,
                            "total_stories": count,
                            "downloaded": len(downloaded_files),
                            "files": downloaded_files,
                            "message": "Download stopped: limit reached",
                            "limit_reached": True,
                        }

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
            return {"success": False, "error": "Network error", "details": "Failed to connect to Snapchat service", "platform": "Snapchat"}

        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {"success": False, "error": "Unexpected error", "details": "An unexpected error occurred while processing Snapchat content", "platform": "Snapchat"}

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
        if not _valid_snapchat_username(username):
            logging.warning(f"Invalid Snapchat username for _scrape_page: {username!r}")
            return []

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
    # Media download helper
    # ------------------------------------------------------------------

    def _safe_get(
        self, url: str, timeout: Optional[float] = None
    ) -> Optional[requests.Response]:
        """Instance delegate for _safe_get using self.session."""
        return _safe_get(url, session=self.session, timeout=timeout)

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
        # 1. Disk critical check before each file
        is_critical, usage = is_storage_critical(output_path)
        if is_critical:
            logging.error(f"❌ Storage critical ({usage}%). Skipping file {index} for @{username}.")
            return None

        # 2. Wall-clock deadline
        start_time = time.time()
        deadline = start_time + _DOWNLOAD_TIMEOUT_SECONDS

        safe_username = sanitize_filename(username)
        extension = "mp4" if media_type == 1 else "jpg"
        ts = timestamp if timestamp else str(int(time.time()))
        filename = os.path.join(
            output_path,
            f"snapchat_{safe_username}_{ts}_{index}.{extension}",
        )

        response = None
        try:
            remaining_time = deadline - time.time()
            if remaining_time <= 0:
                logging.error("❌ Download timeout exceeded before request")
                return None

            response = self._safe_get(media_url, timeout=remaining_time)
            if response is None:
                return None

            # 3. Content-Length check
            max_bytes = _MAX_FILE_SIZE_MB * 1024 * 1024
            cl_header = response.headers.get("Content-Length")
            if cl_header:
                try:
                    content_length = int(cl_header)
                    if content_length > max_bytes:
                        logging.warning(
                            f"Content-Length ({content_length} bytes) exceeds MAX_FILE_SIZE_MB ({_MAX_FILE_SIZE_MB} MB)"
                        )
                        return None
                except ValueError:
                    pass

            response.raise_for_status()

            # 4. Stream and count bytes with wall-clock deadline
            total_bytes = 0
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if time.time() > deadline:
                        logging.warning(f"Download exceeded wall-clock timeout ({_DOWNLOAD_TIMEOUT_SECONDS}s)")
                        raise TimeoutError("Download timed out")
                    if chunk:
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            logging.warning(
                                f"Downloaded bytes ({total_bytes}) exceeded limit ({max_bytes} bytes)"
                            )
                            raise ValueError("File size limit exceeded")
                        f.write(chunk)

            return filename

        except Exception as e:
            logging.error(f"❌ Failed to download media: {e}")
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except OSError:
                    pass
            return None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Backwards-compat alias (queue.py calls download_stories directly
    # in some recovery code paths)
    # ------------------------------------------------------------------

    def download_stories(
        self, username: str, url: str = "", job_id: Optional[str] = None
    ) -> Dict:
        """Synchronous alias kept for queue recovery compatibility."""
        return self._download_stories(username, job_id, mode="both")
