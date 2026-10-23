"""DNS pane: network link, presets and live resolver status."""

from __future__ import annotations

from typing import List, Optional

from gi.repository import Adw, GLib, Gtk

from ..dns import DNSPreset, DNSStore
from .widgets import FormDialog, button, group, label, page


class DNSView(Gtk.Box):
    title = "DNS"
    subtitle = ""

    def __init__(self, store: DNSStore) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.store = store
        self._render_source: Optional[int] = None
        self._updating = False

        self.toolbar_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._test_spinner = Gtk.Spinner()
        self._test_spinner.set_visible(False)
        self.toolbar_end.append(self._test_spinner)
        self.toolbar_end.append(
            button("devnet-speed-symbolic", "Test DNS latency", self._test)
        )
        self._flush_button = button(
            "devnet-refresh-symbolic", "Flush DNS cache", self.store.flush_cache
        )
        self.toolbar_end.append(self._flush_button)
        self.toolbar_end.append(button("devnet-add-symbolic", "Add DNS preset", lambda: self._edit(None)))

        self._page = page()
        self._page.set_vexpand(True)
        self._service_group = group()
        self._presets_group = group(
            "Presets",
            "Turning a preset off switches back to automatic DNS from your router or VPN.",
        )
        self._page.add(self._service_group)
        self._page.add(self._presets_group)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._page)
        scroller.set_vexpand(True)
        self.append(scroller)

        self._rows: List[tuple] = []
        self._unsubscribe = store.subscribe(self._schedule_render)
        self._render()

    # -- rendering --------------------------------------------------------
    def _schedule_render(self) -> None:
        if self._render_source is not None:
            return
        self._render_source = GLib.idle_add(self._render)

    def _render(self) -> bool:
        self._render_source = None
        self._updating = True
        try:
            for parent, row in self._rows:
                parent.remove(row)
            self._rows = []

            self._service_rows()
            self._preset_rows()

            self.subtitle = (self.store.active_preset.name if self.store.active_preset else "Automatic")
            self._test_spinner.set_visible(self.store.testing)
            if self.store.testing:
                self._test_spinner.start()
            else:
                self._test_spinner.stop()
            self._flush_button.set_icon_name(
                "devnet-check-symbolic" if self.store.flushed else "devnet-refresh-symbolic"
            )
        finally:
            self._updating = False
        return False

    def _add_row(self, parent, row: Adw.PreferencesRow) -> None:
        parent.add(row)
        self._rows.append((parent, row))

    def _service_rows(self) -> None:
        link_row = Adw.ActionRow()
        link_row.set_title("Network Link")
        link_row.set_subtitle("Presets are applied to every active link, including VPN links.")
        dropdown = Gtk.DropDown.new_from_strings(self.store.links or ["No links"])
        dropdown.set_valign(Gtk.Align.CENTER)
        dropdown.set_sensitive(bool(self.store.links))
        if self.store.service in self.store.links:
            dropdown.set_selected(self.store.links.index(self.store.service))
        dropdown.connect("notify::selected", self._link_changed, dropdown)
        link_row.add_suffix(dropdown)
        self._add_row(self._service_group, link_row)

        current_row = Adw.ActionRow()
        current_row.set_title("DNS Servers")
        current = ", ".join(self.store.current) if self.store.current else "Automatic"
        if self.store.current_iface:
            current += f" — via {self.store.current_iface}"
        current_row.set_subtitle(current)
        current_row.set_tooltip_text(current)
        name = self.store.active_preset.name if self.store.active_preset else "Automatic"
        active = label(name, "devn-chip")
        current_row.add_suffix(active)
        self._add_row(self._service_group, current_row)

        if self.store.vpn_controls_dns and not self.store.helper_installed:
            warning = Adw.ActionRow()
            warning.add_prefix(Gtk.Image.new_from_icon_name("devnet-warning-symbolic"))
            warning.set_title("Your VPN sets its own DNS")
            warning.set_subtitle(
                "Enable passwordless mode in the sidebar so presets can override it."
            )
            self._add_row(self._service_group, warning)

        if self.store.active_preset is not None or self.store.configured:
            reset = Adw.ActionRow()
            reset.set_title("Use Automatic DNS")
            reset.set_subtitle("Restore the resolver provided by your network.")
            reset_button = Gtk.Button(label="Automatic")
            reset_button.add_css_class("flat")
            reset_button.connect("clicked", lambda _b: self.store.apply([]))
            reset.add_suffix(reset_button)
            self._add_row(self._service_group, reset)

    def _preset_rows(self) -> None:
        if not self.store.presets:
            empty = Adw.ActionRow()
            empty.set_title("No presets")
            empty.set_subtitle("Click + to add a DNS server.")
            empty.set_sensitive(False)
            self._add_row(self._presets_group, empty)
            return
        for index, preset in enumerate(self.store.presets):
            row = Adw.ActionRow()
            row.set_title(preset.name)
            row.set_subtitle(", ".join(preset.servers))
            row.set_tooltip_text(", ".join(preset.servers))
            suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            suffix.set_valign(Gtk.Align.CENTER)
            first = preset.servers[0] if preset.servers else ""
            value = self.store.latency.get(first)
            if value is not None:
                if value < 0:
                    text, css = "Timeout", "devn-error"
                else:
                    text = f"{value} ms"
                    css = (
                        "devn-success" if value < 60 else "devn-warning" if value < 150 else "devn-error"
                    )
                suffix.append(label(text, "devn-mono " + css))
            suffix.append(button("devnet-info-symbolic", "Edit preset", lambda i=index: self._edit(i)))
            switch = Gtk.Switch()
            switch.set_active(self.store.is_active(preset))
            switch.set_valign(Gtk.Align.CENTER)
            switch.connect("state-set", self._on_switch, preset)
            suffix.append(switch)
            row.add_suffix(suffix)
            self._add_row(self._presets_group, row)

    # -- actions ----------------------------------------------------------
    def _link_changed(self, dropdown: Gtk.DropDown, _param, _widget) -> None:
        if self._updating:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(self.store.links):
            self.store.select_link(self.store.links[index])

    def _on_switch(self, _switch: Gtk.Switch, state: bool, preset: DNSPreset) -> bool:
        if not self._updating:
            servers = preset.servers if state else []
            GLib.idle_add(lambda: self.store.apply(servers))
        return False

    def _test(self) -> None:
        self.store.test_latency()

    def _edit(self, index: Optional[int]) -> None:
        preset = self.store.presets[index] if index is not None else None
        fields = [
            ("Name", preset.name if preset else "", "Cloudflare"),
            ("Servers", ", ".join(preset.servers) if preset else "", "1.1.1.1, 1.0.0.1"),
        ]

        def submit(values: List[str]) -> Optional[str]:
            return self.store.upsert(index, values[0], values[1])

        dialog = FormDialog(
            self.get_root(),
            "Edit DNS Preset" if index is not None else "New DNS Preset",
            fields,
            "Save" if index is not None else "Add",
            submit,
            destructive_label="Delete Preset" if index is not None else None,
            on_destructive=(lambda: self.store.remove(self.store.presets[index])) if index is not None else None,
        )
        dialog.present()
        dialog.focus_first()

    # -- lifecycle --------------------------------------------------------
    def on_show(self) -> None:
        self.store.refresh()
        self._schedule_render()

    def on_hide(self) -> None:
        pass


__all__ = ["DNSView"]
