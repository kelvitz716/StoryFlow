#!/usr/bin/env python3
"""
Generate Telegram Session String for MTProto

This script helps you generate a session string for production deployment.
Run this ONCE locally, then add the output to your .env file.

Usage:
    python scripts/generate_session.py

Requirements:
    - Telegram API ID and Hash from https://my.telegram.org
    - Phone number with Telegram account
    - Access to receive SMS/Telegram code
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    """Generate session string interactively."""
    
    # Import inside async context to avoid Python 3.14 event loop issues
    try:
        from pyrogram import Client
    except ImportError:
        print("❌ Pyrogram not installed. Run: pip install pyrogram")
        sys.exit(1)
    
    print("=" * 60)
    print("  Telegram Session String Generator")
    print("=" * 60)
    print()
    print("This will help you generate a session string for production.")
    print("You'll need:")
    print("  1. API ID and Hash from https://my.telegram.org/apps")
    print("  2. Your phone number")
    print("  3. Access to receive verification code")
    print()
    
    # Get credentials
    api_id = input("Enter API ID: ").strip()
    api_hash = input("Enter API Hash: ").strip()
    phone = input("Enter phone number (with country code, e.g., +1234567890): ").strip()
    
    if not api_id or not api_hash or not phone:
        print("\n❌ All fields are required!")
        return
    
    try:
        api_id = int(api_id)
    except ValueError:
        print("\n❌ API ID must be a number!")
        return
    
    print("\n📱 Connecting to Telegram...")
    
    # Create temporary client
    client = Client(
        "temp_session",
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        in_memory=True
    )
    
    try:
        # Start will trigger interactive auth
        await client.start()
        
        # Export session string
        session_string = await client.export_session_string()
        
        # Get user info
        me = await client.get_me()
        
        print("\n" + "=" * 60)
        print("✅ Authentication Successful!")
        print("=" * 60)
        print(f"\nLogged in as: {me.first_name} {me.last_name or ''} (@{me.username})")
        print(f"Phone: {me.phone_number}")
        print()
        print("🔑 Your Session String:")
        print("-" * 60)
        print(session_string)
        print("-" * 60)
        print()
        print("📝 Next Steps:")
        print("1. Add this to your .env file:")
        print(f"   TELEGRAM_SESSION_STRING={session_string}")
        print()
        print("2. Deploy your bot with the updated .env")
        print()
        print("3. MTProto will connect instantly without asking for codes!")
        print()
        print("⚠️  Keep this string SECRET - it's like a password!")
        print("=" * 60)
        
        await client.stop()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("  - Make sure API ID and Hash are correct")
        print("  - Check your phone number format (+country_code)")
        print("  - Ensure you have access to receive codes")
        try:
            await client.stop()
        except:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
