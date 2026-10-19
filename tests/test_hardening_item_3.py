from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Item 3: Duplicate handling & update logging tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_url_logs_debug_update_fields(caplog):
    """Verify debug log at top of handle_url contains all required fields."""
    from bot.handlers import handle_url
    from unittest.mock import AsyncMock

    update = MagicMock()
    update.update_id = 998877
    update.edited_message = None
    update.edited_channel_post = None
    update.channel_post = None

    msg = MagicMock()
    msg.message_id = 5544
    msg.text = "https://instagram.com/p/test_dbg"
    msg.date = datetime.now(timezone.utc)
    msg.is_automatic_forward = True
    msg.sender_chat = MagicMock(id=-100123456)
    msg.reply_text = AsyncMock()

    update.message = msg
    update.effective_message = msg
    update.effective_chat = MagicMock(id=-100987654)
    update.effective_user = MagicMock(id=112233)

    access_mgr = MagicMock()
    access_mgr.is_allowed.return_value = True
    access_mgr.is_admin.return_value = False
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False

    queue_mock = MagicMock()
    queue_mock.submit = AsyncMock(return_value=None)

    with caplog.at_level(logging.DEBUG):
        await handle_url(update, MagicMock(), access_mgr, queue_mock)

    debug_records = [r.message for r in caplog.records if r.levelno == logging.DEBUG and "handle_url update_id=" in r.message]
    assert len(debug_records) >= 1, f"Expected debug log record, got: {caplog.records}"
    log_text = debug_records[0]
    assert "update_id=998877" in log_text
    assert "update_type=message" in log_text
    assert "chat_id=-100987654" in log_text
    assert "message_id=5544" in log_text
    assert "sender_chat_id=-100123456" in log_text
    assert "is_automatic_forward=True" in log_text


@pytest.mark.asyncio
async def test_handle_url_ignores_edited_message():
    """Verify edited_message updates are ignored by handle_url."""
    from bot.handlers import handle_url
    from unittest.mock import AsyncMock

    update = MagicMock()
    update.update_id = 1111
    update.message = None
    update.channel_post = None
    update.edited_channel_post = None

    edited_msg = MagicMock()
    edited_msg.text = "https://instagram.com/p/edited_url"
    update.edited_message = edited_msg
    update.effective_message = edited_msg

    queue_mock = MagicMock()
    queue_mock.submit = AsyncMock()

    await handle_url(update, MagicMock(), MagicMock(), queue_mock)
    # Must be ignored: submit is never called
    queue_mock.submit.assert_not_called()


@pytest.mark.asyncio
async def test_handle_url_ignores_edited_channel_post():
    """Verify edited_channel_post updates are ignored by handle_url."""
    from bot.handlers import handle_url
    from unittest.mock import AsyncMock

    update = MagicMock()
    update.update_id = 2222
    update.message = None
    update.channel_post = None
    update.edited_message = None

    edited_cp = MagicMock()
    edited_cp.text = "https://instagram.com/p/edited_cp"
    update.edited_channel_post = edited_cp
    update.effective_message = edited_cp

    queue_mock = MagicMock()
    queue_mock.submit = AsyncMock()

    await handle_url(update, MagicMock(), MagicMock(), queue_mock)
    queue_mock.submit.assert_not_called()


@pytest.mark.asyncio
async def test_already_active_job_does_not_overwrite_status_msg():
    """
    If download_queue.submit returns an already-active job:
    do not register_job_message over it, and delete the redundant status message.
    """
    from bot.handlers import handle_url
    from utils.bot_utils import JOB_MESSAGES, register_job_message
    from core.queue import DownloadJob
    from unittest.mock import AsyncMock

    chat_id = 9901
    existing_job = DownloadJob(
        job_id="job-active-1",
        user_id="user1",
        url="https://instagram.com/p/active_link",
        platform="Instagram",
    )
    existing_job.is_already_active = True

    # Register initial status message
    initial_status_msg = MagicMock()
    register_job_message("job-active-1", initial_status_msg)

    # Second link arrives for the same URL
    new_status_msg = MagicMock()
    new_status_msg.delete = AsyncMock()

    msg = MagicMock()
    msg.message_id = 7788
    msg.text = "https://instagram.com/p/active_link"
    msg.date = datetime.now(timezone.utc)
    msg.is_automatic_forward = False
    msg.sender_chat = None
    msg.reply_text = AsyncMock(return_value=new_status_msg)

    update = MagicMock()
    update.update_id = 3333
    update.edited_message = None
    update.edited_channel_post = None
    update.channel_post = None
    update.message = msg
    update.effective_message = msg
    update.effective_chat = MagicMock(id=chat_id)
    update.effective_user = MagicMock(id=123)

    access_mgr = MagicMock()
    access_mgr.is_allowed.return_value = True
    access_mgr.is_admin.return_value = False
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False

    queue_mock = MagicMock()
    queue_mock.submit = AsyncMock(return_value=existing_job)
    queue_mock.get_queue_position.return_value = 0

    ctx = MagicMock()
    ctx.user_data = {}

    await handle_url(update, ctx, access_mgr, queue_mock)

    # 1. Redundant status message was deleted
    new_status_msg.delete.assert_called_once()
    # 2. JOB_MESSAGES was NOT overwritten (still points to initial_status_msg)
    assert JOB_MESSAGES["job-active-1"] is initial_status_msg

