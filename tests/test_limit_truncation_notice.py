import asyncio
import os
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.queue import DownloadJob, DownloadQueue, JobStatus


@pytest.mark.asyncio
async def test_limit_reached_produces_exactly_one_notice_after_upload():
    """A result with limit_reached: True and 3 files produces exactly one notice after upload."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    queue = DownloadQueue(max_concurrent=1, bot=mock_bot)
    mock_dl = MagicMock()
    mock_dl.download = AsyncMock(return_value={
        'success': True,
        'files': ['file1.mp4', 'file2.mp4', 'file3.mp4'],
        'limit_reached': True
    })
    queue.gallery_dl = mock_dl

    job = DownloadJob(
        job_id="job_limit_test",
        user_id="user12345",
        chat_id="chat12345",
        message_id=999,
        url="https://instagram.com/user/test",
        platform="Instagram"
    )
    queue._jobs[job.job_id] = job
    queue._running = True

    upload_mock = AsyncMock()
    await queue._queue.put((job, upload_mock))

    worker = asyncio.create_task(queue._worker(0))
    await asyncio.sleep(0.1)
    queue._running = False
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    # Verify upload was called
    upload_mock.assert_called_once_with(['file1.mp4', 'file2.mp4', 'file3.mp4'])

    # Verify job state
    assert job.status == JobStatus.COMPLETED
    assert job.limit_reached is True

    # Verify exactly one notice was sent after upload
    assert mock_bot.send_message.call_count == 1
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "chat12345"
    assert call_kwargs["reply_to_message_id"] == 999
    assert "Stopped at the download limit. The first 3 files were delivered." in call_kwargs["text"]
    # Ensure no internal env var names leaked to non-admin user
    assert "MAX_FILES_PER_JOB" not in call_kwargs["text"]
    assert "MAX_JOB_SIZE_MB" not in call_kwargs["text"]


@pytest.mark.asyncio
async def test_normal_result_produces_no_notice():
    """A normal result (limit_reached: False or omitted) produces none."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    queue = DownloadQueue(max_concurrent=1, bot=mock_bot)
    mock_dl = MagicMock()
    mock_dl.download = AsyncMock(return_value={
        'success': True,
        'files': ['file1.mp4', 'file2.mp4', 'file3.mp4']
    })
    queue.gallery_dl = mock_dl

    job = DownloadJob(
        job_id="job_normal_test",
        user_id="user12345",
        chat_id="chat12345",
        message_id=999,
        url="https://instagram.com/user/test",
        platform="Instagram"
    )
    queue._jobs[job.job_id] = job
    queue._running = True

    upload_mock = AsyncMock()
    await queue._queue.put((job, upload_mock))

    worker = asyncio.create_task(queue._worker(0))
    await asyncio.sleep(0.1)
    queue._running = False
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    # Verify upload was called
    upload_mock.assert_called_once_with(['file1.mp4', 'file2.mp4', 'file3.mp4'])

    # Verify job state
    assert job.status == JobStatus.COMPLETED
    assert job.limit_reached is False

    # Verify NO notice was produced
    assert mock_bot.send_message.call_count == 0
    assert job.limit_notice is None


@pytest.mark.asyncio
async def test_admin_limit_reached_notice_includes_exact_numbers(monkeypatch):
    """Admins may get the exact limit numbers in the notice."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    monkeypatch.setenv("ADMIN_USER_ID", "admin_user_99")

    queue = DownloadQueue(max_concurrent=1, bot=mock_bot)
    mock_dl = MagicMock()
    mock_dl.download = AsyncMock(return_value={
        'success': True,
        'files': ['file1.mp4', 'file2.mp4', 'file3.mp4'],
        'limit_reached': True
    })
    queue.gallery_dl = mock_dl

    job = DownloadJob(
        job_id="job_admin_limit_test",
        user_id="admin_user_99",
        chat_id="chat_admin_99",
        message_id=888,
        url="https://snapchat.com/add/test",
        platform="Snapchat"
    )
    queue._jobs[job.job_id] = job
    queue._running = True

    upload_mock = AsyncMock()
    await queue._queue.put((job, upload_mock))

    worker = asyncio.create_task(queue._worker(0))
    await asyncio.sleep(0.1)
    queue._running = False
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    assert mock_bot.send_message.call_count == 1
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Stopped at the download limit. The first 3 files were delivered." in call_kwargs["text"]
    assert "Admin info:" in call_kwargs["text"]
