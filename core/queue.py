"""Async download queue for handling multiple concurrent requests."""

import asyncio
import logging
import os
import time
import shutil
from core.storage import is_storage_critical, format_storage_report
from core.database import db
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
    chat_id: Optional[str] = None
    message_id: Optional[int] = None
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    message: str = ""
    files: list = field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    job_dir: Optional[str] = None
    
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

    def save_to_db(self):
        """Upsert the current state of the job to SQLite."""
        try:
            with db.get_conn() as conn:
                conn.execute('''
                    INSERT INTO jobs (job_id, user_id, chat_id, message_id, url, platform, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(job_id) DO UPDATE SET 
                        status = excluded.status,
                        updated_at = CURRENT_TIMESTAMP
                ''', (self.job_id, self.user_id, self.chat_id, self.message_id, self.url, self.platform, self.status.value))
        except Exception as e:
            logging.error(f"Failed to save job {self.job_id} to DB: {e}")


class DownloadQueue:
    """
    Async queue for managing download jobs with SQLite tracking.
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        max_per_user: int = 20,
        status_callback: Optional[Callable] = None
    ):
        self.max_concurrent = max_concurrent
        self.max_per_user = max_per_user
        self.status_callback = status_callback
        self.download_path = os.getenv('DOWNLOAD_PATH', './downloads')
        
        self.snapchat = None
        self.gallery_dl = None
        
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: Dict[str, DownloadJob] = {}
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
            
        self._cleanup_task = asyncio.create_task(self._background_cleanup())
        await asyncio.to_thread(self._startup_sweep)

    async def recover_orphaned_jobs(self, telegram_bot):
        """Send apologies to users whose jobs were killed during a server restart."""
        try:
            orphaned = []
            with db.get_conn() as conn:
                cur = conn.execute("SELECT job_id, chat_id FROM jobs WHERE status IN ('queued', 'downloading', 'uploading')")
                orphaned = cur.fetchall()
                if not orphaned:
                    return
                for orphan in orphaned:
                    conn.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (orphan['job_id'],))
            
            logging.info(f"🔄 Recovered {len(orphaned)} orphaned jobs from previous crash.")
            for orphan in orphaned:
                chat_id = orphan['chat_id']
                if chat_id and telegram_bot:
                    try:
                        await telegram_bot.send_message(
                            chat_id=chat_id,
                            text="⚠️ *Server Restarted*\n\nSorry! The server had to restart while processing your link. Please try sending it again.",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logging.warning(f"Could not send recovery message to {chat_id}: {e}")
        except Exception as e:
            logging.error(f"Detailed recovery sweep failed: {e}")
    
    async def stop(self):
        """Stop all workers gracefully."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        if hasattr(self, '_cleanup_task'):
            self._cleanup_task.cancel()
            try: await self._cleanup_task
            except asyncio.CancelledError: pass
        
        self._workers = []
        logging.info("🛑 Download queue stopped")
    
    async def submit(
        self,
        user_id: str,
        url: str,
        platform: str,
        upload_func: Callable,
        chat_id: Optional[str] = None,
        message_id: Optional[int] = None
    ) -> Optional[DownloadJob]:
        active_jobs = [j for j in self._jobs.values() if j.user_id == user_id and 
                       j.status not in (JobStatus.COMPLETED, JobStatus.FAILED)]
        
        if len(active_jobs) >= self.max_per_user:
            return None
        
        for existing_job in active_jobs:
            if existing_job.url == url:
                logging.info(f"♻️ Job {existing_job.job_id} already active for URL: {url} (User: {user_id})")
                return existing_job

        job_id = str(uuid.uuid4())[:8]
        job = DownloadJob(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            url=url,
            platform=platform,
            message="Waiting in queue...",
            job_dir=os.path.join(self.download_path, job_id)
        )
        
        job.save_to_db()
        self._jobs[job_id] = job
        await self._queue.put((job, upload_func))
        
        masked_user = f"{user_id[:3]}***{user_id[-3:]}" if len(user_id) > 6 else "***"
        logging.info(f"📋 Job {job_id} queued for user {masked_user} ({platform})")
        return job
    
    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)
    
    def get_user_jobs(self, user_id: str) -> list:
        return [j for j in self._jobs.values() if j.user_id == user_id]
    
    def get_queue_position(self, job_id: str) -> int:
        job = self._jobs.get(job_id)
        if not job or job.status != JobStatus.QUEUED:
            return 0
        pos = 1
        for jid, j in self._jobs.items():
            if j.status == JobStatus.QUEUED and j.created_at < job.created_at:
                pos += 1
        return pos

    def get_stats(self) -> dict:
        active = [j for j in self._jobs.values() if j.status in (JobStatus.DOWNLOADING, JobStatus.UPLOADING)]
        return {
            'pending': self._queue.qsize(),
            'active': len(active),
            'max_concurrent': self.max_concurrent,
            'active_jobs': active,
        }
    
    async def _worker(self, worker_id: int):
        logging.debug(f"Worker {worker_id} started")
        while self._running:
            try:
                try:
                    job, upload_func = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError: continue
                except RuntimeError as e:
                    if "Event loop is closed" in str(e): break
                    raise
                
                logging.info(f"⚙️ Worker {worker_id} processing job {job.job_id}")
                
                try:
                    job.status = JobStatus.DOWNLOADING
                    job.message = "Downloading content..."
                    job.save_to_db()
                    await self._notify_status(job)
                    
                    if job.job_dir: os.makedirs(job.job_dir, exist_ok=True)

                    is_critical, current_usage = is_storage_critical(job.job_dir or self.download_path, threshold=99.0)
                    
                    if is_critical:
                        job.status = JobStatus.FAILED
                        job.completed_at = datetime.now()
                        job.error = f"Storage Full ({current_usage}%)"
                        job.message = "Disk space is almost full. Purge system to continue."
                        job.save_to_db()
                        await self._notify_status(job)
                        continue

                    last_update = 0
                    def progress_callback(progress_str: str):
                        nonlocal last_update
                        current_time = time.time()
                        if current_time - last_update < 1.5: return
                        job.message = progress_str
                        last_update = current_time
                        if self.status_callback:
                            task = asyncio.create_task(self.status_callback(job))
                            task.add_done_callback(lambda t: t.exception())

                    is_spotlight = "/spotlight/" in job.url
                    if job.platform == "Snapchat" and self.snapchat and not is_spotlight:
                         result = await self.snapchat.download(job.url, job.user_id, job.job_id)
                    elif self.gallery_dl:
                         result = await self.gallery_dl.download(job.url, job.platform, job.user_id, job.job_id, progress_callback=progress_callback)
                    else:
                         result = {'success': False, 'error': 'Downloader not initialized'}
                    
                    if not result.get('success'):
                        job.status = JobStatus.FAILED
                        job.completed_at = datetime.now()
                        job.error = result.get('error', 'Download failed')
                        job.message = f"Failed: {job.error}"
                        job.save_to_db()
                        await self._notify_status(job)
                        continue
                    
                    job.files = result.get('files', [])
                    if not job.files:
                        job.status = JobStatus.COMPLETED
                        job.completed_at = datetime.now()
                        job.message = result.get('message', 'No content found')
                        job.save_to_db()
                        await self._notify_status(job)
                        continue
                    
                    job.status = JobStatus.UPLOADING
                    job.message = f"Uploading {len(job.files)} files..."
                    job.save_to_db()
                    await self._notify_status(job)
                    
                    await upload_func(job.files)
                    
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now()
                    job.message = f"Delivered {len(job.files)} files"
                    job.save_to_db()
                    await self._notify_status(job)
                    
                except Exception as e:
                    logging.error(f"Job {job.job_id} failed: {e}")
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now()
                    job.error = str(e)
                    job.message = f"Error: {e}"
                    job.save_to_db()
                    await self._notify_status(job)
                
                finally:
                    if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                        self._cleanup_job(job.job_id)
                    self._queue.task_done()
            
            except asyncio.CancelledError: break
            except RuntimeError as e:
                if "Event loop is closed" in str(e): break
                break
            except Exception as e:
                logging.error(f"Worker {worker_id} error: {e}")
    
    def _cleanup_job(self, job_id: str):
        job = self._jobs.pop(job_id, None)
        if job and job.job_dir and os.path.exists(job.job_dir):
            try: shutil.rmtree(job.job_dir)
            except Exception as e: logging.error(f"⚠️ Failed to cleanup directory {job.job_dir}: {e}")
    
    async def _notify_status(self, job: DownloadJob):
        if self.status_callback:
            try: await self.status_callback(job)
            except Exception as e: logging.error(f"Status callback error: {e}")

    async def _background_cleanup(self):
        while self._running:
            try:
                await asyncio.sleep(3600)
                if not os.path.exists(self.download_path): continue
                current_time = time.time()
                for entry in os.scandir(self.download_path):
                    if entry.is_dir():
                        is_active = any(job.job_dir == entry.path for job in self._jobs.values())
                        if is_active: continue
                        try:
                            if current_time - entry.stat().st_mtime > 7200:
                                shutil.rmtree(entry.path)
                        except: pass
            except asyncio.CancelledError: break
            except Exception as e:
                await asyncio.sleep(60)

    def _startup_sweep(self):
        if not os.path.exists(self.download_path): return
        count = 0
        try:
            for entry in os.scandir(self.download_path):
                if entry.is_dir():
                    try:
                        shutil.rmtree(entry.path)
                        count += 1
                    except: pass
        except: pass


download_queue: Optional[DownloadQueue] = None

def get_queue() -> DownloadQueue:
    global download_queue
    if download_queue is None:
        download_queue = DownloadQueue()
    return download_queue

async def init_queue(
    snapchat_downloader,
    gallery_dl_downloader,
    max_concurrent: int = 10,
    max_per_user: int = 20,
    status_callback: Optional[Callable] = None
):
    global download_queue
    download_queue = DownloadQueue(
        max_concurrent=max_concurrent,
        max_per_user=max_per_user,
        status_callback=status_callback
    )
    download_queue.snapchat = snapchat_downloader
    download_queue.gallery_dl = gallery_dl_downloader
    await download_queue.start()
    return download_queue
