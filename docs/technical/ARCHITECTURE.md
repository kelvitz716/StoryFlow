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
    GalleryDL -->|Fallback| YTDLP[yt-dlp Wrapper]
    
    Worker -->|Success/Files| Uploader[bot/uploader.py]
    Uploader -->|Small Files <50MB| TelegramAPI[Telegram Bot API]
    Uploader -->|Large Files >50MB| MTProto[MTProto Client (Pyrogram)]
```

## Key Components

### 1. Bot Interface (`bot/`)
Modularized for high-performance interaction and maintainability.
- `handlers.py`: Command routing and message processing.
- `menus.py`: UI layout, keyboards, and navigation flow.
- `uploader.py`: Media batching, delivery logic, and MTProto integration.
- `telegram_bot.py`: Main entry point and orchestration.

### 2. Core Logic (`core/`)
- **Platform Identification**: Regex-based detection of social media URLs (`platform.py`).
- **Queue System**: Async worker-based queue. Manages concurrency and prevents API rate limits (`queue.py`).
- **Storage Management**: Monitoring disk usage and performing "Safe Sweeps" on startup (`storage.py`, `queue.py`).

### 3. Downloaders (`downloaders/`)
- **Job Isolation**: Every download job creates a unique subdirectory `downloads/{job_id}/` to prevent media leakage.
- **Snapchat**: Custom API client for fetching Snap stories (`snapchat.py`).
- **Gallery-DL**: Wrapper around the `gallery-dl` CLI tool (`gallery_dl.py`).
  - Implements `yt-dlp` fallback for high-reliability fetching.

### 4. Authentication (`auth/`)
- **Cookie Manager**: Handles storage and Netscape-format validation (`cookies.py`).
- **MTProto Client**: Pyrogram wrapper enabling uploads up to 2GB (`mtproto.py`).

## Data Flow

1.  **Input**: User sends a URL.
2.  **Detection & Queue**: Platform is identified, and a job is submitted to the `DownloadQueue`.
3.  **Isolation**: The worker creates a unique `downloads/{job_id}` folder.
4.  **Execution**: Appropriate wrapper downloads media into the isolated folder.
5.  **Multi-Stage Retrieval**: If `gallery-dl` fails, the system automatically falls back to `yt-dlp`.
6.  **Upload**: `uploader.py` batches files into media groups for delivery.
7.  **Nuclear Cleanup**: The job directory is deleted *immediately* after delivery or failure.
