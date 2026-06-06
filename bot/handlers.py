"""Command and message handlers for StoryFlow bot."""
import logging
import random
import os
import tempfile
import re
from typing import Optional
from telegram import Update, Document
from telegram.ext import ContextTypes, Application

from core.platform import identify_platform
from auth.access import AccessManager
from auth.cookies import CookieManager  # [NEW]
from bot.menus import send_main_menu, send_help_menu, send_admin_menu, send_cookies_menu, send_delete_cookies_menu
from bot.uploader import batch_upload_media
from utils.bot_utils import format_error_message, get_platform_emoji, escape_markdown, register_job_message, resolve_shortlink
import asyncio
import time

PROCESSING_MSGS = [
    "🔍 Checking URL...",
    "🧐 Analyzing link...",
    "💾 Processing request...",
    "⚡ One moment please..."
]

# MTProto Auth state (mapped in main bot)
AUTH_PENDING = None
AUTH_TYPE = None
AUTH_ADMIN_ID = None



async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                     access_manager: AccessManager, download_queue,
                     mtproto_client=None) -> None:
    """Handle URL message."""
    if not update.effective_message or not update.effective_message.text:
        return

    # Skip channel_post update (handle via forwarded group message)
    if update.channel_post is not None:
        return

    url_text = update.effective_message.text.strip()
    msg = update.effective_message
    
    # Clear any ghosted UI states when the user explicitly sends a new URL
    context.user_data.pop('awaiting_cookies', None)

    # Resolve sender identity
    raw_user_id = str(update.effective_user.id) if update.effective_user else None
    
    if msg.is_automatic_forward and msg.sender_chat:
        user_id = str(msg.sender_chat.id)
    elif raw_user_id is not None and access_manager.is_system_sender(raw_user_id):
        return
    elif raw_user_id is None or access_manager.is_anonymous_sender(raw_user_id):
        user_id = str(update.effective_chat.id)
    else:
        user_id = raw_user_id

    if not access_manager.is_allowed(user_id):
        if not access_manager.is_admin(user_id):
            await msg.reply_text(
                f"⛔ Not authorized.\n"
                f"Ask the admin to authorize your ID: `{user_id}`",
                parse_mode='Markdown'
            )
            return

    # ── URL extraction ────────────────────────────────────────────────────
    # Handle all cases: bare URLs, URLs embedded in text, comma/space/newline
    # separated lists, and URLs forwarded with trailing punctuation.
    #
    # Step 1: insert a space before every "http" so comma-joined URLs are split
    spaced_text = url_text.replace('http', ' http')
    # Step 2: extract everything that looks like a URL
    raw_urls = re.findall(r'https?://[^\s]+', spaced_text)

    def _clean_url(u: str) -> str:
        """
        Strip trailing punctuation from a URL, but preserve bracket characters
        that are balanced within the URL (e.g. Wikipedia-style /wiki/A_(film)).

        Rules:
          - Always strip trailing: . , ! ? ; : \' \" > ‼ … › «
          - Strip trailing ) only if '(' count < ')' count in URL (unbalanced)
          - Strip trailing ] only if '[' count < ']' count in URL (unbalanced)
        """
        # Always-strip set (cannot appear as valid URL-tail in practice)
        _ALWAYS = set('.,!?;:\'"›«>‼…')
        while u:
            ch = u[-1]
            if ch in _ALWAYS:
                u = u[:-1]
            elif ch == ')' and u.count('(') < u.count(')'):
                u = u[:-1]
            elif ch == ']' and u.count('[') < u.count(']'):
                u = u[:-1]
            else:
                break
        return u

    # Step 3: clean and deduplicate
    urls = []
    for u in raw_urls:
        clean_u = _clean_url(u)
        if clean_u and clean_u not in urls:
            urls.append(clean_u)

    if not urls:
        # No URLs found at all — message passed the filter but has no extractable URL
        # (e.g. plain text admin input). Don't process it.
        return

    if len(urls) > 10:
        await msg.reply_text("⚠️ You can only queue up to 10 links at a time. Processing the first 10...")
        urls = urls[:10]

    for raw_url in urls:
        # Resolve any shortlinks first
        url = await resolve_shortlink(raw_url)

        # Identify platform
        platform = identify_platform(url)
        if platform == "Unknown":
            await msg.reply_text(
                f"❌ *Invalid Link*\n\n`{raw_url}`\n"
                "Please enter a valid, public HTTP or HTTPS link.",
                parse_mode='Markdown'
            )
            continue
        
        # Process download
        proc_msg = random.choice(PROCESSING_MSGS)
        status_msg = await msg.reply_text(f"{proc_msg}")
        
        def make_upload_func(sm):
            async def upload_func(files):
                await batch_upload_media(update, files, sm, mtproto_client)
            return upload_func

        if download_queue:
            job = await download_queue.submit(
                user_id=user_id,
                url=url,
                platform=platform,
                upload_func=make_upload_func(status_msg),
                chat_id=str(update.effective_chat.id),
                message_id=msg.message_id
            )
            
            if job:
                register_job_message(job.job_id, status_msg)
                pos = download_queue.get_queue_position(job.job_id)
                if pos > 0:
                     await status_msg.edit_text(f"⏳ *Queued* (Position: {pos})\\nWaiting for worker...", parse_mode='Markdown')
            else:
                await status_msg.edit_text("⚠️ *Queue Full*\\nPlease wait for your active downloads to finish.")
        else:
            await status_msg.edit_text("⚠️ System Error: Queue not active.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager) -> None:
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    access_manager.register_chat_id(user_id, chat_id)
    await send_main_menu(update.message, user_id, access_manager, is_new_message=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             access_manager: AccessManager) -> None:
    """Handle plain-text admin input for add/remove user actions.
    
    Runs in handler group 0 (before the URL handler) so bare numeric IDs
    like `-1003589434674` are processed correctly without needing https://.
    Returns immediately if no admin action is pending, allowing other handlers to run.
    """
    if not update.effective_message or not update.effective_message.text:
        return
    if not update.effective_user:
        return

    user_id = str(update.effective_user.id)

    # Only act if this is the admin with a pending action
    if not access_manager.is_admin(user_id):
        return
    action = context.user_data.get('awaiting_action') if context.user_data is not None else None
    if not action:
        return

    target_id = update.effective_message.text.strip()
    msg = update.effective_message

    if action == 'add_user':
        # Accept plain integers and negative IDs (channels start with -)
        if target_id.lstrip('-').isdigit():
            if access_manager.add_user(target_id):
                response = f"✅ `{target_id}` added to the allowed list."
            else:
                response = f"⚠️ `{target_id}` is already allowed."
        else:
            response = "❌ Invalid ID format. Send a numeric Telegram ID (e.g. `618026357` or `-1001234567890`)."
            await msg.reply_text(response, parse_mode='Markdown')
            return  # Don't clear state — let admin try again

    elif action == 'remove_user':
        if access_manager.remove_user(target_id):
            response = f"✅ `{target_id}` removed from the allowed list."
        else:
            response = f"⚠️ `{target_id}` was not in the allowed list."
    else:
        return

    context.user_data.pop('awaiting_action', None)
    await msg.reply_text(response, parse_mode='Markdown')
    # Send fresh admin menu so the admin can continue managing users
    await send_admin_menu(msg, user_id, access_manager, is_new_message=True)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, cookie_manager: CookieManager) -> None:
    """Handle document (cookie file) upload."""
    document: Document = update.message.document
    user_id = str(update.effective_user.id)
    
    awaiting_platform = context.user_data.get('awaiting_cookies')
    if not awaiting_platform:
        # Silently ignore non-.txt documents (like media files uploaded by MTProto)
        if not document.file_name or not document.file_name.endswith('.txt'):
            return
            
        await update.message.reply_text("📎 I wasn't expecting a cookie file. Go to 'Manage Cookies' first.")
        return
    
    # Clear the awaiting state immediately so re-sending a file works cleanly
    context.user_data.pop('awaiting_cookies', None)
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file.")
        return
    
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
        await status_msg.edit_text(f"⚠️ Error: {str(e)}")
    finally:
        # Always clean up temp file, even on error
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    # Return user to the cookies menu so they can see updated status
    await send_cookies_menu(update.message, user_id, cookie_manager, is_new_message=True)



async def get_auth_code(application: Application, access_manager: AccessManager) -> str:
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    admin_id = access_manager.admin_id
    AUTH_ADMIN_ID = admin_id
    AUTH_PENDING = asyncio.Future()
    AUTH_TYPE = 'code'
    
    await application.bot.send_message(chat_id=int(admin_id), text="📲 *MTProto Code Required*\nPlease send the 5-6 digit code.", parse_mode='Markdown')
    try:
        return await asyncio.wait_for(AUTH_PENDING, timeout=180)
    finally:
        AUTH_PENDING = AUTH_TYPE = AUTH_ADMIN_ID = None

async def get_auth_password(application: Application, access_manager: AccessManager) -> str:
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    admin_id = access_manager.admin_id
    AUTH_ADMIN_ID = admin_id
    AUTH_PENDING = asyncio.Future()
    AUTH_TYPE = 'password'
    
    await application.bot.send_message(chat_id=int(admin_id), text="🔐 *2FA Password Required*\nPlease send your password.", parse_mode='Markdown')
    try:
        return await asyncio.wait_for(AUTH_PENDING, timeout=180)
    finally:
        AUTH_PENDING = AUTH_TYPE = AUTH_ADMIN_ID = None

async def handle_auth_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global AUTH_PENDING, AUTH_TYPE, AUTH_ADMIN_ID
    if not AUTH_PENDING or str(update.effective_user.id) != AUTH_ADMIN_ID:
        return
    
    text = update.message.text.strip()
    if AUTH_TYPE == 'code':
        code = text.replace('-', '').replace(' ', '')
        if code.isdigit() and len(code) in [5, 6]:
            AUTH_PENDING.set_result(code)
            await update.message.reply_text("✅ Code accepted.")
        else:
            await update.message.reply_text("❌ Invalid code.")
    elif AUTH_TYPE == 'password':
        AUTH_PENDING.set_result(text)
        await update.message.reply_text("✅ Password accepted.")
