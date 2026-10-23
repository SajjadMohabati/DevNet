"""Test package initialization with PyGObject fallback for environments without GTK."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

try:
    import gi
except ModuleNotFoundError:
    class MockVariant:
        def __init__(self, sig, val):
            self.sig = sig
            self.val = val

        def unpack(self):
            return self.val

    mock_glib = MagicMock()
    mock_glib.SOURCE_REMOVE = False
    mock_glib.SOURCE_CONTINUE = True
    mock_glib.Variant = MockVariant
    mock_glib.Error = type("Error", (Exception,), {})

    mock_gi = MagicMock()
    mock_gi_repo = MagicMock()
    mock_gi_repo.GLib = mock_glib
    mock_gi_repo.Gio = MagicMock()
    mock_gi_repo.Gtk = MagicMock()
    mock_gi_repo.Gdk = MagicMock()
    mock_gi_repo.Adw = MagicMock()

    sys.modules["gi"] = mock_gi
    sys.modules["gi.repository"] = mock_gi_repo
    sys.modules["gi.repository.GLib"] = mock_glib
    sys.modules["gi.repository.Gio"] = mock_gi_repo.Gio
    sys.modules["gi.repository.Gtk"] = mock_gi_repo.Gtk
    sys.modules["gi.repository.Gdk"] = mock_gi_repo.Gdk
    sys.modules["gi.repository.Adw"] = mock_gi_repo.Adw
