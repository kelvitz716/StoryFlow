"""MTProto client for uploading large files (>50MB) using Pyrogram."""

import os
import logging
import asyncio
from typing import Optional

try:
    from pyrogram import Client
    from pyrogram.errors import SessionPasswordNeeded
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    Client = None


class MTProtoClient:
    """
    MTProto client wrapper for large file uploads.
    
    Uses Pyrogram to upload files up to 2GB (vs 50MB bot limit).
    Requires API_ID and API_HASH from my.telegram.org
    """
    
    def __init__(
        self,
        api_id: Optional[str] = None,
        api_hash: Optional[str] = None,
        session_path: str = './sessions'
    ):
        """
        Initialize MTProto client.
        
        Args:
            api_id: Telegram API ID from my.telegram.org
            api_hash: Telegram API hash from my.telegram.org
            session_path: Directory to store session files
        """
        self.api_id = api_id or os.getenv('TELEGRAM_API_ID')
        self.api_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        self.session_path = session_path
        self.client: Optional[Client] = None
        self._is_connected = False
        
        os.makedirs(session_path, exist_ok=True)
    
    @property
    def is_configured(self) -> bool:
        """Check if MTProto credentials are configured."""
        return bool(self.api_id and self.api_hash and PYROGRAM_AVAILABLE)
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._is_connected and self.client is not None
    
    async def start(self) -> bool:
        """
        Start the MTProto client.
        
        Returns:
            True if started successfully, False otherwise
        """
        if not PYROGRAM_AVAILABLE:
            logging.warning("⚠️ Pyrogram not installed. Run: pip install pyrogram")
            return False
        
        if not self.is_configured:
            logging.warning("⚠️ MTProto not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH")
            return False
        
        try:
            session_file = os.path.join(self.session_path, "storyflow_user")
            
            self.client = Client(
                session_file,
                api_id=int(self.api_id),
                api_hash=self.api_hash,
            )
            
            await self.client.start()
            self._is_connected = True
            
            me = await self.client.get_me()
            logging.info(f"✅ MTProto connected as {me.first_name} (@{me.username})")
            return True
            
        except Exception as e:
            logging.error(f"❌ MTProto connection failed: {e}")
            self._is_connected = False
            return False
    
    async def stop(self):
        """Stop the MTProto client."""
        if self.client and self._is_connected:
            await self.client.stop()
            self._is_connected = False
            logging.info("📴 MTProto disconnected")
    
    async def upload_file(
        self,
        chat_id: int,
        file_path: str,
        caption: str = "",
        progress_callback=None
    ) -> bool:
        """
        Upload a file using MTProto (supports up to 2GB).
        
        Args:
            chat_id: Telegram chat ID to send to
            file_path: Path to file to upload
            caption: Optional caption
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if upload successful, False otherwise
        """
        if not self.is_connected:
            logging.error("❌ MTProto not connected")
            return False
        
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logging.info(f"📤 MTProto uploading {file_size_mb:.1f}MB file...")
            
            # Determine if video or document
            ext = os.path.splitext(file_path)[1].lower()
            is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']
            
            if is_video:
                await self.client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption,
                    progress=progress_callback or self._default_progress
                )
            else:
                await self.client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    caption=caption,
                    progress=progress_callback or self._default_progress
                )
            
            logging.info(f"✅ MTProto upload complete!")
            return True
            
        except Exception as e:
            logging.error(f"❌ MTProto upload failed: {e}")
            return False

    async def _default_progress(self, current, total):
        """Default progress callback for uploads."""
        try:
            percent = current * 100 / total
            # Log every 10% to avoid spam
            if int(percent) % 10 == 0 and int(percent) > 0:
                logging.info(f"📤 Uploading: {percent:.1f}% ({current/1024/1024:.1f}/{total/1024/1024:.1f} MB)")
        except:
            pass



# Global instance
_mtproto_client: Optional[MTProtoClient] = None


def get_mtproto_client() -> Optional[MTProtoClient]:
    """Get the global MTProto client instance."""
    global _mtproto_client
    return _mtproto_client


async def init_mtproto() -> Optional[MTProtoClient]:
    """
    Initialize and start the global MTProto client.
    
    Returns:
        MTProtoClient if successful, None otherwise
    """
    global _mtproto_client
    
    _mtproto_client = MTProtoClient()
    
    if not _mtproto_client.is_configured:
        logging.info("ℹ️ MTProto not configured (optional - for files >50MB)")
        return None
    
    success = await _mtproto_client.start()
    return _mtproto_client if success else None
