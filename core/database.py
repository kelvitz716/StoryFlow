"""Database layer using SQLite with WAL mode for high concurrency."""
import sqlite3
import os
import logging
from typing import Dict, List, Any, Optional

class Database:
    """Manages the SQLite database connection and schemas."""
    
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
    def get_conn(self) -> sqlite3.Connection:
        """Get a configured database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead-Logging for high concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    def _init_db(self):
        """Initialize the database schema."""
        with self.get_conn() as conn:
            # Users table (used by AccessManager)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    chat_id TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Stats table (overall user downloads)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    total_downloads INTEGER DEFAULT 0
                )
            ''')
            # Platform stats table (per-platform downloads)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS platform_stats (
                    user_id TEXT,
                    platform TEXT,
                    downloads INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, platform)
                )
            ''')
            # Jobs table (DownloadQueue persistence)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    chat_id TEXT,
                    message_id INTEGER,
                    url TEXT,
                    platform TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
# Global database instance
db = Database()
