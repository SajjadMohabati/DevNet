"""Process helpers with one rule: the GTK main thread never blocks on I/O."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import Callable, Optional, Sequence, Union

try:
    from gi.repository import GLib
except (ImportError, ModuleNotFoundError):
    GLib = None  # type: ignore

log = logging.getLogger(__name__)

Command = Sequence[str]


def which(program: str) -> Optional[str]:
    return shutil.which(program)


def run(
    args: Command,
    *,
    input_text: Optional[str] = None,
    timeout: float = 20,
    check: bool = False,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run a program without a shell and capture its output."""
    try:
        result = subprocess.run(
            list(args),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        result = subprocess.CompletedProcess(list(args), 127, "", "command not found")
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(list(args), 124, "", "timed out")
    except OSError as exc:  # pragma: no cover - defensive
        result = subprocess.CompletedProcess(list(args), 126, "", str(exc))
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")
    return result


def sh(*args: str, timeout: float = 20) -> str:
    """Output of a command, or an empty string when it fails."""
    return run(args, timeout=timeout).stdout


def on_main(function: Callable) -> None:
    """Run *function* on the GTK main loop, swallowing/logging exceptions."""
    if GLib is None:
        try:
            function()
        except Exception:
            log.exception("callback failed")
        return

    def callback():
        try:
            function()
        except Exception:  # pragma: no cover - UI safety net
            log.exception("idle callback failed")
        return getattr(GLib, "SOURCE_REMOVE", False)

    GLib.idle_add(callback)


def background(function: Callable) -> threading.Thread:
    def runner():
        try:
            function()
        except Exception:  # pragma: no cover - background safety net
            log.exception("background task failed")

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread


def popen_detached(args: Command, cwd: Optional[str] = None) -> bool:
    """Launch a desktop program without tying it to DevNet."""
    try:
        subprocess.Popen(
            list(args),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        return True
    except (OSError, ValueError):
        log.warning("could not launch %s", args, exc_info=True)
        return False


def clipboard_text(text: str) -> None:
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def open_uri(uri: str) -> None:
    from gi.repository import Gio

    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except Exception:  # pragma: no cover - fall back to the desktop handler
        popen_detached(["xdg-open", uri])


def open_folder(path: str) -> None:
    if GLib is not None and hasattr(GLib, "filename_to_uri"):
        open_uri(GLib.filename_to_uri(path, None))
    else:
        open_uri(f"file://{os.path.abspath(path)}")


def read_file(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def write_file(path: str, content: str, mode: int = 0o644) -> bool:
    """Write atomically; returns False instead of raising."""
    directory = os.path.dirname(path) or "."
    temporary = f"{path}.tmp.{os.getpid()}"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        return True
    except OSError:
        log.warning("could not write %s", path, exc_info=True)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False


def parse_key_values(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values
