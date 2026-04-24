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
        # Clear any pending admin actions when returning to main menu
        context.user_data.pop('awaiting_action', None)
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
    
    # Admin — all branches below require admin access
    elif data == "menu_admin":
        # Clear any dangling awaiting_action when re-entering admin menu
        context.user_data.pop('awaiting_action', None)
        await send_admin_menu(query, user_id, access_manager, is_new_message=False)
    elif data == "admin_list":
        if not access_manager.is_admin(user_id):
            await query.edit_message_text("⛔ Admin only.", reply_markup=get_back_button())
            return
        users = access_manager.get_allowed_users()
        user_list = "\n".join([f"• `{u}`" for u in users]) if users else "_No users allowed (only Admin)_"
        await query.edit_message_text(f"📋 *Allowed Users:*\n\n{user_list}", parse_mode='Markdown', reply_markup=get_back_button("menu_admin"))
    elif data == "admin_add":
        if not access_manager.is_admin(user_id):
            await query.edit_message_text("⛔ Admin only.", reply_markup=get_back_button())
            return
        context.user_data['awaiting_action'] = 'add_user'
        await query.edit_message_text(
            "➕ *Add User / Channel*\n\nReply with the Telegram ID to authorize.\n"
            "_Tip: IDs can be negative (e.g. `-1001234567890` for a channel)._",
            parse_mode='Markdown',
            reply_markup=get_back_button("menu_admin")
        )
    elif data == "admin_remove":
        if not access_manager.is_admin(user_id):
            await query.edit_message_text("⛔ Admin only.", reply_markup=get_back_button())
            return
        context.user_data['awaiting_action'] = 'remove_user'
        await query.edit_message_text(
            "➖ *Remove User / Channel*\n\nReply with the Telegram ID to remove.",
            parse_mode='Markdown',
            reply_markup=get_back_button("menu_admin")
        )

    # Purge flow — admin only, requires confirmation
    elif data == "menu_purge_confirm":
        if not access_manager.is_admin(user_id):
            await query.edit_message_text("⛔ Admin only.", reply_markup=get_back_button())
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Yes, purge everything", callback_data="purge_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_admin")],
        ])
        await query.edit_message_text(
            "⚠️ *System Purge*\n\n"
            "This will delete *all* files in the downloads directory.\n"
            "Active downloads will not be interrupted, but their output may be lost.\n\n"
            "Are you sure?",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    elif data == "purge_confirm":
        if not access_manager.is_admin(user_id):
            await query.edit_message_text("⛔ Admin only.", reply_markup=get_back_button())
            return
        download_path = None
        if download_queue:
            # Grab path from queue's downloader config
            try:
                download_path = download_queue.snapchat.output_path
            except AttributeError:
                pass
        if not download_path:
            import os
            download_path = os.getenv('DOWNLOAD_PATH', '/app/downloads')
        try:
            import shutil, os
            removed = 0
            if os.path.isdir(download_path):
                for entry in os.scandir(download_path):
                    if entry.is_dir():
                        shutil.rmtree(entry.path, ignore_errors=True)
                        removed += 1
                    else:
                        os.remove(entry.path)
                        removed += 1
            logging.info(f"🔥 Admin purge: removed {removed} items from {download_path}")
            await query.edit_message_text(
                f"✅ *Purge Complete*\n\nRemoved `{removed}` items from the downloads directory.",
                parse_mode='Markdown',
                reply_markup=get_back_button("menu_admin")
            )
        except Exception as e:
            logging.error(f"Purge failed: {e}")
            await query.edit_message_text(
                f"❌ Purge failed: `{e}`",
                parse_mode='Markdown',
                reply_markup=get_back_button("menu_admin")
            )

    # Cookie Management
    elif data == "menu_delete_cookies":
        await send_delete_cookies_menu(query, is_new_message=False)
    elif data.startswith("delete_"):
        platform = data.replace("delete_", "")
        if platform == "all":
            deleted = sum([
                cookie_manager.delete_cookie_file(user_id, "instagram"),
                cookie_manager.delete_cookie_file(user_id, "facebook"),
                cookie_manager.delete_cookie_file(user_id, "tiktok"),
            ])
            notice = f"✅ Deleted {deleted} cookie file(s)." if deleted else "ℹ️ No cookies were saved."
        else:
            was_deleted = cookie_manager.delete_cookie_file(user_id, platform)
            notice = f"✅ {platform.title()} cookies deleted." if was_deleted else f"ℹ️ No {platform.title()} cookies were saved."
        # Edit to show result briefly, then re-render the full cookies menu
        await query.edit_message_text(notice)
        await send_cookies_menu(query, user_id, cookie_manager, is_new_message=False)
    
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
    from bot.handlers import queue_command, handle_admin_input
    app.add_handler(CommandHandler("start", lambda u, c: start(u, c, access_manager)))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("queue", lambda u, c: queue_command(u, c, access_manager, download_queue)))
    
    # Callback Query
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # MTProto Auth Interceptor (highest priority, group -1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_input), group=-1)

    # Admin text input handler: catches any plain text when admin has a pending action.
    # Runs in group 0 before the URL handler so bare IDs/numbers are handled correctly.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: handle_admin_input(u, c, access_manager)
    ), group=0)

    # Document handler for cookie uploads
    app.add_handler(MessageHandler(filters.Document.ALL, lambda u, c: handle_document(u, c, cookie_manager)))
    
    # URL Handler (group 1 so admin handler gets first crack at group 0)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^https?://'),
        lambda u, c: handle_url(u, c, access_manager, download_queue, mtproto_client)
    ), group=1)
    
    logging.info("🤖 StoryFlow Bot started!")
    app.run_polling()
