"""Cloudflare speed test and always-lightweight live monitors.

Cloudflare's public endpoints are the same ones the macOS app uses:

* ``GET  /__down?bytes=N`` – download N bytes (``0`` gives a cheap latency probe)
* ``POST /__up``           – upload a chunked body
* ``GET  /meta``           – client IP, ISP and the serving datacenter

The full test runs on a worker thread and reports progress through the GTK main
loop.  Live throughput is read straight from ``/sys/class/net`` so the monitor
does not spawn a process every two seconds.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import http.client
import json
import logging
import math
import socket
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from gi.repository import GLib

from .ipv4 import normalize_domain, parse_ip
from .network import is_physical_interface, is_tunnel_name, ping_host, route_get
from .shell import background, on_main
from .storage import Settings, data_dir, load_json, save_json

log = logging.getLogger(__name__)

BASE_HOST = "speed.cloudflare.com"
CHUNK_BYTES = 25_000_000
PHASE_SECONDS = 8.0
RAMP_SECONDS = 0.4
MONITOR_SECONDS = 2
MAX_HISTORY = 30
USER_AGENT = "DevNet/1.2 (Linux)"


# --------------------------------------------------------------------------- model

@dataclass
class SpeedResult:
    date: str
    down: float
    up: float
    ping: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date, "down": self.down, "up": self.up, "ping": self.ping}

    @classmethod
    def from_dict(cls, value: dict) -> "SpeedResult":
        try:
            down = float(value.get("down", 0) or 0)
        except (TypeError, ValueError):
            down = 0.0
        try:
            up = float(value.get("up", 0) or 0)
        except (TypeError, ValueError):
            up = 0.0
        try:
            ping = int(value.get("ping", 0) or 0)
        except (TypeError, ValueError):
            ping = 0
        return cls(
            date=str(value.get("date", "")),
            down=down,
            up=up,
            ping=ping,
            id=str(value.get("id") or uuid.uuid4().hex),
        )

    @property
    def when(self) -> dt.datetime:
        try:
            return dt.datetime.fromisoformat(self.date)
        except ValueError:
            return dt.datetime.fromtimestamp(0).astimezone()


@dataclass
class SpeedSample:
    t: float
    phase: str
    value: float


@dataclass
class PingTarget:
    name: str
    host: str
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "host": self.host, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, value: dict) -> "PingTarget":
        return cls(
            name=str(value.get("name") or value.get("host") or "Target"),
            host=str(value.get("host", "")),
            enabled=bool(value.get("enabled", True)),
            id=str(value.get("id") or uuid.uuid4().hex),
        )


@dataclass
class TargetStat:
    ping: Optional[int] = None
    iface: str = ""


@dataclass
class SpeedMeta:
    client_ip: str = ""
    organization: str = ""
    colo: str = ""
    city: str = ""
    country: str = ""
    protocol: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> "SpeedMeta":
        colo = value.get("colo") or {}
        return cls(
            client_ip=str(value.get("clientIp") or ""),
            organization=str(value.get("asOrganization") or ""),
            colo=str(colo.get("iata") or "") if isinstance(colo, dict) else "",
            city=str(value.get("city") or (colo.get("city") if isinstance(colo, dict) else "") or ""),
            country=str(value.get("country") or ""),
            protocol=str(value.get("httpProtocol") or ""),
        )


DEFAULT_TARGETS: List[PingTarget] = [
    PingTarget("Cloudflare", "1.1.1.1"),
    PingTarget("Google", "8.8.8.8"),
    PingTarget("Shecan", "178.22.122.100"),
]


# ----------------------------------------------------------------- formatting

def format_speed(bytes_per_sec: float, use_bytes: bool = False) -> str:
    """Bytes/s -> ``27.2 Mbps`` (or ``3.4 MB/s``)."""
    if use_bytes:
        return format_rate(bytes_per_sec)
    mbps = bytes_per_sec * 8 / 1_000_000
    if mbps >= 100:
        return f"{mbps:.0f} Mbps"
    if mbps >= 10:
        return f"{mbps:.1f} Mbps"
    if mbps >= 1:
        return f"{mbps:.2f} Mbps"
    return f"{mbps * 1000:.0f} kbps"


def format_rate(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1_000_000:
        return f"{bytes_per_sec / 1_000_000:.1f} MB/s"
    if bytes_per_sec >= 1_000:
        return f"{bytes_per_sec / 1_000:.0f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


def average(events: List[Tuple[float, float]], ramp: float = RAMP_SECONDS) -> float:
    """Average bytes/s, skipping the TCP/TLS ramp-up at the beginning."""
    if not events:
        return 0.0
    last_t, last_bytes = events[-1]
    if last_t <= 0.1 or last_bytes <= 0:
        return 0.0
    skip = ramp if last_t > ramp * 3 else 0.0
    base = 0.0
    if skip > 0:
        for when, count in events:
            if when <= skip:
                base = count
            else:
                break
    return (last_bytes - base) / max(last_t - skip, 0.1)


# ------------------------------------------------------------------ transfer helpers

def _tls_connection(timeout: float = 6.0) -> ssl.SSLSocket:
    context = ssl.create_default_context()
    raw = socket.create_connection((BASE_HOST, 443), timeout=timeout)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return context.wrap_socket(raw, server_hostname=BASE_HOST)


def _http_connection(timeout: float = 6.0) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(
        BASE_HOST,
        443,
        timeout=timeout,
        context=ssl.create_default_context(),
    )


class _Cancelled(Exception):
    pass


class SpeedTester:
    """One on-demand run; separate from the store so it is easy to test."""

    def __init__(self, cancel: threading.Event, publish: Callable[[float, float, str], None]) -> None:
        self.cancel = cancel
        self.publish = publish
        self.started = time.monotonic()

    def check(self) -> None:
        if self.cancel.is_set():
            raise _Cancelled

    def sleep(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            raise _Cancelled

    # -- phases -----------------------------------------------------------
    def ping(self) -> int:
        connection = _http_connection(timeout=4)
        samples: List[float] = []
        try:
            for index in range(4):
                self.check()
                start = time.monotonic()
                try:
                    connection.request("GET", "/__down?bytes=0", headers={"User-Agent": USER_AGENT})
                    response = connection.getresponse()
                    response.read()
                    if response.status >= 400:
                        raise OSError(f"HTTP {response.status}")
                except (OSError, http.client.HTTPException):
                    # Re-open once; some middleboxes drop keep-alive connections.
                    connection.close()
                    connection = _http_connection(timeout=4)
                    start = time.monotonic()
                    connection.request("GET", "/__down?bytes=0", headers={"User-Agent": USER_AGENT})
                    response = connection.getresponse()
                    response.read()
                samples.append((time.monotonic() - start) * 1000)
                self.publish(0.0, 0.15 * (index + 1) / 4, "ping")
                self.sleep(0.12)
        finally:
            connection.close()
        usable = samples[1:] or samples
        return int(round(min(usable))) if usable else 0

    def download(self) -> float:
        events: List[Tuple[float, float]] = []
        total = 0
        smoothed = 0.0
        last_time = 0.0
        last_bytes = 0.0
        start = time.monotonic()
        connection = _http_connection(timeout=8)
        try:
            while True:
                self.check()
                connection.request(
                    "GET",
                    f"/__down?bytes={CHUNK_BYTES}",
                    headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
                )
                response = connection.getresponse()
                if response.status >= 400:
                    raise OSError(f"HTTP {response.status}")
                while True:
                    self.check()
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    now = time.monotonic() - start
                    events.append((now, float(total)))
                    if now - last_time >= 0.1:
                        instant = (total - last_bytes) / max(now - last_time, 0.001)
                        smoothed = instant if smoothed == 0 else smoothed * 0.55 + instant * 0.45
                        last_time, last_bytes = now, float(total)
                        self.publish(smoothed, 0.15 + 0.425 * min(now / PHASE_SECONDS, 1), "download")
                    if now >= PHASE_SECONDS:
                        break
                response.close()
                if time.monotonic() - start >= PHASE_SECONDS:
                    break
        finally:
            connection.close()
        value = average(events)
        if value <= 0 and events:
            value = events[-1][1] / max(events[-1][0], 0.1)
        return value

    def upload(self) -> float:
        events: List[Tuple[float, float]] = []
        total = 0
        smoothed = 0.0
        last_time = 0.0
        last_bytes = 0.0
        start = time.monotonic()
        sock = _tls_connection(timeout=8)
        header = (
            "POST /__up HTTP/1.1\r\n"
            f"Host: {BASE_HOST}\r\n"
            "User-Agent: " + USER_AGENT + "\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Transfer-Encoding: chunked\r\n"
            "Connection: close\r\n\r\n"
        )
        payload = b"\0" * 262_144
        frame = b"%x\r\n" % len(payload) + payload + b"\r\n"
        try:
            sock.sendall(header.encode("ascii"))
            while True:
                self.check()
                sock.sendall(frame)
                total += len(payload)
                now = time.monotonic() - start
                events.append((now, float(total)))
                if now - last_time >= 0.1:
                    instant = (total - last_bytes) / max(now - last_time, 0.001)
                    smoothed = instant if smoothed == 0 else smoothed * 0.55 + instant * 0.45
                    last_time, last_bytes = now, float(total)
                    self.publish(smoothed, 0.575 + 0.425 * min(now / PHASE_SECONDS, 1), "upload")
                if total >= CHUNK_BYTES or now >= PHASE_SECONDS:
                    break
            # Finish the chunked body so the server can answer.
            try:
                sock.sendall(b"0\r\n\r\n")
            except OSError:
                pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
        value = average(events)
        if value <= 0 and events:
            value = events[-1][1] / max(events[-1][0], 0.1)
        return value


# --------------------------------------------------------------------------- store

class SpeedStore:
    """Observable speed-test state, history, targets and live monitors."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.history_path = data_dir() / "speed.json"
        self.targets_path = data_dir() / "targets.json"

        self.phase = "idle"
        self.live = 0.0
        self.progress = 0.0
        self.samples: List[SpeedSample] = []
        self.result: Optional[SpeedResult] = None
        self.history: List[SpeedResult] = []
        self.meta: Optional[SpeedMeta] = None
        self.error: Optional[str] = None

        self.activity_down = 0.0
        self.activity_up = 0.0
        self.live_ping: Optional[int] = None
        self.live_iface = ""
        self.live_host_name = "Cloudflare"
        self.targets: List[PingTarget] = []
        self.target_stats: Dict[str, TargetStat] = {}
        self.menu_host_id = str(settings.get("speed_menu_host", "") or "")
        self.use_bytes = bool(settings.get("speed_use_bytes", False))

        self._listeners: List[Callable[[], None]] = []
        self._cancel: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._visible = False
        self._prev_counters: Optional[Tuple[float, Dict[str, Tuple[int, int]]]] = None
        self._target_index = 0
        self._pinging: set[str] = set()
        self._live_ping_busy = False
        self._monitor_source: Optional[int] = None
        self._closed = False

        self._load()
        self._monitor_source = GLib.timeout_add_seconds(MONITOR_SECONDS, self._monitor_tick)

    # -- notification -----------------------------------------------------
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
                log.exception("speed listener failed")

    def close(self) -> None:
        self._closed = True
        self.stop()
        if self._monitor_source is not None:
            try:
                GLib.source_remove(self._monitor_source)
            except Exception:
                pass
            self._monitor_source = None
        self._listeners.clear()

    # -- properties -------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.phase != "idle"

    @property
    def menu_host(self) -> PingTarget:
        for target in self.targets:
            if target.id == self.menu_host_id:
                return target
        return PingTarget("Cloudflare", "1.1.1.1")

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        if visible:
            self.poke()
        else:
            self._prev_counters = None

    def poke(self) -> None:
        self._monitor_tick(force=True)

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        raw_history = load_json(self.history_path, [])
        if isinstance(raw_history, list):
            self.history = [SpeedResult.from_dict(item) for item in raw_history if isinstance(item, dict)]
            self.history = self.history[:MAX_HISTORY]
        raw_targets = load_json(self.targets_path, None)
        if isinstance(raw_targets, list) and raw_targets:
            self.targets = [PingTarget.from_dict(item) for item in raw_targets if isinstance(item, dict)]
        else:
            self.targets = [PingTarget(item.name, item.host, item.enabled, item.id) for item in DEFAULT_TARGETS]
            self._save_targets()

    def _save_history(self) -> None:
        save_json(self.history_path, [item.to_dict() for item in self.history])

    def _save_targets(self) -> None:
        save_json(self.targets_path, [item.to_dict() for item in self.targets])

    def clear_history(self) -> None:
        self.history = []
        self._save_history()
        self.notify()

    # -- targets ----------------------------------------------------------
    def upsert_target(self, index: Optional[int], name: str, host: str) -> Optional[str]:
        host = host.strip()
        if parse_ip(host) is None and normalize_domain(host) is None:
            return "Enter an IP address (1.1.1.1) or a domain (example.com)."
        label = name.strip() or host
        if index is not None and 0 <= index < len(self.targets):
            self.targets[index].name = label
            self.targets[index].host = host
        else:
            self.targets.append(PingTarget(label, host))
        self._save_targets()
        self.notify()
        return None

    def remove_target(self, target: PingTarget) -> None:
        self.targets = [item for item in self.targets if item.id != target.id]
        self.target_stats.pop(target.id, None)
        if self.menu_host_id == target.id:
            self.menu_host_id = ""
            self.settings.set("speed_menu_host", "")
        self._save_targets()
        self.notify()

    def set_target(self, target: PingTarget, enabled: bool) -> None:
        for item in self.targets:
            if item.id == target.id:
                item.enabled = enabled
                break
        self._save_targets()
        self.notify()

    def set_menu_host(self, target: PingTarget) -> None:
        self.menu_host_id = target.id
        self.settings.set("speed_menu_host", target.id)
        self.live_ping = self.target_stats.get(target.id, TargetStat()).ping
        self.live_host_name = target.name
        self.notify()

    def set_use_bytes(self, value: bool) -> None:
        if self.use_bytes == value:
            return
        self.use_bytes = value
        self.settings.set("speed_use_bytes", value)
        self.notify()

    # -- live monitors ----------------------------------------------------
    def _monitor_tick(self, force: bool = False) -> bool:
        if self._closed:
            return False
        if not (force or self._visible):
            self._prev_counters = None
            return True
        self._sample_activity()
        if not self.running and (force or int(time.monotonic()) % 3 == 0):
            self._sample_live_ping()
        if not self.running:
            self._rotate_target()
        return True

    @staticmethod
    def _counters() -> Dict[str, Tuple[int, int]]:
        counters: Dict[str, Tuple[int, int]] = {}
        root = Path("/sys/class/net")
        try:
            names = [entry.name for entry in root.iterdir()]
        except OSError:
            return counters
        for name in names:
            if name == "lo" or (not is_physical_interface(name) and not is_tunnel_name(name)):
                continue
            try:
                down = int((root / name / "statistics" / "rx_bytes").read_text().strip())
                up = int((root / name / "statistics" / "tx_bytes").read_text().strip())
            except (OSError, ValueError):
                continue
            counters[name] = (down, up)
        return counters

    def _sample_activity(self) -> None:
        now = time.monotonic()
        counters = self._counters()
        previous = self._prev_counters
        self._prev_counters = (now, counters)
        if previous is None:
            return
        elapsed = now - previous[0]
        if elapsed <= 0.5:
            return
        down = up = 0
        for name, (rx, tx) in counters.items():
            old = previous[1].get(name)
            if old is None:
                continue
            down += max(0, rx - old[0])
            up += max(0, tx - old[1])
        down_rate = down / elapsed
        up_rate = up / elapsed
        self.activity_down = down_rate if self.activity_down == 0 else self.activity_down * 0.5 + down_rate * 0.5
        self.activity_up = up_rate if self.activity_up == 0 else self.activity_up * 0.5 + up_rate * 0.5
        self.notify()

    def _sample_live_ping(self) -> None:
        if self._live_ping_busy:
            return
        self._live_ping_busy = True
        target = self.menu_host
        self.live_host_name = target.name

        def work() -> None:
            value = ping_host(target.host)
            info = route_get(target.host)
            on_main(lambda: self._finish_live_ping(value, info.get("dev", "")))

        background(work)

    def _finish_live_ping(self, value: Optional[int], iface: str) -> None:
        self._live_ping_busy = False
        self.live_ping = value
        self.live_iface = iface
        self.notify()

    def _rotate_target(self) -> None:
        enabled = [target for target in self.targets if target.enabled]
        if not enabled:
            return
        target = enabled[self._target_index % len(enabled)]
        self._target_index += 1
        if target.id in self._pinging:
            return
        self._pinging.add(target.id)

        def work() -> None:
            value = ping_host(target.host)
            info = route_get(target.host)
            on_main(lambda: self._finish_target_ping(target.id, value, info.get("dev", "")))

        background(work)

    def _finish_target_ping(self, target_id: str, value: Optional[int], iface: str) -> None:
        self._pinging.discard(target_id)
        if any(item.id == target_id for item in self.targets):
            self.target_stats[target_id] = TargetStat(value, iface)
            if self.menu_host_id == target_id:
                self.live_ping = value
                self.live_iface = iface
            self.notify()

    # -- full test --------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self.error = None
        self.samples = []
        self.live = 0.0
        self.progress = 0.0
        self.phase = "ping"
        self.notify()
        self.fetch_meta()
        cancel = threading.Event()
        self._cancel = cancel
        thread = threading.Thread(target=self._run, args=(cancel,), name="devnet-speed", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def _publish(self, value: float, progress: float, phase: str) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return

        def update() -> None:
            if self._cancel is not None and self._cancel.is_set():
                return
            self.live = value
            self.progress = min(0.999, progress)
            self.samples.append(SpeedSample(time.monotonic(), phase, value))
            if len(self.samples) > 1200:
                del self.samples[:200]
            self.notify()

        on_main(update)

    def _run(self, cancel: threading.Event) -> None:
        tester = SpeedTester(cancel, self._publish)
        result: Optional[SpeedResult] = None
        error: Optional[str] = None
        try:
            ping = tester.ping()
            on_main(lambda: self._set_phase("download"))
            down = tester.download()
            if down <= 0:
                raise OSError("empty download")
            on_main(lambda: self._set_phase("upload"))
            up = tester.upload()
            result = SpeedResult(
                date=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                down=down,
                up=up,
                ping=ping,
            )
        except _Cancelled:
            pass
        except Exception as exc:
            log.info("speed test failed: %s", exc)
            error = "Couldn’t reach speed.cloudflare.com — check your connection."
        on_main(lambda: self._finish(result, error))

    def _set_phase(self, phase: str) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        self.phase = phase
        self.notify()

    def _finish(self, result: Optional[SpeedResult], error: Optional[str]) -> None:
        cancelled = self._cancel is not None and self._cancel.is_set()
        self.phase = "idle"
        self.live = 0.0
        self.progress = 0.0
        self._cancel = None
        self._thread = None
        if error and not cancelled:
            self.error = error
        if result is not None:
            self.result = result
            self.history.insert(0, result)
            self.history = self.history[:MAX_HISTORY]
            self._save_history()
        self.notify()

    def fetch_meta(self) -> None:
        def work() -> None:
            try:
                connection = _http_connection(timeout=5)
                try:
                    connection.request("GET", "/meta", headers={"User-Agent": USER_AGENT})
                    response = connection.getresponse()
                    payload = response.read(65536)
                finally:
                    connection.close()
                value = json.loads(payload.decode("utf-8", "replace"))
                if not isinstance(value, dict) or not value.get("clientIp"):
                    return
                meta = SpeedMeta.from_dict(value)
            except Exception:
                return
            on_main(lambda: self._set_meta(meta))

        background(work)

    def _set_meta(self, meta: SpeedMeta) -> None:
        self.meta = meta
        self.notify()


__all__ = [
    "DEFAULT_TARGETS",
    "PingTarget",
    "SpeedMeta",
    "SpeedResult",
    "SpeedSample",
    "SpeedStore",
    "TargetStat",
    "average",
    "format_rate",
    "format_speed",
]
