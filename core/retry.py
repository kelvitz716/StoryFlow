"""Retry decorator with exponential backoff using tenacity."""

import logging
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)


def create_retry_decorator(max_attempts: int = 3, initial_wait: int = 2, max_wait: int = 60):
    """
    Create a retry decorator with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        initial_wait: Initial wait time in seconds
        max_wait: Maximum wait time in seconds
        
    Returns:
        Configured retry decorator
    """
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


# Pre-configured default decorator
default_retry = create_retry_decorator()
