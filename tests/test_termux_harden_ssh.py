"""Tests for T3: termux/harden-ssh.sh OpenSSH hardening script."""

import glob
import os
import stat
import subprocess
import tempfile


SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "termux", "harden-ssh.sh")

EXPECTED_DIRECTIVES = [
    "PasswordAuthentication no",
    "KbdInteractiveAuthentication no",
    "PubkeyAuthentication yes",
    "PermitRootLogin no",
    "PermitEmptyPasswords no",
    "MaxAuthTries 3",
    "LoginGraceTime 20",
    "X11Forwarding no",
    "AllowAgentForwarding no",
    "ClientAliveInterval 60",
    "ClientAliveCountMax 3",
]


def test_harden_ssh_syntax():
    """Verify termux/harden-ssh.sh is valid POSIX sh via sh -n."""
    res = subprocess.run(["sh", "-n", SCRIPT_PATH], capture_output=True, text=True)
    assert res.returncode == 0, f"sh -n failed: {res.stderr}"


def test_no_authorized_key_fails_and_leaves_config_unchanged():
    """Verify script exits 1 and leaves config unchanged when no valid SSH key exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")
        initial_config = "# Initial config\nPort 8022\nPasswordAuthentication yes\n"
        with open(config_path, "w") as f:
            f.write(initial_config)

        # 1. Non-existent authorized_keys
        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["RELOAD"] = "0"

        res = subprocess.run(["sh", SCRIPT_PATH], env=env, capture_output=True, text=True)
        assert res.returncode == 1
        assert "Lockout protection" in res.stderr or "ssh-copy-id" in res.stderr
        with open(config_path, "r") as f:
            assert f.read() == initial_config

        # 2. authorized_keys exists but only has comments/whitespace
        with open(keys_path, "w") as f:
            f.write("# comment line\n   \n# another comment\n")

        res = subprocess.run(["sh", SCRIPT_PATH], env=env, capture_output=True, text=True)
        assert res.returncode == 1
        with open(config_path, "r") as f:
            assert f.read() == initial_config
        # Ensure no backups created
        assert len(glob.glob(f"{config_path}.bak.*")) == 0


def test_with_key_success_and_idempotent():
    """Verify that with an authorized key, all directives appear exactly once, backup exists, and second run is identical."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")
        stub_sshd = os.path.join(tmpdir, "stub_sshd")

        # Create stub sshd that succeeds
        with open(stub_sshd, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub_sshd, 0o755)

        # Create authorized key
        with open(keys_path, "w") as f:
            f.write("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG... user@host\n")

        initial_config = (
            "# Base SSH config\n"
            "Port 8022\n"
            "AllowTcpForwarding yes\n"
            "#PasswordAuthentication yes\n"
            "PasswordAuthentication yes\n"
            "MaxAuthTries 10\n"
        )
        with open(config_path, "w") as f:
            f.write(initial_config)

        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["SSHD_BIN"] = stub_sshd
        env["RELOAD"] = "0"

        # First run
        res = subprocess.run(["sh", SCRIPT_PATH], env=env, capture_output=True, text=True)
        assert res.returncode == 0, f"Failed: {res.stderr}"

        # Verify backup was created and has mode 600
        backups = glob.glob(f"{config_path}.bak.*")
        assert len(backups) >= 1
        backup_stat = os.stat(backups[0])
        assert stat.S_IMODE(backup_stat.st_mode) == 0o600

        # Read config after run 1
        with open(config_path, "r") as f:
            content_run1 = f.read()

        # Check every expected directive
        for directive in EXPECTED_DIRECTIVES:
            assert directive in content_run1
            # Check exactly once
            assert content_run1.count(directive) == 1

        # Check AllowUsers directive with current user
        import getpass
        current_user = getpass.getuser()
        assert f"AllowUsers {current_user}" in content_run1
        assert content_run1.count(f"AllowUsers {current_user}") == 1

        # Check AllowTcpForwarding was not touched
        assert "AllowTcpForwarding yes" in content_run1
        assert "Port 8022" in content_run1

        # Second run should leave the file completely identical
        res2 = subprocess.run(["sh", SCRIPT_PATH], env=env, capture_output=True, text=True)
        assert res2.returncode == 0

        with open(config_path, "r") as f:
            content_run2 = f.read()

        assert content_run1 == content_run2


def test_failing_sshd_stub_restores_config():
    """Verify that if sshd -t fails, config is restored to original and script exits 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")
        stub_sshd = os.path.join(tmpdir, "stub_sshd_failing")

        # Stub sshd that fails
        with open(stub_sshd, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(stub_sshd, 0o755)

        with open(keys_path, "w") as f:
            f.write("ecdsa-sha2-nistp256 AAAAE2VjZHNh... user@host\n")

        original_content = "Port 8022\nPasswordAuthentication yes\n"
        with open(config_path, "w") as f:
            f.write(original_content)

        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["SSHD_BIN"] = stub_sshd
        env["RELOAD"] = "0"

        res = subprocess.run(["sh", SCRIPT_PATH], env=env, capture_output=True, text=True)
        assert res.returncode == 1
        assert "Validation failed" in res.stderr or "Restoring backup" in res.stderr

        # Config must be restored to original
        with open(config_path, "r") as f:
            assert f.read() == original_content


def test_dry_run_leaves_config_unchanged():
    """Verify --dry-run prints changes and does not modify config or create backups."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")

        with open(keys_path, "w") as f:
            f.write("sk-ssh-ed25519@openssh.com AAAA... user@host\n")

        original_content = "# Original config\nPort 8022\n"
        with open(config_path, "w") as f:
            f.write(original_content)

        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["RELOAD"] = "0"

        res = subprocess.run(["sh", SCRIPT_PATH, "--dry-run"], env=env, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Dry Run" in res.stdout or "Proposed changes" in res.stdout

        # Config must remain unchanged
        with open(config_path, "r") as f:
            assert f.read() == original_content

        # No backups created
        assert len(glob.glob(f"{config_path}.bak.*")) == 0


def test_invalid_listen_rejected():
    """Verify invalid --listen values are rejected before making changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")

        with open(keys_path, "w") as f:
            f.write("ssh-ed25519 AAA... user@host\n")

        original_content = "Port 8022\n"
        with open(config_path, "w") as f:
            f.write(original_content)

        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["RELOAD"] = "0"

        for invalid_ip in ["invalid", "1.2.3", "1.2.3.4.5", "100.64.0.foo"]:
            res = subprocess.run(["sh", SCRIPT_PATH, "--listen", invalid_ip], env=env, capture_output=True, text=True)
            assert res.returncode == 1
            assert "Invalid IPv4 address" in res.stderr

        with open(config_path, "r") as f:
            assert f.read() == original_content


def test_valid_listen_applied():
    """Verify valid --listen address is applied exactly once."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "sshd_config")
        keys_path = os.path.join(tmpdir, "authorized_keys")
        stub_sshd = os.path.join(tmpdir, "stub_sshd")

        with open(stub_sshd, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub_sshd, 0o755)

        with open(keys_path, "w") as f:
            f.write("ssh-ed25519 AAA... user@host\n")

        with open(config_path, "w") as f:
            f.write("Port 8022\n")

        env = os.environ.copy()
        env["SSHD_CONFIG"] = config_path
        env["AUTH_KEYS"] = keys_path
        env["SSHD_BIN"] = stub_sshd
        env["RELOAD"] = "0"

        res = subprocess.run(["sh", SCRIPT_PATH, "--listen", "100.64.0.42"], env=env, capture_output=True, text=True)
        assert res.returncode == 0

        with open(config_path, "r") as f:
            content = f.read()

        assert "ListenAddress 100.64.0.42" in content
        assert content.count("ListenAddress 100.64.0.42") == 1
