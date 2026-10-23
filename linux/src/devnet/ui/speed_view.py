"""Speed pane: live activity, a Cloudflare speed test, ping targets and history."""

from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple

from gi.repository import Adw, GLib, Gtk

from ..shell import clipboard_text
from ..speed import SpeedResult, SpeedStore, PingTarget, format_speed
from .widgets import FormDialog, StatTile, button, label, suggested_button

CARD_MAX_WIDTH = 760


def _card(title: str, description: str = "") -> Tuple[Gtk.Box, Gtk.Box]:
    """A rounded card with a header; returns the outer widget and its content box."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.add_css_class("devn-card")
    heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    heading.append(label(title, "devn-card-title"))
    if description:
        subtitle = label(description, "devn-card-subtitle")
        subtitle.set_wrap(True)
        heading.append(subtitle)
    outer.append(heading)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.append(content)
    return outer, content


def _separator() -> Gtk.Box:
    line = Gtk.Box()
    line.add_css_class("devn-separator")
    line.set_margin_top(2)
    line.set_margin_bottom(2)
    return line


def _clear(box: Gtk.Box) -> None:
    while (child := box.get_first_child()) is not None:
        box.remove(child)


class SpeedView(Gtk.Box):
    title = "Speed"
    subtitle = "Not tested yet"

    def __init__(self, store: SpeedStore) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.store = store
        self._updating = False
        self._render_source: Optional[int] = None
        self._target_signature: Tuple = ()
        self._history_signature: Tuple = ()
        self._meta_signature: Tuple = ()

        # -- toolbar ------------------------------------------------------
        self.toolbar_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self._test_button = Gtk.Button.new_from_icon_name("devnet-speed-symbolic")
        self._test_button.add_css_class("flat")
        self._test_button.set_tooltip_text("Test download and upload speed")
        self._test_button.connect("clicked", lambda _b: self._toggle_test())
        self.toolbar_end.append(self._test_button)

        add_target = button(
            "devnet-add-symbolic", "Add a ping target", lambda: self._edit_target(None)
        )
        self.toolbar_end.append(add_target)

        self._units = Gtk.DropDown.new_from_strings(["Mbps", "MB/s"])
        self._units.set_tooltip_text("Show speeds in bits or bytes per second")
        self._units.set_valign(Gtk.Align.CENTER)
        self._units.set_selected(1 if store.use_bytes else 0)
        self._units.connect("notify::selected", self._units_changed)
        self.toolbar_end.append(self._units)

        self.toolbar_end.append(self._more_button())

        # -- content ------------------------------------------------------
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_margin_top(18)
        outer.set_margin_bottom(24)
        outer.set_margin_start(18)
        outer.set_margin_end(18)

        live_card, live = _card(
            "Live",
            "Sampled in the background every couple of seconds: latency to the "
            "panel target and this computer's throughput.",
        )
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._live_ping = StatTile("Ping", "devnet-clock-symbolic", "—", "muted")
        self._live_down = StatTile("Down", "devnet-down-symbolic", "0 B/s", "blue")
        self._live_up = StatTile("Up", "devnet-up-symbolic", "0 B/s", "orange")
        for tile in (self._live_ping, self._live_down, self._live_up):
            stats.append(tile)
        live.append(stats)
        self._live_route = label("", "devn-card-subtitle", 0.5)
        self._live_route.set_visible(False)
        live.append(self._live_route)
        outer.append(live_card)

        test_card, test = _card(
            "Cloudflare Speed Test",
            "Measures the path your traffic takes right now — through the VPN or "
            "direct, whichever the routing table says.",
        )
        result_stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._down_tile = StatTile("Download", "devnet-down-symbolic", "—", "blue")
        self._up_tile = StatTile("Upload", "devnet-up-symbolic", "—", "orange")
        self._ping_tile = StatTile("Ping", "devnet-clock-symbolic", "—", "muted")
        for tile in (self._down_tile, self._up_tile, self._ping_tile):
            result_stats.append(tile)
        test.append(result_stats)

        self._chart = _chart()
        test.append(self._chart)

        self._progress = Gtk.ProgressBar()
        self._progress.add_css_class("devn-progress")
        self._progress.set_visible(False)
        test.append(self._progress)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.CENTER)
        self._start_button = suggested_button("Start Test", "devnet-play-symbolic", self._toggle_test)
        self._start_button.set_size_request(220, -1)
        actions.append(self._start_button)
        test.append(actions)
        self._error = label("", "devn-error", 0.5)
        self._error.set_wrap(True)
        self._error.set_visible(False)
        test.append(self._error)
        outer.append(test_card)

        targets_card, targets = _card(
            "Ping Targets",
            "Each enabled target is pinged in turn. Use the broadcast icon to show "
            "that target's latency in the panel.",
        )
        self._targets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        targets.append(self._targets_box)
        outer.append(targets_card)

        self._connection_card, connection = _card("Connection")
        self._connection_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        connection.append(self._connection_rows)
        self._connection_card.set_visible(False)
        outer.append(self._connection_card)

        history_card, history = _card(
            "History",
            "The last 30 tests are kept on this computer.",
        )
        self._history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        history.append(self._history_box)
        outer.append(history_card)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(CARD_MAX_WIDTH)
        clamp.set_tightening_threshold(CARD_MAX_WIDTH)
        clamp.set_child(outer)
        clamp.set_vexpand(True)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(clamp)
        scroller.set_vexpand(True)
        self.append(scroller)

        self._unsubscribe = store.subscribe(self._schedule_render)
        self._render()

    # -- toolbar ----------------------------------------------------------
    def _more_button(self) -> Gtk.MenuButton:
        menu = Gtk.MenuButton()
        menu.set_icon_name("devnet-more-symbolic")
        menu.set_tooltip_text("More")
        menu.add_css_class("flat")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        clear = Gtk.Button(label="Clear History")
        clear.add_css_class("flat")
        clear.set_halign(Gtk.Align.FILL)
        clear.set_sensitive(bool(self.store.history))
        clear.connect("clicked", lambda _b: (popover.popdown(), self.store.clear_history()))
        box.append(clear)
        popover.set_child(box)
        menu.set_popover(popover)
        return menu

    def _units_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        if self._updating:
            return
        self.store.set_use_bytes(dropdown.get_selected() == 1)

    def _toggle_test(self) -> None:
        if self.store.running:
            self.store.stop()
        else:
            self.store.start()

    # -- rendering --------------------------------------------------------
    def _schedule_render(self) -> None:
        if self._render_source is not None:
            return
        self._render_source = GLib.idle_add(self._render)

    def _render(self) -> bool:
        self._render_source = None
        store = self.store
        self._updating = True
        try:
            self._sync_toolbar()
            self._sync_live()
            self._sync_result()
            self._sync_targets()
            self._sync_connection()
            self._sync_history()
        finally:
            self._updating = False
        return False

    def _sync_toolbar(self) -> None:
        store = self.store
        self._test_button.set_icon_name(
            "devnet-stop-symbolic" if store.running else "devnet-speed-symbolic"
        )
        self._test_button.set_tooltip_text("Stop the speed test" if store.running else "Test download and upload speed")
        selected = 1 if store.use_bytes else 0
        if self._units.get_selected() != selected:
            self._units.set_selected(selected)
        child = self._start_button.get_child()
        if isinstance(child, Gtk.Box):
            image = child.get_first_child()
            if isinstance(image, Gtk.Image):
                image.set_from_icon_name(
                    "devnet-stop-symbolic" if store.running else "devnet-play-symbolic"
                )
            text = image.get_next_sibling() if image is not None else None
            if isinstance(text, Gtk.Label):
                text.set_text("Stop Test" if store.running else "Start Test")
        if store.running:
            self._start_button.add_css_class("destructive-action")
            self._start_button.remove_css_class("suggested-action")
        else:
            self._start_button.remove_css_class("destructive-action")
            self._start_button.add_css_class("suggested-action")
        self._progress.set_visible(store.running)
        self._progress.set_fraction(store.progress)

    def _sync_live(self) -> None:
        store = self.store
        ping = "—" if store.live_ping is None else f"{store.live_ping} ms"
        self._live_ping.set_value(ping)
        self._live_down.set_value(format_speed(store.activity_down, store.use_bytes))
        self._live_up.set_value(format_speed(store.activity_up, store.use_bytes))
        route = ""
        if store.live_iface:
            route = f"{store.live_host_name} → {store.live_iface}"
        elif store.live_host_name:
            route = store.live_host_name
        self._live_route.set_text(route)
        self._live_route.set_visible(bool(route))

    def _sync_result(self) -> None:
        store = self.store
        if store.phase == "download":
            down = format_speed(store.live, store.use_bytes)
        else:
            down = format_speed(store.result.down, store.use_bytes) if store.result else "—"
        if store.phase == "upload":
            up = format_speed(store.live, store.use_bytes)
        else:
            up = format_speed(store.result.up, store.use_bytes) if store.result else "—"
        if store.phase == "ping":
            ping = "…"
        elif store.result:
            ping = f"{store.result.ping} ms"
        else:
            ping = "—"
        self._down_tile.set_value(down)
        self._up_tile.set_value(up)
        self._ping_tile.set_value(ping)

        samples = [(sample.t, sample.phase, sample.value) for sample in store.samples]
        self._chart.set_samples(samples, store.running)

        self._error.set_text(store.error or "")
        self._error.set_visible(bool(store.error))

        if store.running:
            phases = {"ping": "Measuring latency…", "download": "Testing download…", "upload": "Testing upload…"}
            self.subtitle = phases.get(store.phase, "Testing…")
        elif store.result:
            self.subtitle = (
                f"↓ {format_speed(store.result.down, store.use_bytes)} · "
                f"↑ {format_speed(store.result.up, store.use_bytes)}"
            )
        else:
            self.subtitle = "Not tested yet"

    # -- targets ----------------------------------------------------------
    def _sync_targets(self) -> None:
        signature = tuple(
            (target.id, target.name, target.host, target.enabled, self.store.menu_host_id)
            for target in self.store.targets
        ) + tuple(
            (target_id, stat.ping, stat.iface)
            for target_id, stat in sorted(self.store.target_stats.items())
        )
        if signature == self._target_signature:
            return
        self._target_signature = signature
        _clear(self._targets_box)
        if not self.store.targets:
            self._targets_box.append(
                label("No targets yet. Click + to add one.", "devn-row-subtitle")
            )
            return
        for index, target in enumerate(self.store.targets):
            self._targets_box.append(self._target_row(index, target))

    def _target_row(self, index: int, target: PingTarget) -> Gtk.Box:
        store = self.store
        stat = store.target_stats.get(target.id)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("devn-row")
        row.set_valign(Gtk.Align.CENTER)

        show = Gtk.Button.new_from_icon_name("devnet-radio-symbolic")
        show.add_css_class("flat")
        show.set_tooltip_text("Show this target's latency in the panel")
        show.set_sensitive(target.enabled)
        if target.id == store.menu_host_id:
            show.add_css_class("accent")
        else:
            show.add_css_class("dim-label")
        show.connect("clicked", lambda _b, t=target: store.set_menu_host(t))
        row.append(show)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        name = label(target.name, "devn-row-title")
        detail = target.host
        if stat is not None and stat.iface:
            detail += f" · via {stat.iface}"
        subtitle = label(detail, "devn-row-subtitle devn-mono")
        texts.append(name)
        texts.append(subtitle)
        row.append(texts)

        if target.enabled:
            if stat is None:
                value, css = "…", "dim-label"
            elif stat.ping is None:
                value, css = "timeout", "devn-error"
            else:
                value, css = f"{stat.ping} ms", "devn-mono"
            row.append(label(value, "devn-mono " + css, 1.0))
        else:
            row.append(label("off", "devn-row-subtitle", 1.0))

        menu = Gtk.MenuButton()
        menu.set_icon_name("devnet-more-symbolic")
        menu.add_css_class("flat")
        menu.set_tooltip_text("More actions")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        def item(text: str, icon: str, callback, sensitive: bool = True) -> None:
            widget = Gtk.Button()
            widget.add_css_class("flat")
            widget.set_halign(Gtk.Align.FILL)
            widget.set_sensitive(sensitive)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.append(Gtk.Image.new_from_icon_name(icon))
            content.append(label(text))
            widget.set_child(content)
            widget.connect("clicked", lambda _b: (popover.popdown(), callback()))
            box.append(widget)

        item("Edit…", "devnet-edit-symbolic", lambda i=index: self._edit_target(i))
        item(
            "Show in Panel",
            "devnet-radio-symbolic",
            lambda t=target: store.set_menu_host(t),
            target.enabled,
        )
        item("Copy Host", "devnet-copy-symbolic", lambda t=target: clipboard_text(t.host))
        box.append(Gtk.Separator())
        item("Delete", "devnet-trash-symbolic", lambda t=target: store.remove_target(t))
        popover.set_child(box)
        menu.set_popover(popover)
        row.append(menu)

        switch = Gtk.Switch()
        switch.set_active(target.enabled)
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect(
            "state-set",
            lambda _s, state, t=target: (store.set_target(t, state), False)[1]
            if not self._updating
            else False,
        )
        row.append(switch)
        return row

    # -- connection / history --------------------------------------------
    def _sync_connection(self) -> None:
        meta = self.store.meta
        if meta is None:
            self._connection_card.set_visible(False)
            return
        signature = (meta.client_ip, meta.organization, meta.colo, meta.city, meta.country)
        if signature == self._meta_signature:
            return
        self._meta_signature = signature
        _clear(self._connection_rows)
        rows = [("Your IP", meta.client_ip or "—")]
        if meta.organization:
            rows.append(("Network", meta.organization))
        server = "Cloudflare" + (f" — {meta.colo}" if meta.colo else "")
        rows.append(("Server", server))
        location = ", ".join(part for part in (meta.city, meta.country) if part)
        if location:
            rows.append(("Location", location))
        if meta.protocol:
            rows.append(("Protocol", meta.protocol))
        for title, value in rows:
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            line.append(label(title, "devn-row-subtitle"))
            widget = label(value, "devn-mono", 1.0)
            widget.set_halign(Gtk.Align.END)
            widget.set_selectable(True)
            line.append(widget)
            self._connection_rows.append(line)
        self._connection_card.set_visible(True)

    def _sync_history(self) -> None:
        signature = tuple(result.id for result in self.store.history)
        if signature == self._history_signature:
            return
        self._history_signature = signature
        _clear(self._history_box)
        if not self.store.history:
            self._history_box.append(label("No tests yet.", "devn-row-subtitle"))
            return
        for result in self.store.history:
            self._history_box.append(self._history_row(result))

    def _history_row(self, result: SpeedResult) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("devn-row")
        when = result.when
        if when.year <= 1970:
            stamp = result.date
        elif when.date() == dt.date.today():
            stamp = when.strftime("Today %H:%M")
        else:
            stamp = when.strftime("%b %d, %H:%M")
        row.append(label(stamp, "devn-row-subtitle"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.append(spacer)
        row.append(label(f"↓ {format_speed(result.down, self.store.use_bytes)}", "devn-mono blue"))
        row.append(label(f"↑ {format_speed(result.up, self.store.use_bytes)}", "devn-mono orange"))
        row.append(label(f"{result.ping} ms", "devn-mono dim-label"))
        copy = Gtk.Button.new_from_icon_name("devnet-copy-symbolic")
        copy.add_css_class("flat")
        copy.set_tooltip_text("Copy result")
        copy.connect(
            "clicked",
            lambda _b, r=result: clipboard_text(
                f"↓ {format_speed(r.down, self.store.use_bytes)} · "
                f"↑ {format_speed(r.up, self.store.use_bytes)} · {r.ping} ms"
            ),
        )
        row.append(copy)
        return row

    # -- actions ----------------------------------------------------------
    def _edit_target(self, index: Optional[int]) -> None:
        target = self.store.targets[index] if index is not None else None
        fields = [
            ("Name", target.name if target else "", "Cloudflare"),
            ("Host", target.host if target else "", "1.1.1.1 or example.com"),
        ]

        def submit(values: List[str]) -> Optional[str]:
            return self.store.upsert_target(index, values[0], values[1])

        dialog = FormDialog(
            self.get_root(),
            "Edit Ping Target" if index is not None else "New Ping Target",
            fields,
            "Save" if index is not None else "Add",
            submit,
            destructive_label="Delete Target" if index is not None and target is not None else None,
            on_destructive=(
                lambda: self.store.remove_target(self.store.targets[index])
                if index is not None and target is not None
                else None
            ),
        )
        dialog.present()
        dialog.focus_first()

    # -- lifecycle --------------------------------------------------------
    def on_show(self) -> None:
        self.store.fetch_meta()
        self.store.poke()
        self._schedule_render()

    def on_hide(self) -> None:
        pass


def _chart():
    from .widgets import SpeedChart

    chart = SpeedChart()
    chart.set_content_height(130)
    return chart


__all__ = ["SpeedView"]
