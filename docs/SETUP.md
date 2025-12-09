# Setup Guide

## Prerequisites

- **Python 3.12** is recommended.
- **FFmpeg** (required for media merging/converting).
- **Git**.

## System Dependencies

1.  **Install FFmpeg**:
    ```bash
    # Fedora
    sudo dnf install ffmpeg
    
    # Ubuntu/Debian
    sudo apt install ffmpeg
    ```

2.  **Install gallery-dl** (System-wide recommended):
    ```bash
    sudo pip install -U gallery-dl
    ```

3.  **Install yt-dlp** (System-wide recommended):
    ```bash
    sudo pip install -U yt-dlp
    ```

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository_url>
    cd StoryFlow
    ```

2.  **Set up Python Environment**:
    ```bash
    # Create virtual environment
    python3.12 -m venv venv312
    
    # Activate it
    source venv312/bin/activate
    ```

3.  **Install Python Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  **Environment Variables**:
    Copy the example configuration:
    ```bash
    cp .env.example .env
    ```

2.  **Edit `.env`**:
    Open `.env` and fill in your credentials:
    
    ```ini
    # Telegram Bot Token (from @BotFather)
    TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    
    # Run Mode
    MODE=telegram
    
    # [Optional] MTProto Setup for files > 50MB
    # Get these from https://my.telegram.org -> API Development Tools
    TELEGRAM_API_ID=12345678
    TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
    ```

## Running the Bot

1.  **Activate Environment** (if not already active):
    ```bash
    source venv312/bin/activate
    ```

2.  **Start the Bot**:
    ```bash
    python storyflow.py
    ```

3.  **First Run (MTProto)**:
    If you configured `TELEGRAM_API_ID`, the bot will ask for your phone number and OTP code on the first run to authorize the session. This session is saved locally in `sessions/`.

## Running as Systemd Service (Optional)

Create a service file `/etc/systemd/system/storyflow.service`:

```ini
[Unit]
Description=StoryFlow Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/StoryFlow
ExecStart=/path/to/StoryFlow/venv312/bin/python storyflow.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
