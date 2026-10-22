"""Tray lifecycle tests that do not need a session bus or a display."""

from __future__ import annotations

import unittest
from unittest import mock

from gi.repository import GLib

from devnet.tray import MAX_RETRIES, TrayIcon


def _tray() -> TrayIcon:
    return TrayIcon(
        on_activate=lambda: None,
        on_open=lambda: None,
        on_quit=lambda: None,
        on_routes=lambda _enabled: None,
        on_route=lambda _route, _enabled: None,
        on_dns=lambda _servers: None,
        on_speed=lambda: None,
        menu_state=lambda: {},
    )


class TrayRetryTest(unittest.TestCase):
    def test_gives_up_after_max_retries(self) -> None:
        tray = _tray()
        tray.connection = object()  # type: ignore[assignment]
        calls = 0

        def register() -> None:
            nonlocal calls
            calls += 1
            tray._registered = False

        tray._register_with_watcher = register  # type: ignore[method-assign]
        for _ in range(MAX_RETRIES + 5):
            tray._retry_source = 1
            tray._retry_register()

        self.assertEqual(calls, MAX_RETRIES)
        self.assertEqual(tray._retries, MAX_RETRIES)

        # No new timer is scheduled once the cap is reached.
        tray._retry_source = None
        tray._schedule_registration()
        self.assertIsNone(tray._retry_source)

    def test_watcher_arrival_resets_retry_budget(self) -> None:
        tray = _tray()
        tray._retries = MAX_RETRIES
        tray._registered = False
        tray._register_with_watcher = mock.Mock()  # type: ignore[method-assign]

        tray._watcher_changed(
            None,
            None,
            None,
            None,
            None,
            GLib.Variant("(sss)", ("org.kde.StatusNotifierWatcher", "", ":1.42")),
            None,
        )

        self.assertEqual(tray._retries, 0)
        tray._register_with_watcher.assert_called_once_with()

    def test_owner_change_to_empty_is_ignored(self) -> None:
        tray = _tray()
        tray._retries = 3
        tray._register_with_watcher = mock.Mock()  # type: ignore[method-assign]

        tray._watcher_changed(
            None,
            None,
            None,
            None,
            None,
            GLib.Variant("(sss)", ("org.kde.StatusNotifierWatcher", ":1.42", "")),
            None,
        )

        self.assertEqual(tray._retries, 3)
        tray._register_with_watcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
