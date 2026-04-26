# Architecture Overview

StoryFlow is a modular Telegram bot and CLI application designed for downloading media from various social media platforms. It leverages a combination of custom API wrappers and external tools (`gallery-dl`, `yt-dlp`) to handle content retrieval.

## System Diagram

```mermaid
graph TD
    User[User] -->|Commands/URLs| Bot[Telegram Bot]
    Bot -->|Handlers| Handlers[bot/handlers.py]
    Handlers -->|UI/Menus| Menus[bot/menus.py]
    
    Handlers -->|Queue Job| Queue[core/queue.py]
    Queue -->|Worker| Worker[Queue Worker]
    
    Worker -->|Snapchat| SnapDL[Snapchat Downloader]
    Worker -->|Insta/TikTok/FB| GalleryDL[Gallery-DL Wrapper]
    SnapDL & GalleryDL -->|Inherits| BaseDL[BaseDownloader]
    GalleryDL -->|Fallback| YTDLP[yt-dlp Wrapper]

    SnapDL -->|HTTP POST| Apify[Apify Cloud Actor]
    Apify -->|JSON dataset| SnapDL
    
    Worker -->|Success/Files| Uploader[bot/uploader.py]
    Uploader -->|Small Files <50MB| TelegramAPI[Telegram Bot API]
    TelegramAPI -.->|Rate Limit / FloodWait| MTProto
    Uploader -->|Large Files >50MB| MTProto[MTProto Client (Pyrogram)]
```

## Key Components

### 1. Bot Interface (`bot/`)
Modularized for high-performance interaction and maintainability.
- `handlers.py`: Command routing and message processing.
- `menus.py`: UI layout, keyboards, and navigation flow.
- `uploader.py`: Media batching, delivery logic, and MTProto fallback (rescues rate-limited transfers).
- `telegram_bot.py`: Main entry point and orchestration.

### 2. Core Logic (`core/`)
- **Platform Identification**: Regex-based detection of social media URLs (`platform.py`).
- **Database Architecture**: Centralized, WAL-enabled SQLite database (`database.db`) enforcing ACID guarantees over user authorization lists, global user statistics, and persistent job states (`database.py`, `stats.py`).
- **Queue System**: Async worker-based queue. Manages concurrency natively up to `10` simultaneous streams. Persists all actions to SQLite jobs table allowing orphaned jobs to auto-recover via Telegram DMs on server restart (`queue.py`).
- **Storage Management**: Monitoring disk usage and performing "Safe Sweeps" on startup (`storage.py`, `queue.py`).

### 3. Downloaders (`downloaders/`)
- **BaseDownloader**: Abstract class consolidating shared execution logic, directory preparation, and error tracking.
- **Job Isolation**: Every download job creates a unique subdirectory `downloads/{job_id}/` to prevent media leakage.
- **Snapchat** (`snapchat.py`): Delegates to the Apify `crawlerbros/snapchat-user-stories-scraper` cloud actor via a single synchronous HTTP POST. The actor runs a fully managed Playwright/Chromium session on Apify's infrastructure, returning a JSON dataset of direct media URLs. Your server never hits Snapchat directly. Inherits from `BaseDownloader`.
- **Gallery-DL** (`gallery_dl.py`): Wrapper around the `gallery-dl` CLI tool. Inherits from `BaseDownloader`.
  - Implements `yt-dlp` fallback for high-reliability fetching.

### 4. Authentication (`auth/`)
- **Cookie Manager**: Handles storage and Netscape-format validation (`cookies.py`).
- **MTProto Client**: Pyrogram wrapper enabling uploads up to 2GB (`mtproto.py`).

## Data Flow

1.  **Input**: User sends a URL.
2.  **Detection & Queue**: Platform is identified, and a job is submitted to the `DownloadQueue`. Job state is atomically injected into the SQLite `.db`.
3.  **Isolation**: The worker creates a unique `downloads/{job_id}` folder.
4.  **Execution**: Appropriate wrapper downloads media into the isolated folder.
5.  **Multi-Stage Retrieval**: If `gallery-dl` fails, the system automatically falls back to `yt-dlp`.
6.  **Server Recovery System**: If the core dies mid-download, the next initialization boot fetches hanging jobs from SQLite and delivers error messages directly into user chats.
7.  **Upload**: `uploader.py` batches files into media groups for delivery.
8.  **Nuclear Cleanup**: The job directory is deleted *immediately* after delivery or failure.
