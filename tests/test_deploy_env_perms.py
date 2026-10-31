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


def test_deploy_script_pre_compose_preparation():
    """Verify deploy.sh prepares directories including logs, chowns UID 1000, and creates proxy_net before compose up."""
    deploy_path = os.path.join(os.path.dirname(__file__), "..", "deploy.sh")
    with open(deploy_path, "r") as f:
        content = f.read()

    # 1. Assert mkdir -p downloads cookies sessions data logs
    assert "mkdir -p downloads cookies sessions data logs" in content

    # 2. Assert alpine chown -R 1000:1000 including logs
    assert "chown -R 1000:1000 /downloads /cookies /sessions /data /logs" in content
    assert "Warning: Permission fix failed" in content

    # 3. Assert proxy_net network creation
    assert "docker network create proxy_net" in content

    # 4. Assert all three come before docker compose up
    compose_idx = content.find("docker compose up")
    assert compose_idx != -1

    mkdir_idx = content.find("mkdir -p downloads cookies sessions data logs")
    chown_idx = content.find("chown -R 1000:1000 /downloads /cookies /sessions /data /logs")
    network_idx = content.find("docker network create proxy_net")

    assert mkdir_idx < compose_idx
    assert chown_idx < compose_idx
    assert network_idx < compose_idx


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


def test_update_oci_require_signed_remote_command():
    """Verify update_oci.sh remote command structure: starts with set -e, no subshell exit, and verification before docker rm."""
    oci_script_path = os.path.join(os.path.dirname(__file__), "..", "update_oci.sh")
    with open(oci_script_path, "r") as f:
        content = f.read()

    # 1. Remote command starts with set -e;
    assert '"set -e;' in content

    # 2. No subshell-exit pattern like (echo ... && exit 1)
    assert "(echo '❌ Verification failed: commit/tag not signed' >&2 && exit 1)" not in content
    assert "exit 1; }" in content

    # 3. Verify-tag or verify-commit logic present
    assert "git verify-tag" in content
    assert "git verify-commit" in content

    # 4. Verification must come before docker rm
    verify_idx = content.find("${VERIFY_CMD}")
    docker_rm_idx = content.find("docker rm -f storyflow_app")
    assert verify_idx != -1
    assert docker_rm_idx != -1
    assert verify_idx < docker_rm_idx
