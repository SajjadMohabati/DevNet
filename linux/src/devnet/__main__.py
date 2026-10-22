"""Command-line entry point: ``python3 -m devnet [--panel|--window|--background]``."""

from __future__ import annotations

import logging
import os
import sys

from . import app_info


def _usage() -> str:
    return f"""Usage: devnet [OPTION]

  --window       Open the main window (default)
  --panel        Toggle the compact panel
  --background   Start hidden in the tray only
  --version      Print the version and exit
  -h, --help     Show this help
"""


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args:
        print(f"{app_info.APP_NAME} {app_info.VERSION}")
        return 0
    if "-h" in args or "--help" in args:
        print(_usage(), end="")
        return 0
    known = {"--window", "--panel", "--background"}
    unknown = [arg for arg in args if arg not in known]
    if unknown:
        print(f"devnet: unknown option: {unknown[0]}", file=sys.stderr)
        print(_usage(), file=sys.stderr, end="")
        return 2

    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEVNET_DEBUG") else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from .application import DevNetApplication

    application = DevNetApplication()
    return application.run([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())
