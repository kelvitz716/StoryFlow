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
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


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


def main_cli():
    """Main CLI execution loop."""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    setup_logging()
    
    # Get configuration
    api_base_url = os.getenv('SNAPCHAT_API_BASE_URL', 'https://snapstories.netlify.app')
    download_path = os.getenv('DOWNLOAD_PATH', './downloads')
    cookie_path = os.getenv('COOKIE_PATH', './cookies')
    
    # Initialize downloaders
    snapchat = SnapchatDownloader(
        api_base_url=api_base_url,
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
                result = snapchat.download_stories(username)
                
            elif platform in ["Instagram", "TikTok", "Twitter", "Facebook"]:
                print(f"\n🔄 Downloading {platform} content...")
                result = gallery_dl.download(url, platform)
                
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
    
    # Setup logging
    setup_logging()
    
    # Get configuration
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set in .env file")
        print("   Please add your bot token to .env:")
        print("   TELEGRAM_BOT_TOKEN=your_bot_token_here")
        sys.exit(1)
    
    api_base_url = os.getenv('SNAPCHAT_API_BASE_URL', 'https://snapstories.netlify.app')
    download_path = os.getenv('DOWNLOAD_PATH', './downloads')
    cookie_path = os.getenv('COOKIE_PATH', './cookies')
    
    # Import and run bot
    from bot.telegram_bot import run_telegram_bot
    run_telegram_bot(token, download_path, cookie_path, api_base_url)


def main():
    """Main entry point - choose mode based on environment."""
    load_dotenv()
    mode = os.getenv('MODE', 'cli').lower()
    
    if mode == 'telegram':
        main_telegram()
    else:
        main_cli()


if __name__ == "__main__":
    main()
