"""
Tests for items 1 and 2: validate_domain and is_safe_url hardening.
"""
import socket
import ipaddress
from unittest.mock import patch, MagicMock
import pytest

from core.security import validate_domain, is_safe_url


# ---------------------------------------------------------------------------
# Item 1 — validate_domain
# ---------------------------------------------------------------------------

ALLOWED = ['x.com', 'instagram.com']


class TestValidateDomainRejects:
    """URLs that must NOT be classified as a known platform."""

    def test_userinfo_with_ip_as_path(self):
        """https://x.com:80@169.254.169.254/ — userinfo attack."""
        assert validate_domain("https://x.com:80@169.254.169.254/", ALLOWED) is False

    def test_userinfo_with_evil_host(self):
        """https://instagram.com:x@evil.example/ — userinfo attack."""
        assert validate_domain("https://instagram.com:x@evil.example/", ALLOWED) is False

    def test_userinfo_at_sign_only(self):
        """https://x.com@evil.example/ — x.com is the user, evil.example is the host."""
        assert validate_domain("https://x.com@evil.example/", ALLOWED) is False

    def test_subdomain_lookalike(self):
        """https://instagram.com.evil.example/ — evil.example is the host."""
        assert validate_domain("https://instagram.com.evil.example/", ALLOWED) is False

    def test_wrong_scheme_ftp(self):
        """ftp://x.com/ — non-http/https scheme."""
        assert validate_domain("ftp://x.com/", ALLOWED) is False

    def test_wrong_scheme_javascript(self):
        """javascript:alert(1) — non-http/https scheme."""
        assert validate_domain("javascript:alert(1)", ALLOWED) is False


class TestValidateDomainAccepts:
    """URLs that SHOULD be classified as known platforms."""

    def test_bare_platform_url(self):
        """https://x.com/a — simple, clean URL."""
        assert validate_domain("https://x.com/a", ALLOWED) is True

    def test_www_instagram(self):
        """https://www.instagram.com/p/x/ — www. prefix."""
        assert validate_domain("https://www.instagram.com/p/x/", ALLOWED) is True

    def test_fqdn_trailing_dot(self):
        """https://x.com./ — trailing dot (FQDN form) should be stripped and accepted."""
        assert validate_domain("https://x.com./path", ALLOWED) is True

    def test_subdomain(self):
        """https://sub.x.com/path — legitimate subdomain."""
        assert validate_domain("https://sub.x.com/path", ALLOWED) is True


# ---------------------------------------------------------------------------
# Item 2 — is_safe_url
# ---------------------------------------------------------------------------

def _make_addrinfo(ip_str: str):
    """Build a minimal socket.getaddrinfo return value for a given IP string."""
    ip = ipaddress.ip_address(ip_str)
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, '', (ip_str, 0))]


class TestIsSafeUrlBlocked:
    """All of these must be rejected (return False)."""

    def test_tailscale_100_80(self):
        """100.80.198.77 — Tailscale CGNAT range, not globally routable."""
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('100.80.198.77')):
            assert is_safe_url("http://somehost.example/") is False

    def test_tailscale_100_64(self):
        """100.64.0.1 — Tailscale CGNAT start."""
        # Numeric host — resolved without DNS
        assert is_safe_url("http://100.64.0.1/") is False

    def test_loopback_127(self):
        """127.0.0.1 — loopback."""
        assert is_safe_url("http://127.0.0.1/") is False

    def test_private_192_168(self):
        """192.168.100.28 — RFC-1918 private."""
        assert is_safe_url("http://192.168.100.28/") is False

    def test_link_local_169_254(self):
        """169.254.169.254 — AWS/link-local metadata."""
        assert is_safe_url("http://169.254.169.254/") is False

    def test_ipv6_loopback(self):
        """::1 — IPv6 loopback."""
        assert is_safe_url("http://[::1]/") is False

    def test_ipv4_mapped_loopback(self):
        """::ffff:127.0.0.1 — IPv4-mapped IPv6 loopback."""
        assert is_safe_url("http://[::ffff:127.0.0.1]/") is False

    def test_numeric_hex_host(self):
        """0x7f000001 — hex-encoded 127.0.0.1."""
        # Python ipaddress.ip_address handles this
        assert is_safe_url("http://0x7f000001/") is False

    def test_numeric_decimal_host(self):
        """2130706433 — dotless decimal 127.0.0.1."""
        assert is_safe_url("http://2130706433/") is False

    def test_numeric_short_loopback(self):
        """127.1 — abbreviated loopback."""
        assert is_safe_url("http://127.1/") is False

    def test_unresolvable_host(self):
        """Hostname that raises gaierror — must be rejected (fail closed)."""
        with patch('socket.getaddrinfo', side_effect=socket.gaierror("Name not found")):
            assert is_safe_url("http://does-not-exist-xyz.invalid/") is False

    def test_localhost_name(self):
        """literal 'localhost' hostname."""
        assert is_safe_url("http://localhost/path") is False

    def test_ftp_scheme_rejected(self):
        """Non-http/https scheme must be rejected."""
        assert is_safe_url("ftp://8.8.8.8/") is False


class TestIsSafeUrlAccepts:
    """Public addresses that must be accepted."""

    def test_google_dns(self):
        """8.8.8.8 — globally routable."""
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('8.8.8.8')):
            assert is_safe_url("http://dns.google/") is True

    def test_numeric_public_ip(self):
        """Numeric public IP without DNS."""
        assert is_safe_url("https://8.8.8.8/") is True
