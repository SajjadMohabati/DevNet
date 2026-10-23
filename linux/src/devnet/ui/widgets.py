"""Reusable GTK widgets for the DevNet windows.

The visual language intentionally follows Adwaita rather than pretending to be
AppKit: rounded 12 px cards, quiet secondary text, symbolic icons and a
Control-Center-like quick-settings panel.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from ..shell import clipboard_text  # noqa: E402

MODIFIER_MASK = (
    Gdk.ModifierType.CONTROL_MASK
    | Gdk.ModifierType.ALT_MASK
    | Gdk.ModifierType.SHIFT_MASK
    | Gdk.ModifierType.SUPER_MASK
)


def label(text: str, css: Optional[str] = None, xalign: float = 0.0) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.set_xalign(xalign)
    widget.set_ellipsize(Pango.EllipsizeMode.END)
    if css:
        for name in css.split():
            widget.add_css_class(name)
    return widget


def button(icon: Optional[str], tooltip: str, callback: Callable, text: Optional[str] = None) -> Gtk.Button:
    if text is None:
        widget = Gtk.Button.new_from_icon_name(icon or "image-missing-symbolic")
        widget.add_css_class("flat")
    else:
        widget = Gtk.Button()
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if icon:
            content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(label(text))
        widget.set_child(content)
    widget.set_tooltip_text(tooltip)
    widget.connect("clicked", lambda _b: callback())
    return widget


def suggested_button(text: str, icon: Optional[str], callback: Callable) -> Gtk.Button:
    widget = Gtk.Button()
    widget.add_css_class("suggested-action")
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
    content.set_halign(Gtk.Align.CENTER)
    if icon:
        content.append(Gtk.Image.new_from_icon_name(icon))
    content.append(label(text))
    widget.set_child(content)
    widget.connect("clicked", lambda _b: callback())
    return widget


def group(title: Optional[str] = None, description: Optional[str] = None) -> Adw.PreferencesGroup:
    widget = Adw.PreferencesGroup()
    if title:
        widget.set_title(title)
    if description:
        widget.set_description(description)
    return widget


def page() -> Adw.PreferencesPage:
    return Adw.PreferencesPage()


class AppIcon(Gtk.Box):
    """A rounded-square runtime glyph, the Linux version of the macOS AppIcon."""

    def __init__(self, text: Optional[str] = None, icon: Optional[str] = None,
                 color: str = "gray", small: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.add_css_class("devn-app-icon")
        self.add_css_class(color)
        if small:
            self.add_css_class("small")
        self.set_size_request(20 if small else 26, 20 if small else 26)
        if icon:
            image = Gtk.Image.new_from_icon_name(icon)
            image.add_css_class("devn-app-glyph")
            image.set_pixel_size(12 if small else 16)
            # Fill the whole square so GTK draws the glyph dead centre (a vertical Box would top-align it).
            image.set_size_request(20 if small else 26, 20 if small else 26)
            self.append(image)
        else:
            self.append(label(text or "??", None, 0.5))


class Badge(Gtk.Label):
    def __init__(self, text: str = "") -> None:
        super().__init__(label=text)
        self.add_css_class("devn-nav-badge")
        self.set_visible(bool(text))


class StatusDot(Gtk.Box):
    def __init__(self, state: Optional[bool] = None) -> None:
        super().__init__()
        self.set_size_request(7, 7)
        self.set_valign(Gtk.Align.CENTER)
        self.add_css_class("devn-status-dot")
        self.set_state(state)

    def set_state(self, state: Optional[bool]) -> None:
        self.remove_css_class("on")
        self.remove_css_class("off")
        if state is True:
            self.add_css_class("on")
        elif state is False:
            self.add_css_class("off")


class SidebarRow(Gtk.Box):
    def __init__(self, title: str, value: str = "", dot: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("devn-sidebar-row")
        self._dot: Optional[StatusDot] = StatusDot() if dot else None
        if self._dot is not None:
            self.append(self._dot)
        self._title = label(title, "devn-sidebar-row-title")
        self._title.set_hexpand(True)
        self.append(self._title)
        self._value = label(value, "devn-sidebar-row-value", 1.0)
        self._value.set_halign(Gtk.Align.END)
        self.append(self._value)

    def set_value(self, value: str) -> None:
        self._value.set_text(value or "—")

    def set_state(self, state: Optional[bool]) -> None:
        if self._dot is not None:
            self._dot.set_state(state)


class IPLine(Gtk.Box):
    """Icon, label (+ detail), monospaced value and a copy button."""

    def __init__(self, icon: str, title: str, value: str = "", detail: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("devn-ip-row")
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(14)
        image.add_css_class("dim-label")
        self.append(image)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        self._title = label(title, "devn-ip-label")
        texts.append(self._title)
        self._detail = label(detail, "devn-caption")
        self._detail.set_visible(bool(detail))
        texts.append(self._detail)
        self.append(texts)
        self._value = label(value or "—", "devn-ip-value", 1.0)
        self._value.set_halign(Gtk.Align.END)
        self._value.set_selectable(True)
        self._value.set_focusable(False)   # selectable, but don't grab focus and show a caret on open
        self.append(self._value)
        self._copy = Gtk.Button.new_from_icon_name("devnet-copy-symbolic")
        self._copy.add_css_class("devn-ip-copy")
        self._copy.set_tooltip_text(f"Copy {title}")
        self._copy.set_sensitive(bool(value))
        self._copy.connect("clicked", self._copy_value)
        self.append(self._copy)
        self._reset_source: Optional[int] = None

    def set_value(self, value: str) -> None:
        self._value.set_text(value or "—")
        self._copy.set_sensitive(bool(value))

    def set_detail(self, detail: str) -> None:
        self._detail.set_text(detail)
        self._detail.set_visible(bool(detail))

    def _copy_value(self, _button: Gtk.Button) -> None:
        text = self._value.get_text()
        if not text or text == "—":
            return
        clipboard_text(text)
        self._copy.set_icon_name("devnet-check-symbolic")
        if self._reset_source is not None:
            GLib.source_remove(self._reset_source)
        self._reset_source = GLib.timeout_add(1200, self._reset_icon)

    def _reset_icon(self) -> bool:
        self._reset_source = None
        self._copy.set_icon_name("devnet-copy-symbolic")
        return False


class StatTile(Gtk.Box):
    def __init__(self, title: str, icon: str, value: str, color: str = "muted",
                 active: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.set_hexpand(True)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_halign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(12)
        image.add_css_class("dim-label")
        header.append(image)
        header.append(label(title, "devn-stat-title", 0.5))
        self.append(header)
        self._value = label(value, "devn-stat-value " + color, 0.5)
        self._value.set_halign(Gtk.Align.CENTER)
        self.append(self._value)
        self._active = active
        self._color = color

    def set_value(self, value: str) -> None:
        self._value.set_text(value)

    def set_emphasis(self, active: bool) -> None:
        self.set_opacity(1.0 if active or not getattr(self, "_running", False) else 0.45)


class Tile(Gtk.Box):
    """Control-Center-style quick toggle used in the panel."""

    def __init__(self, icon: str, title: str, subtitle: str = "",
                 callback: Optional[Callable] = None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("devn-tile")
        self._callback = callback

        # Primary clickable content
        self._main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._main.set_hexpand(True)
        self._main.set_valign(Gtk.Align.CENTER)

        self._icon = Gtk.Image.new_from_icon_name(icon)
        self._icon.set_pixel_size(14)
        self._icon.add_css_class("devn-tile-icon")
        self._icon.set_size_request(28, 28)
        self._main.append(self._icon)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        texts.set_hexpand(True)
        texts.set_valign(Gtk.Align.CENTER)
        self._title = label(title, "devn-tile-title")
        self._subtitle = label(subtitle, "devn-tile-subtitle")
        texts.append(self._title)
        texts.append(self._subtitle)
        self._main.append(texts)
        self.append(self._main)

        self._accessory = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._accessory.set_valign(Gtk.Align.CENTER)
        self.append(self._accessory)

        if callback is not None:
            gesture = Gtk.GestureClick()
            gesture.connect("released", lambda _g, _n, _x, _y: self._clicked())
            self._main.add_controller(gesture)

    def add_accessory(self, widget: Gtk.Widget) -> None:
        self._accessory.append(widget)

    def set_on(self, on: bool) -> None:
        if on:
            self.add_css_class("on")
        else:
            self.remove_css_class("on")

    def set_title(self, title: str) -> None:
        self._title.set_text(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.set_text(subtitle)

    def _clicked(self) -> None:
        if self._callback:
            self._callback()


class FormDialog(Adw.Window):
    """Small modal form, used for routes, DNS presets and ping targets."""

    def __init__(
        self,
        parent: Optional[Gtk.Window],
        title: str,
        fields: Sequence[Tuple[str, str, str]],
        submit_label: str,
        on_submit: Callable[[List[str]], Optional[str]],
        destructive_label: Optional[str] = None,
        on_destructive: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(transient_for=parent, modal=True, title=title)
        self.set_default_size(430, -1)
        self.set_resizable(False)
        self._on_submit = on_submit
        self._on_destructive = on_destructive
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.set_title_widget(label(title, "title-4", 0.5))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label=submit_label)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda _b: self._submit())
        header.pack_end(save)
        root.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        self._entries: List[Gtk.Entry] = []
        for field_title, value, placeholder in fields:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.append(label(field_title, "caption"))
            entry = Gtk.Entry()
            entry.set_text(value)
            entry.set_placeholder_text(placeholder)
            entry.set_hexpand(True)
            entry.connect("activate", lambda _e: self._submit())
            box.append(entry)
            content.append(box)
            self._entries.append(entry)
        self._error = label("", "devn-error")
        self._error.set_visible(False)
        self._error.set_wrap(True)
        content.append(self._error)
        if destructive_label and on_destructive:
            destructive = Gtk.Button(label=destructive_label)
            destructive.add_css_class("destructive-action")
            destructive.set_halign(Gtk.Align.START)
            destructive.connect("clicked", lambda _b: self._destructive())
            content.append(destructive)
        root.append(content)
        self.set_content(root)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    def focus_first(self) -> None:
        if self._entries:
            self._entries[0].grab_focus()

    def _key(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _submit(self) -> None:
        values = [entry.get_text() for entry in self._entries]
        error = self._on_submit(values)
        if error:
            self._error.set_text(error)
            self._error.set_visible(True)
            return
        self.close()

    def _destructive(self) -> None:
        if self._on_destructive:
            self._on_destructive()
        self.close()


class ShortcutRecorder(Gtk.Button):
    """Key-cap display that records a new GNOME accelerator."""

    def __init__(self, accelerator: str, on_change: Callable[[str], None]) -> None:
        super().__init__()
        self.add_css_class("flat")
        self.set_tooltip_text("Click, then press a shortcut. Escape cancels.")
        self._accelerator = accelerator
        self._on_change = on_change
        self._recording = False
        self._controller: Optional[Gtk.EventControllerKey] = None
        self._box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.set_child(self._box)
        self.connect("clicked", self._toggle)
        self._render()

    def set_accelerator(self, accelerator: str) -> None:
        self._accelerator = accelerator
        if not self._recording:
            self._render()

    def _render(self) -> None:
        while (child := self._box.get_first_child()) is not None:
            self._box.remove(child)
        for part in _pretty_accelerator(self._accelerator):
            cap = label(part, "devn-keycap")
            self._box.append(cap)

    def _toggle(self, _button: Gtk.Button) -> None:
        self._stop() if self._recording else self._start()

    def _start(self) -> None:
        self._recording = True
        while (child := self._box.get_first_child()) is not None:
            self._box.remove(child)
        self._box.append(label("Press keys…", "devn-recording"))
        root = self.get_root()
        if root is not None:
            self._controller = Gtk.EventControllerKey()
            self._controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self._controller.connect("key-pressed", self._key)
            root.add_controller(self._controller)
        self.grab_focus()

    def _stop(self) -> None:
        self._recording = False
        if self._controller is not None:
            root = self.get_root()
            if root is not None:
                root.remove_controller(self._controller)
            self._controller = None
        self._render()

    def _key(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._stop()
            return True
        modifiers = state & MODIFIER_MASK
        if not modifiers & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return True
        name = Gdk.keyval_name(keyval)
        if not name:
            return True
        if len(name) == 1:
            name = name.lower()
        parts: List[str] = []
        if modifiers & Gdk.ModifierType.CONTROL_MASK:
            parts.append("<Control>")
        if modifiers & Gdk.ModifierType.ALT_MASK:
            parts.append("<Alt>")
        if modifiers & Gdk.ModifierType.SHIFT_MASK:
            parts.append("<Shift>")
        if modifiers & Gdk.ModifierType.SUPER_MASK:
            parts.append("<Super>")
        accelerator = "".join(parts) + name
        self._accelerator = accelerator
        self._stop()
        self._on_change(accelerator)
        return True


def _pretty_accelerator(value: str) -> List[str]:
    if not value:
        return ["Set…"]
    parts: List[str] = []
    rest = value
    names = {
        "<Control>": "Ctrl", "<Primary>": "Ctrl", "<Alt>": "Alt",
        "<Shift>": "Shift", "<Super>": "Super", "<Meta>": "Super",
    }
    for token, pretty in names.items():
        if token in rest:
            parts.append(pretty)
            rest = rest.replace(token, "")
    if rest:
        parts.append(rest.upper() if len(rest) == 1 else rest)
    return parts or ["Set…"]


class SpeedChart(Gtk.DrawingArea):
    """Download/upload chart with a smooth Catmull-Rom curve."""

    def __init__(self) -> None:
        super().__init__()
        self.set_content_height(120)
        self.set_hexpand(True)
        self.add_css_class("devn-chart")
        self._samples: List[Tuple[float, str, float]] = []
        self._running = False
        self.set_draw_func(self._draw)

    def set_samples(self, samples: List[Tuple[float, str, float]], running: bool) -> None:
        self._samples = samples
        self._running = running
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        cr.set_line_width(1)
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.18)
        for index in range(1, 4):
            y = height * index / 4
            cr.move_to(8, y)
            cr.line_to(width - 8, y)
            cr.stroke()

        if len(self._samples) < 2:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.5)
            layout = self.create_pango_layout(
                "Run a test to see the graph" if not self._samples else "…"
            )
            layout.set_alignment(Pango.Alignment.CENTER)
            text_w, text_h = layout.get_pixel_size()
            cr.move_to((width - text_w) / 2, (height - text_h) / 2)
            PangoCairo.show_layout(cr, layout)
            return

        max_v = max(1.0, max(sample[2] for sample in self._samples))
        times = [sample[0] for sample in self._samples]
        first_t, last_t = min(times), max(times)
        span = max(0.001, last_t - first_t)
        usable_w = max(1, width - 12)
        usable_h = max(1, height - 8)

        def point(sample: Tuple[float, str, float]) -> Tuple[float, float]:
            x = 6 + (sample[0] - first_t) / span * usable_w
            y = height - 4 - sample[2] / max_v * usable_h
            return x, y

        def curve(points: List[Tuple[float, float]]) -> None:
            if not points:
                return
            cr.move_to(*points[0])
            if len(points) <= 2:
                for px, py in points[1:]:
                    cr.line_to(px, py)
                return
            for index in range(len(points) - 1):
                p0 = points[max(index - 1, 0)]
                p1 = points[index]
                p2 = points[index + 1]
                p3 = points[min(index + 2, len(points) - 1)]
                c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
                c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
                cr.curve_to(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])

        try:
            import cairo  # noqa: F401
            has_cairo = True
        except ImportError:
            has_cairo = False

        def series(phase: str, color: Tuple[float, float, float]) -> Optional[Tuple[float, float]]:
            points = [point(sample) for sample in self._samples if sample[1] == phase]
            if len(points) < 2:
                return None

            # Area fill with smooth vertical gradient
            if has_cairo:
                import cairo
                gradient = cairo.LinearGradient(0, 0, 0, height)
                gradient.add_color_stop_rgba(0.0, color[0], color[1], color[2], 0.25)
                gradient.add_color_stop_rgba(1.0, color[0], color[1], color[2], 0.02)
                cr.set_source(gradient)
            else:
                cr.set_source_rgba(color[0], color[1], color[2], 0.14)

            curve(points)
            cr.line_to(points[-1][0], height)
            cr.line_to(points[0][0], height)
            cr.close_path()
            cr.fill()

            # Smooth curve line
            cr.set_source_rgba(*color, 1.0)
            cr.set_line_width(1.8)
            cr.set_line_join(1)  # cairo.LINE_JOIN_ROUND
            cr.set_line_cap(1)   # cairo.LINE_CAP_ROUND
            curve(points)
            cr.stroke()
            return points[-1]

        down_last = series("download", (0.208, 0.518, 0.894))
        up_last = series("upload", (0.902, 0.380, 0.0))

        # Tip dot matches the active phase color with a glowing halo
        last_point = up_last or down_last
        last_color = (0.902, 0.380, 0.0) if up_last is not None else (0.208, 0.518, 0.894)
        if last_point is not None:
            # Outer glow
            cr.set_source_rgba(last_color[0], last_color[1], last_color[2], 0.30 if self._running else 0.18)
            cr.arc(last_point[0], last_point[1], 6, 0, math.pi * 2)
            cr.fill()
            # Solid tip
            cr.set_source_rgba(last_color[0], last_color[1], last_color[2], 1.0)
            cr.arc(last_point[0], last_point[1], 3, 0, math.pi * 2)
            cr.fill()


class Toast:
    """Tiny inline toast that replaces a label for a moment."""

    def __init__(self, widget: Gtk.Label) -> None:
        self.widget = widget
        self._source: Optional[int] = None

    def show(self, text: str, error: bool = False) -> None:
        self.widget.set_text(text)
        self.widget.set_visible(True)
        if error:
            self.widget.add_css_class("devn-error")
        else:
            self.widget.remove_css_class("devn-error")
        if self._source is not None:
            GLib.source_remove(self._source)
        if not error:
            self._source = GLib.timeout_add(2200, self._clear)

    def _clear(self) -> bool:
        self._source = None
        self.widget.set_visible(False)
        return False


__all__ = [
    "AppIcon",
    "Badge",
    "FormDialog",
    "IPLine",
    "SidebarRow",
    "SpeedChart",
    "StatTile",
    "StatusDot",
    "Tile",
    "Toast",
    "button",
    "group",
    "label",
    "page",
    "suggested_button",
]
