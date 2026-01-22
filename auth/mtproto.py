"""MTProto client for uploading large files (>50MB) using Pyrogram."""

import os
import logging
import asyncio
from typing import Optional

# Lazily loaded imports
PYROGRAM_AVAILABLE = None
Client = None

def _ensure_pyrogram():
    """Import pyrogram only when needed to avoid early event loop errors."""
    global PYROGRAM_AVAILABLE, Client
    if PYROGRAM_AVAILABLE is not None:
        return PYROGRAM_AVAILABLE
    
    try:
        from pyrogram import Client as PClient
        Client = PClient
        PYROGRAM_AVAILABLE = True
    except ImportError:
        PYROGRAM_AVAILABLE = False
    return PYROGRAM_AVAILABLE


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
        phone_number: Optional[str] = None,
        session_path: str = './sessions'
    ):
        """
        Initialize MTProto client for user account (2GB upload limit).
        
        Args:
            api_id: Telegram API ID from my.telegram.org
            api_hash: Telegram API hash from my.telegram.org
            phone_number: Phone number for user authentication
            session_path: Directory to store session files
        """
        self.api_id = api_id or os.getenv('TELEGRAM_API_ID')
        self.api_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        self.phone_number = phone_number or os.getenv('TELEGRAM_PHONE_NUMBER')
        self.session_path = session_path
        self.client: Optional[Client] = None
        self._is_connected = False
        
        # Callbacks for interactive authentication (set by bot)
        self.code_callback = None  # async function that returns the code
        self.password_callback = None  # async function that returns 2FA password
        
        os.makedirs(session_path, exist_ok=True)
    
    @property
    def is_configured(self) -> bool:
        """Check if MTProto credentials are configured."""
        return bool(self.api_id and self.api_hash and self.phone_number and _ensure_pyrogram())
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._is_connected and self.client is not None
    
    async def start(self) -> bool:
        """
        Start the MTProto client using user session.
        
        Uses existing session if available, otherwise authenticates interactively
        using provided callbacks for code entry.
        
        Returns:
            True if started successfully, False otherwise
        """
        if not _ensure_pyrogram():
            logging.warning("⚠️ Pyrogram not installed. Run: pip install pyrogram")
            return False
        
        if not self.is_configured:
            logging.warning("⚠️ MTProto not configured. Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE_NUMBER")
            return False
        
        try:
            session_file = os.path.join(self.session_path, "storyflow_user")
            
            logging.info("📱 Starting MTProto user client...")
            
            self.client = Client(
                session_file,
                api_id=int(self.api_id),
                api_hash=self.api_hash,
                phone_number=self.phone_number
            )
            
            # Set up code and password handlers if callbacks are provided
            if self.code_callback:
                self.client.phone_code = self._code_handler
            if self.password_callback:
                self.client.password = self._password_handler
            
            await self.client.start()
            self._is_connected = True
            
            # Security: Restrict session file permissions
            session_file_path = session_file + ".session"
            if os.path.exists(session_file_path):
                os.chmod(session_file_path, 0o600)
                logging.debug(f"🔒 Session file secured: {session_file_path}")
            
            me = await self.client.get_me()
            logging.info(f"✅ MTProto connected as user: {me.first_name} (@{me.username}) - 2GB upload limit")
            return True
            
        except Exception as e:
            logging.error(f"❌ MTProto connection failed: {e}")
            logging.error(f"   For Docker: Set TELEGRAM_SESSION_STRING in .env")
            logging.error(f"   To generate: Run 'python -m auth.generate_session' locally")
            logging.error(f"   Get API credentials from: https://my.telegram.org/apps")
            self._is_connected = False
            return False
    
    
    async def _code_handler(self):
        """Handler for phone code - calls the callback if set."""
        if self.code_callback:
            logging.info("📲 Requesting authentication code via callback...")
            code = await self.code_callback()
            logging.debug(f"✅ Code received from callback")
            return code
        else:
            # Fallback to console input (shouldn't happen in bot mode)
            logging.warning("⚠️ No code callback set, falling back to console")
            return input("Enter the code you received: ")
    
    async def _password_handler(self):
        """Handler for 2FA password - calls the callback if set."""
        if self.password_callback:
            logging.info("🔐 Requesting 2FA password via callback...")
            password = await self.password_callback()
            logging.debug(f"✅ Password received from callback")
            return password
        else:
            # Fallback to console input (shouldn't happen in bot mode)
            logging.warning("⚠️ No password callback set, falling back to console")
            import getpass
            return getpass.getpass("Enter your 2FA password: ")
    
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
