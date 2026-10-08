"""
Tests for item 9:
- ADMIN_USER_ID with non-numeric entries causes sys.exit(1).
- init_queue reads MAX_CONCURRENT_JOBS / MAX_JOBS_PER_USER from env.
- MAX_CONCURRENT_JOBS is clamped to [1, 10].
"""
import os
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from storyflow import _validate_admin_ids


class TestAdminIdValidation:

    def test_valid_single_id(self):
        """A single numeric ID is accepted."""
        result = _validate_admin_ids("123456789")
        assert result == ["123456789"]

    def test_valid_comma_separated(self):
        """Multiple numeric IDs are accepted."""
        result = _validate_admin_ids("123, 456, -789")
        assert result == ["123", "456", "-789"]

    def test_non_numeric_entry_exits(self):
        """A non-numeric entry must cause sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            _validate_admin_ids("123, admin_user, 456")
        assert exc_info.value.code == 1

    def test_token_like_entry_exits(self):
        """A bot-token-like string must also cause sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            _validate_admin_ids("123456789:ABCDEF")
        assert exc_info.value.code == 1

    def test_empty_entries_ignored(self):
        """Trailing commas and empty entries are skipped."""
        result = _validate_admin_ids("123,,456,")
        assert result == ["123", "456"]


class TestQueueEnvDefaults:

    @pytest.mark.asyncio
    async def test_default_max_concurrent_is_2(self):
        """Without env vars, max_concurrent defaults to 2."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        with patch.dict(os.environ, {}, clear=False):
            # Remove the relevant keys if present
            os.environ.pop('MAX_CONCURRENT_JOBS', None)
            os.environ.pop('MAX_JOBS_PER_USER', None)

            with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                await q_module.init_queue(None, None)
                mock_cls.assert_called_once()
                kwargs = mock_cls.call_args
                assert kwargs[1]['max_concurrent'] == 2 or kwargs[0][0] == 2 or mock_cls.call_args.kwargs.get('max_concurrent') == 2

    @pytest.mark.asyncio
    async def test_env_max_concurrent_respected(self):
        """MAX_CONCURRENT_JOBS=5 is applied."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        with patch.dict(os.environ, {'MAX_CONCURRENT_JOBS': '5', 'MAX_JOBS_PER_USER': '3'}):
            with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                await q_module.init_queue(None, None)
                call_kwargs = mock_cls.call_args.kwargs
                assert call_kwargs['max_concurrent'] == 5
                assert call_kwargs['max_per_user'] == 3

    @pytest.mark.asyncio
    async def test_max_concurrent_clamped_above_10(self):
        """MAX_CONCURRENT_JOBS > 10 is clamped to 10."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        with patch.dict(os.environ, {'MAX_CONCURRENT_JOBS': '99'}):
            with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                await q_module.init_queue(None, None)
                call_kwargs = mock_cls.call_args.kwargs
                assert call_kwargs['max_concurrent'] == 10

    @pytest.mark.asyncio
    async def test_max_concurrent_clamped_below_1(self):
        """MAX_CONCURRENT_JOBS=0 is clamped to 1."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        with patch.dict(os.environ, {'MAX_CONCURRENT_JOBS': '0'}):
            with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                await q_module.init_queue(None, None)
                call_kwargs = mock_cls.call_args.kwargs
                assert call_kwargs['max_concurrent'] == 1

    @pytest.mark.asyncio
    async def test_max_per_user_clamped_below_1_env(self):
        """MAX_JOBS_PER_USER=0 or negative from env is clamped to 1."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        for invalid_val in ('0', '-5'):
            with patch.dict(os.environ, {'MAX_JOBS_PER_USER': invalid_val}):
                with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                    await q_module.init_queue(None, None)
                    call_kwargs = mock_cls.call_args.kwargs
                    assert call_kwargs['max_per_user'] == 1

    @pytest.mark.asyncio
    async def test_max_per_user_clamped_below_1_param(self):
        """init_queue(max_per_user=0) or negative is clamped to 1."""
        from core import queue as q_module

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()

        for invalid_val in (0, -10):
            with patch.object(q_module, 'DownloadQueue', return_value=mock_queue) as mock_cls:
                await q_module.init_queue(None, None, max_per_user=invalid_val)
                call_kwargs = mock_cls.call_args.kwargs
                assert call_kwargs['max_per_user'] == 1

    def test_download_queue_direct_init_clamped(self):
        """Direct DownloadQueue(max_per_user=0) is clamped to at least 1."""
        from core.queue import DownloadQueue
        q = DownloadQueue(max_per_user=0)
        assert q.max_per_user == 1
        q_neg = DownloadQueue(max_per_user=-3)
        assert q_neg.max_per_user == 1


class TestEnvExamplePacingVars:

    def test_env_example_has_pacing_and_backlog_vars(self):
        """Verify .env.example defines EDIT_MIN_INTERVAL_SECONDS, BACKLOG_AGE_SECONDS, BACKLOG_SUBMIT_DELAY_SECONDS."""
        with open(".env.example", "r") as f:
            content = f.read()

        assert "EDIT_MIN_INTERVAL_SECONDS=1.5" in content
        assert "EDIT_MSG_MIN_INTERVAL_SECONDS=3.5" in content
        assert "BACKLOG_AGE_SECONDS=60" in content
        assert "BACKLOG_SUBMIT_DELAY_SECONDS=1.5" in content


class TestEnvIntHelper:

    def test_importable_from_storyflow_and_core(self):
        """_env_int is exposed from both storyflow and core.queue."""
        from storyflow import _env_int as fn1
        from core.queue import _env_int as fn2
        assert callable(fn1)
        assert callable(fn2)

    def test_abc_string_logs_warning_and_uses_default(self, caplog):
        """'abc' logs warning and returns default (clamped)."""
        from core.queue import _env_int
        import logging
        with patch.dict(os.environ, {"TEST_INT_VAR": "abc"}):
            with caplog.at_level(logging.WARNING):
                val = _env_int("TEST_INT_VAR", default=5, lo=1, hi=10)
                assert val == 5
                assert any("TEST_INT_VAR" in r.message and "abc" in r.message for r in caplog.records)

    def test_empty_string_logs_warning_and_uses_default(self, caplog):
        """'' logs warning and returns default (clamped)."""
        from core.queue import _env_int
        import logging
        for empty_val in ("", "   "):
            with patch.dict(os.environ, {"TEST_INT_VAR": empty_val}):
                with caplog.at_level(logging.WARNING):
                    val = _env_int("TEST_INT_VAR", default=5, lo=1, hi=10)
                    assert val == 5
                    assert any("Empty value" in r.message and "TEST_INT_VAR" in r.message for r in caplog.records)

    def test_minus_one_clamped(self):
        """'-1' is parsed and clamped to lo."""
        from core.queue import _env_int
        with patch.dict(os.environ, {"TEST_INT_VAR": "-1"}):
            val = _env_int("TEST_INT_VAR", default=5, lo=1, hi=10)
            assert val == 1

    def test_9999_clamped(self):
        """'9999' is parsed and clamped to hi."""
        from core.queue import _env_int
        with patch.dict(os.environ, {"TEST_INT_VAR": "9999"}):
            val = _env_int("TEST_INT_VAR", default=5, lo=1, hi=10)
            assert val == 10

    def test_valid_in_range_and_unset(self, caplog):
        """Valid integer parses without warning; unset env var returns default without warning."""
        from core.queue import _env_int
        import logging
        with caplog.at_level(logging.WARNING):
            with patch.dict(os.environ, {"TEST_INT_VAR": "7"}):
                assert _env_int("TEST_INT_VAR", default=5, lo=1, hi=10) == 7
            with patch.dict(os.environ, {}, clear=True):
                assert _env_int("TEST_INT_VAR", default=4, lo=1, hi=10) == 4
        assert len(caplog.records) == 0


class TestEnvFloatHelper:

    def test_importable_from_storyflow_and_core(self):
        """_env_float is exposed from both storyflow and core.queue."""
        from storyflow import _env_float as fn1
        from core.queue import _env_float as fn2
        assert callable(fn1)
        assert callable(fn2)

    def test_empty_string(self, caplog):
        """'' logs warning and returns default (clamped)."""
        from core.queue import _env_float
        import logging
        for empty_val in ("", "   "):
            with patch.dict(os.environ, {"TEST_FLOAT_VAR": empty_val}):
                with caplog.at_level(logging.WARNING):
                    val = _env_float("TEST_FLOAT_VAR", default=5.5, lo=1.0, hi=10.0)
                    assert val == 5.5
                    assert any("Empty value" in r.message and "TEST_FLOAT_VAR" in r.message for r in caplog.records)

    def test_abc_string(self, caplog):
        """'abc' logs warning and returns default (clamped)."""
        from core.queue import _env_float
        import logging
        with patch.dict(os.environ, {"TEST_FLOAT_VAR": "abc"}):
            with caplog.at_level(logging.WARNING):
                val = _env_float("TEST_FLOAT_VAR", default=5.5, lo=1.0, hi=10.0)
                assert val == 5.5
                assert any("Non-numeric value" in r.message and "TEST_FLOAT_VAR" in r.message for r in caplog.records)

    def test_minus_one_clamped(self):
        """'-1' is parsed and clamped to lo."""
        from core.queue import _env_float
        with patch.dict(os.environ, {"TEST_FLOAT_VAR": "-1"}):
            val = _env_float("TEST_FLOAT_VAR", default=5.5, lo=0.0, hi=10.0)
            assert val == 0.0

    def test_9999_clamped(self):
        """'9999' is parsed and clamped to hi."""
        from core.queue import _env_float
        with patch.dict(os.environ, {"TEST_FLOAT_VAR": "9999"}):
            val = _env_float("TEST_FLOAT_VAR", default=5.5, lo=0.0, hi=10.0)
            assert val == 10.0

    def test_valid_in_range_and_unset(self, caplog):
        """Valid float parses without warning; unset env var returns default without warning."""
        from core.queue import _env_float
        import logging
        with caplog.at_level(logging.WARNING):
            with patch.dict(os.environ, {"TEST_FLOAT_VAR": "7.25"}):
                assert _env_float("TEST_FLOAT_VAR", default=5.5, lo=1.0, hi=10.0) == 7.25
            with patch.dict(os.environ, {}, clear=True):
                assert _env_float("TEST_FLOAT_VAR", default=4.0, lo=1.0, hi=10.0) == 4.0
        assert len(caplog.records) == 0


class TestBlankEnvVarsDoNotRaise:

    def test_edit_coordinator_blank_edit_vars(self):
        """EditCoordinator() must not raise on blank EDIT_* values."""
        from bot.edit_gate import EditCoordinator
        with patch.dict(os.environ, {
            "EDIT_MIN_INTERVAL_SECONDS": "",
            "EDIT_MSG_MIN_INTERVAL_SECONDS": "",
        }):
            coord = EditCoordinator()
            assert coord.edit_min_interval == 1.5
            assert coord.msg_min_interval == 3.5

    @pytest.mark.asyncio
    async def test_handle_url_blank_backlog_vars(self):
        """handle_url must not raise on blank BACKLOG_* values."""
        from bot.handlers import handle_url
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, AsyncMock

        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(return_value=None)
        access_mgr = MagicMock()
        access_mgr.is_system_sender.return_value = False
        access_mgr.is_anonymous_sender.return_value = False
        access_mgr.is_user_allowed.return_value = True

        msg = MagicMock()
        msg.text = "https://instagram.com/p/test"
        msg.date = datetime.now(timezone.utc)
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.channel_post = None
        update.effective_message = msg
        update.effective_user = MagicMock(id=123)
        update.effective_chat = MagicMock(id=456)
        context = MagicMock()
        context.user_data = {}

        with patch.dict(os.environ, {
            "BACKLOG_AGE_SECONDS": "",
            "BACKLOG_SUBMIT_DELAY_SECONDS": "",
        }):
            # Must not raise on blank BACKLOG_*
            await handle_url(update, context, access_mgr, mock_queue)



