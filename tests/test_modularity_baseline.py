"""Baseline characterization tests for StoryFlow modularity refactoring.

These tests capture current behavior across:
1. Config & startup permissions
2. Queue downloader dispatch & routing
3. Bot handler exports and execution dispatch
"""

import os
import stat
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.queue import DownloadQueue, DownloadJob, JobStatus
from storyflow import _validate_admin_ids, _startup_permissions
import bot.handlers as handlers


# ---------------------------------------------------------------------------
# 1. Config & Startup Permissions Baseline
# ---------------------------------------------------------------------------

def test_validate_admin_ids_valid():
    assert _validate_admin_ids("123456789") == ["123456789"]
    assert _validate_admin_ids("123, -456, 789") == ["123", "-456", "789"]


def test_validate_admin_ids_invalid():
    with pytest.raises(SystemExit):
        _validate_admin_ids("invalid_id")


def test_startup_permissions_chmods_files(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST=1")
    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir()
    cookie_file = cookie_dir / "test.txt"
    cookie_file.write_text("cookie")

    _orig_exists = os.path.exists

    with patch.dict(os.environ, {"COOKIE_PATH": str(cookie_dir)}), \
         patch("os.path.exists", side_effect=lambda p: str(env_file) == p or _orig_exists(p)), \
         patch("glob.glob", return_value=[str(cookie_file)]):
        _startup_permissions()


# ---------------------------------------------------------------------------
# 2. Queue Downloader Dispatch Baseline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_dispatches_snapchat_non_spotlight_to_snapchat_downloader(tmp_path):
    """Snapchat story link must be routed to snapchat.download."""
    snapchat_mock = MagicMock()
    snapchat_mock.download = AsyncMock(return_value={"success": True, "files": ["/tmp/file.mp4"]})
    gallery_dl_mock = MagicMock()
    gallery_dl_mock.download = AsyncMock()

    queue = DownloadQueue(max_concurrent=1, max_per_user=5)
    queue.snapchat = snapchat_mock
    queue.gallery_dl = gallery_dl_mock
    queue.download_path = str(tmp_path / "out")

    upload_mock = AsyncMock()
    job = await queue.submit(
        user_id="123",
        url="https://snapchat.com/stories/username",
        platform="Snapchat",
        upload_func=upload_mock,
    )

    async def _process_one(q):
        q._running = True
        worker_task = asyncio.create_task(q._worker(0))
        await q._queue.join()
        q._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Process the queued job
    await _process_one(queue)

    snapchat_mock.download.assert_called_once_with(
        "https://snapchat.com/stories/username", "123", job.job_id
    )
    gallery_dl_mock.download.assert_not_called()
    upload_mock.assert_called_once_with(["/tmp/file.mp4"])


@pytest.mark.asyncio
async def test_queue_dispatches_snapchat_spotlight_to_gallery_dl(tmp_path):
    """Snapchat spotlight link must be routed to gallery_dl.download."""
    snapchat_mock = MagicMock()
    snapchat_mock.download = AsyncMock()
    gallery_dl_mock = MagicMock()
    gallery_dl_mock.download = AsyncMock(return_value={"success": True, "files": ["/tmp/spotlight.mp4"]})

    queue = DownloadQueue(max_concurrent=1, max_per_user=5)
    queue.snapchat = snapchat_mock
    queue.gallery_dl = gallery_dl_mock
    queue.download_path = str(tmp_path / "out")

    upload_mock = AsyncMock()
    await queue.submit(
        user_id="123",
        url="https://snapchat.com/spotlight/12345678",
        platform="Snapchat",
        upload_func=upload_mock,
    )

    async def _process_one(q):
        q._running = True
        worker_task = asyncio.create_task(q._worker(0))
        await q._queue.join()
        q._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    await _process_one(queue)

    gallery_dl_mock.download.assert_called_once()
    snapchat_mock.download.assert_not_called()
    upload_mock.assert_called_once_with(["/tmp/spotlight.mp4"])


@pytest.mark.asyncio
async def test_queue_dispatches_instagram_to_gallery_dl(tmp_path):
    """Instagram link must be routed to gallery_dl.download."""
    snapchat_mock = MagicMock()
    snapchat_mock.download = AsyncMock()
    gallery_dl_mock = MagicMock()
    gallery_dl_mock.download = AsyncMock(return_value={"success": True, "files": ["/tmp/reel.mp4"]})

    queue = DownloadQueue(max_concurrent=1, max_per_user=5)
    queue.snapchat = snapchat_mock
    queue.gallery_dl = gallery_dl_mock
    queue.download_path = str(tmp_path / "out")

    upload_mock = AsyncMock()
    await queue.submit(
        user_id="123",
        url="https://www.instagram.com/reel/123",
        platform="Instagram",
        upload_func=upload_mock,
    )

    async def _process_one(q):
        q._running = True
        worker_task = asyncio.create_task(q._worker(0))
        await q._queue.join()
        q._running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    await _process_one(queue)

    gallery_dl_mock.download.assert_called_once()
    snapchat_mock.download.assert_not_called()
    upload_mock.assert_called_once_with(["/tmp/reel.mp4"])


# ---------------------------------------------------------------------------
# 3. Handlers API Surface Baseline
# ---------------------------------------------------------------------------

def test_handlers_public_interface_preserved():
    """Ensure bot.handlers maintains its public exports during refactoring."""
    expected_exports = [
        "start",
        "help_command",
        "queue_command",
        "handle_url",
        "handle_document",
        "handle_admin_input",
        "JOB_MESSAGES",
    ]
    for name in expected_exports:
        assert hasattr(handlers, name), f"Missing expected export {name} in bot.handlers"
