"""Configuration loading, validation, and environment helpers."""

import os
import sys
import glob
import stat
import logging
from typing import List


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    """
    Read an integer from environment variable `name`, log a warning on empty or
    non-numeric value, and clamp the resulting integer to [lo, hi].
    """
    raw = os.getenv(name)
    if raw is None:
        val = default
    elif not raw.strip():
        logging.warning(f"Empty value for environment variable {name}, using default {default}")
        val = default
    else:
        try:
            val = int(raw.strip())
        except (ValueError, TypeError):
            logging.warning(
                f"Non-numeric value {raw!r} for environment variable {name}, using default {default}"
            )
            val = default
    return max(int(lo), min(int(hi), int(val)))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    """
    Read a float from environment variable `name`, log a warning on empty or
    non-numeric value, and clamp the resulting float to [lo, hi].
    """
    raw = os.getenv(name)
    if raw is None:
        val = default
    elif not raw.strip():
        logging.warning(f"Empty value for environment variable {name}, using default {default}")
        val = default
    else:
        try:
            val = float(raw.strip())
        except (ValueError, TypeError):
            logging.warning(
                f"Non-numeric value {raw!r} for environment variable {name}, using default {default}"
            )
            val = default
    return max(float(lo), min(float(hi), float(val)))


def _validate_admin_ids(raw: str) -> List[str]:
    """
    Parse and validate ADMIN_USER_ID. Accepts a comma-separated list of
    numeric Telegram IDs (positive or negative integers).
    Calls sys.exit(1) with a clear message if any entry is non-numeric.
    """
    entries = [e.strip() for e in raw.split(',') if e.strip()]
    for entry in entries:
        if not entry.lstrip('-').isdigit():
            print(
                f"❌ FATAL: ADMIN_USER_ID contains non-numeric entry: {entry!r}\n"
                "  Expected a comma-separated list of Telegram user IDs (e.g. 123456789 or -1001234567890).",
                file=sys.stderr
            )
            sys.exit(1)
    return entries


def _startup_permissions():
    """
    Apply restrictive file permissions at startup.
    chmod 600 on .env and cookie files; chmod 700 on data directories.
    All errors are logged as warnings and ignored.
    """
    def _chmod(path: str, mode: int):
        try:
            os.chmod(path, mode)
        except Exception as exc:
            logging.warning(f"startup permissions: could not chmod {path!r}: {exc}")

    # Restrict .env
    if os.path.exists('.env'):
        _chmod('.env', stat.S_IRUSR | stat.S_IWUSR)  # 600

    # Restrict cookie files
    cookie_path = os.getenv('COOKIE_PATH', './cookies')
    for f in glob.glob(os.path.join(cookie_path, '*.txt')):
        _chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 600

    # Restrict sensitive directories
    for d in [cookie_path, './sessions', './data']:
        if os.path.isdir(d):
            _chmod(d, stat.S_IRWXU)  # 700
