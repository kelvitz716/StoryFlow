# 🎬 StoryFlow

A unified media downloader for social media stories and content.

## Supported Platforms

| Platform | Content Types |
|----------|--------------|
| 👻 Snapchat | Stories |
| 📸 Instagram | Posts, Reels, Stories* |
| 🎵 TikTok | Videos |
| 🐦 Twitter/X | Media |
| 📘 Facebook | Videos |

*\*Instagram Stories require cookie authentication*

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Run

**CLI Mode:**
```bash
python storyflow.py
```

**Telegram Bot Mode:**
```bash
# Add to .env:
TELEGRAM_BOT_TOKEN=your_bot_token
MODE=telegram

python storyflow.py
```

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with buttons |
| `/help` | Usage guide |
| `/upload_cookies` | Upload Instagram cookies |
| `/my_cookies` | View saved cookies |
| `/delete_cookies` | Remove cookies |

## Project Structure

```
StoryFlow/
├── storyflow.py          # Main entry point
├── core/                 # Platform detection, rate limiting
├── downloaders/          # Snapchat API, gallery-dl wrapper
├── auth/                 # Cookie management
├── bot/                  # Telegram bot handlers
└── requirements.txt      # Python dependencies
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MODE` | `cli` or `telegram` | `cli` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | - |
| `DOWNLOAD_PATH` | Temp download directory | `./downloads` |
| `COOKIE_PATH` | Cookie storage | `./cookies` |

## Requirements

- Python 3.10+
- [gallery-dl](https://github.com/mikf/gallery-dl) (system-wide)

## License

MIT
