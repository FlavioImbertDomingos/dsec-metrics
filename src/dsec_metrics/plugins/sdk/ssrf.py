"""Outbound request policy: which hosts collectors may reach, checked on every request.

A URL passes when its scheme is HTTPS (or HTTP for hosts the operator names), its host
matches the operator's allowlist, and every address the host resolves to is a normal
unicast address: not loopback, link-local (which includes the cloud metadata address
169.254.169.254), multicast, unspecified, reserved or "this network", in IPv4 or IPv6,
including IPv4 addresses embedded in IPv6 forms (mapped, 6to4, Teredo, NAT64). Private
ranges are allowed because internal APIs live there; the allowlist is what limits them.

The caller connects to the address returned by :meth:`OutboundPolicy.check`, never
resolving the name a second time, so a DNS answer that changes between check and connect
does not help.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

# Names and addresses of cloud instance metadata services, refused even if allowlisted.
METADATA_NAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
        "metadata.azure.com",
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)

# Ranges refused in addition to what ipaddress flags: "this network" and shared
# address space (carrier-grade NAT, where some clouds put their metadata service).
EXTRA_BLOCKED = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
)
NAT64 = ipaddress.ip_network("64:ff9b::/96")

Resolver = Callable[[str, int], Sequence[str]]


class BlockedURL(ValueError):  # noqa: N818 (reads better at call sites than BlockedURLError)
    """The URL is not allowed. The message names the reason, never credentials."""


def system_resolver(host: str, port: int) -> list[str]:
    """Every address the system resolver returns for a name."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise BlockedURL(f"cannot resolve {host}") from None
    return sorted({str(info[4][0]) for info in infos})


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def address_allowed(address: str) -> bool:
    """Whether a collector may connect to this address. Raises ValueError if it is not one."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_v4(ip)
        if embedded is not None:
            candidates.append(embedded)
    for candidate in candidates:
        if (
            candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_unspecified
            or candidate.is_reserved
            or (isinstance(candidate, ipaddress.IPv6Address) and candidate.is_site_local)
            or any(candidate in net for net in EXTRA_BLOCKED if net.version == candidate.version)
            or str(candidate) in METADATA_NAMES
        ):
            return False
    return True


def host_matches(host: str, patterns: Sequence[str]) -> bool:
    """Exact names, or ``*.example.com`` for any subdomain (not the bare domain)."""
    host = host.lower().rstrip(".")
    for pattern in patterns:
        p = pattern.strip().lower().rstrip(".")
        if not p:
            continue
        if p.startswith("*."):
            if host.endswith(p[1:]) and host != p[2:]:
                return True
        elif host == p:
            return True
    return False


@dataclass(frozen=True)
class Target:
    """A checked URL: connect to ``address``, verify TLS against ``host``."""

    scheme: str
    host: str
    port: int
    address: str
    path: str


@dataclass(frozen=True)
class OutboundPolicy:
    """The operator's allowlist and the resolver to check addresses with.

    An empty allowlist allows nothing, so a fresh install makes no outbound calls.
    """

    allowed_hosts: tuple[str, ...] = ()
    allow_http_hosts: tuple[str, ...] = ()
    resolver: Resolver = system_resolver

    def check(self, url: str) -> Target:
        """Return where to connect, or raise :class:`BlockedURL`."""
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise BlockedURL("URL has no host")
        if parts.username or parts.password:
            raise BlockedURL("credentials in URLs are not allowed; use a secret reference")
        if scheme == "http":
            if not host_matches(host, self.allow_http_hosts):
                raise BlockedURL(f"plain HTTP to {host} is not allowed")
        elif scheme != "https":
            raise BlockedURL(f"scheme {scheme or 'none'} is not allowed")
        if host in METADATA_NAMES:
            raise BlockedURL(f"{host} is a cloud metadata endpoint")
        if not host_matches(host, self.allowed_hosts):
            raise BlockedURL(f"{host} is not in the collector host allowlist")
        try:
            port = parts.port or (443 if scheme == "https" else 80)
        except ValueError:
            raise BlockedURL("invalid port") from None
        addresses = list(self.resolver(host, port))
        if not addresses:
            raise BlockedURL(f"cannot resolve {host}")
        for address in addresses:
            try:
                ok = address_allowed(address)
            except ValueError:
                raise BlockedURL(f"{host} resolved to something that is not an address") from None
            if not ok:
                raise BlockedURL(f"{host} resolves to a blocked address ({address})")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return Target(scheme, host, port, addresses[0], path)
