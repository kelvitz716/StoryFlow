"""Utilities for splitting oversized video files before Telegram upload."""

import asyncio
import logging
import math
import os
import signal
from typing import List, Optional

from core.config import _env_int

# Maximum size per uploaded part in MB (default 1900 MB, safely under Telegram's 2 GB MTProto cap).
# Users with Telegram Premium can raise this up to 3900 MB.
_MAX_UPLOAD_PART_MB = _env_int('MAX_UPLOAD_PART_MB', 1900, 50, 3900)

_VIDEO_EXTENSIONS = frozenset({'.mp4', '.mov', '.avi', '.mkv', '.webm'})


async def _run_proc(cmd: List[str], timeout: int = 600) -> tuple[int, str, str]:
    """Run a subprocess with process-group isolation and wall-clock timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout_b.decode(errors='replace').strip(),
            stderr_b.decode(errors='replace').strip(),
        )
    except asyncio.TimeoutError:
        if proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                await proc.wait()
            except Exception:
                pass
        raise TimeoutError(f"Command timed out after {timeout}s: {cmd[0]}")


async def _get_duration_seconds(file_path: str) -> Optional[float]:
    """Return media duration in seconds using ffprobe, or None if unavailable."""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path,
    ]
    try:
        rc, out, _ = await _run_proc(cmd, timeout=30)
        if rc == 0 and out:
            dur = float(out.splitlines()[0].strip())
            return dur if dur > 0 else None
    except Exception as exc:
        logging.warning(f"ffprobe failed for {os.path.basename(file_path)}: {exc}")
    return None


async def split_video_file(
    file_path: str,
    max_part_bytes: Optional[int] = None,
) -> List[str]:
    """
    Split a single video file into <= max_part_bytes segments using ffmpeg stream copy.

    Returns the list of resulting part file paths (or [file_path] if no split was
    needed or if splitting failed). Deletes the original file only after parts are
    successfully created.
    """
    limit_bytes = max_part_bytes if max_part_bytes is not None else _MAX_UPLOAD_PART_MB * 1024 * 1024

    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size <= limit_bytes:
        return [file_path]

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _VIDEO_EXTENSIONS:
        logging.warning(
            f"⚠️ File {os.path.basename(file_path)} ({file_size / (1024*1024):.1f} MB) "
            f"exceeds {limit_bytes / (1024*1024):.0f} MB but is not a supported video format."
        )
        return [file_path]

    duration = await _get_duration_seconds(file_path)
    if not duration:
        logging.warning(f"⚠️ Could not determine duration for {os.path.basename(file_path)}; skipping split.")
        return [file_path]

    # Use a 90% target per segment to absorb VBR bitrate spikes across keyframes.
    target_bytes = int(limit_bytes * 0.90)
    num_parts = max(2, math.ceil(file_size / target_bytes))
    segment_time = max(10, int(duration / num_parts))

    parent_dir = os.path.dirname(file_path)
    stem = os.path.splitext(os.path.basename(file_path))[0]
    output_pattern = os.path.join(parent_dir, f"{stem}_part%03d{ext}")

    logging.info(
        f"✂️ Splitting {os.path.basename(file_path)} ({file_size / (1024*1024):.1f} MB, "
        f"{duration:.0f}s) into ~{num_parts} parts (~{segment_time}s each)..."
    )

    cmd = [
        'ffmpeg',
        '-y',
        '-i', file_path,
        '-c', 'copy',
        '-map', '0',
        '-f', 'segment',
        '-segment_time', str(segment_time),
        '-segment_format', 'mp4',
        # faststart moves each part's moov atom to the front so Telegram can
        # play the file inline without waiting for the full download.
        '-movflags', '+faststart+frag_keyframe',
        '-reset_timestamps', '1',
        output_pattern,
    ]

    try:
        rc, _, stderr = await _run_proc(cmd, timeout=600)
    except Exception as exc:
        logging.error(f"❌ ffmpeg split failed for {os.path.basename(file_path)}: {exc}")
        return [file_path]

    if rc != 0:
        logging.error(f"❌ ffmpeg split exited with {rc}: {stderr[-300:]}")
        return [file_path]

    prefix = f"{stem}_part"
    parts = sorted(
        os.path.join(parent_dir, fname)
        for fname in os.listdir(parent_dir)
        if fname.startswith(prefix) and fname.endswith(ext)
    )

    if not parts:
        logging.error(f"❌ ffmpeg split produced no parts for {os.path.basename(file_path)}")
        return [file_path]

    # Remove original oversized file now that parts are safely on disk
    try:
        os.remove(file_path)
    except OSError as exc:
        logging.warning(f"⚠️ Could not remove original file after split: {exc}")

    logging.info(f"✅ Split into {len(parts)} part(s).")
    return parts


async def prepare_files_for_upload(
    files: List[str],
    max_part_bytes: Optional[int] = None,
) -> List[str]:
    """Expand any oversized video files in `files` into <= max_part_bytes parts."""
    prepared: List[str] = []
    for path in files:
        parts = await split_video_file(path, max_part_bytes=max_part_bytes)
        prepared.extend(parts)
    return prepared
