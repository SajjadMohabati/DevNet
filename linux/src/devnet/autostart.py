"""XDG autostart, shared by GNOME, KDE and most Linux desktops."""

from __future__ import annotations

from pathlib import Path

from gi.repository import GLib


def autostart_path() -> Path:
    return Path(GLib.get_user_config_dir()) / "autostart" / "org.devnet.App.desktop"


def enabled() -> bool:
    return autostart_path().is_file()


def set_enabled(value: bool, command: str = "devnet --background") -> bool:
    path = autostart_path()
    if not value:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
    content = f"""[Desktop Entry]
Type=Application
Name=DevNet
Comment=Split tunneling, DNS switching and dev-server manager
Exec={command}
Icon=org.devnet.App
Terminal=false
Categories=Network;
X-GNOME-Autostart-enabled=true
Hidden=false
"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return True
    except OSError:
        return False


__all__ = ["autostart_path", "enabled", "set_enabled"]
