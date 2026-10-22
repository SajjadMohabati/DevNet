"""Application object: stores, tray icon, shortcut, panel and main window."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import app_info  # noqa: E402
from .dns import DNSStore  # noqa: E402
from .network import NetStore  # noqa: E402
from .processes import ProcStore  # noqa: E402
from .routes import RouteStore  # noqa: E402
from .shortcut import DEFAULT_ACCELERATOR, ShortcutManager, launch_command  # noqa: E402
from .speed import SpeedStore  # noqa: E402
from .storage import Settings  # noqa: E402
from .tray import TrayIcon  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402
from .ui.panel import PanelWindow  # noqa: E402

log = logging.getLogger(__name__)


class DevNetApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=app_info.APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.settings: Optional[Settings] = None
        self.routes: Optional[RouteStore] = None
        self.procs: Optional[ProcStore] = None
        self.dns: Optional[DNSStore] = None
        self.net: Optional[NetStore] = None
        self.speed: Optional[SpeedStore] = None
        self.tray: Optional[TrayIcon] = None
        self.tray_available = False
        self._window: Optional[MainWindow] = None
        self._panel: Optional[PanelWindow] = None
        self._tray_subscriptions = []
        self._net_source: Optional[int] = None
        self._started = False

    # ------------------------------------------------------------------ startup
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        GLib.set_prgname("devnet")
        GLib.set_application_name(app_info.APP_NAME)
        Gtk.Window.set_default_icon_name(app_info.APP_ID)
        self._load_css()
        self._load_icons()

        self.settings = Settings()
        self.routes = RouteStore()
        self.procs = ProcStore(self.settings)
        self.dns = DNSStore(self.settings)
        self.net = NetStore()
        self.speed = SpeedStore(self.settings)

        self._start_tray()
        self._register_shortcut()
        self._watch_stores()
        self.net.refresh()
        self._net_source = GLib.timeout_add_seconds(60, self._net_tick)
        # Keep running with no window: DevNet lives in the tray like the macOS app.
        self.hold()
        self._started = True

    def _load_css(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        path = Path(__file__).resolve().parent / "ui" / "style.css"
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(path))
        except GLib.Error:
            log.exception("could not load %s", path)
            return
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _load_icons(self) -> None:
        """Make the bundled icon work when running from a source checkout."""
        display = Gdk.Display.get_default()
        if display is None:
            return
        folder = Path(__file__).resolve().parent / "resources"
        if folder.is_dir():
            Gtk.IconTheme.get_for_display(display).add_search_path(str(folder))

    def _start_tray(self) -> None:
        tray = TrayIcon(
            on_activate=self.toggle_panel,
            on_open=lambda: self.show_window(None),
            on_quit=self.quit,
            on_routes=self._tray_routes,
            on_route=self._tray_route,
            on_dns=self._tray_dns,
            on_speed=self._tray_speed,
            menu_state=self._menu_state,
        )
        self.tray = tray
        self.tray_available = tray.start()
        if not self.tray_available:
            log.info("tray icon unavailable; the window and shortcut still work")

    def _register_shortcut(self) -> None:
        assert self.settings is not None
        accelerator = str(self.settings.get("shortcut", DEFAULT_ACCELERATOR) or "")
        if not accelerator:
            return
        error = ShortcutManager().register(accelerator, launch_command())
        if error:
            log.info("global shortcut unavailable: %s", error)

    def _watch_stores(self) -> None:
        assert self.routes and self.speed and self.net and self.dns and self.procs
        callbacks = [
            self.routes.subscribe(self._tray_refresh),
            self.speed.subscribe(self._tray_refresh),
            self.dns.subscribe(self._tray_refresh),
        ]
        self._tray_subscriptions = callbacks

    def _net_tick(self) -> bool:
        if self.net is not None:
            self.net.refresh()
        return True

    # -------------------------------------------------------------- tray state
    def _tray_refresh(self) -> None:
        if self.tray is None or not self.tray_available:
            return
        if self.routes is not None:
            self.tray.set_active(self.routes.active_count > 0)
        self.tray.refresh_menu()

    def _menu_state(self) -> dict:
        assert self.routes and self.dns
        routes = [
            (route.id, route.net, bool(route.enabled), self.routes.is_partial(route))
            for route in self.routes.config.routes
        ]
        presets = [(preset.name, preset.servers, self.dns.is_active(preset)) for preset in self.dns.presets]
        active = self.dns.active_preset
        return {
            "routes": routes,
            "all_on": self.routes.all_on,
            "dns": presets,
            "dns_active": active.name if active is not None else "",
        }

    def _tray_routes(self, enabled: bool) -> None:
        if self.routes is not None:
            self.routes.set_all(enabled)
            self._tray_refresh()

    def _tray_route(self, route_id: str, enabled: bool) -> None:
        if self.routes is None:
            return
        route = next((item for item in self.routes.config.routes if item.id == route_id), None)
        if route is not None:
            self.routes.set(route, enabled)
            self._tray_refresh()

    def _tray_dns(self, servers) -> None:
        if self.dns is not None:
            self.dns.apply(list(servers))
            self._tray_refresh()

    def _tray_speed(self) -> None:
        if self.speed is not None:
            self.speed.start()

    # ------------------------------------------------------------------- modes
    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = list(command_line.get_arguments())[1:]
        if "--panel" in args:
            mode = "panel"
        elif "--background" in args:
            mode = "background"
        else:
            mode = "window"
        self._handle_mode(mode)
        return 0

    def do_activate(self) -> None:
        self._handle_mode("window")

    def _handle_mode(self, mode: str) -> None:
        if mode == "panel":
            self.toggle_panel()
        elif mode == "window":
            self.show_window(None)
        # "background" deliberately leaves the application hidden in the tray.

    def show_window(self, pane: Optional[str]) -> None:
        window = self._ensure_window()
        if pane:
            window.set_pane(pane)
        window.present()
        self.refresh_speed_visibility()

    def toggle_panel(self) -> None:
        panel = self._ensure_panel()
        if panel.get_visible():
            panel.set_visible(False)
        else:
            panel.present()
            panel.grab_focus()
        self.refresh_speed_visibility()

    def refresh_speed_visibility(self) -> None:
        if self.speed is None:
            return
        window_visible = bool(
            self._window is not None
            and self._window.get_visible()
            and self._window.pane == "speed"
        )
        panel_visible = bool(self._panel is not None and self._panel.get_visible())
        self.speed.set_visible(window_visible or panel_visible)

    # ------------------------------------------------------------------- views
    def _ensure_window(self) -> MainWindow:
        if self._window is None:
            assert self.settings and self.routes and self.procs and self.dns and self.net and self.speed
            self._window = MainWindow(
                self, self.settings, self.routes, self.procs, self.dns, self.net, self.speed
            )
        return self._window

    def _ensure_panel(self) -> PanelWindow:
        if self._panel is None:
            assert self.settings and self.routes and self.procs and self.dns and self.net and self.speed
            self._panel = PanelWindow(
                self, self.settings, self.routes, self.procs, self.dns, self.net, self.speed
            )
        if self._window is not None and self._window.get_visible():
            self._panel.set_transient_for(self._window)
        return self._panel

    # ----------------------------------------------------------------- shutdown
    def do_shutdown(self) -> None:
        if self._net_source is not None:
            try:
                GLib.source_remove(self._net_source)
            except Exception:
                pass
            self._net_source = None
        for unsubscribe in self._tray_subscriptions:
            try:
                unsubscribe()
            except Exception:
                pass
        self._tray_subscriptions = []
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        if self.speed is not None:
            self.speed.close()
            self.speed = None
        if self.procs is not None:
            self.procs.close()
            self.procs = None
        if self.net is not None:
            self.net.close()
            self.net = None
        Adw.Application.do_shutdown(self)


__all__ = ["DevNetApplication"]
