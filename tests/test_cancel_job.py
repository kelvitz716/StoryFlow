"""Tests for Feature 2: Cancel a queued job."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestCancelJob(unittest.IsolatedAsyncioTestCase):
    """Verify cancel_job behaviour on the DownloadQueue."""

    def _make_queue_with_job(self, status_str='queued'):
        from core.queue import DownloadQueue, DownloadJob, JobStatus

        q = DownloadQueue(max_concurrent=1)
        q.status_callback = AsyncMock()

        status_map = {
            'queued': JobStatus.QUEUED,
            'downloading': JobStatus.DOWNLOADING,
            'uploading': JobStatus.UPLOADING,
            'completed': JobStatus.COMPLETED,
            'failed': JobStatus.FAILED,
        }

        job = DownloadJob(
            job_id='abc123',
            user_id='user1',
            url='https://example.com',
            platform='YouTube',
        )
        job.status = status_map[status_str]
        job.save_to_db = MagicMock()  # avoid real DB write
        q._jobs['abc123'] = job
        return q, job

    async def test_cancel_queued_job_returns_true(self):
        """cancel_job on a QUEUED job owned by user returns True."""
        q, job = self._make_queue_with_job('queued')
        result = await q.cancel_job('abc123', 'user1')
        self.assertTrue(result)

    async def test_cancelled_job_removed_from_jobs_dict(self):
        """After cancellation, the job must not be in _jobs."""
        q, job = self._make_queue_with_job('queued')
        await q.cancel_job('abc123', 'user1')
        self.assertNotIn('abc123', q._jobs)

    async def test_cancel_sets_cancelled_status(self):
        """The job's status must be set to CANCELLED before removal."""
        from core.queue import JobStatus
        q, job = self._make_queue_with_job('queued')
        await q.cancel_job('abc123', 'user1')
        # status was set before pop, check via save_to_db call args
        self.assertTrue(job.save_to_db.called)
        self.assertEqual(job.status, JobStatus.CANCELLED)

    async def test_cancel_sets_completed_at(self):
        """completed_at must be populated on cancellation."""
        q, job = self._make_queue_with_job('queued')
        await q.cancel_job('abc123', 'user1')
        self.assertIsNotNone(job.completed_at)

    async def test_cannot_cancel_wrong_user(self):
        """cancel_job must return False if the user_id doesn't match."""
        q, job = self._make_queue_with_job('queued')
        result = await q.cancel_job('abc123', 'another_user')
        self.assertFalse(result)

    async def test_cannot_cancel_unknown_job(self):
        """cancel_job must return False for an unknown job_id."""
        q, _ = self._make_queue_with_job('queued')
        result = await q.cancel_job('nonexistent', 'user1')
        self.assertFalse(result)

    async def test_cannot_cancel_downloading_job(self):
        """cancel_job must return False for a DOWNLOADING job."""
        q, job = self._make_queue_with_job('downloading')
        result = await q.cancel_job('abc123', 'user1')
        self.assertFalse(result)

    async def test_cannot_cancel_uploading_job(self):
        """cancel_job must return False for an UPLOADING job."""
        q, job = self._make_queue_with_job('uploading')
        result = await q.cancel_job('abc123', 'user1')
        self.assertFalse(result)

    async def test_cannot_cancel_completed_job(self):
        """cancel_job must return False for a COMPLETED job."""
        q, job = self._make_queue_with_job('completed')
        result = await q.cancel_job('abc123', 'user1')
        self.assertFalse(result)

    async def test_status_callback_called_on_cancel(self):
        """status_callback must be called with the cancelled job."""
        from core.queue import JobStatus
        q, job = self._make_queue_with_job('queued')
        await q.cancel_job('abc123', 'user1')
        q.status_callback.assert_called_once()
        called_job = q.status_callback.call_args[0][0]
        self.assertEqual(called_job.status, JobStatus.CANCELLED)

    def test_cancelled_in_job_status_enum(self):
        """CANCELLED must be a member of JobStatus."""
        from core.queue import JobStatus
        self.assertIn('CANCELLED', [s.name for s in JobStatus])
        self.assertEqual(JobStatus.CANCELLED.value, 'cancelled')

    async def test_worker_skips_cancelled_job(self):
        """A CANCELLED job dequeued by a worker must be skipped without processing."""
        from core.queue import DownloadQueue, DownloadJob, JobStatus

        q = DownloadQueue(max_concurrent=1)
        q._running = True
        q.status_callback = AsyncMock()

        job = DownloadJob(
            job_id='skip1',
            user_id='user2',
            url='https://example.com',
            platform='YouTube',
        )
        job.status = JobStatus.CANCELLED
        job.save_to_db = MagicMock()

        upload_func = AsyncMock()
        await q._queue.put((job, upload_func))

        # Run the worker for one iteration then stop it
        q._running = False  # will exit after processing the one item
        q._running = True
        worker_task = asyncio.create_task(q._worker(0))
        await asyncio.sleep(0.1)  # let worker pick up the job
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

        # The upload_func must NOT have been called for a cancelled job
        upload_func.assert_not_called()


if __name__ == '__main__':
    unittest.main()
