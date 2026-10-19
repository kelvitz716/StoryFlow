# Efficiency Analysis & Improvement Plan

This document outlines identified bottlenecks and proposed improvements to enhance the performance and scalability of StoryFlow.

## ✅ Completed Improvements

### 1. Non-Blocking Downloader Execution [RESOLVED]
Previously, synchronous `subprocess` calls would freeze the entire bot event loop.
- **Solution**: Refactored `GalleryDLDownloader` and `SnapchatDownloader` to execute within the `DownloadQueue` worker context, ensuring the bot remains responsive during heavy downloads.

### 2. Concurrency Management & Isolation [RESOLVED]
- **Queue Integration**: The `DownloadQueue` is now the core engine of StoryFlow.
- **Job Isolation**: Implemented `downloads/{job_id}/` subdirectory isolation to prevent media leakage between concurrent users.
- **Auto-Cleanup**: Automated immediate deletion of job-specific folders upon delivery or failure.
- **Safe Sweep**: Added a "Safe Sweep" startup cycle to clear stale debris on system reboot.

### 3. Modular Bot Architecture [RESOLVED]
- Refactored the monolithic `telegram_bot.py` into specialized modules (`bot/`, `utils/`), significantly improving code readability and making 24/7 AWS maintenance easier.
- Synchronized UI updates using a centralized `JOB_MESSAGES` registry to avoid orphaned status messages.

### 4. Robust Rate Limiting & MTProto Rescue [RESOLVED]
- **Smart Retries**: Batch Media Group uploads now wait and natively retry without crashing out or jumping to Pyrogram for minimal delays.
- **Failover**: Instant, automatic fallback to the MTProto User Client if the files are >50MB.
- **Status Guarding**: Implemented a Time-Based UI Throttler (`safe_edit_text`) with an in-memory cache to mathematically prevent `429 Too Many Requests` storms caused by small text edits.
- **API Request Spacing**: Decoupled UI updates from massive `sendMediaGroup` blasts via deliberate 5-second cooling delays to ensure Telegram burst limits are safely navigated.

### 5. Increased Architecture Capacity [RESOLVED]
- **Worker Scaling**: The global background engine has been scaled up to handle up to 5 concurrent worker threads simultaneously natively on AWS.
- **User Queues**: Increased the `max_per_user` threshold to 10 instances allowing massive multi-batch queueing.
- **Live Dashboard**: Added a `/queue` endpoint for live visibility into active workers and pending tasks without digging into logs.

### 6. Snapchat Backend Migration — Direct Scraper [RESOLVED]
The community-hosted `snapstories.netlify.app` API was permanently decommissioned (HTTP 404).
- **Solution**: Replaced the custom API wrapper with a direct web scraper targeting `story.snapchat.com` __NEXT_DATA__ JSON and yt-dlp Spotlight extractor.
- **Impact**: Zero external cloud services, tokens, or costs required.
- **Config**: Configurable rate limit via `MAX_REQUESTS_PER_MINUTE`.

---

## 🚀 Future Roadmap & Long-term Goals

### 1. Profile & Channel Download Policy (TikTok, Instagram, Twitter) [DECIDED]
- **Issue**: Profile URLs (e.g., `tiktok.com/@username`, `instagram.com/username`) trigger full user archive/playlist scraping in `gallery-dl`, potentially downloading hundreds of files, hitting the 5-minute subprocess timeout, or exhausting queue capacity. Meanwhile, `yt-dlp` has `--no-playlist` and only downloads 1 file.
- **Decision**: **Option 3 — Configurable toggle** with a safe default of `ALLOW_PROFILE_DOWNLOADS=false`.
  - Default-off prevents accidental mass-downloads on shared or Termux-constrained deployments.
  - Admins can opt in by setting `ALLOW_PROFILE_DOWNLOADS=true` in `.env`.
  - When enabled, pair with `MAX_PROFILE_ITEMS=10` passed as `--range 1-N` (gallery-dl) or `--playlist-items 1-N` (yt-dlp) to bound the worst case.
- **Implementation**:
  1. Add `ALLOW_PROFILE_DOWNLOADS` and `MAX_PROFILE_ITEMS` to `core/config.py` via `_env_bool` / `_env_int`.
  2. In `core/platform.py → identify_platform()`, detect profile patterns (e.g. path has no post ID after the username).
  3. In `bot/handlers/url.py → handle_url()`, check `ALLOW_PROFILE_DOWNLOADS`; if false, reply with:
     > ℹ️ *Profile links are not supported.* Please send a direct post or video link.
  4. In `downloaders/base.py`, when `is_profile=True`, append `--range 1-{MAX_PROFILE_ITEMS}` / `--playlist-items 1-{MAX_PROFILE_ITEMS}` to the subprocess args.
- **Status**: Decided — implementation deferred to next sprint.

---
*Last updated: 2026-10-19*
