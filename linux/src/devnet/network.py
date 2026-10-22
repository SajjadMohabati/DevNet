"""Read Linux network state: interfaces, routes, VPNs and public addresses.

Everything here is read-only. Mutating routes is done by the scoped root helper.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import ssl
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Callable

from .ipv4 import first_ipv4, ip_string, parse_cidr, parse_ip
from .shell import background, on_main, run, sh, which

log = logging.getLogger(__name__)

SYS_NET = Path("/sys/class/net")

TUNNEL_PREFIXES = (
    "tun",
    "tap",
    "wg",
    "ppp",
    "ipsec",
    "utun",
    "tailscale",
    "zt",
    "nebula",
    "nordlynx",
    "proton",
    "mullvad",
    "sing",
    "clash",
    "xray",
    "v2ray",
)
VIRTUAL_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "virbr",
    "veth",
    "vmnet",
    "vboxnet",
    "cni",
    "flannel",
    "kube",
    "lxc",
    "lxd",
    "podman",
    "incus",
)
VM_PREFIXES = ("en", "eth", "wl", "wlan", "ww", "ib", "bond", "team", "em")


def is_tunnel_name(name: str) -> bool:
    return name.startswith(TUNNEL_PREFIXES)


def is_virtual_name(name: str) -> bool:
    return name.startswith(VIRTUAL_PREFIXES)


def is_physical_interface(name: str) -> bool:
    if name == "lo" or is_virtual_name(name) or is_tunnel_name(name):
        return False
    if (SYS_NET / name / "device").exists() or (SYS_NET / name / "wireless").exists():
        return True
    return name.startswith(VM_PREFIXES)


def interfaces(up_only: bool = False) -> List[str]:
    try:
        names = sorted(p.name for p in SYS_NET.iterdir())
    except OSError:
        return []
    result = []
    for name in names:
        if name == "lo":
            continue
        if up_only:
            try:
                state = (SYS_NET / name / "operstate").read_text(encoding="utf-8").strip()
            except OSError:
                state = ""
            if state in {"down", "notpresent", "lowerlayerdown"}:
                continue
        result.append(name)
    return result


def physical_interfaces(up_only: bool = False) -> List[str]:
    return [name for name in interfaces(up_only) if is_physical_interface(name)]


def ipv4_address(interface: str) -> str:
    output = sh("ip", "-4", "-o", "addr", "show", "dev", interface, "scope", "global")
    match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", output)
    return match.group(1) if match else ""


@dataclass
class RouteEntry:
    cidr: str
    gateway: Optional[str] = None
    device: Optional[str] = None
    source: Optional[str] = None
    metric: Optional[int] = None
    scope: Optional[str] = None
    protocol: Optional[str] = None
    raw: str = ""

    def same_path(self, gateway: Optional[str], device: Optional[str]) -> bool:
        return self.gateway == gateway and self.device == device


def _route_tokens(line: str) -> List[str]:
    return line.strip().split()


def parse_route_line(line: str) -> Optional[RouteEntry]:
    """Parse one line of ``ip -4 route`` output."""
    line = line.strip()
    if not line:
        return None
    tokens = _route_tokens(line)
    if not tokens:
        return None
    if tokens[0] in {"local", "broadcast", "unreachable", "blackhole", "prohibit", "throw"}:
        return None

    cidr: Optional[str] = None
    index = 0
    if tokens[0] == "default":
        cidr = "0.0.0.0/0"
        index = 1
    else:
        if "/" in tokens[0]:
            parsed = parse_cidr(tokens[0])
            if parsed is None:
                return None
            cidr = parsed[0]
            index = 1
        elif parse_ip(tokens[0]) is not None:
            cidr = f"{tokens[0]}/32"
            index = 1
    if cidr is None:
        return None

    entry = RouteEntry(cidr=cidr, raw=line)
    rest = tokens[index:]
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "via" and i + 1 < len(rest):
            entry.gateway = rest[i + 1]
            i += 2
        elif token == "dev" and i + 1 < len(rest):
            entry.device = rest[i + 1]
            i += 2
        elif token == "src" and i + 1 < len(rest):
            entry.source = rest[i + 1]
            i += 2
        elif token == "metric" and i + 1 < len(rest):
            try:
                entry.metric = int(rest[i + 1])
            except ValueError:
                entry.metric = None
            i += 2
        elif token == "scope" and i + 1 < len(rest):
            entry.scope = rest[i + 1]
            i += 2
        elif token == "proto" and i + 1 < len(rest):
            entry.protocol = rest[i + 1]
            i += 2
        else:
            i += 1
    return entry


def routing_table() -> Dict[str, RouteEntry]:
    """The IPv4 main routing table, keyed by canonical CIDR."""
    output = sh("ip", "-4", "route", "show")
    table: Dict[str, RouteEntry] = {}
    for line in output.splitlines():
        entry = parse_route_line(line)
        if entry is None:
            continue
        previous = table.get(entry.cidr)
        if previous is None:
            table[entry.cidr] = entry
            continue
        # Keep the lowest-metric path; entries without a metric sort last.
        old_metric = previous.metric if previous.metric is not None else 1 << 30
        new_metric = entry.metric if entry.metric is not None else 1 << 30
        if new_metric < old_metric:
            table[entry.cidr] = entry
    return table


def default_routes() -> List[RouteEntry]:
    output = sh("ip", "-4", "route", "show", "default")
    seen = {}
    for line in output.splitlines():
        entry = parse_route_line(line)
        if entry is not None and entry.cidr == "0.0.0.0/0":
            seen[(entry.gateway, entry.device, entry.metric)] = entry
    return list(seen.values())


def parse_route_get(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    tokens = text.split()
    i = 0
    while i < len(tokens):
        if tokens[i] in {"via", "dev", "src", "uid", "table", "mark", "pref"} and i + 1 < len(tokens):
            result[tokens[i]] = tokens[i + 1]
            i += 2
        else:
            i += 1
    return result


def route_get(host: str) -> Dict[str, str]:
    result = run(["ip", "-4", "route", "get", host], timeout=5)
    if result.returncode != 0:
        return {}
    return parse_route_get(result.stdout)


def _nmcli_gateway(interface: str) -> str:
    if not which("nmcli"):
        return ""
    output = sh("nmcli", "-g", "IP4.GATEWAY", "device", "show", interface, timeout=5)
    for line in output.splitlines():
        if parse_ip(line.strip()) is not None:
            return line.strip()
    return ""


@dataclass
class LanRoute:
    gateway: str = ""
    device: str = ""
    local_ip: str = ""

    @property
    def valid(self) -> bool:
        return parse_ip(self.gateway) is not None and bool(self.device)


def lan_route() -> LanRoute:
    """The router of the physical network, even when a VPN owns the default route."""
    defaults = default_routes()
    candidates = [r for r in defaults if r.device and is_physical_interface(r.device) and r.gateway]
    candidates.sort(key=lambda r: r.metric if r.metric is not None else 1 << 30)
    for entry in candidates:
        if entry.gateway and parse_ip(entry.gateway) is not None:
            return LanRoute(entry.gateway, entry.device or "", ipv4_address(entry.device or ""))

    # The VPN may have replaced the default route. Look for any physical route
    # with a gateway, then ask NetworkManager for the DHCP gateway.
    table = routing_table()
    physical = [r for r in table.values() if r.device and is_physical_interface(r.device) and r.gateway]
    physical.sort(key=lambda r: r.metric if r.metric is not None else 1 << 30)
    for entry in physical:
        return LanRoute(entry.gateway or "", entry.device or "", ipv4_address(entry.device or ""))

    for name in physical_interfaces(up_only=True):
        gateway = _nmcli_gateway(name)
        if gateway:
            return LanRoute(gateway, name, ipv4_address(name))

    # Last resort: the current default route, if it is physical.
    for entry in defaults:
        if entry.gateway and entry.device and is_physical_interface(entry.device):
            return LanRoute(entry.gateway, entry.device, ipv4_address(entry.device))
    return LanRoute()


def detect_gateway() -> str:
    return lan_route().gateway


def device_for_gateway(gateway: str) -> str:
    """Interface that reaches *gateway*."""
    if parse_ip(gateway) is None:
        return ""
    info = route_get(gateway)
    return info.get("dev", "")


def default_interface() -> str:
    info = route_get("1.1.1.1")
    return info.get("dev", "")


def ping_host(host: str, timeout: int = 2) -> Optional[int]:
    """One ICMP echo, in milliseconds. Returns None when there is no answer."""
    if not which("ping"):
        return tcp_ping(host, timeout)
    result = run(["ping", "-4", "-c", "1", "-W", str(max(1, timeout)), "-n", host], timeout=timeout + 2)
    if result.returncode != 0:
        return None
    match = re.search(r"time[=<]\s*([\d.]+)\s*ms", result.stdout)
    if not match:
        return None
    try:
        return int(round(float(match.group(1))))
    except ValueError:
        return None


def tcp_ping(host: str, timeout: int = 2) -> Optional[int]:
    """Latency to a TCP port, used only when ``ping`` is unavailable."""
    import time

    try:
        start = time.monotonic()
        with socket.create_connection((host, 443), timeout=timeout):
            pass
        return int(round((time.monotonic() - start) * 1000))
    except OSError:
        return None


def gateway_reachable(gateway: str) -> Optional[bool]:
    if parse_ip(gateway) is None:
        return None
    if not which("ping"):
        return None
    result = run(["ping", "-4", "-c", "1", "-W", "1", "-n", gateway], timeout=3)
    return " 0% packet loss" in result.stdout or " 0.0% packet loss" in result.stdout


@dataclass
class Tunnel:
    name: str
    kind: str
    iface: str
    public_ip: str = ""

    @property
    def id(self) -> str:
        return self.iface


_NM_TYPE_NAMES = {
    "wireguard": "WireGuard",
    "vpn": "VPN",
    "tun": "Tunnel",
    "tap": "Tunnel",
    "ipsec": "IPsec",
    "l2tp": "L2TP",
    "pptp": "PPTP",
    "openvpn": "OpenVPN",
}


def _kind_for(name: str, conn_type: str) -> str:
    lower = f"{name} {conn_type}".lower()
    if "wireguard" in lower:
        return "WireGuard"
    if "proton" in lower:
        return "ProtonVPN"
    if "openvpn" in lower:
        return "OpenVPN"
    if "tailscale" in lower:
        return "Tailscale"
    return _NM_TYPE_NAMES.get(conn_type.lower(), conn_type.capitalize() or "VPN")


def _split_nmcli(line: str) -> List[str]:
    """Split nmcli's escaped ``-t`` output on unescaped colons."""
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def tunnels(default_iface: str = "") -> List[Tunnel]:
    found: Dict[str, Tunnel] = {}
    if which("nmcli"):
        output = sh("nmcli", "-t", "-f", "UUID,NAME,TYPE,DEVICE", "connection", "show", "--active", timeout=8)
        for line in output.splitlines():
            fields = _split_nmcli(line)
            if len(fields) < 4:
                continue
            uuid, name, conn_type, device = fields[:4]
            lookup = f"{name} {conn_type}".lower()
            is_vpn = conn_type in {"vpn", "wireguard", "tun", "tap", "ipsec", "l2tp", "pptp"} or any(
                word in lookup for word in ("vpn", "wireguard", "openvpn", "proton", "tailscale")
            )
            if not device and is_vpn:
                devices = sh("nmcli", "-g", "GENERAL.DEVICES", "connection", "show", uuid, timeout=5)
                device = next((d.strip() for d in devices.splitlines() if d.strip()), "")
            if is_vpn and device:
                found[device] = Tunnel(name=name or "Tunnel", kind=_kind_for(name, conn_type), iface=device)

    for name in interfaces(up_only=True):
        if is_tunnel_name(name) and name not in found:
            found[name] = Tunnel(name="Tunnel", kind="Tunnel", iface=name)

    result = list(found.values())
    result.sort(key=lambda t: (t.iface != default_iface, t.iface))
    return result


def _fetch_ipv4(url: str, source_ip: str = "", timeout: float = 4.0, user_agent: str = "DevNet/1.2") -> str:
    """Fetch a tiny URL, optionally from one interface's source address."""
    import http.client
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return ""
    try:
        connection = http.client.HTTPSConnection(
            parts.hostname,
            parts.port or 443,
            timeout=timeout,
            context=ssl.create_default_context(),
            source_address=(source_ip, 0) if source_ip else None,
        )
        try:
            connection.request(
                "GET",
                parts.path or "/",
                headers={"User-Agent": user_agent, "Accept": "text/plain,application/json"},
            )
            response = connection.getresponse()
            text = response.read(4096).decode("utf-8", "replace")
        finally:
            connection.close()
        return first_ipv4(text)
    except Exception:
        return ""


def public_ip(interface: str) -> str:
    address = ipv4_address(interface)
    if not address:
        return ""
    return _fetch_ipv4("https://api.ipify.org", source_ip=address)


def routed_ip() -> str:
    return _fetch_ipv4("https://ipapi.ir")


def country_name(code: str) -> str:
    """English country name from iso-codes when installed, else the code."""
    path = Path("/usr/share/iso-codes/json/iso_3166-1.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("3166-1", []):
            if entry.get("alpha_2", "").lower() == code.lower():
                return entry.get("name", code.upper())
    except (OSError, ValueError):
        pass
    return code.upper()


@dataclass
class NetworkSnapshot:
    default_iface: str = ""
    physical_iface: str = ""
    local_ip: str = ""
    gateway: str = ""
    gateway_up: Optional[bool] = None
    tunnels: List[Tunnel] = field(default_factory=list)
    direct_ip: str = ""
    routed_ip: str = ""


def snapshot() -> NetworkSnapshot:
    default_dev = default_interface()
    lan = lan_route()
    physical = lan.device or (physical_interfaces(up_only=True) or [""])[0]
    return NetworkSnapshot(
        default_iface=default_dev,
        physical_iface=physical,
        local_ip=ipv4_address(physical) if physical else "",
        gateway=lan.gateway,
        gateway_up=gateway_reachable(lan.gateway),
        tunnels=tunnels(default_dev),
    )


def vpn_active(default_iface: str, tunnel_list: Iterable[Tunnel]) -> bool:
    return bool(list(tunnel_list)) or is_tunnel_name(default_iface)


class NetStore:
    """Observable network summary for the sidebar and the panel."""

    def __init__(self) -> None:
        self.default_iface = ""
        self.physical_iface = ""
        self.local_ip = ""
        self.gateway = ""
        self.gateway_up: Optional[bool] = None
        self.tunnels: List[Tunnel] = []
        self.direct_ip = ""
        self.routed_ip = ""
        self._listeners: List[Callable[[], None]] = []
        self._refreshing = False
        self._closed = False

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                log.exception("network listener failed")

    def close(self) -> None:
        self._closed = True
        self._listeners.clear()

    @property
    def vpn(self) -> bool:
        return bool(self.tunnels) or is_tunnel_name(self.default_iface)

    @property
    def vpn_ip(self) -> str:
        for tunnel in self.tunnels:
            if tunnel.iface == self.default_iface:
                return tunnel.public_ip
        if self.tunnels:
            return self.tunnels[0].public_ip
        return self.direct_ip

    def refresh(self) -> None:
        if self._refreshing or self._closed:
            return
        self._refreshing = True
        background(self._refresh_worker)

    def _refresh_worker(self) -> None:
        try:
            snap = snapshot()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("network refresh failed: %s", exc)
            on_main(self._fail)
            return

        jobs: List[tuple] = []
        if snap.physical_iface:
            jobs.append(("direct", lambda name=snap.physical_iface: public_ip(name)))
        for tunnel in snap.tunnels:
            jobs.append((tunnel.iface, lambda name=tunnel.iface: public_ip(name)))
        jobs.append(("routed", routed_ip))
        results: Dict[str, str] = {}
        if jobs:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
                futures = {pool.submit(job): key for key, job in jobs}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results[futures[future]] = future.result()
                    except Exception:
                        results[futures[future]] = ""
        on_main(lambda: self._publish(snap, results))

    def _fail(self) -> None:
        self._refreshing = False
        self.notify()

    def _publish(self, snap: NetworkSnapshot, results: Dict[str, str]) -> None:
        self._refreshing = False
        if self._closed:
            return
        self.default_iface = snap.default_iface
        self.physical_iface = snap.physical_iface
        self.local_ip = snap.local_ip
        self.gateway = snap.gateway
        self.gateway_up = snap.gateway_up
        self.tunnels = snap.tunnels
        for tunnel in self.tunnels:
            tunnel.public_ip = results.get(tunnel.iface, "")
        self.direct_ip = results.get("direct", "")
        self.routed_ip = results.get("routed", "")
        self.notify()



__all__ = [
    "LanRoute",
    "NetStore",
    "NetworkSnapshot",
    "RouteEntry",
    "Tunnel",
    "country_name",
    "default_interface",
    "default_routes",
    "detect_gateway",
    "device_for_gateway",
    "gateway_reachable",
    "interfaces",
    "ipv4_address",
    "is_physical_interface",
    "is_tunnel_name",
    "lan_route",
    "parse_route_get",
    "parse_route_line",
    "physical_interfaces",
    "ping_host",
    "public_ip",
    "routed_ip",
    "route_get",
    "routing_table",
    "snapshot",
    "tcp_ping",
    "tunnels",
    "vpn_active",
]
