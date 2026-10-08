"""
Tests for item 5: raw stderr must never appear in job.error or format_error_message output.
"""
import asyncio
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from downloaders.base import BaseDownloader
from utils.bot_utils import format_error_message


SECRET = "SECRET-BODY-123"


class ConcreteDownloader(BaseDownloader):
    pass


def _python_script_cmd(*lines: str) -> list:
    return [sys.executable, "-c", "\n".join(lines)]


class TestStderrNotLeaked:
    """Raw stderr containing secrets must never reach job.error or format_error_message."""

    @pytest.mark.asyncio
    async def test_stderr_secret_not_in_error_key(self):
        """
        A failing subprocess that writes a secret to stderr must not expose
        that secret in the result dict returned to the queue/caller.
        """
        cmd = _python_script_cmd(
            "import sys",
            f"sys.stderr.write('{SECRET}\\n')",
            "sys.stderr.flush()",
            "sys.exit(1)",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        result = await dl._execute_with_retry(cmd, process_name="test_secret", max_attempts=1)

        assert result['success'] is False
        # The secret must not appear anywhere in the result dict
        for key, val in result.items():
            assert SECRET not in str(val), (
                f"Secret found in result[{key!r}]: {val!r}"
            )

    @pytest.mark.asyncio
    async def test_format_error_message_does_not_contain_secret(self):
        """
        format_error_message must only receive sanitised error strings.
        When called with a generic error, the output must not contain the secret.
        """
        generic_error = "Download failed due to an internal error"
        output = format_error_message(generic_error, platform="Instagram")
        assert SECRET not in output

    @pytest.mark.asyncio
    async def test_internal_exception_gives_generic_job_error(self):
        """
        Simulate the queue's exception path: if a downloader raises with
        a message that contains a secret, job.error must be the generic string.

        We test the BaseDownloader layer directly to confirm it doesn't
        propagate raw exception text.
        """
        # A command that makes the process raise via an unexpected error
        # (we simulate this by patching asyncio.create_subprocess_exec to raise)
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")

        async def _boom(*args, **kwargs):
            raise RuntimeError(f"Internal plumbing error: {SECRET}")

        with patch('asyncio.create_subprocess_exec', side_effect=_boom):
            result = await dl._execute_with_retry(
                ["dummy"], process_name="test_exception_leak", max_attempts=1
            )

        assert result['success'] is False
        # Generic message — no secret
        assert SECRET not in result.get('error', '')
        # 'stderr' key must not be present
        assert 'stderr' not in result

    @pytest.mark.asyncio
    async def test_stderr_key_absent_on_success(self):
        """On success, the result dict must not contain a 'stderr' key."""
        cmd = _python_script_cmd(
            "import sys",
            f"sys.stderr.write('{SECRET}\\n')",
            "sys.stderr.flush()",
            "sys.stdout.write('done\\n')",
            "sys.stdout.flush()",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        result = await dl._execute_with_retry(cmd, process_name="test_no_stderr_key")
        assert result['success'] is True
        assert 'stderr' not in result
        assert SECRET not in str(result)


class TestExceptionSecretNotLeaked:
    """RuntimeError('SECRET-123') must never leak into job.error, result, or reply text."""

    SECRET_CODE = "SECRET-123"

    @pytest.mark.asyncio
    async def test_gallery_dl_unexpected_exception_no_secret(self):
        """gallery_dl.download must not leak exception text in 'details'."""
        from downloaders.gallery_dl import GalleryDLDownloader
        dl = GalleryDLDownloader(output_path="/tmp/test_dl_scratch")
        with patch.object(dl, '_execute_with_retry', side_effect=RuntimeError(self.SECRET_CODE)):
            result = await dl.download("https://instagram.com/p/test", platform="Instagram")
        assert result['success'] is False
        for key, val in result.items():
            assert self.SECRET_CODE not in str(val), f"Secret leaked in result[{key!r}]"

    @pytest.mark.asyncio
    async def test_gallery_dl_ytdlp_exception_no_secret(self):
        """gallery_dl._download_with_ytdlp must not leak exception text in 'error'."""
        from downloaders.gallery_dl import GalleryDLDownloader
        dl = GalleryDLDownloader(output_path="/tmp/test_dl_scratch")
        with patch.object(dl, '_execute_with_retry', side_effect=RuntimeError(self.SECRET_CODE)):
            result = await dl._download_with_ytdlp(
                "https://instagram.com/reel/test", platform="Instagram", user_id=None,
                output_path="/tmp/test_dl_scratch", files_before=set()
            )
        assert result['success'] is False
        for key, val in result.items():
            assert self.SECRET_CODE not in str(val), f"Secret leaked in result[{key!r}]"

    @pytest.mark.asyncio
    async def test_snapchat_unexpected_exception_no_secret(self):
        """snapchat.download must not leak unexpected exception text in 'details'."""
        from downloaders.snapchat import SnapchatDownloader
        dl = SnapchatDownloader(output_path="/tmp/test_dl_scratch")
        with patch.object(dl, '_scrape_page', side_effect=RuntimeError(self.SECRET_CODE)):
            result = await dl.download("https://story.snapchat.com/s/test")
        assert result['success'] is False
        for key, val in result.items():
            assert self.SECRET_CODE not in str(val), f"Secret leaked in result[{key!r}]"

    @pytest.mark.asyncio
    async def test_snapchat_request_exception_no_secret(self):
        """snapchat.download must not leak RequestException text in 'details'."""
        import requests
        from downloaders.snapchat import SnapchatDownloader
        dl = SnapchatDownloader(output_path="/tmp/test_dl_scratch")
        with patch.object(dl, '_scrape_page', side_effect=requests.exceptions.RequestException(self.SECRET_CODE)):
            result = await dl.download("https://story.snapchat.com/s/test")
        assert result['success'] is False
        for key, val in result.items():
            assert self.SECRET_CODE not in str(val), f"Secret leaked in result[{key!r}]"

    @pytest.mark.asyncio
    async def test_handlers_cookie_exception_no_secret(self):
        """Cookie file handler must never leak exception text in reply edit_text."""
        from bot.handlers import handle_document
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 12345
        update.effective_chat.type = "private"
        document = MagicMock()
        document.file_name = "cookies.txt"
        document.file_size = 100
        document.get_file = AsyncMock(side_effect=RuntimeError(self.SECRET_CODE))
        update.message.document = document

        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)

        context = MagicMock()
        context.user_data = {'awaiting_cookies': 'instagram'}
        cookie_mgr = MagicMock()
        access_mgr = MagicMock()
        access_mgr.is_allowed.return_value = True

        with patch('bot.handlers.send_cookies_menu', new=AsyncMock()):
            await handle_document(update, context, cookie_mgr, access_mgr)

        for call in status_msg.edit_text.call_args_list:
            text = call[0][0] if call[0] else call[1].get('text', '')
            assert self.SECRET_CODE not in str(text), f"Secret leaked in reply: {text}"

    @pytest.mark.asyncio
    async def test_job_error_never_contains_secret(self):
        """Queue worker must ensure job.error never contains raw exception secrets."""
        from core.queue import DownloadJob, DownloadQueue
        queue = DownloadQueue(max_concurrent=1)
        mock_dl = MagicMock()
        mock_dl.download = AsyncMock(side_effect=RuntimeError(self.SECRET_CODE))
        queue.gallery_dl = mock_dl

        job = DownloadJob(
            job_id="test1",
            user_id="user1",
            url="https://instagram.com/p/test",
            platform="Instagram",
        )
        queue._jobs[job.job_id] = job
        queue._running = True
        await queue._queue.put((job, AsyncMock()))

        worker = asyncio.create_task(queue._worker(0))
        await asyncio.sleep(0.1)
        queue._running = False
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

        assert self.SECRET_CODE not in (job.error or "")
        assert self.SECRET_CODE not in (job.message or "")

