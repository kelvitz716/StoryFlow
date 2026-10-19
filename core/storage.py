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
        check_path = os.path.abspath(path or ".")
        while not os.path.exists(check_path):
            parent = os.path.dirname(check_path)
            if parent == check_path:
                break
            check_path = parent
            
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


def get_directory_size(path: str = ".") -> Tuple[int, int]:
    """
    Calculate the total size in bytes and number of top-level items in a directory.

    Returns:
        Tuple of (total_bytes, item_count)
    """
    total_size = 0
    item_count = 0
    if not path or not os.path.exists(path) or not os.path.isdir(path):
        return 0, 0
    try:
        for entry in os.scandir(path):
            item_count += 1
            try:
                if entry.is_file(follow_symlinks=False):
                    total_size += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    for root, _, files in os.walk(entry.path):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                total_size += os.path.getsize(fp)
                            except OSError:
                                pass
            except OSError:
                pass
    except OSError:
        pass
    return total_size, item_count


def format_size(size_bytes: float) -> str:
    """Format bytes into a human-readable string (B, KB, MB, GB, TB)."""
    try:
        val = float(size_bytes)
    except (ValueError, TypeError):
        return "0 B"
    if val <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if round(val, 1) >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.1f} {units[unit_idx]}"

