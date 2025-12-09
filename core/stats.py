"""Simple JSON-based statistics manager."""

import os
import json
import logging
from typing import Dict, Any

STATS_FILE = "data/stats.json"

class StatsManager:
    """Manages user statistics."""
    
    def __init__(self):
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        self._stats = self._load_stats()
        
    def _load_stats(self) -> Dict[str, Any]:
        """Load stats from JSON file."""
        if not os.path.exists(STATS_FILE):
            return {}
        try:
            with open(STATS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load stats: {e}")
            return {}
            
    def _save_stats(self):
        """Save stats to JSON file."""
        try:
            with open(STATS_FILE, 'w') as f:
                json.dump(self._stats, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save stats: {e}")

    def increment_download(self, user_id: str, platform: str):
        """Increment download count for a user and platform."""
        user_id = str(user_id)
        
        if user_id not in self._stats:
            self._stats[user_id] = {
                "total_downloads": 0,
                "platforms": {}
            }
            
        user_stats = self._stats[user_id]
        user_stats["total_downloads"] += 1
        
        # Function-level platform stats
        if platform not in user_stats["platforms"]:
            user_stats["platforms"][platform] = 0
        user_stats["platforms"][platform] += 1
        
        self._save_stats()
        
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get stats for a specific user."""
        return self._stats.get(str(user_id), {
            "total_downloads": 0,
            "platforms": {}
        })

# Global instance
stats_manager = StatsManager()
