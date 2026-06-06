#!/bin/bash
set -e

echo "🔄 [Entrypoint] Upgrading yt-dlp and gallery-dl to the latest versions..."
# Upgrade core download libraries at container launch to handle breaking site changes
pip install --no-cache-dir --upgrade yt-dlp gallery-dl

echo "🚀 [Entrypoint] Starting StoryFlow..."
exec python storyflow.py
