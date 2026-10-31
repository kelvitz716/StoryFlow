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
    is_admin = access_manager.is_admin(user_id)

    if not await require_allowed(update, access_manager):
        return

    if not download_queue:
        await update.message.reply_text("⚠️ Queue is not initialized.")
        return

    # Get active jobs
    stats = download_queue.get_stats()
    active_jobs = stats['active_jobs']

    # Non-admins see only their own jobs, never another user's ID digits.
    if is_admin:
        visible_jobs = active_jobs
        pending = stats['pending']
    else:
        visible_jobs = [j for j in active_jobs if j.user_id == user_id]
        pending = len(visible_jobs)

    msg = (
        f"📊 *Queue Status*\n\n"
        f"🔄 *Active Jobs:* {stats['active']}/{stats['max_concurrent']}\n"
        f"⏳ *Pending in Queue:* {pending}\n"
    )

    if visible_jobs:
        msg += "\n*Current Work:*\n"
        for job in visible_jobs:
            platform_emoji = get_platform_emoji(job.platform)
            if is_admin:
                msg += f"- {platform_emoji} _{str(job.status.value).title()}_ (UID: `{job.user_id[-4:]}`)\n"
            else:
                msg += f"- {platform_emoji} _{str(job.status.value).title()}_\n"

    await update.message.reply_text(msg, parse_mode='Markdown')


async def mapchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager) -> None:
    """Handle /mapchannel command to link a channel to the sender's cookies."""
    if not await require_allowed(update, access_manager):
        return
    user_id = str(update.effective_user.id)
    chat = update.effective_chat
    chat_id = str(chat.id) if chat else ""
    msg = update.effective_message

    from core import cookie_map

    args = context.args if context and context.args else []

    # If argument provided: /mapchannel <target_channel_id>
    if args:
        target_id = args[0].strip()
        if target_id.lstrip('-').isdigit():
            cookie_map.add(target_id, user_id)
            await msg.reply_text(
                f"✅ Channel `{target_id}` is now linked to your cookies!\n"
                f"Any downloads from this channel will use your cookies.",
                parse_mode='Markdown'
            )
            return
        else:
            await msg.reply_text("❌ Invalid ID format. Use: `/mapchannel -1001234567890`", parse_mode='Markdown')
            return

    # If executed inside a channel or group (negative ID)
    if chat_id.startswith('-'):
        cookie_map.add(chat_id, user_id)
        chat_title = chat.title if chat and chat.title else "This channel"
        await msg.reply_text(
            f"✅ *{chat_title}* (`{chat_id}`) has been linked to your cookies!\n"
            f"Future downloads posted here will use your cookies.",
            parse_mode='Markdown'
        )
        return

    # If executed in private chat without arguments:
    # Check if the message is a reply or forward from a channel
    if msg and msg.forward_from_chat and str(msg.forward_from_chat.id).startswith('-'):
        ch_id = str(msg.forward_from_chat.id)
        ch_title = msg.forward_from_chat.title or "Channel"
        cookie_map.add(ch_id, user_id)
        await msg.reply_text(
            f"✅ *{ch_title}* (`{ch_id}`) has been linked to your cookies!\n"
            f"Future downloads posted here or from this channel will use your cookies.",
            parse_mode='Markdown'
        )
        return

    # Show help and current mappings
    mappings = cookie_map.all_mappings()
    is_fallback = cookie_map.is_admin_fallback_enabled()
    lines = [
        "🍪 *Channel Cookie Mapping*\n",
        f"⚡ *Admin Fallback:* {'✅ Enabled (all channels use admin cookies)' if is_fallback else '❌ Disabled'}\n",
    ]
    if mappings:
        lines.append("*Current Mapped Channels:*")
        for ch, own in mappings.items():
            lines.append(f"• `{ch}` ➔ User `{own}`")
        lines.append("")
    lines.append(
        "📌 *How to link a channel:*\n"
        "1. Send `/mapchannel` directly inside the group or channel\n"
        "2. Or forward any message from your channel here and reply with `/mapchannel`\n"
        "3. Or type: `/mapchannel -100xxxxxxxxxx`\n"
        "4. Or manage in `/admin` ➔ *Channel Cookies*"
    )
    await msg.reply_text("\n".join(lines), parse_mode='Markdown')
