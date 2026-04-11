"""Platform-independent storage monitoring utility."""

import shutil
import logging
import os
from typing import Dict, Tuple

def get_storage_info(path: str = ".") -> Dict[str, any]:
    """
    Get storage statistics for the given path.
    
    Returns:
        Dict with total, used, free (in bytes) and percent_used.
    """
    try:
        # Use the parent directory if path doesn't exist yet
        check_path = path
        while not os.path.exists(check_path) and check_path != "/":
            check_path = os.path.dirname(check_path)
            
        total, used, free = shutil.disk_usage(check_path)
        percent = (used / total) * 100
        
        return {
            "total": total,
            "used": used,
            "free": free,
            "percent_used": round(percent, 2),
            "path": os.path.abspath(check_path)
        }
    except Exception as e:
        logging.error(f"Failed to get storage info: {e}")
        return {
            "total": 0,
            "used": 0,
            "free": 0,
            "percent_used": 0,
            "path": path,
            "error": str(e)
        }

def is_storage_critical(path: str = ".", threshold: float = 90.0) -> Tuple[bool, float]:
    """
    Check if storage usage exceeds the threshold.
    
    Args:
        path: Path to check
        threshold: Percentage threshold (0-100)
        
    Returns:
        Tuple of (is_critical, current_percent)
    """
    info = get_storage_info(path)
    percent = info.get("percent_used", 0)
    return percent >= threshold, percent

def format_storage_report(path: str = ".") -> str:
    """Format a human-readable storage report."""
    info = get_storage_info(path)
    
    def to_gb(b):
        return b / (1024**3)
        
    usage_bar = "▓" * (int(info['percent_used'] // 10)) + "░" * (10 - int(info['percent_used'] // 10))
    
    return (
        f"📊 *Storage Report*\n"
        f"📍 Path: `{info['path']}`\n"
        f"📈 Progress: `[{usage_bar}]` {info['percent_used']}%\n"
        f"🆓 Free: `{to_gb(info['free']):.2f} GB` / `{to_gb(info['total']):.2f} GB`"
    )
