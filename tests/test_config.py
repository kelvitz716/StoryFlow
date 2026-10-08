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

