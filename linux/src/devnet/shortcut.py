"""Global shortcut via GNOME's custom media-key bindings.

A portable Linux equivalent of macOS' Carbon hotkey is not available: X11 grabs
are global but Wayland forbids them, and the XDG GlobalShortcuts portal is not
implemented by every desktop.  GNOME's own settings daemon is the reliable path
on the target desktops, so DevNet registers one custom keybinding there and falls
back cleanly (the shortcut field explains why) everywhere else.
"""

from __future__ import annotations

import ast
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import List, Optional

from .shell import run

log = logging.getLogger(__name__)

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/devnet/"
MEDIA_KEYS_SCHEMA = SCHEMA + ".custom-keybinding"
DEFAULT_ACCELERATOR = "<Control><Shift>i"


def available() -> bool:
    if not shutil.which("gsettings"):
        return False
    result = run(["gsettings", "list-schemas"], timeout=5)
    return SCHEMA in result.stdout.splitlines()


def _read_list() -> List[str]:
    result = run(["gsettings", "get", SCHEMA, "custom-keybindings"], timeout=5)
    text = (result.stdout or "").strip()
    if not text:
        return []
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _write_list(values: List[str]) -> None:
    rendered = "[" + ", ".join(repr(value) for value in values) + "]"
    run(["gsettings", "set", SCHEMA, "custom-keybindings", rendered], timeout=5)


def _set_path(key: str, value: str) -> None:
    run(["gsettings", "set", MEDIA_KEYS_SCHEMA + ":" + CUSTOM_PATH, key, value], timeout=5)


class ShortcutManager:
    """Owns the DevNet entry in GNOME's custom keybinding list."""

    def __init__(self) -> None:
        self.registered = False

    def register(self, accelerator: str, command: str) -> Optional[str]:
        self.unregister(keep_setting=True)
        if not available():
            return (
                "Global shortcuts need GNOME (gsettings). The menu-bar icon and "
                "“devnet --panel” still work."
            )
        # GNOME requires the entry to exist in the list before setting its path.
        current = _read_list()
        if CUSTOM_PATH not in current:
            current.append(CUSTOM_PATH)
            _write_list(current)
        _set_path("name", "DevNet")
        _set_path("command", command)
        _set_path("binding", accelerator)
        self.registered = True
        return None

    def unregister(self, keep_setting: bool = False) -> None:
        if not available():
            self.registered = False
            return
        current = _read_list()
        if CUSTOM_PATH in current:
            _write_list([value for value in current if value != CUSTOM_PATH])
        if not keep_setting:
            run(["gsettings", "reset-recursively", MEDIA_KEYS_SCHEMA + ":" + CUSTOM_PATH], timeout=5)
        self.registered = False


def launch_command() -> str:
    """Command that reopens DevNet's panel from a keybinding."""
    executable = shutil.which("devnet")
    if executable:
        return shlex.quote(executable) + " --panel"
    # Running from a source checkout: keep the module importable.
    root = Path(__file__).resolve().parents[2]
    return (
        f"env PYTHONPATH={shlex.quote(str(root / 'src'))} "
        f"{shlex.quote(shutil.which('python3') or 'python3')} -m devnet --panel"
    )


__all__ = [
    "DEFAULT_ACCELERATOR",
    "ShortcutManager",
    "available",
    "launch_command",
]
