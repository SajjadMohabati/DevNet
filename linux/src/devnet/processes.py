"""Find the current user's dev servers and containers, then stop them.

macOS uses ``lsof`` and ``launchctl``; on Linux the same information lives in
``/proc`` and ``ss``, with user services managed by systemd.  The store never
blocks the GTK main thread: every scan runs on a short-lived worker thread and
publishes its result through ``on_main``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .shell import background, on_main, popen_detached, run, which
from .storage import Settings

log = logging.getLogger(__name__)

# Names that mostly describe a daemon or an app helper rather than a project.
SYSTEM_PREFIXES = (
    "/usr/",
    "/opt/",
    "/snap/",
    "/var/",
    "/boot/",
    "/lib/",
    "/bin/",
    "/sbin/",
    "/nix/store/",
)

RUNTIME_TABLE: Sequence[Tuple[str, str, str]] = (
    ("node", "JS", "green"),
    ("bun", "Bun", "pink"),
    ("deno", "De", "teal"),
    ("python", "Py", "blue"),
    ("uvicorn", "Py", "blue"),
    ("gunicorn", "Py", "blue"),
    ("hypercorn", "Py", "blue"),
    ("java", "Jv", "orange"),
    ("ruby", "Rb", "red"),
    ("php", "Php", "indigo"),
    ("dotnet", ".N", "purple"),
    ("com.docker", "Dk", "blue"),
    ("docker", "Dk", "blue"),
    ("podman", "Pd", "purple"),
    ("postgres", "Pg", "blue"),
    ("redis", "Rd", "red"),
    ("mysql", "SQL", "cyan"),
    ("mongod", "Mg", "green"),
    ("nginx", "Nx", "green"),
    ("caddy", "Cd", "green"),
    ("go", "Go", "cyan"),
    ("rust", "Rs", "orange"),
    ("cargo", "Rs", "orange"),
    ("air", "Go", "cyan"),
    ("vite", "Vt", "purple"),
    ("next", "Nx", "gray"),
)

SS_PROCESS = re.compile(r'\(\("([^"]+)",pid=(\d+),fd=\d+\)')


@dataclass
class DevProcess:
    pid: int
    name: str
    ports: List[int] = field(default_factory=list)
    cwd: str = ""
    command: str = ""
    unit: Optional[str] = None

    @property
    def id(self) -> int:
        return self.pid

    @property
    def has_project(self) -> bool:
        if not self.cwd or self.cwd == "/":
            return False
        if "/.app/Contents" in self.cwd or self.cwd.startswith(SYSTEM_PREFIXES):
            return False
        return Path(self.cwd).is_dir()

    @property
    def project(self) -> str:
        if "/.gradle/daemon/" in self.cwd:
            return f"Gradle Daemon {Path(self.cwd).name}"
        if self.has_project:
            return Path(self.cwd).name or self.cwd
        return self.name

    @property
    def runtime(self) -> Tuple[str, str]:
        return runtime_glyph(self.name)

    @property
    def subtitle(self) -> str:
        if self.unit:
            return f"systemd user unit {self.unit}"
        return self.command or self.name


@dataclass
class Container:
    id: str
    name: str
    image: str
    status: str
    ports: str = ""
    runtime: str = "docker"

    @property
    def published_ports(self) -> List[int]:
        """``0.0.0.0:5432->5432/tcp`` -> ``[5432]``."""
        result = set()
        for mapping in self.ports.split(","):
            if "->" not in mapping:
                continue
            host = mapping.split("->", 1)[0].strip()
            if not host:
                continue
            value = host.rsplit(":", 1)[-1].strip("[]")
            if value.isdigit():
                result.add(int(value))
        return sorted(result)


def runtime_glyph(name: str) -> Tuple[str, str]:
    lower = name.lower()
    for prefix, glyph, color in RUNTIME_TABLE:
        if lower.startswith(prefix) or prefix in lower:
            return glyph, color
    return (name[:2].capitalize() or "??", "gray")


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _command(pid: int) -> str:
    raw = _read(f"/proc/{pid}/cmdline")
    if raw:
        parts = [part for part in raw.split("\0") if part]
        if parts:
            return " ".join(parts)
    return _read(f"/proc/{pid}/comm").strip()


def _same_user(pid: int) -> bool:
    try:
        return os.stat(f"/proc/{pid}").st_uid == os.getuid()
    except OSError:
        return False


def _listener_ports() -> Dict[int, Tuple[str, List[int]]]:
    """pid -> (command name, listening TCP ports), from one ``ss`` call."""
    output = run(["ss", "-H", "-ltnp"], timeout=8).stdout
    found: Dict[int, Tuple[str, List[int]]] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        match = SS_PROCESS.search(line)
        if not match:
            continue
        name, pid_text = match.group(1), match.group(2)
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        local = fields[3]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        if not port_text.isdigit():
            continue
        port = int(port_text)
        if not _same_user(pid):
            continue
        previous = found.get(pid)
        if previous is None:
            found[pid] = (name, [port])
        elif port not in previous[1]:
            previous[1].append(port)
    for name, ports in found.values():
        ports.sort()
    return found


def _user_units() -> Dict[int, str]:
    """MainPID -> systemd user unit for running services."""
    if not which("systemctl"):
        return {}
    result = run(
        ["systemctl", "--user", "list-units", "--type=service", "--state=running",
         "--no-legend", "--plain", "--no-pager"],
        timeout=8,
    )
    if result.returncode != 0:
        return {}
    units = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        unit = fields[0].lstrip("●").strip()
        if unit.endswith(".service"):
            units.append(unit)
    mapping: Dict[int, str] = {}
    for unit in units[:80]:
        shown = run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"], timeout=3).stdout.strip()
        if shown.isdigit() and int(shown) > 0:
            mapping[int(shown)] = unit
    return mapping


def scan(show_all: bool) -> List[DevProcess]:
    listeners = _listener_ports()
    if not listeners:
        return []
    units = _user_units()
    own_pid = os.getpid()
    items: List[DevProcess] = []
    for pid, (name, ports) in listeners.items():
        if pid == own_pid:
            continue
        process = DevProcess(
            pid=pid,
            name=name,
            ports=sorted(ports),
            cwd=_cwd(pid),
            command=_command(pid),
            unit=units.get(pid),
        )
        if show_all or process.has_project or process.unit:
            items.append(process)
    items.sort(key=lambda item: (item.ports[0] if item.ports else 1 << 20, item.pid))
    return items


def _docker_command() -> Optional[str]:
    explicit = os.environ.get("DEVNET_DOCKER")
    if explicit and os.access(explicit, os.X_OK):
        return explicit
    for candidate in ("docker", "podman"):
        path = which(candidate)
        if path:
            return path
    return None


def _docker_socket_present() -> bool:
    host = os.environ.get("DOCKER_HOST", "")
    if host.startswith("unix://"):
        return Path(host[7:]).exists()
    socket = Path("/var/run/docker.sock")
    if socket.exists():
        return True
    rootless = Path.home() / ".docker" / "run" / "docker.sock"
    if rootless.exists():
        return True
    return bool(host)


def scan_containers() -> Tuple[bool, List[Container]]:
    docker = _docker_command()
    if not docker or not _docker_socket_present():
        return False, []
    result = run(
        [docker, "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
        timeout=8,
    )
    if result.returncode != 0:
        return False, []
    runtime = "podman" if Path(docker).name == "podman" else "docker"
    containers: List[Container] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        containers.append(
            Container(
                id=fields[0],
                name=fields[1],
                image=fields[2],
                status=fields[3],
                ports=fields[4] if len(fields) > 4 else "",
                runtime=runtime,
            )
        )
    return True, containers


# --------------------------------------------------------------------------- editors

@dataclass(frozen=True)
class Editor:
    name: str
    command: str
    terminal: bool = False


_EDITOR_CANDIDATES: Sequence[Editor] = (
    Editor("VS Code", "code"),
    Editor("Cursor", "cursor"),
    Editor("IntelliJ IDEA", "idea"),
    Editor("Zed", "zed"),
    Editor("GNOME Terminal", "gnome-terminal", True),
    Editor("Console", "kgx", True),
    Editor("Konsole", "konsole", True),
    Editor("xterm", "xterm", True),
)


def editors() -> List[Editor]:
    return [editor for editor in _EDITOR_CANDIDATES if which(editor.command)]


def open_in(editor: Editor, folder: str) -> bool:
    if not Path(folder).is_dir():
        return False
    if editor.terminal:
        if editor.command == "gnome-terminal":
            return popen_detached([editor.command, f"--working-directory={folder}"])
        if editor.command == "konsole":
            return popen_detached([editor.command, "--workdir", folder])
        return popen_detached([editor.command], cwd=folder)
    return popen_detached([editor.command, folder])


# ----------------------------------------------------------------------------- store

class ProcStore:
    """Observable list of running dev servers and containers."""

    __slots__ = ("settings", "items", "containers", "docker_up", "stopping", "show_all",
                 "_listeners", "_refreshing", "_closed")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.items: List[DevProcess] = []
        self.containers: List[Container] = []
        self.docker_up = False
        self.stopping: set[str] = set()
        self.show_all = bool(settings.get("show_all_processes", False))
        self._listeners: List[Callable[[], None]] = []
        self._refreshing = False
        self._closed = False

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
                log.exception("project listener failed")

    def close(self) -> None:
        self._closed = True
        self._listeners.clear()

    # -- queries ----------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self.items) + len(self.containers)

    def is_stopping(self, item: object) -> bool:
        key = item.id if isinstance(item, (DevProcess, Container)) else str(item)
        return str(key) in self.stopping

    def set_show_all(self, value: bool) -> None:
        if self.show_all == value:
            return
        self.show_all = value
        self.settings.set("show_all_processes", value)
        self.refresh()

    # -- scanning ---------------------------------------------------------
    def refresh(self) -> None:
        if self._refreshing or self._closed:
            return
        self._refreshing = True
        show_all = self.show_all
        background(lambda: self._refresh_worker(show_all))

    def _refresh_worker(self, show_all: bool) -> None:
        try:
            items = scan(show_all)
            docker_up, containers = scan_containers()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("project scan failed: %s", exc)
            items, docker_up, containers = [], False, []

        def publish() -> None:
            self._refreshing = False
            if self._closed:
                return
            self.items = items
            self.docker_up = docker_up
            self.containers = containers
            alive = {str(item.pid) for item in items} | {container.id for container in containers}
            self.stopping.intersection_update(alive)
            self.notify()

        on_main(publish)

    # -- stopping ---------------------------------------------------------
    def stop(self, process: DevProcess) -> None:
        """Stop a process. A second call while stopping force-kills it."""
        key = str(process.pid)
        forced = key in self.stopping
        self.stopping.add(key)
        self.notify()

        def work() -> None:
            try:
                if process.unit:
                    run(["systemctl", "--user", "stop", process.unit], timeout=30)
                elif forced:
                    os.kill(process.pid, signal.SIGKILL)
                else:
                    os.kill(process.pid, signal.SIGTERM)
                    deadline = time.monotonic() + 1.4
                    while time.monotonic() < deadline:
                        try:
                            os.kill(process.pid, 0)
                        except OSError:
                            break
                        time.sleep(0.12)
                    else:
                        try:
                            os.kill(process.pid, signal.SIGKILL)
                        except OSError:
                            pass
            except OSError as exc:
                log.info("could not stop %s: %s", process.pid, exc)
            on_main(self.refresh)

        background(work)

    def stop_container(self, container: Container) -> None:
        if container.id in self.stopping:
            return
        docker = _docker_command()
        if not docker:
            return
        self.stopping.add(container.id)
        self.notify()

        def work() -> None:
            run([docker, "stop", container.id], timeout=60)
            on_main(self.refresh)

        background(work)

    def stop_all(self) -> None:
        for process in list(self.items):
            self.stop(process)


__all__ = [
    "Container",
    "DevProcess",
    "Editor",
    "ProcStore",
    "editors",
    "open_in",
    "runtime_glyph",
    "scan",
    "scan_containers",
]
