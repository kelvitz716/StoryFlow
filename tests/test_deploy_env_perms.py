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
