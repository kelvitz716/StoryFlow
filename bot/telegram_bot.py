"""
Main entry point for the StoryFlow Telegram bot.
Integrates handlers, menus, and uploader modules for a modular architecture.
"""
import os
import sys
import logging
from typing import Optional

from telegram import Update
from telegram.error import RetryAfter, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

from bot.handlers import (
    handle_url, start, help_command, handle_document,
    handle_auth_input, get_auth_code, get_auth_password,
    record_backlog_job_outcome
)
from utils.bot_utils import format_error_message, get_platform_emoji, escape_markdown, JOB_MESSAGES, pop_job_message
from core.database import db
from core.migrations import run_migrations
# Global Components
snapchat: Optional[SnapchatDownloader] = None
gallery_dl: Optional[GalleryDLDownloader] = None
cookie_manager: Optional[CookieManager] = None
access_manager: Optional[AccessManager] = None
mtproto_client: Optional[any] = None
download_queue: Optional[DownloadQueue] = None

# MTProto Auth State (Shared with handlers)

from bot.edit_gate import request_edit

# ============= UI UPDATES & CALLBACKS =============

async def update_job_status(application: Application, job: DownloadJob):
    """Callback for queue status updates, using the application bot context."""
    status_msg = JOB_MESSAGES.get(job.job_id)
    if not status_msg:
        if job.status == JobStatus.COMPLETED:
            stats_manager.increment_download(job.user_id, job.platform)
            pop_job_message(job.job_id)
            record_backlog_job_outcome(job)
        elif job.status == JobStatus.FAILED:
            pop_job_message(job.job_id)
            record_backlog_job_outcome(job)
        return

    try:
        emoji = get_platform_emoji(job.platform)
        
        if job.status == JobStatus.QUEUED:
            pos = get_queue().get_queue_position(job.job_id)
            request_edit(
                status_msg,
                f"⏳ *Queued* (Position: {pos})\nWaiting for available worker...", 
                parse_mode='Markdown',
                terminal=False
            )
            
        elif job.status == JobStatus.DOWNLOADING:
            # Escape the message for safe Markdown rendering
            msg = escape_markdown(job.message, version=1)
            request_edit(
                status_msg,
                f"⬇️ *Downloading...*\n{emoji} {msg}",
                parse_mode='Markdown',
                terminal=False
            )
            
        elif job.status == JobStatus.UPLOADING:
            # Batch upload handles its own status updates
            pass
            
        elif job.status == JobStatus.COMPLETED:
            stats_manager.increment_download(job.user_id, job.platform)
            pop_job_message(job.job_id)
                
        elif job.status == JobStatus.FAILED:
            error_text = format_error_message(job.error or "Unknown failure", job.platform)
            request_edit(
                status_msg,
                error_text,
                parse_mode='Markdown',
                terminal=True
            )
            pop_job_message(job.job_id)
                
    except Exception as e:
        logging.error(f"Failed to update status message for job {job.job_id}: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all inline keyboard button callbacks."""
    from bot.handlers.callbacks import button_callback as _handle_callback
    await _handle_callback(
        update=update,
        context=context,
        access_manager=access_manager,
        cookie_manager=cookie_manager,
        stats_manager=stats_manager,
        download_queue=download_queue
    )

# ============= INFRASTRUCTURE & BOOTSTRAP =============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Application-level error handler (item 3).

    Logs one concise line for RetryAfter / NetworkError / TimedOut errors so that
    Termux does not receive five-line tracebacks per flood-control hit.  All other
    exceptions get a full traceback so real bugs are not silently swallowed.
    """
    exc = context.error
    if isinstance(exc, RetryAfter):
        logging.warning(f"Telegram RetryAfter({exc.retry_after}s) — update skipped.")
    elif isinstance(exc, (NetworkError, TimedOut)):
        logging.warning(f"Telegram transient error ({type(exc).__name__}): {exc}")
    else:
        logging.exception(f"Unhandled exception in update handler: {exc}", exc_info=exc)


def run_telegram_bot(token: str, download_path: str, cookie_path: str) -> None:
    """Initialize and run the StoryFlow Telegram bot."""
    global snapchat, gallery_dl, cookie_manager, access_manager

    # Silence libraries that log the bot token in request URLs (item 7)
    import logging as _logging
    _logging.getLogger("httpx").setLevel(_logging.WARNING)
    _logging.getLogger("httpcore").setLevel(_logging.WARNING)

    admin_id = os.getenv('ADMIN_USER_ID')
    if not admin_id:
        logging.error("❌ ADMIN_USER_ID not set!")
        sys.exit(1)
        
    # Run DB migrations BEFORE AccessManager checks state
    run_migrations(db)
        
    access_manager = AccessManager(admin_id=admin_id)
    cookie_manager = CookieManager(cookie_path=cookie_path)
    
    # Initialize Downloaders
    snapchat = SnapchatDownloader(output_path=download_path)
    gallery_dl = GalleryDLDownloader(output_path=download_path, cookie_path=cookie_path, admin_id=admin_id)
    
    app = Application.builder().token(token).read_timeout(60).write_timeout(60).build()
    
    async def post_init(application):
        global mtproto_client, download_queue
        # MTProto client init (item 9: ImportError is non-fatal)
        try:
            from auth.mtproto import init_mtproto
            mtproto_client = await init_mtproto()
            # Set callbacks for interactive auth (if no session string)
            if mtproto_client:
                mtproto_client.code_callback = lambda: get_auth_code(application, access_manager)
                mtproto_client.password_callback = lambda: get_auth_password(application, access_manager)
        except ImportError:
            logging.warning(
                "MTProto (Pyrogram/TgCrypto) is unavailable — "
                "files >50 MB will fall back to the Bot API 50 MB limit."
            )
        except Exception as e:
            logging.warning(f"MTProto init failed: {e}")
            
        # Queue init
        download_queue = await init_queue(
            snapchat_downloader=snapchat,
            gallery_dl_downloader=gallery_dl,
            status_callback=lambda job: update_job_status(application, job)
        )
        
        # Recover orphaned jobs from previous crash
        await download_queue.recover_orphaned_jobs(application.bot)
    
    async def post_stop(application):
        if download_queue: await download_queue.stop()
        if mtproto_client: await mtproto_client.stop()

    app.post_init = post_init
    app.post_stop = post_stop
    app.bot_data['download_path'] = download_path
    
    # Handlers
    from bot.handlers import queue_command, handle_admin_input
    app.add_handler(CommandHandler("start", lambda u, c: start(u, c, access_manager)))
    app.add_handler(CommandHandler("help", lambda u, c: help_command(u, c, access_manager)))
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
    app.add_handler(MessageHandler(filters.Document.ALL, lambda u, c: handle_document(u, c, cookie_manager, access_manager)))
    
    # URL Handler (group 1 so admin handler gets first crack at group 0)
    # Matches any message containing an http/https URL (not just messages starting with one)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'https?://'),
        lambda u, c: handle_url(u, c, access_manager, download_queue, mtproto_client)
    ), group=1)
    
    # Error handler (item 3)
    app.add_error_handler(error_handler)

    logging.info("🤖 StoryFlow Bot started!")
    app.run_polling()
