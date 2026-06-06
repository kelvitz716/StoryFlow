# StoryFlow OCI Deployment Guide

This document describes how to deploy, manage, and upgrade the StoryFlow bot on OCI using the Git-based update workflow.

## Architecture Context

- **Application Files**: `/home/opc/data/storyflow/`
- **Container Name**: `storyflow_app`
- **User**: `opc`
- **Network**: `proxy_net` (external docker bridge)

---

## One-Click Update (from anywhere)

After pushing your local changes to GitHub, run:

```bash
./update_oci.sh
```

This will:
1. SSH into the OCI VM with agent forwarding
2. Run `git fetch && git reset --hard origin/master` to apply latest code
3. Remove the old container and run `docker compose up -d --build`

---

## Environment Configuration on OCI

The `.env` file lives at `/home/opc/data/storyflow/.env` on the VM and is **not tracked by Git** — it must be configured manually once.

SSH into the VM and edit it:

```bash
ssh -i ~/Downloads/ssh-key-2026-05-27.key opc@100.68.227.114
nano /home/opc/data/storyflow/.env
```

Required variables:

```ini
ADMIN_USER_ID=618026357               # Your Telegram user ID (comma-separated for multiple admins)

TELEGRAM_BOT_TOKEN=your_bot_token     # From @BotFather

# MTProto — enables >50MB uploads (up to 2GB)
# Get API_ID and API_HASH from https://my.telegram.org/apps
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE_NUMBER=+1234567890     # Phone number linked to your Telegram account

# (Recommended for production) Pre-generated session string avoids interactive login prompt.
# Generate it once locally: python scripts/generate_session.py
TELEGRAM_SESSION_STRING=

APIFY_TOKEN=your_apify_token          # From https://console.apify.com/settings/integrations
MODE=telegram
```

After editing, restart the container to apply changes:

```bash
cd /home/opc/data/storyflow
docker compose up -d
```

---

## Generating a MTProto Session String

A session string lets the bot authenticate silently without prompting you for a phone code at every start.
Generate it **once** on your **local machine**:

```bash
# Activate your local virtual environment
source venv312/bin/activate

# Run the generator (interactive — will ask for API ID, API Hash, and phone code)
python scripts/generate_session.py
```

Copy the output and paste it into `TELEGRAM_SESSION_STRING=` in the OCI `.env` file, then restart the container.

---

## Operations & Management

### View Application Logs
```bash
ssh -i ~/Downloads/ssh-key-2026-05-27.key opc@100.68.227.114 "docker logs -f storyflow_app"
```

### Restart StoryFlow
```bash
ssh -i ~/Downloads/ssh-key-2026-05-27.key opc@100.68.227.114 "cd /home/opc/data/storyflow && docker compose restart"
```

### Dynamic Extractor Updates
`yt-dlp` and `gallery-dl` are automatically upgraded at every container startup via `entrypoint.sh`.
To pick up the latest extractor code without a full rebuild:
```bash
ssh -i ~/Downloads/ssh-key-2026-05-27.key opc@100.68.227.114 "cd /home/opc/data/storyflow && docker compose restart"
```
