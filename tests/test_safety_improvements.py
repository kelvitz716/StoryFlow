"""
Unit tests for Safety & Stability improvements (Step 1).
- core/storage.py: No infinite loops on non-existent relative paths.
- downloaders/gallery_dl.py: Cookie fallback privacy (never leak other users' cookies; support multi-admin IDs).
- downloaders/base.py: Subprocess termination on asyncio task cancellation.
- bot/handlers/admin.py: Deletion of plaintext 2FA password message.
- auth/mtproto.py: Zero-division guard and handle rewinding.
"""
import os
import signal
import tempfile
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from core.storage import get_storage_info, is_storage_critical
from downloaders.base import BaseDownloader
from downloaders.gallery_dl import GalleryDLDownloader


def test_storage_info_nonexistent_relative_path_does_not_loop():
    """Ensure get_storage_info resolves non-existent relative path without infinite loop."""
    # A nested relative path guaranteed not to exist
    non_existent = "some_random_nonexistent_subfolder/deep/nested/dir"
    info = get_storage_info(non_existent)
    assert info is not None
    assert info["total"] > 0
    assert info["percent_used"] >= 0
    assert "path" in info


def test_is_storage_critical_nonexistent_path():
    """is_storage_critical returns boolean without hanging."""
    critical, percent = is_storage_critical("non_existent_folder_xyz_123", threshold=99.9)
    assert isinstance(critical, bool)
    assert isinstance(percent, (int, float))


def test_cookie_fallback_never_leaks_other_users_cookies():
    """_get_fallback_cookie must never return another user's cookie file."""
    with tempfile.TemporaryDirectory() as cookie_dir:
        platform = "instagram"
        user_id = "user_victim"
        other_user = "user_attacker"

        # Create cookies for another user
        other_cookie = os.path.join(cookie_dir, f"{platform}_{other_user}.txt")
        with open(other_cookie, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")

        dl = GalleryDLDownloader(
            output_path=tempfile.mkdtemp(),
            cookie_path=cookie_dir,
            admin_id="admin1"
        )

        # Lookup for user_victim must NOT return other_user's cookie!
        res = dl._get_cookie_file(platform, user_id)
        assert res is None, f"Cross-user cookie leaked: {res}"


def test_cookie_fallback_multi_admin_support():
    """_get_fallback_cookie supports comma-separated ADMIN_USER_ID when fallback is enabled."""
    with tempfile.TemporaryDirectory() as cookie_dir:
        platform = "instagram"
        admin1 = "1001"
        admin2 = "1002"
        user_id = "5555"

        # Create cookie for the second admin in the list
        admin2_cookie = os.path.join(cookie_dir, f"{platform}_{admin2}.txt")
        with open(admin2_cookie, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")

        with patch.dict(os.environ, {"ALLOW_ADMIN_COOKIE_FALLBACK": "true"}):
            import importlib
            import downloaders.gallery_dl as gdl_mod
            importlib.reload(gdl_mod)

            dl = gdl_mod.GalleryDLDownloader(
                output_path=tempfile.mkdtemp(),
                cookie_path=cookie_dir,
                admin_id=f"{admin1}, {admin2}"
            )

            fallback = dl._get_cookie_file(platform, user_id)
            assert fallback == admin2_cookie


@pytest.mark.asyncio
async def test_subprocess_killed_on_task_cancellation():
    """Verify that cancelling the async task kills the spawned subprocess group."""
    dl = BaseDownloader(output_path=tempfile.mkdtemp())

    # Mock process that stays running
    proc = MagicMock()
    proc.returncode = None
    proc.pid = 98765

    # Mock readline that hangs until cancelled
    async def hang_readline():
        await asyncio.sleep(100)
        return b""

    proc.stdout.readline = AsyncMock(side_effect=hang_readline)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(side_effect=hang_readline)
    proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with patch("os.getpgid", return_value=98765):
            with patch("os.killpg") as mock_killpg:
                task = asyncio.create_task(
                    dl._execute_with_retry(["sleep", "100"], process_name="test_cancel")
                )
                await asyncio.sleep(0.05)  # Let it start
                task.cancel()

                with pytest.raises(asyncio.CancelledError):
                    await task

                mock_killpg.assert_called_with(98765, signal.SIGKILL)


@pytest.mark.asyncio
async def test_admin_2fa_password_message_deleted():
    """Verify that plaintext 2FA password messages sent by admin are deleted immediately."""
    from bot.handlers import admin as admin_handlers

    admin_id = "123456"
    admin_handlers.AUTH_PENDING = asyncio.Future()
    admin_handlers.AUTH_TYPE = "password"
    admin_handlers.AUTH_ADMIN_ID = admin_id

    update = MagicMock()
    update.effective_user.id = int(admin_id)
    update.message.text = "my_secret_2fa_cloud_password"
    update.message.delete = AsyncMock()
    update.effective_chat.send_message = AsyncMock()

    await admin_handlers.handle_auth_input(update, MagicMock())

    # 1. Result was set on the future
    assert admin_handlers.AUTH_PENDING.result() == "my_secret_2fa_cloud_password"
    # 2. Message was deleted
    update.message.delete.assert_called_once()
    # 3. Confirmation message sent
    update.effective_chat.send_message.assert_called_once()
    assert "deleted from chat" in update.effective_chat.send_message.call_args[0][0]


def test_rate_limiter_allows_and_blocks():
    """Verify rate limiter allows up to max_requests and paces execution."""
    from core.rate_limiter import RateLimiter
    import time

    rl = RateLimiter(max_requests=2, time_window=1)
    t0 = time.time()
    rl.wait_if_needed()
    rl.wait_if_needed()
    # 2 requests fired immediately
    assert time.time() - t0 < 0.5
    assert rl.get_remaining() == 0


def test_edit_gate_discarded_messages_lru_bounded():
    """Verify _discarded_messages does not grow beyond _LRU_MAX_ENTRIES."""
    from bot.edit_gate import EditCoordinator

    coord = EditCoordinator()
    dummy_msg = MagicMock()
    dummy_msg.chat_id = 12345
    limit = coord._LRU_MAX_ENTRIES

    for i in range(limit + 50):
        dummy_msg.message_id = i
        coord.discard(dummy_msg)

    assert len(coord._discarded_messages) == limit
    # Oldest 50 messages were evicted
    assert 0 not in coord._discarded_messages
    assert (limit + 49) in coord._discarded_messages


def test_save_cookie_file_sets_0600_permissions():
    """Verify saved cookie file has 0600 permissions."""
    import stat
    from auth.cookies import CookieManager

    with tempfile.TemporaryDirectory() as cookie_dir:
        cm = CookieManager(cookie_path=cookie_dir)
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tFALSE\t2000000000\tsessionid\tabc\n")
            src_file = tf.name

        try:
            res = cm.save_cookie_file(user_id="123456", platform="instagram", file_path=src_file)
            assert res["success"] is True
            cookie_path = res["cookie_file"]
            mode = os.stat(cookie_path).st_mode & 0o777
            assert mode == (stat.S_IRUSR | stat.S_IWUSR)  # 0600
        finally:
            if os.path.exists(src_file):
                os.remove(src_file)


def test_access_manager_is_allowed_caching():
    """Verify is_allowed caches positive and negative responses and invalidates on mutation."""
    from auth.access import AccessManager

    am = AccessManager(admin_id="999999")
    test_user = "12345678"

    # Initially not allowed
    assert am.is_allowed(test_user) is False
    assert test_user in am._cache
    assert am._cache[test_user][0] is False

    # Add user -> cache updated to True
    am.add_user(test_user)
    assert am.is_allowed(test_user) is True
    assert am._cache[test_user][0] is True

    # Remove user -> cache updated to False
    am.remove_user(test_user)
    assert am.is_allowed(test_user) is False
    assert am._cache[test_user][0] is False


@pytest.mark.asyncio
async def test_async_save_to_db():
    """Verify DownloadJob.save_to_db() is awaitable and persists to DB."""
    from core.queue import DownloadJob, JobStatus
    from core.database import db

    job = DownloadJob(
        job_id="test_async_job_1",
        user_id="123",
        chat_id="456",
        message_id=789,
        url="https://instagram.com/p/123",
        platform="Instagram",
        status=JobStatus.DOWNLOADING,
    )

    await job.save_to_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", ("test_async_job_1",)).fetchone()
        assert row is not None
        assert row["status"] == "downloading"


def test_startup_sweep_preserves_non_job_directories():
    """Verify _startup_sweep only deletes 8-hex-char job directories and preserves other folders."""
    from core.queue import DownloadQueue

    with tempfile.TemporaryDirectory() as dl_dir:
        # 1. Job directory (8 hex chars)
        job_dir = os.path.join(dl_dir, "4fb09d5c")
        os.makedirs(job_dir, exist_ok=True)

        # 2. Non-job directory (e.g. cookies, static, other folders)
        keep_dir = os.path.join(dl_dir, "custom_folder")
        os.makedirs(keep_dir, exist_ok=True)

        q = DownloadQueue(download_path=dl_dir)
        q._startup_sweep()

        # Job directory deleted
        assert not os.path.exists(job_dir)
        # Custom directory preserved
        assert os.path.exists(keep_dir)


def test_format_error_message_uses_v1_escaping():
    """Verify format_error_message uses Markdown V1 escaping (does not escape periods/hyphens)."""
    from utils.bot_utils import format_error_message

    msg = format_error_message("File not found: test-file.mp4 (404 error)")
    # V2 would have turned . and - into \. and \-
    assert r"\." not in msg
    assert r"\-" not in msg
    assert "*Error*" in msg


def test_cookie_manager_list_cookies_uses_mtime_cache():
    """Verify list_cookies caches cookie expiry based on file mtime."""
    from auth.cookies import CookieManager

    with tempfile.TemporaryDirectory() as cookie_dir:
        cm = CookieManager(cookie_path=cookie_dir)
        cookie_file = os.path.join(cookie_dir, "instagram_user123.txt")
        with open(cookie_file, "w") as f:
            f.write("# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tFALSE\t2000000000\tsessionid\tabc\n")

        # First call populates cache
        cookies = cm.list_cookies("user123")
        assert len(cookies) == 1
        assert cookie_file in cm._expiry_cache

        # Subsequent call uses cache
        cached_tuple = cm._expiry_cache[cookie_file]
        cookies2 = cm.list_cookies("user123")
        assert len(cookies2) == 1
        assert cm._expiry_cache[cookie_file] == cached_tuple


def test_format_size_units():
    """Verify format_size correctly formats bytes across different unit scales."""
    from core.storage import format_size

    assert format_size(0) == "0 B"
    assert format_size(-10) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1536) == "1.5 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 * 1024 * 124.5) == "124.5 MB"
    assert format_size(1024 * 1024 * 1024 * 2.5) == "2.5 GB"


def test_get_directory_size_nested():
    """Verify get_directory_size recursively calculates byte size and top-level item count."""
    from core.storage import get_directory_size

    with tempfile.TemporaryDirectory() as dl_dir:
        # Empty directory
        size, count = get_directory_size(dl_dir)
        assert size == 0
        assert count == 0

        # Create top-level file (100 bytes)
        file1 = os.path.join(dl_dir, "file1.txt")
        with open(file1, "wb") as f:
            f.write(b"x" * 100)

        # Create top-level subdirectory with 2 nested files (300 bytes total)
        subdir = os.path.join(dl_dir, "job_12345678")
        os.makedirs(subdir, exist_ok=True)
        file2 = os.path.join(subdir, "video.mp4")
        with open(file2, "wb") as f:
            f.write(b"y" * 200)
        file3 = os.path.join(subdir, "thumb.jpg")
        with open(file3, "wb") as f:
            f.write(b"z" * 100)

        # Total size = 100 + 200 + 100 = 400 bytes, top-level items = 2 (file1 + subdir)
        size, count = get_directory_size(dl_dir)
        assert size == 400
        assert count == 2


@pytest.mark.asyncio
async def test_purge_confirm_callback_displays_space_to_recover():
    """Verify menu_purge_confirm shows space to recover and item count."""
    from bot.handlers.callbacks import button_callback

    with tempfile.TemporaryDirectory() as dl_dir:
        # Create a sample file
        sample_file = os.path.join(dl_dir, "video.mp4")
        with open(sample_file, "wb") as f:
            f.write(b"A" * 1024 * 500)  # 500 KB

        # Mock update and callback query
        query = MagicMock()
        query.data = "menu_purge_confirm"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 12345

        access_mgr = MagicMock()
        access_mgr.is_admin.return_value = True
        access_mgr.is_allowed.return_value = True

        cookie_mgr = MagicMock()
        stats_mgr = MagicMock()

        queue = MagicMock()
        queue.download_path = dl_dir

        ctx = MagicMock()

        await button_callback(
            update=update,
            context=ctx,
            access_manager=access_mgr,
            cookie_manager=cookie_mgr,
            stats_manager=stats_mgr,
            download_queue=queue
        )

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "⚠️ *System Purge*" in call_text
        assert "Space to recover:" in call_text
        assert "500.0 KB" in call_text
        assert "1 item" in call_text


@pytest.mark.asyncio
async def test_purge_execution_callback_displays_recovered_space():
    """Verify purge_confirm executes deletion and reports recovered space."""
    from bot.handlers.callbacks import button_callback

    with tempfile.TemporaryDirectory() as dl_dir:
        sample_file = os.path.join(dl_dir, "video.mp4")
        with open(sample_file, "wb") as f:
            f.write(b"B" * 1024 * 1024 * 2)  # 2.0 MB

        query = MagicMock()
        query.data = "purge_confirm"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 12345

        access_mgr = MagicMock()
        access_mgr.is_admin.return_value = True
        access_mgr.is_allowed.return_value = True

        queue = MagicMock()
        queue.download_path = dl_dir

        await button_callback(
            update=update,
            context=MagicMock(),
            access_manager=access_mgr,
            cookie_manager=MagicMock(),
            stats_manager=MagicMock(),
            download_queue=queue
        )

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "✅ *Purge Complete*" in call_text
        assert "Recovered `2.0 MB` (1 item)" in call_text
        assert not os.path.exists(sample_file)

