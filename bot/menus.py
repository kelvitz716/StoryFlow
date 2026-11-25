"""Menu and keyboard generation for the StoryFlow bot."""
from typing import Optional, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from auth.access import AccessManager
from core.stats import stats_manager

QUALITY_LABELS = {
    'best':  '🔝 Best (default)',
    '1080p': '🎥 1080p',
    '720p':  '📺 720p',
    '480p':  '📱 480p',
    'audio': '🎵 Audio only',
}


def get_cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Inline keyboard with a cancel button for a specific job."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_job_{job_id}")]
    ])

def get_main_menu_keyboard(user_id: Optional[str] = None, access_manager: Optional[AccessManager] = None):
    """Get the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("📖 How to Use", callback_data="menu_help")],
        [InlineKeyboardButton("🍪 Manage Cookies", callback_data="menu_cookies")],
        [InlineKeyboardButton("📊 My Stats", callback_data="menu_stats")],
        [InlineKeyboardButton("🋺 Quality", callback_data="menu_quality")],
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
        "I securely download stories, reels, and videos from:\n"
        "👻 Snapchat • 📸 Instagram • 🎵 TikTok\n"
        "🐦 Twitter/X • 📘 Facebook • 🌐 any other link!\n\n"
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
        "• /start - Main menu panel\n"
        "• /help - Usage guide\n"
        "• /queue - View your current active downloads\n\n"
        "_Tap a platform below for specific tips:_"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👻 Snapchat", callback_data="help_snapchat"),
         InlineKeyboardButton("📸 Instagram", callback_data="help_instagram")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="help_tiktok"),
         InlineKeyboardButton("📘 Facebook", callback_data="help_facebook")],
        [InlineKeyboardButton("🐦 Twitter/X", callback_data="help_twitter")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def send_cookies_menu(target, user_id: str, cookie_manager, is_new_message: bool = False, notice: Optional[str] = None):
    """Send the cookie management menu."""
    cookies = cookie_manager.list_cookies(user_id) if cookie_manager else []
    
    PLATFORM_EMOJI = {
        'instagram': '\U0001f4f8',  # 📸
        'facebook':  '\U0001f4d8',  # 📘
        'tiktok':    '\U0001f3b5',  # 🎵
    }

    if cookies:
        lines = ["\U0001f36a *Your Cookies*\n"]
        for c in cookies:
            emoji = PLATFORM_EMOJI.get(c['platform'], '\U0001f4c4')
            status = "\u26a0\ufe0f Expired" if c.get('is_expired') else "\u2705 Active"
            lines.append(f"{emoji} {c['platform'].title()}: {status}")
            lines.append(f"   \U0001f4c5 {c.get('expiry_str', 'Unknown')}\n")
        text = "\n".join(lines)
    else:
        text = (
            "\U0001f36a *Cookie Manager*\n\n"
            "No cookies saved yet!\n\n"
            "Cookies let you download content that requires login\n"
            "(like Instagram stories or Facebook reels)."
        )
    if notice:
        text = f"{notice}\n\n{text}"
    
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
        [InlineKeyboardButton("🍪 Channel Cookies", callback_data="admin_channel_cookies")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")],
    ])
    
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def send_channel_cookies_menu(target, user_id: str, access_manager: AccessManager, is_new_message: bool = False):
    """Send the channel cookie mapping and admin fallback management menu."""
    if not access_manager.is_admin(user_id):
        return

    from core import cookie_map
    mappings = cookie_map.all_mappings()
    is_fallback = cookie_map.is_admin_fallback_enabled()

    fallback_status = "✅ Enabled" if is_fallback else "❌ Disabled"
    fallback_btn_text = "⚡ Disable Fallback" if is_fallback else "⚡ Enable Fallback"

    text = (
        "🍪 *Channel Cookie Management*\n\n"
        f"⚡ *Global Admin Fallback:* {fallback_status}\n"
        "_(When enabled, all channels and anonymous jobs automatically use the admin's cookies)_\n\n"
    )
    if mappings:
        text += f"*Mapped Channels ({len(mappings)}):*\n"
        for ch, own in mappings.items():
            text += f"• `{ch}` ➔ User `{own}`\n"
    else:
        text += "No specific channel mappings saved yet.\n"

    text += (
        "\n💡 *Quick tip:* When a download fails in a channel, tap the "
        "`[🍪 Link My Cookies]` button on the error message, or send `/mapchannel` in the channel!"
    )

    buttons = [
        [InlineKeyboardButton(fallback_btn_text, callback_data="admin_toggle_cookie_fallback")]
    ]
    for ch in list(mappings.keys())[:5]:
        buttons.append([InlineKeyboardButton(f"🗑️ Unlink {ch}", callback_data=f"admin_unlink_channel_{ch}")])

    buttons.append([InlineKeyboardButton("⬅️ Back to Admin", callback_data="menu_admin")])
    keyboard = InlineKeyboardMarkup(buttons)

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


async def send_quality_menu(target, user_id: str, is_new_message: bool = False):
    """Send or edit the quality selection menu (global default)."""
    from core.user_prefs import get_user_quality, QUALITY_OPTIONS
    current = get_user_quality(user_id)
    lines = ['🎬 *Download Quality*\n', 'Global default for all platforms.\n']
    for key, label in QUALITY_LABELS.items():
        tick = '✅' if key == current else '⬜'
        lines.append(f'{tick} {label}')
    text = '\n'.join(lines)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('🔝 Best',  callback_data='quality_best'),
         InlineKeyboardButton('🎥 1080p', callback_data='quality_1080p')],
        [InlineKeyboardButton('📺 720p',  callback_data='quality_720p'),
         InlineKeyboardButton('📱 480p',  callback_data='quality_480p')],
        [InlineKeyboardButton('🎵 Audio only', callback_data='quality_audio')],
        [InlineKeyboardButton('🔧 Per-Platform Overrides', callback_data='quality_platform_menu')],
        [InlineKeyboardButton('⬅️ Main Menu', callback_data='menu_main')],
    ])
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


# Platforms that support per-platform quality overrides (yt-dlp routed)
PLATFORM_QUALITY_TARGETS = [
    ('XVideos',  '🔞'),
    ('xHamster', '🔞'),
    ('YouTube',  '▶️'),
    ('Twitter',  '🐦'),
    ('Reddit',   '🤖'),
    ('TikTok',   '🎵'),
    ('Instagram','📸'),
    ('Facebook', '📘'),
]


async def send_platform_quality_menu(target, user_id: str, is_new_message: bool = False):
    """Show all per-platform quality overrides and let the user pick one to configure."""
    from core.user_prefs import get_all_platform_overrides
    overrides = get_all_platform_overrides(user_id)

    lines = ['🔧 *Per-Platform Quality*\n',
             'Override quality for specific platforms.\n',
             'Platform-specific setting takes priority over the global default.\n']
    for platform, emoji in PLATFORM_QUALITY_TARGETS:
        q = overrides.get(platform)
        label = QUALITY_LABELS.get(q, q) if q else '_(global default)_'
        lines.append(f'{emoji} *{platform}*: {label}')

    text = '\n'.join(lines)
    buttons = []
    row = []
    for i, (platform, emoji) in enumerate(PLATFORM_QUALITY_TARGETS):
        row.append(InlineKeyboardButton(
            f'{emoji} {platform}', callback_data=f'qplat_pick_{platform}'
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton('⬅️ Quality', callback_data='menu_quality')])

    keyboard = InlineKeyboardMarkup(buttons)
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def send_platform_quality_picker(target, user_id: str, platform: str, is_new_message: bool = False):
    """Quality picker for a specific platform."""
    from core.user_prefs import get_platform_quality
    current = get_platform_quality(user_id, platform)
    emoji = next((e for p, e in PLATFORM_QUALITY_TARGETS if p == platform), '🎬')

    lines = [f'{emoji} *{platform} Quality*\n',
             f'Override quality just for {platform}.\n']
    for key, label in QUALITY_LABELS.items():
        tick = '✅' if key == current else '⬜'
        lines.append(f'{tick} {label}')
    if not current:
        lines.append('✅ _(global default)_')

    text = '\n'.join(lines)
    buttons = [
        [InlineKeyboardButton('🔝 Best',  callback_data=f'qplat_set_{platform}_best'),
         InlineKeyboardButton('🎥 1080p', callback_data=f'qplat_set_{platform}_1080p')],
        [InlineKeyboardButton('📺 720p',  callback_data=f'qplat_set_{platform}_720p'),
         InlineKeyboardButton('📱 480p',  callback_data=f'qplat_set_{platform}_480p')],
        [InlineKeyboardButton('🎵 Audio only', callback_data=f'qplat_set_{platform}_audio')],
        [InlineKeyboardButton('🔄 Use Global Default', callback_data=f'qplat_clear_{platform}')],
        [InlineKeyboardButton('⬅️ Per-Platform', callback_data='quality_platform_menu')],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    if is_new_message:
        await target.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await target.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

