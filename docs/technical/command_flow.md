# StoryFlow Bot Command & Interaction Guide

This document maps the interactive flows of the StoryFlow Telegram bot. All future updates to commands or menus must maintain these fluid transitions to ensure a high-quality user experience.

## 🌟 Core Philosophy
- **Fluid Navigation**: Every menu should have a way to go back or return to the main menu.
- **Visual Feedback**: Use emojis and clear status messages to indicate state (Processing, Downloading, Uploading).
- **Automated Stability**: Prioritize automated cleanup and isolation over manual maintenance.

## 🎮 Command Structure

| Command | Description | Flow |
|---------|-------------|------|
| `/start` | Initializes the bot interaction | -> **Main Menu** |
| `/help` | Shows usage guide | -> **Help Menu** |
| `/my_cookies` | Manages authentication cookies | -> **Cookie Menu** |
| `/purge` | (Admin) Manual sweep trigger | -> **System Message** (Automated) |
| `/adduser` | (Admin) Authorize a new user | -> **Direct Action** |

## 🔀 Interaction Flows

### 1. Main Menu Flow (`/start`)
The central hub of the application.
```mermaid
graph TD
    Start[/start] --> MainMenu
    MainMenu[Main Menu]
    
    MainMenu -->|Tap 'How to Use'| HelpMenu
    MainMenu -->|Tap 'Manage Cookies'| CookieMenu
    MainMenu -->|Tap 'My Stats'| StatsView
    
    HelpMenu -->|Tap 'Back'| MainMenu
    CookieMenu -->|Tap 'Main Menu'| MainMenu
    StatsView -->|Tap 'Back'| MainMenu
```

### 2. Download Flow (URL Input)
Automatic handling of media links with architectural isolation.
```mermaid
graph TD
    UserLink[User sends URL] --> Analyze{Identify Platform}
    
    Analyze -->|Unknown| ErrorMsg[Show Error & Supported Platforms]
    Analyze -->|Supported| Processing[Status: 'Analyzing...']
    
    Processing --> Queue{Download Queue}
    
    Queue -->|Wait| StatusQueued[Status: 'Queued (Pos X)...']
    Queue -->|Start| Isolation[Action: Create downloads/job_id/]
    
    Isolation --> StatusDown[Status: 'Downloading...']
    
    StatusDown -->|Success| Uploading[Action: bot/uploader.py]
    StatusDown -->|Fail| FinalCleanup[Action: Delete job_id/]
    
    Uploading -->|Rate Limit / FloodWait| MTProto[Failover to MTProto User API]
    Uploading -->|Complete| FinalCleanup
    MTProto -->|Complete| FinalCleanup
    FinalCleanup --> FinalMsg[✅ Delivery Complete]
```

### 3. Maintenance & Reliability
StoryFlow implements several automated reliability flows for 24/7 cloud deployment.

#### A. Startup "Safe Sweep"
Every time the bot starts (e.g., after a Git pull and container restart), it performs a nuclear sweep of the `downloads/` directory to clear any leftover debris from previous sessions.

#### B. Periodic Scrubbing
A background task runs every 60 minutes to remove orphan directories (folders older than 2 hours that aren't linked to an active job).

## ⚠️ Maintenance Guidelines
1. **Never break the chain**: Ensure every new menu has a "Back" button pointing to its logical parent.
2. **Consistent Style**: Use established emojis for platforms (👻, 📸, 🎵, 🐦, 📘).
3. **Async Everywhere**: All UI interactions must remain non-blocking to ensure the bot responds during heavy downloads.
