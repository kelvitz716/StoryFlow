"""Utility functions for the Telegram bot."""
import re
import logging
from typing import Optional, Dict

# Global registry for job status messages (shared between handlers and bot entry point)
JOB_MESSAGES: Dict[str, any] = {}

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
    
    # Common error mapping
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
