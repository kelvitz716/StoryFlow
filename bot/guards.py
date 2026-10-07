"""
Reusable access-control guard for StoryFlow bot handlers (item 6).

Usage (in handlers / callbacks):
    from bot.guards import require_allowed

    async def my_handler(update, context, access_manager):
        if not await require_allowed(update, access_manager):
            return
        ...  # only reached for allowed users
"""
import logging
from telegram import Update
from auth.access import AccessManager


async def require_allowed(update: Update, access_manager: AccessManager) -> bool:
    """
    Check whether the sender of this update is allowed to use the bot.

    Behaviour:
    - Allowed users (including admins): returns True, caller proceeds normally.
    - Disallowed users in a private chat: sends a short rejection message,
      returns False.
    - Disallowed users in a group/channel: silently ignores (returns False
      with no message), to avoid spamming shared chats.

    Args:
        update: Incoming Telegram update.
        access_manager: AccessManager instance.

    Returns:
        True if the user is allowed, False otherwise.
    """
    if update.effective_user is None:
        return False

    user_id = str(update.effective_user.id)

    if access_manager.is_allowed(user_id) or access_manager.is_admin(user_id):
        return True

    # Determine chat type for the rejection strategy
    chat = update.effective_chat
    is_private = chat is not None and chat.type == "private"

    if is_private:
        msg = update.effective_message
        if msg:
            try:
                await msg.reply_text(
                    f"⛔ You are not authorised to use this bot.\n"
                    f"Ask the admin to add your ID: `{user_id}`",
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logging.debug(f"require_allowed: could not send rejection: {exc}")
    # Groups: silent ignore — no reply to avoid spam

    return False
