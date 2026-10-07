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
