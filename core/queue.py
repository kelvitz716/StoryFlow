"""Async download queue for handling multiple concurrent requests."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any
from enum import Enum
from datetime import datetime
import uuid


class JobStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadJob:
    """Represents a download job in the queue."""
    job_id: str
    user_id: str
    url: str
    platform: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    message: str = ""
    files: list = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "url": self.url,
            "platform": self.platform,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "files_count": len(self.files),
            "error": self.error,
        }


class DownloadQueue:
    """
    Async queue for managing download jobs.
    
    Features:
    - Non-blocking job submission
    - Per-user job limits
    - Concurrent download workers
    - Status callbacks for UI updates
    """
    
    def __init__(
        self,
        max_concurrent: int = 3,
        max_per_user: int = 2,
        status_callback: Optional[Callable] = None
    ):
        self.max_concurrent = max_concurrent
        self.max_per_user = max_per_user
        self.status_callback = status_callback
        
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: Dict[str, DownloadJob] = {}
        self._user_jobs: Dict[str, list] = {}  # user_id -> [job_ids]
        self._workers: list = []
        self._running = False
        
    async def start(self):
        """Start the queue workers."""
        if self._running:
            return
            
        self._running = True
        logging.info(f"🚀 Starting download queue with {self.max_concurrent} workers")
        
        for i in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
    
    async def stop(self):
        """Stop all workers gracefully."""
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers = []
        logging.info("🛑 Download queue stopped")
    
    async def submit(
        self,
        user_id: str,
        url: str,
        platform: str,
        download_func: Callable,
        upload_func: Callable
    ) -> Optional[DownloadJob]:
        """
        Submit a new download job to the queue.
        
        Args:
            user_id: Telegram user ID
            url: URL to download
            platform: Platform name (Snapchat, Instagram, etc.)
            download_func: Async function to download content
            upload_func: Async function to upload to Telegram
            
        Returns:
            DownloadJob if queued, None if user limit reached
        """
        # Check user limit
        user_jobs = self._user_jobs.get(user_id, [])
        active_jobs = [j for j in user_jobs if self._jobs.get(j) and 
                       self._jobs[j].status not in (JobStatus.COMPLETED, JobStatus.FAILED)]
        
        if len(active_jobs) >= self.max_per_user:
            return None
        
        # Create job
        job_id = str(uuid.uuid4())[:8]
        job = DownloadJob(
            job_id=job_id,
            user_id=user_id,
            url=url,
            platform=platform,
            message="Waiting in queue..."
        )
        
        # Track job
        self._jobs[job_id] = job
        if user_id not in self._user_jobs:
            self._user_jobs[user_id] = []
        self._user_jobs[user_id].append(job_id)
        
        # Add to queue with callbacks
        await self._queue.put((job, download_func, upload_func))
        
        logging.info(f"📋 Job {job_id} queued for user {user_id} ({platform})")
        return job
    
    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)
    
    def get_user_jobs(self, user_id: str) -> list:
        """Get all jobs for a user."""
        job_ids = self._user_jobs.get(user_id, [])
        return [self._jobs[jid] for jid in job_ids if jid in self._jobs]
    
    def get_queue_position(self, job_id: str) -> int:
        """Get position in queue (1-indexed, 0 if not in queue)."""
        # This is approximate since we can't peek into asyncio.Queue
        job = self._jobs.get(job_id)
        if not job or job.status != JobStatus.QUEUED:
            return 0
        
        # Count queued jobs before this one
        pos = 1
        for jid, j in self._jobs.items():
            if j.status == JobStatus.QUEUED and j.created_at < job.created_at:
                pos += 1
        return pos
    
    async def _worker(self, worker_id: int):
        """Worker that processes jobs from the queue."""
        logging.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Get next job (with timeout to check _running flag)
                try:
                    job, download_func, upload_func = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                logging.info(f"⚙️ Worker {worker_id} processing job {job.job_id}")
                
                try:
                    # Update status: downloading
                    job.status = JobStatus.DOWNLOADING
                    job.message = "Downloading content..."
                    await self._notify_status(job)
                    
                    # Execute download
                    result = await download_func()
                    
                    if not result.get('success'):
                        job.status = JobStatus.FAILED
                        job.error = result.get('error', 'Download failed')
                        job.message = f"Failed: {job.error}"
                        await self._notify_status(job)
                        continue
                    
                    job.files = result.get('files', [])
                    
                    if not job.files:
                        job.status = JobStatus.COMPLETED
                        job.message = result.get('message', 'No content found')
                        await self._notify_status(job)
                        continue
                    
                    # Update status: uploading
                    job.status = JobStatus.UPLOADING
                    job.message = f"Uploading {len(job.files)} files..."
                    await self._notify_status(job)
                    
                    # Execute upload
                    await upload_func(job.files)
                    
                    # Mark complete
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now()
                    job.message = f"Delivered {len(job.files)} files"
                    await self._notify_status(job)
                    
                except Exception as e:
                    logging.error(f"Job {job.job_id} failed: {e}")
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.message = f"Error: {e}"
                    await self._notify_status(job)
                
                finally:
                    self._queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Worker {worker_id} error: {e}")
    
    async def _notify_status(self, job: DownloadJob):
        """Call status callback if set."""
        if self.status_callback:
            try:
                await self.status_callback(job)
            except Exception as e:
                logging.error(f"Status callback error: {e}")


# Global queue instance
download_queue: Optional[DownloadQueue] = None


def get_queue() -> DownloadQueue:
    """Get the global download queue instance."""
    global download_queue
    if download_queue is None:
        download_queue = DownloadQueue()
    return download_queue


async def init_queue(
    max_concurrent: int = 3,
    max_per_user: int = 2,
    status_callback: Optional[Callable] = None
):
    """Initialize and start the global download queue."""
    global download_queue
    download_queue = DownloadQueue(
        max_concurrent=max_concurrent,
        max_per_user=max_per_user,
        status_callback=status_callback
    )
    await download_queue.start()
    return download_queue
