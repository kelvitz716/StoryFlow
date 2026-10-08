"""
Tests verifying gallery_dl exception classes, exit codes, and error mapping in BaseDownloader.
"""
import pytest
import gallery_dl.exception as gdx
from downloaders.base import BaseDownloader


def test_gallery_dl_exception_exit_codes():
    """
    Assert mapping of gallery_dl.exception classes:
    - Exit code 16 for AuthRequired / AuthenticationError / AuthorizationError.
    - Exit code 4 for HttpError / NotFoundError / ExtractionError / AbortExtraction.
    Breaks if gallery-dl changes its exit codes.
    """
    auth_exceptions = (gdx.AuthRequired, gdx.AuthenticationError, gdx.AuthorizationError)
    for exc in auth_exceptions:
        assert getattr(exc, "code", None) == 16, (
            f"Expected {exc.__name__}.code == 16, got {getattr(exc, 'code', None)}"
        )

    http_and_not_found_exceptions = (
        gdx.HttpError,
        gdx.NotFoundError,
        gdx.ExtractionError,
        gdx.AbortExtraction,
    )
    for exc in http_and_not_found_exceptions:
        assert getattr(exc, "code", None) == 4, (
            f"Expected {exc.__name__}.code == 4, got {getattr(exc, 'code', None)}"
        )


@pytest.mark.asyncio
async def test_gallery_dl_exit_code_16_auth_required():
    """gallery-dl exit code 16 triggers login required."""
    dl = BaseDownloader(output_path="./downloads")

    # Mock subprocess returncode 16
    async def fake_proc(*args, **kwargs):
        class DummyProc:
            returncode = 16
            stdout = None
            stderr = None
            async def wait(self): pass
        return DummyProc()

    # We can test _execute_with_retry
    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 16
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[b"error\n", b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
        assert res["success"] is False
        assert "Login required" in res["error"]
        assert res["returncode"] == 16


@pytest.mark.asyncio
async def test_gallery_dl_exit_code_4_404_content_not_found():
    """gallery-dl exit code 4 with 404 says Content not found, not login required."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 4
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[b"HTTP Error 404: Not Found\n", b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
        assert res["success"] is False
        assert res["error"] == "Content not found"
        assert "Login required" not in res["error"]


@pytest.mark.asyncio
async def test_broad_stderr_does_not_trigger_auth_error():
    """Broad words ('cookie', 'forbidden', 'redirect') must NOT trigger auth error."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    for word in [b"received cookie header\n", b"redirect to new url\n", b"forbidden action\n"]:
        with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = mock.MagicMock()
            proc.returncode = 1
            proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
            proc.stderr.read = mock.AsyncMock(side_effect=[word, b""])
            proc.wait = mock.AsyncMock(return_value=0)
            mock_exec.return_value = proc

            res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
            assert res["success"] is False
            assert "Login required" not in res["error"]


@pytest.mark.asyncio
async def test_specific_stderr_triggers_auth_error():
    """Specific words ('login required', '401', 'sign in to confirm') trigger auth error."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    for phrase in [b"login required to view\n", b"HTTP 401 unauthorized\n", b"sign in to confirm age\n"]:
        with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = mock.MagicMock()
            proc.returncode = 1
            proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
            proc.stderr.read = mock.AsyncMock(side_effect=[phrase, b""])
            proc.wait = mock.AsyncMock(return_value=0)
            mock_exec.return_value = proc

            res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
            assert res["success"] is False
            assert "Login required" in res["error"]
