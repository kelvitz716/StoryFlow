"""Command and message handlers for StoryFlow bot."""
import logging
import random
import os
from typing import Optional
from telegram import Update, Document
from telegram.ext import ContextTypes, Application

from core.platform import identify_platform
from auth.access import AccessManager
from auth.cookies import CookieManager  # [NEW]
from bot.menus import send_main_menu, send_help_menu, send_admin_menu, send_cookies_menu, send_delete_cookies_menu
from bot.uploader import batch_upload_media
from utils.bot_utils import format_error_message, get_platform_emoji, escape_markdown, JOB_MESSAGES
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

    url = update.effective_message.text.strip()
    msg = update.effective_message

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
                f"Ask the admin to run: `/adduser {user_id}`",
                parse_mode='Markdown'
            )
            return

    # Admin input handling
    action = context.user_data.get('awaiting_action') if context.user_data is not None else None
    if action and access_manager.is_admin(user_id):
        if action == 'add_user':
            target_id = url.strip()
            if target_id.isdigit() or target_id.startswith('-'):
                if access_manager.add_user(target_id):
                    await update.effective_message.reply_text(f"✅ User/Channel `{target_id}` added!")
                else:
                    await update.effective_message.reply_text(f"⚠️ User `{target_id}` already allowed.")
            else:
                await update.effective_message.reply_text("❌ Invalid ID format.")
            
            context.user_data.pop('awaiting_action', None)
            await send_admin_menu(update.effective_message, user_id, access_manager)
            return

        elif action == 'remove_user':
            target_id = url.strip()
            if access_manager.remove_user(target_id):
                await update.effective_message.reply_text(f"✅ User `{target_id}` removed.")
            else:
                await update.effective_message.reply_text(f"⚠️ User `{target_id}` not found.")
            
            context.user_data.pop('awaiting_action', None)
            await send_admin_menu(update.effective_message, user_id, access_manager)
            return

    # Identify platform
    platform = identify_platform(url)
    if platform == "Unknown":
        # Ignore non-URLs or unrecognised links unless they were expected for an action
        if action:
             return
        await update.effective_message.reply_text(
            "🤔 Hmm, I don't recognize that link!\n"
            "I support Snapchat, Instagram, TikTok, Twitter, and Facebook."
        )
        return
    
    # Process download
    proc_msg = random.choice(PROCESSING_MSGS)
    status_msg = await update.effective_message.reply_text(f"{proc_msg}")
    
    async def upload_func(files):
        await batch_upload_media(update, files, status_msg, mtproto_client)

    if download_queue:
        job = await download_queue.submit(
            user_id=user_id,
            url=url,
            platform=platform,
            upload_func=upload_func
        )
        
        if job:
            JOB_MESSAGES[job.job_id] = status_msg
            pos = download_queue.get_queue_position(job.job_id)
            if pos > 0:
                 await status_msg.edit_text(f"⏳ *Queued* (Position: {pos})\nWaiting for worker...", parse_mode='Markdown')
        else:
            await status_msg.edit_text("⚠️ *Queue Full*\nPlease wait for your active downloads to finish.")
    else:
        await status_msg.edit_text("⚠️ System Error: Queue not active.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, access_manager: AccessManager) -> None:
    user_id = str(update.effective_user.id)
    await send_main_menu(update.message, user_id, access_manager, is_new_message=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_help_menu(update.message, is_new_message=True)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, cookie_manager: CookieManager) -> None:
    """Handle document (cookie file) upload."""
    document: Document = update.message.document
    user_id = str(update.effective_user.id)
    
    awaiting_platform = context.user_data.get('awaiting_cookies')
    if not awaiting_platform:
        await update.message.reply_text("📎 I wasn't expecting a cookie file. Go to 'Manage Cookies' first.")
        return
    
    context.user_data['awaiting_cookies'] = False
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file.")
        return
    
    status_msg = await update.message.reply_text(f"⏳ Processing {awaiting_platform.title()} cookies...")
    
    try:
        import tempfile
        file = await document.get_file()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            temp_path = tf.name
        
        await file.download_to_drive(temp_path)
        result = cookie_manager.save_cookie_file(user_id, awaiting_platform, temp_path)
        
        if result['success']:
            msg = f"✅ *{awaiting_platform.title()} Cookies Saved!*\nValid until: {result.get('expiry_str', 'Unknown')}"
            await status_msg.edit_text(msg, parse_mode='Markdown')
        else:
            await status_msg.edit_text(f"❌ Failed: {result.get('error')}")
        
        if os.path.exists(temp_path): os.remove(temp_path)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Error: {str(e)}")

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
