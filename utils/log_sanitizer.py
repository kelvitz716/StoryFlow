"""
Log sanitization utility to prevent sensitive data from appearing in logs.

This module provides filters and formatters to redact sensitive information like:
- Bot tokens
- API keys/hashes
- Session strings / cookie auth headers
- Phone numbers
- User IDs (in certain contexts)
"""

import re
import logging
import traceback
from typing import Pattern


# ---------------------------------------------------------------------------
# Additional patterns requested by G2
# ---------------------------------------------------------------------------

_EXTRA_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    # Telethon / Pyrogram base64 session string (long, ends without = padding often)
    'session_string': (
        re.compile(r'(?<![A-Za-z0-9+/])([A-Za-z0-9+/]{80,}={0,2})(?![A-Za-z0-9+/=])'),
        '***REDACTED-SESSION***',
    ),
    # Cookie: or Set-Cookie: header values
    'cookie_header': (
        re.compile(r'(?i)((?:Set-)?Cookie\s*:\s*)\S+'),
        r'\1***REDACTED-COOKIE***',
    ),
    # Authorization: Bearer / Basic / Token header
    'auth_header': (
        re.compile(r'(?i)(Authorization\s*:\s*(?:Bearer|Basic|Token)\s+)\S+'),
        r'\1***REDACTED-TOKEN***',
    ),
    # Phone numbers with country code (+ prefix, 7–15 digits)
    'phone_number': (
        re.compile(r'(?<!\d)\+\d{7,15}(?!\d)'),
        '+***REDACTED-PHONE***',
    ),
}


class SensitiveDataFilter(logging.Filter):
    """Filter to sanitize sensitive data from log messages (msg and args only)."""

    # Patterns for sensitive data
    PATTERNS = {
        'bot_token': re.compile(r'\d{9,10}:[A-Za-z0-9_-]{35}'),
        'api_hash': re.compile(r'[a-f0-9]{32}'),
        'api_id': re.compile(r'TELEGRAM_API_ID=\d+'),
        'user_id_context': re.compile(r'(user_id["\']?\s*[:=]\s*["\']?)\d+'),
    }

    # Replacement strings
    REPLACEMENTS = {
        'bot_token': '***REDACTED-BOT-TOKEN***',
        'api_hash': '***REDACTED-API-HASH***',
        'api_id': 'TELEGRAM_API_ID=***REDACTED***',
        'user_id_context': r'\1***REDACTED***',
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record to sanitize sensitive data.

        Args:
            record: The log record to filter

        Returns:
            True to allow the record through (we always allow, just sanitize)
        """
        # Sanitize the message
        record.msg = self.sanitize(str(record.msg))

        # Sanitize args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: v if isinstance(v, (int, float)) else self.sanitize(str(v))
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    arg if isinstance(arg, (int, float)) else self.sanitize(str(arg))
                    for arg in record.args
                )

        return True

    def sanitize(self, text: str) -> str:
        """
        Sanitize a string by replacing sensitive patterns.

        Args:
            text: The text to sanitize

        Returns:
            Sanitized text with sensitive data redacted
        """
        for pattern_name, pattern in self.PATTERNS.items():
            replacement = self.REPLACEMENTS[pattern_name]
            text = pattern.sub(replacement, text)

        for _name, (pattern, replacement) in _EXTRA_PATTERNS.items():
            text = pattern.sub(replacement, text)

        return text


class SanitizingFormatter(logging.Formatter):
    """
    A Formatter subclass that sanitizes the *fully formatted* log output,
    including exception tracebacks.  It applies the same redaction rules as
    SensitiveDataFilter but acts on the final string produced by
    ``Formatter.format()``, so nothing slips through via exc_text or exc_info.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sanitizer = SensitiveDataFilter()

    def format(self, record: logging.LogRecord) -> str:
        # Let the standard Formatter build the full string (with traceback, etc.)
        formatted = super().format(record)
        # Sanitize the entire output, including any traceback text
        return self._sanitizer.sanitize(formatted)


def add_sensitive_data_filter(logger: logging.Logger = None) -> None:
    """
    Add the sensitive data filter to a logger.

    Args:
        logger: Logger to add filter to. If None, adds to root logger.
    """
    if logger is None:
        logger = logging.getLogger()

    # Check if filter already exists
    for f in logger.filters:
        if isinstance(f, SensitiveDataFilter):
            return  # Already added

    logger.addFilter(SensitiveDataFilter())


def sanitize_string(text: str) -> str:
    """
    Sanitize a string directly without using the logging filter.

    Args:
        text: The text to sanitize

    Returns:
        Sanitized text
    """
    filter_instance = SensitiveDataFilter()
    return filter_instance.sanitize(text)
