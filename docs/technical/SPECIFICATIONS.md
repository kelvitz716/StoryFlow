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

class SnapchatDownloader:
    """Handler for Snapchat downloads using SnapStory DL API."""
    
    def __init__(self, api_base_url: str, api_key: Optional[str] = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_key = api_key
        self.rate_limiter = RateLimiter(
            max_requests=int(os.getenv('MAX_REQUESTS_PER_MINUTE', 30))
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StoryFlow/1.0',
            'Accept': 'application/json'
        })
    
    @create_retry_decorator()
    async def download(self, url: str, user_id: Optional[str] = None, job_id: Optional[str] = None) -> Dict:
        """
        Download Snapchat story using SnapStory DL API (Async).
        
        Args:
            url: Snapchat story URL
            user_id: Telegram user ID
            job_id: Unique job identifier for directory isolation
            
        Returns:
            Dict containing status and media information
        """
        self.rate_limiter.wait_if_needed()
        
        try:
            # Construct API request
            api_endpoint = f"{self.api_base_url}/download"
            params = {'url': url}
            
            if self.api_key:
                params['api_key'] = self.api_key
            
            logging.info(f"📡 Requesting Snapchat story from API...")
            
            # Make API request with timeout
            response = self.session.get(
                api_endpoint,
                params=params,
                timeout=30
            )
            
            # Check HTTP status
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            
            if data.get('success') or data.get('status') == 'success':
                media_url = data.get('media_url') or data.get('download_url')
                
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

class GalleryDLDownloader:
    """Handler for general media downloads using gallery-dl."""
    
    def __init__(self, output_path: str = './downloads', cookie_path: str = './cookies'):
        self.output_path = output_path
        self.cookie_path = cookie_path
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(cookie_path, exist_ok=True)
    
    async def download(self, url: str, platform: str, user_id: Optional[str] = None, job_id: Optional[str] = None, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Download media using gallery-dl with job isolation (Async).
        
        Args:
            url: Media URL
            platform: Platform name (Instagram, TikTok, etc.)
            user_id: User ID for cookie lookup
            job_id: Unique job identifier
            progress_callback: Optional callback for status updates
            
        Returns:
            Dict containing status and download information
        """
        # Determine job-specific output path
        job_output_path = os.path.join(self.output_path, job_id) if job_id else self.output_path
        os.makedirs(job_output_path, exist_ok=True)
        try:
            command = self._build_command(url, platform, user_id)
            
            logging.info(f"📥 Downloading {platform} content via gallery-dl...")
            logging.debug(f"Command: {' '.join(command)}")
            
            # Execute gallery-dl with retry logic
            result = self._execute_with_retry(command)
            
            if result['success']:
                logging.info(f"✅ {platform} content downloaded successfully!")
                return result
            else:
                logging.error(f"❌ Download failed: {result.get('error')}")
                return result
                
        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")
            return {
                'success': False,
                'error': 'Unexpected error',
                'details': str(e)
            }
    
    def _build_command(self, url: str, platform: str, user_id: Optional[str]) -> list:
        """Build gallery-dl command with appropriate options."""
        command = [
            'gallery-dl',
            '-d', self.output_path,
            '--no-mtime',  # Don't set file modification time
        ]
        
        # Add cookie support for Instagram
        if platform == "Instagram" and user_id:
            cookie_file = os.path.join(self.cookie_path, f"instagram_{user_id}.txt")
            if os.path.exists(cookie_file):
                logging.info(f"🍪 Using cookies for authentication: {cookie_file}")
                command.extend(['--cookies', cookie_file])
            else:
                logging.warning(f"⚠️ No cookie file found for user {user_id}")
        
        # Add URL as final argument
        command.append(url)
        
        return command
    
    def _execute_with_retry(self, command: list, max_attempts: int = 3) -> Dict:
        """Execute command with retry logic."""
        for attempt in range(1, max_attempts + 1):
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=300  # 5 minutes timeout
                )
                
                return {
                    'success': True,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
                
            except subprocess.CalledProcessError as e:
                logging.warning(f"⚠️ Attempt {attempt}/{max_attempts} failed")
                logging.debug(f"Exit code: {e.returncode}")
                logging.debug(f"STDERR: {e.stderr}")
                
                # Check if it's an authentication error
                if 'login' in e.stderr.lower() or 'authentication' in e.stderr.lower():
                    return {
                        'success': False,
                        'error': 'Authentication required',
                        'details': 'Please upload cookies.txt file',
                        'stderr': e.stderr
                    }
                
                # Retry on network errors
                if attempt < max_attempts and self._is_retryable_error(e.stderr):
                    wait_time = 2 ** attempt  # Exponential backoff
                    logging.info(f"⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                return {
                    'success': False,
                    'error': f'gallery-dl failed (exit code {e.returncode})',
                    'stderr': e.stderr
                }
                
            except subprocess.TimeoutExpired:
                logging.error(f"❌ Timeout after 5 minutes")
                return {
                    'success': False,
                    'error': 'Download timeout',
                    'details': 'Process exceeded 5 minute limit'
                }
        
        return {
            'success': False,
            'error': 'Max retry attempts reached'
        }
    
    def _is_retryable_error(self, stderr: str) -> bool:
        """Check if error is retryable."""
        retryable_keywords = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'rate limit'
        ]
        stderr_lower = stderr.lower()
        return any(keyword in stderr_lower for keyword in retryable_keywords)
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