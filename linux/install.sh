#!/bin/sh
# DevNet for Linux — source installer for Debian/Ubuntu and Fedora/RHEL.
#
#   sudo ./linux/install.sh              install app + privileged helper
#   sudo ./linux/install.sh --no-deps    skip package-manager dependency install
#   sudo ./linux/install.sh --uninstall  remove app; keep user settings
#   sudo ./linux/install.sh --purge      remove app and system state
#
# The macOS installer is a separate script at the repository root.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/devnet/__init__.py")
HELPER=/usr/libexec/devnet/devnet-helper
RULE=/etc/polkit-1/rules.d/50-devnet.rules

B=$(printf '\033[1m')
D=$(printf '\033[2m')
G=$(printf '\033[32m')
C=$(printf '\033[36m')
R=$(printf '\033[31m')
N=$(printf '\033[0m')

ok() { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
note() { printf '  %s•%s %s\n' "$C" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$R" "$N" "$1" >&2; }
die() { printf '  %s✗ %s%s\n' "$R" "$1" "$N" >&2; exit 1; }

usage() {
  cat <<EOF
DevNet $VERSION for Linux

Usage:
  sudo $0 [--no-deps]        install
  sudo $0 --uninstall        remove the app (user settings are kept)
  sudo $0 --purge            remove the app and system state

Options:
  --no-deps     do not call apt/dnf; fail later if runtime packages are missing
  -h, --help    show this help
EOF
}

MODE=install
DEPS=1
for arg in "$@"; do
  case "$arg" in
    --uninstall) MODE=uninstall ;;
    --purge) MODE=purge ;;
    --no-deps) DEPS=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "Unknown option: $arg" ;;
  esac
done

[ "$(id -u)" = 0 ] || die "Run with sudo: sudo $0"

printf '\n  %s%sDevNet%s %s%s — split tunneling for Linux%s\n' "$B" "$C" "$N" "$D" "$VERSION" "$N"
printf '  %sby Sajjad Mohabati · github.com/SajjadMohabati/DevNet%s\n\n' "$D" "$N"

refresh_caches() {
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
  fi
}

uninstall_files() {
  if [ -x "$HELPER" ]; then
    # Put the resolver back before the helper disappears. If this fails, the
    # backup stays in /var/lib/devnet for a manual recovery.
    "$HELPER" dns-reset >/dev/null 2>&1 || warn "Could not restore automatic DNS."
  fi
  rm -f "$RULE"
  rm -f /usr/bin/devnet
  rm -f /usr/share/applications/org.devnet.App.desktop
  rm -f /usr/share/metainfo/org.devnet.App.metainfo.xml
  for size in 16 24 32 48 64 128 256 512 1024; do
    rm -f "/usr/share/icons/hicolor/${size}x${size}/apps/org.devnet.App.png"
  done
  rm -rf /usr/lib/devnet
  rm -f "$HELPER"
  rmdir /usr/libexec/devnet 2>/dev/null || true
  refresh_caches
}

if [ "$MODE" = uninstall ] || [ "$MODE" = purge ]; then
  uninstall_files
  if [ "$MODE" = purge ]; then
    rm -rf /var/lib/devnet
    ok "Removed app and system state"
  else
    ok "Removed app (user settings were left in ~/.config/devnet and ~/.local/share/devnet)"
  fi
  printf '\n'
  exit 0
fi

install_dependencies() {
  [ "$DEPS" = 1 ] || { note "Skipping dependency installation"; return; }
  if command -v apt-get >/dev/null 2>&1; then
    note "Installing Debian/Ubuntu runtime packages"
    apt-get install -y --no-install-recommends \
      python3 python3-gi python3-gi-cairo \
      gir1.2-gtk-4.0 gir1.2-adw-1 \
      iproute2 iputils-ping \
      desktop-file-utils hicolor-icon-theme \
      pkexec >/dev/null 2>&1 || \
    apt-get install -y --no-install-recommends \
      python3 python3-gi python3-gi-cairo \
      gir1.2-gtk-4.0 gir1.2-adw-1 \
      iproute2 iputils-ping \
      desktop-file-utils hicolor-icon-theme \
      policykit-1 >/dev/null 2>&1 || \
    warn "Some packages could not be installed automatically; see linux/README.md."
  elif command -v dnf >/dev/null 2>&1; then
    note "Installing Fedora/RHEL runtime packages"
    dnf install -y \
      python3 python3-gobject python3-cairo gtk4 libadwaita \
      iproute iputils polkit \
      desktop-file-utils hicolor-icon-theme >/dev/null 2>&1 || \
    warn "Some packages could not be installed automatically; see linux/README.md."
  elif command -v yum >/dev/null 2>&1; then
    note "Installing Red Hat runtime packages"
    yum install -y \
      python3 python3-gobject python3-cairo gtk4 libadwaita \
      iproute iputils polkit \
      desktop-file-utils hicolor-icon-theme >/dev/null 2>&1 || \
    warn "Some packages could not be installed automatically; see linux/README.md."
  else
    note "No apt/dnf/yum found; skipping dependency installation"
  fi
}

check_runtime() {
  command -v python3 >/dev/null 2>&1 || die "python3 is missing."
  python3 - <<'PY' >/dev/null 2>&1 || die "PyGObject, GTK4 or libadwaita is missing (see linux/README.md)."
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
PY
  command -v ip >/dev/null 2>&1 || die "iproute2 is missing."
  command -v pkexec >/dev/null 2>&1 || die "pkexec/polkit is missing."
}

install_dependencies
check_runtime

install -d -m 755 /usr/lib/devnet
rm -rf /usr/lib/devnet/devnet
tar -C "$HERE/src" \
  --exclude='__pycache__' --exclude='*.pyc' \
  -cf - devnet | tar -C /usr/lib/devnet -xf -
chmod -R go-w /usr/lib/devnet/devnet
ok "Application    → /usr/lib/devnet"

install -d -m 755 /usr/bin
install -m 755 "$HERE/bin/devnet" /usr/bin/devnet
ok "Launcher       → /usr/bin/devnet"

install -d -m 755 /usr/libexec/devnet
install -m 755 "$HERE/data/devnet-helper" "$HELPER"
ok "Root helper    → $HELPER"

install -d -m 755 /usr/share/applications
install -m 644 "$HERE/data/org.devnet.App.desktop" /usr/share/applications/
install -d -m 755 /usr/share/metainfo
install -m 644 "$HERE/data/org.devnet.App.metainfo.xml" /usr/share/metainfo/
install -d -m 755 /usr/share/icons/hicolor
for size in 16 24 32 48 64 128 256 512 1024; do
  source="$HERE/data/icons/hicolor/${size}x${size}/apps/org.devnet.App.png"
  if [ -f "$source" ]; then
    install -d -m 755 "/usr/share/icons/hicolor/${size}x${size}/apps"
    install -m 644 "$source" "/usr/share/icons/hicolor/${size}x${size}/apps/org.devnet.App.png"
  fi
done
refresh_caches
ok "Desktop entry, AppStream metadata and icons installed"

printf '\n  %sDone.%s Open DevNet from your app grid, or run %sdevnet%s.\n' "$B" "$N" "$C" "$N"
printf '  %sClick “Enable Passwordless Mode” once in the sidebar for instant route/DNS changes.%s\n' "$D" "$N"
printf '  %sGNOME needs the AppIndicator extension for the tray icon; the shortcut and window work without it.%s\n\n' "$D" "$N"
