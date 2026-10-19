"""Bot command handlers (/start, /help, /queue)."""

from telegram import Update
from telegram.ext import ContextTypes

from auth.access import AccessManager
from bot.menus import send_main_menu, send_help_menu
from bot.guards import require_allowed
from utils.bot_utils import get_platform_emoji


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager) -> None:
    """Handle /start command."""
    if not await require_allowed(update, access_manager):
        return
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    access_manager.register_chat_id(user_id, chat_id)
    await send_main_menu(update.message, user_id, access_manager, is_new_message=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager) -> None:
    """Handle /help command."""
    if not await require_allowed(update, access_manager):
        return
    await send_help_menu(update.message, is_new_message=True)


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager, download_queue) -> None:
    """Check the status of the background queue."""
    user_id = str(update.effective_user.id)
    if not access_manager.is_admin(user_id):
        await update.message.reply_text("❌ You do not have permission to view the queue.")
        return
        
    if not download_queue:
        await update.message.reply_text("⚠️ Queue is not initialized.")
        return
        
    # Get active jobs
    stats = download_queue.get_stats()
    pending = stats['pending']
    active_jobs = stats['active_jobs']
    
    msg = (
        f"📊 *Queue Status*\n\n"
        f"🔄 *Active Jobs:* {stats['active']}/{stats['max_concurrent']}\n"
        f"⏳ *Pending in Queue:* {pending}\n"
    )
    
    if active_jobs:
        msg += "\n*Current Work:*\n"
        for job in active_jobs:
            platform_emoji = get_platform_emoji(job.platform)
            msg += f"- {platform_emoji} _{str(job.status.value).title()}_ (UID: `{job.user_id[-4:]}`)\n"
            
    await update.message.reply_text(msg, parse_mode='Markdown')
