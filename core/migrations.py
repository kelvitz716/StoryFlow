"""Database migration tools (JSON to SQLite)."""
import json
import os
import logging
from core.database import Database

def run_migrations(db: Database):
    """Run one-time migrations from legacy JSON files to SQLite database."""
    logging.info("🔍 Checking for legacy JSON databases...")
    
    # 1. Migrate Users
    if os.path.exists("data/allowed_users.json"):
        try:
            with open("data/allowed_users.json", "r") as f:
                data = json.load(f)
            users = data.get("allowed_users", [])
            with db.get_conn() as conn:
                for uid in users:
                    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(uid),))
            os.rename("data/allowed_users.json", "data/allowed_users.json.bak")
            logging.info(f"✅ Migrated {len(users)} allowed users to SQLite.")
        except Exception as e:
            logging.error(f"❌ Migration error (users): {e}")

    # 2. Migrate Stats
    if os.path.exists("data/stats.json"):
        try:
            with open("data/stats.json", "r") as f:
                stats = json.load(f)
            with db.get_conn() as conn:
                for uid, stat in stats.items():
                    uid_str = str(uid)
                    conn.execute("INSERT OR REPLACE INTO user_stats (user_id, total_downloads) VALUES (?, ?)", 
                                 (uid_str, stat.get("total_downloads", 0)))
                    for plat, count in stat.get("platforms", {}).items():
                         conn.execute("INSERT OR REPLACE INTO platform_stats (user_id, platform, downloads) VALUES (?, ?, ?)",
                                      (uid_str, plat, count))
            os.rename("data/stats.json", "data/stats.json.bak")
            logging.info(f"✅ Migrated stats for {len(stats)} users to SQLite.")
        except Exception as e:
            logging.error(f"❌ Migration error (stats): {e}")
