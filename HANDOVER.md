# StoryFlow Project Handover Document

## Project Overview
StoryFlow is a unified media downloader designed for social media content. It supports Snapchat, Instagram, TikTok, Twitter/X, and Facebook. The project is built with Python 3.12 and can run as either a CLI tool or a Telegram bot.

---

## File Tree
```text
.
├── auth                    # Authentication & Access Control
│   ├── access.py           # Whitelisting & Admin logic
│   ├── cookies.py          # Cookie management (IG, FB, TikTok)
│   ├── __init__.py
│   └── mtproto.py          # MTProto client for 2GB uploads
├── bot                     # Telegram Interaction Layer
│   ├── __init__.py
│   └── telegram_bot.py     # Main bot handlers & UI
├── core                    # Business Logic
│   ├── __init__.py
│   ├── platform.py         # URL identification & routing
│   ├── queue.py            # Async download worker queue
│   ├── rate_limiter.py     # API protection
│   ├── retry.py            # Resilience logic
│   ├── security.py         # Sanitization
│   ├── stats.py            # Usage statistics
│   └── storage.py          # File management
├── docs                    # Documentation (Second Brain)
│   ├── guides
│   │   ├── SETUP.md
│   │   └── USAGE.md
│   ├── planning
│   │   └── IMPROVEMENTS.md
│   ├── technical
│   │   ├── ARCHITECTURE.md
│   │   ├── command_flow.md
│   │   └── SPECIFICATIONS.md
│   └── README.md
├── downloaders             # Platform Specific Wrappers
│   ├── gallery_dl.py       # Wrapper for gallery-dl (IG, TT, FB, X)
│   ├── __init__.py
│   └── snapchat.py         # Apify-powered Snapchat story downloader
├── scripts                 # Utility Scripts
│   └── generate_session.py # For MTProto login persistence
├── tests                   # Testing
│   ├── run_test_links.py
│   └── test_links.md
├── utils                   # Helpers
│   ├── __init__.py
│   └── log_sanitizer.py
├── deploy.sh               # AWS/Docker Deployment Script
├── Dockerfile              # Docker configuration
├── README.md               # Quick Start Guide
├── requirements.txt        # Python dependencies
└── storyflow.py            # Main entry point
```

---

## Architecture & Core Technologies
- **Python 3.12**: Required for compatibility with `tgcrypto` and latest async patterns.
- **Telegram Bot API (python-telegram-bot)**: Primary interface.
- **Pyrogram (MTProto)**: Used as a side-car client to bypass the 50MB Bot API limit, allowing uploads up to 2GB.
- **gallery-dl & yt-dlp**: Core engines for media extraction (Instagram, TikTok, Facebook, Twitter/X).
- **Apify** (`crawlerbros/snapchat-user-stories-scraper`): Cloud-side headless browser actor for Snapchat story downloads. Eliminates the need to run Playwright/Chromium locally — the server sends a single HTTP POST and receives direct media URLs in return.
- **Docker**: Containerized deployment with volume persistence for cookies and sessions.

---

## Recent Key Changes & Refactoring

### 1. Advanced Access Control (`auth/access.py`)
- **Telegram Channel Support**: The bot now supports being used in channels linked to discussion groups. It correctly identifies `automatic_forward` messages from channels and allows whitelisting by Channel ID.
- **Anonymous Sender Support**: Handles messages from `@GroupAnonymousBot` by falling back to the `chat_id` for authorization checks.
- **Whitelisting Persistence**: Allowed users and channels are stored in `data/allowed_users.json`, ensuring access remains across restarts.

### 2. Large File Handling
- Integrated **MTProto** for uploading files larger than 50MB.
- Implemented a **progress bar** for large uploads to provide user feedback.
- Automated **file cleanup** immediately after upload to save server disk space.

### 3. AWS Deployment Optimization
- `deploy.sh` script handles everything: `.env` configuration, Docker build, volume creation, and permission fixes.
- Configured for **AWS Free Tier** (EC2 t2.micro) with a swap file recommended for memory-intensive gallery-dl operations.

### 4. Snapchat Backend Migration (April 2026)
- **Old backend** (`snapstories.netlify.app`) confirmed dead (permanent `404`).
- `snapchat-dlp` pip package also broken (`APIResponseError`) due to Snapchat SPA changes.
- Migrated to **Apify** (`crawlerbros/snapchat-user-stories-scraper` actor). Cloud-hosted Playwright sessions bypass Snapchat restrictions cleanly with zero memory overhead on the AWS server.
- `SNAPCHAT_API_BASE_URL` env var replaced with `APIFY_TOKEN`.

---

## Authentication Systems
1. **Bot Token**: Standard Telegram bot token for interaction.
2. **MTProto Session**: `API_ID` and `API_HASH` are required. Use `scripts/generate_session.py` to create a `TELEGRAM_SESSION_STRING` for headless production environments.
3. **Cookies**: Users can upload `cookies.txt` (Netscape format) via the bot to enable downloading of private or age-restricted content (Instagram Stories, Facebook Reels).
4. **Apify API Token**: Required for Snapchat story downloads. Set `APIFY_TOKEN` in `.env`. Free tier: $5/month at [apify.com](https://apify.com).

---


## Current Status & Known Limitations
- **Snapchat**: Powered by Apify cloud actor. Public stories only. Usage is billed at $1.00/1,000 results (free tier covers ~5,000 downloads/month).
- **Instagram**: Very sensitive to rate limits. Always use fresh cookies for stable story downloading.
- **Disk Space**: While there is auto-cleanup, failed downloads might leave artifacts. Use the `/purge` command (Admin only) to clear the `downloads/` directory.

---

## Future Roadmap
- [ ] **Multi-account rotation** for Instagram cookies to avoid blocks.
- [ ] **Web Dashboard** for viewing global statistics and managing users.
- [ ] **Direct Streaming** support to avoid disk writes entirely.
- [ ] **Proxy Integration** at the downloader level to bypass geo-blocks.

---

**Handover completed by Antigravity AI.**
