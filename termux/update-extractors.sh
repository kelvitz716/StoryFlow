#!/data/data/com.termux/files/usr/bin/sh
# Update gallery-dl and yt-dlp extractors, then restart the service.
# Run manually whenever a site starts failing due to outdated extractors.
#
# Usage:
#   chmod +x termux/update-extractors.sh
#   ./termux/update-extractors.sh

set -e
umask 077

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/venv"
PREV_FILE="$REPO_DIR/data/extractors.prev"

echo "=== StoryFlow: Updating extractors ==="

# Activate venv
# shellcheck source=/dev/null
. "$VENV/bin/activate"

# Save current versions to extractors.prev (mode 600)
mkdir -p -m 700 "$REPO_DIR/data"
touch "$PREV_FILE"
chmod 600 "$PREV_FILE"

PREV_YTDLP=$(yt-dlp --version 2>/dev/null || echo "")
PREV_GALLERYDL=$(gallery-dl --version 2>/dev/null || echo "")

cat <<EOF > "$PREV_FILE"
yt-dlp==$PREV_YTDLP
gallery-dl==$PREV_GALLERYDL
EOF

echo "  Saved current extractor versions to $PREV_FILE"

echo "  Upgrading yt-dlp..."
pip install --upgrade yt-dlp

echo "  Upgrading gallery-dl..."
pip install --upgrade gallery-dl

# Verify upgraded versions
echo "  Verifying extractor versions..."
if ! (yt-dlp --version && gallery-dl --version) >/dev/null 2>&1; then
  echo "ERROR: Extractor verification failed after upgrade. Reinstalling saved versions..." >&2
  pip install -r "$PREV_FILE"
  exit 1
fi

echo "  Restarting StoryFlow service..."
sv restart storyflow && echo "  Service restarted." \
  || echo "  WARNING: Could not restart service. Restart manually with: sv restart storyflow"

echo ""
echo "=== Extractor update complete ==="
yt-dlp --version
gallery-dl --version

echo ""
echo "Rollback command: pip install -r $PREV_FILE"
