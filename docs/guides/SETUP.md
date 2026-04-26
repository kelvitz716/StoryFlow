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
    - `APIFY_TOKEN`: Your Apify API token for Snapchat story downloads (see below).

4.  **Start the Bot**:
    ```bash
    python storyflow.py
    ```

## Apify Setup (Snapchat Stories)

Snapchat story downloads are powered by the **Apify** cloud scraping platform (`crawlerbros/snapchat-user-stories-scraper` actor). This eliminates the need to run a headless browser on your server.

1. Create a free account at [apify.com](https://apify.com). The free tier provides **$5 credit/month**, which is sufficient for typical personal bot usage.
2. Go to [console.apify.com/settings/integrations](https://console.apify.com/settings/integrations) and copy your **Personal API token**.
3. Add it to your `.env`:
   ```env
   APIFY_TOKEN=apify_api_xxxxxxxxxxxxxxxxxxxx
   ```

> [!TIP]
> Pricing is pay-per-use at **$1.00 / 1,000 results**. The free monthly credit translates to ~5,000 story downloads before any charges apply.

## MTProto Setup (Large Files)

To support files > 50MB, you must provide `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. On the first startup, the bot will ask for an OTP code in the terminal to authorize the session.

> [!TIP]
> **2FA**: If you have 2FA enabled, you will also need to enter your Cloud Password in the terminal or via the bot's admin menu.
