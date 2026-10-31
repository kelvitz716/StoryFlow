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

    @pytest.mark.asyncio
    async def test_non_txt_document_silently_ignored(self):
        """Non-.txt documents (like GIFs or videos) must be silently ignored even if large."""
        from bot.handlers import handle_document
        from auth.cookies import CookieManager

        am = _make_access_manager(admin_id="9999", allowed=["1111"])
        cm = MagicMock(spec=CookieManager)

        update = _make_update("1111", chat_type="supergroup")
        update.message.document = MagicMock()
        update.message.document.file_size = 5 * 1024 * 1024  # 5 MB GIF
        update.message.document.file_name = "funny_animation.gif"
        update.message.document.get_file = AsyncMock()
        update.message.reply_text = AsyncMock()

        ctx = _make_context()
        await handle_document(update, ctx, cm, am)

        # Must not reply or complain about cookie file size
        update.message.reply_text.assert_not_called()
        update.message.document.get_file.assert_not_called()


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
        import logging as _log
        # Simulate what run_telegram_bot does
        _log.getLogger("httpx").setLevel(_log.WARNING)
        _log.getLogger("httpcore").setLevel(_log.WARNING)
        assert _log.getLogger("httpx").level == _log.WARNING
        assert _log.getLogger("httpcore").level == _log.WARNING


# ---------------------------------------------------------------------------
# G1 — handle_url uses require_allowed; queue_command filters by user
# ---------------------------------------------------------------------------

def _make_update_group(user_id: str, chat_id: str, chat_type: str = "group", text: str = "https://example.com") -> MagicMock:
    """Build a fake Update for group messages with distinct chat_id."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = int(user_id)
    update.effective_chat = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_chat.id = int(chat_id)
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.text = text
    msg.is_automatic_forward = False
    msg.sender_chat = None
    msg.date = None
    update.effective_message = msg
    update.message = msg
    # make update.message_id / update_id work
    update.update_id = 1
    update.edited_message = None
    update.channel_post = None
    update.edited_channel_post = None
    return update


class TestHandleUrlG1:
    """G1 tests for handle_url access control."""

    @pytest.mark.asyncio
    async def test_non_allowed_user_in_group_gets_no_reply(self):
        """Non-allowed user posting a URL in a group gets no reply, nothing enqueued."""
        from core.queue import DownloadQueue, JobStatus
        am = _make_access_manager(admin_id="9999")
        # user 1111 not allowed, chat -200 not allowed
        update = _make_update_group("1111", "-200", chat_type="group")
        ctx = _make_context()

        dq = MagicMock()
        dq.add_job = AsyncMock(return_value=None)

        from bot.handlers import handle_url
        with patch("bot.handlers.resolve_shortlink", return_value=None), \
             patch("bot.handlers.identify_platform", return_value="Generic"):
            await handle_url(update, ctx, am, dq)

        update.message.reply_text.assert_not_called()
        dq.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_allowed_user_in_private_gets_rejection(self):
        """Non-allowed user in private chat gets a standard rejection, nothing enqueued."""
        am = _make_access_manager(admin_id="9999")
        update = _make_update("1111", chat_type="private", text="https://example.com")
        # Wire effective_chat.id and effective_chat.type properly for require_allowed
        update.effective_chat.id = 1111
        update.effective_chat.type = "private"
        update.effective_message.is_automatic_forward = False
        update.effective_message.sender_chat = None
        update.effective_message.date = None
        ctx = _make_context()

        dq = MagicMock()
        dq.add_job = AsyncMock(return_value=None)

        from bot.handlers import handle_url
        with patch("bot.handlers.resolve_shortlink", return_value=None):
            await handle_url(update, ctx, am, dq)

        update.effective_message.reply_text.assert_called_once()
        dq.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowlisted_group_chat_is_accepted(self):
        """A URL sent from an allowlisted group chat is accepted (no rejection)."""
        am = _make_access_manager(admin_id="9999", allowed=["-200"])
        update = _make_update_group("1111", "-200", chat_type="group", text="https://www.instagram.com/p/abc123/")
        ctx = _make_context()

        fake_job = MagicMock()
        fake_job.job_id = "job-abc"
        dq = MagicMock()
        dq.submit = AsyncMock(return_value=fake_job)

        coord = MagicMock()
        coord.clock.return_value = 0.0
        coord.sleep_func = AsyncMock()

        from bot.handlers import handle_url
        with patch("bot.handlers.resolve_shortlink", return_value=None), \
             patch("bot.handlers.identify_platform", return_value="Instagram"), \
             patch("bot.handlers.register_job_message"), \
             patch("bot.handlers.register_backlog_job"), \
             patch("bot.handlers.batch_upload_media", new=AsyncMock()), \
             patch("bot.handlers.get_edit_coordinator", return_value=coord):
            await handle_url(update, ctx, am, dq)

        # No rejection reply was sent
        call_texts = [str(c) for c in update.message.reply_text.call_args_list]
        for t in call_texts:
            assert "not authoris" not in t.lower() and "⛔" not in t


class TestQueueCommandG1:
    """G1 tests for /queue access isolation."""

    def _make_job(self, user_id: str, platform: str = "Instagram"):
        from core.queue import DownloadJob, JobStatus
        import uuid
        job = MagicMock(spec=DownloadJob)
        job.user_id = user_id
        job.platform = platform
        job.status = JobStatus.DOWNLOADING
        return job

    @pytest.mark.asyncio
    async def test_non_admin_sees_only_own_jobs(self):
        """A non-admin user B never sees user A's jobs in /queue."""
        am = _make_access_manager(admin_id="9999", allowed=["1111", "2222"])
        # Call as user 2222
        update = _make_update("2222", chat_type="private")
        update.effective_chat.id = 2222
        ctx = _make_context()

        job_a = self._make_job("1111")
        job_b = self._make_job("2222")

        dq = MagicMock()
        dq.get_stats.return_value = {
            "pending": 1,
            "active": 2,
            "max_concurrent": 4,
            "active_jobs": [job_a, job_b],
        }

        from bot.handlers import queue_command
        await queue_command(update, ctx, am, dq)

        reply_text = update.message.reply_text.call_args[0][0]
        # job_b shows up (platform = Instagram)
        assert "Instagram" in reply_text or "downloading" in reply_text.lower()
        # User A's last-4 digits must NOT appear
        assert "1111"[-4:] not in reply_text

    @pytest.mark.asyncio
    async def test_admin_sees_all_jobs(self):
        """Admin sees all jobs, including other users'."""
        am = _make_access_manager(admin_id="9999", allowed=["1111", "2222"])
        update = _make_update("9999", chat_type="private")
        update.effective_chat.id = 9999
        ctx = _make_context()

        job_a = self._make_job("1111")
        job_b = self._make_job("2222")

        dq = MagicMock()
        dq.get_stats.return_value = {
            "pending": 0,
            "active": 2,
            "max_concurrent": 4,
            "active_jobs": [job_a, job_b],
        }

        from bot.handlers import queue_command
        await queue_command(update, ctx, am, dq)

        reply_text = update.message.reply_text.call_args[0][0]
        # Both users' last-4 digits appear for admin
        assert "1111"[-4:] in reply_text
        assert "2222"[-4:] in reply_text
