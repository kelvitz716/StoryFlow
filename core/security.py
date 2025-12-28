"""Security utilities for input validation and sanitization."""

import re
import logging
from urllib.parse import urlparse, urlunparse

def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal and invalid characters.
    
    Args:
        filename: Unsafe filename string
        
    Returns:
        Safe filename string (alphanumeric, -, _)
    """
    # Remove null bytes
    filename = filename.replace('\0', '')
    
    # Replace invalid chars with underscore
    # Allow alphanumeric, underscore, hyphen, and period
    cleaned = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    
    # Remove leading/trailing periods/spaces
    cleaned = cleaned.strip('. ')
    
    # Ensure it's not empty or just dots
    if not cleaned or cleaned.replace('.', '') == '':
        cleaned = 'unnamed_file'
        
    return cleaned

def validate_domain(url: str, allowed_domains: list[str]) -> bool:
    """
    Strictly validate that a URL belongs to allowed domains.
    
    Args:
        url: Input URL
        allowed_domains: List of allowed domains (e.g. ['snapchat.com'])
        
    Returns:
        True if valid, False otherwise
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()
        if not hostname:
            return False
            
        # Remove port if present
        if ':' in hostname:
            hostname = hostname.split(':')[0]
            
        # Remove www.
        hostname = hostname.replace('www.', '')
        
        for domain in allowed_domains:
            if hostname == domain or hostname.endswith('.' + domain):
                return True
                
        return False
        
    except Exception:
        return False

def mask_sensitive_url(url: str) -> str:
    """
    Mask sensitive query parameters in a URL for logging.
    
    Args:
        url: Full URL
        
    Returns:
        URL with sensitive params replaced by ***
    """
    try:
        parsed = urlparse(url)
        
        # If it's a media URL with signature, mask complex query params
        # For simplicity, we just say if there's a query, we mask values
        # but keep keys to help debugging
        if parsed.query:
            # Reconstruct masked query
            # We don't parse_qs because it handles multiple values; manual split is safer for preservation
            pairs = parsed.query.split('&')
            masked_pairs = []
            for pair in pairs:
                if '=' in pair:
                    key, _ = pair.split('=', 1)
                    # Mask everything except known safe keys (e.g. 'v' for youtube)
                    if key in ('v', 'id', 'p'):
                        masked_pairs.append(pair)
                    else:
                        masked_pairs.append(f"{key}=***")
                else:
                    masked_pairs.append(pair)
            
            new_query = '&'.join(masked_pairs)
            parsed = parsed._replace(query=new_query)
            
        return urlunparse(parsed)
        
    except Exception:
        return "Checking URL..." # Fallback
