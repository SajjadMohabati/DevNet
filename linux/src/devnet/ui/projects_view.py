"""Projects pane: listening dev servers and Docker/Podman containers."""

from __future__ import annotations

from typing import List, Optional

from gi.repository import Adw, GLib, Gtk

from ..processes import Container, DevProcess, ProcStore, editors, open_in
from ..shell import clipboard_text, open_folder, open_uri
from .widgets import AppIcon, button, group, label, page


class ProjectsView(Gtk.Box):
    title = "Projects"
    subtitle = ""

    def __init__(self, store: ProcStore) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.store = store
        self._render_source: Optional[int] = None
        self._timer: Optional[int] = None
        self._updating = False

        self.toolbar_start = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_end = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.toolbar_start.append(self._filter_button())
        self.toolbar_start.append(button("devnet-refresh-symbolic", "Refresh", self.store.refresh))
        self.toolbar_end.append(
            button("devnet-close-symbolic", "Stop all processes", self.store.stop_all)
        )

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_vexpand(True)

        status = Adw.StatusPage()
        status.set_title("No Running Projects")
        status.set_description("Dev servers listening on a port will appear here.")
        status.set_icon_name("devnet-projects-symbolic")
        self._stack.add_named(status, "empty")

        self._page = page()
        self._page.set_vexpand(True)
        self._process_group = group("Processes")
        self._docker_group = group("Docker Containers")
        self._page.add(self._process_group)
        self._page.add(self._docker_group)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._page)
        scroller.set_vexpand(True)
        self._stack.add_named(scroller, "list")
        self.append(self._stack)

        self._rows: List[tuple] = []
        self._unsubscribe = store.subscribe(self._schedule_render)
        self._render()

    # -- toolbar ----------------------------------------------------------
    def _filter_button(self) -> Gtk.MenuButton:
        menu = Gtk.MenuButton()
        menu.set_icon_name("devnet-more-symbolic")
        menu.set_tooltip_text("Filter")
        menu.add_css_class("flat")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        check = Gtk.CheckButton(label="Show system processes")
        check.set_active(self.store.show_all)
        check.connect("toggled", lambda button: self.store.set_show_all(button.get_active()))
        box.append(check)
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
            for row in self._rows:
                parent, widget = row
                parent.remove(widget)
            self._rows = []

            for process in self.store.items:
                row = self._process_row(process)
                self._process_group.add(row)
                self._rows.append((self._process_group, row))
            for container in self.store.containers:
                row = self._container_row(container)
                self._docker_group.add(row)
                self._rows.append((self._docker_group, row))

            self._process_group.set_visible(bool(self.store.items))
            self._docker_group.set_visible(bool(self.store.docker_up and self.store.containers))
            self._stack.set_visible_child_name(
                "list" if (self.store.items or self.store.containers) else "empty"
            )
            self.subtitle = f"{self.store.count} running"
        finally:
            self._updating = False
        return False

    def _process_row(self, process: DevProcess) -> Adw.PreferencesRow:
        row = Adw.ActionRow()
        glyph, color = process.runtime
        row.add_prefix(AppIcon(glyph, None, color))
        row.set_title(process.project)
        row.set_subtitle(process.subtitle)
        row.set_tooltip_text(process.command)
        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        suffix.set_valign(Gtk.Align.CENTER)
        for port in process.ports[:3]:
            link = Gtk.LinkButton.new_with_label(f"http://localhost:{port}", f":{port}")
            link.set_tooltip_text(f"Open http://localhost:{port}")
            link.add_css_class("flat")
            suffix.append(link)
        suffix.append(self._process_menu(process))
        stopping = self.store.is_stopping(process)
        stop = Gtk.Button(label="Force" if stopping else "Stop")
        stop.add_css_class("flat")
        if stopping:
            stop.add_css_class("destructive-action")
        stop.set_tooltip_text("Send SIGKILL" if stopping else "Stop this process")
        stop.connect("clicked", lambda _b, p=process: self.store.stop(p))
        suffix.append(stop)
        row.add_suffix(suffix)
        return row

    def _process_menu(self, process: DevProcess) -> Gtk.MenuButton:
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

        def add(text: str, icon: str, callback) -> None:
            item = Gtk.Button()
            item.add_css_class("flat")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.append(Gtk.Image.new_from_icon_name(icon))
            content.append(label(text))
            item.set_child(content)
            item.connect("clicked", lambda _b: (popover.popdown(), callback()))
            box.append(item)

        if process.has_project:
            for editor in editors():
                add(
                    f"Open in {editor.name}",
                    "devnet-terminal-symbolic",
                    lambda e=editor, p=process: open_in(e, p.cwd),
                )
            add("Show in Files", "devnet-folder-symbolic", lambda p=process: open_folder(p.cwd))
            box.append(Gtk.Separator())
            add("Copy Path", "devnet-copy-symbolic", lambda p=process: clipboard_text(p.cwd))
        add("Copy PID", "devnet-copy-symbolic", lambda p=process: clipboard_text(str(p.pid)))
        for port in process.ports:
            add(
                f"Open localhost:{port}",
                "devnet-dns-symbolic",
                lambda value=port: open_uri(f"http://localhost:{value}"),
            )
        popover.set_child(box)
        menu.set_popover(popover)
        return menu

    def _container_row(self, container: Container) -> Adw.PreferencesRow:
        row = Adw.ActionRow()
        row.add_prefix(AppIcon(None, "devnet-package-bold-symbolic", "blue"))
        row.set_title(container.name)
        row.set_subtitle(f"{container.image} — {container.status}")
        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        suffix.set_valign(Gtk.Align.CENTER)
        for port in container.published_ports[:3]:
            link = Gtk.LinkButton.new_with_label(f"http://localhost:{port}", f":{port}")
            link.add_css_class("flat")
            suffix.append(link)
        stopping = self.store.is_stopping(container)
        stop = Gtk.Button(label="Stopping…" if stopping else "Stop")
        stop.set_sensitive(not stopping)
        stop.add_css_class("flat")
        stop.connect("clicked", lambda _b, c=container: self.store.stop_container(c))
        suffix.append(stop)
        row.add_suffix(suffix)
        return row

    # -- lifecycle --------------------------------------------------------
    def on_show(self) -> None:
        self.store.refresh()
        self._schedule_render()
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(3, self._tick)

    def on_hide(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        self.store.refresh()
        return True


__all__ = ["ProjectsView"]
