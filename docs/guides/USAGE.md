# Usage Guide

## Telegram Bot

StoryFlow is a high-reliability bot designed for seamless media retrieval.

### Basic Commands

| Command | Description |
|:---|:---|
| `/start` | Opens the main interactive dashboard. (Access Stats, Cookies, Admin Tools here). |
| `/help` | Detailed usage instructions and platform tips. |
| `/queue` | View your current active downloads and queue position. |

### Downloading Media

Simply **send any supported link** to the bot. StoryFlow uses a specialized **Job Queue** to ensure every request is handled reliably, even during high-traffic periods.

**Supported Platforms:**
- **Instagram**: Reels, Stories, Posts (including private content with cookies).
- **Snapchat**: Stories (active 24h), Highlights (saved albums), and Spotlight videos.
- **TikTok**: High-quality watermark-free videos.
- **Facebook**: Reels and public videos.
- **Twitter/X**: Media attachments and GIFs.

### The Download Process

1.  **Submission**: Your link is added to the queue instantly.
2.  **Isolation**: The bot creates a unique, private directory just for your job to ensure privacy.
3.  **Download**: The system uses a multi-stage approach (gallery-dl -> fallback to yt-dlp) to ensure retrieval success.
4.  **Delivery**: Media is sent back to you (MTProto is used for files >50MB to support up to 2GB delivery).
5.  **Nuclear Cleanup**: The temporary files and private directory are deleted *immediately* after delivery.

### Admin Features

Admins can manage the bot via the **Admin Tools** button inside the `/start` menu:
- **Queue Status**: Active and pending jobs visible in server UI.
- **System Purge**: One-click purge of all temporary media debris.
- **User Management**: Authorize new users interactively via the bot UI.

---

## CLI Mode

StoryFlow can also be used as a CLI tool for local testing or batch processing.

```bash
# Set MODE=cli in .env
python storyflow.py
```

The CLI now uses the same underlying **Async Job Engine** as the bot, ensuring consistent performance across both interfaces.
