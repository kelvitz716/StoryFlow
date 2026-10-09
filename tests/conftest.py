"""
Hermetic test configuration for StoryFlow.

Item 2: Autouse fixture that stubs socket.getaddrinfo to a public IP for known
platform hosts so the test suite passes hermetically with DNS blocked.
"""
import ipaddress
import socket
import pytest

KNOWN_PLATFORMS = {
    # Core platforms
    "instagram.com": "157.240.22.35",
    "snapchat.com": "142.250.180.46",
    "tiktok.com": "162.159.153.4",
    "twitter.com": "104.244.42.1",
    "x.com": "104.244.42.1",
    "facebook.com": "157.240.22.35",
    "fb.watch": "157.240.22.35",
    # Shorteners & test hosts
    "bit.ly": "67.199.248.11",
    "t.co": "104.244.42.1",
    "tinyurl.com": "104.20.138.65",
    "dns.google": "8.8.8.8",
    "example.com": "93.184.216.34",
    "example.org": "93.184.216.34",
    "example.net": "93.184.216.34",
    "example": "93.184.216.34",
    "localhost": "127.0.0.1",
}


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_stub_ip(host: str) -> str | None:
    host_lower = host.lower().rstrip(".")
    for domain, ip in KNOWN_PLATFORMS.items():
        if host_lower == domain or host_lower.endswith("." + domain):
            return ip
    return None


@pytest.fixture(autouse=True)
def stub_dns(monkeypatch):
    """Stub socket.getaddrinfo to a public IP for known platform hosts (item 2).

    Simulates an offline / blocked-DNS environment:
    - Known platform hosts resolve immediately to deterministic public IPs without network calls.
    - Numeric IP addresses are parsed locally without DNS.
    - All other hostnames raise socket.gaierror, ensuring tests do not make real network calls.
    """
    orig_getaddrinfo = socket.getaddrinfo

    def hermetic_getaddrinfo(host, port, *args, **kwargs):
        if host:
            stub_ip = _resolve_stub_ip(str(host))
            if stub_ip is not None:
                p = 0
                if port is not None:
                    try:
                        p = int(port)
                    except (ValueError, TypeError):
                        p = 0
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", (stub_ip, p)),
                    (socket.AF_INET, socket.SOCK_DGRAM, 17, "", (stub_ip, p)),
                ]
            if _is_ip_address(str(host)):
                return orig_getaddrinfo(host, port, *args, **kwargs)
            # DNS blocked for unknown hosts
            raise socket.gaierror(socket.EAI_NONAME, f"Hermetic test environment: DNS blocked for {host}")
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", hermetic_getaddrinfo)
