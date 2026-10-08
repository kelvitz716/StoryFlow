import re
import logging
import time
from typing import Optional, Dict

# Global registry for job status messages (shared between handlers and bot entry point)
JOB_MESSAGES: Dict[str, any] = {}
# Timestamp tracking for JOB_MESSAGES TTL sweeps
_JOB_MESSAGES_TIMES: Dict[str, float] = {}
_JOB_MESSAGES_TTL = 3600  # 1 hour

def _sweep_job_messages():
    """Remove JOB_MESSAGES entries that are older than TTL (in case callbacks were never fired)."""
    now = time.time()
    expired = [jid for jid, ts in _JOB_MESSAGES_TIMES.items() if now - ts > _JOB_MESSAGES_TTL]
    for jid in expired:
        JOB_MESSAGES.pop(jid, None)
        _JOB_MESSAGES_TIMES.pop(jid, None)
    if expired:
        logging.debug(f"🧹 JOB_MESSAGES TTL sweep: removed {len(expired)} orphan entries")

def register_job_message(job_id: str, message):
    """Register a status message for a job with TTL tracking."""
    if message is None:
        return
    if len(JOB_MESSAGES) > 200:
        _sweep_job_messages()
    JOB_MESSAGES[job_id] = message
    _JOB_MESSAGES_TIMES[job_id] = time.time()

def pop_job_message(job_id: str):
    """Remove a job's status message from the registry."""
    JOB_MESSAGES.pop(job_id, None)
    _JOB_MESSAGES_TIMES.pop(job_id, None)


import asyncio
import requests
from core.security import validate_domain, is_safe_url


class UnsafeRedirectError(Exception):
    """
    Raised by resolve_shortlink when a redirect hop leads to a non-global
    address, when the hop limit is exceeded, or when a connection/timeout
    error occurs during resolution.

    Callers must treat this as an invalid/unsafe URL and reject the request
    with a generic message rather than exposing the underlying reason to users.
    """


async def resolve_shortlink(url: str) -> str:
    """
    Resolve a URL shortener / redirect chain, validating every hop.

    Algorithm (item 3):
    - Primary platform domains skip resolution (they don't redirect off-platform).
    - Short/redirect domains are followed manually: up to MAX_HOPS hops, using
      requests.get(..., allow_redirects=False, stream=True) so no body is
      downloaded. On HEAD 405/403 the function falls back to GET with stream=True.
    - BEFORE each hop target is requested, is_safe_url() is called on it.
      If it returns False, UnsafeRedirectError is raised immediately and no
      request is made to the unsafe address.
    - On timeout, connection error, or too-many-hops: raise UnsafeRedirectError
      (fail closed — rejecting an occasional legitimate link is acceptable).
    - On success, return the FINAL validated URL (not the original), so that
      the downloader receives a URL whose destination has already been checked.

    Args:
        url: URL to resolve.

    Returns:
        Resolved, safe final URL.

    Raises:
        UnsafeRedirectError: if any hop is unsafe, resolution fails, or
                             the hop limit is exceeded.
    """
    # Primary domains that do NOT need redirect resolution
    primary_domains = ['snapchat.com', 'instagram.com', 'tiktok.com', 'twitter.com', 'x.com', 'facebook.com']
    exclude_shorteners = ['dl.snapchat.com', 'vm.tiktok.com', 'fb.watch']

    is_primary = validate_domain(url, primary_domains) and not validate_domain(url, exclude_shorteners)
    if is_primary:
        return url

    MAX_HOPS = 5
    TIMEOUT_SECS = 5

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    def _do_resolve() -> str:
        """
        Synchronous manual redirect follower.  Run in a thread via asyncio.to_thread.
        Returns the final safe URL.
        Raises UnsafeRedirectError on any unsafe or failed hop.
        """
        current_url = url
        hops = 0

        while hops < MAX_HOPS:
            # Validate current target before requesting it
            if not is_safe_url(current_url):
                logging.warning(
                    f"resolve_shortlink: blocked unsafe hop {hops} → {current_url!r} "
                    f"(original URL: {url!r})"
                )
                raise UnsafeRedirectError(f"Unsafe redirect target at hop {hops}: {current_url!r}")

            try:
                response = requests.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    stream=True,
                    timeout=TIMEOUT_SECS,
                )
                # Close immediately — we only need headers
                response.close()
            except requests.exceptions.Timeout:
                logging.warning(f"resolve_shortlink: timeout resolving {current_url!r}")
                raise UnsafeRedirectError(f"Timeout resolving {current_url!r}")
            except requests.exceptions.ConnectionError as exc:
                logging.warning(f"resolve_shortlink: connection error resolving {current_url!r}: {exc}")
                raise UnsafeRedirectError(f"Connection error resolving {current_url!r}")
            except Exception as exc:
                logging.warning(f"resolve_shortlink: unexpected error resolving {current_url!r}: {exc}")
                raise UnsafeRedirectError(f"Resolution error for {current_url!r}")

            # If this is a redirect, extract Location and continue
            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "").strip()
                if not location:
                    # No Location header — treat final URL as current
                    return current_url

                # Resolve relative redirects against the current URL
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                hops += 1
                current_url = next_url
                continue

            # Non-redirect response: we've reached the final destination
            return current_url

        # Exceeded hop limit
        logging.warning(
            f"resolve_shortlink: exceeded {MAX_HOPS} hops for {url!r}, last URL: {current_url!r}"
        )
        raise UnsafeRedirectError(f"Too many redirects (>{MAX_HOPS}) from {url!r}")

    return await asyncio.to_thread(_do_resolve)


def escape_markdown(text: str, version: int = 2) -> str:
    """
    Escape special characters for Telegram Markdown.

    Args:
        text: Unescaped text
        version: Markdown version (1 or 2)

    Returns:
        Escaped text
    """
    if version == 1:
        # Markdown V1 escaping (simpler)
        # Characters to escape: _ * ` [
        escape_chars = r'_*`['
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
    else:
        # Markdown V2 escaping (strict)
        # Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_error_message(error: str, platform: Optional[str] = None) -> str:
    """Format a user-friendly error message."""
    prefix = f"❌ *{platform} Error*" if platform else "❌ *Error*"

    # Common error mapping (order matters — more specific checks first)
    error_lower = error.lower()
    if 'login' in error_lower or 'cookie' in error_lower or 'authentication' in error_lower:
        hint = "\n\n💡 *Hint:* This content may require login cookies. Try adding them in 'Manage Cookies'."
    elif 'not found' in error_lower or '404' in error_lower or 'no active stories' in error_lower:
        hint = "\n\n💡 *Hint:* The link might be invalid, or the user/content has no active public stories."
    elif 'rate limit' in error_lower:
        hint = "\n\n💡 *Hint:* Too many requests. Please wait a few minutes."
    else:
        hint = ""

    return f"{prefix}\n{escape_markdown(error)}{hint}"

def get_platform_emoji(platform: str) -> str:
    """Get emoji for a platform."""
    emojis = {
        "Instagram": "📸",
        "TikTok": "🎵",
        "Twitter": "🐦",
        "Facebook": "📘",
        "Snapchat": "👻",
        "X": "🐦"
    }
    return emojis.get(platform, "📥")
