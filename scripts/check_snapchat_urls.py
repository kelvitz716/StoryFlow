#!/usr/bin/env python3
"""Check Snapchat URLs and extract usernames without making network calls."""

import sys
from pathlib import Path
from typing import List

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.platform import extract_snapchat_username
from core.security import validate_domain


def check_url(url: str) -> None:
    url = url.strip()
    if not url:
        return

    # Check platform via validate_domain (no DNS/network)
    if validate_domain(url, ['snapchat.com']):
        platform = "Snapchat"
    else:
        platform = "Other/Unknown"

    username = extract_snapchat_username(url)
    result = username if username else "REJECTED"

    print(f"{platform:<15} | {result}")


def main():
    urls: List[str] = []
    if len(sys.argv) > 1:
        urls = sys.argv[1:]
    else:
        # Read from stdin
        if not sys.stdin.isatty():
            urls = [line.strip() for line in sys.stdin if line.strip()]

    if not urls:
        print(f"Usage: {sys.argv[0]} <url> [<url> ...]")
        print(f"   or: cat urls.txt | {sys.argv[0]}")
        sys.exit(1)

    print(f"{'Platform':<15} | Extracted username or REJECTED")
    print("-" * 50)
    for u in urls:
        check_url(u)


if __name__ == "__main__":
    main()
