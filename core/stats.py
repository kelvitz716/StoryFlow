"""SQLite-based statistics manager."""

import logging
from typing import Dict, Any
from core.database import db

class StatsManager:
    """Manages user statistics via SQLite."""
    
    def increment_download(self, user_id: str, platform: str):
        """Increment download count for a user and platform atomically."""
        uid = str(user_id)
        plat = str(platform)
        try:
            with db.get_conn() as conn:
                # Upsert user total
                conn.execute("""
                    INSERT INTO user_stats (user_id, total_downloads)
                    VALUES (?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET total_downloads = total_downloads + 1
                """, (uid,))
                
                # Upsert platform total
                conn.execute("""
                    INSERT INTO platform_stats (user_id, platform, downloads)
                    VALUES (?, ?, 1)
                    ON CONFLICT(user_id, platform) DO UPDATE SET downloads = downloads + 1
                """, (uid, plat))
        except Exception as e:
            logging.error(f"Failed to increment stats: {e}")
        
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get stats for a specific user."""
        uid = str(user_id)
        result = {
            "total_downloads": 0,
            "platforms": {}
        }
        try:
            with db.get_conn() as conn:
                # Get total
                cur = conn.execute("SELECT total_downloads FROM user_stats WHERE user_id = ?", (uid,))
                row = cur.fetchone()
                if row:
                    result["total_downloads"] = row["total_downloads"]
                
                # Get platforms
                cur = conn.execute("SELECT platform, downloads FROM platform_stats WHERE user_id = ?", (uid,))
                for row in cur.fetchall():
                    result["platforms"][row["platform"]] = row["downloads"]
                    
        except Exception as e:
            logging.error(f"Failed to fetch stats: {e}")
            
        return result

# Global instance
stats_manager = StatsManager()
