"""
Tests for G2 / K1: SanitizingFormatter and SensitiveDataFilter redacts secrets in logs and tracebacks.

Covers:
- URLsafe base64 session strings (>=200 chars).
- Cookie header redaction (full rest of line).
- Cookie key-value redactions (bare and inside headers).
- Phone numbers, bot tokens, api hash, auth headers.
- Untouched lines: ordinary log lines, URLs <200 chars, 32-char job IDs.
"""
import base64
import logging
import os
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


# ── SanitizingFormatter and Pattern tests ─────────────────────────────────────

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

    def test_session_string_random_200_trials(self):
        """Build session string with base64.urlsafe_b64encode(os.urandom(263)).decode().rstrip('='). Repeat 200 times.
        After sanitizing, no 20-character substring of the original may remain."""
        for _ in range(200):
            orig = base64.urlsafe_b64encode(os.urandom(263)).decode().rstrip("=")
            sanitized = sanitize_string(f"session={orig}")
            assert orig not in sanitized
            # Check that no 20-character substring of orig remains in sanitized
            for i in range(len(orig) - 20 + 1):
                sub = orig[i:i + 20]
                assert sub not in sanitized, f"Found 20-char leak '{sub}' in sanitized output: {sanitized}"

    def test_cookie_header_leaks_neither_value(self):
        """'Cookie: a=1; sessionid=SECRET; csrftoken=TOK' leaks neither value."""
        text = "Cookie: a=1; sessionid=SECRET; csrftoken=TOK"
        sanitized = sanitize_string(text)
        assert "SECRET" not in sanitized
        assert "TOK" not in sanitized
        assert "REDACTED" in sanitized

    def test_bare_cookie_kv_leaks_neither_value(self):
        """The bare form 'sessionid=SECRET csrftoken=TOK' leaks neither value."""
        text = "sessionid=SECRET csrftoken=TOK"
        sanitized = sanitize_string(text)
        assert "SECRET" not in sanitized
        assert "TOK" not in sanitized
        assert "sessionid=" in sanitized
        assert "csrftoken=" in sanitized
        assert "REDACTED" in sanitized

    def test_set_cookie_header_is_redacted(self):
        """Set-Cookie: header value is redacted completely."""
        text = "Set-Cookie: auth_token=supersecret; Path=/"
        output = sanitize_string(text)
        assert "supersecret" not in output
        assert "Path=/" not in output
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
        assert "+3" in output

    def test_ordinary_log_lines_unchanged(self):
        """Ordinary log lines remain unchanged."""
        text = "Downloading 5 files from Instagram for user 12345"
        assert sanitize_string(text) == text

    def test_urls_under_200_chars_unchanged(self):
        """URLs under 200 characters are not treated as session strings."""
        url = "https://instagram.com/p/C_abc123XYZ_xyz?igsh=MXZ5aW12ODZ4eQ=="
        assert len(url) < 200
        assert sanitize_string(url) == url

    def test_32_character_job_id_unchanged(self):
        """A 32-character job ID (non-hex or non-api_hash) is unchanged, except for existing api_hash rule if 32 hex chars."""
        # 32-char uuid without hyphens contains non-hex or hyphenated uuid
        job_id = "job_abcdefghijklmnopqrstuvwxyz12"
        assert len(job_id) == 32
        assert sanitize_string(job_id) == job_id


class TestSensitiveDataFilterStillWorks:
    """Ensure existing filter tests still pass."""

    def test_bot_token_sanitized(self):
        token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        assert sanitize_string(token) == "***REDACTED-BOT-TOKEN***"

    def test_api_id_sanitized(self):
        text = "TELEGRAM_API_ID=12345678"
        result = sanitize_string(text)
        assert "12345678" not in result
        assert "REDACTED" in result
