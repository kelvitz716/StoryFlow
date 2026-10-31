"""
Tests for item 4: subprocess hygiene in BaseDownloader._execute_with_retry.

Tests:
- (a) >200 KB stderr, minimal stdout — must finish, not hang.
- (b) One very long stdout line — must not crash the job.
"""
import asyncio
import os
import sys
import textwrap
import pytest
from downloaders.base import BaseDownloader


class ConcreteDownloader(BaseDownloader):
    """Minimal concrete subclass for testing."""
    pass


# ---------------------------------------------------------------------------
# Helper: build a command that runs an inline Python script
# ---------------------------------------------------------------------------

def _python_script_cmd(*lines: str) -> list:
    """Return a command list that executes the given Python lines."""
    script = "\n".join(lines)
    return [sys.executable, "-c", script]


# ---------------------------------------------------------------------------
# Test (a): large stderr, minimal stdout — must not hang
# ---------------------------------------------------------------------------

class TestLargeStderrNonBlocking:
    """A subprocess that writes >200 KB to stderr must finish without deadlock."""

    @pytest.mark.asyncio
    async def test_large_stderr_finishes(self):
        """200 KB of stderr must not block the process or the drain task."""
        # Write 200 KB to stderr, one byte to stdout, then exit 0
        cmd = _python_script_cmd(
            "import sys",
            "sys.stderr.write('E' * 204800)",  # 200 KB
            "sys.stderr.flush()",
            "sys.stdout.write('ok\\n')",
            "sys.stdout.flush()",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        result = await asyncio.wait_for(
            dl._execute_with_retry(cmd, process_name="test_large_stderr"),
            timeout=30,  # Should finish in well under a second
        )
        assert result['success'] is True
        assert 'stdout' in result
        # Confirm stderr was NOT leaked in the result dict
        assert 'stderr' not in result

    @pytest.mark.asyncio
    async def test_large_stderr_failure_finishes(self):
        """200 KB to stderr + non-zero exit — must still finish without hang."""
        cmd = _python_script_cmd(
            "import sys",
            "sys.stderr.write('X' * 204800)",
            "sys.stderr.flush()",
            "sys.exit(1)",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        result = await asyncio.wait_for(
            dl._execute_with_retry(cmd, process_name="test_large_stderr_fail", max_attempts=1),
            timeout=30,
        )
        assert result['success'] is False
        # Must be a generic message, not raw stderr
        assert 'XXXXX' not in result.get('error', '')
        assert 'stderr' not in result


# ---------------------------------------------------------------------------
# Test (b): very long stdout line — must not crash
# ---------------------------------------------------------------------------

class TestLongStdoutLine:
    """A single very long stdout line must not raise ValueError and crash the job."""

    @pytest.mark.asyncio
    async def test_long_line_does_not_crash(self):
        """
        A stdout line of 2 MB (beyond the default asyncio 64 KB limit) must be
        handled gracefully — either by the 1 MB _PIPE_LIMIT catching it or by
        the ValueError handler skipping the line.  In either case the job must
        not raise an unhandled exception.
        """
        # 2 MB line — exceeds the 1 MB _PIPE_LIMIT, so readline will raise ValueError
        cmd = _python_script_cmd(
            "import sys",
            "sys.stdout.write('L' * 2097152 + '\\n')",
            "sys.stdout.flush()",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        # Must not raise — result may be success or failure but never an exception
        try:
            result = await asyncio.wait_for(
                dl._execute_with_retry(cmd, process_name="test_long_line", max_attempts=1),
                timeout=30,
            )
            # Job may succeed (0 exit) or fail, but must not propagate ValueError
            assert isinstance(result, dict)
            assert 'success' in result
        except asyncio.TimeoutError:
            pytest.fail("Job hung on long stdout line")


# ---------------------------------------------------------------------------
# Test (c): stdout flood for 3s — must not grow process RSS by >50 MB (item 1)
# ---------------------------------------------------------------------------

def _get_process_rss_mb() -> float:
    """Read current VmRSS in MB from /proc/self/status."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


class TestStdoutFloodBoundedMemory:
    """A child that floods stdout for 3s must not grow process RSS by more than ~50 MB."""

    @pytest.mark.asyncio
    async def test_stdout_flood_3s_rss_bounded(self):
        """
        Flood stdout continuously for 3.0 seconds.
        Verify that:
        1. Process finishes cleanly without OOM or hanging.
        2. Result stdout stores at most 200 lines and at most 64 KB.
        3. RSS growth does not exceed 50 MB.
        """
        import gc
        gc.collect()
        rss_before = _get_process_rss_mb()

        cmd = _python_script_cmd(
            "import sys, time",
            "end = time.time() + 3.0",
            "chunk = 'LINE ' + ('x' * 100) + '\\n'",
            "while time.time() < end:",
            "    sys.stdout.write(chunk)",
            "sys.stdout.flush()",
        )
        dl = ConcreteDownloader(output_path="/tmp/test_dl_scratch")
        result = await asyncio.wait_for(
            dl._execute_with_retry(cmd, process_name="test_stdout_flood", max_attempts=1),
            timeout=10,
        )
        assert result['success'] is True
        stdout = result.get('stdout', '')
        lines = stdout.splitlines()

        # Must store at most 200 lines
        assert len(lines) <= 200

        # Must store at most 64 KB
        assert len(stdout.encode('utf-8')) <= 65536

        gc.collect()
        rss_after = _get_process_rss_mb()
        rss_growth_mb = rss_after - rss_before
        assert rss_growth_mb < 50.0, f"RSS grew by {rss_growth_mb:.2f} MB, exceeding 50 MB limit"


# ---------------------------------------------------------------------------
# Test (d): G4 size and file watchdog limits
# ---------------------------------------------------------------------------

class TestWatchdogLimits:
    """G4 tests: watchdog kills process when job size or file count exceeds cap."""

    @pytest.mark.asyncio
    async def test_watchdog_kills_process_exceeding_size_cap_and_cleans_partial(self, tmp_path, monkeypatch):
        """A process that writes more than MAX_JOB_SIZE_MB is killed and partial files cleaned."""
        import downloaders.base as base_module
        # Set cap to 1 MB (1048576 bytes)
        monkeypatch.setattr(base_module, "_MAX_JOB_SIZE_MB", 1)

        job_dir = tmp_path / "job_size_test"
        job_dir.mkdir()

        # Script creates a completed file then continually writes to a .part file
        script = textwrap.dedent(f"""
            import sys, time, os
            d = {repr(str(job_dir))}
            with open(os.path.join(d, "good.mp4"), "wb") as f:
                f.write(b"good" * 1024)
            part_path = os.path.join(d, "large.part")
            with open(part_path, "wb") as f:
                while True:
                    f.write(b"X" * 65536)
                    f.flush()
                    time.sleep(0.05)
        """)
        cmd = [sys.executable, "-c", script]

        dl = ConcreteDownloader(output_path=str(tmp_path))
        result = await dl._execute_with_retry(
            cmd,
            process_name="test_watchdog_size",
            max_attempts=1,
            job_dir=str(job_dir),
            check_interval=0.1,  # Fast check for test
        )

        assert result['success'] is False
        assert result.get('limit_reached') is True
        assert "limit" in result.get('error', '').lower()

        # Verify partial file was removed and good completed file remained
        remaining_files = os.listdir(str(job_dir))
        assert "good.mp4" in remaining_files
        assert not any(f.endswith('.part') for f in remaining_files)

    @pytest.mark.asyncio
    async def test_watchdog_below_cap_unchanged(self, tmp_path, monkeypatch):
        """A process that stays below the size cap finishes normally with success."""
        import downloaders.base as base_module
        monkeypatch.setattr(base_module, "_MAX_JOB_SIZE_MB", 100)

        job_dir = tmp_path / "job_below_cap"
        job_dir.mkdir()

        script = textwrap.dedent(f"""
            import sys, os
            d = {repr(str(job_dir))}
            with open(os.path.join(d, "file.mp4"), "wb") as f:
                f.write(b"data" * 1024)
            print("done")
        """)
        cmd = [sys.executable, "-c", script]

        dl = ConcreteDownloader(output_path=str(tmp_path))
        result = await dl._execute_with_retry(
            cmd,
            process_name="test_watchdog_normal",
            max_attempts=1,
            job_dir=str(job_dir),
            check_interval=0.1,
        )

        assert result['success'] is True
        assert os.path.exists(os.path.join(str(job_dir), "file.mp4"))

