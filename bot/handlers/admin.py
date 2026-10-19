"""Admin text input and interactive MTProto authentication handlers."""

import asyncio
from telegram import Update
from telegram.ext import ContextTypes, Application

from auth.access import AccessManager
from bot.menus import send_admin_menu

# MTProto Auth state (mapped in main bot)
AUTH_PENDING = None
AUTH_TYPE = None
AUTH_ADMIN_ID = None


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
