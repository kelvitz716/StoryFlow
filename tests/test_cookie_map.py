"""
Tests for core/cookie_map.py and in-bot channel cookie mapping features.
"""
import os
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core import cookie_map


@pytest.fixture(autouse=True)
def clean_cookie_map(tmp_path, monkeypatch):
    """Point _MAP_FILE to tmp_path so tests don't touch production data."""
    test_file = tmp_path / "data" / "cookie_map.json"
    monkeypatch.setattr(cookie_map, "_MAP_FILE", test_file)
    cookie_map._mappings = {}
    cookie_map._admin_fallback_override = None
    yield
    if test_file.exists():
        test_file.unlink()


class TestCookieMapCore:
    def test_add_get_remove_mappings(self):
        cookie_map.add("-100123456", "987654")
        assert cookie_map.get("-100123456") == "987654"
        assert cookie_map.get("-999999999") is None

        all_m = cookie_map.all_mappings()
        assert "-100123456" in all_m

        assert cookie_map.remove("-100123456") is True
        assert cookie_map.get("-100123456") is None
        assert cookie_map.remove("-100123456") is False

    def test_persistence_to_json(self):
        cookie_map.add("-100111", "222")
        cookie_map.set_admin_fallback(True)

        # Re-initialize by reading from file
        cookie_map._mappings = {}
        cookie_map._admin_fallback_override = None
        cookie_map.reload()

        assert cookie_map.get("-100111") == "222"
        assert cookie_map.is_admin_fallback_enabled() is True

        cookie_map.set_admin_fallback(False)
        assert cookie_map.is_admin_fallback_enabled() is False

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("COOKIE_OWNER_MAP", "-100999:888")
        cookie_map.reload()
        assert cookie_map.get("-100999") == "888"

        # Explicit add overrides env var
        cookie_map.add("-100999", "777")
        assert cookie_map.get("-100999") == "777"


@pytest.mark.asyncio
class TestMapChannelCommand:
    async def test_mapchannel_inside_group_or_channel(self):
        from bot.handlers.commands import mapchannel_command

        update = MagicMock()
        update.effective_user = MagicMock(id=618026357)
        update.effective_chat = MagicMock(id=-1001234567890, title="My Channel")
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()

        ctx = MagicMock(args=[])
        am = MagicMock()
        am.is_user_allowed.return_value = True
        am.is_admin.return_value = True

        await mapchannel_command(update, ctx, am)

        assert cookie_map.get("-1001234567890") == "618026357"
        update.effective_message.reply_text.assert_called_once()
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert "linked to your cookies" in call_text

    async def test_mapchannel_with_args_in_private(self):
        from bot.handlers.commands import mapchannel_command

        update = MagicMock()
        update.effective_user = MagicMock(id=618026357)
        update.effective_chat = MagicMock(id=618026357)
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()

        ctx = MagicMock(args=["-1009876543210"])
        am = MagicMock()
        am.is_user_allowed.return_value = True
        am.is_admin.return_value = True

        await mapchannel_command(update, ctx, am)

        assert cookie_map.get("-1009876543210") == "618026357"
        update.effective_message.reply_text.assert_called_once()
        call_text = update.effective_message.reply_text.call_args[0][0]
        assert "-1009876543210" in call_text


@pytest.mark.asyncio
class TestMapChannelCallback:
    async def test_button_callback_map_channel(self):
        from bot.handlers.callbacks import button_callback

        update = MagicMock()
        update.effective_user = MagicMock(id=618026357)
        update.effective_chat = MagicMock(id=-1001234567890)
        query = MagicMock()
        query.data = "map_channel_-1001234567890"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        ctx = MagicMock()
        am = MagicMock()
        am.is_admin.return_value = True
        am.is_user_allowed.return_value = True
        cm = MagicMock()
        sm = MagicMock()

        await button_callback(update, ctx, am, cm, sm)

        assert query.answer.call_count == 2
        assert "Channel linked" in str(query.answer.call_args)
        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "Channel Linked" in call_text
