# StoryFlow Project Handover Document

## Project Overview
StoryFlow is a unified media downloader for social media content. It supports Snapchat, Instagram, TikTok, Twitter/X, and Facebook. The project is built with Python 3.12 and runs as a Telegram bot (primary) or CLI tool.

**Deployment target:** Android phone running Termux, co-hosted with Jellyfin, Sonarr, Radarr, and qBittorrent, reachable over Tailscale (100.64.0.0/10). See `termux/README.md` for setup.

---

## File Tree
```text
.
├── auth                    # Authentication & Access Control
│   ├── access.py           # Whitelisting & Admin logic (SQLite-backed)
│   ├── cookies.py          # Cookie management (IG, FB, TikTok)
│   ├── __init__.py
│   └── mtproto.py          # MTProto client for files >50 MB (optional)
├── bot                     # Telegram Interaction Layer
│   ├── guards.py           # require_allowed() access guard
│   ├── handlers.py         # Command routing & message handling
│   ├── menus.py            # Inline keyboard menus
│   ├── uploader.py         # Media delivery & MTProto fallback
│   ├── __init__.py
│   └── telegram_bot.py     # Entry point & component wiring
├── core                    # Business Logic
│   ├── __init__.py
│   ├── platform.py         # URL identification & SSRF-gated routing
│   ├── queue.py            # Async download worker queue (SQLite-backed)
│   ├── rate_limiter.py     # API protection
│   ├── security.py         # validate_domain, is_safe_url (SSRF protection)
│   ├── stats.py            # Usage statistics
│   └── storage.py          # File management
├── docs                    # Documentation
│   ├── guides/
│   ├── planning/
│   │   └── IMPROVEMENTS.md
│   ├── technical/
│   │   └── SPECIFICATIONS.md
│   └── README.md
├── downloaders             # Platform-specific wrappers
│   ├── base.py             # BaseDownloader (subprocess hygiene, stderr drain)
│   ├── gallery_dl.py       # gallery-dl & yt-dlp wrapper (IG, TT, FB, X)
│   ├── __init__.py
│   └── snapchat.py         # Snapchat story downloader (direct scraper + yt-dlp)
├── scripts                 # Utility scripts
│   └── generate_session.py # MTProto session string generator
├── termux                  # Termux/Android deployment
│   ├── setup.sh            # First-install script
│   ├── update-extractors.sh
│   ├── service/run         # runit service script
│   ├── service/log/run     # runit log script
│   └── README.md           # Full Termux deployment guide
├── tests                   # pytest test suite
│   ├── test_security.py
│   ├── test_platform_redirect.py
│   ├── test_subprocess.py
│   ├── test_stderr_leak.py
│   ├── test_access_control.py
│   ├── test_cookie_fallback.py
│   └── test_config.py
├── utils                   # Helpers
│   ├── __init__.py
│   ├── bot_utils.py        # resolve_shortlink (hop-by-hop validation), formatters
│   └── log_sanitizer.py
├── .env.example            # Environment template (see all variables here)
├── requirements.txt        # Pinned production dependencies
├── requirements-dev.txt    # Dev dependencies (pytest)
└── storyflow.py            # Main entry point
```

---

## Architecture & Core Technologies
- **Python 3.12**: Required for compatibility with `tgcrypto` and latest async patterns.
- **Telegram Bot API (python-telegram-bot)**: Primary interface.
- **Pyrogram (MTProto)**: Optional side-car client for uploads >50 MB. If Pyrogram/TgCrypto are not installed (common on Termux), the bot continues with the standard 50 MB Bot API limit.
- **gallery-dl & yt-dlp**: Core extraction engines (Instagram, TikTok, Facebook, Twitter/X).
- **Snapchat**: Direct HTTP scraping of `story.snapchat.com` combined with yt-dlp's `SnapchatSpotlight` extractor for Spotlight URLs. No external cloud service is required.
- **SQLite**: Backing store for the job queue and user access list.

---

## Security Architecture (hardening/termux branch)

| Layer | What it does |
|-------|-------------|
| `validate_domain` | Rejects URLs with userinfo (`@`), non-http(s) schemes, trailing-dot attacks |
| `is_safe_url` | Blocks loopback, RFC-1918, link-local, Tailscale CGNAT (100.64/10), multicast, unresolvable hosts; unwraps IPv4-mapped IPv6 |
| `identify_platform` | Calls `is_safe_url` on **every** URL before platform dispatch |
| `resolve_shortlink` | Manual hop-by-hop redirect follower (max 5 hops); calls `is_safe_url` before each hop; raises `UnsafeRedirectError` on failure (fail closed) |
| `BaseDownloader` | `start_new_session=True`; concurrent stderr drain capped at 64 KB; wall-clock timeout → `killpg`; 1 MB pipe buffer; never returns raw stderr in result dicts |
| `require_allowed` | Guards all handlers; silent in groups, rejects with user ID in private |
| Admin cookie fallback | Disabled by default; opt-in via `ALLOW_ADMIN_COOKIE_FALLBACK=true` |
| Startup | Validates `ADMIN_USER_ID` numerically; `chmod 600 .env` + cookie files; `chmod 700` on sessions/data directories |

---

## Authentication Systems
1. **Bot Token**: Set `TELEGRAM_BOT_TOKEN` in `.env`.
2. **MTProto Session** (optional): Set `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `TELEGRAM_SESSION_STRING`. Generate the session string with `python scripts/generate_session.py`.
3. **Cookies**: Users upload `cookies.txt` (Netscape format) via `/manage_cookies`. Files are size-checked (≤256 KB) and extension-checked (`.txt`) before `get_file()` is ever called.
4. **Apify API Token**: Required for Snapchat story downloads. Set `APIFY_TOKEN` in `.env`. Free tier: $5/month at [apify.com](https://apify.com).

---

## Environment Variables
See `.env.example` for the full annotated list. Key variables added by the hardening branch:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_CONCURRENT_JOBS` | `2` | Parallel download workers (clamped 1–10) |
| `MAX_JOBS_PER_USER` | `5` | Max queued jobs per user |
| `MAX_FILE_SIZE_MB` | `500` | Reject files larger than this (gallery-dl + yt-dlp) |
| `DOWNLOAD_TIMEOUT_SECONDS` | `600` | Wall-clock timeout per subprocess |
| `ALLOW_ADMIN_COOKIE_FALLBACK` | `false` | Share admin cookies with all users (opt-in) |

---

## Current Status & Known Limitations
- **Snapchat Stories / Highlights / Spotlight**: Handled via direct scraper; Apify is no longer required but the token is still read if present.
- **Instagram**: Sensitive to rate limits. Always use fresh cookies.
- **MTProto on Termux**: TgCrypto may fail to build; the bot continues without it (files ≤50 MB only).
- **Disk Space**: Use `/purge` (admin only) to clear `downloads/` if space is low.

---

## Future Roadmap
- [ ] Multi-account Instagram cookie rotation.
- [ ] Web dashboard for statistics and user management.
- [ ] Direct streaming support (avoid disk writes).
- [ ] Proxy integration at the downloader level for geo-blocks.

---

**Handover updated by Antigravity AI — hardening/termux branch.**
