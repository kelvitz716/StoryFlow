# StoryFlow — Termux Deployment Guide

This guide covers running StoryFlow on an Android phone in **Termux**, alongside
Jellyfin, Sonarr, Radarr, qBittorrent, and other services reachable over
Tailscale (100.64.0.0/10).

---

## Prerequisites

- Termux installed from **F-Droid** (Play Store builds are outdated and will fail)
- Tailscale running on the device
- A Telegram bot token from [@BotFather](https://t.me/botfather)
- Your Telegram numeric user ID (ask [@userinfobot](https://t.me/userinfobot))

---

## 1 — First Install

```sh
# 1. Clone the repo
pkg install -y git
git clone https://github.com/kelvitz716/StoryFlow.git ~/StoryFlow
cd ~/StoryFlow

# 2. Run the setup script (takes ~5 minutes on first run)
chmod +x termux/setup.sh
./termux/setup.sh
```

The setup script:
- Installs: `python clang make libffi openssl-tool ffmpeg`
- Creates a Python virtual environment at `~/StoryFlow/venv`
- Installs all Python requirements (TgCrypto is optional — build failure is OK)
- Copies the runit service files to `~/.config/sv/storyflow/`

---

## 2 — Configure `.env`

```sh
cp ~/StoryFlow/.env.example ~/StoryFlow/.env
nano ~/StoryFlow/.env
```

Minimum required fields:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_USER_ID=your_numeric_telegram_id
```

> **Security note**: the startup script automatically runs `chmod 600 .env`
> on every launch, but set it now just in case:
> ```sh
> chmod 600 ~/StoryFlow/.env
> ```

---

## 3 — Enable and Start the Service

Termux uses **runit** for background services via the `termux-services` package.

```sh
# Install termux-services if not already installed
pkg install -y termux-services

# Enable StoryFlow to start automatically on boot
sv-enable storyflow

# Start it now (no reboot needed)
sv start storyflow
```

---

## 4 — Check Status and Logs

```sh
# Service status (shows "run:" or "down:")
sv status storyflow

# Live log stream
tail -f ~/logs/storyflow/current

# Last 50 log lines
svlogd -t < ~/logs/storyflow/current | tail -50
```

---

## 5 — Stop / Restart

```sh
sv stop storyflow      # graceful stop
sv restart storyflow   # stop + start
sv-disable storyflow   # remove from auto-start
```

---

## 6 — Update Extractors

Run this whenever gallery-dl or yt-dlp starts failing on a particular site
(usually because the site changed its layout):

```sh
~/StoryFlow/termux/update-extractors.sh
```

This upgrades both tools and restarts the service automatically.

---

## 7 — Update StoryFlow

```sh
cd ~/StoryFlow
sv stop storyflow
git pull
~/StoryFlow/venv/bin/pip install -r requirements.txt
sv start storyflow
```

---

## 8 — Battery Optimisation

Android aggressively kills background processes to save battery. Prevent this:

### Wake Lock (keeps CPU awake while Termux is running)

```sh
# Acquire a wake lock — run once per session or put in ~/.bashrc
termux-wake-lock
```

> **Tip**: add `termux-wake-lock` to `~/.bashrc` so it runs automatically
> every time you open Termux.

### Disable Battery Optimisation for Termux

1. **Settings → Apps → Termux → Battery → Unrestricted** (exact path varies by
   Android version and manufacturer)
2. Some ROMs (e.g. MIUI, OneUI) also have a separate "Background app management"
   or "Auto-close apps" setting — disable it for Termux there too.

### Tailscale

Ensure Tailscale is also excluded from battery optimisation so the VPN
connection stays up.

---

## 9 — Coexisting with Jellyfin / Sonarr / Radarr / qBittorrent

All those services bind to `127.0.0.1` or `0.0.0.0` on their respective ports.
StoryFlow's SSRF filter (`is_safe_url`) **blocks** `127.0.0.1`, `192.168.x.x`,
and the Tailscale CGNAT range (`100.64.0.0/10`) — so a maliciously crafted link
cannot reach those services through StoryFlow.

No firewall rules are required; the filter is applied before any outbound
request is made.

---

## 10 — Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Service shows `down:` immediately | Missing `.env` or bad `ADMIN_USER_ID` | Check `~/logs/storyflow/current` |
| `ModuleNotFoundError` on start | venv not activated in run script | Verify `termux/service/run` points to `venv/bin/python` |
| Bot doesn't respond | Phone asleep / no wake-lock | Run `termux-wake-lock` and check battery settings |
| Download fails with "unsupported" | Outdated extractor | Run `update-extractors.sh` |
| Large file not delivered | TgCrypto missing (MTProto unavailable) | Bot will log a warning; files ≤50 MB still work |

---

## File Layout

```
termux/
  setup.sh               ← first-install script
  update-extractors.sh   ← upgrade yt-dlp + gallery-dl
  service/
    run                  ← runit service script
    log/
      run                ← runit logger script
  README.md              ← this file
```
