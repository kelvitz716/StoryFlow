"""
Tests for item 3:
- identify_platform runs is_safe_url on ALL URLs (including named platforms).
- resolve_shortlink raises UnsafeRedirectError instead of returning an unsafe URL.
- Second hop to 100.80.198.77 is never requested.
"""
import socket
import pytest
from unittest.mock import patch, MagicMock, call
import requests as req_module

from core.platform import identify_platform
from utils.bot_utils import resolve_shortlink, UnsafeRedirectError


# ---------------------------------------------------------------------------
# identify_platform — SSRF gate for named platforms
# ---------------------------------------------------------------------------

def _make_addrinfo(ip_str: str):
    import ipaddress
    ip = ipaddress.ip_address(ip_str)
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, '', (ip_str, 0))]


class TestIdentifyPlatformSsrf:
    """Named-platform URLs that resolve to unsafe IPs must return Unknown."""

    def test_instagram_resolves_to_loopback(self):
        """An instagram.com URL whose IP is 127.0.0.1 must be Unknown."""
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('127.0.0.1')):
            assert identify_platform("https://www.instagram.com/p/abc/") == "Unknown"

    def test_snapchat_resolves_to_tailscale(self):
        """A snapchat.com URL whose IP is in the Tailscale range must be Unknown."""
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('100.80.198.77')):
            assert identify_platform("https://www.snapchat.com/add/user") == "Unknown"

    def test_tiktok_resolves_to_private(self):
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('192.168.1.1')):
            assert identify_platform("https://www.tiktok.com/@user/video/123") == "Unknown"

    def test_x_resolves_to_public(self):
        """x.com resolving to a public IP is fine."""
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('104.244.42.1')):
            assert identify_platform("https://x.com/user/status/123") == "Twitter"

    def test_instagram_resolves_to_public(self):
        with patch('socket.getaddrinfo', return_value=_make_addrinfo('157.240.22.35')):
            assert identify_platform("https://www.instagram.com/p/abc/") == "Instagram"


# ---------------------------------------------------------------------------
# resolve_shortlink — UnsafeRedirectError semantics
# ---------------------------------------------------------------------------

def _redirect_response(location: str, status: int = 302) -> MagicMock:
    """Build a mock response that looks like a redirect."""
    resp = MagicMock()
    resp.status_code = status
    resp.is_redirect = True
    resp.headers = {"Location": location}
    resp.close = MagicMock()
    return resp


def _final_response(url: str = "https://example.com/final", status: int = 200) -> MagicMock:
    """Build a mock response that looks like a final non-redirect page."""
    resp = MagicMock()
    resp.status_code = status
    resp.is_redirect = False
    resp.headers = {}
    resp.url = url
    resp.close = MagicMock()
    return resp


class TestResolveShortlinkUnsafeHop:
    """resolve_shortlink must raise UnsafeRedirectError for unsafe hops."""

    @pytest.mark.asyncio
    async def test_first_hop_is_loopback(self):
        """A URL that redirects immediately to 127.0.0.1 must be rejected."""
        call_log = []

        def fake_get(url, **kwargs):
            call_log.append(url)
            if url == "https://short.example/link":
                return _redirect_response("http://127.0.0.1/")
            pytest.fail(f"Unexpected request to {url!r}")

        with patch('requests.get', side_effect=fake_get):
            with pytest.raises(UnsafeRedirectError):
                await resolve_shortlink("https://short.example/link")

        # The second (unsafe) URL must never have been requested
        assert "http://127.0.0.1/" not in call_log

    @pytest.mark.asyncio
    async def test_public_first_hop_unsafe_second_hop(self):
        """
        Original URL is public.
        First hop → publicly routable intermediate.
        Second hop → http://100.80.198.77:8096/ (Tailscale/Jellyfin).
        Must be rejected; the Tailscale address must never be requested.
        """
        call_log = []

        def fake_get(url, **kwargs):
            call_log.append(url)
            if url == "https://bit.ly/example":
                # First hop: redirect to a public intermediate URL
                return _redirect_response("https://cdn.example.com/r?id=42")
            elif url == "https://cdn.example.com/r?id=42":
                # Second hop: redirect to Tailscale/Jellyfin
                return _redirect_response("http://100.80.198.77:8096/web/index.html")
            pytest.fail(f"Unexpected request to {url!r}")

        with patch('requests.get', side_effect=fake_get):
            with pytest.raises(UnsafeRedirectError):
                await resolve_shortlink("https://bit.ly/example")

        # The Tailscale address must never have been requested
        assert not any("100.80.198.77" in u for u in call_log), (
            f"Tailscale address was requested: {call_log}"
        )

    @pytest.mark.asyncio
    async def test_tailscale_direct_first_hop(self):
        """Direct Tailscale URL — first call never happens."""
        call_log = []

        def fake_get(url, **kwargs):
            call_log.append(url)
            pytest.fail(f"Should not have requested {url!r}")

        with patch('requests.get', side_effect=fake_get):
            with pytest.raises(UnsafeRedirectError):
                await resolve_shortlink("http://100.80.198.77:8096/")

        assert call_log == []

    @pytest.mark.asyncio
    async def test_connection_error_raises(self):
        """Connection errors must fail closed (raise UnsafeRedirectError)."""
        with patch('requests.get', side_effect=req_module.exceptions.ConnectionError("refused")):
            with pytest.raises(UnsafeRedirectError):
                await resolve_shortlink("https://short.example/link")

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        """Timeouts must fail closed."""
        with patch('requests.get', side_effect=req_module.exceptions.Timeout("timed out")):
            with pytest.raises(UnsafeRedirectError):
                await resolve_shortlink("https://short.example/link")

    @pytest.mark.asyncio
    async def test_too_many_hops_raises(self):
        """More than 5 hops must raise UnsafeRedirectError."""
        hop_num = [0]

        def fake_get(url, **kwargs):
            hop_num[0] += 1
            resp = MagicMock()
            resp.status_code = 302
            resp.is_redirect = True
            resp.headers = {"Location": f"https://cdn{hop_num[0]}.example.com/"}
            resp.close = MagicMock()
            return resp

        with patch('requests.get', side_effect=fake_get):
            with patch('socket.getaddrinfo') as mock_dns:
                import ipaddress, socket as sock_mod
                mock_dns.return_value = [(sock_mod.AF_INET, sock_mod.SOCK_STREAM, 0, '', ('104.20.1.1', 0))]
                with pytest.raises(UnsafeRedirectError):
                    await resolve_shortlink("https://short.example/link")


class TestResolveShortlinkHappyPath:
    """resolve_shortlink must return the final URL on a clean redirect chain."""

    @pytest.mark.asyncio
    async def test_clean_redirect_chain(self):
        """A clean public → public redirect returns the final URL."""
        import socket as sock_mod

        def fake_get(url, **kwargs):
            if url == "https://short.example/link":
                return _redirect_response("https://destination.example.com/page")
            elif url == "https://destination.example.com/page":
                return _final_response("https://destination.example.com/page")
            pytest.fail(f"Unexpected request to {url!r}")

        def fake_getaddrinfo(host, port, **kwargs):
            return [(sock_mod.AF_INET, sock_mod.SOCK_STREAM, 0, '', ('104.20.1.1', 0))]

        with patch('requests.get', side_effect=fake_get):
            with patch('socket.getaddrinfo', side_effect=fake_getaddrinfo):
                result = await resolve_shortlink("https://short.example/link")

        assert result == "https://destination.example.com/page"

    @pytest.mark.asyncio
    async def test_primary_domain_skips_resolution(self):
        """Primary platform domains are returned unchanged without any HTTP request."""
        with patch('requests.get') as mock_get:
            result = await resolve_shortlink("https://www.instagram.com/p/abc123/")
        mock_get.assert_not_called()
        assert result == "https://www.instagram.com/p/abc123/"
