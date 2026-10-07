"""Security utilities for input validation and sanitization."""

import re
import logging
import socket
import ipaddress
from urllib.parse import urlparse, urlunparse


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal and invalid characters.

    Args:
        filename: Unsafe filename string

    Returns:
        Safe filename string (alphanumeric, -, _)
    """
    # Remove null bytes
    filename = filename.replace('\0', '')

    # Replace invalid chars with underscore
    # Allow alphanumeric, underscore, hyphen, and period
    cleaned = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)

    # Remove leading/trailing periods/spaces
    cleaned = cleaned.strip('. ')

    # Ensure it's not empty or just dots
    if not cleaned or cleaned.replace('.', '') == '':
        cleaned = 'unnamed_file'

    return cleaned


def validate_domain(url: str, allowed_domains: list[str]) -> bool:
    """
    Strictly validate that a URL belongs to allowed domains.

    Rules (item 1):
    - Scheme must be http or https.
    - Reject any URL whose netloc contains '@' (userinfo present).
    - Use urlparse().hostname (not netloc) — this never includes port or userinfo.
    - Strip a single trailing dot from the hostname (FQDN form), then lowercase.
    - Empty hostname → reject.

    Args:
        url: Input URL
        allowed_domains: List of allowed domains (e.g. ['snapchat.com'])

    Returns:
        True if valid, False otherwise
    """
    try:
        parsed = urlparse(url)

        # Reject non-http/https schemes
        if parsed.scheme not in ('http', 'https'):
            return False

        # Reject URLs with userinfo (@-sign in netloc means credentials were embedded)
        if '@' in (parsed.netloc or ''):
            return False

        # Use parsed.hostname — already strips port, already handles IPv6 brackets
        hostname = parsed.hostname
        if not hostname:
            return False

        # Strip a single trailing dot (FQDN notation) and lowercase
        hostname = hostname.rstrip('.').lower()
        if not hostname:
            return False

        # Remove www. prefix
        hostname = hostname.removeprefix('www.')

        for domain in allowed_domains:
            if hostname == domain or hostname.endswith('.' + domain):
                return True

        return False

    except Exception:
        return False


def mask_sensitive_url(url: str) -> str:
    """
    Mask sensitive query parameters in a URL for logging.

    Args:
        url: Full URL

    Returns:
        URL with sensitive params replaced by ***
    """
    try:
        parsed = urlparse(url)

        # If it's a media URL with signature, mask complex query params
        # For simplicity, we just say if there's a query, we mask values
        # but keep keys to help debugging
        if parsed.query:
            # Reconstruct masked query
            # We don't parse_qs because it handles multiple values; manual split is safer for preservation
            pairs = parsed.query.split('&')
            masked_pairs = []
            for pair in pairs:
                if '=' in pair:
                    key, _ = pair.split('=', 1)
                    # Mask everything except known safe keys (e.g. 'v' for youtube)
                    if key in ('v', 'id', 'p'):
                        masked_pairs.append(pair)
                    else:
                        masked_pairs.append(f"{key}=***")
                else:
                    masked_pairs.append(pair)

            new_query = '&'.join(masked_pairs)
            parsed = parsed._replace(query=new_query)

        return urlunparse(parsed)

    except Exception:
        return "Checking URL..."  # Fallback


def is_safe_url(url: str) -> bool:
    """
    Check if the URL points to a globally routable IP address (SSRF protection).

    Rules (item 2):
    - Reject non-http/https schemes and empty hostnames.
    - Block localhost names.
    - Detect numeric-host tricks (hex, decimal, octal, dotless) by trying
      ipaddress.ip_address(hostname) before DNS lookup.
    - Resolve hostname via socket.getaddrinfo; reject on failure (fail closed).
    - For each resolved address: unwrap IPv4-mapped IPv6 (ip.ipv4_mapped),
      then reject if not ip.is_global.

    Args:
        url: Input URL string

    Returns:
        True if URL is safe and globally routable, False otherwise
    """
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ('http', 'https'):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Block literal localhost variants
        if hostname.lower() in ('localhost', 'localhost.localdomain'):
            return False

        # Detect numeric-host tricks before DNS: ip_address() handles
        # dotted-decimal, dotless-decimal, hex (0x7f000001), octal, etc.
        try:
            numeric_ip = ipaddress.ip_address(hostname)
            # Unwrap IPv4-mapped IPv6 first
            if hasattr(numeric_ip, 'ipv4_mapped') and numeric_ip.ipv4_mapped is not None:
                numeric_ip = numeric_ip.ipv4_mapped
            return bool(numeric_ip.is_global)
        except ValueError:
            pass  # Not a bare numeric address — continue to DNS resolution

        # Resolve hostname to IP addresses; fail closed if unresolvable
        try:
            addrinfo = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False

        if not addrinfo:
            return False

        for _family, _type, _proto, _canonname, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                return False

            # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1)
            if hasattr(ip, 'ipv4_mapped') and ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped

            # Reject if not globally routable (catches loopback, private,
            # link-local, reserved, multicast, Tailscale 100.64/10, etc.)
            if not ip.is_global:
                return False

        return True

    except Exception:
        return False
