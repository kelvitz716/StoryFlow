"""
Tests for hardening item 5:
Stderr Tail Logging on Final Failure in BaseDownloader._execute_with_retry.
When a subprocess exhausts all retries and finally fails, log a sanitized,
truncated tail of stderr (last 500 characters, passed through the existing log sanitizer)
at WARNING. Ensure end-users still only receive generic, safe errors.
"""
import sys
import logging
import pytest
from downloaders.base import BaseDownloader


class ConcreteDownloader(BaseDownloader):
    pass


def _python_script_cmd(*lines: str) -> list:
    return [sys.executable, "-c", "\n".join(lines)]


@pytest.mark.asyncio
async def test_stderr_tail_logged_at_warning_on_final_failure(caplog):
    """
    When retries are exhausted, the last 500 characters of stderr must be
    sanitized and logged at WARNING level, while returning only safe generic errors.
    """
    bot_token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-12345678"
    # Create stderr > 600 chars with unique prefix and sensitive token in the tail
    start_prefix = "UNIQUE_START_OF_STDERR_THAT_MUST_BE_TRUNCATED_"
    long_middle = "X" * 600
    cmd = _python_script_cmd(
        "import sys",
        f"sys.stderr.write('{start_prefix}{long_middle} END_OF_LOG {bot_token}\\n')",
        "sys.stderr.flush()",
        "sys.exit(1)",
    )
    dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")

    with caplog.at_level(logging.WARNING):
        result = await dl._execute_with_retry(
            cmd,
            process_name="test_stderr_tail",
            max_attempts=2,
        )

    # User-facing result must be safe and generic
    assert result["success"] is False
    assert "error" in result
    assert result["error"] == "Download failed (code 1)"
    assert "stderr" not in result
    assert bot_token not in str(result)
    assert "PREFIX_ERR_" not in str(result)

    # Check WARNING log
    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "Stderr tail:" in r.message
    ]
    assert len(warning_records) == 1, f"Expected 1 WARNING with Stderr tail, got {len(warning_records)}"
    record = warning_records[0]

    # Verify sensitive data was redacted
    assert bot_token not in record.message
    assert "***REDACTED-BOT-TOKEN***" in record.message

    # Verify truncation: the logged tail should not exceed 500 chars (plus format prefix)
    # The tail extracted was stderr[-500:], so start_prefix must be truncated
    assert start_prefix not in record.message
    assert "END_OF_LOG" in record.message
