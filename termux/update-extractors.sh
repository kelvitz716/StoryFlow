#!/data/data/com.termux/files/usr/bin/sh
# Update gallery-dl and yt-dlp extractors, then restart the service.
# Run manually whenever a site starts failing due to outdated extractors.
#
# Usage:
#   chmod +x termux/update-extractors.sh
#   ./termux/update-extractors.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/venv"

echo "=== StoryFlow: Updating extractors ==="

# Activate venv
# shellcheck source=/dev/null
. "$VENV/bin/activate"

echo "  Upgrading yt-dlp..."
pip install --upgrade yt-dlp

echo "  Upgrading gallery-dl..."
pip install --upgrade gallery-dl

echo "  Restarting StoryFlow service..."
sv restart storyflow && echo "  Service restarted." \
  || echo "  WARNING: Could not restart service. Restart manually with: sv restart storyflow"

echo ""
echo "=== Extractor update complete ==="
yt-dlp --version
gallery-dl --version
