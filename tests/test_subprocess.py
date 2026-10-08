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

