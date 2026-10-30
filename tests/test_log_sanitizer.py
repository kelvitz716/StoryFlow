"""
Tests for G2: SanitizingFormatter redacts secrets in tracebacks.

Covers:
- Bot token, session string, cookie header, auth header, phone number are
  redacted in the formatted output (including traceback text).
- SanitizingFormatter.format() redacts exc_info tracebacks.
- Existing SensitiveDataFilter patterns still work.
"""
import logging
import traceback
import pytest

from utils.log_sanitizer import (
    SensitiveDataFilter,
    SanitizingFormatter,
    sanitize_string,
)

# ── Helper: build a LogRecord with an attached exception ──────────────────────

def _make_exc_record(msg: str, secret_in_exc: str) -> logging.LogRecord:
    """Raise a ValueError that carries a secret, catch it, attach to a LogRecord."""
    try:
        raise ValueError(secret_in_exc)
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    return record


# ── SanitizingFormatter tests ─────────────────────────────────────────────────

class TestSanitizingFormatter:

    def _fmt(self) -> SanitizingFormatter:
        return SanitizingFormatter('%(levelname)s %(message)s')

    def test_bot_token_in_traceback_is_redacted(self):
        """A bot token that appears inside a traceback must be redacted."""
        secret = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        record = _make_exc_record("download failed", secret)
        output = self._fmt().format(record)
        assert secret not in output
        assert "REDACTED" in output

    def test_session_string_in_traceback_is_redacted(self):
        """A long base64 session string in an exception message must be redacted."""
        # 100-char base64-looking string
        secret = "A" * 80 + "BBB="
        record = _make_exc_record("auth error", secret)
        output = self._fmt().format(record)
        assert secret not in output
        assert "REDACTED" in output

    def test_cookie_header_is_redacted(self):
        """Cookie: header value in a message is redacted."""
        text = "Cookie: session=abc123xyz"
        output = sanitize_string(text)
        assert "abc123xyz" not in output
        assert "REDACTED" in output

    def test_set_cookie_header_is_redacted(self):
        """Set-Cookie: header value is redacted."""
        text = "Set-Cookie: auth_token=supersecret; Path=/"
        output = sanitize_string(text)
        assert "supersecret" not in output
        assert "REDACTED" in output

    def test_auth_header_bearer_redacted(self):
        """Authorization: Bearer <token> is redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
        output = sanitize_string(text)
        assert "eyJhbGciOiJIUzI1NiJ9.secret" not in output
        assert "REDACTED" in output

    def test_auth_header_basic_redacted(self):
        """Authorization: Basic <creds> is redacted."""
        text = "Authorization: Basic dXNlcjpwYXNz"
        output = sanitize_string(text)
        assert "dXNlcjpwYXNz" not in output
        assert "REDACTED" in output

    def test_phone_number_redacted(self):
        """Phone number with country code is redacted."""
        text = "Sending OTP to +12025551234"
        output = sanitize_string(text)
        assert "+12025551234" not in output
        assert "REDACTED" in output

    def test_phone_number_not_over_triggered(self):
        """Short numeric strings (< 7 digits) are NOT redacted as phone numbers."""
        text = "retry attempt +3"
        output = sanitize_string(text)
        # +3 should remain intact
        assert "+3" in output

    def test_sanitizing_formatter_redacts_message(self):
        """SanitizingFormatter redacts a bot token in the plain log message."""
        token = "9876543210:ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZaaa"
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__,
            lineno=0, msg=f"token={token}", args=(), exc_info=None,
        )
        output = SanitizingFormatter('%(message)s').format(record)
        assert token not in output
        assert "REDACTED" in output


class TestSensitiveDataFilterStillWorks:
    """Ensure existing filter tests still pass after G2 changes."""

    def test_bot_token_sanitized(self):
        token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        assert sanitize_string(token) == "***REDACTED-BOT-TOKEN***"

    def test_api_id_sanitized(self):
        text = "TELEGRAM_API_ID=12345678"
        result = sanitize_string(text)
        assert "12345678" not in result
        assert "REDACTED" in result
