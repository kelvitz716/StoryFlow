# Architecture Overview

StoryFlow is a modular Telegram bot and CLI application designed for downloading media from various social media platforms. It leverages a combination of custom API wrappers and external tools (`gallery-dl`, `yt-dlp`) to handle content retrieval.

## System Diagram

```mermaid
graph TD
    User[User] -->|Commands/URLs| Bot[Telegram Bot]
    Bot -->|Identify Platform| Core[Core Logic]
    
    Core -->|Snapchat| SnapDL[Snapchat Downloader]
    Core -->|Insta/TikTok/FB| GalleryDL[Gallery-DL Wrapper]
    GalleryDL -->|Fallback| YTDLP[yt-dlp Wrapper]
    
    Bot -->|Store Credentials| Auth[Auth Manager]
    Auth -->|Cookies| CookieStore[Cookie Storage]
    
    Bot -->|Small Files <50MB| TelegramAPI[Telegram Bot API]
    Bot -->|Large Files >50MB| MTProto[MTProto Client (Pyrogram)]
```

## Key Components

### 1. Bot Interface (`bot/`)
- Handles Telegram updates (messages, commands, callbacks).
- Manages user interaction flow (menus, buttons).
- **Files**: `telegram_bot.py`

### 2. Core Logic (`core/`)
- **Platform Identification**: Regex-based detection of social media URLs (`platform.py`).
- **Queue System**: Async job queue for managing concurrent downloads (currently optional/disabled) (`queue.py`).
- **Rate Limiting**: Token bucket algorithm to prevent API spam (`rate_limiter.py`).

### 3. Downloaders (`downloaders/`)
- **Snapchat**: Custom API client for fetching Snap stories (`snapchat.py`).
- **Gallery-DL**: Wrapper around the `gallery-dl` CLI tool (`gallery_dl.py`).
  - Handles process execution.
  - Manages output directories.
  - Implements `yt-dlp` fallback for Facebook/TikTok.

### 4. Authentication (`auth/`)
- **Cookie Manager**: Handles storage and validation of Netscape-format cookies (`cookies.py`).
- **MTProto Client**: Pyrogram wrapper for interacting with Telegram's MTProto API, enabling large file uploads up to 2GB (`mtproto.py`).

## Data Flow

1.  **Input**: User sends a URL to the bot.
2.  **Detection**: `identify_platform()` determines the source (Instagram, Snapchat, etc.).
3.  **Routing**:
    - Snapchat URLs -> `SnapchatDownloader`.
    - Other URLs -> `GalleryDLDownloader`.
4.  **Execution**:
    - `GalleryDLDownloader` attempts download via `gallery-dl`.
    - If failed (e.g., Facebook), retries with `yt-dlp`.
5.  **Processing**: Media files are saved to a temporary `downloads/` directory.
6.  **Upload**:
    - Files < 50MB: Uploaded via standard Bot API.
    - Files > 50MB: Uploaded via MTProto (if configured).
7.  **Cleanup**: Files are immediately deleted after successful delivery to save disk space.
