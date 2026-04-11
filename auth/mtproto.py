"""MTProto client for uploading large files (>50MB) using Pyrogram."""

import os
import logging
import asyncio
from typing import Optional

# Lazily loaded imports
PYROGRAM_AVAILABLE = None
Client = None
types = None
from pyrogram.errors import FloodWait

def _ensure_pyrogram():
    """Import pyrogram only when needed to avoid early event loop errors."""
    global PYROGRAM_AVAILABLE, Client, types
    if PYROGRAM_AVAILABLE is not None:
        return PYROGRAM_AVAILABLE
    
    try:
        from pyrogram import Client as PClient, types as PTypes
        Client = PClient
        types = PTypes
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
        session_string: Optional[str] = None,
        session_path: str = './sessions'
    ):
        """
        Initialize MTProto client for user account (2GB upload limit).
        
        Args:
            api_id: Telegram API ID from my.telegram.org
            api_hash: Telegram API hash from my.telegram.org
            phone_number: Phone number for user authentication
            session_string: Pre-authenticated session string (recommended for production)
            session_path: Directory to store session files
        """
        self.api_id = api_id or os.getenv('TELEGRAM_API_ID')
        self.api_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        self.phone_number = phone_number or os.getenv('TELEGRAM_PHONE_NUMBER')
        self.session_string = session_string or os.getenv('TELEGRAM_SESSION_STRING')
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
        # Either session string OR (api creds + phone number)
        has_session = bool(self.session_string and self.api_id and self.api_hash)
        has_interactive = bool(self.api_id and self.api_hash and self.phone_number)
        return (has_session or has_interactive) and _ensure_pyrogram()
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._is_connected and self.client is not None
    
    async def start(self) -> bool:
        """
        Start the MTProto client.
        
        Priority 1: Use session string if available (fast, non-blocking)
        Priority 2: Skip for now (will auth later when needed)
        
        Returns:
            True if started successfully, False otherwise
        """
        if not _ensure_pyrogram():
            logging.warning("⚠️ Pyrogram not installed. Run: pip install pyrogram")
            return False
        
        if not self.is_configured:
            logging.info("ℹ️ MTProto not configured - files >50MB will be skipped")
            return False
        
        try:
            # Priority 1: Use session string (production path)
            if self.session_string:
                logging.info("📱 Starting MTProto with session string...")
                
                self.client = Client(
                    "storyflow_session",
                    api_id=int(self.api_id),
                    api_hash=self.api_hash,
                    session_string=self.session_string,
                    in_memory=True  # Don't save to file
                )
                
                await self.client.start()
                self._is_connected = True
                
                me = await self.client.get_me()
                logging.info(f"✅ MTProto connected as: {me.first_name} (@{me.username}) - 2GB upload limit")
                return True
            
            # Priority 2: Skip for now, will authenticate on first use
            else:
                logging.info("ℹ️ MTProto configured for interactive auth (will authenticate when needed)")
                return False
            
        except Exception as e:
            logging.error(f"❌ MTProto connection failed: {e}")
            self._is_connected = False
            return False
    
    async def authenticate_interactive(self, application=None) -> bool:
        """
        Perform interactive authentication (for first use without session string).
        
        Should be called on-demand when >50MB file needs upload.
        """
        if self._is_connected:
            return True  # Already authenticated
        
        if not self.phone_number:
            logging.error("❌ Phone number required for interactive auth")
            return False
        
        try:
            session_file = os.path.join(self.session_path, "storyflow_user")
            
            logging.info("🔐 MTProto interactive authentication starting...")
            
            self.client = Client(
                session_file,
                api_id=int(self.api_id),
                api_hash=self.api_hash
            )
            
            await self.client.connect()
            
            # Check if already authorized
            try:
                me = await self.client.get_me()
                logging.info(f"✅ MTProto using existing session for {me.first_name}")
                self._is_connected = True
                return True
            except Exception:
                # Need to authenticate
                logging.info("🔐 Sending verification code...")
                
                sent_code = await self.client.send_code(self.phone_number)
                logging.info(f"📲 Verification code sent to {self.phone_number}")
                
                if not self.code_callback:
                    raise Exception("No code callback configured - cannot authenticate")
                
                # Get code via callback
                code = await self._code_handler()
                
                # Sign in
                try:
                    await self.client.sign_in(self.phone_number, sent_code.phone_code_hash, code)
                    logging.info("✅ Signed in successfully!")
                except Exception as e:
                    if "password" in str(e).lower() or "2fa" in str(e).lower():
                        if not self.password_callback:
                            raise Exception("2FA required but no password callback configured")
                        
                        password = await self._password_handler()
                        await self.client.check_password(password)
                        logging.info("✅ 2FA authentication successful!")
                    else:
                        raise
                
                # Secure session file
                session_file_path = session_file + ".session"
                if os.path.exists(session_file_path):
                    os.chmod(session_file_path, 0o600)
                
                me = await self.client.get_me()
                logging.info(f"✅ MTProto authenticated as: {me.first_name} (@{me.username})")
                self._is_connected = True
                return True
                
        except Exception as e:
            logging.error(f"❌ Interactive auth failed: {e}")
            self._is_connected = False
            
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
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
        reply_to_message_id: Optional[int] = None,
        progress_callback=None
    ) -> bool:
        """
        Upload a file using MTProto (supports up to 2GB).
        
        Args:
            chat_id: Telegram chat ID to send to
            file_path: Path to file to upload
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if upload successful, False otherwise
        """
        if not self.is_connected:
            logging.error("❌ MTProto not connected")
            return False
        
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            # Mask chat_id for privacy (show first 3 and last 3 digits)
            masked_chat = f"{str(chat_id)[:3]}***{str(chat_id)[-3:]}" if len(str(chat_id)) > 6 else "***"
            logging.info(f"📤 MTProto uploading {file_size_mb:.1f}MB file to chat_id={masked_chat}...")
            
            # Determine if video or document
            ext = os.path.splitext(file_path)[1].lower()
            is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']
            
            if is_video:
                await self.client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    progress=progress_callback or self._default_progress
                )
            else:
                await self.client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    progress=progress_callback or self._default_progress
                )
            
            logging.info(f"✅ MTProto upload complete!")
            return True
            
        except Exception as e:
            logging.error(f"❌ MTProto upload failed: {e}")
            return False

    async def send_media_group(
        self,
        chat_id: int,
        files: list,
        caption: str = "",
        reply_to_message_id: Optional[int] = None
    ) -> bool:
        """
        Send a media group (album) using MTProto.
        Handles FloodWait automatically.
        """
        if not self.is_connected:
            return False
            
        _ensure_pyrogram()
        media = []
        for file_path in files:
            if not os.path.exists(file_path):
                continue
                
            ext = os.path.splitext(file_path)[1].lower()
            is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']
            
            if is_video:
                media.append(types.InputMediaVideo(media=file_path))
            else:
                media.append(types.InputMediaPhoto(media=file_path))
        
        if not media:
            return False

        # Add caption to first item
        if caption:
            media[0].caption = caption

        # Attempt upload with automatic flood wait logic
        for attempt in range(3):
            try:
                await self.client.send_media_group(
                    chat_id=chat_id,
                    media=media,
                    reply_to_message_id=reply_to_message_id
                )
                logging.info(f"✅ MTProto media group delivered ({len(media)} files)")
                return True
            except FloodWait as e:
                logging.warning(f"⚠️ MTProto FloodWait: Sleeping {e.value}s (Attempt {attempt+1}/3)")
                await asyncio.sleep(e.value)
            except Exception as e:
                logging.error(f"❌ MTProto media group failed: {e}")
                return False
        
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
    
    # Return client even if not connected (for on-demand auth later)
    return _mtproto_client

