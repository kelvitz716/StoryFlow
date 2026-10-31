#!/usr/bin/env python3
"""Observe real Snapchat media hostnames without downloading media."""

import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Dict

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.platform import _valid_snapchat_username
from downloaders.snapchat import SnapchatDownloader, _ALLOWED_MEDIA_HOST_SUFFIXES


def check_host_allowed(host: str) -> bool:
    host_lower = host.lower()
    return any(host_lower == s or host_lower.endswith('.' + s) for s in _ALLOWED_MEDIA_HOST_SUFFIXES)


def get_registrable_suffix(host: str) -> str:
    parts = host.lower().split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return host.lower()


def probe_snapchat_hosts(usernames: List[str]) -> None:
    downloader = SnapchatDownloader()
    all_observed_hosts: List[str] = []

    for username in usernames:
        if not _valid_snapchat_username(username):
            print(f"❌ Invalid username: {username!r} (rejected)")
            continue

        print(f"\nProbing @{username}...")
        try:
            items = downloader._scrape_page(username, mode="both")
        except Exception as e:
            print(f"❌ Error scraping @{username}: {e}")
            continue

        if not items:
            print(f"No items found for @{username}.")
            continue

        print(f"{'hostname':<45} | {'passes _ALLOWED_MEDIA_HOST_SUFFIXES':<35} | {'media type'}")
        print("-" * 95)

        for item in items:
            media_url = item.get("mediaUrl")
            if not media_url:
                continue

            parsed = urlparse(media_url)
            hostname = parsed.hostname or ""
            passes = "yes" if check_host_allowed(hostname) else "no"

            media_type_raw = item.get("mediaType", 0)
            media_type_desc = "video" if media_type_raw == 1 else "image"

            all_observed_hosts.append(hostname)
            print(f"{hostname:<45} | {passes:<35} | {media_type_desc}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    unique_hosts = sorted(set(all_observed_hosts))
    if not unique_hosts:
        print("No hostnames observed.")
        return

    # Group by last two labels (registrable domain)
    grouped: Dict[str, List[str]] = {}
    for host in unique_hosts:
        suffix = get_registrable_suffix(host)
        grouped.setdefault(suffix, []).append(host)

    print("\nUnique hostnames grouped by registrable domain (last 2 labels):")
    for suffix, hosts in sorted(grouped.items()):
        print(f"  [{suffix}]")
        for h in hosts:
            passes = "passes" if check_host_allowed(h) else "FAILS"
            print(f"    - {h} ({passes})")

    # Check if allowlist needs changing
    failed_hosts = [h for h in unique_hosts if not check_host_allowed(h)]
    print()
    if failed_hosts:
        print(f"⚠️  Allowlist NEEDS CHANGING. The following hosts failed: {', '.join(failed_hosts)}")
    else:
        print("✅ Allowlist does not need changing. All observed hosts pass.")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <username> [<username> ...]")
        sys.exit(1)

    probe_snapchat_hosts(sys.argv[1:])


if __name__ == "__main__":
    main()
