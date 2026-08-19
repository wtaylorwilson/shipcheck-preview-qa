"""SSRF guards: https-only public internet, no private/metadata/localhost.

Used both as a preflight on POST /qa_preview and again on every Playwright
request (including redirects) so a public host cannot bounce us onto RFC1918.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

NAV_TIMEOUT_S = 20
JOB_CAP_S = 240


class UnsafeUrl(ValueError):
    """Raised when a URL must not be fetched."""


BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "local",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata.google.com",
        "metadata",
        "host.docker.internal",
        "kubernetes.default",
        "kubernetes.default.svc",
        "kubernetes.default.svc.cluster.local",
    }
)

BLOCKED_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".corp",
    ".lan",
    ".home",
    ".localdomain",
    ".invalid",
    ".onion",
)

# Networks beyond what ipaddress.{is_private,is_loopback,...} already catch.
EXTRA_V4 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / shared address space
    ipaddress.ip_network("192.0.0.0/29"),
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("255.255.255.255/32"),
)
EXTRA_V6 = (
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
)


def _host_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), (parsed.hostname or "")


def ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip_is_blocked(ip.ipv4_mapped)
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        return ip_is_blocked(ip.sixtofour)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    nets = EXTRA_V4 if ip.version == 4 else EXTRA_V6
    return any(ip in net for net in nets)


def parse_ip(host: str) -> ipaddress._BaseAddress | None:
    h = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass
    # Decimal / hex IPv4 tricks: 2130706433, 0x7f000001
    try:
        if h.isdigit() or h.lower().startswith("0x"):
            return ipaddress.IPv4Address(int(h, 0))
    except (ValueError, OverflowError):
        return None
    return None


def hostname_is_blocked(host: str) -> bool:
    h = host.strip().strip("[]").rstrip(".").lower()
    if not h:
        return True
    if h in BLOCKED_HOSTS:
        return True
    if any(h.endswith(suf) for suf in BLOCKED_SUFFIXES):
        return True
    if h.startswith("metadata."):
        return True
    return False


def resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    seen: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if ip not in seen:
            seen.append(ip)
    return seen


def assert_url_allowed(url: str, *, resolve: bool = True) -> None:
    """Raise UnsafeUrl unless url is https to a public internet host.

    `resolve=False` skips DNS (used for cheap structural tests). Production
    callers always resolve so DNS rebinding / private A records are caught.
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrl("url is required")
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        raise UnsafeUrl("file:// is not allowed")
    if scheme != "https":
        raise UnsafeUrl("only https URLs are allowed")
    if parsed.username or parsed.password:
        # Avoid confusing userinfo-as-host tricks; public previews do not need it.
        raise UnsafeUrl("URLs with embedded credentials are not allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeUrl("url is missing a hostname")
    if hostname_is_blocked(host):
        raise UnsafeUrl(f"blocked hostname: {host}")
    ip = parse_ip(host)
    if ip is not None:
        if ip_is_blocked(ip):
            raise UnsafeUrl(f"blocked IP: {ip}")
        return
    # Browsers still parse 0177.0.0.1 as octal loopback. Reject leading zeros.
    dotted = host.split(".")
    if len(dotted) == 4 and all(part.isdigit() for part in dotted):
        if any(len(part) > 1 and part.startswith("0") for part in dotted):
            raise UnsafeUrl(f"ambiguous IPv4 hostname: {host}")
    if any(ch in host for ch in (" ", "\t", "\n", "\r")):
        raise UnsafeUrl("malformed hostname")
    if not resolve:
        return
    try:
        ips = resolve_ips(host)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"DNS lookup failed for {host}") from exc
    if not ips:
        raise UnsafeUrl(f"no addresses for {host}")
    for resolved in ips:
        if ip_is_blocked(resolved):
            raise UnsafeUrl(f"{host} resolves to blocked IP {resolved}")


def assert_redirect_target_safe(from_url: str, location: str) -> None:
    if not location:
        raise UnsafeUrl("empty redirect Location")
    next_url = urljoin(from_url, location)
    assert_url_allowed(next_url, resolve=True)


def is_url_allowed(url: str, *, resolve: bool = True) -> bool:
    try:
        assert_url_allowed(url, resolve=resolve)
        return True
    except UnsafeUrl:
        return False
