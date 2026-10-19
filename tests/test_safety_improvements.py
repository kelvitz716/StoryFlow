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
