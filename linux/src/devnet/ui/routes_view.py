"""Routes pane: split-tunneling entries and the default gateway."""

from __future__ import annotations

from typing import List, Optional

from gi.repository import Adw, GLib, Gtk

from ..routes import Route, RouteStore
from ..shell import clipboard_text
from ..network import device_for_gateway
from .widgets import FormDialog, button, group, label, page


class RoutesView(Gtk.Box):
    title = "Routes"
    subtitle = ""

    def __init__(self, store: RouteStore) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.store = store
        self._updating = False
        self._render_source: Optional[int] = None
        self._gateway_value = ""

        self.toolbar_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_start.append(
            button("view-refresh-symbolic", "Refresh route status", self._refresh)
        )
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._spinner.set_tooltip_text("Applying changes…")
        self.toolbar_start.append(self._spinner)
        self.toolbar_end.append(self._add_button())

        page_widget = page()
        page_widget.set_vexpand(True)
        self._all_group = group()
        # Adw.SwitchRow needs libadwaita 1.4; Debian 12 ships 1.2, so use the
        # equivalent ActionRow + Switch pair that has been available since 1.0.
        self._all_row = Adw.ActionRow()
        self._all_row.set_title("All Routes")
        self._all_switch = Gtk.Switch()
        self._all_switch.set_valign(Gtk.Align.CENTER)
        self._all_switch.connect("state-set", self._on_all_switch)
        self._all_row.add_suffix(self._all_switch)
        self._all_row.set_activatable_widget(self._all_switch)
        self._all_group.add(self._all_row)
        page_widget.add(self._all_group)

        self._routes_group = group(
            "Routes",
            "Traffic to these networks goes through the gateway instead of the default route.",
        )
        page_widget.add(self._routes_group)
        self._gateway_group = group()
        self._gateway_row = Adw.ActionRow()
        self._gateway_row.set_title("Default Gateway")
        self._gateway_row.set_subtitle("Leave empty to use the router of the current network.")
        self._gateway_entry = Gtk.Entry()
        self._gateway_entry.set_width_chars(20)
        self._gateway_entry.set_valign(Gtk.Align.CENTER)
        self._gateway_entry.connect("activate", self._on_gateway)
        self._gateway_row.add_suffix(self._gateway_entry)
        self._gateway_group.add(self._gateway_row)
        page_widget.add(self._gateway_group)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page_widget)
        scroller.set_vexpand(True)
        self.append(scroller)

        self._page = page_widget
        self._route_rows: List[Adw.PreferencesRow] = []
        self._unsubscribe = store.subscribe(self._schedule_render)
        self._render()

    # -- toolbar ----------------------------------------------------------
    def _add_button(self) -> Gtk.MenuButton:
        menu = Gtk.MenuButton()
        menu.set_icon_name("list-add-symbolic")
        menu.set_tooltip_text("Add a route")
        menu.add_css_class("flat")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        first = Gtk.Button(label="Network or Domain…")
        first.add_css_class("flat")
        first.set_halign(Gtk.Align.FILL)
        first.connect("clicked", lambda _b: (popover.popdown(), self._edit(None)))
        second = Gtk.Button(label="Country IP Ranges…")
        second.add_css_class("flat")
        second.set_halign(Gtk.Align.FILL)
        second.connect("clicked", lambda _b: (popover.popdown(), self._country()))
        box.append(first)
        box.append(second)
        popover.set_child(box)
        menu.set_popover(popover)
        return menu

    # -- rendering --------------------------------------------------------
    def _schedule_render(self) -> None:
        if self._render_source is not None:
            return
        self._render_source = GLib.idle_add(self._render)

    def _render(self) -> bool:
        self._render_source = None
        self._updating = True
        try:
            total = len(self.store.config.routes)
            active = self.store.active_count
            self._all_switch.set_active(self.store.all_on)
            self._all_row.set_subtitle(
                "Applying changes…" if self.store.busy else f"{active} of {total} active"
            )
            self._spinner.set_visible(self.store.busy)
            if self.store.busy:
                self._spinner.start()
            else:
                self._spinner.stop()
            self.subtitle = f"{active} of {total} active"

            for row in self._route_rows:
                self._routes_group.remove(row)
            self._route_rows = []
            if not self.store.config.routes:
                empty = Adw.ActionRow()
                empty.set_title("No routes yet")
                empty.set_subtitle("Click + to add a network, domain or country.")
                empty.set_sensitive(False)
                self._routes_group.add(empty)
                self._route_rows.append(empty)
            else:
                for index, route in enumerate(self.store.config.routes):
                    self._route_rows.append(self._route_row(index, route))

            gateway = self.store.current_gateway
            self._gateway_entry.set_placeholder_text(
                f"Automatic ({gateway})" if gateway else "Automatic (no network)"
            )
            if not self._gateway_entry.has_focus():
                self._gateway_entry.set_text(self.store.config.gateway)

            self._all_row.set_sensitive(total > 0 and not self.store.busy)
        finally:
            self._updating = False
        return False

    def _route_row(self, index: int, route: Route) -> Adw.PreferencesRow:
        row = Adw.ActionRow()
        row.set_title(route.net)
        pieces = []
        if route.is_list:
            pieces.append(f"{self.store.hits.get(route.id, 0)} of {len(route.targets)} ranges")
        elif route.is_domain:
            addresses = ", ".join(route.resolved or [])
            if addresses:
                pieces.append(addresses)
        pieces.append(f"via {self.store.gateway_for(route)}")
        if route.note:
            pieces.append(route.note)
        row.set_subtitle(" — ".join(pieces))
        row.set_tooltip_text(row.get_subtitle() or "")

        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        suffix.set_valign(Gtk.Align.CENTER)
        if self.store.is_partial(route):
            missing = len(route.targets) - self.store.hits.get(route.id, 0)
            partial = Gtk.Button(label=f"{missing} missing")
            partial.add_css_class("devn-pill")
            partial.add_css_class("flat")
            partial.set_tooltip_text("Apply the missing ranges")
            partial.connect(
                "clicked",
                lambda _b, r=route: GLib.idle_add(lambda: self.store.set(r, True)),
            )
            suffix.append(partial)
        copy = button(
            "edit-copy-symbolic",
            "Copy the equivalent ip route command",
            lambda r=route: self._copy_commands(r),
        )
        suffix.append(copy)
        if route.is_list:
            edit = button(
                "view-refresh-symbolic",
                "Update the country ranges",
                lambda r=route: self.store.add_country(r.country or ""),
            )
        else:
            edit = button("dialog-information-symbolic", "Edit route", lambda i=index: self._edit(i))
        suffix.append(edit)
        switch = Gtk.Switch()
        switch.set_active(self.store.active.get(route.id, False))
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("state-set", self._on_route_switch, route)
        suffix.append(switch)
        row.add_suffix(suffix)
        self._routes_group.add(row)
        return row

    # -- actions ----------------------------------------------------------
    def _on_route_switch(self, _switch: Gtk.Switch, state: bool, route: Route) -> bool:
        if not self._updating:
            GLib.idle_add(lambda: self.store.set(route, state))
        return False

    def _on_all_switch(self, _switch: Gtk.Switch, state: bool) -> bool:
        if not self._updating:
            GLib.idle_add(lambda: (self.store.set_all(state), False)[1])
        return False

    def _on_gateway(self, entry: Gtk.Entry) -> None:
        if self.store.set_gateway(entry.get_text()):
            self._gateway_entry.set_text(self.store.config.gateway)
        else:
            entry.set_text(self.store.config.gateway)

    def _refresh(self) -> None:
        self.store.refresh()
        self._schedule_render()

    def _copy_commands(self, route: Route) -> None:
        gateway = self.store.gateway_for(route)
        device = self.store.lan_device or device_for_gateway(gateway)
        lines = []
        for target in route.targets:
            line = f"sudo ip route replace {target} via {gateway}"
            if device:
                line += f" dev {device}"
            lines.append(line)
        clipboard_text("\n".join(lines))

    def _edit(self, index: Optional[int]) -> None:
        route = self.store.config.routes[index] if index is not None else None
        fields = [
            ("Network or Domain", route.net if route else "", "10.20.30.0/24 or example.com"),
            ("Gateway", (route.gateway or "") if route else "", self.store.current_gateway or "Automatic"),
            ("Note", route.note if route else "", "Optional"),
        ]

        def submit(values: List[str]) -> Optional[str]:
            return self.store.upsert(index, values[0], values[1], values[2])

        dialog = FormDialog(
            self.get_root(),
            "Edit Route" if index is not None else "New Route",
            fields,
            "Save" if index is not None else "Add",
            submit,
            destructive_label="Delete Route" if index is not None else None,
            on_destructive=(lambda: self.store.remove(self.store.config.routes[index])) if index is not None else None,
        )
        dialog.present()
        dialog.focus_first()

    def _country(self) -> None:
        def submit(values: List[str]) -> Optional[str]:
            code = values[0].strip()
            if len(code) != 2 or not code.isalpha():
                return "Enter a two-letter country code, e.g. IR."
            self.store.add_country(code)
            return None

        dialog = FormDialog(
            self.get_root(),
            "Country IP Ranges",
            [("Country code", "IR", "IR")],
            "Add",
            submit,
        )
        dialog.present()
        dialog.focus_first()

    # -- lifecycle --------------------------------------------------------
    def on_show(self) -> None:
        self.store.refresh()
        self._schedule_render()

    def on_hide(self) -> None:
        pass


__all__ = ["RoutesView"]
