"""Tests for item 4: termux/setup.sh requirements installation with TgCrypto filtered out."""

import os
import subprocess
import tempfile


def test_setup_script_has_tgcrypto_filter():
    """Verify termux/setup.sh uses grep -viE '^tgcrypto' and temp file without '|| true'."""
    setup_path = os.path.join(os.path.dirname(__file__), "..", "termux", "setup.sh")
    with open(setup_path, "r") as f:
        content = f.read()

    assert "grep -viE '^tgcrypto'" in content or 'grep -viE "^tgcrypto"' in content
    assert "REQ_TMP=$(mktemp)" in content or "mktemp" in content
    assert 'pip install -r "$REQ_TMP"' in content
    # Ensure no '|| true' on the core pip install line
    for line in content.splitlines():
        if 'pip install -r "$REQ_TMP"' in line:
            assert "|| true" not in line
    # Verify TgCrypto is attempted separately
    assert "pip install TgCrypto" in content


def test_tgcrypto_filtering_output():
    """Verify that filtering requirements.txt actually strips TgCrypto but keeps other packages."""
    req_path = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp_name = tmp.name

    try:
        cmd = f"grep -viE '^tgcrypto' {req_path} > {tmp_name}"
        res = subprocess.run(cmd, shell=True, check=True)
        assert res.returncode == 0

        with open(tmp_name, "r") as f:
            filtered = f.read()

        assert "TgCrypto" not in filtered
        assert "tgcrypto" not in filtered.lower()
        assert "yt-dlp" in filtered
        assert "gallery_dl" in filtered
        assert "python-telegram-bot" in filtered
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
