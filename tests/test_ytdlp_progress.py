"""Tests for Feature 1: yt-dlp progress via stdout (--newline + --progress flags)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestYtDlpProgressFlags(unittest.IsolatedAsyncioTestCase):
    """Verify that _download_with_ytdlp builds the correct yt-dlp command."""

    def _make_downloader(self):
        from downloaders.gallery_dl import GalleryDLDownloader
        return GalleryDLDownloader(output_path='/tmp/test_dl', cookie_path='/tmp/test_cookies')

    async def test_newline_and_progress_flags_present(self):
        """Command must include --newline and --progress."""
        dl = self._make_downloader()
        captured = {}

        async def fake_execute(command, **kwargs):
            captured['command'] = command
            return {'success': True}

        dl._execute_with_retry = fake_execute
        dl._get_download_files = MagicMock(return_value=set())

        await dl._download_with_ytdlp(
            url='https://example.com/video',
            platform='YouTube',
            user_id=None,
            output_path='/tmp/out',
            files_before=set(),
        )

        cmd = captured['command']
        self.assertIn('--newline', cmd, '--newline must be in yt-dlp command')
        self.assertIn('--progress', cmd, '--progress must be in yt-dlp command')

    async def test_no_spurious_f_string_on_max_filesize(self):
        """--max-filesize must be a plain string, not an f-string artefact."""
        dl = self._make_downloader()
        captured = {}

        async def fake_execute(command, **kwargs):
            captured['command'] = command
            return {'success': True}

        dl._execute_with_retry = fake_execute
        dl._get_download_files = MagicMock(return_value=set())

        await dl._download_with_ytdlp(
            url='https://example.com/video',
            platform='YouTube',
            user_id=None,
            output_path='/tmp/out',
            files_before=set(),
        )

        cmd = captured['command']
        self.assertIn('--max-filesize', cmd,
                      '--max-filesize must be present as its own element')

    async def test_fmt_is_added_to_command(self):
        """When fmt is provided it must be inserted as -f <fmt>."""
        dl = self._make_downloader()
        captured = {}

        async def fake_execute(command, **kwargs):
            captured['command'] = command
            return {'success': True}

        dl._execute_with_retry = fake_execute
        dl._get_download_files = MagicMock(return_value=set())

        fmt = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
        await dl._download_with_ytdlp(
            url='https://example.com/video',
            platform='YouTube',
            user_id=None,
            output_path='/tmp/out',
            files_before=set(),
            fmt=fmt,
        )

        cmd = captured['command']
        self.assertIn('-f', cmd)
        idx = cmd.index('-f')
        self.assertEqual(cmd[idx + 1], fmt)

    async def test_audio_only_adds_extract_audio_flags(self):
        """When audio_only=True, -x and --audio-format mp3 must be in the command."""
        dl = self._make_downloader()
        captured = {}

        async def fake_execute(command, **kwargs):
            captured['command'] = command
            return {'success': True}

        dl._execute_with_retry = fake_execute
        dl._get_download_files = MagicMock(return_value=set())

        await dl._download_with_ytdlp(
            url='https://example.com/audio',
            platform='SoundCloud',
            user_id=None,
            output_path='/tmp/out',
            files_before=set(),
            audio_only=True,
        )

        cmd = captured['command']
        self.assertIn('-x', cmd)
        self.assertIn('--audio-format', cmd)
        idx = cmd.index('--audio-format')
        self.assertEqual(cmd[idx + 1], 'mp3')

    async def test_url_placed_after_separator(self):
        """The URL must come after '--' to prevent argument injection."""
        dl = self._make_downloader()
        captured = {}

        async def fake_execute(command, **kwargs):
            captured['command'] = command
            return {'success': True}

        dl._execute_with_retry = fake_execute
        dl._get_download_files = MagicMock(return_value=set())

        url = 'https://example.com/video'
        await dl._download_with_ytdlp(
            url=url,
            platform='YouTube',
            user_id=None,
            output_path='/tmp/out',
            files_before=set(),
        )

        cmd = captured['command']
        self.assertIn('--', cmd)
        sep_idx = cmd.index('--')
        self.assertEqual(cmd[sep_idx + 1], url)


if __name__ == '__main__':
    unittest.main()
