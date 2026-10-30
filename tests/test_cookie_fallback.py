"""
Tests for item 8: cookie fallback opt-in and consistent file naming.
- Admin fallback is off by default; enabled only with ALLOW_ADMIN_COOKIE_FALLBACK=true.
- GalleryDLDownloader._get_cookie_file and CookieManager.get_cookie_file resolve
  the same filename for the same (platform, user_id) pair.
"""
import os
import re
import tempfile
import pytest
from unittest.mock import patch

import downloaders.gallery_dl as gdl_module  # noqa: F401 — keep for reload tests


def _sanitize(name: str) -> str:
    """Replicate the common sanitization rule used by both classes."""
    return re.sub(r'[^\w\-]', '', name) or 'unknown'


class TestCookieFileNamingConsistency:
    """Gallery-dl and CookieManager must agree on cookie file paths."""

    @pytest.mark.parametrize("user_id", ["123", "-1001234567890", "abc_def-1", "weird!@#$%"])
    def test_same_path_for_all_user_ids(self, user_id):
        """
        For every user_id, the filename produced by GalleryDLDownloader._get_cookie_file
        (when the file does not exist) must match what CookieManager.get_cookie_file
        would generate.
        """
        platform = "instagram"
        with tempfile.TemporaryDirectory() as cookie_dir:
            # CookieManager path
            cm_path = os.path.join(
                cookie_dir,
                f"{_sanitize(platform)}_{_sanitize(user_id)}.txt"
            )
            # GalleryDLDownloader path
            from downloaders.gallery_dl import GalleryDLDownloader
            dl = GalleryDLDownloader(
                output_path=tempfile.mkdtemp(),
                cookie_path=cookie_dir,
                admin_id="9999"
            )
            # Neither file exists; _get_cookie_file returns None.
            # We probe by creating the file at the CM path and checking dl finds it.
            with open(cm_path, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
            result = dl._get_cookie_file(platform, user_id)
            assert result == cm_path, (
                f"Mismatch for user_id={user_id!r}: dl returned {result!r}, expected {cm_path!r}"
            )


class TestAdminCookieFallbackOptIn:
    """Admin fallback must be disabled by default and enabled only via env."""

    def test_admin_fallback_disabled_by_default(self):
        """Without ALLOW_ADMIN_COOKIE_FALLBACK, admin cookie is never returned."""
        with tempfile.TemporaryDirectory() as cookie_dir:
            platform = "instagram"
            admin_id = "9999"
            user_id = "1111"

            # Create the admin cookie file
            s_admin = _sanitize(admin_id)
            admin_path = os.path.join(cookie_dir, f"{platform}_{s_admin}.txt")
            with open(admin_path, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")

            from downloaders.gallery_dl import GalleryDLDownloader
            with patch.dict(os.environ, {'ALLOW_ADMIN_COOKIE_FALLBACK': 'false'}):
                # Re-import to pick up the patched env
                import importlib
                import downloaders.gallery_dl as _m
                importlib.reload(_m)
                dl = _m.GalleryDLDownloader(
                    output_path=tempfile.mkdtemp(),
                    cookie_path=cookie_dir,
                    admin_id=admin_id
                )
                result = dl._get_cookie_file(platform, user_id)

            assert result is None, (
                f"Admin fallback leaked when ALLOW_ADMIN_COOKIE_FALLBACK=false: {result!r}"
            )

    def test_admin_fallback_enabled_when_opted_in(self):
        """With ALLOW_ADMIN_COOKIE_FALLBACK=true, admin cookie IS returned as fallback."""
        with tempfile.TemporaryDirectory() as cookie_dir:
            platform = "instagram"
            admin_id = "9999"
            user_id = "1111"

            s_admin = _sanitize(admin_id)
            admin_path = os.path.join(cookie_dir, f"{platform}_{s_admin}.txt")
            with open(admin_path, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")

            with patch.dict(os.environ, {'ALLOW_ADMIN_COOKIE_FALLBACK': 'true'}):
                import importlib
                import downloaders.gallery_dl as _m
                importlib.reload(_m)
                dl = _m.GalleryDLDownloader(
                    output_path=tempfile.mkdtemp(),
                    cookie_path=cookie_dir,
                    admin_id=admin_id
                )
                result = dl._get_cookie_file(platform, user_id)

            assert result == admin_path, (
                f"Expected admin fallback path {admin_path!r}, got {result!r}"
            )


@pytest.mark.asyncio
async def test_user_b_failure_never_passes_user_a_cookies():
    """User B has no cookies and user A does. B's failure never passes A's file to --cookies."""
    with tempfile.TemporaryDirectory() as cookie_dir:
        cookie_a = os.path.join(cookie_dir, "instagram_userA.txt")
        with open(cookie_a, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")

        from downloaders.gallery_dl import GalleryDLDownloader
        dl = GalleryDLDownloader(
            output_path=tempfile.mkdtemp(),
            cookie_path=cookie_dir,
            admin_id="admin999"
        )

        fail_res = {'success': False, 'error': 'Download failed'}
        with patch.object(dl, '_execute_with_retry', return_value=fail_res) as mock_exec, \
             patch.object(dl, '_download_with_ytdlp', return_value={'success': False, 'error': 'yt-dlp failed'}):

            res = await dl.download("https://instagram.com/p/test", "Instagram", user_id="userB")
            assert res['success'] is False

            for call_args in mock_exec.call_args_list:
                cmd = call_args[0][0]
                assert cookie_a not in cmd
                assert '--cookies' not in cmd


@pytest.mark.asyncio
async def test_retry_uses_admin_cookie_only_when_flag_true():
    """With flag false, admin cookie is never used on retry; with true, it is."""
    import importlib
    import downloaders.gallery_dl as _m

    with tempfile.TemporaryDirectory() as cookie_dir:
        admin_cookie = os.path.join(cookie_dir, "instagram_admin999.txt")
        with open(admin_cookie, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")

        # 1. Flag is False
        with patch.dict(os.environ, {'ALLOW_ADMIN_COOKIE_FALLBACK': 'false'}):
            importlib.reload(_m)
            dl_false = _m.GalleryDLDownloader(
                output_path=tempfile.mkdtemp(),
                cookie_path=cookie_dir,
                admin_id="admin999"
            )
            fail_res = {'success': False, 'error': 'Download failed'}
            with patch.object(dl_false, '_execute_with_retry', return_value=fail_res) as mock_exec_false, \
                 patch.object(dl_false, '_download_with_ytdlp', return_value={'success': False, 'error': 'fail'}):
                await dl_false.download("https://instagram.com/p/test", "Instagram", user_id="userB")
                assert mock_exec_false.call_count == 1
                assert '--cookies' not in mock_exec_false.call_args_list[0][0][0]

        # 2. Flag is True
        with patch.dict(os.environ, {'ALLOW_ADMIN_COOKIE_FALLBACK': 'true'}):
            importlib.reload(_m)
            dl_true = _m.GalleryDLDownloader(
                output_path=tempfile.mkdtemp(),
                cookie_path=cookie_dir,
                admin_id="admin999"
            )
            succ_res = {'success': True, 'stdout': 'ok'}
            with patch.object(dl_true, '_execute_with_retry', side_effect=[fail_res, succ_res]) as mock_exec_true, \
                 patch.object(dl_true, '_get_download_files', side_effect=[set(), set(), {'/path/file.mp4'}, {'/path/file.mp4'}]):
                res = await dl_true.download("https://instagram.com/p/test", "Instagram", user_id="userB")
                assert res['success'] is True
                assert mock_exec_true.call_count == 2
                assert '--cookies' not in mock_exec_true.call_args_list[0][0][0]
                assert '--cookies' in mock_exec_true.call_args_list[1][0][0]
                assert admin_cookie in mock_exec_true.call_args_list[1][0][0]


def test_delete_user_cookies():
    """delete_user_cookies('123') leaves instagram_4123.txt alone and removes instagram_123.txt and tiktok_123.txt."""
    from auth.cookies import delete_user_cookies
    with tempfile.TemporaryDirectory() as cookie_dir:
        ig_4123 = os.path.join(cookie_dir, "instagram_4123.txt")
        ig_123 = os.path.join(cookie_dir, "instagram_123.txt")
        tt_123 = os.path.join(cookie_dir, "tiktok_123.txt")

        for path in (ig_4123, ig_123, tt_123):
            with open(path, 'w') as f:
                f.write("cookie data")

        deleted = delete_user_cookies("123", cookie_path=cookie_dir)
        assert deleted == 2
        assert os.path.exists(ig_4123)
        assert not os.path.exists(ig_123)
        assert not os.path.exists(tt_123)

