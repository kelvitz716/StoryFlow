"""
Tests for backlog mode in bot.handlers.handle_url.
Verifies rate-limiting, single summary message burst grouping, and submission pacing.
"""
import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, AsyncMock

from bot.handlers import handle_url, _CHAT_BURSTS, _LAST_BACKLOG_SUBMIT, _BACKLOG_JOBS
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


@pytest.mark.asyncio
async def test_3_backlog_jobs_1_failing_summary_shows_2_done_1_failed():
    """
    3 backlog jobs, 1 failing -> summary shows 2 done, 1 failed.
    Verifies outcomes are recorded when jobs have no status message,
    and single summary is updated with failed links listed.
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

    chat_id = 777
    past_date = datetime.fromtimestamp(1700.0, tz=timezone.utc)

    jobs = []
    mock_queue = MagicMock()

    async def fake_submit(*args, **kwargs):
        j = DownloadJob(
            job_id=f"backlog-job-{len(jobs) + 1}",
            user_id="123",
            chat_id=str(chat_id),
            url=kwargs.get("url", f"https://instagram.com/p/test{len(jobs)}"),
            platform="instagram",
        )
        jobs.append(j)
        return j

    mock_queue.submit = AsyncMock(side_effect=fake_submit)
    mock_queue.get_queue_position = MagicMock(return_value=1)

    access_mgr = MagicMock()
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False
    access_mgr.is_user_allowed.return_value = True

    context = MagicMock()
    context.user_data = {}

    messages = []
    urls = [
        "https://instagram.com/p/success1",
        "https://instagram.com/p/fail1",
        "https://instagram.com/p/success2",
    ]
    for i, u in enumerate(urls):
        update, msg = make_update(chat_id, 300 + i, u, past_date)
        messages.append(msg)
        await handle_url(update, context, access_mgr, mock_queue)

    await coord.flush(str(chat_id))

    # Single summary message reply created
    total_replies = [call for m in messages for call in m.reply_calls]
    assert len(total_replies) == 1
    summary_msg = total_replies[0]["msg"]
    assert "3 queued links" in summary_msg.text

    assert len(jobs) == 3

    # Now simulate execution of jobs: job 0 succeeds, job 1 fails, job 2 succeeds
    from bot.telegram_bot import update_job_status
    app_mock = MagicMock()

    # Job 0 succeeds
    jobs[0].status = JobStatus.COMPLETED
    await update_job_status(app_mock, jobs[0])

    # Job 1 fails
    jobs[1].status = JobStatus.FAILED
    jobs[1].error = "Video is private"
    await update_job_status(app_mock, jobs[1])

    # Job 2 succeeds
    jobs[2].status = JobStatus.COMPLETED
    await update_job_status(app_mock, jobs[2])

    await coord.flush(str(chat_id))

    # Summary shows 2 done, 1 failed, 0 left
    assert "2 done, 1 failed" in summary_msg.text
    assert "0 left" in summary_msg.text
    # Failed links section lists the failed link
    assert "Failed links:" in summary_msg.text
    assert "https://instagram.com/p/fail1" in summary_msg.text


@pytest.mark.asyncio
async def test_backlog_failed_links_truncated_to_5_plus_and_n_more():
    """
    Backlog burst with >5 failures truncates failed links list to 5 plus 'and N more'.
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

    chat_id = 666
    past_date = datetime.fromtimestamp(1700.0, tz=timezone.utc)

    jobs = []
    mock_queue = MagicMock()

    async def fake_submit(*args, **kwargs):
        j = DownloadJob(
            job_id=f"trunc-job-{len(jobs) + 1}",
            user_id="123",
            chat_id=str(chat_id),
            url=kwargs.get("url", f"https://instagram.com/p/test{len(jobs)}"),
            platform="instagram",
        )
        jobs.append(j)
        return j

    mock_queue.submit = AsyncMock(side_effect=fake_submit)
    mock_queue.get_queue_position = MagicMock(return_value=1)

    access_mgr = MagicMock()
    access_mgr.is_system_sender.return_value = False
    access_mgr.is_anonymous_sender.return_value = False
    access_mgr.is_user_allowed.return_value = True

    context = MagicMock()
    context.user_data = {}

    # Queue 8 links: 1 succeeds, 7 fail
    messages = []
    for i in range(8):
        update, msg = make_update(chat_id, 400 + i, f"https://instagram.com/p/link{i}", past_date)
        messages.append(msg)
        await handle_url(update, context, access_mgr, mock_queue)

    await coord.flush(str(chat_id))

    total_replies = [call for m in messages for call in m.reply_calls]
    summary_msg = total_replies[0]["msg"]

    from bot.telegram_bot import update_job_status
    app_mock = MagicMock()

    # Job 0 succeeds
    jobs[0].status = JobStatus.COMPLETED
    await update_job_status(app_mock, jobs[0])

    # Jobs 1..7 fail
    for i in range(1, 8):
        jobs[i].status = JobStatus.FAILED
        jobs[i].error = "Download error"
        await update_job_status(app_mock, jobs[i])

    await coord.flush(str(chat_id))

    assert "1 done, 7 failed, 0 left" in summary_msg.text
    assert "Failed links:" in summary_msg.text
    # Exactly first 5 failed links appear
    for i in range(1, 6):
        assert f"https://instagram.com/p/link{i}" in summary_msg.text
    # 6th and 7th failed links are truncated
    assert "https://instagram.com/p/link6" not in summary_msg.text
    assert "https://instagram.com/p/link7" not in summary_msg.text
    # "and 2 more" is present
    assert "and 2 more" in summary_msg.text
