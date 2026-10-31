"""Tests for H2: deploy.sh .env permission protection and removal of hardcoded admin ID."""

import os


def test_deploy_script_env_permissions_and_no_hardcoded_admin():
    """Verify deploy.sh contains umask 077 and chmod 600 .env, and no longer contains 618026357."""
    deploy_path = os.path.join(os.path.dirname(__file__), "..", "deploy.sh")
    with open(deploy_path, "r") as f:
        content = f.read()

    assert "umask 077" in content
    assert "chmod 600 .env" in content
    assert "618026357" not in content


def test_update_oci_script_hardened():
    """Verify update_oci.sh has no ssh -A, uses HTTPS remote, and validates REF."""
    oci_script_path = os.path.join(os.path.dirname(__file__), "..", "update_oci.sh")
    with open(oci_script_path, "r") as f:
        content = f.read()

    # 1. No ssh -A (agent forwarding removed)
    assert "ssh -A" not in content

    # 2. HTTPS git remote
    assert "https://github.com/kelvitz716/StoryFlow.git" in content
    assert "git@github.com" not in content

    # 3. Validates REF
    assert "REF" in content
    assert "A-Za-z0-9" in content


def test_entrypoint_extractor_auto_update_flag():
    """Verify entrypoint.sh reads EXTRACTOR_AUTO_UPDATE, defaults to true, and has both branches."""
    entrypoint_path = os.path.join(os.path.dirname(__file__), "..", "entrypoint.sh")
    with open(entrypoint_path, "r") as f:
        content = f.read()

    # 1. Flag is read
    assert "EXTRACTOR_AUTO_UPDATE" in content

    # 2. Default is true
    assert 'EXTRACTOR_AUTO_UPDATE="${EXTRACTOR_AUTO_UPDATE:-true}"' in content or 'EXTRACTOR_AUTO_UPDATE:-true' in content

    # 3. Both branches exist
    assert 'if [ "$EXTRACTOR_AUTO_UPDATE" = "true" ]' in content or 'if [ "$EXTRACTOR_AUTO_UPDATE" == "true" ]' in content
    assert "pip install --no-cache-dir --upgrade yt-dlp gallery-dl" in content
    assert "else" in content
    assert "pinned" in content.lower() or "EXTRACTOR_AUTO_UPDATE=false" in content
