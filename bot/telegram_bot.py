"""
Main entry point for the StoryFlow Telegram bot.
Integrates handlers, menus, and uploader modules for a modular architecture.
"""
import os
import sys
import logging
import asyncio
import time
import random
from typing import Optional

from telegram import Update, Document, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    TypeHandler,
    filters,
    ContextTypes
)

# Core imports
from core.queue import DownloadQueue, DownloadJob, JobStatus, init_queue, get_queue
from downloaders.snapchat import SnapchatDownloader
from downloaders.gallery_dl import GalleryDLDownloader
from auth.cookies import CookieManager
from auth.access import AccessManager
from core.stats import stats_manager

# Bot module imports [NEW]
from bot.menus import (
    send_main_menu, send_help_menu, send_cookies_menu, 
    send_admin_menu, send_delete_cookies_menu, get_back_button
)
from bot.handlers import (
    handle_url, start, help_command, handle_document,
    handle_auth_input, get_auth_code, get_auth_password
)
from bot.uploader import batch_upload_media
from utils.bot_utils import format_error_message, get_platform_emoji, escape_markdown, JOB_MESSAGES

# Global Components
snapchat: Optional[SnapchatDownloader] = None
gallery_dl: Optional[GalleryDLDownloader] = None
cookie_manager: Optional[CookieManager] = None
access_manager: Optional[AccessManager] = None
mtproto_client: Optional[any] = None
download_queue: Optional[DownloadQueue] = None

# MTProto Auth State (Shared with handlers)
AUTH_PENDING = None
AUTH_TYPE = None
AUTH_ADMIN_ID = None

# ============= UI UPDATES & CALLBACKS =============

async def update_job_status(application: Application, job: DownloadJob):
    """Callback for queue status updates, using the application bot context."""
    status_msg = JOB_MESSAGES.get(job.job_id)
    if not status_msg:
        return

    try:
        emoji = get_platform_emoji(job.platform)
        
        if job.status == JobStatus.QUEUED:
            pos = get_queue().get_queue_position(job.job_id)
            await status_msg.edit_text(
                f"⏳ *Queued* (Position: {pos})\nWaiting for available worker...", 
                parse_mode='Markdown'
            )
            
        elif job.status == JobStatus.DOWNLOADING:
            # Escape the message for safe Markdown rendering
            msg = escape_markdown(job.message)
            await status_msg.edit_text(f"⬇️ *Downloading...*\n{emoji} {msg}", parse_mode='Markdown')
            
        elif job.status == JobStatus.UPLOADING:
            # Batch upload handles its own status updates
            pass
            
        elif job.status == JobStatus.COMPLETED:
            stats_manager.increment_download(job.user_id, job.platform)
            JOB_MESSAGES.pop(job.job_id, None)
                
        elif job.status == JobStatus.FAILED:
            error_text = format_error_message(job.error or "Unknown failure", job.platform)
            await status_msg.edit_text(error_text, parse_mode='Markdown')
            JOB_MESSAGES.pop(job.job_id, None)
                
    except Exception as e:
        logging.error(f"Failed to update status message for job {job.job_id}: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    data = query.data
    
    # Navigation
    if data == "menu_main":
        await send_main_menu(query, user_id, access_manager, is_new_message=False)
    elif data == "menu_help":
        await send_help_menu(query, is_new_message=False)
    elif data == "menu_cookies":
        await send_cookies_menu(query, user_id, cookie_manager, is_new_message=False)
    elif data == "menu_stats":
        stats = stats_manager.get_user_stats(user_id)
        total = stats.get('total_downloads', 0)
        platforms = stats.get('platforms', {})
        breakdown = "\n".join([f"• {p}: {c}" for p, c in platforms.items()]) if platforms else "No downloads yet!"
        text = f"📊 *Your Statistics*\n\n📥 *Total Downloads:* {total}\n\n*Platform Breakdown:*\n{breakdown}"
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_back_button())
    
    # Admin
    elif data == "menu_admin":
        await send_admin_menu(query, user_id, access_manager, is_new_message=False)
    elif data == "admin_list":
        users = access_manager.get_allowed_users()
        user_list = "\n".join([f"• `{u}`" for u in users]) if users else "_No users allowed (only Admins)_"
        await query.edit_message_text(f"📋 *Allowed Users:*\n\n{user_list}", parse_mode='Markdown', reply_markup=get_back_button("menu_admin"))
    elif data == "admin_add":
        context.user_data['awaiting_action'] = 'add_user'
        await query.edit_message_text("➕ *Add User*\n\nSend the Telegram ID to authorize.", parse_mode='Markdown', reply_markup=get_back_button("menu_admin"))
    elif data == "admin_remove":
        context.user_data['awaiting_action'] = 'remove_user'
        await query.edit_message_text("➖ *Remove User*\n\nSend the Telegram ID to remove.", parse_mode='Markdown', reply_markup=get_back_button("menu_admin"))
    
    # Cookie Management
    elif data == "menu_delete_cookies":
        await send_delete_cookies_menu(query, is_new_message=False)
    elif data.startswith("delete_"):
        platform = data.replace("delete_", "")
        if platform == "all":
            cookie_manager.delete_cookie_file(user_id, "instagram")
            cookie_manager.delete_cookie_file(user_id, "facebook")
            cookie_manager.delete_cookie_file(user_id, "tiktok")
            text = "✅ All cookies deleted!"
        else:
            cookie_manager.delete_cookie_file(user_id, platform)
            text = f"✅ {platform.title()} cookies deleted!"
        await query.edit_message_text(text, reply_markup=get_back_button("menu_cookies"))
    
    elif data.startswith("cookies_"):
        platform = data.replace("cookies_", "")
        context.user_data['awaiting_cookies'] = platform
        text = f"🍪 *Add {platform.title()} Cookies*\n\nPlease upload your `cookies.txt` file."
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_back_button("menu_cookies"))

    # Help Platform Tips
    elif data.startswith("help_"):
        platform = data.replace("help_", "")
        tips = {
            "snapchat": "👻 *Snapchat Tips*\n\nJust send a profile link!",
            "instagram": "📸 *Instagram Tips*\n\nPosts are public, Stories need cookies.",
            "tiktok": "🎵 *TikTok Tips*\n\nNo-watermark downloads supported!",
            "facebook": "📘 *Facebook Tips*\n\nReels often require cookies.",
            "twitter": "🐦 *Twitter/X Tips*\n\nNo cookies required usually."
        }
        await query.edit_message_text(tips.get(platform, "No tips available."), parse_mode='Markdown', reply_markup=get_back_button("menu_help"))

# ============= INFRASTRUCTURE & BOOTSTRAP =============

async def cleanup_job_task(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resilient cleanup task for old media folders."""
    download_path = context.bot_data.get('download_path')
    if not download_path: return
    
    logging.info("🧹 Starting background storage cleanup...")
    # This logic is now mostly handled by job-specific cleanup in queue.py,
    # but we can keep a general sweep for safety.
    pass

def run_telegram_bot(token: str, download_path: str, cookie_path: str, api_base_url: str) -> None:
    """Initialize and run the StoryFlow Telegram bot."""
    global snapchat, gallery_dl, cookie_manager, mtproto_client, access_manager
    
    admin_id = os.getenv('ADMIN_USER_ID')
    if not admin_id:
        logging.error("❌ ADMIN_USER_ID not set!")
        sys.exit(1)
        
    access_manager = AccessManager(admin_id=admin_id)
    cookie_manager = CookieManager(cookie_path=cookie_path)
    
    # Initialize Downloaders
    snapchat = SnapchatDownloader(api_base_url=api_base_url, output_path=download_path)
    gallery_dl = GalleryDLDownloader(output_path=download_path, cookie_path=cookie_path, admin_id=admin_id)
    
    app = Application.builder().token(token).read_timeout(60).write_timeout(60).build()
    
    async def post_init(application):
        global mtproto_client, download_queue
        # MTProto client init
        try:
            from auth.mtproto import init_mtproto
            mtproto_client = await init_mtproto()
            # Set callbacks for interactive auth (if no session string)
            if mtproto_client:
                mtproto_client.code_callback = lambda: get_auth_code(application, access_manager)
                mtproto_client.password_callback = lambda: get_auth_password(application, access_manager)
        except Exception as e:
            logging.warning(f"MTProto init failed: {e}")
            
        # Queue init
        download_queue = await init_queue(
            snapchat_downloader=snapchat,
            gallery_dl_downloader=gallery_dl,
            status_callback=lambda job: update_job_status(application, job)
        )
    
    async def post_stop(application):
        if download_queue: await download_queue.stop()
        if mtproto_client: await mtproto_client.stop()

    app.post_init = post_init
    app.post_stop = post_stop
    app.bot_data['download_path'] = download_path
    
    # Handlers
    from bot.handlers import queue_command
    app.add_handler(CommandHandler("start", lambda u, c: start(u, c, access_manager)))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("queue", lambda u, c: queue_command(u, c, access_manager, download_queue)))
    
    # Callback Query
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # MTProto Auth Interceptor
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_input), group=-1)

    # Document handler for cookie uploads
    app.add_handler(MessageHandler(filters.Document.ALL, lambda u, c: handle_document(u, c, cookie_manager)))
    
    # URL Handler
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^https?://'),
        lambda u, c: handle_url(u, c, access_manager, download_queue, mtproto_client)
    ))
    
    # Cleanup Task
    if app.job_queue:
        app.job_queue.run_repeating(cleanup_job_task, interval=86400, first=10)
    
    logging.info("🤖 StoryFlow Bot started!")
    app.run_polling()
