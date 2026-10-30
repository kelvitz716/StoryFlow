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
        assert res["error"] == "Authentication required"
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
        assert "Authentication required" not in res["error"]


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
            assert "Authentication required" not in res["error"]


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
            assert res["error"] == "Authentication required"


@pytest.mark.asyncio
async def test_url_with_4012_not_treated_as_auth_error():
    """URLs containing '4012' must NOT trigger false auth errors."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[b"Failed downloading https://instagram.com/p/4012345/\n", b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
        assert res["success"] is False
        assert res["error"] != "Authentication required"
        assert "Authentication required" not in str(res.get("details", ""))


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,stderr_msg", [
    (429, b"HTTP Error 429: Too Many Requests\n"),
    (503, b"HTTP Error 503: Service Unavailable\n"),
])
async def test_429_and_503_trigger_3_retry_attempts(status_code, stderr_msg):
    """HTTP 429 and 503 errors trigger exactly 3 retry attempts."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec, \
         mock.patch("asyncio.sleep", new_callable=mock.AsyncMock) as mock_sleep:

        def make_proc():
            proc = mock.MagicMock()
            proc.returncode = 4  # exit code 4 from gallery-dl on http error
            proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
            proc.stderr.read = mock.AsyncMock(side_effect=[stderr_msg, b""])
            proc.wait = mock.AsyncMock(return_value=0)
            return proc

        mock_exec.side_effect = [make_proc(), make_proc(), make_proc()]

        res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=3)
        assert res["success"] is False
        assert mock_exec.call_count == 3
        # Should have slept between attempts (2 sleeps for 3 attempts)
        assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_ytdlp_auth_error_tiktok_extractor_stderr():
    """Verify TikTok extractor stderr string triggers auth error with actionable guidance."""
    dl = BaseDownloader(output_path="./downloads")

    exact_tiktok_stderr = (
        b"This post may not be comfortable for some audiences. "
        b"Log in for access. Use --cookies-from-browser or --cookies for the authentication.\n"
    )

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[exact_tiktok_stderr, b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "yt-dlp", max_attempts=1)
        assert res["success"] is False
        assert res["error"] == "Authentication required"
        assert res["details"] == "This content needs a logged-in session. Ask the admin to add cookies for this platform."


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", [
    b"ERROR: log in for access\n",
    b"ERROR: please use --cookies to authenticate\n",
    b"ERROR: login required to watch this video\n",
])
async def test_ytdlp_auth_phrases_trigger_auth_error(phrase):
    """Verify phrases 'log in for access', 'use --cookies', 'login required' trigger auth error."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[phrase, b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "yt-dlp", max_attempts=1)
        assert res["success"] is False
        assert res["error"] == "Authentication required"
        assert res["details"] == "This content needs a logged-in session. Ask the admin to add cookies for this platform."


@pytest.mark.asyncio
async def test_instagram_redirect_to_login_triggers_auth_error():
    """gallery-dl stderr with 'HTTP redirect to login page' triggers auth error."""
    dl = BaseDownloader(output_path="./downloads")

    stderr_msg = b"[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)\n"

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 4
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[stderr_msg, b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "gallery-dl", max_attempts=1)
        assert res["success"] is False
        assert res["error"] == "Authentication required"
        assert res["details"] == "This content needs a logged-in session. Ask the admin to add cookies for this platform."
        assert res["returncode"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("msg", [
    b"ERROR: [Instagram] DeqKnfVxiqD: This content isn't available to everyone: It can't be seen by certain audiences.\n",
    b"ERROR: [youtube] 12345: Sign in to confirm your age\n",
    b"ERROR: This video is age-restricted and requires login\n",
    b"ERROR: Restricted content cannot be viewed\n",
])
async def test_age_and_audience_restricted_triggers_auth_error(msg):
    """Audience and age-restricted messages trigger auth error with cookie guidance."""
    dl = BaseDownloader(output_path="./downloads")

    import unittest.mock as mock
    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout.readline = mock.AsyncMock(side_effect=[b"", b""])
        proc.stderr.read = mock.AsyncMock(side_effect=[msg, b""])
        proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = proc

        res = await dl._execute_with_retry(["dummy"], "yt-dlp", max_attempts=1)
        assert res["success"] is False
        assert res["error"] == "Authentication required"
        assert res["details"] == "This content needs a logged-in session. Ask the admin to add cookies for this platform."


@pytest.mark.asyncio
async def test_download_retries_with_cookies_on_gallery_dl_failure():
    """Verify download tries without cookies first, then retries gallery-dl with cookies."""
    from downloaders.gallery_dl import GalleryDLDownloader
    import unittest.mock as mock

    dl = GalleryDLDownloader(output_path="./downloads", cookie_path="./cookies")
    dl._get_cookie_file = mock.MagicMock(return_value="/path/to/cookies.txt")

    # First attempt (without cookies) fails, second attempt (with cookies) succeeds
    fail_res = {'success': False, 'error': 'Download failed'}
    succ_res = {'success': True, 'stdout': 'ok'}

    with mock.patch.object(dl, '_execute_with_retry', side_effect=[fail_res, succ_res]) as mock_exec, \
         mock.patch.object(dl, '_get_download_files', side_effect=[set(), set(), {'/path/file.mp4'}, {'/path/file.mp4'}]):

        res = await dl.download("https://instagram.com/p/test", "Instagram", user_id="123")
        assert res['success'] is True
        assert mock_exec.call_count == 2
        # First call was without cookies
        first_call_cmd = mock_exec.call_args_list[0][0][0]
        assert '--cookies' not in first_call_cmd
        # Second call was with cookies
        second_call_cmd = mock_exec.call_args_list[1][0][0]
        assert '--cookies' in second_call_cmd


@pytest.mark.asyncio
async def test_download_retries_with_fallback_cookie_for_group_chats():
    """Verify retry uses the resolved cookie from _get_cookie_file."""
    from downloaders.gallery_dl import GalleryDLDownloader
    import unittest.mock as mock

    dl = GalleryDLDownloader(output_path="./downloads", cookie_path="./cookies", admin_id="999")
    dl._get_cookie_file = mock.MagicMock(return_value="/cookies/instagram_999.txt")

    fail_res = {'success': False, 'error': 'Download failed'}
    succ_res = {'success': True, 'stdout': 'ok'}

    with mock.patch.object(dl, '_execute_with_retry', side_effect=[fail_res, succ_res]) as mock_exec, \
         mock.patch.object(dl, '_get_download_files', side_effect=[set(), set(), {'/path/file.mp4'}, {'/path/file.mp4'}]):

        res = await dl.download("https://instagram.com/p/test", "Instagram", user_id="-1001234567")
        assert res['success'] is True
        assert mock_exec.call_count == 2
        # First call was without cookies
        assert '--cookies' not in mock_exec.call_args_list[0][0][0]
        # Second call used fallback cookie
        second_call_cmd = mock_exec.call_args_list[1][0][0]
        assert '--cookies' in second_call_cmd
        assert '/cookies/instagram_999.txt' in second_call_cmd


@pytest.mark.asyncio
async def test_ytdlp_fallback_receives_retry_cookie():
    """Verify yt-dlp fallback is invoked when gallery-dl fails both attempts."""
    from downloaders.gallery_dl import GalleryDLDownloader
    import unittest.mock as mock

    dl = GalleryDLDownloader(output_path="./downloads", cookie_path="./cookies", admin_id="999")
    dl._get_cookie_file = mock.MagicMock(return_value="/cookies/instagram_999.txt")

    fail_res = {'success': False, 'error': 'Download failed'}

    with mock.patch.object(dl, '_execute_with_retry', return_value=fail_res), \
         mock.patch.object(dl, '_get_download_files', return_value=set()), \
         mock.patch.object(dl, '_download_with_ytdlp', return_value={'success': True, 'files': ['/path/v.mp4']}) as mock_ytdlp:

        res = await dl.download("https://instagram.com/p/test", "Instagram", user_id="-1001234567")
        assert res['success'] is True
        mock_ytdlp.assert_called_once()



