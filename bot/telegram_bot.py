"""Telegram bot for StoryFlow media downloader."""

import os
import logging
import asyncio
from typing import Optional

from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from core.platform import identify_platform, extract_snapchat_username
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader
from auth.cookies import CookieManager


import random

# Initialize components
snapchat: Optional[SnapchatDownloader] = None
gallery_dl: Optional[GalleryDLDownloader] = None
cookie_manager: Optional[CookieManager] = None

# Fun greeting messages
GREETINGS = [
    "Hey there! 👋",
    "What's up! 🎉",
    "Hello, friend! ✨",
    "Yo! Ready to grab some stories? 🚀",
]

# Fun processing messages
PROCESSING_MSGS = [
    "Hang tight! I'm on it 🔥",
    "Let me work my magic ✨",
    "Fetching that content for you 🚀",
    "One sec, grabbing the goods 📦",
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with inline keyboard."""
    # Create inline keyboard buttons
    keyboard = [
        [InlineKeyboardButton("❓ Help & Usage", callback_data="help")],
        [InlineKeyboardButton("🍪 Upload Cookies", callback_data="upload_cookies")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌟 *Welcome to StoryFlow!*\n\n"
        "Your personal media grabber is ready. 📦\n\n"
        "Just send me a link from:\n"
        "👻 Snapchat • 📸 Instagram • 🎵 TikTok\n"
        "🐦 Twitter/X • 📘 Facebook",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message (for /help command)."""
    await send_help_message(update.message)


async def send_help_message(message_or_query):
    """Send help message content."""
    help_text = (
        "📖 *StoryFlow Guide*\n\n"
        "━━━━━━━━━━━━━━\n"
        "👻 *Snapchat*\n"
        "Send a profile link like:\n"
        "`snapchat.com/add/username`\n\n"
        "━━━━━━━━━━━━━━\n"
        "📸 *Instagram*\n"
        "• Public posts/reels: Just send the link\n"
        "• Private content: Upload cookies first\n\n"
        "━━━━━━━━━━━━━━\n"
        "🎵 *TikTok, Twitter, Facebook*\n"
        "Just send the video URL!\n\n"
        "━━━━━━━━━━━━━━\n"
        "💡 *Tip:* Public content = no cookies needed"
    )
    
    if hasattr(message_or_query, 'reply_text'):
        await message_or_query.reply_text(help_text, parse_mode='Markdown')
    else:
        await message_or_query.edit_message_text(help_text, parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    
    if query.data == "help":
        await send_help_message(query)
        
    elif query.data == "upload_cookies":
        context.user_data['awaiting_cookies'] = True
        await query.edit_message_text(
            "🍪 *Cookie Time!*\n\n"
            "Send me your Instagram cookies.txt file and I'll remember it for you.\n\n"
            "🔐 *Your cookies are private:*\n"
            "• Only you can use them\n"
            "• Delete anytime with /delete\\_cookies\n\n"
            "_Waiting for your file..._",
            parse_mode='Markdown'
        )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle URL message."""
    url = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    # Identify platform
    platform = identify_platform(url)
    
    if platform == "Error":
        await update.message.reply_text("🤔 Hmm, that doesn't look like a valid URL. Try again?")
        return
    
    if platform == "Unknown":
        await update.message.reply_text(
            "🤷 I don't recognize that platform!\n\n"
            "I work with:\n"
            "👻 Snapchat • 📸 Instagram • 🎵 TikTok\n"
            "🐦 Twitter/X • 📘 Facebook"
        )
        return
    
    # Send processing message with fun text
    proc_msg = random.choice(PROCESSING_MSGS)
    status_msg = await update.message.reply_text(f"{proc_msg}")
    
    try:
        # Download based on platform
        if platform == "Snapchat":
            username = extract_snapchat_username(url)
            if not username:
                await status_msg.edit_text(
                    "🤔 Couldn't find a username in that link.\n"
                    "Try: snapchat.com/add/username"
                )
                return
            
            await status_msg.edit_text(f"⬇️ *Downloading Stories...*\nFetching from @{username}", parse_mode='Markdown')
            result = snapchat.download_stories(username)
            
        else:
            # Instagram, TikTok, Twitter, Facebook
            platform_emoji = {"Instagram": "📸", "TikTok": "🎵", "Twitter": "🐦", "Facebook": "📘"}
            emoji = platform_emoji.get(platform, "📥")
            await status_msg.edit_text(f"⬇️ *Downloading...*\n{emoji} Grabbing {platform} content", parse_mode='Markdown')
            result = gallery_dl.download(url, platform, user_id)
        
        # Handle result
        if result.get('success'):
            files = result.get('files', [])
            
            if not files:
                # No files but success (e.g., no active stories)
                message = result.get('message', 'No content found')
                await status_msg.edit_text(f"😕 {message}")
                return
            
            total_files = len(files)
            
            # Show download complete message before uploading
            await status_msg.edit_text(
                f"✅ *Downloaded {total_files} items!*\n"
                f"Now sending to you...",
                parse_mode='Markdown'
            )
            
            # Batch upload files (Telegram limit: 10 per media group, 50MB per file)
            await batch_upload_media(update, files, status_msg)
            
        else:
            error_msg = result.get('error', 'Unknown error')
            
            if error_msg == 'Authentication required':
                await status_msg.edit_text(
                    "🔒 *Authentication required for Instagram*\n\n"
                    "Please use /upload\\_cookies to upload your cookies.txt file.\n\n"
                    "*How to get cookies:*\n"
                    "1. Install 'Get cookies.txt' browser extension\n"
                    "2. Visit Instagram and login\n"
                    "3. Export cookies as cookies.txt\n"
                    "4. Send the file here after /upload\\_cookies",
                    parse_mode='Markdown'
                )
            else:
                await status_msg.edit_text(f"❌ Failed: {error_msg}")
                
    except Exception as e:
        logging.error(f"Error processing URL: {e}")
        await status_msg.edit_text(f"⚠️ Error: {str(e)}")


async def batch_upload_media(update: Update, files: list, status_msg) -> None:
    """
    Upload media files in batches using Telegram media groups.
    
    Telegram limits:
    - Max 10 files per media group
    - Max 50MB per file for bots
    - Max 10MB for photos
    """
    from telegram import InputMediaPhoto, InputMediaVideo
    from telegram.error import RetryAfter
    
    total_files = len(files)
    batch_size = 10  # Telegram max for media groups
    batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
    
    uploaded_count = 0
    failed_count = 0
    
    for batch_idx, batch in enumerate(batches):
        batch_start = batch_idx * batch_size + 1
        batch_end = min((batch_idx + 1) * batch_size, total_files)
        
        # Update status with fun message
        await status_msg.edit_text(
            f"🚀 Sending your stories to space... batch {batch_idx + 1}/{len(batches)}\n"
            f"(files {batch_start}-{batch_end} of {total_files})"
        )
        
        # Prepare media group
        media_group = []
        valid_files = []
        files_to_send_individually = []  # Files that can't be in media group
        
        # Supported extensions for media groups
        photo_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
        video_exts = ('.mp4', '.mov', '.webm', '.avi', '.mkv', '.m4v')
        
        for idx, filepath in enumerate(batch):
            try:
                file_size = os.path.getsize(filepath)
                file_ext = os.path.splitext(filepath)[1].lower()
                
                # 50MB limit for bot API
                if file_size > 50 * 1024 * 1024:
                    logging.warning(f"File too large (>50MB): {filepath}")
                    failed_count += 1
                    continue
                
                if file_ext in photo_exts:
                    # Photos have 10MB limit in media groups
                    if file_size > 10 * 1024 * 1024:
                        # Send as document instead
                        files_to_send_individually.append(('photo', filepath))
                    else:
                        media_group.append(InputMediaPhoto(media=open(filepath, 'rb')))
                        valid_files.append(filepath)
                        
                elif file_ext in video_exts:
                    media_group.append(InputMediaVideo(media=open(filepath, 'rb')))
                    valid_files.append(filepath)
                    
                else:
                    # Send unknown file types as documents individually
                    files_to_send_individually.append(('document', filepath))
                    
            except Exception as e:
                logging.error(f"Error preparing file {filepath}: {e}")
                failed_count += 1
                continue
        
        if not media_group and not files_to_send_individually:
            continue
        
        # Add caption to first item in batch (if we have a media group)
        if media_group:
            start_num = batch_start
            end_num = start_num + len(valid_files) - 1
            caption = f"📸 Stories {start_num}-{end_num} of {total_files}"
            media_group[0] = type(media_group[0])(
                media=media_group[0].media,
                caption=caption
            )
        
        # Send media group with retry logic for flood control
        if media_group:
            max_retries = 3
            for retry in range(max_retries):
                try:
                    await update.message.reply_media_group(media=media_group)
                    uploaded_count += len(valid_files)
                    
                    # Cleanup: Delete files after successful upload
                    for filepath in valid_files:
                        try:
                            os.remove(filepath)
                            logging.debug(f"Cleaned up: {filepath}")
                        except Exception as e:
                            logging.warning(f"Failed to cleanup {filepath}: {e}")
                    
                    await asyncio.sleep(1)  # Rate limit
                    break
                    
                except RetryAfter as e:
                    wait_time = e.retry_after
                    logging.warning(f"Flood control: waiting {wait_time}s")
                    await status_msg.edit_text(
                        f"⏳ Telegram says slow down! Waiting {wait_time}s...\n"
                        f"Batch {batch_idx + 1}/{len(batches)}"
                    )
                    await asyncio.sleep(wait_time + 1)
                    
                except Exception as e:
                    if 'flood' in str(e).lower() or 'retry' in str(e).lower():
                        wait_time = 30
                        logging.warning(f"Possible flood control: waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logging.error(f"Error sending media group: {e}")
                        failed_count += len(valid_files)
                        break
        
        # Send files that couldn't be in the media group individually
        for file_type, filepath in files_to_send_individually:
            try:
                with open(filepath, 'rb') as f:
                    if file_type == 'photo':
                        await update.message.reply_document(f, caption=f"📷 {os.path.basename(filepath)}")
                    else:
                        await update.message.reply_document(f, caption=f"📁 {os.path.basename(filepath)}")
                    uploaded_count += 1
                    
                    # Cleanup: Delete file after successful upload
                    try:
                        os.remove(filepath)
                        logging.debug(f"Cleaned up: {filepath}")
                    except Exception as e:
                        logging.warning(f"Failed to cleanup {filepath}: {e}")
                    
                    await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                logging.error(f"Error sending individual file {filepath}: {e}")
                failed_count += 1
        
        # Delay between batches to avoid flood control
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(1)
    
    # Delete status message and send completion message
    try:
        await status_msg.delete()
    except:
        pass
    
    # Send completion messages matching reference design
    if failed_count == 0:
        # Delivery complete message
        await update.message.reply_text(
            f"✅ *Delivery Complete!*\n\n"
            f"All {total_files} stories are here.",
            parse_mode='Markdown'
        )
        
        # Friendly closing message
        await update.message.reply_text(
            "Enjoy! ✨ Send another link whenever you're ready."
        )
    else:
        await update.message.reply_text(
            f"✅ *Delivery Complete!*\n\n"
            f"Got {uploaded_count} of {total_files} files.\n"
            f"⚠️ {failed_count} skipped (too large >50MB)",
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "Enjoy! ✨ Send another link whenever you're ready."
        )


async def upload_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cookie file upload command."""
    context.user_data['awaiting_cookies'] = True
    await update.message.reply_text(
        "🍪 *Cookie Time!*\n\n"
        "Send me your Instagram cookies.txt file and I'll remember it for you.\n\n"
        "🔐 *Don't worry:*\n"
        "• Your cookies are yours alone\n"
        "• Nobody else can use them\n"
        "• Delete anytime with /delete\\_cookies\n\n"
        "_Waiting for your file..._",
        parse_mode='Markdown'
    )


async def list_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List user's saved cookies."""
    user_id = str(update.effective_user.id)
    cookies = cookie_manager.list_cookies(user_id)
    
    if not cookies:
        await update.message.reply_text(
            "🍪 No cookies saved yet!\n\n"
            "Use /upload\\_cookies to get started with Instagram.",
            parse_mode='Markdown'
        )
    else:
        platforms = [c['platform'].title() for c in cookies]
        await update.message.reply_text(
            f"🍪 *Your cookie jar:*\n\n"
            f"✅ {', '.join(platforms)}\n\n"
            f"You're all set for private content! 🎉",
            parse_mode='Markdown'
        )


async def delete_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete user's cookies."""
    user_id = str(update.effective_user.id)
    
    deleted = cookie_manager.delete_cookie_file(user_id, "instagram")
    
    if deleted:
        await update.message.reply_text("🗑️ Cookies gone! Your data is cleared.")
    else:
        await update.message.reply_text("🤷 No cookies to delete — you're already clean!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document (cookie file) upload."""
    document: Document = update.message.document
    user_id = str(update.effective_user.id)
    
    # Check if user was expecting to upload cookies
    if not context.user_data.get('awaiting_cookies'):
        await update.message.reply_text(
            "📎 Got a file, but I wasn't expecting one.\n"
            "Use /upload\\_cookies first if you want to upload cookies.",
            parse_mode='Markdown'
        )
        return
    
    # Reset flag
    context.user_data['awaiting_cookies'] = False
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file (cookies.txt)")
        return
    
    # Download file
    status_msg = await update.message.reply_text("⏳ Processing cookies...")
    
    try:
        file = await document.get_file()
        temp_path = f"/tmp/cookies_{user_id}.txt"
        await file.download_to_drive(temp_path)
        
        # Save cookie file
        result = cookie_manager.save_cookie_file(user_id, "instagram", temp_path)
        
        if result['success']:
            await status_msg.edit_text(
                "✅ *Cookies saved successfully!*\n\n"
                "You can now download private Instagram content.\n"
                "Just send me an Instagram URL.",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ Failed to save cookies: {result.get('error')}\n\n"
                "Make sure you exported cookies in Netscape format."
            )
        
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    except Exception as e:
        logging.error(f"Error processing cookie upload: {e}")
        await status_msg.edit_text(f"⚠️ Error: {str(e)}")


def run_telegram_bot(token: str, download_path: str, cookie_path: str, api_base_url: str) -> None:
    """Run the Telegram bot."""
    global snapchat, gallery_dl, cookie_manager
    
    # Initialize components
    snapchat = SnapchatDownloader(
        api_base_url=api_base_url,
        output_path=download_path
    )
    
    gallery_dl = GalleryDLDownloader(
        output_path=download_path,
        cookie_path=cookie_path
    )
    
    cookie_manager = CookieManager(cookie_path=cookie_path)
    
    # Create application
    app = Application.builder().token(token).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("upload_cookies", upload_cookies))
    app.add_handler(CommandHandler("my_cookies", list_cookies))
    app.add_handler(CommandHandler("delete_cookies", delete_cookies))
    
    # Callback handler for inline keyboard buttons
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # URL handler (text messages that look like URLs)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^https?://'),
        handle_url
    ))
    
    # Document handler for cookie uploads
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Run bot
    logging.info("🤖 StoryFlow Telegram Bot starting...")
    print("🤖 StoryFlow Telegram Bot started!")
    print("Press Ctrl+C to stop")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)
