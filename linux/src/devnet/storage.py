"""XDG paths and tiny JSON persistence helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from gi.repository import GLib

APP_DIR = "devnet"


def data_dir() -> Path:
    path = Path(GLib.get_user_data_dir()) / APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    path = Path(GLib.get_user_config_dir()) / APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    path = Path(base) / APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save_json(path: Path, value: Any) -> bool:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        return False


class Settings:
    """User-visible preferences that do not belong to a single store."""

    def __init__(self) -> None:
        self.path = config_dir() / "settings.json"
        self.data = load_json(self.path, {})
        if not isinstance(self.data, dict):
            self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self.data.get(key) == value:
            return
        self.data[key] = value
        save_json(self.path, self.data)

    def pop(self, key: str, default: Any = None) -> Any:
        value = self.data.pop(key, default)
        save_json(self.path, self.data)
        return value
