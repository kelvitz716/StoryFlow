"""
Per-user download quality preferences.

Quality options map to yt-dlp format strings:
  best       -> bestvideo+bestaudio/best   (default)
  1080p      -> bestvideo[height<=1080]+bestaudio/best[height<=1080]
  720p       -> bestvideo[height<=720]+bestaudio/best[height<=720]
  480p       -> bestvideo[height<=480]+bestaudio/best[height<=480]
  audio      -> bestaudio/best             (audio-only, triggers -x)
"""
from core.database import db
import logging

QUALITY_OPTIONS = {
    'best':  ('bestvideo+bestaudio/best',   False),  # (format_string, audio_only)
    '1080p': ('bestvideo[height<=1080]+bestaudio/best[height<=1080]', False),
    '720p':  ('bestvideo[height<=720]+bestaudio/best[height<=720]',   False),
    '480p':  ('bestvideo[height<=480]+bestaudio/best[height<=480]',   False),
    'audio': ('bestaudio/best',             True),
}

DEFAULT_QUALITY = 'best'


def get_user_quality(user_id: str) -> str:
    """Return the user's saved quality key (defaults to 'best')."""
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                'SELECT quality FROM user_prefs WHERE user_id = ?', (user_id,)
            ).fetchone()
            return row['quality'] if row else DEFAULT_QUALITY
    except Exception as e:
        logging.warning(f'get_user_quality: {e}')
        return DEFAULT_QUALITY


def set_user_quality(user_id: str, quality: str) -> bool:
    """Persist the user's quality preference. Returns True on success."""
    if quality not in QUALITY_OPTIONS:
        return False
    try:
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO user_prefs (user_id, quality) VALUES (?, ?)'
                ' ON CONFLICT(user_id) DO UPDATE SET quality = excluded.quality',
                (user_id, quality)
            )
        return True
    except Exception as e:
        logging.warning(f'set_user_quality: {e}')
        return False
