"""Document upload handler for cookie files."""

import os
import tempfile
import logging
from telegram import Update
from telegram.ext import ContextTypes

from auth.access import AccessManager
from auth.cookies import CookieManager
from bot.guards import require_allowed
from bot.menus import send_cookies_menu


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, cookie_manager: CookieManager, access_manager: AccessManager) -> None:
    """Handle document (cookie file) upload."""
    # Access guard (item 6)
    if not await require_allowed(update, access_manager):
        return

    document = update.message.document
    if not document:
        return

    # Silently ignore non-.txt documents (like GIFs, stickers, media files)
    if not document.file_name or not document.file_name.endswith('.txt'):
        return

    user_id = str(update.effective_user.id)

    # Reject oversized or missing file size BEFORE downloading (item 6)
    MAX_COOKIE_BYTES = 256 * 1024  # 256 KB
    if document.file_size is None or document.file_size > MAX_COOKIE_BYTES:
        await update.message.reply_text(
            "❌ Cookie file too large. Maximum size is 256 KB."
        )
        return

    awaiting_platform = context.user_data.get('awaiting_cookies')
    if not awaiting_platform:
        await update.message.reply_text("📎 I wasn't expecting a cookie file. Go to 'Manage Cookies' first.")
        return

    # Clear the awaiting state immediately so re-sending a file works cleanly
    context.user_data.pop('awaiting_cookies', None)
    
    status_msg = await update.message.reply_text(f"⏳ Processing {awaiting_platform.title()} cookies...")
    
    temp_path = None
    try:
        file = await document.get_file()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            temp_path = tf.name

        await file.download_to_drive(temp_path)
        result = cookie_manager.save_cookie_file(user_id, awaiting_platform, temp_path)

        if result['success']:
            expiry = result.get('expiry_str', 'Unknown')
            expired_warning = "\n⚠️ _This cookie is already expired!_" if result.get('is_expired') else ""
            msg = f"✅ *{awaiting_platform.title()} Cookies Saved!*\nValid until: {expiry}{expired_warning}"
            await status_msg.edit_text(msg, parse_mode='Markdown')
        else:
            await status_msg.edit_text(f"❌ Failed: {result.get('error')}")
    except Exception as e:
        logging.error(f"Error handling cookie file: {e}")
        await status_msg.edit_text("⚠️ An error occurred while processing the cookie file.")
    finally:
        # Always clean up temp file, even on error
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    # Return user to the cookies menu so they can see updated status
    await send_cookies_menu(update.message, user_id, cookie_manager, is_new_message=True)
