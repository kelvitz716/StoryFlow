"""Telegram bot for StoryFlow media downloader."""

import os
import sys
import logging
import asyncio
import time
from typing import Optional
from functools import wraps

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
from core.queue import DownloadQueue, DownloadJob, JobStatus, init_queue, get_queue
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader
from auth.cookies import CookieManager
from auth.access import AccessManager  # [NEW]
from core.stats import stats_manager

# MTProto import (lazily loaded to avoid early event loop errors in Python 3.12)
MTPROTO_AVAILABLE = None

def _ensure_mtproto():
    global MTPROTO_AVAILABLE
    if MTPROTO_AVAILABLE is not None:
        return MTPROTO_AVAILABLE
    try:
        # We don't import here, we just check if it's available
        import auth.mtproto
        MTPROTO_AVAILABLE = True
    except Exception as e:
        logging.warning(f"MTProto not available: {e}")
        MTPROTO_AVAILABLE = False
    return MTPROTO_AVAILABLE


import random

# Initialize components
snapchat: Optional[SnapchatDownloader] = None
gallery_dl: Optional[GalleryDLDownloader] = None
cookie_manager: Optional[CookieManager] = None
access_manager: Optional[AccessManager] = None  # [NEW]
mtproto_client: Optional['MTProtoClient'] = None

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

# MTProto authentication state
AUTH_PENDING = None  # asyncio.Future for pending auth
AUTH_TYPE = None  # 'code' or 'password'
AUTH_ADMIN_ID = None  # Admin user ID for auth


def requires_access(handler):
    """
    Decorator to enforce access control on command handlers.
    
    Checks if the user is allowed via access_manager before executing the handler.
    Returns an "unauthorized" message if access is denied.
    """
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        
        # Ignore Telegram Service messages
        if user_id == "777000":
            return
            
        # Check if access_manager is initialized and user is allowed
        if access_manager and not access_manager.is_allowed(user_id):
            await update.message.reply_text(
                f"⛔ *Access Denied*\n\n"
                f"You are not authorized to use this bot.\n"
                f"User ID: `{user_id}`\n\n"
                f"Please contact the bot administrator if you need access.",
                parse_mode='Markdown'
            )
            logging.warning(f"🚫 Unauthorized access attempt from user {user_id}")
            return
        
        # User is authorized, proceed with handler
        return await handler(update, context)
    
    return wrapper


async def get_auth_code(application: Application) -> str:
    """
    Request authentication code from admin via bot.
    
    Creates a Future and waits for admin to send the code.
    Timeout: 180 seconds (3 minutes).
    """
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    
    # Get admin ID from access_manager
    admin_id = access_manager.admin_id if access_manager else None
    if not admin_id:
        raise Exception("Admin ID not configured")
    
    AUTH_ADMIN_ID = admin_id
    
    # Create Future for code
    AUTH_PENDING = asyncio.Future()
    AUTH_TYPE = 'code'
    
    # Send request to admin
    try:
        await application.bot.send_message(
            chat_id=int(admin_id),
            text=(
                "📲 *MTProto Authentication Required*\n\n"
                "A verification code has been sent to your phone.\n"
                "Please send the code here (5-6 digits).\n\n"
                "⏱️ Timeout: 3 minutes"
            ),
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Failed to send auth request: {e}")
        AUTH_PENDING = None
        AUTH_TYPE = None
        raise
    
    # Wait for code with timeout
    try:
        code = await asyncio.wait_for(AUTH_PENDING, timeout=180)
        logging.info("✅ Auth code received from admin")
        return code
    except asyncio.TimeoutError:
        logging.error("❌ Auth code timeout (3 minutes)")
        await application.bot.send_message(
            chat_id=int(admin_id),
            text="❌ Authentication timed out. Please try again."
        )
        raise Exception("Authentication timeout")
    finally:
        AUTH_PENDING = None
        AUTH_TYPE = None
        AUTH_ADMIN_ID = None


async def get_auth_password(application: Application) -> str:
    """
    Request 2FA password from admin via bot.
    
    Similar to get_auth_code but for password entry.
    """
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    
    admin_id = access_manager.admin_id if access_manager else None
    if not admin_id:
        raise Exception("Admin ID not configured")
    
    AUTH_ADMIN_ID = admin_id
    
    # Create Future for password
    AUTH_PENDING = asyncio.Future()
    AUTH_TYPE = 'password'
    
    # Send request to admin
    try:
        await application.bot.send_message(
            chat_id=int(admin_id),
            text=(
                "🔐 *2FA Password Required*\n\n"
                "Please send your Two-Factor Authentication password.\n\n"
                "⏱️ Timeout: 3 minutes"
            ),
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Failed to send 2FA request: {e}")
        AUTH_PENDING = None
        AUTH_TYPE = None
        raise
    
    # Wait for password with timeout
    try:
        password = await asyncio.wait_for(AUTH_PENDING, timeout=180)
        logging.info("✅ 2FA password received from admin")
        return password
    except asyncio.TimeoutError:
        logging.error("❌ 2FA password timeout (3 minutes)")
        await application.bot.send_message(
            chat_id=int(admin_id),
            text="❌ Authentication timed out. Please try again."
        )
        raise Exception("Authentication timeout")
    finally:
        AUTH_PENDING = None
        AUTH_TYPE = None
        AUTH_ADMIN_ID = None


async def update_job_status(application: Application, job: 'DownloadJob'):
    """Callback for queue status updates, using the application bot context."""
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
            await status_msg.edit_text(f"⬇️ *Downloading...*\n{emoji} {job.message}", parse_mode='Markdown')
            
        elif job.status.value == "uploading":
            # Batch upload handles its own status updates, but we set a generic one just in case
            # await status_msg.edit_text(f"🚀 *Uploading...*\nPreparing to send files...", parse_mode='Markdown')
            pass
            
        elif job.status.value == "completed":
            # Increment stats
            stats_manager.increment_download(job.user_id, job.platform)
            
            # Final cleanup
            JOB_MESSAGES.pop(job.job_id, None)
                
        elif job.status.value == "failed":
            await status_msg.edit_text(f"❌ *Failed*\n{job.error}", parse_mode='Markdown')
            JOB_MESSAGES.pop(job.job_id, None)
                
    except Exception as e:
        logging.error(f"Failed to update status message for job {job.job_id}: {e}")


# ============= MAIN MENU & NAVIGATION =============

def get_main_menu_keyboard(user_id: Optional[str] = None):
    """Get the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("📖 How to Use", callback_data="menu_help")],
        [InlineKeyboardButton("🍪 Manage Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("📊 My Stats", callback_data="menu_stats")],
    ]
    
    # [NEW] Admin Tools Button
    if user_id and access_manager and access_manager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("🛠️ Admin Tools", callback_data="menu_admin")])
        
    return InlineKeyboardMarkup(keyboard)


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
    user_id = str(target.chat.id) if hasattr(target, 'chat') else str(target.from_user.id)
    keyboard = get_main_menu_keyboard(user_id)
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


@requires_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with main menu."""
    await send_main_menu(update.message, is_new_message=True)


@requires_access
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
        "*Available Commands:*\n"
        "• /start - Main menu\n"
        "• /help - Usage guide\n"
        "• /my\\_cookies - Manage login cookies\n"
        "• /purge - ⚠️ Delete all downloaded files (Maintenance)\n\n"
        "_Tap a platform for specific tips:_"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👻 Snapchat", callback_data="help_snapchat"),
         InlineKeyboardButton("📸 Instagram", callback_data="help_instagram")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="help_tiktok"),
         InlineKeyboardButton("📘 Facebook", callback_data="help_facebook")],
        [InlineKeyboardButton("🐦 Twitter/X", callback_data="help_twitter"),
         InlineKeyboardButton("⚠️ Purge System", callback_data="menu_purge_confirm")],
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
        [InlineKeyboardButton("🎵 Add TikTok", callback_data="cookies_tiktok")],
        [InlineKeyboardButton("🗑️ Delete Cookies", callback_data="menu_delete_cookies")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def send_admin_menu(target, user_id: str):
    """Send the admin tools menu."""
    if not access_manager.is_admin(user_id):
        return

    text = (
        "🛠️ *Admin Tools*\n\n"
        "Manage users and system access.\n"
        f"Currently allowed users: `{len(access_manager.get_allowed_users())}`"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Users", callback_data="admin_list"),
         InlineKeyboardButton("⚠️ System Purge", callback_data="menu_purge_confirm")],
        [InlineKeyboardButton("➕ Add User", callback_data="admin_add"),
         InlineKeyboardButton("➖ Remove User", callback_data="admin_remove")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    # Check if target is message or callback query
    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)



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

    elif query.data == "menu_admin":
        await send_admin_menu(query, user_id)

    elif query.data == "admin_list":
        users = access_manager.get_allowed_users()
        if not users:
            user_list = "_No users allowed (only Admins)_"
        else:
            user_list = "\n".join([f"• `{u}`" for u in users])
        
        text = f"📋 *Allowed Users:*\n\n{user_list}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_admin")]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

    elif query.data == "admin_add":
        context.user_data['awaiting_action'] = 'add_user'
        text = (
            "➕ *Add User*\n\n"
            "Send the Telegram ID of the user or channel you want to authorize.\n\n"
            "_Tap Cancel to abort._"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="menu_admin")]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

    elif query.data == "admin_remove":
        context.user_data['awaiting_action'] = 'remove_user'
        text = (
            "➖ *Remove User*\n\n"
            "Send the Telegram ID you want to remove.\n\n"
            "_Tap Cancel to abort._"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="menu_admin")]])
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

    elif query.data == "help_twitter":
        text = (
            "🐦 *Twitter/X Tips*\n\n"
            "Send me a tweet link:\n"
            "`x.com/user/status/123...`\n"
            "`twitter.com/user/status/123...`\n\n"
            "I'll download the video or images!\n\n"
            "💡 _No cookies needed usually_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Help", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

    # ============= SYSTEM ACTIONS =============

    elif query.data == "menu_purge_confirm":
        text = (
            "⚠️ *System Purge - Warning*\n\n"
            "This will delete ALL downloaded files from the server.\n"
            "This is useful if storage is full or downloads are stuck.\n\n"
            "*Are you sure?*"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Yes, Purge Everything", callback_data="menu_purge_execute")],
            [InlineKeyboardButton("⬅️ No, Go Back", callback_data="menu_help")],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

    elif query.data == "menu_purge_execute":
        await query.edit_message_text("🧹 Starting full system purge...")
        user_id = query.from_user.id
        
        # Trigger same logic as /purge command
        if context.job_queue:
            context.job_queue.run_once(
                cleanup_job, 
                when=0,
                data={'force': True, 'chat_id': query.message.chat_id},
                name=f"purge_{user_id}"
            )
        else:
             await query.message.reply_text("⚠️ System Error: Job Queue not active. Cannot schedule purge.")
             logging.error("JobQueue not available to schedule purge")
    
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
    
    elif query.data == "cookies_tiktok":
        context.user_data['awaiting_cookies'] = 'tiktok'
        text = (
            "🎵 *Upload TikTok Cookies*\n\n"
            "Send me your `cookies.txt` file from TikTok.\n\n"
            "*How to get it:*\n"
            "1. Install 'Get cookies.txt' extension\n"
            "2. Go to tiktok.com (logged in)\n"
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
            [InlineKeyboardButton("🎵 TikTok", callback_data="delete_tiktok")],
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
    
    elif query.data == "delete_tiktok":
        deleted = cookie_manager.delete_cookie_file(user_id, "tiktok")
        text = "✅ TikTok cookies deleted!" if deleted else "🤷 No TikTok cookies found."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Cookies", callback_data="menu_cookies")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard)
    
    elif query.data == "delete_all":
        ig = cookie_manager.delete_cookie_file(user_id, "instagram")
        fb = cookie_manager.delete_cookie_file(user_id, "facebook")
        tk = cookie_manager.delete_cookie_file(user_id, "tiktok")
        text = "✅ All cookies deleted!" if (ig or fb or tk) else "🤷 No cookies to delete."
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
    # Guard against None message (edited messages, channel posts, etc.)
    if not update.message or not update.message.text:
        logging.warning(f"Received update without message/text: {type(update)}")
        return
    
    url = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    # [NEW] Access Check
    if user_id == "777000":
        return # Ignore Telegram Service messages
        
    if not access_manager.is_allowed(user_id):
        if access_manager.is_admin(user_id):
            pass # Admin is always allowed
        else:
            await update.message.reply_text(f"⛔ Not authorized to use this bot (ID: `{user_id}`).", parse_mode='Markdown')
            return

    # [NEW] Admin Input Handling
    action = context.user_data.get('awaiting_action')
    if action and access_manager.is_admin(user_id):
        if action == 'add_user':
            target_id = url.strip() # In this context, url is just the text input
            if target_id.isdigit() or target_id.startswith('-'):
                if access_manager.add_user(target_id):
                    await update.message.reply_text(f"✅ User/Channel `{target_id}` added!")
                else:
                    await update.message.reply_text(f"⚠️ User `{target_id}` is already allowed.")
            else:
                await update.message.reply_text("❌ Invalid ID format. Please send a numeric ID.")
            
            context.user_data.pop('awaiting_action', None)
            await send_admin_menu(update.message, user_id)
            return

        elif action == 'remove_user':
            target_id = url.strip()
            if access_manager.remove_user(target_id):
                await update.message.reply_text(f"✅ User `{target_id}` removed.")
            else:
                await update.message.reply_text(f"⚠️ User `{target_id}` was not found.")
            
            context.user_data.pop('awaiting_action', None)
            await send_admin_menu(update.message, user_id)
            return

    if not is_supported_url(url):
        await update.message.reply_text("🤔 Hmm, that doesn't look like a supported link. Try a Snapchat, Instagram, or TikTok link!")
        return
    
    # Identify platform
    platform = identify_platform(url)
    
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
                
                # 45MB limit (Bot API max is 50MB) - try MTProto for larger files for reliability
                if file_size > 45 * 1024 * 1024:
                    # Try MTProto for large files
                    if mtproto_client and mtproto_client.is_connected:
                        logging.info(f"📤 Large file ({file_size / 1024 / 1024:.1f}MB), using MTProto...")
                        chat_id = update.effective_chat.id
                        message_id = update.message.message_id
                        # Mask for privacy
                        masked_chat = f"{str(chat_id)[:3]}***{str(chat_id)[-3:]}" if len(str(chat_id)) > 6 else "***"
                        logging.debug(f"📍 Extracted chat_id={masked_chat}, message_id={message_id}")
                        
                        # Progress callback
                        last_upload_update = 0
                        async def upload_progress(current, total):
                            nonlocal last_upload_update
                            current_time = time.time()
                            if current_time - last_upload_update < 2.0:
                                return
                            last_upload_update = current_time
                            percent = (current / total) * 100
                            try:
                                await status_msg.edit_text(
                                    f"📤 Uploading large file via MTProto...\n"
                                    f"File: {os.path.basename(filepath)}\n"
                                    f"Progress: {percent:.1f}%"
                                )
                            except Exception:
                                pass

                        success = await mtproto_client.upload_file(
                            chat_id, filepath, caption="",
                            reply_to_message_id=message_id,
                            progress_callback=upload_progress
                        )
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
        
        # Send media group with improved retry logic for flood control
        if media_group:
            upload_success = False
            retry_count = 0
            max_retry_attempts = 5  # Increased from 3
            
            while not upload_success and retry_count < max_retry_attempts:
                try:
                    await update.message.reply_media_group(media=media_group)
                    uploaded_count += len(valid_files)
                    upload_success = True
                    
                    # Cleanup: Delete files after successful upload
                    for filepath in valid_files:
                        try:
                            os.remove(filepath)
                            logging.debug(f"Cleaned up: {filepath}")
                        except Exception as e:
                            logging.warning(f"Failed to cleanup {filepath}: {e}")
                    
                    logging.info(f"✅ Successfully uploaded batch {batch_idx + 1}/{len(batches)}")
                    
                except RetryAfter as e:
                    retry_count += 1
                    wait_time = e.retry_after
                    logging.warning(f"⏳ FloodWait triggered: waiting {wait_time}s (attempt {retry_count}/{max_retry_attempts})")
                    
                    try:
                        await status_msg.edit_text(
                            f"⏳ Telegram rate limit hit! Waiting {wait_time}s...\\n"
                            f"Batch {batch_idx + 1}/{len(batches)} • Attempt {retry_count}/{max_retry_attempts}\\n"
                            f"Don't worry, I'll retry automatically! 🔄"
                        )
                    except Exception:
                        pass  # Ignore if status update fails
                    
                    await asyncio.sleep(wait_time + 2)  # Wait requested time + buffer
                    
                except Exception as e:
                    retry_count += 1
                    
                    # Check if it's a flood-related error
                    error_str = str(e).lower()
                    if 'flood' in error_str or 'retry' in error_str or '429' in error_str:
                        wait_time = 30 + (retry_count * 10)  # Exponential backoff
                        logging.warning(f"⏳ Possible flood control (attempt {retry_count}): waiting {wait_time}s - {e}")
                        
                        try:
                            await status_msg.edit_text(
                                f"⏳ Rate limit detected! Waiting {wait_time}s...\\n"
                                f"Batch {batch_idx + 1}/{len(batches)} • Attempt {retry_count}/{max_retry_attempts}"
                            )
                        except Exception:
                            pass
                        
                        await asyncio.sleep(wait_time)
                    else:
                        # Non-flood error - log and break
                        logging.error(f"❌ Error sending media group batch {batch_idx + 1}: {e}")
                        failed_count += len(valid_files)
                        break
            
            # If we exhausted retries without success
            if not upload_success and retry_count >= max_retry_attempts:
                logging.error(f"❌ Failed to upload batch {batch_idx + 1} after {max_retry_attempts} attempts")
                failed_count += len(valid_files)
        
        # Send files that couldn't be in the media group individually
        for file_type, filepath in files_to_send_individually:
            try:
                with open(filepath, 'rb') as f:
                    if file_type == 'photo':
                        await update.message.reply_document(f, caption=f"📷 {os.path.basename(filepath)}")
                    else:
                        await update.message.reply_document(f, caption=f"📁 {os.path.basename(filepath)}")
                    uploaded_count += 1
                    await asyncio.sleep(2)  # Increased delay for individual files
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
        
        # Progressive delay between batches to avoid flood control
        if batch_idx < len(batches) - 1:
            # Progressive delay: starts at 2s, increases to 7s for later batches
            base_delay = 2
            incremental_delay = min(batch_idx * 0.5, 5)  # Max 5s additional delay
            total_delay = base_delay + incremental_delay
            
            logging.info(f"⏱️ Waiting {total_delay:.1f}s before next batch (progressive rate limiting)")
            await asyncio.sleep(total_delay)
    
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

    # RESILIENT CLEANUP: Ensure ALL files in the original list are removed
    # This covers files that might have failed preparation or upload
    logging.info(f"🧹 Performing post-upload cleanup for {len(files)} files...")
    cleaned_count = 0
    for filepath in files:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                cleaned_count += 1
                logging.debug(f"Resilient cleanup: {filepath}")
        except FileNotFoundError:
            pass # Already gone, which is fine
        except Exception as e:
            logging.warning(f"Failed to cleanup {filepath}: {e}")
            
    if cleaned_count > 0:
        logging.info(f"✨ Cleanup verified: {cleaned_count}/{len(files)} files removed.")


@requires_access
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
        [InlineKeyboardButton("🎵 Add TikTok", callback_data="cookies_tiktok")],
        [InlineKeyboardButton("🗑️ Delete Cookies", callback_data="menu_delete_cookies")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


@requires_access
async def list_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias for upload_cookies - shows cookie status."""
    await upload_cookies(update, context)


@requires_access
async def delete_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_cookies command."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Instagram", callback_data="delete_instagram"),
         InlineKeyboardButton("📘 Facebook", callback_data="delete_facebook")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="delete_tiktok")],
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


def is_supported_url(url: str) -> bool:
    """Strictly validate that the URL belongs to a supported domain."""
    import re
    supported_domains = [
        r'https?://(www\.)?snapchat\.com/.*',
        r'https?://(www\.)?instagram\.com/.*',
        r'https?://(www\.)?tiktok\.com/.*',
        r'https?://vm\.tiktok\.com/.*',
        r'https?://(www\.)?(twitter\.com|x\.com)/.*',
        r'https?://(www\.)?facebook\.com/.*',
        r'https?://fb\.watch/.*'
    ]
    return any(re.match(pattern, url, re.IGNORECASE) for pattern in supported_domains)


async def handle_auth_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle MTProto authentication code/password input from admin.
    
    Intercepts messages when AUTH_PENDING is active.
    """
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    
    # Only process if auth is pending and from admin
    if not AUTH_PENDING or not AUTH_TYPE:
        return  # Not waiting for auth, let other handlers process
    
    user_id = str(update.effective_user.id)
    if user_id != AUTH_ADMIN_ID:
        return  # Not from admin
    
    text = update.message.text.strip()
    
    if AUTH_TYPE == 'code':
        # Validate code format (5-6 digits, possibly with dash)
        code = text.replace('-', '').replace(' ', '')
        if not code.isdigit() or len(code) not in [5, 6]:
            await update.message.reply_text(
                "❌ Invalid code format. Please send 5-6 digits (e.g., 12345 or 123-456)"
            )
            return
        
        # Resolve the Future with the code
        if not AUTH_PENDING.done():
            AUTH_PENDING.set_result(code)
            await update.message.reply_text("✅ Code received! Authenticating...")
            logging.info(f"📲 Auth code submitted by admin")
    
    elif AUTH_TYPE == 'password':
        # No validation for password, accept as-is
        if not AUTH_PENDING.done():
            AUTH_PENDING.set_result(text)
            await update.message.reply_text("✅ Password received! Authenticating...")
            logging.info(f"🔐 2FA password submitted by admin")


@requires_access
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
        import tempfile
        file = await document.get_file()
        
        # Create a secure temporary file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            temp_path = tf.name
        
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
    Can also be triggered manually with force=True to delete ALL files.
    """
    download_path = context.bot_data.get('download_path')
    # Check if triggered manually via command
    force = False
    if context.job and context.job.data:
        force = context.job.data.get('force', False)
    
    if not download_path:
        logging.warning("🧹 Cleanup job skipped: download_path not set")
        return
        
    logging.info(f"🧹 Starting {'FORCED ' if force else ''}cleanup...")
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
                    
                    # Delete if forced OR if older than max_age
                    if force or file_age > max_age:
                        file_size = file_stat.st_size
                        os.remove(filepath)
                        count += 1
                        cleaned_size += file_size
                        logging.debug(f"Deleted {'forced' if force else 'old'} file: {filename}")
                        
                except Exception as e:
                    logging.warning(f"Failed to check/delete {filename}: {e}")
                    
        if count > 0:
            size_mb = cleaned_size / (1024 * 1024)
            msg = f"✨ Cleanup complete: Removed {count} files ({size_mb:.2f} MB)"
            logging.info(msg)
            # If triggered manually, try to reply
            # If triggered manually, try to reply
            if context.job and context.job.data and context.job.data.get('chat_id'):
                await context.bot.send_message(chat_id=context.job.data['chat_id'], text=msg)
        else:
            msg = "✨ Cleanup complete: No files found to remove"
            logging.info(msg)
            if context.job and context.job.data and context.job.data.get('chat_id'):
                await context.bot.send_message(chat_id=context.job.data['chat_id'], text=msg)
            
    except Exception as e:
        logging.error(f"❌ Cleanup job failed: {e}")
        if context.job and context.job.data and context.job.data.get('chat_id'):
            await context.bot.send_message(chat_id=context.job.data['chat_id'], text=f"❌ Cleanup failed: {e}")


async def purge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /purge command to delete all downloaded files."""
    user_id = str(update.effective_user.id)
    
    # Security check: only allow admin to use purge
    if not access_manager.is_admin(user_id):
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    msg = await update.message.reply_text("🧹 Starting full system purge...")
    
    # Schedule the cleanup job immediately with force=True
    if context.job_queue:
        context.job_queue.run_once(
            cleanup_job, 
            when=0,
            data={'force': True, 'chat_id': update.effective_chat.id},
            name=f"purge_{user_id}"
        )
    else:
        # Fallback if no job queue - run synchronously (might block briefly, but safer than crashing)
        # Note: cleanup_job requires a context with .job.data usually, so we mock it or call logic directly
        # For simplicity, we'll try to just call the core logic if possible, 
        # but cleanup_job relies on context.job structure. 
        # Better to warn user.
        await update.message.reply_text("⚠️ System Error: Job Queue not active. Cannot schedule purge.")
        logging.error("JobQueue not available to schedule purge")


# ============= ADMIN COMMANDS =============

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /adduser command."""
    user_id = str(update.effective_user.id)
    if not access_manager.is_admin(user_id):
        return # Ignore non-admins
        
    if not context.args:
        await update.message.reply_text("Usage: /adduser <user_id>")
        return
        
    target_id = context.args[0]
    if access_manager.add_user(target_id):
        await update.message.reply_text(f"✅ User {target_id} added.")
    else:
        await update.message.reply_text(f"⚠️ User {target_id} is already allowed.")


async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /removeuser command."""
    user_id = str(update.effective_user.id)
    if not access_manager.is_admin(user_id):
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <user_id>")
        return
        
    target_id = context.args[0]
    if access_manager.remove_user(target_id):
        await update.message.reply_text(f"✅ User {target_id} removed.")
    else:
        await update.message.reply_text(f"⚠️ User {target_id} was not in the list.")


async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /listusers command."""
    user_id = str(update.effective_user.id)
    if not access_manager.is_admin(user_id):
        return
        
    users = access_manager.get_allowed_users()
    if not users:
        await update.message.reply_text("No allowed users (only Admin).")
    else:
        user_list = "\n".join([f"• `{u}`" for u in users])
        await update.message.reply_text(f"📋 **Allowed Users:**\n{user_list}", parse_mode='Markdown')


def run_telegram_bot(token: str, download_path: str, cookie_path: str, api_base_url: str) -> None:
    """Run the Telegram bot."""
    global snapchat, gallery_dl, cookie_manager, mtproto_client, access_manager
    
    # Initialize components
    # Get Admin ID from environment - REQUIRED for security
    admin_id = os.getenv('ADMIN_USER_ID')
    if not admin_id:
        logging.error("❌ CRITICAL: ADMIN_USER_ID environment variable is not set!")
        logging.error("   The bot cannot run securely without an admin user ID.")
        logging.error("   Please set ADMIN_USER_ID in your .env file:")
        logging.error("   ADMIN_USER_ID=your_telegram_user_id")
        logging.error("   Get your User ID by messaging @userinfobot on Telegram")
        sys.exit(1)
        
    logging.info(f"🔐 Access control enabled for admin: {admin_id[:3]}***{admin_id[-3:]}")
    access_manager = AccessManager(admin_id=admin_id)

    snapchat = SnapchatDownloader(
        api_base_url=api_base_url,
        output_path=download_path
    )
    
    gallery_dl = GalleryDLDownloader(
        output_path=download_path,
        cookie_path=cookie_path,
        admin_id=admin_id  # [NEW] Pass admin ID for shared cookies
    )
    
    cookie_manager = CookieManager(cookie_path=cookie_path)
    
    # Create application with increased timeouts for slow connections
    app = Application.builder().token(token).read_timeout(120).write_timeout(120).build()
    
    # Initialize MTProto client and Download Queue
    async def post_init(application):
        global mtproto_client, download_queue
        
        # Start MTProto lazily to avoid event loop issues in Python 3.12
        if _ensure_mtproto():
            try:
                from auth.mtproto import init_mtproto
                mtproto_client = await init_mtproto()
                
                # Set callbacks for interactive auth (if no session string)
                if mtproto_client:
                    mtproto_client.code_callback = lambda: get_auth_code(application)
                    mtproto_client.password_callback = lambda: get_auth_password(application)
                    
                    if mtproto_client.is_connected:
                        logging.info("📤 MTProto ready for large file uploads (up to 2GB)")
                    else:
                        logging.info("📤 MTProto ready - will authenticate when >50MB file uploaded")
                else:
                    logging.info("ℹ️ MTProto not configured - files >50MB will be skipped")
            except Exception as e:
                logging.warning(f"⚠️ Failed to initialize MTProto: {e}")
        else:
            logging.info("ℹ️ MTProto not available - files >50MB will be skipped")
            
        # Start Download Queue
        logging.info("🚀 Starting download queue workers...")
        download_queue = await init_queue(
            snapchat_downloader=snapchat,
            gallery_dl_downloader=gallery_dl,
            max_concurrent=3,
            max_per_user=2,
            status_callback=lambda job: update_job_status(application, job)
        )
    
    async def post_stop(application):
        global mtproto_client, download_queue
        
        # Stop Download Queue
        if download_queue:
            logging.info("🛑 Stopping download queue...")
            await download_queue.stop()
            
        # Stop MTProto
        if mtproto_client:
            logging.info("📴 Stopping MTProto...")
            await mtproto_client.stop()

    app.post_init = post_init
    app.post_stop = post_stop
    
    # Store download path for cleanup job
    app.bot_data['download_path'] = download_path
    
    # Global error handler for unhandled exceptions
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors and send user-friendly message."""
        logging.error(f"Exception while handling an update:", exc_info=context.error)
        
        # Try to inform the user
        try:
            if update and isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ *Oops! Something went wrong.*\\n\\n"
                    "The error has been logged. Please try again or contact support if the issue persists.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logging.error(f"Failed to send error message to user: {e}")
    
    app.add_error_handler(error_handler)
    
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
    app.add_handler(CommandHandler("upload_cookies", upload_cookies))
    app.add_handler(CommandHandler("my_cookies", list_cookies))
    app.add_handler(CommandHandler("delete_cookies", delete_cookies))
    app.add_handler(CommandHandler("purge", purge_command))
    
    # Admin commands
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("listusers", list_users_command))

    # Note: /queue command available but queue not auto-started
    
    # Callback handler for inline keyboard buttons
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # MTProto auth handler (high priority - intercepts auth codes)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_auth_input
    ), group=-1)  # Higher priority than URL handler
    
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
