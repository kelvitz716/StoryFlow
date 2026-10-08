"""Tests for item 6: branch structure and non-spec isolation."""

import os
import subprocess


def test_features_extras_branch_exists():
    """Verify that features/extras branch exists in the repository."""
    res = subprocess.run(["git", "branch", "--list", "features/extras"], capture_output=True, text=True, check=True)
    assert "features/extras" in res.stdout


def test_hardening_termux_branch_no_non_spec_test_files():
    """Verify that non-spec test files (cancel_job, platform_sites, ytdlp_progress) are not on hardening/termux."""
    tests_dir = os.path.dirname(__file__)
    non_spec_files = ["test_cancel_job.py", "test_platform_sites.py", "test_ytdlp_progress.py"]
    for f in non_spec_files:
        path = os.path.join(tests_dir, f)
        assert not os.path.exists(path), f"Non-spec test file {f} should not be on hardening/termux"
