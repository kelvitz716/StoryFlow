"""
Access Manager for controlling user access to the bot using SQLite.
"""
import logging
from typing import List
from core.database import db

class AccessManager:
    """Manages allowed users and admin access via SQLite."""

    # Telegram internal senders that should be silently ignored.
    SYSTEM_IDS: set = {"777000"}

    # Senders that represent an anonymous group/channel identity.
    ANONYMOUS_IDS: set = {"1087968824"}

    def __init__(self, admin_id: str):
        # Support comma-separated admin IDs
        self.admin_ids = [aid.strip() for aid in str(admin_id).split(",") if aid.strip()]
        self.admin_id = self.admin_ids[0] if self.admin_ids else ""
        # Ensure admins are always in the database for tracking purposes
        self._ensure_admin()

    def _ensure_admin(self):
        """Make sure all admin IDs are recorded so we can track their chat_id."""
        try:
            with db.get_conn() as conn:
                for aid in self.admin_ids:
                    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (aid,))
        except Exception as e:
            logging.error(f"Failed to ensure admins in DB: {e}")

    def is_admin(self, user_id: str) -> bool:
        """Check if a user is an admin."""
        return str(user_id) in self.admin_ids

    def is_system_sender(self, user_id: str) -> bool:
        """Return True for Telegram-internal senders that should be silently ignored."""
        return str(user_id) in self.SYSTEM_IDS

    def is_anonymous_sender(self, user_id: str) -> bool:
        """Return True for senders that represent an anonymous group/channel identity."""
        return str(user_id) in self.ANONYMOUS_IDS

    def is_allowed(self, user_id: str) -> bool:
        """Check if a user is allowed to use the bot."""
        uid = str(user_id)
        if uid in self.admin_ids:
            return True
        try:
            with db.get_conn() as conn:
                cur = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,))
                return cur.fetchone() is not None
        except Exception as e:
            logging.error(f"Database error checking user access: {e}")
            return False

    def add_user(self, user_id: str) -> bool:
        """Add a user to the allowed list."""
        uid = str(user_id)
        try:
            with db.get_conn() as conn:
                cur = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,))
                if cur.fetchone() is not None:
                    return False
                conn.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
                return True
        except Exception as e:
            logging.error(f"Failed to add user {uid}: {e}")
            return False

    def remove_user(self, user_id: str) -> bool:
        """Remove a user from the allowed list."""
        uid = str(user_id)
        try:
            with db.get_conn() as conn:
                cur = conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                return cur.rowcount > 0
        except Exception as e:
            logging.error(f"Failed to remove user {uid}: {e}")
            return False

    def get_allowed_users(self) -> List[str]:
        """Get list of allowed user IDs."""
        try:
            with db.get_conn() as conn:
                cur = conn.execute("SELECT user_id FROM users ORDER BY added_at ASC")
                return [row['user_id'] for row in cur.fetchall()]
        except Exception as e:
            logging.error(f"Failed to fetch users: {e}")
            return []
            
    def register_chat_id(self, user_id: str, chat_id: str):
        """Register the last known chat_id for sending recovery messages."""
        uid = str(user_id)
        cid = str(chat_id)
        try:
            self._ensure_admin() # Ensure record exists to update it
            with db.get_conn() as conn:
                conn.execute("UPDATE users SET chat_id = ? WHERE user_id = ?", (cid, uid))
        except Exception as e:
            logging.error(f"Failed to update chat_id for {uid}: {e}")
