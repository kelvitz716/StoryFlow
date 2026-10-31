# Setup Guide

## Prerequisites

- **Python 3.11/3.12** is recommended.
- **FFmpeg** (required for media merging/converting).
- **Git**.
- **Docker** (Recommended for deployment).

## Deployment (Recommended: Docker + deploy.sh)

For 24/7 cloud operation (like AWS), using Docker is the most reliable way to ensure stability and isolate dependencies.

1.  **Clone the repository**:
    ```bash
    git clone <repository_url>
    cd StoryFlow
    ```

2.  **Run the deployment script**:
    ```bash
    chmod +x deploy.sh
    ./deploy.sh
    ```
    This script will:
    - Interactive prompt you for configuration.
    - Create the `.env` file automatically.
    - Set up the necessary data volumes with correct permissions.
    - Build and start the StoryFlow Docker container.

3.  **Monitor Logs**:
    ```bash
    docker logs -f storyflow_app
    ```

## Manual Installation (Optional)

If you prefer to run directly on your host:

1.  **Install FFmpeg**:
    ```bash
    # Ubuntu/Debian
    sudo apt install ffmpeg
    ```

2.  **Set up Python Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configure `.env`**:
    Manually create `.env` from `.env.example` and fill in:
    - `TELEGRAM_BOT_TOKEN`: From @BotFather.
    - `ADMIN_USER_ID`: Your Telegram ID (to authorize commands).
    - `MODE=telegram`: To run the bot.
    - `EXTRACTOR_AUTO_UPDATE=false`: Optional, set to false to prevent auto-upgrading yt-dlp and gallery-dl on startup.
    Restrict file permissions on the host: `chmod 600 .env`.

4.  **Start the Bot**:
    ```bash
    python storyflow.py
    ```

## MTProto Setup (Large Files)

To support files > 50MB, you must provide `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. On the first startup, the bot will ask for an OTP code in the terminal to authorize the session.

> [!TIP]
> **2FA**: If you have 2FA enabled, you will also need to enter your Cloud Password in the terminal or via the bot's admin menu.

## Channel & Anonymous Cookie Mapping (`COOKIE_OWNER_MAP`)

When downloads are requested by Telegram channels or anonymous admin posts (which have negative numeric IDs such as `-1001234567890`), StoryFlow requires an explicit mapping to associate the channel with an owner's cookie file.

Add `COOKIE_OWNER_MAP` to `.env`:
```env
COOKIE_OWNER_MAP=-1001234567890:123456789,-1009876543210:123456789
```

- **Format**: `identity:owner,identity:owner` (comma-separated pairs of digits with an optional leading `-`).
- **Behavior**: The channel job attempts to use the mapped owner's cookie file (e.g. `instagram_123456789.txt`).
- **Priority**: A user's own cookie file always takes priority if present.
- **Isolation**: Unmapped channel identities never fall through to other users' cookies.

### In-Bot Management (No `.env` editing needed!)
You can also map channels or toggle fallback directly in Telegram:
- **1-Tap Button**: When a download in a channel fails with "Authentication required", the bot replies with an interactive `[🍪 Link My Cookies to This Channel]` button. Tap it once to link your cookies to the channel.
- **Command `/mapchannel`**: Send `/mapchannel` directly inside any channel or group to link it to your account.
- **Admin Menu**: Go to `/admin` ➔ **Channel Cookies** to toggle Global Admin Fallback or view/unlink mapped channels.

## Admin Cookie Fallback (`ALLOW_ADMIN_COOKIE_FALLBACK`)

By default StoryFlow never uses the admin's cookie files as a fallback for other users. Set this only when you intentionally want the admin's saved cookies to act as a fallback for users who have no cookies of their own:

```env
ALLOW_ADMIN_COOKIE_FALLBACK=true
```

> [!CAUTION]
> Enabling this shares the admin's authenticated session with any user who triggers a download. Leave it `false` (the default) in multi-user deployments.

## Download Limits

These env vars cap how much each download job can consume. All are optional — the defaults are generous enough for typical use:

| Variable | Default | Range | Description |
|---|---|---|---|
| `MAX_FILE_SIZE_MB` | `500` | 1 – 10 000 | Maximum size of a single file accepted from gallery-dl / yt-dlp (MB). |
| `MAX_JOB_SIZE_MB` | `2048` | 10 – 100 000 | Cumulative download size allowed per job before the subprocess is killed (MB). |
| `MAX_FILES_PER_JOB` | `500` | 1 – 10 000 | Maximum number of files downloaded in a single job. |
| `DOWNLOAD_TIMEOUT_SECONDS` | `600` | 10 – 86 400 | Wall-clock timeout for a single download subprocess (seconds). |

Example `.env` snippet:
```env
MAX_FILE_SIZE_MB=500
MAX_JOB_SIZE_MB=2048
MAX_FILES_PER_JOB=500
DOWNLOAD_TIMEOUT_SECONDS=600
```

## Per-User Download Quality

Users can set their preferred video quality via the bot's **Settings → Quality** menu (or the inline keyboard shown after sending a URL). The available options are:

| Key | Description |
|---|---|
| `best` | Best available video + audio (default) |
| `1080p` | Up to 1080p |
| `720p` | Up to 720p |
| `480p` | Up to 480p |
| `audio` | Audio-only (MP3 extraction via yt-dlp) |

Preferences are stored per-user in the local SQLite database and apply to all yt-dlp-backed downloads. There is no global env var for quality — each user picks their own via the in-bot menu.

