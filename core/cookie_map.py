"""
Runtime-editable cookie owner mapping (C1 extension) and admin cookie fallback settings.

Maps channel/anonymous identities (negative IDs) to a personal account ID
so the personal account's cookie file is used for that channel's jobs.

Priority: data/cookie_map.json entries override COOKIE_OWNER_MAP env var.
Both sources are loaded on import; call reload() after editing the env var.
Add/remove via add() / remove() — changes persist to JSON immediately.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, Dict

_MAP_FILE = Path(__file__).parent.parent / "data" / "cookie_map.json"
_ID_RE = re.compile(r'^-?\d+$')

_mappings: Dict[str, str] = {}
_admin_fallback_override: Optional[bool] = None


def _load_env() -> Dict[str, str]:
    """Parse COOKIE_OWNER_MAP env var (identity:owner,...) into a dict."""
    raw = os.environ.get("COOKIE_OWNER_MAP", "").strip()
    result: Dict[str, str] = {}
    if not raw:
        return result
    has_malformed = False
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 1)
        if (
            len(parts) == 2
            and _ID_RE.match(parts[0].strip())
            and _ID_RE.match(parts[1].strip())
        ):
            result[parts[0].strip()] = parts[1].strip()
        else:
            has_malformed = True
    if has_malformed:
        logging.warning("⚠️ Malformed entry detected in COOKIE_OWNER_MAP; ignored")
    return result


def reload() -> None:
    """Reload mappings and fallback setting from env var + JSON file."""
    global _mappings, _admin_fallback_override
    new_map = _load_env()
    _admin_fallback_override = None
    if _MAP_FILE.exists():
        try:
            with open(_MAP_FILE, "r") as f:
                file_data = json.load(f)
            if isinstance(file_data, dict):
                if "mappings" in file_data and isinstance(file_data["mappings"], dict):
                    new_map.update(file_data["mappings"])
                    _admin_fallback_override = file_data.get("admin_fallback_override")
                else:
                    new_map.update(file_data)
        except Exception as exc:
            logging.warning(f"cookie_map: failed to read {_MAP_FILE}: {exc}")
    _mappings = new_map


def get(identity: str) -> Optional[str]:
    """Return the mapped owner ID for *identity*, or None."""
    return _mappings.get(str(identity))


def add(channel_id: str, owner_id: str) -> None:
    """Add or update a mapping and persist to the JSON file."""
    _mappings[str(channel_id)] = str(owner_id)
    _persist()


def remove(channel_id: str) -> bool:
    """Remove a mapping. Returns True if it existed."""
    key = str(channel_id)
    if key in _mappings:
        del _mappings[key]
        _persist()
        return True
    return False


def all_mappings() -> Dict[str, str]:
    """Return a copy of all current mappings."""
    return dict(_mappings)


def is_admin_fallback_enabled() -> bool:
    """Check if admin cookie fallback is enabled (persisted setting or env)."""
    if _admin_fallback_override is not None:
        return _admin_fallback_override
    return os.getenv('ALLOW_ADMIN_COOKIE_FALLBACK', 'false').lower() == 'true'


def set_admin_fallback(enabled: Optional[bool]) -> None:
    """Set admin fallback override and persist."""
    global _admin_fallback_override
    _admin_fallback_override = enabled
    _persist()


def _persist() -> None:
    try:
        _MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mappings": _mappings,
            "admin_fallback_override": _admin_fallback_override
        }
        with open(_MAP_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        os.chmod(_MAP_FILE, 0o600)
    except Exception as exc:
        logging.error(f"cookie_map: failed to persist {_MAP_FILE}: {exc}")


reload()
