"""Small IPv4 helpers shared by the routing, DNS and speed-test code.

These mirror the macOS implementation so both ports accept the same input and
produce the same canonical strings.
"""

from __future__ import annotations

import ipaddress
from typing import Optional, Tuple


def parse_ip(value: str) -> Optional[int]:
    """Return an IPv4 address as an integer, or ``None`` when invalid."""
    parts = value.strip().split(".")
    if len(parts) != 4:
        return None
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 or n > 255 for n in numbers):
        return None
    result = 0
    for n in numbers:
        result = (result << 8) | n
    return result


def ip_string(number: int) -> str:
    return ".".join(str((number >> (24 - 8 * i)) & 255) for i in range(4))


def parse_cidr(value: str) -> Optional[Tuple[str, str, str]]:
    """``"10.20.30.5/24"`` -> ``("10.20.30.0/24", "10.20.30.0", "255.255.255.0")``."""
    parts = value.strip().split("/")
    if len(parts) != 2:
        return None
    try:
        bits = int(parts[1])
    except ValueError:
        return None
    if not 0 <= bits <= 32:
        return None
    address = parse_ip(parts[0])
    if address is None:
        return None
    mask = 0 if bits == 0 else (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
    network = address & mask
    return f"{ip_string(network)}/{bits}", ip_string(network), ip_string(mask)


def normalize_cidr(value: str) -> Optional[str]:
    parsed = parse_cidr(value)
    return parsed[0] if parsed else None


def normalize_domain(value: str) -> Optional[str]:
    """``"https://portal.example.com/path"`` -> ``"portal.example.com"``."""
    host = value.strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0]
    if "." not in host:
        return None
    if not all(c.isalnum() or c in ".-" for c in host):
        return None
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return None
    return host


def first_ipv4(text: str) -> str:
    """Extract the first valid IPv4 address from arbitrary text/JSON."""
    token = ""
    for char in text:
        if char.isdigit() or char == ".":
            token += char
            continue
        if token:
            if parse_ip(token) is not None:
                return token
            token = ""
    if token and parse_ip(token) is not None:
        return token
    return ""


def network_contains(cidr: str, address: str) -> bool:
    """True when *address* is inside *cidr* (both dotted strings)."""
    try:
        return ipaddress.IPv4Address(address) in ipaddress.IPv4Network(cidr, strict=False)
    except ValueError:
        return False
