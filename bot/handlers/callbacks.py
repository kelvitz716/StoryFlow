"""Inline keyboard callback query handler."""

import os
import shutil
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from auth.access import AccessManager
from auth.cookies import CookieManager
from core.stats import StatsManager
from bot.guards import require_allowed
from bot.menus import (
    send_main_menu,
    send_help_menu,
    send_admin_menu,
    send_cookies_menu,
    send_delete_cookies_menu,
    get_back_button
)


async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    access_manager: AccessManager,
    cookie_manager: CookieManager,
    stats_manager: StatsManager,
    download_queue=None
) -> None:
    """Handle all inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()

    # Access guard — unauthorized users get no response from any button branch
    if not await require_allowed(update, access_manager):
        return

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
            download_path = os.getenv('DOWNLOAD_PATH', '/app/downloads')
        try:
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
