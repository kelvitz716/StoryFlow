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
    Check whether the sender/chat of this update is allowed to use the bot.

    Behaviour:
    - Allowed users/channels/groups: returns True, caller proceeds normally.
    - Disallowed users in a private chat: sends a short rejection message,
      returns False.
    - Disallowed users in a group/channel: silently ignores (returns False
      with no message), to avoid spamming shared chats.

    Args:
        update: Incoming Telegram update.
        access_manager: AccessManager instance.

    Returns:
        True if the user/chat is allowed, False otherwise.
    """
    msg = update.effective_message

    # Collect all possible candidate IDs for access authorization
    candidate_ids = []

    if msg and msg.is_automatic_forward and msg.sender_chat:
        candidate_ids.append(str(msg.sender_chat.id))

    if update.effective_user:
        raw_uid = str(update.effective_user.id)
        if not access_manager.is_system_sender(raw_uid):
            candidate_ids.append(raw_uid)

    if update.effective_chat:
        candidate_ids.append(str(update.effective_chat.id))

    if msg and msg.sender_chat:
        candidate_ids.append(str(msg.sender_chat.id))

    for uid in candidate_ids:
        if access_manager.is_allowed(uid) or access_manager.is_admin(uid):
            return True

    # Determine chat type for the rejection strategy
    chat = update.effective_chat
    is_private = chat is not None and chat.type == "private"

    if is_private and update.effective_user:
        user_id = str(update.effective_user.id)
        if msg:
            try:
                await msg.reply_text(
                    f"⛔ You are not authorised to use this bot.\n"
                    f"Ask the admin to add your ID: `{user_id}`",
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logging.debug(f"require_allowed: could not send rejection: {exc}")
    # Groups/Channels: silent ignore — no reply to avoid spam

    return False
