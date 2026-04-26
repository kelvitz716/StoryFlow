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

### 6. Snapchat Backend Migration — Apify [RESOLVED]
The community-hosted `snapstories.netlify.app` API was permanently decommissioned (HTTP 404). The `snapchat-dlp` pip package was also verified broken due to Snapchat's SPA architecture changes.
- **Solution**: Replaced the custom API wrapper with the Apify `crawlerbros/snapchat-user-stories-scraper` cloud actor. The actor runs a fully managed Playwright/Chromium session on Apify's infrastructure and returns a JSON dataset of direct media URLs via a single HTTP POST.
- **Impact**: Zero memory overhead on the AWS server, no headless browser required, identical return dict shape so the rest of the bot required no changes.
- **Config**: `SNAPCHAT_API_BASE_URL` env var replaced with `APIFY_TOKEN`.

---

## 🚀 Future Roadmap & Long-term Goals

(No outstanding tasks currently identified for the core roadmap. System is operating at full functional capacity.)

---
*Last updated: 2026-04-26*
