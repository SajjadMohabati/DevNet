"""DNS presets and live resolver switching.

The helper applies a preset to every active link (including VPN links) and
keeps a root-owned backup so "Automatic" can restore what was there before.
"""

from __future__ import annotations

import concurrent.futures
import logging
import random
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from gi.repository import GLib

from . import privilege
from .ipv4 import ip_string, parse_ip
from .network import default_interface, interfaces, is_tunnel_name
from .shell import background, on_main, read_file, run, which
from .storage import Settings, data_dir, load_json, save_json

log = logging.getLogger(__name__)

HELPER_STATE = Path("/var/lib/devnet/dns.json")
RESOLV_CONF = Path("/etc/resolv.conf")


@dataclass
class DNSPreset:
    name: str
    servers: List[str]
    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "servers": list(self.servers)}

    @classmethod
    def from_dict(cls, value: dict) -> "DNSPreset":
        return cls(
            name=str(value.get("name", "Preset")),
            servers=[str(item) for item in value.get("servers", []) if parse_ip(str(item)) is not None],
            id=str(value.get("id") or __import__("uuid").uuid4().hex),
        )


DEFAULT_PRESETS: List[DNSPreset] = [
    DNSPreset("Shecan", ["178.22.122.100", "185.51.200.2"]),
    DNSPreset("Shecan Pro", ["178.22.122.101", "185.51.200.1"]),
    DNSPreset("Electro", ["78.157.42.100", "78.157.42.101"]),
    DNSPreset("Begzar", ["185.55.226.26", "185.55.225.25"]),
    DNSPreset("403", ["10.202.10.202", "10.202.10.102"]),
    DNSPreset("Radar Game", ["10.202.10.10", "10.202.10.11"]),
    DNSPreset("Google", ["8.8.8.8", "8.8.4.4"]),
    DNSPreset("Cloudflare", ["1.1.1.1", "1.0.0.1"]),
]


def migrate_presets(presets: List[DNSPreset]) -> None:
    for preset in presets:
        if preset.name == "Shecan" and preset.servers == ["178.22.122.100", "185.51.231.231"]:
            preset.servers = ["178.22.122.100", "185.51.200.2"]
    if not any(preset.servers[:1] == ["178.22.122.101"] for preset in presets):
        index = next((i for i, preset in enumerate(presets) if preset.name == "Shecan"), -1)
        presets.insert(index + 1 if index >= 0 else 0, DNSPreset("Shecan Pro", ["178.22.122.101", "185.51.200.1"]))


def parse_resolv_conf(text: str) -> List[str]:
    servers = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("nameserver "):
            value = line.split(None, 1)[1].strip()
            if parse_ip(value) is not None:
                servers.append(value)
    return servers


@dataclass
class ResolvedLink:
    name: str
    servers: List[str] = field(default_factory=list)
    default_route: bool = False


def parse_resolvectl_status(text: str) -> tuple[Dict[str, ResolvedLink], List[str]]:
    """Parse ``resolvectl status`` into per-link DNS and global servers."""
    links: Dict[str, ResolvedLink] = {}
    global_servers: List[str] = []
    current: Optional[str] = None
    global_block = False
    for line in text.splitlines():
        match = re.match(r"^Link\s+\d+\s+\(([^)]+)\)", line)
        if match:
            current = match.group(1)
            links.setdefault(current, ResolvedLink(current))
            global_block = False
            continue
        if line.startswith("Global"):
            current = None
            global_block = True
            continue
        if match := re.match(r"^\s*DNS Servers:\s*(.+)$", line):
            servers = [token for token in match.group(1).split() if parse_ip(token) is not None]
            if global_block:
                global_servers = servers
            elif current:
                links[current].servers = servers
            continue
        if match := re.match(r"^\s*Current DNS Server:\s*(.+)$", line):
            servers = [token for token in match.group(1).split() if parse_ip(token) is not None]
            if current and servers:
                links[current].servers = servers + [s for s in links[current].servers if s not in servers]
            continue
        if match := re.match(r"^\s*Default Route:\s*(\w+)", line):
            if current:
                links[current].default_route = match.group(1).lower() == "yes"
    return links, global_servers


def build_dns_query(host: str) -> bytes:
    transaction = random.randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", transaction, 0x0100, 1, 0, 0, 0)
    encoded = b"".join(bytes([len(part)]) + part.encode("ascii") for part in host.split(".") if part)
    return header + encoded + b"\x00" + struct.pack("!HH", 1, 1)


def dns_latency(server: str, host: str = "google.com", timeout: float = 2.0) -> int:
    """Raw UDP DNS round-trip in milliseconds, or -1 on timeout."""
    if parse_ip(server) is None:
        return -1
    query = build_dns_query(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        start = time.monotonic()
        sock.sendto(query, (server, 53))
        sock.recvfrom(2048)
        return int(round((time.monotonic() - start) * 1000))
    except OSError:
        return -1
    finally:
        sock.close()


def detect_backend() -> str:
    if which("resolvectl") and run(["resolvectl", "status"], timeout=4).returncode == 0:
        return "systemd-resolved"
    if which("nmcli") and run(["nmcli", "general", "status"], timeout=4).returncode == 0:
        return "NetworkManager"
    return "resolv.conf"


def read_applied_servers() -> List[str]:
    try:
        value = load_json(HELPER_STATE, {})
        servers = value.get("servers", []) if isinstance(value, dict) else []
        return [str(server) for server in servers if parse_ip(str(server)) is not None]
    except Exception:
        return []


class DNSStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.file = data_dir() / "dns.json"
        saved = load_json(self.file, None)
        if isinstance(saved, list):
            self.presets = [DNSPreset.from_dict(item) for item in saved if isinstance(item, dict)]
            migrate_presets(self.presets)
        else:
            self.presets = list(DEFAULT_PRESETS)
            initial = self._effective_dns()
            if initial and not any(preset.servers == initial for preset in self.presets):
                self.presets.append(DNSPreset("Previous", initial))
        self.save()

        self.backend = "resolv.conf"
        self.links: List[str] = []
        self.current: List[str] = []
        self.current_iface = ""
        self.configured: List[str] = []
        self.service = str(settings.get("dns_link", ""))
        self.error: Optional[str] = None
        self.latency: Dict[str, int] = {}
        self.testing = False
        self.flushed = False
        self.applying = False
        self.applied = read_applied_servers()
        self._last_reapply = 0.0
        self._refreshing = False
        self._listeners: List[Callable[[], None]] = []

        self.refresh()
        GLib.timeout_add_seconds(20, self._maintenance_tick)

    # ------------------------------------------------------------------ events

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
                log.exception("DNS listener failed")

    def _notify_main(self) -> None:
        on_main(self.notify)

    # --------------------------------------------------------------- properties

    @property
    def helper_installed(self) -> bool:
        return privilege.helper_installed()

    @property
    def passwordless(self) -> bool:
        return privilege.passwordless()

    @property
    def busy(self) -> bool:
        return self.applying

    @property
    def vpn_controls_dns(self) -> bool:
        return is_tunnel_name(default_interface())

    @property
    def active_preset(self) -> Optional[DNSPreset]:
        # Resolvers may reorder or prepend the current server, so compare sets
        # rather than the exact list order.
        def same(values: List[str]) -> bool:
            return bool(values) and set(values) == set(self.current)

        for preset in self.presets:
            if same(preset.servers):
                return preset
        for preset in self.presets:
            if self.configured and set(preset.servers) == set(self.configured):
                return preset
        for preset in self.presets:
            if self.applied and set(preset.servers) == set(self.applied):
                return preset
        return None

    def is_active(self, preset: DNSPreset) -> bool:
        active = self.active_preset
        return active is not None and active.id == preset.id

    # ---------------------------------------------------------------- persistence

    def save(self) -> None:
        save_json(self.file, [preset.to_dict() for preset in self.presets])

    # ------------------------------------------------------------------ reading

    def _effective_dns(self) -> List[str]:
        if which("resolvectl"):
            result = run(["resolvectl", "status"], timeout=5)
            if result.returncode == 0:
                links, global_servers = parse_resolvectl_status(result.stdout)
                default = default_interface()
                if default in links and links[default].servers:
                    return links[default].servers
                for link in links.values():
                    if link.default_route and link.servers:
                        return link.servers
                if global_servers:
                    return global_servers
                for link in links.values():
                    if link.servers:
                        return link.servers
        return parse_resolv_conf(read_file(str(RESOLV_CONF)))

    def _read_links(self) -> tuple[str, List[str], Dict[str, ResolvedLink], List[str], str]:
        backend = detect_backend()
        links_map: Dict[str, ResolvedLink] = {}
        global_servers: List[str] = []
        if backend == "systemd-resolved":
            result = run(["resolvectl", "status"], timeout=5)
            if result.returncode == 0:
                links_map, global_servers = parse_resolvectl_status(result.stdout)
        names = [name for name in links_map if name != "lo"] if links_map else interfaces(up_only=True)
        default = default_interface()
        names.sort(key=lambda name: (name != default, name))
        current = self._effective_dns()
        iface = default if default in names else (names[0] if names else "")
        if backend == "systemd-resolved":
            if default in links_map and links_map[default].servers:
                iface = default
            else:
                for link in links_map.values():
                    if link.default_route and link.servers:
                        iface = link.name
                        break
        return backend, names, links_map, global_servers, iface

    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        background(self._refresh_worker)

    def _refresh_worker(self) -> None:
        backend, names, links_map, _global, iface = self._read_links()
        current = self._effective_dns()
        service = self.service if self.service in names else (names[0] if names else "")
        configured = links_map[service].servers if service in links_map else []
        applied = read_applied_servers()

        def update() -> None:
            self._refreshing = False
            self.backend = backend
            self.links = names
            if service and service != self.service:
                self.service = service
                self.settings.set("dns_link", service)
            self.current = current
            self.current_iface = iface
            self.configured = configured
            self.applied = applied
            self.notify()

        on_main(update)

    def select_link(self, link: str) -> None:
        self.service = link
        self.settings.set("dns_link", link)
        self.refresh()

    # ------------------------------------------------------------------ changes

    def apply(self, servers: List[str]) -> None:
        if self.applying:
            return
        self.applying = True
        self.error = None
        self._notify_main()
        background(lambda: self._apply_worker(list(servers)))

    def _apply_worker(self, servers: List[str], quiet: bool = False) -> None:
        error = privilege.dns_set(servers)
        on_main(lambda: self._after_apply(servers, error, quiet))

    def _after_apply(self, servers: List[str], error: str, quiet: bool = False) -> None:
        self.applying = False
        if error:
            self.error = error
        else:
            self.applied = list(servers)
            self.settings.set("dns_applied", list(servers))
            if not servers:
                self.settings.pop("dns_applied", None)
        self.notify()
        self.refresh()
        if not error and servers and not quiet:
            # The helper reports success, but make sure the resolver really sees it.
            def verify() -> None:
                if set(self.current) != set(servers):
                    self.error = (
                        f"The {self.backend} backend did not accept the change. "
                        "See the Linux README for supported DNS setups."
                    )
                    self.notify()

            GLib.timeout_add(1200, lambda: (verify(), False)[1])

    def flush_cache(self) -> None:
        background(self._flush_worker)

    def _flush_worker(self) -> None:
        error = privilege.dns_flush()
        on_main(lambda: self._after_flush(error))

    def _after_flush(self, error: str) -> None:
        if error:
            self.error = error
            self.notify()
            return
        self.flushed = True
        self.notify()
        GLib.timeout_add(2000, self._reset_flushed)

    def _reset_flushed(self) -> bool:
        self.flushed = False
        self.notify()
        return False

    def _maintenance_tick(self) -> bool:
        # Keep an active preset applied when a link reconnects, but only when a
        # passwordless rule exists so the app never pops an unexpected prompt.
        if (
            self.applied
            and not self.applying
            and self.passwordless
            and time.monotonic() - self._last_reapply > 30
            and set(self.applied) != set(self.current)
        ):
            self._last_reapply = time.monotonic()
            self.applying = True
            self.notify()
            background(lambda: self._apply_worker(list(self.applied), quiet=True))
        else:
            self.refresh()
        return True

    def test_latency(self) -> None:
        if self.testing:
            return
        self.testing = True
        self.latency = {}
        self.notify()
        servers = sorted({preset.servers[0] for preset in self.presets if preset.servers})
        background(lambda: self._latency_worker(servers))

    def _latency_worker(self, servers: List[str]) -> None:
        results: Dict[str, int] = {}
        if servers:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(servers))) as pool:
                for server, value in zip(servers, pool.map(dns_latency, servers)):
                    results[server] = value
        on_main(lambda: self._after_latency(results))

    def _after_latency(self, results: Dict[str, int]) -> None:
        self.latency = results
        self.testing = False
        self.notify()

    def upsert(self, index: Optional[int], name: str, servers: str) -> Optional[str]:
        tokens = re.split(r"[, \n\u060c]+", servers.strip())
        values = [token for token in tokens if token]
        name = name.strip()
        if not name:
            return "Enter a name."
        if not values or any(parse_ip(token) is None for token in values):
            return "Enter one or more IPv4 addresses."
        normalized = [ip_string(parse_ip(token) or 0) for token in values]
        if index is not None and 0 <= index < len(self.presets):
            self.presets[index].name = name
            self.presets[index].servers = normalized
        else:
            self.presets.append(DNSPreset(name=name, servers=normalized))
        self.save()
        self.notify()
        return None

    def remove(self, preset: DNSPreset) -> None:
        self.presets = [item for item in self.presets if item.id != preset.id]
        self.save()
        self.notify()


# Keep the dataclass import referenced for callers that reconstruct presets.
__all__ = ["DNSStore", "DNSPreset", "DEFAULT_PRESETS", "dns_latency", "parse_resolvectl_status"]
