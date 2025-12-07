"""URL platform identification and username extraction."""

import re
import logging
from urllib.parse import urlparse
from typing import Tuple, Optional


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
        
        if len(segments) < 2:
            logging.warning(f"Invalid Snapchat URL format: {url}")
            return None
        
        # Expected patterns: /add/username, /stories/username, /spotlight/username
        action = segments[0].lower()
        
        if action in ('add', 'stories', 'spotlight'):
            username = segments[1]
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


def parse_url(url: str) -> Tuple[str, Optional[str]]:
    """
    Parse URL to identify platform and extract relevant data.
    
    Args:
        url: Input URL
        
    Returns:
        Tuple of (platform, username_or_None)
    """
    platform = identify_platform(url)
    
    if platform == "Snapchat":
        username = extract_snapchat_username(url)
        return platform, username
    
    return platform, None
