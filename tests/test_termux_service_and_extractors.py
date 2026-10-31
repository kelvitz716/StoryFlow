"""Tests for T2: termux/service/run and termux/update-extractors.sh hardening and syntax."""

import os
import subprocess


def test_service_run_static_assertions():
    """Verify termux/service/run contains umask 077, missing .env check, chmod 600 .env, and shared storage refusal."""
    service_run_path = os.path.join(os.path.dirname(__file__), "..", "termux", "service", "run")
    with open(service_run_path, "r") as f:
        content = f.read()

    # 1. umask 077
    assert "umask 077" in content

    # 2. Check for missing .env before exec
    assert "[ ! -f .env ]" in content or "! [ -f .env ]" in content
    assert "exit 1" in content
    env_check_idx = content.find(".env ]")
    exec_idx = content.find("exec python")
    assert env_check_idx != -1
    assert exec_idx != -1
    assert env_check_idx < exec_idx

    # 3. chmod 600 .env
    assert "chmod 600 .env" in content

    # 4. Refuse DOWNLOAD_PATH under /sdcard, /storage/, or $HOME/storage
    assert "DOWNLOAD_PATH" in content
    assert "/sdcard" in content
    assert "/storage" in content
    assert "storage" in content


def test_service_run_syntax():
    """Verify termux/service/run passes sh -n syntax check."""
    service_run_path = os.path.join(os.path.dirname(__file__), "..", "termux", "service", "run")
    res = subprocess.run(["sh", "-n", service_run_path], capture_output=True, text=True)
    assert res.returncode == 0, f"sh -n failed: {res.stderr}"


def test_update_extractors_static_assertions():
    """Verify update-extractors.sh saves versions with mode 600, checks versions, handles rollback, and prints rollback command."""
    update_path = os.path.join(os.path.dirname(__file__), "..", "termux", "update-extractors.sh")
    with open(update_path, "r") as f:
        content = f.read()

    # 1. umask 077 and mode 600 for extractors.prev in $REPO_DIR/data
    assert "umask 077" in content
    assert "extractors.prev" in content
    assert "chmod 600" in content

    # 2. Checks yt-dlp --version && gallery-dl --version
    assert "yt-dlp --version && gallery-dl --version" in content or (
        "yt-dlp --version" in content and "gallery-dl --version" in content
    )

    # 3. Reinstalls saved versions on failure, exits 1, does not restart service
    assert 'pip install -r "$PREV_FILE"' in content or 'pip install -r $PREV_FILE' in content
    fail_idx = content.find('pip install -r "$PREV_FILE"')
    restart_idx = content.find("sv restart storyflow")
    assert fail_idx != -1
    assert restart_idx != -1
    assert fail_idx < restart_idx

    # 4. Prints rollback command at the end
    assert "Rollback command:" in content or "rollback" in content.lower()


def test_update_extractors_syntax():
    """Verify termux/update-extractors.sh passes sh -n syntax check."""
    update_path = os.path.join(os.path.dirname(__file__), "..", "termux", "update-extractors.sh")
    res = subprocess.run(["sh", "-n", update_path], capture_output=True, text=True)
    assert res.returncode == 0, f"sh -n failed: {res.stderr}"
