"""Tests for utils.video_split oversized video splitting."""

import os
import pytest
from unittest.mock import AsyncMock, patch

from utils.video_split import split_video_file, prepare_files_for_upload


@pytest.mark.asyncio
async def test_small_file_not_split(tmp_path):
    f = tmp_path / "small.mp4"
    f.write_bytes(b"0" * 1024)
    res = await split_video_file(str(f), max_part_bytes=2048)
    assert res == [str(f)]
    assert f.exists()


@pytest.mark.asyncio
async def test_non_video_oversized_passthrough(tmp_path):
    f = tmp_path / "archive.zip"
    f.write_bytes(b"0" * 4096)
    res = await split_video_file(str(f), max_part_bytes=1024)
    assert res == [str(f)]
    assert f.exists()


@pytest.mark.asyncio
async def test_oversized_video_splits_and_removes_original(tmp_path):
    f = tmp_path / "movie.mp4"
    f.write_bytes(b"0" * 5000)

    async def fake_run_proc(cmd, timeout=600):
        # Create fake ffmpeg output parts
        (tmp_path / "movie_part000.mp4").write_bytes(b"1" * 2500)
        (tmp_path / "movie_part001.mp4").write_bytes(b"2" * 2500)
        return (0, "", "")

    with patch("utils.video_split._get_duration_seconds", new=AsyncMock(return_value=120.0)):
        with patch("utils.video_split._run_proc", side_effect=fake_run_proc):
            parts = await prepare_files_for_upload([str(f)], max_part_bytes=3000)

    assert len(parts) == 2
    assert parts[0].endswith("movie_part000.mp4")
    assert parts[1].endswith("movie_part001.mp4")
    assert not f.exists()
