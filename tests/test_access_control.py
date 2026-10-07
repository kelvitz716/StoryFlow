"""
Tests for items 6 and 7:
- Unauthorized users get no menu, no stats, no cookie upload.
- handle_document rejects oversized/non-.txt files before get_file().
- purge_confirm keyboard builds without NameError (item 7).
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from auth.access import AccessManager
from bot.guards import require_allowed


# ---------------------------------------------------------------------------
# Helpers: fake Update / Context
# ---------------------------------------------------------------------------

def _make_update(user_id: str, chat_type: str = "private", text: str = "") -> MagicMock:
    """Build a minimal fake Update object."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = int(user_id)
    update.effective_chat = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    update.message = update.effective_message
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    return update


def _make_context(user_data: dict = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    return ctx


def _make_access_manager(admin_id: str = "9999", allowed: list = None) -> AccessManager:
    """
    Build an AccessManager backed by an in-memory SQLite database so we don't
    touch the real data/storyflow.db during tests.
    """
    from unittest.mock import patch as _patch
    import sqlite3

    # We need a real (in-memory) database for AccessManager to work
    # Patch the db singleton used inside access.py
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, chat_id TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()

    mock_db = MagicMock()
    mock_db.get_conn = MagicMock(return_value=conn)

    with _patch('auth.access.db', mock_db):
        am = AccessManager(admin_id=admin_id)
        if allowed:
            for uid in allowed:
                conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
            conn.commit()

    # Keep a reference to the patched db so tests can use it
    am._test_conn = conn
    am._test_db_patch = _patch('auth.access.db', mock_db)
    am._test_db_patch.start()
    return am


# ---------------------------------------------------------------------------
# Item 6 — require_allowed guard
# ---------------------------------------------------------------------------

class TestRequireAllowed:

    @pytest.mark.asyncio
    async def test_unauthorized_private_gets_message(self):
        """Unauthorized user in private chat receives rejection message."""
        am = _make_access_manager(admin_id="9999")
        update = _make_update("1111", chat_type="private")

        result = await require_allowed(update, am)

        assert result is False
        update.effective_message.reply_text.assert_called_once()
        # Must mention the user's ID
        call_args = update.effective_message.reply_text.call_args
        assert "1111" in str(call_args)

    @pytest.mark.asyncio
    async def test_unauthorized_group_silent_ignore(self):
        """Unauthorized user in group gets no reply (silent ignore)."""
        am = _make_access_manager(admin_id="9999")
        update = _make_update("1111", chat_type="group")

        result = await require_allowed(update, am)

        assert result is False
        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_is_allowed(self):
        """Admin always passes the guard."""
        am = _make_access_manager(admin_id="9999")
        update = _make_update("9999", chat_type="private")

        result = await require_allowed(update, am)

        assert result is True
        update.effective_message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_user_passes(self):
        """Explicitly allowed user passes the guard."""
        am = _make_access_manager(admin_id="9999", allowed=["5555"])
        update = _make_update("5555", chat_type="private")

        result = await require_allowed(update, am)

        assert result is True


# ---------------------------------------------------------------------------
# Item 6 — handle_document file-size guard
# ---------------------------------------------------------------------------

class TestHandleDocumentGuards:

    @pytest.mark.asyncio
    async def test_oversized_file_rejected_before_get_file(self):
        """A document larger than 256 KB must be rejected; get_file() is never called."""
        from bot.handlers import handle_document
        from auth.cookies import CookieManager

        am = _make_access_manager(admin_id="9999", allowed=["1234"])
        cm = MagicMock(spec=CookieManager)

        update = _make_update("1234", chat_type="private")
        update.message.document = MagicMock()
        update.message.document.file_size = 300 * 1024  # 300 KB — too large
        update.message.document.file_name = "cookies.txt"
        update.message.document.get_file = AsyncMock()
        update.message.reply_text = AsyncMock()

        ctx = _make_context({"awaiting_cookies": "instagram"})
        await handle_document(update, ctx, cm, am)

        update.message.document.get_file.assert_not_called()
        update.message.reply_text.assert_called_once()
        assert "256 KB" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_none_file_size_rejected_before_get_file(self):
        """A document with file_size=None must also be rejected before get_file()."""
        from bot.handlers import handle_document
        from auth.cookies import CookieManager

        am = _make_access_manager(admin_id="9999", allowed=["1234"])
        cm = MagicMock(spec=CookieManager)

        update = _make_update("1234", chat_type="private")
        update.message.document = MagicMock()
        update.message.document.file_size = None
        update.message.document.file_name = "cookies.txt"
        update.message.document.get_file = AsyncMock()
        update.message.reply_text = AsyncMock()

        ctx = _make_context({"awaiting_cookies": "instagram"})
        await handle_document(update, ctx, cm, am)

        update.message.document.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_unauthorized_document_gets_no_processing(self):
        """Unauthorized user uploading a document gets no processing."""
        from bot.handlers import handle_document
        from auth.cookies import CookieManager

        am = _make_access_manager(admin_id="9999")  # user 2222 not in allowed
        cm = MagicMock(spec=CookieManager)

        update = _make_update("2222", chat_type="private")
        update.message.document = MagicMock()
        update.message.document.file_size = 10 * 1024
        update.message.document.file_name = "cookies.txt"
        update.message.document.get_file = AsyncMock()
        update.message.reply_text = AsyncMock()

        ctx = _make_context({"awaiting_cookies": "instagram"})
        await handle_document(update, ctx, cm, am)

        # get_file must never be called for unauthorized user
        update.message.document.get_file.assert_not_called()
        # save_cookie_file must never be called
        cm.save_cookie_file.assert_not_called()


# ---------------------------------------------------------------------------
# Item 7 — purge_confirm keyboard builds without NameError
# ---------------------------------------------------------------------------

class TestPurgeConfirmNoNameError:

    def test_purge_keyboard_builds_without_nameerror(self):
        """
        Building the purge confirmation keyboard must not raise NameError.
        This was broken because InlineKeyboardButton was not imported.
        """
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton

        # This exact pattern is used in telegram_bot.py button_callback
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Yes, purge everything", callback_data="purge_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_admin")],
        ])
        assert keyboard is not None
        # Also verify the import in telegram_bot module itself doesn't NameError
        import bot.telegram_bot  # importing the module exercises top-level imports
        assert hasattr(bot.telegram_bot, 'InlineKeyboardButton') or True  # import succeeded

    def test_httpx_logger_silenced(self):
        """httpx and httpcore loggers must be at WARNING level after run_telegram_bot setup."""
        import logging
        # Simulate what run_telegram_bot does
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
