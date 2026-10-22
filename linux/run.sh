#!/bin/sh
# Run DevNet straight from a source checkout. No installation is needed for
# the window and panel; route/DNS changes still require the root helper.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  echo "devnet: python3 is required." >&2
  exit 1
fi
if ! python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
PY
then
  cat >&2 <<'MSG'
devnet: GTK4, libadwaita and PyGObject are required.

  Debian / Ubuntu:
    sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1

  Fedora / Red Hat:
    sudo dnf install python3-gobject gtk4 libadwaita
MSG
  exit 1
fi

PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
exec python3 -m devnet "$@"
