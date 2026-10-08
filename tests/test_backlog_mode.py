"""
Tests for backlog mode in bot.handlers.handle_url.
Verifies rate-limiting, single summary message burst grouping, and submission pacing.
"""
import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, AsyncMock

from bot.handlers import handle_url, _CHAT_BURSTS, _LAST_BACKLOG_SUBMIT
from bot.edit_gate import EditCoordinator, set_edit_coordinator
from core.queue import DownloadJob, JobStatus


class FakeClock:
    def __init__(self, start_time: float = 2000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += seconds
        await asyncio.sleep(0)


class MockMessage:
    def __init__(self, chat_id: int, message_id: int, text: str, date: datetime):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text
        self.date = date
        self.is_automatic_forward = False
        self.sender_chat = None
        self.reply_calls = []

    async def reply_text(self, text, parse_mode=None, **kwargs):
        msg = MockSummaryMessage(self.chat_id, self.message_id + 1000, text)
        self.reply_calls.append({"text": text, "parse_mode": parse_mode, "msg": msg})
        return msg


class MockSummaryMessage:
    def __init__(self, chat_id: int, message_id: int, initial_text: str):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = initial_text
        self.edit_calls = []

    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        self.text = text
        self.edit_calls.append({"text": text, "parse_mode": parse_mode})


def make_update(chat_id: int, message_id: int, url: str, date: datetime):
    msg = MockMessage(chat_id, message_id, url, date)
    update = MagicMock()
    update.channel_post = None
    update.effective_message = msg
    update.effective_user = MagicMock(id=123)
    update.effective_chat = MagicMock(id=chat_id)
    return update, msg


@pytest.mark.asyncio
async def test_10_backlog_updates_one_summary_and_spaced_submissions():
    """
    10 updates dated 5 minutes ago -> exactly one summary reply,
    job submissions >=1.5s apart.
    """
    _CHAT_BURSTS.clear()
    _LAST_BACKLOG_SUBMIT.clear()

    fake_clock = FakeClock(start_time=2000.0)
    coord = EditCoordinator(
        edit_min_interval=1.5,
        msg_min_interval=3.5,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    chat_id = 999
    # 5 minutes ago = 300s before start_time
    past_date = datetime.fromtimestamp(1700.0, tz=timezone.utc)

    submission_times = []
    mock_queue = MagicMock()

    async def fake_submit(*args, **kwargs):
        submission_times.append(fake_clock.time())
        return DownloadJob(
            job_id=f"job-{len(submission_times)}",
            user_id="123",
            url=kwargs.get("url", "https://instagram.com/p/test"),
            platform="instagram",
        )

    mock_queue.submit = AsyncMock(side_effect=fake_submit)
    mock_queue.get_queue_position = MagicMock(return_value=1)

    access_mgr = MagicMock()
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False
    access_mgr.is_user_allowed.return_value = True

    context = MagicMock()
    context.user_data = {}

    messages = []
    for i in range(10):
        update, msg = make_update(chat_id, 100 + i, f"https://instagram.com/p/test{i}", past_date)
        messages.append(msg)
        await handle_url(update, context, access_mgr, mock_queue)

    await coord.flush(str(chat_id))

    # Exactly one reply_text was made across all 10 messages (the summary reply)
    total_replies = [call for m in messages for call in m.reply_calls]
    assert len(total_replies) == 1
    assert "Back online: processing 1 queued links" in total_replies[0]["text"]

    # The summary message itself was updated as links arrived
    summary_msg = total_replies[0]["msg"]
    assert "10 queued links" in summary_msg.text

    # 10 job submissions occurred
    assert len(submission_times) == 10
    # Every submission is >= 1.5s apart
    for idx in range(1, len(submission_times)):
        diff = submission_times[idx] - submission_times[idx - 1]
        assert diff >= 1.5 - 1e-6, f"Submissions {idx-1} and {idx} were only {diff}s apart!"


@pytest.mark.asyncio
async def test_fresh_message_behaves_normally():
    """One fresh (non-backlog) message behaves exactly as before."""
    _CHAT_BURSTS.clear()
    _LAST_BACKLOG_SUBMIT.clear()

    fake_clock = FakeClock(start_time=2000.0)
    coord = EditCoordinator(
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    chat_id = 888
    # Fresh message: 5 seconds ago (< 60s BACKLOG_AGE_SECONDS)
    fresh_date = datetime.fromtimestamp(1995.0, tz=timezone.utc)

    mock_queue = MagicMock()
    job = DownloadJob(
        job_id="fresh-job-1",
        user_id="123",
        url="https://instagram.com/p/fresh",
        platform="instagram",
    )
    mock_queue.submit = AsyncMock(return_value=job)
    mock_queue.get_queue_position = MagicMock(return_value=1)

    access_mgr = MagicMock()
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False
    access_mgr.is_user_allowed.return_value = True

    context = MagicMock()
    context.user_data = {}

    update, msg = make_update(chat_id, 200, "https://instagram.com/p/fresh", fresh_date)
    await handle_url(update, context, access_mgr, mock_queue)

    await coord.flush(str(chat_id))

    # Fresh message sends standard per-link processing message
    assert len(msg.reply_calls) == 1
    # Status message was queued and updated
    status_msg = msg.reply_calls[0]["msg"]
    assert "Queued" in status_msg.text
