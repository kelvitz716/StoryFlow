"""
Access Manager for controlling user access to the bot.
"""
import json
import logging
import os
from typing import Set, List

class AccessManager:
    """Manages allowed users and admin access."""

    def __init__(self, admin_id: str, data_file: str = "data/allowed_users.json"):
        """
        Initialize the AccessManager.
        
        Args:
            admin_id: The Telegram User ID of the admin.
            data_file: Path to the JSON file storing allowed users.
        """
        self.admin_id = str(admin_id)
        self.data_file = data_file
        self.allowed_users: Set[str] = self._load_allowed_users()
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

    def _load_allowed_users(self) -> Set[str]:
        """Load allowed users from JSON file."""
        if not os.path.exists(self.data_file):
            return set()
        
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                return set(str(uid) for uid in data.get("allowed_users", []))
        except Exception as e:
            logging.error(f"Failed to load allowed users: {e}")
            return set()

    def _save_allowed_users(self):
        """Save allowed users to JSON file."""
        try:
            with open(self.data_file, 'w') as f:
                json.dump({"allowed_users": list(self.allowed_users)}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save allowed users: {e}")

    def is_admin(self, user_id: str) -> bool:
        """Check if a user is the admin."""
        return str(user_id) == self.admin_id

    def is_allowed(self, user_id: str) -> bool:
        """Check if a user is allowed to use the bot."""
        uid = str(user_id)
        # Admin is always allowed
        if uid == self.admin_id:
            return True
        return uid in self.allowed_users

    def add_user(self, user_id: str) -> bool:
        """Add a user to the allowed list."""
        uid = str(user_id)
        if uid not in self.allowed_users:
            self.allowed_users.add(uid)
            self._save_allowed_users()
            return True
        return False

    def remove_user(self, user_id: str) -> bool:
        """Remove a user from the allowed list."""
        uid = str(user_id)
        if uid in self.allowed_users:
            self.allowed_users.remove(uid)
            self._save_allowed_users()
            return True
        return False

    def get_allowed_users(self) -> List[str]:
        """Get list of allowed user IDs."""
        return list(self.allowed_users)
