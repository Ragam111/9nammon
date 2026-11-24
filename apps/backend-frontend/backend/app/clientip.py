"""Resolve the client IP used for rate limits.

A forwarded header is trusted only when the direct peer is a configured proxy (TRUSTED_PROXY_CIDRS).
Otherwise any client could send its own X-Real-IP and get a fresh rate-limit bucket.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(items: Sequence[str]) -> list[IPNetwork]:
    """Parse CIDR strings such as "172.28.0.10/32". Blank entries are ignored; bad entries raise ValueError."""
    return [ipaddress.ip_network(item.strip(), strict=False) for item in items if item.strip()]


def resolve_client_ip(peer: str | None, headers: Mapping[str, str], trusted: Sequence[IPNetwork]) -> str:
    """Return the client IP.

    Uses X-Real-IP only when `peer` is inside a trusted network and the header is a valid IP.
    """
    if not peer:
        return "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer  # e.g. the test client's name; not an IP, so nothing to trust
    if not any(peer_ip in net for net in trusted):
        return peer
    real = headers.get("x-real-ip", "").strip()
    try:
        return str(ipaddress.ip_address(real))
    except ValueError:
        return peer
