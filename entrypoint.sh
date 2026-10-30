#!/bin/bash
set -e

echo "🔄 [Entrypoint] Upgrading yt-dlp and gallery-dl to the latest versions..."
pip install --no-cache-dir --upgrade yt-dlp gallery-dl || echo "⚠️ extractor upgrade failed, continuing with installed versions"

echo "🚀 [Entrypoint] Starting StoryFlow..."
exec python storyflow.py
