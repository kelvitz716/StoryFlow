#!/bin/bash
set -e

# Extractor auto-update flag (G6, default true)
EXTRACTOR_AUTO_UPDATE="${EXTRACTOR_AUTO_UPDATE:-true}"

if [ "$EXTRACTOR_AUTO_UPDATE" = "true" ]; then
    echo "🔄 [Entrypoint] Upgrading yt-dlp and gallery-dl to the latest versions..."
    pip install --no-cache-dir --upgrade yt-dlp gallery-dl || echo "⚠️ extractor upgrade failed, continuing with installed versions"
else
    echo "ℹ️ [Entrypoint] EXTRACTOR_AUTO_UPDATE=false, using pinned extractor versions"
fi

python -c "import importlib.metadata as m; print('yt-dlp', m.version('yt-dlp'), '| gallery-dl', m.version('gallery_dl'))" || true

echo "🚀 [Entrypoint] Starting StoryFlow..."
exec python storyflow.py
