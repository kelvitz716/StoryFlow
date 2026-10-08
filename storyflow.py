#!/usr/bin/env python3
"""
StoryFlow - Unified Social Media Story Downloader

A Python CLI tool for downloading stories and media from:
- Snapchat (via SnapStory DL API)
- Instagram, TikTok, Twitter/X, Facebook (via gallery-dl)
"""

import os
import sys
import logging
from dotenv import load_dotenv

from core.platform import identify_platform, extract_snapchat_username
from core.queue import _env_int
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader


def _validate_admin_ids(raw: str) -> list[str]:
    """
    Parse and validate ADMIN_USER_ID.  Accepts a comma-separated list of
    numeric Telegram IDs (positive or negative integers).
    Calls sys.exit(1) with a clear message if any entry is non-numeric.
    """
    entries = [e.strip() for e in raw.split(',') if e.strip()]
    for entry in entries:
        if not entry.lstrip('-').isdigit():
            print(
                f"\u274c FATAL: ADMIN_USER_ID contains non-numeric entry: {entry!r}\n"
                "  Expected a comma-separated list of Telegram user IDs (e.g. 123456789 or -1001234567890).",
                file=sys.stderr
            )
            sys.exit(1)
    return entries


def _startup_permissions():
    """
    Apply restrictive file permissions at startup (item 9).
    chmod 600 on .env and cookie files; chmod 700 on data directories.
    All errors are logged as warnings and ignored.
    """
    import glob
    import stat

    def _chmod(path: str, mode: int):
        try:
            os.chmod(path, mode)
        except Exception as exc:
            logging.warning(f"startup permissions: could not chmod {path!r}: {exc}")

    # Restrict .env
    if os.path.exists('.env'):
        _chmod('.env', stat.S_IRUSR | stat.S_IWUSR)  # 600

    # Restrict cookie files
    cookie_path = os.getenv('COOKIE_PATH', './cookies')
    for f in glob.glob(os.path.join(cookie_path, '*.txt')):
        _chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 600

    # Restrict sensitive directories
    for d in [cookie_path, './sessions', './data']:
        if os.path.isdir(d):
            _chmod(d, stat.S_IRWXU)  # 700


def setup_logging():
    """Configure logging for the application with sensitive data filtering."""
    from utils.log_sanitizer import SensitiveDataFilter
    from logging.handlers import RotatingFileHandler
    
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure rotating file handler (10MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        'logs/storyflow.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Configure console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    ))
    
    # Setup root logger with both handlers
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )
    
    # Add sensitive data filter to handlers (this catches library logs too)
    sensitive_filter = SensitiveDataFilter()
    file_handler.addFilter(sensitive_filter)
    console_handler.addFilter(sensitive_filter)


def print_banner():
    """Print welcome banner."""
    print("\n" + "=" * 60)
    print("🎬 StoryFlow Media Downloader")
    print("=" * 60)
    print("Supported platforms:")
    print("  • Snapchat  (stories)")
    print("  • Instagram (posts, reels, stories)")
    print("  • TikTok    (videos)")
    print("  • Twitter/X (media)")
    print("  • Facebook  (videos)")
    print("-" * 60)
    print("Commands: 'quit' or 'exit' to close")
    print("=" * 60 + "\n")


def format_result(result: dict) -> None:
    """Format and print download result."""
    if result.get('success'):
        print("\n✅ Download successful!")
        
        # Snapchat specific output
        if result.get('username'):
            print(f"   👤 Username: @{result['username']}")
        if result.get('total_stories'):
            print(f"   📸 Stories: {result.get('downloaded', 0)}/{result['total_stories']}")
        if result.get('files'):
            print(f"   📁 Files:")
            for f in result['files']:
                print(f"      • {os.path.basename(f)}")
        if result.get('message'):
            print(f"   ℹ️  {result['message']}")
    else:
        print(f"\n❌ Download failed: {result.get('error', 'Unknown error')}")
        if result.get('details'):
            print(f"   Details: {result['details']}")
        
        # Provide helpful hints
        if result.get('error') == 'Authentication required':
            print("\n💡 Tip: For Instagram private content, place your cookies.txt")
            print("   file in the ./cookies directory as 'instagram.txt'")


async def main_cli():
    """Main CLI execution loop."""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    setup_logging()
    
    # Get configuration
    download_path = os.getenv('DOWNLOAD_PATH', './downloads')
    cookie_path = os.getenv('COOKIE_PATH', './cookies')
    
    # Initialize downloaders
    snapchat = SnapchatDownloader(
        output_path=download_path
    )
    
    gallery_dl = GalleryDLDownloader(
        output_path=download_path,
        cookie_path=cookie_path
    )
    
    # Print welcome banner
    print_banner()
    
    while True:
        try:
            # Get user input
            url = input("📎 Enter URL: ").strip()
            
            # Check exit condition
            if url.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            
            if not url:
                continue
            
            # Validate URL format
            if not url.startswith(('http://', 'https://')):
                print("❌ Invalid URL. Please enter a complete URL (https://...)")
                continue
            
            # Identify platform
            platform = identify_platform(url)
            
            # Handle different platforms
            if platform == "Snapchat":
                # Extract username from URL
                username = extract_snapchat_username(url)
                if not username:
                    print("❌ Could not extract username from Snapchat URL")
                    print("   Expected format: snapchat.com/add/username")
                    continue
                
                print(f"\n🔄 Fetching stories for @{username}...")
                result = await snapchat.download(url, user_id="cli", job_id="cli_session")
                
            elif platform in ["Instagram", "TikTok", "Twitter", "Facebook"]:
                print(f"\n🔄 Downloading {platform} content...")
                result = await gallery_dl.download(url, platform, user_id="cli", job_id="cli_session")
                
            elif platform == "Unknown":
                print("\n🚫 Unsupported platform.")
                print("   Supported: Snapchat, Instagram, TikTok, Twitter/X, Facebook")
                continue
                
            elif platform == "Error":
                print("\n❌ Invalid URL format.")
                print("   Please enter a complete URL (e.g., https://...)")
                continue
            else:
                print(f"\n⚠️ Unexpected platform: {platform}")
                continue
            
            # Display result
            format_result(result)
            print()  # Empty line for readability
                
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
            
        except Exception as e:
            logging.error(f"Unexpected error: {e}", exc_info=True)
            print(f"\n⚠️ An error occurred: {e}")
            print("   Please try again.\n")

def main_telegram():
    """Run Telegram bot mode."""
    # Load environment variables
    load_dotenv()

    # Validate ADMIN_USER_ID before anything else (item 9)
    raw_admin = os.getenv('ADMIN_USER_ID', '')
    if not raw_admin:
        print("❌ Error: ADMIN_USER_ID not set in .env file", file=sys.stderr)
        sys.exit(1)
    _validate_admin_ids(raw_admin)

    # Apply restrictive file permissions (item 9)
    _startup_permissions()

    # Setup logging
    setup_logging()

    # Get configuration
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set in .env file")
        print("   Please add your bot token to .env:")
        print("   TELEGRAM_BOT_TOKEN=your_bot_token_here")
        sys.exit(1)

    download_path = os.getenv('DOWNLOAD_PATH', './downloads')
    cookie_path = os.getenv('COOKIE_PATH', './cookies')

    # Import and run bot
    from bot.telegram_bot import run_telegram_bot
    run_telegram_bot(token, download_path, cookie_path)


def main():
    """Main entry point - choose mode based on environment."""
    load_dotenv()
    mode = os.getenv('MODE', 'cli').lower()
    
    if mode == 'telegram':
        main_telegram()
    else:
        import asyncio
        asyncio.run(main_cli())


if __name__ == "__main__":
    main()
