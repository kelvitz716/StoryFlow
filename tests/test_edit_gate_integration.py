"""
Integration tests verifying update_job_status and safe_edit_text delegate to EditCoordinator.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.queue import DownloadJob, JobStatus
from bot.telegram_bot import update_job_status
from bot.uploader import safe_edit_text
from bot.edit_gate import EditCoordinator, set_edit_coordinator, get_edit_coordinator
from utils.bot_utils import JOB_MESSAGES


class DummyMessage:
    def __init__(self, chat_id=10, message_id=20):
        self.chat_id = chat_id
        self.message_id = message_id
        self.edited_texts = []

    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        self.edited_texts.append(text)


class DummyClock:
    def __init__(self):
        self.curr = 100.0

    def time(self):
        return self.curr

    async def sleep(self, seconds):
        self.curr += seconds


@pytest.mark.asyncio
async def test_update_job_status_delegates_to_coordinator():
    """Verify that update_job_status routes through EditCoordinator without direct awaiting."""
    clock = DummyClock()
    coord = EditCoordinator(clock=clock.time, sleep_func=clock.sleep)
    set_edit_coordinator(coord)

    msg = DummyMessage(chat_id=100, message_id=200)
    job_id = "test-job-int-1"
    JOB_MESSAGES[job_id] = msg

    job = DownloadJob(
        job_id=job_id,
        user_id="123",
        url="https://example.com/test",
        platform="snapchat",
    )
    job.status = JobStatus.DOWNLOADING
    job.message = "Downloading story..."

    mock_app = MagicMock()
    await update_job_status(mock_app, job)

    # Immediately after update_job_status, coordinator has the pending edit
    await coord.flush("100")
    assert len(msg.edited_texts) == 1
    assert "Downloading..." in msg.edited_texts[0]

    JOB_MESSAGES.pop(job_id, None)


@pytest.mark.asyncio
async def test_update_job_status_handles_none_status_msg():
    """Verify that update_job_status handles nonexistent status_msg safely."""
    mock_app = MagicMock()
    job = DownloadJob(
        job_id="nonexistent-job",
        user_id="123",
        url="https://example.com/test",
        platform="snapchat",
    )
    job.status = JobStatus.COMPLETED
    # Should not raise exception
    await update_job_status(mock_app, job)


@pytest.mark.asyncio
async def test_safe_edit_text_delegates_to_coordinator():
    """Verify safe_edit_text delegates to EditCoordinator."""
    clock = DummyClock()
    coord = EditCoordinator(clock=clock.time, sleep_func=clock.sleep)
    set_edit_coordinator(coord)

    msg = DummyMessage(chat_id=300, message_id=400)
    await safe_edit_text(msg, "Batch upload 1/2")

    await coord.flush("300")
    assert len(msg.edited_texts) == 1
    assert msg.edited_texts[0] == "Batch upload 1/2"


@pytest.mark.asyncio
async def test_safe_edit_text_none_message_safe():
    """Verify safe_edit_text handles None message safely."""
    await safe_edit_text(None, "Text")
