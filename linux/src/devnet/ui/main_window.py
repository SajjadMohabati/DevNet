"""The main DevNet window: sidebar, network summary and the four panes."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import app_info, autostart, privilege
from ..dns import DNSStore
from ..network import NetStore
from ..processes import ProcStore
from ..routes import RouteStore
from ..shell import background, on_main
from ..shortcut import DEFAULT_ACCELERATOR, ShortcutManager, launch_command
from ..speed import SpeedStore
from ..storage import Settings
from .dns_view import DNSView
from .projects_view import ProjectsView
from .routes_view import RoutesView
from .speed_view import SpeedView
from .widgets import AppIcon, Badge, ShortcutRecorder, SidebarRow, label

log = logging.getLogger(__name__)

PANES: Tuple[Tuple[str, str, str, str], ...] = (
    ("routes", "Routes", "network-transmit-receive-symbolic", "blue"),
    ("projects", "Projects", "applications-engineering-symbolic", "green"),
    ("dns", "DNS", "network-workgroup-symbolic", "indigo"),
    ("speed", "Speed", "power-profile-performance-symbolic", "orange"),
)


def _clear(box: Gtk.Box) -> None:
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def _has_icon(name: str) -> bool:
    display = Gdk.Display.get_default()
    if display is None:
        return False
    try:
        return Gtk.IconTheme.get_for_display(display).has_icon(name)
    except Exception:
        return False


class MainWindow(Adw.ApplicationWindow):
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
        super().__init__(application=app)
        self.app = app
        self.settings = settings
        self.routes = routes
        self.procs = procs
        self.dns = dns
        self.net = net
        self.speed = speed
        self.shortcuts = ShortcutManager()

        self.set_title(app_info.APP_NAME)
        self.set_default_size(1060, 740)
        self.set_size_request(860, 560)
        self.add_css_class("devn-window")

        pane = str(settings.get("pane", "routes"))
        self.pane = pane if pane in {item[0] for item in PANES} else "routes"
        self._updating = False
        self._net_signature: Tuple = ()
        self._header_source: Optional[int] = None
        self._about: Optional[Adw.AboutWindow] = None
        self._passwordless_busy = False
        self._passwordless_state: Optional[bool] = None
        self._render_source: Optional[int] = None

        self._views = {
            "routes": RoutesView(routes),
            "projects": ProjectsView(procs),
            "dns": DNSView(dns),
            "speed": SpeedView(speed),
        }
        self._toolbars: Dict[str, Tuple[List[Gtk.Widget], List[Gtk.Widget]]] = {}
        for key, view in self._views.items():
            self._toolbars[key] = (
                self._take_children(view.toolbar_start),
                self._take_children(view.toolbar_end),
            )

        self._nav: Dict[str, Tuple[Gtk.ToggleButton, Badge]] = {}
        self._build_layout()
        self._sync_pane_ui()
        self._render_sidebar()

        self._unsubscribe = [
            routes.subscribe(self._schedule_render),
            procs.subscribe(self._schedule_render),
            dns.subscribe(self._schedule_render),
            net.subscribe(self._schedule_render),
            speed.subscribe(self._schedule_render),
        ]
        self.connect("close-request", self._on_close)
        self.connect("show", self._on_show)
        self.connect("hide", self._on_hide)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.append(self._build_sidebar())

        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        detail.set_hexpand(True)

        header = Adw.HeaderBar()
        self._header = header
        self._title = label("DevNet", "title-4")
        self._title.set_halign(Gtk.Align.CENTER)
        self._subtitle = label("", "devn-caption", 0.5)
        self._subtitle.set_halign(Gtk.Align.CENTER)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_valign(Gtk.Align.CENTER)
        title_box.append(self._title)
        title_box.append(self._subtitle)
        header.set_title_widget(title_box)

        self._toolbar_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._toolbar_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.pack_start(self._toolbar_start)
        header.pack_end(self._toolbar_end)
        self._app_menu_button = self._app_menu()
        self._toolbar_end.append(self._app_menu_button)
        detail.append(header)

        self._banner = self._build_banner()
        detail.append(self._banner)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)
        self._stack.set_vexpand(True)
        for key, _, _, _ in PANES:
            self._stack.add_named(self._views[key], key)
        detail.append(self._stack)

        root.append(detail)
        self.set_content(root)

    def _build_banner(self) -> Gtk.Revealer:
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("devn-banner")
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_valign(Gtk.Align.CENTER)
        box.append(icon)
        self._banner_label = label("", "devn-error")
        self._banner_label.set_hexpand(True)
        self._banner_label.set_wrap(True)
        box.append(self._banner_label)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.set_tooltip_text("Dismiss")
        close.connect("clicked", self._dismiss_errors)
        box.append(close)
        revealer.set_child(box)
        return revealer

    def _build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("devn-sidebar")
        sidebar.set_size_request(236, -1)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand.add_css_class("devn-brand")
        if _has_icon(app_info.APP_ID):
            image = Gtk.Image.new_from_icon_name(app_info.APP_ID)
            image.set_pixel_size(30)
            brand.append(image)
        else:
            brand.append(AppIcon("DN", None, "blue"))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        texts.set_valign(Gtk.Align.CENTER)
        texts.append(label(app_info.APP_NAME, "devn-brand-title"))
        texts.append(label("Linux · Split tunneling", "devn-brand-subtitle"))
        brand.append(texts)
        sidebar.append(brand)

        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav.add_css_class("devn-nav")
        nav.set_margin_start(8)
        nav.set_margin_end(8)
        group: Optional[Gtk.ToggleButton] = None
        for key, title, icon, color in PANES:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.append(AppIcon(None, icon, color, small=True))
            row.append(label(title, "devn-nav-title"))
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            row.append(spacer)
            badge = Badge()
            row.append(badge)
            toggle = Gtk.ToggleButton()
            toggle.set_child(row)
            toggle.set_tooltip_text(title)
            if group is None:
                group = toggle
            else:
                toggle.set_group(group)
            toggle.connect("toggled", self._nav_toggled, key)
            nav.append(toggle)
            self._nav[key] = (toggle, badge)
        sidebar.append(nav)

        sidebar.append(label("NETWORK", "devn-section-label"))
        self._net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.append(self._net_box)

        filler = Gtk.Box()
        filler.set_vexpand(True)
        sidebar.append(filler)
        sidebar.append(self._build_footer())
        return sidebar

    def _build_footer(self) -> Gtk.Box:
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        footer.add_css_class("devn-footer")

        self._passwordless = Gtk.Button()
        self._passwordless.add_css_class("flat")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        content.set_halign(Gtk.Align.START)
        content.append(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        self._passwordless_label = label("Enable Passwordless Mode…")
        content.append(self._passwordless_label)
        self._passwordless.set_child(content)
        self._passwordless.set_tooltip_text(
            "Install a polkit rule limited to route and DNS changes, so DevNet "
            "never asks for your password"
        )
        self._passwordless.set_halign(Gtk.Align.START)
        self._passwordless.connect("clicked", self._enable_passwordless)
        footer.append(self._passwordless)

        shortcut_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        shortcut_row.add_css_class("devn-footer-row")
        shortcut_row.append(label("Shortcut"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        shortcut_row.append(spacer)
        accelerator = str(self.settings.get("shortcut", DEFAULT_ACCELERATOR) or "")
        self._shortcut = ShortcutRecorder(accelerator, self._shortcut_changed)
        self._shortcut.set_valign(Gtk.Align.CENTER)
        shortcut_row.append(self._shortcut)
        shortcut_row.set_tooltip_text("Opens the panel from anywhere (GNOME)")
        footer.append(shortcut_row)

        autostart_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        autostart_row.add_css_class("devn-footer-row")
        autostart_row.append(label("Launch at Login"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        autostart_row.append(spacer)
        self._autostart = Gtk.Switch()
        self._autostart.set_valign(Gtk.Align.CENTER)
        self._autostart.set_active(autostart.enabled())
        self._autostart.connect("state-set", self._autostart_changed)
        autostart_row.append(self._autostart)
        footer.append(autostart_row)

        self._footer_error = label("", "devn-error")
        self._footer_error.set_wrap(True)
        self._footer_error.set_visible(False)
        footer.append(self._footer_error)

        footer.append(Gtk.Separator())

        credits = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        credits.append(label(f"{app_info.APP_NAME} {app_info.VERSION} · by", "devn-caption"))
        link = Gtk.LinkButton.new_with_label(app_info.WEBSITE, app_info.AUTHOR)
        link.add_css_class("devn-link")
        link.set_tooltip_text(app_info.REPO)
        credits.append(link)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        credits.append(spacer)
        about = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about.add_css_class("flat")
        about.set_tooltip_text("About DevNet")
        about.connect("clicked", lambda _b: self._show_about())
        credits.append(about)
        footer.append(credits)

        self._sync_passwordless()
        return footer

    def _app_menu(self) -> Gtk.MenuButton:
        menu = Gtk.MenuButton()
        menu.set_icon_name("open-menu-symbolic")
        menu.add_css_class("flat")
        menu.set_tooltip_text("Main Menu")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        def item(text: str, icon: str, callback) -> None:
            widget = Gtk.Button()
            widget.add_css_class("flat")
            widget.set_halign(Gtk.Align.FILL)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.append(Gtk.Image.new_from_icon_name(icon))
            content.append(label(text))
            widget.set_child(content)
            widget.connect("clicked", lambda _b: (popover.popdown(), callback()))
            box.append(widget)

        item("Open Panel", "view-list-symbolic", lambda: self.app.toggle_panel())
        item("About DevNet", "help-about-symbolic", self._show_about)
        box.append(Gtk.Separator())
        item("Quit DevNet", "application-exit-symbolic", lambda: self.app.quit())
        popover.set_child(box)
        menu.set_popover(popover)
        return menu

    # ------------------------------------------------------------------ panes
    def _take_children(self, box: Gtk.Box) -> List[Gtk.Widget]:
        widgets: List[Gtk.Widget] = []
        while (child := box.get_first_child()) is not None:
            box.remove(child)
            widgets.append(child)
        return widgets

    def _nav_toggled(self, toggle: Gtk.ToggleButton, key: str) -> None:
        if self._updating or not toggle.get_active():
            return
        self.set_pane(key)

    def set_pane(self, key: str) -> None:
        if key not in self._views:
            return
        previous = self.pane
        if previous == key and self._stack.get_visible_child_name() == key:
            return
        self.pane = key
        self.settings.set("pane", key)
        old_view = self._views.get(previous)
        if old_view is not None and previous != key:
            old_view.on_hide()
        self._stack.set_visible_child_name(key)
        self._sync_pane_ui()
        self._views[key].on_show()
        self.app.refresh_speed_visibility()

    def _sync_pane_ui(self) -> None:
        self._updating = True
        try:
            for key, (toggle, _badge) in self._nav.items():
                toggle.set_active(key == self.pane)
        finally:
            self._updating = False
        self._sync_header()
        self._populate_toolbar()

    def _populate_toolbar(self) -> None:
        _clear(self._toolbar_start)
        while (child := self._toolbar_end.get_first_child()) is not None:
            self._toolbar_end.remove(child)
        start, end = self._toolbars.get(self.pane, ([], []))
        for widget in start:
            self._toolbar_start.append(widget)
        for widget in end:
            self._toolbar_end.append(widget)
        self._toolbar_end.append(self._app_menu_button)

    def _sync_header(self) -> None:
        self._header_source = None
        view = self._views.get(self.pane)
        if view is None:
            return
        self._title.set_text(view.title)
        self._subtitle.set_text(view.subtitle)
        self._subtitle.set_visible(bool(view.subtitle))

    def _schedule_render(self) -> None:
        if self._render_source is not None:
            return
        self._render_source = GLib.idle_add(self._render)

    def _render(self) -> bool:
        self._render_source = None
        self._render_sidebar()
        self._sync_header()
        self._sync_errors()
        self._sync_passwordless()
        return False

    # ---------------------------------------------------------------- sidebar
    def _render_sidebar(self) -> None:
        self._nav["routes"][1].set_text(str(self.routes.active_count) if self.routes.active_count else "")
        self._nav["projects"][1].set_text(str(self.procs.count) if self.procs.count else "")
        self._render_network()

    def _render_network(self) -> None:
        signature = (
            self.net.default_iface,
            self.net.vpn,
            self.net.local_ip,
            self.net.direct_ip,
            self.net.routed_ip,
            self.net.gateway,
            self.net.gateway_up,
            tuple((tunnel.iface, tunnel.name, tunnel.public_ip) for tunnel in self.net.tunnels),
        )
        if signature == self._net_signature:
            return
        self._net_signature = signature
        _clear(self._net_box)

        default = "—"
        if self.net.default_iface:
            default = f"VPN ({self.net.default_iface})" if self.net.vpn else self.net.default_iface
        rows = [
            ("Default Route", default, None),
            ("Local IP", self.net.local_ip or "—", None),
            ("ISP IP", self.net.direct_ip or "—", None),
            ("Iran IP", self.net.routed_ip or "—", None),
        ]
        for title, value, state in rows:
            self._net_box.append(SidebarRow(title, value, dot=state is not None))
        for tunnel in self.net.tunnels:
            row = SidebarRow(f"{tunnel.name} ({tunnel.iface})", tunnel.public_ip or "—")
            self._net_box.append(row)
        if self.net.gateway_up is True:
            gateway_text = "Reachable"
        elif self.net.gateway_up is False:
            gateway_text = "Unreachable"
        else:
            gateway_text = "—"
        gateway = SidebarRow("Gateway", gateway_text, dot=True)
        gateway.set_state(self.net.gateway_up)
        self._net_box.append(gateway)

    def _sync_errors(self) -> None:
        message = self.routes.error or self.dns.error or ""
        self._banner_label.set_text(message)
        self._banner.set_reveal_child(bool(message))

    def _dismiss_errors(self) -> None:
        self.routes.error = None
        self.dns.error = None
        self._sync_errors()

    def _sync_passwordless(self, force: bool = False) -> None:
        if force or self._passwordless_state is None:
            self._passwordless_state = privilege.passwordless()
        enabled = bool(self._passwordless_state)
        self._passwordless.set_visible(not enabled)
        self._passwordless.set_sensitive(not self._passwordless_busy)
        self._passwordless_label.set_text(
            "Enabling…" if self._passwordless_busy else "Enable Passwordless Mode…"
        )

    # ----------------------------------------------------------------- footer
    def _enable_passwordless(self) -> None:
        if self._passwordless_busy:
            return
        self._passwordless_busy = True
        self._passwordless.set_sensitive(False)
        self._sync_passwordless()

        def work() -> None:
            error = privilege.enable_passwordless()
            on_main(lambda: self._after_passwordless(error))

        background(work)

    def _after_passwordless(self, error: str) -> None:
        self._passwordless_busy = False
        self._passwordless.set_sensitive(True)
        if error:
            self._footer_error.set_text(error)
            self._footer_error.set_visible(True)
        else:
            self._footer_error.set_visible(False)
            self.dns.refresh()
        self._sync_passwordless(force=True)

    def _shortcut_changed(self, accelerator: str) -> None:
        if not accelerator:
            self.shortcuts.unregister()
            self.settings.set("shortcut", "")
            return
        error = self.shortcuts.register(accelerator, launch_command())
        if error:
            self._footer_error.set_text(error)
            self._footer_error.set_visible(True)
            self._shortcut.set_accelerator(str(self.settings.get("shortcut", DEFAULT_ACCELERATOR)))
            return
        self._footer_error.set_visible(False)
        self.settings.set("shortcut", accelerator)

    def _autostart_changed(self, _switch: Gtk.Switch, state: bool) -> bool:
        command = launch_command().replace("--panel", "--background")
        if autostart.set_enabled(state, command):
            if state:
                self.settings.set("autostart_command", command)
            self._footer_error.set_visible(False)
        else:
            self._footer_error.set_text("Couldn’t update the autostart entry.")
            self._footer_error.set_visible(True)
            GLib.idle_add(lambda: (self._autostart.set_active(not state), False)[1])
        return False

    def _show_about(self) -> None:
        if self._about is not None:
            self._about.present()
            return
        about = Adw.AboutWindow(
            transient_for=self,
            modal=False,
            application_name=app_info.APP_NAME,
            application_icon=app_info.APP_ID,
            version=app_info.VERSION,
            developer_name=app_info.AUTHOR,
            website=app_info.WEBSITE,
            issue_url=app_info.ISSUES,
            comments=app_info.DESCRIPTION,
            license_type=Gtk.License.MIT_X11,
        )
        about.connect("close-request", self._about_closed)
        self._about = about
        about.present()

    def _about_closed(self, window: Gtk.Window) -> bool:
        self._about = None
        return False

    # -------------------------------------------------------------- lifecycle
    def _on_show(self, _window: Gtk.Widget) -> None:
        self._render_sidebar()
        self._sync_header()
        self._sync_passwordless(force=True)
        self._views[self.pane].on_show()
        self.app.refresh_speed_visibility()

    def _on_hide(self, _window: Gtk.Widget) -> None:
        self.app.refresh_speed_visibility()

    def _on_close(self, _window: Gtk.Window) -> bool:
        if getattr(self.app, "tray_available", False):
            self.set_visible(False)
            return True
        self.app.quit()
        return True

    def _on_key(self, _controller, keyval, _keycode, state) -> bool:
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        if control and keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self.app.quit()
            return True
        if control and keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.set_visible(False)
            return True
        if control and Gdk.KEY_1 <= keyval <= Gdk.KEY_4:
            self.set_pane([item[0] for item in PANES][keyval - Gdk.KEY_1])
            return True
        return False


__all__ = ["MainWindow"]
