"""Telegram bot for StoryFlow media downloader."""

import os
import logging
import asyncio
import time
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
from core.queue import DownloadQueue, JobStatus, init_queue, get_queue
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader
from auth.cookies import CookieManager
from core.stats import stats_manager

# MTProto import (optional - for large files >50MB)
try:
    from auth.mtproto import MTProtoClient, get_mtproto_client, init_mtproto
    MTPROTO_AVAILABLE = True
except Exception as e:
    logging.warning(f"MTProto not available: {e}")
    MTProtoClient = None
    get_mtproto_client = lambda: None
    init_mtproto = None
    MTPROTO_AVAILABLE = False


import random

# Initialize components
snapchat: Optional[SnapchatDownloader] = None
gallery_dl: Optional[GalleryDLDownloader] = None
cookie_manager: Optional[CookieManager] = None
mtproto_client: Optional[MTProtoClient] = None

# Queue instance
download_queue: Optional[DownloadQueue] = None

# Fun greeting messages
GREETINGS = [
    "Hey! Ready to download? 🚀",
    "Send me a link and I'll do the rest! ✨",
    "I'm listening... send a link! 🎧",
    "Ready for your stories! 📸"
]

PROCESSING_MSGS = [
    "🔍 Checking URL...",
    "🧐 Analyzing link...",
    "💾 Processing request...",
    "⚡ One moment please..."
]

# Map job_id -> status_message object for updates
JOB_MESSAGES = {}

async def queue_status_callback(job):
    """Callback for queue status updates."""
    status_msg = JOB_MESSAGES.get(job.job_id)
    if not status_msg:
        return

    try:
        platform_emoji = {"Instagram": "📸", "TikTok": "🎵", "Twitter": "🐦", "Facebook": "📘", "Snapchat": "👻"}
        emoji = platform_emoji.get(job.platform, "📥")
        
        if job.status.value == "queued":
            # Show queue position
            pos = get_queue().get_queue_position(job.job_id)
            await status_msg.edit_text(f"⏳ *Queued* (Position: {pos})\nWaiting for available worker...", parse_mode='Markdown')
            
        elif job.status.value == "downloading":
            await status_msg.edit_text(f"⬇️ *Downloading...*\n{emoji} Grabbing {job.platform} content", parse_mode='Markdown')
            
        elif job.status.value == "uploading":
            # Batch upload handles its own status updates, but we set a generic one just in case
            # await status_msg.edit_text(f"🚀 *Uploading...*\nPreparing to send files...", parse_mode='Markdown')
            pass
            
        elif job.status.value == "completed":
            # Increment stats
            stats_manager.increment_download(job.user_id, job.platform)
            
            # Final cleanup
            if job.job_id in JOB_MESSAGES:
                del JOB_MESSAGES[job.job_id]
                
        elif job.status.value == "failed":
            await status_msg.edit_text(f"❌ *Failed*\n{job.error}", parse_mode='Markdown')
            if job.job_id in JOB_MESSAGES:
                del JOB_MESSAGES[job.job_id]
                
    except Exception as e:
        logging.error(f"Failed to update status message for job {job.job_id}: {e}")


# ============= MAIN MENU & NAVIGATION =============

def get_main_menu_keyboard():
    """Get the main menu inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use", callback_data="menu_help")],
        [InlineKeyboardButton("🍪 Manage Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("📊 My Stats", callback_data="menu_stats")],
    ])


def get_back_button(callback_data: str = "menu_main"):
    """Get a back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=callback_data)]])


async def send_main_menu(target, is_new_message: bool = True):
    """Send or edit the main menu."""
    text = (
        "🎬 *StoryFlow Downloader*\n\n"
        "I can download stories, reels, and videos from:\n"
        "👻 Snapchat • 📸 Instagram • 🎵 TikTok\n"
        "🐦 Twitter/X • 📘 Facebook\n\n"
        "👇 *Tap a button to get started!*"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ Help & Usage", callback_data="menu_help")],
        [InlineKeyboardButton("📊 My Stats", callback_data="menu_stats"),
         InlineKeyboardButton("🍪 Manage Cookies", callback_data="menu_cookies")],
    ])
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with main menu."""
    await send_main_menu(update.message, is_new_message=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help via command."""
    await send_help_menu(update.message, is_new_message=True)


async def send_help_menu(target, is_new_message: bool = True):
    """Send or edit the help menu."""
    text = (
        "📖 *How to Use StoryFlow*\n\n"
        "1️⃣ Copy a link from any supported platform\n"
        "2️⃣ Paste it here\n"
        "3️⃣ I'll download and send it back!\n\n"
        "_Tap a platform for specific tips:_"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👻 Snapchat", callback_data="help_snapchat"),
         InlineKeyboardButton("📸 Instagram", callback_data="help_instagram")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="help_tiktok"),
         InlineKeyboardButton("📘 Facebook", callback_data="help_facebook")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def send_cookies_menu(target, user_id: str):
    """Send the cookie management menu."""
    # Check existing cookies
    cookies = cookie_manager.list_cookies(user_id) if cookie_manager else []
    
    if cookies:
        lines = ["🍪 *Your Cookies*\n"]
        for c in cookies:
            emoji = "📸" if c['platform'] == 'instagram' else "📘"
            status = "⚠️ Expired" if c.get('is_expired') else "✅ Active"
            lines.append(f"{emoji} {c['platform'].title()}: {status}")
            lines.append(f"   📅 {c.get('expiry_str', 'Unknown')}\n")
        text = "\n".join(lines)
    else:
        text = (
            "🍪 *Cookie Manager*\n\n"
            "No cookies saved yet!\n\n"
            "Cookies let you download content that requires login\n"
            "(like Instagram stories or Facebook reels)."
        )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Add Instagram", callback_data="cookies_instagram"),
         InlineKeyboardButton("📘 Add Facebook", callback_data="cookies_facebook")],
        [InlineKeyboardButton("🗑️ Delete Cookies", callback_data="menu_delete_cookies")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)



async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    
    # ============= MAIN NAVIGATION =============
    
    if query.data == "menu_main":
        await send_main_menu(query, is_new_message=False)
    
    elif query.data == "menu_help":
        await send_help_menu(query, is_new_message=False)
    
    elif query.data == "menu_cookies":
        await send_cookies_menu(query, user_id)
    
    elif query.data == "menu_stats":
        stats = stats_manager.get_user_stats(user_id)
        total = stats.get('total_downloads', 0)
        platforms = stats.get('platforms', {})
        
        # Build platform breakdown
        if platforms:
            breakdown = "\n".join([f"• {p}: {c}" for p, c in platforms.items()])
        else:
            breakdown = "No downloads yet!"
            
        text = (
            f"📊 *Your Statistics*\n\n"
            f"📥 *Total Downloads:* {total}\n\n"
            f"*Platform Breakdown:*\n{breakdown}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    # ============= PLATFORM HELP =============
    
    elif query.data == "help_snapchat":
        text = (
            "👻 *Snapchat Tips*\n\n"
            "Send me a profile link like:\n"
            "`snapchat.com/add/username`\n\n"
            "I'll grab ALL their public stories!\n\n"
            "💡 _No cookies needed for Snapchat_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Help", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "help_instagram":
        text = (
            "📸 *Instagram Tips*\n\n"
            "• *Public posts/reels*: Just send the link\n"
            "• *Stories/Private*: Need cookies first\n\n"
            "Example links:\n"
            "`instagram.com/p/ABC123`\n"
            "`instagram.com/reel/XYZ789`\n\n"
            "💡 _Use 'Manage Cookies' to add login cookies_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🍪 Add Instagram Cookies", callback_data="cookies_instagram")],
            [InlineKeyboardButton("⬅️ Back to Help", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "help_tiktok":
        text = (
            "🎵 *TikTok Tips*\n\n"
            "Just send a TikTok video link:\n"
            "`tiktok.com/@user/video/123`\n\n"
            "I'll download it without watermark!\n\n"
            "💡 _No cookies needed for most videos_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Help", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "help_facebook":
        text = (
            "📘 *Facebook Tips*\n\n"
            "• *Public videos*: Just send the link\n"
            "• *Reels/Private*: Need cookies first\n\n"
            "Example link:\n"
            "`facebook.com/watch/?v=123`\n\n"
            "💡 _Many Facebook videos require login cookies_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🍪 Add Facebook Cookies", callback_data="cookies_facebook")],
            [InlineKeyboardButton("⬅️ Back to Help", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    # ============= COOKIE MANAGEMENT =============
    
    elif query.data == "cookies_instagram":
        context.user_data['awaiting_cookies'] = 'instagram'
        text = (
            "📸 *Upload Instagram Cookies*\n\n"
            "Send me your `cookies.txt` file from Instagram.\n\n"
            "*How to get it:*\n"
            "1. Install 'Get cookies.txt' extension\n"
            "2. Go to instagram.com (logged in)\n"
            "3. Export cookies\n"
            "4. Send the file here\n\n"
            "_Waiting for your file..._"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "cookies_facebook":
        context.user_data['awaiting_cookies'] = 'facebook'
        text = (
            "📘 *Upload Facebook Cookies*\n\n"
            "Send me your `cookies.txt` file from Facebook.\n\n"
            "*How to get it:*\n"
            "1. Install 'Get cookies.txt' extension\n"
            "2. Go to facebook.com (logged in)\n"
            "3. Export cookies\n"
            "4. Send the file here\n\n"
            "_Waiting for your file..._"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "menu_delete_cookies":
        text = (
            "🗑️ *Delete Cookies*\n\n"
            "Which cookies would you like to delete?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Instagram", callback_data="delete_instagram"),
             InlineKeyboardButton("📘 Facebook", callback_data="delete_facebook")],
            [InlineKeyboardButton("⚠️ Delete All", callback_data="delete_all")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    
    elif query.data == "delete_instagram":
        deleted = cookie_manager.delete_cookie_file(user_id, "instagram")
        text = "✅ Instagram cookies deleted!" if deleted else "🤷 No Instagram cookies found."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Cookies", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard)
    
    elif query.data == "delete_facebook":
        deleted = cookie_manager.delete_cookie_file(user_id, "facebook")
        text = "✅ Facebook cookies deleted!" if deleted else "🤷 No Facebook cookies found."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Cookies", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard)
    
    elif query.data == "delete_all":
        ig = cookie_manager.delete_cookie_file(user_id, "instagram")
        fb = cookie_manager.delete_cookie_file(user_id, "facebook")
        text = "✅ All cookies deleted!" if (ig or fb) else "🤷 No cookies to delete."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Cookies", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard)
    
    # ============= LEGACY SUPPORT =============
    
    elif query.data == "help":
        await send_help_menu(query, is_new_message=False)
    
    elif query.data == "upload_cookies":
        await send_cookies_menu(query, user_id)


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
    
    # Define download function based on platform
    async def download_func():
        try:
            if platform == "Snapchat":
                # Check if it's a Spotlight link (public video)
                if "/spotlight/" in url:
                    logging.info("🔦 Detected Snapchat Spotlight link, using gallery-dl...")
                    return await gallery_dl.download(url, platform, user_id)
                
                # Otherwise treat as User Stories
                username = extract_snapchat_username(url)
                if not username:
                    return {'success': False, 'error': 'Invalid Snapchat link'}
                return snapchat.download_stories(username)
            else:
                # Instagram, TikTok, Twitter, Facebook
                return await gallery_dl.download(url, platform, user_id)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # Define upload function
    async def upload_func(files):
        await batch_upload_media(update, files, status_msg)

    # Submit to queue
    if download_queue:
        job = await download_queue.submit(
            user_id=user_id,
            url=url,
            platform=platform,
            download_func=download_func,
            upload_func=upload_func
        )
        
        if job:
            # Track status message for updates
            JOB_MESSAGES[job.job_id] = status_msg
            
            # Show queue position if queued
            pos = download_queue.get_queue_position(job.job_id)
            if pos > 0:
                 await status_msg.edit_text(f"⏳ *Queued* (Position: {pos})\nWaiting for available worker...", parse_mode='Markdown')
        else:
            await status_msg.edit_text("⚠️ *Queue Full*\nYou have too many active downloads. Please wait for one to finish.")
    else:
        # Fallback if queue failed to init
        await status_msg.edit_text("⚠️ System Error: Queue not active.")
        logging.error("Download queue not initialized!")


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
                
                # 50MB limit for bot API - try MTProto for larger files
                if file_size > 50 * 1024 * 1024:
                    # Try MTProto for large files
                    if mtproto_client and mtproto_client.is_connected:
                        logging.info(f"📤 Large file ({file_size / 1024 / 1024:.1f}MB), using MTProto...")
                        chat_id = update.effective_chat.id
                        success = await mtproto_client.upload_file(chat_id, filepath, caption="")
                        if success:
                            uploaded_count += 1
                            # Cleanup after successful upload
                            try:
                                os.remove(filepath)
                                logging.debug(f"Cleaned up: {filepath}")
                            except:
                                pass
                        else:
                            failed_count += 1
                    else:
                        logging.warning(f"File too large (>50MB) and MTProto not available: {filepath}")
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
                    await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                logging.error(f"Error sending individual file {filepath}: {e}")
                failed_count += 1
            finally:
                # Cleanup individual file
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        logging.debug(f"Cleaned up: {filepath}")
                    except Exception as e:
                        logging.warning(f"Failed to cleanup {filepath}: {e}")
        
        # Delay between batches to avoid flood control
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(1)
    
    # Final Status Update
    if failed_count == 0:
        await status_msg.edit_text("✅ Delivery Complete!\nAll files sent successfully.")
    elif uploaded_count > 0:
        await status_msg.edit_text(f"✅ Delivery Complete!\nSent {uploaded_count} files.\n(Failed: {failed_count})")
    else:
        await status_msg.edit_text("❌ Failed to send files.")
        
    # Send friendly closing message
    if failed_count == 0:
        await update.message.reply_text(
            f"Enjoy! ✨ Send another link whenever you're ready.",
            parse_mode='Markdown'
        )


async def upload_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /upload_cookies command - show cookie menu."""
    user_id = str(update.effective_user.id)
    cookies = cookie_manager.list_cookies(user_id) if cookie_manager else []
    
    if cookies:
        lines = ["🍪 *Your Cookies*\n"]
        for c in cookies:
            emoji = "📸" if c['platform'] == 'instagram' else "📘"
            status = "⚠️ Expired" if c.get('is_expired') else "✅ Active"
            lines.append(f"{emoji} {c['platform'].title()}: {status}")
            lines.append(f"   📅 {c.get('expiry_str', 'Unknown')}\n")
        text = "\n".join(lines)
    else:
        text = (
            "🍪 *Cookie Manager*\n\n"
            "No cookies yet! Add some to unlock private content."
        )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Add Instagram", callback_data="cookies_instagram"),
         InlineKeyboardButton("📘 Add Facebook", callback_data="cookies_facebook")],
        [InlineKeyboardButton("🗑️ Delete Cookies", callback_data="menu_delete_cookies")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def list_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias for upload_cookies - shows cookie status."""
    await upload_cookies(update, context)


async def delete_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_cookies command."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Instagram", callback_data="delete_instagram"),
         InlineKeyboardButton("📘 Facebook", callback_data="delete_facebook")],
        [InlineKeyboardButton("⚠️ Delete All", callback_data="delete_all")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    await update.message.reply_text(
        "🗑️ *Delete Cookies*\n\nWhich cookies would you like to delete?",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


# Queue status command available when queue is enabled
# async def queue_status(update, context): ...


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document (cookie file) upload."""
    document: Document = update.message.document
    user_id = str(update.effective_user.id)
    
    # Check if user was expecting to upload cookies
    awaiting_platform = context.user_data.get('awaiting_cookies')
    if not awaiting_platform:
        await update.message.reply_text(
            "📎 Got a file, but I wasn't expecting one.\n"
            "Use /upload\\_cookies first if you want to upload cookies.",
            parse_mode='Markdown'
        )
        return
    
    # Reset flag
    context.user_data['awaiting_cookies'] = False
    
    # Handle legacy True value (default to instagram)
    if awaiting_platform is True:
        awaiting_platform = 'instagram'
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file (cookies.txt)")
        return
    
    # Download file
    platform_emoji = "📸" if awaiting_platform == 'instagram' else "📘"
    status_msg = await update.message.reply_text(f"⏳ Processing {awaiting_platform.title()} cookies...")
    
    try:
        file = await document.get_file()
        temp_path = f"/tmp/cookies_{user_id}.txt"
        await file.download_to_drive(temp_path)
        
        # Save cookie file for the selected platform
        result = cookie_manager.save_cookie_file(user_id, awaiting_platform, temp_path)
        
        if result['success']:
            platform_name = awaiting_platform.title()
            expiry_str = result.get('expiry_str', 'Unknown')
            is_expired = result.get('is_expired', False)
            
            if is_expired:
                await status_msg.edit_text(
                    f"⚠️ *{platform_name} Cookies Saved (But Expired!)*\n\n"
                    f"These cookies expired on {expiry_str}.\n"
                    f"Please export fresh cookies from your browser and upload again.",
                    parse_mode='Markdown'
                )
            else:
                await status_msg.edit_text(
                    f"✅ *{platform_name} Cookies Saved!*\n\n"
                    f"📅 Valid until: {expiry_str}\n\n"
                    f"You can now download {platform_name} content that requires login.",
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


async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Scheduled job to clean up old media files (older than 24h).
    """
    download_path = context.bot_data.get('download_path')
    if not download_path:
        logging.warning("🧹 Cleanup job skipped: download_path not set")
        return
        
    logging.info("🧹 Starting daily cleanup...")
    count = 0
    cleaned_size = 0
    
    try:
        current_time = time.time()
        max_age = 86400  # 24 hours in seconds
        
        for root, dirs, files in os.walk(download_path):
            for filename in files:
                filepath = os.path.join(root, filename)
                
                # Check file age
                try:
                    file_stat = os.stat(filepath)
                    file_age = current_time - file_stat.st_mtime
                    
                    if file_age > max_age:
                        file_size = file_stat.st_size
                        os.remove(filepath)
                        count += 1
                        cleaned_size += file_size
                        logging.debug(f"Deleted old file: {filename}")
                        
                except Exception as e:
                    logging.warning(f"Failed to check/delete {filename}: {e}")
                    
        if count > 0:
            size_mb = cleaned_size / (1024 * 1024)
            logging.info(f"✨ Cleanup complete: Removed {count} files ({size_mb:.2f} MB)")
        else:
            logging.info("✨ Cleanup complete: No old files found")
            
    except Exception as e:
        logging.error(f"❌ Cleanup job failed: {e}")


def run_telegram_bot(token: str, download_path: str, cookie_path: str, api_base_url: str) -> None:
    """Run the Telegram bot."""
    global snapchat, gallery_dl, cookie_manager, mtproto_client
    
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
    
    # Create application with increased timeouts for slow connections
    app = Application.builder().token(token).read_timeout(120).write_timeout(120).build()
    
    # Initialize MTProto client and Download Queue
    if MTPROTO_AVAILABLE and init_mtproto:
        async def post_init(application):
            global mtproto_client, download_queue
            
            # Start MTProto
            mtproto_client = await init_mtproto()
            if mtproto_client and mtproto_client.is_connected:
                logging.info("📤 MTProto ready for large file uploads (up to 2GB)")
            else:
                logging.info("ℹ️ MTProto not configured - files >50MB will be skipped")
            
            # Start Download Queue
            logging.info("🚀 Starting download queue workers...")
            download_queue = await init_queue(max_concurrent=3, status_callback=queue_status_callback)
        
        app.post_init = post_init
    else:
        # Just init queue if MTProto failed
        async def post_init(application):
            global download_queue
            logging.info("🚀 Starting download queue workers...")
            download_queue = await init_queue(max_concurrent=3, status_callback=queue_status_callback)
            logging.info("ℹ️ MTProto not available - files >50MB will be skipped")
            
        app.post_init = post_init
    
    # Store download path for cleanup job
    app.bot_data['download_path'] = download_path
    
    # Schedule cleanup job (every 24h)
    if app.job_queue:
        app.job_queue.run_repeating(cleanup_job, interval=86400, first=10)
        logging.info("🧹 Cleanup job scheduled (every 24h)")
    else:
        logging.warning("⚠️ JobQueue not available - cleanup job disabled")
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("upload_cookies", upload_cookies))
    app.add_handler(CommandHandler("my_cookies", list_cookies))
    app.add_handler(CommandHandler("delete_cookies", delete_cookies))
    # Note: /queue command available but queue not auto-started
    
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
