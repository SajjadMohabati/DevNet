"""A pure Gio StatusNotifierItem tray icon with a DBusMenu.

No GTK3, libappindicator or extra Python module is needed.  The icon publishes
``org.kde.StatusNotifierItem`` and ``com.canonical.dbusmenu`` on the session bus,
which is what GNOME (with the AppIndicator extension), KDE, Xfce, Cinnamon,
Budgie and most other panels understand.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"
RETRY_INTERVAL = 4
MAX_RETRIES = 15
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="NewMenu"/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
  </interface>
</node>
"""


@dataclass
class MenuItem:
    id: int
    label: str = ""
    enabled: bool = True
    visible: bool = True
    kind: str = "standard"          # standard | separator | submenu
    children: List["MenuItem"] = field(default_factory=list)
    action: Optional[Callable[[], None]] = None
    toggle: Optional[bool] = None    # True/False renders a checkmark item

    def properties(self) -> Dict[str, GLib.Variant]:
        props: Dict[str, GLib.Variant] = {
            "enabled": GLib.Variant("b", self.enabled),
            "visible": GLib.Variant("b", self.visible),
        }
        if self.kind == "separator":
            props["type"] = GLib.Variant("s", "separator")
            return props
        props["label"] = GLib.Variant("s", self.label)
        if self.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        if self.toggle is not None:
            props["toggle-type"] = GLib.Variant("s", "checkmark")
            props["toggle-state"] = GLib.Variant("i", 1 if self.toggle else 0)
        return props


class TrayIcon:
    """Owns the bus name, objects, menu and watcher registration."""

    def __init__(
        self,
        *,
        on_activate: Callable[[], None],
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
        on_routes: Callable[[bool], None],
        on_route: Callable[[str, bool], None],
        on_dns: Callable[[List[str]], None],
        on_speed: Callable[[], None],
        menu_state: Callable[[], dict],
    ) -> None:
        self.on_activate = on_activate
        self.on_open = on_open
        self.on_quit = on_quit
        self.on_routes = on_routes
        self.on_route = on_route
        self.on_dns = on_dns
        self.on_speed = on_speed
        self.menu_state = menu_state

        self.connection: Optional[Gio.DBusConnection] = None
        self.service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._owner_id = 0
        self._registered = False
        self._retry_source: Optional[int] = None
        self._retries = 0
        self._icon_name = "network-wired-symbolic"
        self._revision = 1
        self._root = MenuItem(0, kind="submenu")
        self._items: Dict[int, MenuItem] = {}
        self._subscription = 0

    # -- lifecycle --------------------------------------------------------
    def start(self) -> bool:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as exc:
            log.info("no session bus, tray icon disabled: %s", exc)
            return False
        if self.connection is None:
            return False
        try:
            self.connection.register_object(
                ITEM_PATH, _parse(ITEM_XML), self._item_call, self._item_property, None
            )
            self.connection.register_object(
                MENU_PATH, _parse(MENU_XML), self._menu_call, self._menu_property, None
            )
        except GLib.Error as exc:
            log.warning("could not export tray objects: %s", exc)
            return False

        self._owner_id = Gio.bus_own_name_on_connection(
            self.connection,
            self.service,
            Gio.BusNameOwnerFlags.NONE,
            self._name_acquired,
            None,
        )
        self._subscription = self.connection.signal_subscribe(
            "org.freedesktop.DBus",
            "org.freedesktop.DBus",
            "NameOwnerChanged",
            "/org/freedesktop/DBus",
            WATCHER,
            Gio.DBusSignalFlags.NONE,
            self._watcher_changed,
        )
        self._schedule_registration()
        return True

    def stop(self) -> None:
        if self._retry_source is not None:
            try:
                GLib.source_remove(self._retry_source)
            except Exception:
                pass
            self._retry_source = None
        if self.connection is not None:
            if self._subscription:
                self.connection.signal_unsubscribe(self._subscription)
                self._subscription = 0
            try:
                self.connection.call_sync(
                    WATCHER,
                    WATCHER_PATH,
                    WATCHER,
                    "UnregisterStatusNotifierItem",
                    GLib.Variant("(s)", (self.service,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    800,
                    None,
                )
            except GLib.Error:
                pass
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        self.connection = None

    # -- state ------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        icon = "network-vpn-symbolic" if active else "network-wired-symbolic"
        if icon == self._icon_name:
            return
        self._icon_name = icon
        if self.connection is not None:
            self.connection.emit_signal(None, ITEM_PATH, ITEM_IFACE, "NewIcon", None)

    def refresh_menu(self) -> None:
        if self.connection is None:
            return
        self._revision += 1
        self.connection.emit_signal(
            None, MENU_PATH, MENU_IFACE, "LayoutUpdated",
            GLib.Variant("(ui)", (self._revision, 0)),
        )

    # -- watcher ----------------------------------------------------------
    def _name_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._registered = False
        self._retries = 0
        self._register_with_watcher()

    def _watcher_changed(self, _conn, _sender, _path, _iface, _signal, params, _data) -> None:
        try:
            _name, _old, new = params.unpack()
        except (ValueError, TypeError):
            return
        if new:
            self._registered = False
            self._retries = 0
            self._register_with_watcher()

    def _schedule_registration(self) -> None:
        if self._registered or self.connection is None:
            return
        if self._retries >= MAX_RETRIES:
            return
        if self._retry_source is not None:
            return
        self._retry_source = GLib.timeout_add_seconds(RETRY_INTERVAL, self._retry_register)

    def _retry_register(self) -> bool:
        self._retry_source = None
        if self._registered or self.connection is None:
            return False
        if self._retries >= MAX_RETRIES:
            return False
        self._retries += 1
        self._register_with_watcher()
        if not self._registered and self._retries >= MAX_RETRIES:
            log.info("status notifier watcher unavailable; gave up after %d attempts", self._retries)
        return False

    def _register_with_watcher(self) -> None:
        if self.connection is None:
            return
        try:
            result = self.connection.call_sync(
                WATCHER,
                WATCHER_PATH,
                WATCHER,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.service,)),
                None,
                Gio.DBusCallFlags.NONE,
                1200,
                None,
            )
            self._registered = result is not None
            if self._registered:
                log.info("registered tray icon with %s", WATCHER)
        except GLib.Error as exc:
            self._registered = False
            log.debug("status notifier watcher unavailable: %s", exc)
            self._schedule_registration()

    # -- StatusNotifierItem ----------------------------------------------
    def _item_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        if method == "Activate":
            self.on_activate()
            invocation.return_value(None)
        elif method == "SecondaryActivate":
            self.on_activate()
            invocation.return_value(None)
        elif method == "ContextMenu":
            self.on_activate()
            invocation.return_value(None)
        elif method == "Scroll":
            self.on_activate()
            invocation.return_value(None)
        else:
            invocation.return_value(None)

    def _item_property(self, _conn, _sender, _path, _iface, name) -> GLib.Variant:
        if name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if name == "Id":
            return GLib.Variant("s", "devnet")
        if name == "Title":
            return GLib.Variant("s", "DevNet")
        if name == "Status":
            return GLib.Variant("s", "Active")
        if name == "WindowId":
            return GLib.Variant("i", 0)
        if name == "IconName":
            return GLib.Variant("s", self._icon_name)
        if name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if name == "Menu":
            return GLib.Variant("o", MENU_PATH)
        if name == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("DevNet", [], "Split tunneling and DNS", "DevNet"))
        if name in {"IconPixmap", "OverlayIconPixmap", "AttentionIconPixmap"}:
            return GLib.Variant("a(iiay)", [])
        if name in {"OverlayIconName", "AttentionIconName", "AttentionMovieName"}:
            return GLib.Variant("s", "")
        return GLib.Variant("s", "")

    # -- DBusMenu ---------------------------------------------------------
    def _build_menu(self) -> MenuItem:
        state = self.menu_state() if self.menu_state else {}
        root = MenuItem(0, kind="submenu")
        root.children.append(MenuItem(1, "Open DevNet", action=self.on_open))
        root.children.append(MenuItem(2, "Toggle Panel", action=self.on_activate))

        routes = state.get("routes", [])
        routes_item = MenuItem(3, "Routes", kind="submenu")
        routes_item.children.append(
            MenuItem(
                31,
                "All Routes",
                action=lambda: self.on_routes(not state.get("all_on", False)),
                toggle=bool(state.get("all_on", False)),
            )
        )
        routes_item.children.append(MenuItem(32, kind="separator"))
        if routes:
            for index, (route_id, label, enabled, partial) in enumerate(routes):
                text = label + ("  (partial)" if partial else "")
                routes_item.children.append(
                    MenuItem(
                        300 + index,
                        text,
                        action=lambda rid=route_id, on=not enabled: self.on_route(rid, on),
                        toggle=bool(enabled),
                    )
                )
        else:
            routes_item.children.append(MenuItem(33, "No routes yet", enabled=False))
        root.children.append(routes_item)

        dns_item = MenuItem(4, "DNS", kind="submenu")
        dns_item.children.append(
            MenuItem(40, "Automatic (DHCP)", action=lambda: self.on_dns([]),
                     toggle=not state.get("dns_active", ""))
        )
        dns_item.children.append(MenuItem(41, kind="separator"))
        for index, (name, servers, active) in enumerate(state.get("dns", [])):
            dns_item.children.append(
                MenuItem(
                    400 + index,
                    name,
                    action=lambda values=list(servers): self.on_dns(values),
                    toggle=bool(active),
                )
            )
        root.children.append(dns_item)

        root.children.append(MenuItem(5, "Run Speed Test", action=self.on_speed))
        root.children.append(MenuItem(6, kind="separator"))
        root.children.append(MenuItem(7, "Quit DevNet", action=self.on_quit))
        return root

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        try:
            if method == "GetLayout":
                parent_id, depth, _names = params.unpack()
                root = self._build_menu()
                self._root = root
                self._items = {}
                self._index(root)
                node = self._find(parent_id) or root
                layout = self._layout(node, depth)
                invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, layout)))
            elif method == "GetGroupProperties":
                ids, _names = params.unpack()
                root = self._build_menu()
                self._items = {}
                self._index(root)
                wanted = list(ids) if ids else list(self._items)
                rows = []
                for item_id in wanted:
                    item = self._items.get(item_id)
                    if item is not None:
                        rows.append((item.id, item.properties()))
                invocation.return_value(GLib.Variant("(a(ia{sv}))", (rows,)))
            elif method == "GetProperty":
                item_id, name = params.unpack()
                self._ensure_menu()
                item = self._items.get(item_id)
                value = item.properties().get(name) if item else None
                invocation.return_value(GLib.Variant("(v)", (value or GLib.Variant("s", ""),)))
            elif method == "Event":
                item_id, event_id, _data, _timestamp = params.unpack()
                if event_id == "clicked":
                    self._ensure_menu()
                    item = self._items.get(item_id)
                    if item is not None and item.action is not None and item.enabled:
                        GLib.idle_add(self._run_action, item.action)
                invocation.return_value(None)
            elif method == "EventGroup":
                events, = params.unpack()
                for item_id, event_id, _data, _timestamp in events:
                    if event_id == "clicked":
                        self._ensure_menu()
                        item = self._items.get(item_id)
                        if item is not None and item.action is not None and item.enabled:
                            GLib.idle_add(self._run_action, item.action)
                invocation.return_value(GLib.Variant("(ai)", ([],)))
            elif method == "AboutToShow":
                invocation.return_value(GLib.Variant("(b)", (True,)))
            elif method == "AboutToShowGroup":
                ids, = params.unpack()
                invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            else:
                invocation.return_value(None)
        except Exception:
            log.exception("DBusMenu call %s failed", method)
            invocation.return_value(None)

    def _menu_property(self, _conn, _sender, _path, _iface, name) -> GLib.Variant:
        if name == "Version":
            return GLib.Variant("u", 3)
        if name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if name == "Status":
            return GLib.Variant("s", "normal")
        if name == "IconThemePath":
            return GLib.Variant("as", [])
        return GLib.Variant("s", "")

    # -- menu helpers -----------------------------------------------------
    def _ensure_menu(self) -> None:
        if not self._items:
            self._root = self._build_menu()
            self._items = {}
            self._index(self._root)

    def _index(self, item: MenuItem) -> None:
        self._items[item.id] = item
        for child in item.children:
            self._index(child)

    def _find(self, item_id: int) -> Optional[MenuItem]:
        return self._items.get(item_id)

    def _layout(self, item: MenuItem, depth: int) -> tuple:
        children = []
        if depth != 0:
            for child in item.children:
                if not child.visible:
                    continue
                if child.kind == "separator":
                    nested: tuple = (child.id, child.properties(), [])
                elif depth < 0 or depth > 1:
                    nested = self._layout(child, depth - 1 if depth > 0 else -1)
                else:
                    nested = (child.id, child.properties(), [])
                children.append(GLib.Variant("v", GLib.Variant("(ia{sv}av)", nested)))
        return (item.id, item.properties(), children)

    @staticmethod
    def _run_action(action: Callable[[], None]) -> bool:
        try:
            action()
        except Exception:
            log.exception("tray action failed")
        return False


def _parse(xml: str):
    info = Gio.DBusNodeInfo.new_for_xml(xml)
    return info.interfaces[0]


__all__ = ["MenuItem", "TrayIcon"]
