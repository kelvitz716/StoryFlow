"""
Per-user download quality preferences.

Two layers of quality selection:
  1. Per-platform override  (e.g. XVideos → 720p, everything else → best)
  2. Global user default    (the existing /quality setting)

Resolution order for get_effective_quality(user_id, platform):
  platform override → global user default → system DEFAULT_QUALITY ('best')

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


# ---------------------------------------------------------------------------
# Schema migration (runs once at import time — safe to call repeatedly)
# ---------------------------------------------------------------------------

def _ensure_platform_quality_table() -> None:
    """Create the platform_quality table if it does not yet exist."""
    try:
        with db.get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS platform_quality (
                    user_id  TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    quality  TEXT NOT NULL DEFAULT 'best',
                    PRIMARY KEY (user_id, platform)
                )
            ''')
    except Exception as e:
        logging.warning(f'platform_quality table init: {e}')


_ensure_platform_quality_table()


# ---------------------------------------------------------------------------
# Global quality (existing behaviour — unchanged)
# ---------------------------------------------------------------------------

def get_user_quality(user_id: str) -> str:
    """Return the user's saved global quality key (defaults to 'best')."""
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
    """Persist the user's global quality preference. Returns True on success."""
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


# ---------------------------------------------------------------------------
# Per-platform quality override (new — Option B groundwork)
# ---------------------------------------------------------------------------

def get_platform_quality(user_id: str, platform: str) -> str | None:
    """
    Return the user's per-platform quality override, or None if none is set.
    Callers should fall back to get_user_quality() when this returns None.
    """
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                'SELECT quality FROM platform_quality WHERE user_id = ? AND platform = ?',
                (user_id, platform)
            ).fetchone()
            return row['quality'] if row else None
    except Exception as e:
        logging.warning(f'get_platform_quality: {e}')
        return None


def set_platform_quality(user_id: str, platform: str, quality: str) -> bool:
    """
    Persist a per-platform quality override for a user. Returns True on success.
    Pass quality=None or call clear_platform_quality() to remove the override.
    """
    if quality not in QUALITY_OPTIONS:
        return False
    try:
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO platform_quality (user_id, platform, quality) VALUES (?, ?, ?)'
                ' ON CONFLICT(user_id, platform) DO UPDATE SET quality = excluded.quality',
                (user_id, platform, quality)
            )
        return True
    except Exception as e:
        logging.warning(f'set_platform_quality: {e}')
        return False


def clear_platform_quality(user_id: str, platform: str) -> bool:
    """Remove a per-platform quality override (fall back to global default)."""
    try:
        with db.get_conn() as conn:
            conn.execute(
                'DELETE FROM platform_quality WHERE user_id = ? AND platform = ?',
                (user_id, platform)
            )
        return True
    except Exception as e:
        logging.warning(f'clear_platform_quality: {e}')
        return False


def get_all_platform_overrides(user_id: str) -> dict[str, str]:
    """Return all per-platform quality overrides for a user as {platform: quality}."""
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                'SELECT platform, quality FROM platform_quality WHERE user_id = ?',
                (user_id,)
            ).fetchall()
            return {row['platform']: row['quality'] for row in rows}
    except Exception as e:
        logging.warning(f'get_all_platform_overrides: {e}')
        return {}


# ---------------------------------------------------------------------------
# Unified resolver — use this everywhere a quality is needed for a download
# ---------------------------------------------------------------------------

def get_effective_quality(user_id: str, platform: str | None = None) -> str:
    """
    Resolve the quality to use for a download, in priority order:
      1. Per-platform override (if platform is given and an override is set)
      2. Global user preference
      3. System default ('best')
    """
    if platform:
        override = get_platform_quality(user_id, platform)
        if override:
            return override
    return get_user_quality(user_id)

