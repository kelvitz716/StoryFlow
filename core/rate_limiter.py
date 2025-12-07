"""Token bucket rate limiter for API requests."""

import time
import logging
from collections import deque
from threading import Lock


class RateLimiter:
    """Token bucket rate limiter for API requests."""
    
    def __init__(self, max_requests: int, time_window: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds (default: 60)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def wait_if_needed(self) -> None:
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
    
    def get_remaining(self) -> int:
        """Get remaining requests in current window."""
        with self.lock:
            now = time.time()
            # Remove expired entries
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()
            return max(0, self.max_requests - len(self.requests))
