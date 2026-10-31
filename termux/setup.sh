#!/data/data/com.termux/files/usr/bin/sh
# StoryFlow Termux Setup Script
#
# Run once after cloning the repository to set up the Python environment.
# Usage:
#   cd ~/StoryFlow
#   chmod +x termux/setup.sh
#   ./termux/setup.sh

set -e
umask 077

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/venv"

echo "=== StoryFlow Termux Setup ==="
echo "Repo: $REPO_DIR"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/4] Installing system packages via pkg..."
pkg install -y python clang make libffi openssl-tool ffmpeg

# ── 2. Python virtual environment ───────────────────────────────────────────
echo "[2/4] Creating Python virtual environment..."
python -m venv "$VENV"
# shellcheck source=/dev/null
. "$VENV/bin/activate"

# ── 3. Python dependencies ──────────────────────────────────────────────────
echo "[3/4] Installing Python dependencies..."
pip install --upgrade pip wheel

# TgCrypto requires a C compiler and may fail on some Termux builds.
# Install core requirements with TgCrypto filtered out; fail loudly if it fails.
echo "  Installing core requirements (excluding TgCrypto)..."
REQ_TMP=$(mktemp)
grep -viE '^tgcrypto' "$REPO_DIR/requirements.txt" > "$REQ_TMP"
pip install -r "$REQ_TMP"
rm -f "$REQ_TMP"

echo "  Attempting TgCrypto install (optional — needed for MTProto large-file uploads)..."
REQ_TMP=$(mktemp)
if grep -iE '^tgcrypto' "$REPO_DIR/requirements.txt" > "$REQ_TMP" && [ -s "$REQ_TMP" ]; then
  pip install -r "$REQ_TMP" && echo "  TgCrypto installed OK." \
    || echo "  WARNING: TgCrypto build failed. MTProto large-file uploads will be unavailable."
else
  echo "  WARNING: No TgCrypto pinned line found in requirements.txt; skipping."
fi
rm -f "$REQ_TMP"

# ── 4. runit service & directories ──────────────────────────────────────────
echo "[4/4] Installing runit service files and securing directories..."

# Create directories with secure permissions (700)
mkdir -p -m 700 "$REPO_DIR/sessions" "$REPO_DIR/cookies" "$REPO_DIR/data" "$HOME/logs/storyflow"
chmod 700 "$REPO_DIR/sessions" "$REPO_DIR/cookies" "$REPO_DIR/data" "$HOME/logs/storyflow"

# Create .env securely if missing
[ -f "$REPO_DIR/.env" ] || install -m 600 "$REPO_DIR/.env.example" "$REPO_DIR/.env"

# Termux's sv-enable reads from $SVDIR (defaults to ~/.config/runit/sv).
# Fall back to the env var if set, otherwise use the Termux default.
RUNIT_SV_DIR="${SVDIR:-$HOME/.config/runit/sv}"
SV_DIR="$RUNIT_SV_DIR/storyflow"
mkdir -p "$SV_DIR/log"

# Copy service scripts and make them executable
cp "$REPO_DIR/termux/service/run"     "$SV_DIR/run"
cp "$REPO_DIR/termux/service/log/run" "$SV_DIR/log/run"
chmod +x "$SV_DIR/run" "$SV_DIR/log/run"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and fill in your values:"
echo "       nano $REPO_DIR/.env"
echo ""
echo "  2. Secure your SSH server (recommended):"
echo "       sh termux/harden-ssh.sh"
echo ""
echo "  3. Enable and start the service:"
echo "       sv-enable storyflow"
echo "       sv start storyflow"
echo ""
echo "  4. Check logs:"
echo "       tail -f $HOME/logs/storyflow/current"
echo ""
echo "  5. See termux/README.md for battery optimisation and wake-lock info."
echo "  Service installed to: $SV_DIR"
