"""Split-tunneling routes.

A route stores what the user *wants*. ``reconcile`` compares that with the
live Linux routing table and applies only the difference, one batch at a time.
Repeated clicks, network changes and partial failures therefore converge.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

try:
    from gi.repository import GLib
except (ImportError, ModuleNotFoundError):
    GLib = None  # type: ignore

from . import privilege
from .ipv4 import ip_string, normalize_cidr, normalize_domain, parse_cidr, parse_ip
from .network import country_name, device_for_gateway, lan_route, route_get, routing_table
from .shell import background, on_main
from .storage import data_dir, load_json, save_json

log = logging.getLogger(__name__)

COUNTRY_URL = "https://www.ipdeny.com/ipblocks/data/aggregated/{code}-aggregated.zone"


@dataclass
class Route:
    net: str
    gateway: Optional[str] = None
    note: str = ""
    resolved: Optional[List[str]] = None
    country: Optional[str] = None
    ranges: Optional[List[str]] = None
    enabled: Optional[bool] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def is_list(self) -> bool:
        return self.ranges is not None

    @property
    def is_domain(self) -> bool:
        return not self.is_list and parse_cidr(self.net) is None

    @property
    def targets(self) -> List[str]:
        if self.ranges is not None:
            return list(self.ranges)
        if self.is_domain:
            return [f"{address}/32" for address in (self.resolved or [])]
        normalized = normalize_cidr(self.net)
        return [normalized] if normalized else []

    def to_dict(self) -> dict:
        value = {
            "id": self.id,
            "net": self.net,
            "note": self.note,
        }
        if self.gateway is not None:
            value["gateway"] = self.gateway
        if self.resolved is not None:
            value["resolved"] = list(self.resolved)
        if self.country is not None:
            value["country"] = self.country
        if self.ranges is not None:
            value["list"] = list(self.ranges)
        if self.enabled is not None:
            value["enabled"] = bool(self.enabled)
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "Route":
        ranges = value.get("list")
        route = cls(
            net=str(value.get("net", "")),
            gateway=value.get("gateway"),
            note=str(value.get("note", "")),
            resolved=list(value["resolved"]) if value.get("resolved") is not None else None,
            country=value.get("country"),
            ranges=list(ranges) if ranges is not None else None,
            enabled=value.get("enabled"),
            id=str(value.get("id") or uuid.uuid4().hex),
        )
        return route


@dataclass
class Config:
    gateway: str = ""
    routes: List[Route] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"gateway": self.gateway, "routes": [route.to_dict() for route in self.routes]}

    @classmethod
    def from_dict(cls, value: dict) -> "Config":
        routes = [Route.from_dict(item) for item in value.get("routes", []) if isinstance(item, dict)]
        return cls(gateway=str(value.get("gateway", "")), routes=routes)


def fetch_country_ranges(code: str) -> List[str]:
    request = urllib.request.Request(
        COUNTRY_URL.format(code=code),
        headers={"User-Agent": "DevNet/1.2 (+https://github.com/SajjadMohabati/DevNet)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception:
        return []
    ranges: List[str] = []
    for line in text.splitlines():
        parsed = parse_cidr(line.strip())
        if parsed:
            ranges.append(parsed[0])
    return ranges


def resolve_ipv4(host: str) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return []
    addresses = {info[4][0] for info in infos if parse_ip(info[4][0]) is not None}
    return sorted(addresses)


class RouteStore:
    """State + reconciler for the Routes pane."""

    def __init__(self, autostart: bool = True) -> None:
        self.path = data_dir() / "routes.json"
        raw = load_json(self.path, {})
        self.config = Config.from_dict(raw) if isinstance(raw, dict) else Config()
        self.error: Optional[str] = None
        self.pending = 0
        self.hits: Dict[str, int] = {}
        lan = lan_route()
        self.lan_gateway = lan.gateway
        self.lan_device = lan.device
        self.lan_ip = lan.local_ip
        self._listeners: List[Callable[[], None]] = []
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._updating_gateway = False

        if self.config.routes and all(route.enabled is None for route in self.config.routes):
            # Upgrade from a config created before on/off state existed.
            table = routing_table()
            for route in self.config.routes:
                route.enabled = bool(route.targets) and any(
                    target in table and table[target].gateway is not None for target in route.targets
                )
            self.config.gateway = ""
        self.save()

        if autostart:
            self._ensure_worker()
            self.reconcile()
            if GLib is not None:
                GLib.timeout_add_seconds(10, self._gateway_tick)

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
                log.exception("route listener failed")

    def _notify_main(self) -> None:
        on_main(self.notify)

    # --------------------------------------------------------------- properties

    @property
    def busy(self) -> bool:
        return self.pending > 0

    @property
    def active(self) -> Dict[str, bool]:
        return {route.id: bool(route.enabled) for route in self.config.routes}

    @property
    def active_count(self) -> int:
        return sum(1 for route in self.config.routes if route.enabled is True)

    @property
    def all_on(self) -> bool:
        return bool(self.config.routes) and self.active_count == len(self.config.routes)

    def is_partial(self, route: Route) -> bool:
        return bool(route.enabled) and self.hits.get(route.id, 0) < len(route.targets)

    @property
    def current_gateway(self) -> str:
        return self.config.gateway or self.lan_gateway

    def gateway_for(self, route: Route) -> str:
        return route.gateway or self.current_gateway

    # ---------------------------------------------------------------- persistence

    def save(self) -> None:
        save_json(self.path, self.config.to_dict())

    # ------------------------------------------------------------------- reading

    def refresh(self) -> None:
        if self.pending:
            return
        routes = [(route.id, route.targets, self.gateway_for(route)) for route in self.config.routes]
        background(lambda: self._refresh_worker(routes))

    def _refresh_worker(self, routes: Sequence[tuple]) -> None:
        table = routing_table()
        hits = {}
        for route_id, targets, gateway in routes:
            hits[route_id] = sum(
                1 for target in targets if target in table and table[target].gateway == gateway
            )
        on_main(lambda: self._apply_hits(hits))

    def _apply_hits(self, hits: Dict[str, int]) -> None:
        self.hits = hits
        self.notify()

    # ---------------------------------------------------------------- reconciling

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="devnet-routes", daemon=True)
        self._worker.start()

    def reconcile(self, also_remove: Optional[Sequence[str]] = None) -> None:
        wanted = [(route.enabled is True, list(route.targets), self.gateway_for(route)) for route in self.config.routes]
        remove = list(also_remove or [])
        self._ensure_worker()
        self.pending += 1
        self._queue.put((wanted, remove))
        self._notify_main()

    def _worker_loop(self) -> None:
        while True:
            wanted, also_remove = self._queue.get()
            error: Optional[str] = None
            try:
                operations = self._plan(wanted, also_remove)
                if operations:
                    error = privilege.routes_apply(operations)
                    if not error:
                        retry = self._plan(wanted, also_remove)
                        if retry:
                            error = privilege.routes_apply(retry)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("reconcile failed")
                error = str(exc)
            on_main(lambda e=error: self._finish_reconcile(e))

    def _finish_reconcile(self, error: Optional[str]) -> None:
        self.pending = max(0, self.pending - 1)
        if error:
            self.error = error
        self.notify()
        self.refresh()

    def _plan(self, wanted: Sequence[tuple], also_remove: Sequence[str]) -> List[dict]:
        table = routing_table()
        operations: List[dict] = []
        seen = set()
        keep = set()
        device_cache: Dict[str, str] = {}

        def device_for(gateway: str) -> str:
            if gateway == self.lan_gateway and self.lan_device:
                return self.lan_device
            if gateway not in device_cache:
                info = route_get(gateway)
                device_cache[gateway] = info.get("dev", "") or self.lan_device
            return device_cache[gateway]

        def add(op: str, cidr: str, gateway: Optional[str] = None, device: Optional[str] = None) -> None:
            key = (op, cidr, gateway, device)
            if key in seen:
                return
            seen.add(key)
            value = {"op": op, "cidr": cidr}
            if gateway:
                value["gateway"] = gateway
            if device:
                value["device"] = device
            operations.append(value)

        enabled_networks = []
        for on, targets, gateway in wanted:
            if not on or parse_ip(gateway) is None:
                continue
            device = device_for(gateway)
            if not device:
                continue
            for target in targets:
                cidr = normalize_cidr(target)
                if not cidr:
                    continue
                keep.add(cidr)
                parsed = parse_cidr(cidr)
                if parsed and not cidr.endswith("/32"):
                    enabled_networks.append((parsed, gateway, device))
                current = table.get(cidr)
                if current and current.same_path(gateway, device):
                    continue
                add("replace", cidr, gateway, device)

        # Cached host routes (cloned while traffic went elsewhere, e.g. into the
        # VPN) override our network routes for that address. Drop the ones inside
        # an enabled range that still use another IP gateway.
        for cidr, entry in table.items():
            if not cidr.endswith("/32") or cidr in keep:
                continue
            if not entry.gateway or parse_ip(entry.gateway) is None:
                continue
            address = parse_ip(cidr[:-3])
            if address is None:
                continue
            for parsed, gateway, device in enabled_networks:
                network_int = parse_ip(parsed[1]) or 0
                mask_int = parse_ip(parsed[2]) or 0
                if parsed[0].endswith("/32"):
                    continue
                if address & mask_int == network_int and entry.gateway != gateway:
                    add("delete", cidr, entry.gateway, entry.device)
                    break

        # Turn off routes that are no longer wanted (only explicit IP gateways,
        # never interface-only routes that belong to a VPN).
        off = [target for on, targets, _gateway in wanted if not on for target in targets]
        for target in list(off) + list(also_remove):
            cidr = normalize_cidr(target)
            if not cidr or cidr in keep:
                continue
            entry = table.get(cidr)
            if entry and entry.gateway and parse_ip(entry.gateway) is not None:
                add("delete", cidr, entry.gateway, entry.device)
        return operations

    # --------------------------------------------------------------- mutations

    def _resolve(self, index: int) -> List[str]:
        route = self.config.routes[index]
        if not route.is_domain:
            return []
        old_targets = set(route.targets)
        addresses = resolve_ipv4(route.net)
        if not addresses:
            self.error = f"Couldn’t resolve {route.net}."
            self._notify_main()
            return []
        route.resolved = addresses
        return sorted(old_targets.difference(route.targets))

    def set(self, route: Route, enabled: bool) -> None:
        index = next((i for i, item in enumerate(self.config.routes) if item.id == route.id), None)
        if index is None:
            return
        stale = self._resolve(index) if enabled else []
        self.config.routes[index].enabled = enabled
        self.save()
        self.notify()
        self.reconcile(also_remove=stale)

    def set_all(self, enabled: bool) -> None:
        stale: List[str] = []
        for index in range(len(self.config.routes)):
            if enabled:
                stale += self._resolve(index)
            self.config.routes[index].enabled = enabled
        self.save()
        self.notify()
        self.reconcile(also_remove=stale)

    def upsert(self, index: Optional[int], net: str, gateway: str, note: str) -> Optional[str]:
        parsed_cidr = parse_cidr(net)
        if parsed_cidr:
            target = parsed_cidr[0]
        else:
            domain = normalize_domain(net)
            if not domain:
                return "Enter a network (10.20.30.0/24) or a domain (example.com)."
            target = domain

        gateway = gateway.strip()
        if gateway and parse_ip(gateway) is None:
            return "The gateway must be an IPv4 address."

        new_route = Route(
            net=target,
            gateway=ip_string(parse_ip(gateway)) if gateway else None,
            note=note.strip(),
        )
        stale: List[str] = []
        if index is not None and 0 <= index < len(self.config.routes):
            old = self.config.routes[index]
            new_route.id = old.id
            new_route.enabled = old.enabled
            if old.net == new_route.net:
                new_route.resolved = old.resolved
            else:
                stale = old.targets
            self.config.routes[index] = new_route
            if new_route.enabled is True and old.net != new_route.net:
                stale += self._resolve(index)
        else:
            new_route.enabled = False
            self.config.routes.append(new_route)
        self.save()
        self.notify()
        self.reconcile(also_remove=stale)
        return None

    def add_country(self, code: str) -> None:
        code = code.strip().lower()
        if len(code) != 2 or not code.isalpha():
            self.error = "Enter a two-letter country code, e.g. IR."
            self._notify_main()
            return
        self.pending += 1
        self._notify_main()
        background(lambda: self._download_country(code))

    def _download_country(self, code: str) -> None:
        ranges = fetch_country_ranges(code)
        on_main(lambda: self._country_ready(code, ranges))

    def _country_ready(self, code: str, ranges: List[str]) -> None:
        self.pending = max(0, self.pending - 1)
        if not ranges:
            self.error = f"Couldn’t download IP ranges for {code.upper()}."
            self.notify()
            return
        stale: List[str] = []
        index = next((i for i, route in enumerate(self.config.routes) if route.country == code), None)
        if index is not None:
            old = set(self.config.routes[index].ranges or [])
            stale = sorted(old.difference(ranges))
            self.config.routes[index].ranges = ranges
        else:
            route = Route(
                net=f"{country_name(code)} IP ranges",
                country=code,
                ranges=ranges,
                enabled=False,
            )
            self.config.routes.append(route)
        self.save()
        self.notify()
        self.reconcile(also_remove=stale)

    def remove(self, route: Route) -> None:
        targets = route.targets
        self.config.routes = [item for item in self.config.routes if item.id != route.id]
        self.save()
        self.notify()
        self.reconcile(also_remove=targets)

    def set_gateway(self, value: str) -> bool:
        value = value.strip()
        if not value or value.lower() in {"auto", "automatic"}:
            self.config.gateway = ""
        else:
            if parse_ip(value) is None:
                self.error = "The gateway must be an IPv4 address."
                self._notify_main()
                return False
            self.config.gateway = ip_string(parse_ip(value) or 0)
        self.save()
        self.notify()
        self.reconcile()
        return True

    def command_for(self, route: Route) -> List[str]:
        gateway = self.gateway_for(route)
        device = self.lan_device or device_for_gateway(gateway)
        return [
            "sudo",
            "ip",
            "route",
            "replace",
            f"{route.net}",
            "via",
            gateway,
            "dev",
            device,
        ]

    # ------------------------------------------------------------- gateway watch

    def _gateway_tick(self) -> bool:
        if self._updating_gateway:
            return True
        self._updating_gateway = True
        background(self._check_gateway)
        return True

    def _check_gateway(self) -> None:
        lan = lan_route()
        on_main(lambda: self._gateway_changed(lan))

    def _gateway_changed(self, lan) -> None:
        self._updating_gateway = False
        if lan.gateway == self.lan_gateway and lan.device == self.lan_device:
            return
        self.lan_gateway = lan.gateway
        self.lan_device = lan.device
        self.lan_ip = lan.local_ip
        self.notify()
        self.reconcile()
