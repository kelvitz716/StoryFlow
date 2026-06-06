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
from core.security import validate_domain

async def resolve_shortlink(url: str) -> str:
    """Resolve any URL shorteners or redirects asynchronously, skipping primary domains."""
    # Primary domains that do NOT need redirect resolution
    # Note: we exclude short domains like vm.tiktok.com, fb.watch, and dl.snapchat.com so they get resolved.
    primary_domains = ['snapchat.com', 'instagram.com', 'tiktok.com', 'twitter.com', 'x.com', 'facebook.com']
    exclude_shorteners = ['dl.snapchat.com', 'vm.tiktok.com', 'fb.watch']
    
    is_primary = validate_domain(url, primary_domains) and not validate_domain(url, exclude_shorteners)
    
    if not is_primary:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
            
            def do_resolve():
                try:
                    response = requests.head(url, headers=headers, allow_redirects=True, timeout=5)
                    # If HEAD is not allowed (405 or 403), try a streamed GET
                    if response.status_code in [403, 405]:
                        response = requests.get(url, headers=headers, allow_redirects=True, stream=True, timeout=5)
                        response.close() # Close stream immediately
                    return str(response.url)
                except Exception:
                    # Fallback to GET directly on any other issue
                    try:
                        response = requests.get(url, headers=headers, allow_redirects=True, stream=True, timeout=5)
                        response.close()
                        return str(response.url)
                    except Exception:
                        return url

            resolved_url = await asyncio.to_thread(do_resolve)
            return resolved_url
        except Exception as e:
            logging.error(f"Failed to resolve shortlink {url}: {e}")
    return url

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
