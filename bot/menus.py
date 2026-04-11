"""Menu and keyboard generation for the StoryFlow bot."""
from typing import Optional, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from auth.access import AccessManager
from core.stats import stats_manager

def get_main_menu_keyboard(user_id: Optional[str] = None, access_manager: Optional[AccessManager] = None):
    """Get the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("📖 How to Use", callback_data="menu_help")],
        [InlineKeyboardButton("🍪 Manage Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("📊 My Stats", callback_data="menu_stats")],
    ]
    
    if user_id and access_manager and access_manager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("🛠️ Admin Tools", callback_data="menu_admin")])
        
    return InlineKeyboardMarkup(keyboard)

def get_back_button(callback_data: str = "menu_main"):
    """Get a back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=callback_data)]])

async def send_main_menu(target, user_id: str, access_manager: Optional[AccessManager], is_new_message: bool = True):
    """Send or edit the main menu."""
    text = (
        "🎬 *StoryFlow Downloader*\n\n"
        "I can download stories, reels, and videos from:\n"
        "👻 Snapchat • 📸 Instagram • 🎵 TikTok\n"
        "🐦 Twitter/X • 📘 Facebook\n\n"
        "👇 *Tap a button to get started!*"
    )
    keyboard = get_main_menu_keyboard(user_id, access_manager)
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

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

async def send_cookies_menu(target, user_id: str, cookie_manager, is_new_message: bool = False):
    """Send the cookie management menu."""
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
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def send_admin_menu(target, user_id: str, access_manager: AccessManager, is_new_message: bool = False):
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
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def send_delete_cookies_menu(target, is_new_message: bool = False):
    """Send the confirm delete cookies menu."""
    text = "🗑️ *Delete Cookies*\n\nSelect which platform to clear:"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Instagram", callback_data="delete_instagram"),
         InlineKeyboardButton("📘 Facebook", callback_data="delete_facebook")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="delete_tiktok")],
        [InlineKeyboardButton("🔥 Delete All", callback_data="delete_all")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_cookies")],
    ])
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
