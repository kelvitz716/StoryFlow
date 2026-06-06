import re
import logging
from urllib.parse import urlparse
from typing import Tuple, Optional
from core.security import validate_domain, is_safe_url


def identify_platform(url: str) -> str:
    """
    Identify platform using strict domain validation.
    
    Returns:
        - "Snapchat": For snapchat.com URLs
        - "Instagram": For instagram.com URLs
        - "TikTok": For tiktok.com or vm.tiktok.com URLs
        - "Twitter": For twitter.com or x.com URLs
        - "Facebook": For facebook.com or fb.watch URLs
        - "Generic": For other HTTP/HTTPS URLs
        - "Unknown": For unsupported platforms
    """
    if validate_domain(url, ['snapchat.com']):
        return "Snapchat"
    elif validate_domain(url, ['instagram.com']):
        return "Instagram"
    elif validate_domain(url, ['tiktok.com', 'vm.tiktok.com']):
        return "TikTok"
    elif validate_domain(url, ['twitter.com', 'x.com']):
        return "Twitter"
    elif validate_domain(url, ['facebook.com', 'fb.watch']):
        return "Facebook"
    elif url.startswith(('http://', 'https://')) and is_safe_url(url):
        return "Generic"
    else:
        return "Unknown"


def extract_snapchat_username(url: str) -> Optional[str]:
    """
    Extract username from Snapchat URL.
    
    Supported URL patterns:
        - https://www.snapchat.com/add/username
        - https://www.snapchat.com/add/username/
        - https://www.snapchat.com/add/username/l
        - https://snapchat.com/stories/username
        - https://snapchat.com/spotlight/username
    
    Args:
        url: Snapchat URL
        
    Returns:
        Username string or None if extraction fails
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Split path into segments
        segments = [s for s in path.split('/') if s]
        
        # Expected patterns: /add/username, /stories/username, /spotlight/username, /highlight/username, /@username
        
        if len(segments) == 1 and segments[0].startswith('@'):
            return segments[0].lstrip('@')
            
        if len(segments) < 2:
            logging.warning(f"Invalid Snapchat URL format: {url}")
            return None
        
        action = segments[0].lower()
        
        if action in ('add', 'stories', 'spotlight', 'highlight', 'highlights'):
            username = segments[1].lstrip('@')
            # Clean username (remove trailing 'l' from some share links)
            if len(segments) > 2 and segments[2] == 'l':
                pass  # Username is already correct
            return username
        else:
            logging.warning(f"Unrecognized Snapchat URL action: {action}")
            return None
            
    except Exception as e:
        logging.error(f"Failed to extract Snapchat username: {e}")
        return None



