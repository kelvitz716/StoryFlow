"""
Log sanitization utility to prevent sensitive data from appearing in logs.

This module provides filters to redact sensitive information like:
- Bot tokens
- API keys/hashes
- User IDs (in certain contexts)
"""

import re
import logging
from typing import Pattern


class SensitiveDataFilter(logging.Filter):
    """Filter to sanitize sensitive data from log messages."""
    
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
                record.args = {k: self.sanitize(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.sanitize(str(arg)) for arg in record.args)
        
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
        
        return text


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
