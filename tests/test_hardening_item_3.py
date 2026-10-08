"""
Tests for hardening item 3:
Register an application error handler that logs ONE line for RetryAfter/NetworkError/TimedOut
(no traceback) and the full traceback for everything else.
"""
import logging
from unittest.mock import MagicMock
import pytest

from telegram.error import RetryAfter, NetworkError, TimedOut
from bot.telegram_bot import error_handler


@pytest.mark.asyncio
async def test_error_handler_retry_after_one_line_no_traceback(caplog):
    """RetryAfter -> one log line without traceback."""
    exc = RetryAfter(retry_after=40)
    ctx = MagicMock()
    ctx.error = exc

    with caplog.at_level(logging.DEBUG):
        await error_handler(update=None, context=ctx)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]

    assert len(warning_records) == 1, f"Expected 1 WARNING, got {len(warning_records)}"
    assert len(error_records) == 0, f"Expected 0 ERROR, got {len(error_records)}"
    assert "RetryAfter(40s)" in warning_records[0].message
    # No traceback in warning
    assert warning_records[0].exc_info is None


@pytest.mark.asyncio
async def test_error_handler_network_error_one_line_no_traceback(caplog):
    """NetworkError -> one log line without traceback."""
    exc = NetworkError("Connection reset")
    ctx = MagicMock()
    ctx.error = exc

    with caplog.at_level(logging.DEBUG):
        await error_handler(update=None, context=ctx)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]

    assert len(warning_records) == 1
    assert len(error_records) == 0
    assert warning_records[0].exc_info is None


@pytest.mark.asyncio
async def test_error_handler_timed_out_one_line_no_traceback(caplog):
    """TimedOut -> one log line without traceback."""
    exc = TimedOut("Request timed out")
    ctx = MagicMock()
    ctx.error = exc

    with caplog.at_level(logging.DEBUG):
        await error_handler(update=None, context=ctx)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]

    assert len(warning_records) == 1
    assert len(error_records) == 0
    assert warning_records[0].exc_info is None


@pytest.mark.asyncio
async def test_error_handler_value_error_logs_traceback(caplog):
    """ValueError -> full traceback logged."""
    exc = ValueError("unexpected handler crash")
    ctx = MagicMock()
    ctx.error = exc

    with caplog.at_level(logging.DEBUG):
        await error_handler(update=None, context=ctx)

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1, f"Expected at least 1 ERROR record, got {len(error_records)}"
    assert any(r.exc_info is not None for r in error_records), "Expected exc_info (traceback) on ERROR record"
