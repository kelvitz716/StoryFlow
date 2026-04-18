# 🚀 StoryFlow: Complete Technical Specification

## Project Overview
**StoryFlow** is a robust Python CLI/Telegram bot that acts as a unified media gateway with advanced error handling, rate limiting, and authentication support.

---

## 1. Dependencies & Installation

```bash
# Core dependencies
pip install requests urllib3 python-dotenv tenacity

# External utilities (system-wide)
pip install gallery-dl

# For Telegram bot (optional)
pip install python-telegram-bot
```

### Required Packages

| Package | Version | Purpose |
|---------|---------|---------|
| `requests` | ≥2.31.0 | HTTP client for API communication |
| `urllib3` | ≥2.0.0 | Advanced HTTP connection pooling |
| `python-dotenv` | ≥1.0.0 | Environment variable management |
| `tenacity` | ≥8.2.0 | Retry logic with exponential backoff |
| `gallery-dl` | ≥1.26.0 | Multi-platform media downloader |
| `python-telegram-bot` | ≥20.0 | Telegram bot framework (if using bot mode) |

---

## 2. Environment Configuration

Create a `.env` file:

```env
# Snapchat API Configuration
SNAPCHAT_API_BASE_URL=https://snapstories.netlify.app/api
SNAPCHAT_API_KEY=your_api_key_here

# Download Configuration
DOWNLOAD_PATH=./downloads
COOKIE_PATH=./cookies

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=30
RETRY_MAX_ATTEMPTS=3
RETRY_INITIAL_WAIT=2
RETRY_MAX_WAIT=60

# Telegram Bot (Optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

---

## 3. Core Architecture

### 3.1 URL Platform Identification

**Function:** `identify_platform(url: str) -> str`

```python
from urllib.parse import urlparse

def identify_platform(url: str) -> str:
    """
    Identify platform from URL using robust hostname parsing.
    
    Returns:
        - "Snapchat": For snapchat.com URLs
        - "Instagram": For instagram.com URLs
        - "TikTok": For tiktok.com or vm.tiktok.com URLs
        - "Twitter": For twitter.com or x.com URLs
        - "Facebook": For facebook.com or fb.watch URLs
        - "Unknown": For unsupported platforms
        - "Error": For invalid URLs
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()
        
        if not hostname:
            return "Error"
        
        # Remove www. prefix if present
        hostname = hostname.replace('www.', '')
        
        # Platform matching
        if 'snapchat.com' in hostname:
            return "Snapchat"
        elif 'instagram.com' in hostname:
            return "Instagram"
        elif 'tiktok.com' in hostname or 'vm.tiktok.com' in hostname:
            return "TikTok"
        elif 'twitter.com' in hostname or 'x.com' in hostname:
            return "Twitter"
        elif 'facebook.com' in hostname or 'fb.watch' in hostname:
            return "Facebook"
        else:
            return "Unknown"
            
    except Exception as e:
        logging.error(f"URL parsing error: {e}")
        return "Error"
```

### 3.2 Multi-Platform Downloader Base

**Class:** `BaseDownloader`

All platform-specific downloaders inherit from this base class to ensure consistent directory isolation, safe subprocess execution, and unified error handling.

```python
class BaseDownloader:
    """Consolidated base for all media downloaders."""
    
    def __init__(self, output_path: str):
        self.output_path = output_path
        os.makedirs(output_path, exist_ok=True)

    def _prepare_job_directory(self, job_id: str) -> str:
        """Isolated sandbox for every download task."""
        job_dir = os.path.join(self.output_path, job_id)
        os.makedirs(job_dir, exist_ok=True)
        return job_dir

    async def _execute_with_retry(self, command: list, process_name: str, max_attempts: int = 3) -> Dict:
        """Unified async execution with timeout and retry logic."""
        # Uses asyncio.create_subprocess_exec with 5-minute timeouts
        # Implements exponential backoff and platform-agnostic failure detection
```

---

## 4. Rate Limiting & Retry Strategy

### 4.1 Rate Limiter Implementation

```python
import time
from collections import deque
from threading import Lock

class RateLimiter:
    """Token bucket rate limiter for API requests."""
    
    def __init__(self, max_requests: int, time_window: int = 60):
        """
        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds (default: 60)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def wait_if_needed(self):
        """Block if rate limit would be exceeded."""
        with self.lock:
            now = time.time()
            
            # Remove requests outside time window
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()
            
            # Check if we need to wait
            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[0])
                if sleep_time > 0:
                    logging.info(f"⏳ Rate limit reached. Waiting {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    self.requests.popleft()
            
            # Record this request
            self.requests.append(time.time())
```

### 4.2 Retry Decorator with Exponential Backoff

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import logging

# Configure retry strategy
def create_retry_decorator(max_attempts=3, initial_wait=2, max_wait=60):
    """Create a retry decorator with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=initial_wait, max=max_wait),
        retry=retry_if_exception_type((
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError
        )),
        before_sleep=before_sleep_log(logging.getLogger(), logging.WARNING),
        reraise=True
    )
```

---

## 5. Snapchat Download Handler

### 5.1 SnapStory DL API Integration

```python
import requests
import os
import logging
from typing import Optional, Dict

class SnapchatDownloader(BaseDownloader):
    """Handler for Snapchat downloads using SnapStory DL API."""
    
    def __init__(self, api_base_url: str, output_path: str = './downloads'):
        super().__init__(output_path)
        self.api_base_url = api_base_url.rstrip('/')
        self.rate_limiter = RateLimiter(max_requests=30)
        self.session = requests.Session()
    
    async def download(self, url: str, job_id: str) -> Dict:
        """
        Unified download entry point (Async).
        Wraps the synchronous API requests in a thread executor.
        """
        username = extract_username(url)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.download_stories, username, job_id)
```
                
                if media_url:
                    # Download actual media file
                    filename = self._download_media_file(media_url, output_path)
                    
                    logging.info(f"✅ Snapchat story downloaded: {filename}")
                    return {
                        'success': True,
                        'platform': 'Snapchat',
                        'filename': filename,
                        'media_url': media_url
                    }
                else:
                    raise ValueError("No media URL in API response")
            else:
                error_msg = data.get('error') or data.get('message') or 'Unknown error'
                raise ValueError(f"API returned error: {error_msg}")
                
        except requests.exceptions.HTTPError as e:
            logging.error(f"❌ HTTP Error {e.response.status_code}: {e.response.text}")
            return {
                'success': False,
                'error': f"HTTP {e.response.status_code}",
                'details': e.response.text
            }
            
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error: {e}")
            return {
                'success': False,
                'error': 'Network error',
                'details': str(e)
            }
            
        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {
                'success': False,
                'error': 'Unexpected error',
                'details': str(e)
            }
    
    def _download_media_file(self, media_url: str, output_path: str) -> str:
        """Download media file from direct URL."""
        os.makedirs(output_path, exist_ok=True)
        
        response = self.session.get(media_url, stream=True, timeout=60)
        response.raise_for_status()
        
        # Generate filename
        filename = os.path.join(
            output_path,
            f"snapchat_{int(time.time())}.mp4"
        )
        
        # Download with progress
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return filename
```

---

## 6. Gallery-DL Handler with Cookie Support

### 6.1 Gallery-DL Downloader

```python
import subprocess
import os
import logging
from typing import Optional, Dict

class GalleryDLDownloader(BaseDownloader):
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies'):
        super().__init__(output_path)
        self.cookie_path = cookie_path
    
    async def download(self, url: str, platform: str, user_id: str, job_id: str) -> Dict:
        """
        Modernized async downloader with automatic directory sandboxing.
        """
        job_dir = self._prepare_job_directory(job_id)
        files_before = self._get_download_files(job_dir)
        
        command = self._build_command(url, platform, user_id, job_dir)
        result = await self._execute_with_retry(command, process_name="gallery-dl")
        
        # Post-download: Diff directory to identify new files
        # Includes automatic yt-dlp fallback logic...
```
```

---

## 7. Cookie Management for Instagram

### 7.1 Cookie Handler

```python
import os
import shutil
from typing import Optional

class CookieManager:
    """Manage cookie files for authenticated downloads."""
    
    def __init__(self, cookie_path: str = './cookies'):
        self.cookie_path = cookie_path
        os.makedirs(cookie_path, exist_ok=True)
    
    def save_cookie_file(self, user_id: str, platform: str, file_path: str) -> Dict:
        """
        Save uploaded cookie file for user.
        
        Args:
            user_id: User identifier (Telegram user ID)
            platform: Platform name (e.g., "instagram")
            file_path: Path to uploaded cookie file
            
        Returns:
            Dict with success status
        """
        try:
            # Validate cookie file
            if not self._validate_cookie_file(file_path):
                return {
                    'success': False,
                    'error': 'Invalid cookie file format'
                }
            
            # Destination path
            dest_file = os.path.join(
                self.cookie_path,
                f"{platform.lower()}_{user_id}.txt"
            )
            
            # Copy file
            shutil.copy2(file_path, dest_file)
            
            logging.info(f"✅ Cookie file saved for user {user_id}")
            return {
                'success': True,
                'cookie_file': dest_file
            }
            
        except Exception as e:
            logging.error(f"❌ Failed to save cookie file: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _validate_cookie_file(self, file_path: str) -> bool:
        """Validate cookie file format (Netscape format)."""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                # Basic validation: check for cookie structure
                return '# Netscape HTTP Cookie File' in content or '\t' in content
        except Exception:
            return False
    
    def get_cookie_file(self, user_id: str, platform: str) -> Optional[str]:
        """Get cookie file path for user if exists."""
        cookie_file = os.path.join(
            self.cookie_path,
            f"{platform.lower()}_{user_id}.txt"
        )
        return cookie_file if os.path.exists(cookie_file) else None
    
    def delete_cookie_file(self, user_id: str, platform: str) -> bool:
        """Delete cookie file for user."""
        cookie_file = self.get_cookie_file(user_id, platform)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
            logging.info(f"🗑️ Deleted cookie file for user {user_id}")
            return True
        return False
```

---

## 8. Main Application Flow

### 8.1 CLI Mode

```python
import os
import logging
from dotenv import load_dotenv

def main_cli():
    """Main CLI execution loop."""
    # Load environment variables
    load_dotenv()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Initialize components
    snapchat = SnapchatDownloader(
        api_base_url=os.getenv('SNAPCHAT_API_BASE_URL'),
        api_key=os.getenv('SNAPCHAT_API_KEY')
    )
    
    gallery_dl = GalleryDLDownloader(
        output_path=os.getenv('DOWNLOAD_PATH', './downloads'),
        cookie_path=os.getenv('COOKIE_PATH', './cookies')
    )
    
    print("🎬 StoryFlow Media Downloader")
    print("=" * 50)
    print("Supported: Snapchat, Instagram, TikTok, Twitter/X, Facebook")
    print("Type 'quit' or 'exit' to close")
    print("=" * 50)
    
    while True:
        try:
            # Get user input
            url = input("\n📎 Enter URL: ").strip()
            
            # Check exit condition
            if url.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            
            if not url:
                continue
            
            # Identify platform
            platform = identify_platform(url)
            
            # Dispatch to appropriate handler
            if platform == "Snapchat":
                result = snapchat.download_story(url)
                
            elif platform in ["Instagram", "TikTok", "Twitter", "Facebook"]:
                result = gallery_dl.download(url, platform)
                
            elif platform == "Unknown":
                print("🚫 Unsupported platform.")
                print("Supported: Snapchat, Instagram, TikTok, Twitter/X, Facebook")
                continue
                
            elif platform == "Error":
                print("❌ Invalid URL format.")
                print("Please enter a complete URL (e.g., https://...)")
                continue
            
            # Display result
            if result.get('success'):
                print(f"✅ Download successful!")
                if result.get('filename'):
                    print(f"📁 File: {result['filename']}")
            else:
                print(f"❌ Download failed: {result.get('error', 'Unknown error')}")
                if result.get('details'):
                    print(f"Details: {result['details']}")
                    
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
            
        except Exception as e:
            logging.error(f"Unexpected error: {e}", exc_info=True)
            print(f"⚠️ An error occurred. Please try again.")

if __name__ == "__main__":
    main_cli()
```

---

### 9.1 Modular Application Structure

The bot is divided into several modules to improve maintainability:

1.  `bot/handlers.py`: Command routing and specialized input handling (URLs, auth, documents).
2.  `bot/menus.py`: Inline keyboard generation and navigation flow.
3.  `bot/uploader.py`: Media batching, delivery logic, and MTProto support.
4.  `bot/telegram_bot.py`: Entry point and component orchestration.

### 9.2 Download Job Flow

```python
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... identification logic ...
    
    # Submit to Queue
    job = await download_queue.submit(
        user_id=user_id,
        url=url,
        platform=platform,
        upload_func=upload_func
    )
```

---

## 10. Error Handling Summary

### Error Types & Responses

| Error Type | Handler | Response |
|------------|---------|----------|
| Invalid URL | `identify_platform()` | Return "Error", display format help |
| Unsupported Platform | `identify_platform()` | Return "Unknown", list supported platforms |
| Rate Limit | `RateLimiter` | Auto-wait with progress message |
| Network Timeout | Retry decorator | Auto-retry 3x with exponential backoff |
| API Error (4xx/5xx) | Exception handler | Log status + message, return error dict |
| Auth Required | gallery-dl STDERR | Prompt for cookies.txt upload |
| Download Timeout | subprocess timeout | Kill process, return timeout error |
| Invalid Cookie File | `CookieManager` | Reject file, display format requirements |

---

## 11. Usage Examples

### CLI Mode
```bash
python storyflow.py

# Enter URL: https://www.snapchat.com/story/...
# ✅ Download successful!

# Enter URL: https://www.instagram.com/p/...
# 🔒 Authentication required. Please run cookie setup.
```

### Telegram Bot Mode
```bash
MODE=telegram python storyflow.py

# User sends: https://www.instagram.com/reel/...
# Bot: 🔒 Authentication required
#      Use /upload_cookies to upload cookies.txt

# User sends: /upload_cookies
# User uploads: cookies.txt
# Bot: ✅ Cookies saved! Try downloading again.
```

---

## 12. Security Considerations

✅ **Never hardcode API keys** - use environment variables
✅ **Validate all user input** - URLs, file uploads
✅ **Prevent shell injection** - use list-based command construction
✅ **Rate limit API calls** - protect against abuse
✅ **Secure cookie storage** - user-specific files with restricted permissions
✅ **Timeout all operations** - prevent hanging processes
✅ **Log security events** - authentication attempts, failed uploads
✅ **Clean temporary files** - remove after processing

---

## 13. Testing Checklist

- [ ] Test each platform URL
- [ ] Test rate limiting behavior
- [ ] Test retry on network failure
- [ ] Test Instagram without cookies (should fail gracefully)
- [ ] Test Instagram with valid cookies
- [ ] Test invalid URLs
- [ ] Test unsupported platforms
- [ ] Test cookie file upload (valid/invalid)
- [ ] Test Telegram bot commands
- [ ] Test concurrent downloads
- [ ] Test timeout scenarios
- [ ] Test error logging