"""The compact Control-Center-style panel, opened from the tray or the shortcut."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from gi.repository import Gdk, GLib, Gtk

from .. import app_info
from ..dns import DNSStore
from ..network import NetStore
from ..processes import Container, DevProcess, ProcStore
from ..routes import Route, RouteStore
from ..speed import SpeedStore, format_speed
from ..storage import Settings
from .widgets import AppIcon, IPLine, Tile, label

log = logging.getLogger(__name__)


def _clear(box: Gtk.Box) -> None:
    while (child := box.get_first_child()) is not None:
        box.remove(child)


class PanelWindow(Gtk.Window):
    """A small transient window that behaves like a popover."""

    def __init__(
        self,
        app,
        settings: Settings,
        routes: RouteStore,
        procs: ProcStore,
        dns: DNSStore,
        net: NetStore,
        speed: SpeedStore,
    ) -> None:
        super().__init__(title=app_info.APP_NAME)
        self.app = app
        self.settings = settings
        self.routes = routes
        self.procs = procs
        self.dns = dns
        self.net = net
        self.speed = speed

        self.set_default_size(362, -1)
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_hide_on_close(True)
        self.set_modal(False)
        self.add_css_class("devn-panel-window")

        self._render_source: Optional[int] = None
        self._focus_source: Optional[int] = None
        self._tunnel_signature: Tuple = ()
        self._route_signature: Tuple = ()
        self._project_signature: Tuple = ()
        self._errors_signature: Tuple = ()

        self.set_child(self._build_body())
        self._unsubscribe = [
            routes.subscribe(self._schedule_render),
            procs.subscribe(self._schedule_render),
            dns.subscribe(self._schedule_render),
            net.subscribe(self._schedule_render),
            speed.subscribe(self._schedule_render),
        ]
        self.connect("show", self._on_show)
        self.connect("hide", self._on_hide)
        self.connect("close-request", self._on_close)
        self.connect("notify::is-active", self._active_changed)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self._render()

    # ------------------------------------------------------------------ layout
    def _build_body(self) -> Gtk.Box:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.add_css_class("devn-panel")
        outer.set_margin_top(4)
        outer.set_margin_bottom(4)
        outer.set_margin_start(4)
        outer.set_margin_end(4)

        handle = Gtk.WindowHandle()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.add_css_class("devn-panel-body")
        handle.set_child(body)
        outer.append(handle)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.append(label(app_info.APP_NAME, "devn-panel-header"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        self._busy_spinner = Gtk.Spinner()
        self._busy_spinner.set_visible(False)
        header.append(self._busy_spinner)
        self._status_label = label("", "devn-caption", 1.0)
        header.append(self._status_label)
        body.append(header)

        # IPs ------------------------------------------------------------
        ip_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        ip_card.add_css_class("devn-ip-card")
        self._local = IPLine("computer-symbolic", "Local")
        self._isp = IPLine("network-wired-symbolic", "ISP")
        self._iran = IPLine("network-transmit-receive-symbolic", "Iran")
        for line in (self._local, self._isp, self._iran):
            ip_card.append(line)
        self._tunnel_rule = Gtk.Separator()
        self._tunnel_rule.set_margin_top(3)
        self._tunnel_rule.set_margin_bottom(3)
        self._tunnel_rule.set_visible(False)
        ip_card.append(self._tunnel_rule)
        self._tunnel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        ip_card.append(self._tunnel_box)
        body.append(ip_card)

        body.append(self._build_speed())

        self._error = label("", "devn-error")
        self._error.set_wrap(True)
        self._error.set_visible(False)
        body.append(self._error)

        toggles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._routes_tile = Tile("network-transmit-receive-symbolic", "Routes", "0 of 0 on", self._toggle_routes)
        self._routes_tile.set_hexpand(True)
        toggles.append(self._routes_tile)
        self._dns_tile = Tile("network-workgroup-symbolic", "DNS", "Automatic")
        self._dns_tile.set_hexpand(True)
        self._dns_menu = Gtk.MenuButton()
        self._dns_menu.add_css_class("devn-menu-tile")
        self._dns_menu.set_child(self._dns_tile)
        self._dns_menu.set_always_show_arrow(False)
        self._dns_menu.set_hexpand(True)
        self._dns_popover = Gtk.Popover()
        self._dns_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._dns_popover_box.set_margin_top(6)
        self._dns_popover_box.set_margin_bottom(6)
        self._dns_popover_box.set_margin_start(6)
        self._dns_popover_box.set_margin_end(6)
        self._dns_popover.set_child(self._dns_popover_box)
        self._dns_popover.connect("show", self._build_dns_menu)
        self._dns_menu.set_popover(self._dns_popover)
        toggles.append(self._dns_menu)
        body.append(toggles)

        self._routes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.append(self._routes_box)

        body.append(Gtk.Separator())

        projects_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        projects_header.append(label("Projects", "devn-row-subtitle"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        projects_header.append(spacer)
        self._projects_link = Gtk.Button()
        self._projects_link.add_css_class("flat")
        self._projects_link.add_css_class("devn-link")
        self._projects_link.connect("clicked", lambda _b: self._open("projects"))
        projects_header.append(self._projects_link)
        body.append(projects_header)

        self._projects_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.append(self._projects_box)

        body.append(Gtk.Separator())

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        open_button = Gtk.Button()
        open_button.add_css_class("flat")
        open_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        open_content.append(Gtk.Image.new_from_icon_name("window-new-symbolic"))
        open_content.append(label("Open DevNet"))
        open_button.set_child(open_content)
        open_button.connect("clicked", lambda _b: self._open(None))
        footer.append(open_button)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)
        quit_button = Gtk.Button()
        quit_button.add_css_class("flat")
        quit_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        quit_content.append(Gtk.Image.new_from_icon_name("application-exit-symbolic"))
        quit_content.append(label("Quit"))
        quit_button.set_child(quit_content)
        quit_button.connect("clicked", lambda _b: self.app.quit())
        footer.append(quit_button)
        body.append(footer)

        credits = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        credits.set_halign(Gtk.Align.CENTER)
        credits.append(
            label(f"{app_info.APP_NAME} {app_info.VERSION} · Created by", "devn-caption", 0.5)
        )
        link = Gtk.LinkButton.new_with_label(app_info.REPO, app_info.AUTHOR)
        link.add_css_class("devn-link")
        credits.append(link)
        body.append(credits)
        return outer

    def _build_speed(self) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("devn-speed-compact")
        row.set_valign(Gtk.Align.CENTER)

        badge = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        badge.add_css_class("devn-ping-badge")
        badge.set_valign(Gtk.Align.CENTER)
        self._ping = label("—", "devn-ping-value", 0.5)
        self._ping.set_halign(Gtk.Align.CENTER)
        badge.append(self._ping)
        unit = label("ms", "devn-caption", 0.5)
        unit.set_halign(Gtk.Align.CENTER)
        badge.append(unit)
        row.append(badge)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        rates = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._down = label("0 B/s", "devn-mono blue")
        self._up = label("0 B/s", "devn-mono orange")
        rates.append(Gtk.Image.new_from_icon_name("go-down-symbolic"))
        rates.append(self._down)
        rates.append(Gtk.Image.new_from_icon_name("go-up-symbolic"))
        rates.append(self._up)
        texts.append(rates)
        self._speed_host = label("Cloudflare", "devn-caption")
        texts.append(self._speed_host)
        row.append(texts)

        self._speed_button = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self._speed_button.add_css_class("flat")
        self._speed_button.set_valign(Gtk.Align.CENTER)
        self._speed_button.connect("clicked", self._toggle_speed)
        row.append(self._speed_button)

        open_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        open_button.add_css_class("flat")
        open_button.set_valign(Gtk.Align.CENTER)
        open_button.set_tooltip_text("Open the full speed test")
        open_button.connect("clicked", lambda _b: self._open("speed"))
        row.append(open_button)

        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        wrapper.append(row)
        self._speed_progress = Gtk.ProgressBar()
        self._speed_progress.add_css_class("devn-progress")
        self._speed_progress.set_visible(False)
        wrapper.append(self._speed_progress)
        return wrapper

    # ---------------------------------------------------------------- rendering
    def _schedule_render(self) -> None:
        if self._render_source is not None:
            return
        self._render_source = GLib.idle_add(self._render)

    def _render(self) -> bool:
        self._render_source = None
        self._sync_header()
        self._sync_network()
        self._sync_speed()
        self._sync_errors()
        self._sync_routes()
        self._sync_projects()
        return False

    def _sync_header(self) -> None:
        busy = self.routes.busy
        self._busy_spinner.set_visible(busy)
        if busy:
            self._busy_spinner.start()
            self._status_label.set_text("Applying…")
            return
        self._busy_spinner.stop()
        if self.net.vpn:
            count = len(self.net.tunnels)
            self._status_label.set_text(f"{count} VPNs on" if count > 1 else "VPN on")
        else:
            self._status_label.set_text("No VPN")

    def _sync_network(self) -> None:
        self._local.set_value(self.net.local_ip)
        self._isp.set_value(self.net.direct_ip)
        self._iran.set_value(self.net.routed_ip)
        signature = tuple(
            (tunnel.iface, tunnel.name, tunnel.public_ip, tunnel.iface == self.net.default_iface)
            for tunnel in self.net.tunnels
        )
        if signature == self._tunnel_signature:
            return
        self._tunnel_signature = signature
        _clear(self._tunnel_box)
        self._tunnel_rule.set_visible(bool(self.net.tunnels))
        for tunnel in self.net.tunnels:
            default = tunnel.iface == self.net.default_iface
            line = IPLine(
                "channel-secure-symbolic",
                tunnel.name,
                tunnel.public_ip,
                tunnel.iface + (" · default" if default else ""),
            )
            self._tunnel_box.append(line)

    def _ping_css(self) -> str:
        value = self.speed.live_ping
        if value is None:
            return "devn-ping-value"
        if value < 80:
            return "devn-ping-value green"
        if value < 200:
            return "devn-ping-value yellow"
        return "devn-ping-value red"

    def _sync_speed(self) -> None:
        store = self.speed
        self._ping.set_text("—" if store.live_ping is None else str(store.live_ping))
        for name in ("green", "yellow", "red"):
            self._ping.remove_css_class(name)
        for name in self._ping_css().split()[1:]:
            self._ping.add_css_class(name)
        self._down.set_text("…" if store.running else format_speed(store.activity_down, store.use_bytes))
        self._up.set_text("…" if store.running else format_speed(store.activity_up, store.use_bytes))
        self._speed_host.set_text(store.live_host_name or "Cloudflare")
        self._speed_button.set_icon_name(
            "media-playback-stop-symbolic" if store.running else "media-playback-start-symbolic"
        )
        self._speed_button.set_tooltip_text("Stop the speed test" if store.running else "Run a speed test")
        self._speed_progress.set_visible(store.running)
        self._speed_progress.set_fraction(store.progress)

    def _sync_errors(self) -> None:
        message = self.routes.error or self.dns.error or ""
        self._error.set_text(message)
        self._error.set_visible(bool(message))

    # -- routes -----------------------------------------------------------
    def _sync_routes(self) -> None:
        routes = self.routes.config.routes
        active = self.routes.active_count
        self._routes_tile.set_on(active > 0)
        self._routes_tile.set_subtitle(f"{active} of {len(routes)} on")

        active_preset = self.dns.active_preset
        if active_preset is not None:
            dns_name = active_preset.name
        elif self.dns.vpn_controls_dns:
            dns_name = f"From VPN ({self.dns.current_iface})"
        else:
            dns_name = "Automatic"
        self._dns_tile.set_on(active_preset is not None)
        self._dns_tile.set_subtitle(dns_name)

        signature = tuple(
            (route.id, route.net, bool(route.enabled), self.routes.is_partial(route),
             self.routes.hits.get(route.id, 0), len(route.targets),
             route.is_list, route.is_domain)
            for route in routes
        )
        if signature == self._route_signature:
            return
        self._route_signature = signature
        _clear(self._routes_box)
        if not routes:
            self._routes_box.append(label("No routes yet.", "devn-row-subtitle"))
            return
        self._routes_box.append(Gtk.Separator())
        for route in routes:
            self._routes_box.append(self._route_row(route))

    def _route_row(self, route: Route) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("devn-route-mini")
        row.set_valign(Gtk.Align.CENTER)
        if route.is_list:
            icon = "starred-symbolic"
        elif route.is_domain:
            icon = "network-workgroup-symbolic"
        else:
            icon = "network-transmit-receive-symbolic"
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(12)
        image.add_css_class("dim-label")
        row.append(image)
        text = label(route.net, "devn-mono")
        text.set_hexpand(True)
        row.append(text)
        if self.routes.is_partial(route):
            row.append(
                label(
                    f"{self.routes.hits.get(route.id, 0)}/{len(route.targets)}",
                    "devn-pill",
                    1.0,
                )
            )
        switch = Gtk.Switch()
        switch.set_active(bool(route.enabled))
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("state-set", self._route_switch, route)
        row.append(switch)
        return row

    def _route_switch(self, _switch: Gtk.Switch, state: bool, route: Route) -> bool:
        GLib.idle_add(lambda: (self.routes.set(route, state), False)[1])
        return False

    def _toggle_routes(self) -> None:
        self.routes.set_all(not self.routes.all_on)

    # -- DNS menu ---------------------------------------------------------
    def _build_dns_menu(self, _popover: Gtk.Popover) -> None:
        _clear(self._dns_popover_box)

        def item(text: str, active: bool, callback) -> None:
            widget = Gtk.Button()
            widget.add_css_class("flat")
            widget.set_halign(Gtk.Align.FILL)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_icon_name(
                "object-select-symbolic" if active else "network-workgroup-symbolic"
            )
            icon.set_opacity(1.0 if active else 0.3)
            content.append(icon)
            content.append(label(text))
            widget.set_child(content)
            widget.connect(
                "clicked",
                lambda _b: (self._dns_popover.popdown(), callback()),
            )
            self._dns_popover_box.append(widget)

        for preset in self.dns.presets:
            item(preset.name, self.dns.is_active(preset), lambda p=preset: self.dns.apply(p.servers))
        self._dns_popover_box.append(Gtk.Separator())
        item("Automatic (DHCP)", self.dns.active_preset is None, lambda: self.dns.apply([]))

    # -- projects ---------------------------------------------------------
    def _project_signature_now(self) -> Tuple:
        return (
            tuple(
                (item.pid, item.project, tuple(item.ports), item.runtime)
                for item in self.procs.items[:4]
            ),
            tuple(
                (container.id, container.name, tuple(container.published_ports))
                for container in self.procs.containers[
                    : max(0, 4 - len(self.procs.items))
                ]
            ),
            self.procs.docker_up,
            self.procs.count,
        )

    def _sync_projects(self) -> None:
        signature = self._project_signature_now()
        if signature == self._project_signature:
            return
        self._project_signature = signature
        _clear(self._projects_box)
        total = self.procs.count
        self._projects_link.set_visible(total > 4)
        self._projects_link.set_label(f"All {total}" if total > 4 else "")
        if total == 0:
            self._projects_box.append(label("Nothing running", "devn-row-subtitle"))
            return
        for process in self.procs.items[:4]:
            self._projects_box.append(self._process_row(process))
        remaining = max(0, 4 - len(self.procs.items))
        for container in self.procs.containers[:remaining]:
            self._projects_box.append(self._container_row(container))

    def _project_base(self, glyph: str, color: str, title: str) -> Tuple[Gtk.Box, Gtk.Box]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("devn-route-mini")
        row.set_valign(Gtk.Align.CENTER)
        row.append(AppIcon(glyph, None, color, small=True))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        texts.append(label(title, "devn-row-title"))
        row.append(texts)
        return row, texts

    def _process_row(self, process: DevProcess) -> Gtk.Box:
        glyph, color = process.runtime
        row, _texts = self._project_base(glyph, color, process.project)
        for port in process.ports[:2]:
            link = Gtk.LinkButton.new_with_label(f"http://localhost:{port}", f":{port}")
            link.add_css_class("flat")
            link.add_css_class("devn-link")
            row.append(link)
        stop = Gtk.Button.new_from_icon_name("window-close-symbolic")
        stop.add_css_class("flat")
        stop.set_tooltip_text("Stop")
        stop.connect("clicked", lambda _b, p=process: self.procs.stop(p))
        row.append(stop)
        return row

    def _container_row(self, container: Container) -> Gtk.Box:
        row, texts = self._project_base("Dk", "blue", container.name)
        texts.append(label(container.status, "devn-caption"))
        for port in container.published_ports[:2]:
            link = Gtk.LinkButton.new_with_label(f"http://localhost:{port}", f":{port}")
            link.add_css_class("flat")
            link.add_css_class("devn-link")
            row.append(link)
        stop = Gtk.Button.new_from_icon_name("window-close-symbolic")
        stop.add_css_class("flat")
        stop.set_tooltip_text("Stop")
        stop.connect("clicked", lambda _b, c=container: self.procs.stop_container(c))
        row.append(stop)
        return row

    # -- actions ----------------------------------------------------------
    def _toggle_speed(self, _button: Gtk.Button) -> None:
        if self.speed.running:
            self.speed.stop()
        else:
            self.speed.start()

    def _open(self, pane: Optional[str]) -> None:
        self.set_visible(False)
        self.app.show_window(pane)

    # -- lifecycle --------------------------------------------------------
    def _on_show(self, _window: Gtk.Widget) -> None:
        self.net.refresh()
        self.routes.refresh()
        self.dns.refresh()
        self.procs.refresh()
        self.speed.fetch_meta()
        self.speed.poke()
        self._render()
        self.app.refresh_speed_visibility()
        if self._focus_source is not None:
            GLib.source_remove(self._focus_source)
        self._focus_source = GLib.timeout_add(120, self._grab)

    def _grab(self) -> bool:
        self._focus_source = None
        self.present()
        return False

    def _on_hide(self, _window: Gtk.Widget) -> None:
        if self._focus_source is not None:
            GLib.source_remove(self._focus_source)
            self._focus_source = None
        self.app.refresh_speed_visibility()

    def _on_close(self, _window: Gtk.Window) -> bool:
        self.set_visible(False)
        return True

    def _active_changed(self, *_args) -> None:
        if self.get_visible() and not self.is_active():
            GLib.timeout_add(180, self._hide_if_inactive)

    def _hide_if_inactive(self) -> bool:
        if not self.is_active():
            self.set_visible(False)
        return False

    def _on_key(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        return False


__all__ = ["PanelWindow"]
