"""
Tests for hardening item 1:
A link must never be dropped because its acknowledgement message failed.
- In handle_url wrap the status reply: on RetryAfter, open the chat gate in the coordinator,
  set status_msg=None and STILL submit the job.
- Also treat a chat whose gate is currently open as backlog mode, so no per-link replies are sent
  while flood-gated.
- Do the same for the "already active" and "queue full" replies.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from bot.edit_gate import (
    EditCoordinator,
    set_edit_coordinator,
    RetryAfter,
)
from bot.handlers import (
    handle_url,
    _CHAT_BURSTS,
    _LAST_BACKLOG_SUBMIT,
    _BACKLOG_JOBS,
)
from core.queue import DownloadJob


class FakeClock:
    def __init__(self, start_time: float = 2000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += max(0.0, seconds)
        await asyncio.sleep(0)


class FakeMessage:
    def __init__(self, chat_id: int = 100, message_id: int = 1,
                 url: str = "https://instagram.com/p/test",
                 date: datetime = None, clock_func=None):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = url
        self.date = date or datetime.fromtimestamp(1700.0, tz=timezone.utc)
        self.is_automatic_forward = False
        self.sender_chat = None
        self.reply_calls: list = []
        self._clock = clock_func
        self._reply_raises: Exception = None

    async def reply_text(self, text, parse_mode=None, **kwargs):
        if self._reply_raises is not None:
            exc = self._reply_raises
            self._reply_raises = None
            raise exc
        child = FakeMessage(
            chat_id=self.chat_id,
            message_id=self.message_id + 1000,
            clock_func=self._clock,
        )
        child.text = text
        self.reply_calls.append({"text": text, "parse_mode": parse_mode, "msg": child})
        return child


def make_update(msg: FakeMessage, user_id: int = 123):
    update = MagicMock()
    update.channel_post = None
    update.effective_message = msg
    update.effective_user = MagicMock(id=user_id)
    update.effective_chat = MagicMock(id=msg.chat_id)
    return update


def make_access_mgr():
    mgr = MagicMock()
    mgr.is_system_sender.return_value = False
    mgr.is_anonymous_sender.return_value = False
    mgr.is_allowed.return_value = True
    mgr.is_admin.return_value = False
    return mgr


def make_queue(jobs_store: list):
    mock_queue = MagicMock()

    async def fake_submit(*args, **kwargs):
        j = DownloadJob(
            job_id=f"job-{len(jobs_store) + 1}",
            user_id="123",
            url=kwargs.get("url", "https://instagram.com/p/test"),
            platform="instagram",
        )
        jobs_store.append(j)
        return j

    mock_queue.submit = AsyncMock(side_effect=fake_submit)
    mock_queue.get_queue_position = MagicMock(return_value=0)
    return mock_queue


@pytest.mark.asyncio
async def test_retry_after_on_reply_text_job_still_submitted():
    """
    reply_text raises RetryAfter(40) -> handler does not raise,
    the job IS submitted, and the coordinator gate is open.
    """
    _CHAT_BURSTS.clear()
    _LAST_BACKLOG_SUBMIT.clear()
    _BACKLOG_JOBS.clear()

    fake_clock = FakeClock(start_time=2000.0)
    coord = EditCoordinator(
        edit_min_interval=0.0,
        msg_min_interval=0.0,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    chat_id = 5001
    fresh_date = datetime.fromtimestamp(1995.0, tz=timezone.utc)

    jobs_submitted = []
    mock_queue = make_queue(jobs_submitted)

    msg = FakeMessage(chat_id=chat_id, message_id=1,
                      url="https://instagram.com/p/ra1", date=fresh_date,
                      clock_func=fake_clock.time)
    msg._reply_raises = RetryAfter(retry_after=40)

    update = make_update(msg)
    ctx = MagicMock()
    ctx.user_data = {}

    await handle_url(update, ctx, make_access_mgr(), mock_queue)
    await coord.flush(str(chat_id))

    assert len(jobs_submitted) == 1, f"Expected 1 job submitted, got {len(jobs_submitted)}"
    assert coord.send_gate_open(str(chat_id)), "Expected coordinator gate to be open after RetryAfter"


@pytest.mark.asyncio
async def test_gate_open_means_no_per_link_replies_for_next_5_links(monkeypatch):
    """
    reply_text raising RetryAfter(40): handler does not raise, the job IS submitted,
    gate is open, and the next 5 links in that chat send zero per-link replies.
    """
    monkeypatch.setenv("BACKLOG_SUBMIT_DELAY_SECONDS", "0")

    _CHAT_BURSTS.clear()
    _LAST_BACKLOG_SUBMIT.clear()
    _BACKLOG_JOBS.clear()

    fake_clock = FakeClock(start_time=2000.0)
    coord = EditCoordinator(
        edit_min_interval=0.0,
        msg_min_interval=0.0,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    chat_id = 5002
    fresh_date = datetime.fromtimestamp(1995.0, tz=timezone.utc)

    jobs_submitted = []
    mock_queue = make_queue(jobs_submitted)
    access_mgr = make_access_mgr()

    # Link 0: trigger RetryAfter(3600), gate opens
    msg0 = FakeMessage(chat_id=chat_id, message_id=10,
                       url="https://instagram.com/p/link0", date=fresh_date,
                       clock_func=fake_clock.time)
    msg0._reply_raises = RetryAfter(retry_after=3600)
    ctx = MagicMock()
    ctx.user_data = {}
    await handle_url(make_update(msg0), ctx, access_mgr, mock_queue)

    assert coord.send_gate_open(str(chat_id)), "Gate should be open after link 0"

    # Next 5 links in that chat must send zero per-link replies
    per_link_reply_counts = []
    for i in range(1, 6):
        msg_i = FakeMessage(chat_id=chat_id, message_id=10 + i,
                            url=f"https://instagram.com/p/link{i}",
                            date=fresh_date, clock_func=fake_clock.time)
        ctx_i = MagicMock()
        ctx_i.user_data = {}
        await handle_url(make_update(msg_i), ctx_i, access_mgr, mock_queue)
        per_link_reply_counts.append(len(msg_i.reply_calls))

    await coord.flush(str(chat_id))

    assert per_link_reply_counts == [0, 0, 0, 0, 0], f"Expected all zeros, got {per_link_reply_counts}"
    assert len(jobs_submitted) == 6, f"Expected 6 jobs submitted, got {len(jobs_submitted)}"
