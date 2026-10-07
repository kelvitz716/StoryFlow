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
