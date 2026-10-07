#!/data/data/com.termux/files/usr/bin/sh
# StoryFlow Termux Setup Script
#
# Run once after cloning the repository to set up the Python environment.
# Usage:
#   cd ~/StoryFlow
#   chmod +x termux/setup.sh
#   ./termux/setup.sh

set -e

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
# We install it separately so a build failure doesn't abort the rest.
echo "  Installing core requirements..."
pip install -r "$REPO_DIR/requirements.txt" --ignore-installed TgCrypto || true

echo "  Attempting TgCrypto install (optional — needed for MTProto large-file uploads)..."
pip install TgCrypto && echo "  TgCrypto installed OK." \
  || echo "  WARNING: TgCrypto build failed. MTProto large-file uploads will be unavailable."

# ── 4. runit service ────────────────────────────────────────────────────────
echo "[4/4] Installing runit service files..."

SV_DIR="$HOME/.config/sv/storyflow"
mkdir -p "$SV_DIR/log"
mkdir -p "$HOME/logs/storyflow"

# Copy service scripts and make them executable
cp "$REPO_DIR/termux/service/run"     "$SV_DIR/run"
cp "$REPO_DIR/termux/service/log/run" "$SV_DIR/log/run"
chmod +x "$SV_DIR/run" "$SV_DIR/log/run"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and fill in your values:"
echo "       cp $REPO_DIR/.env.example $REPO_DIR/.env"
echo "       nano $REPO_DIR/.env"
echo ""
echo "  2. Enable and start the service:"
echo "       sv-enable storyflow"
echo "       sv start storyflow"
echo ""
echo "  3. Check logs:"
echo "       tail -f $HOME/logs/storyflow/current"
echo ""
echo "  4. See termux/README.md for battery optimisation and wake-lock info."
