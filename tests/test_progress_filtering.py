"""
Tests for hardening item 4:
Progress Text URL Filtering in BaseDownloader._execute_with_retry.
Ensure progress text never surfaces a URL or query string.
Skip lines starting with http or containing ://.
Use os.path.basename() only for real file paths.
"""
import sys
import pytest
from downloaders.base import BaseDownloader


class ConcreteDownloader(BaseDownloader):
    pass


def _python_script_cmd(*lines: str) -> list:
    return [sys.executable, "-c", "\n".join(lines)]


@pytest.mark.asyncio
async def test_echoed_url_in_subprocess_skipped_by_progress_callback():
    """An echoed URL in subprocess output must be skipped by the progress callback."""
    cmd = _python_script_cmd(
        "import sys",
        "sys.stdout.write('https://instagram.com/p/C_sample_post/video.mp4\\n')",
        "sys.stdout.write('http://example.com/asset.jpg?token=secret\\n')",
        "sys.stdout.write('[download] https://tiktok.com/@creator/video/12345\\n')",
        "sys.stdout.write('ftp://files.example.com/file.mp4?query=1\\n')",
        "sys.stdout.write('/tmp/StoryFlow/job1/downloaded_reel.mp4\\n')",
        "sys.stdout.flush()",
    )
    dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
    progress_calls = []

    result = await dl._execute_with_retry(
        cmd,
        process_name="test_progress",
        max_attempts=1,
        progress_callback=lambda text: progress_calls.append(text),
    )

    assert result["success"] is True

    # None of the progress calls should contain URLs, schemes, or query strings
    for call in progress_calls:
        assert "http" not in call.lower(), f"URL leaked in progress callback: {call}"
        assert "://" not in call, f"Scheme leaked in progress callback: {call}"
        assert "?" not in call, f"Query string leaked in progress callback: {call}"

    # The real file path should have been passed using os.path.basename
    assert progress_calls == ["Downloading: downloaded_reel.mp4"]


@pytest.mark.asyncio
async def test_progress_callback_real_file_paths_and_percentages():
    """Real file paths and percentages are processed correctly."""
    cmd = _python_script_cmd(
        "import sys",
        "sys.stdout.write('[download]  35.5% of ~10.00MiB at 2.50MiB/s ETA 00:02\\n')",
        "sys.stdout.write('/home/user/downloads/track.mp3\\n')",
        "sys.stdout.flush()",
    )
    dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
    progress_calls = []

    result = await dl._execute_with_retry(
        cmd,
        process_name="test_progress_valid",
        max_attempts=1,
        progress_callback=lambda text: progress_calls.append(text),
    )

    assert result["success"] is True
    assert "Downloading: 35.5% (ETA 00:02)" in progress_calls
    assert "Downloading: track.mp3" in progress_calls
