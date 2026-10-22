# DevNet for Linux

A native Linux port of [DevNet](https://github.com/SajjadMohabati/DevNet) — split tunneling,
DNS switching, a speed test and a local dev-server manager in one small GTK4 app.

The Linux app has the same four sections as the macOS app:

| Section | What it does |
|---|---|
| **Routes** | Send networks, hosts, domains, or whole country IP ranges around your VPN. Routes are reconciled automatically when Wi-Fi or a VPN changes. |
| **Projects** | Find processes listening on local ports and Docker/Podman containers, grouped by project folder. Open them in your editor or stop them. |
| **DNS** | Apply Shecan, Shecan Pro, Electro, Begzar, 403, Radar Game, Google, Cloudflare or your own preset to every active link — including VPN links. Restore Automatic at any time. |
| **Speed** | Cloudflare download/upload/ping test with a live graph and history, plus live latency for your own targets. |

The window, compact panel, tray menu and global shortcut match the macOS app's layout and
behaviour. Everything runs locally; there is no account, telemetry, or background daemon.

## Requirements

- Linux with GTK 4 and libadwaita: **Debian 12+**, **Ubuntu 22.10+**, **Fedora 37+**, or
  **RHEL 9** with EPEL. The code targets GTK 4.8 / libadwaita 1.2 APIs.
- Python 3.9+ with PyGObject.
- `iproute2` (`ip`) and `iputils` (`ping`).
- polkit (`pkexec`) for route and DNS changes.
- NetworkManager or systemd-resolved are recommended; a plain `/etc/resolv.conf` is also
  supported.
- On GNOME, the **AppIndicator and KStatusNotifierItem Support** extension is needed for the
  tray icon. The window, panel, shortcut and all features work without it.

Install the runtime packages manually if needed:

```bash
# Debian / Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  iproute2 iputils-ping pkexec desktop-file-utils hicolor-icon-theme

# Fedora / Red Hat
sudo dnf install python3 python3-gobject python3-cairo gtk4 libadwaita iproute iputils polkit \
  desktop-file-utils hicolor-icon-theme
```

## Install

### Debian package

```bash
sudo apt install ./devnet_1.2.0_all.deb
```

### RPM package

```bash
sudo dnf install ./devnet-1.2.0-1.*.noarch.rpm
```

### From this repository

```bash
sudo ./linux/install.sh
```

`install.sh` installs the application, desktop entry, icons, root helper and polkit support.
Use `--no-deps` to skip automatic package installation, or run `./linux/run.sh` to launch
straight from the checkout without installing anything.

The source installer and packages place files in:

| Path | Purpose |
|---|---|
| `/usr/lib/devnet/devnet` | Python application code |
| `/usr/bin/devnet` | Launcher |
| `/usr/libexec/devnet/devnet-helper` | Small privileged helper |
| `/usr/share/applications/org.devnet.App.desktop` | Desktop entry |
| `/usr/share/metainfo/org.devnet.App.metainfo.xml` | AppStream metadata |
| `/usr/share/icons/hicolor/*/apps/org.devnet.App.png` | Application icons |

### First run

```bash
devnet
```

Open **DevNet** from your app grid. Click **Enable Passwordless Mode** in the sidebar once if
you want route and DNS changes without a polkit prompt. The button installs one polkit rule
that allows only `/usr/libexec/devnet/devnet-helper` to run for your user; it does not grant
general root access and is not a sudoers rule.

## Command line

```bash
devnet             # open the main window (default)
devnet --panel     # toggle the compact panel
devnet --background# start hidden in the tray
devnet --version
```

The tray action and the GNOME custom shortcut (`Ctrl+Shift+I` by default) use `--panel`.
Change the shortcut in the window sidebar; DevNet stores it in GNOME's
`org.gnome.settings-daemon.plugins.media-keys` schema.

## How it works

### Routes

The app reads `ip -4 route` and keeps a desired route list in
`~/.local/share/devnet/routes.json`. On every change it diffs the wanted list against the live
table and sends **one** batch of `replace`/`delete` operations to the helper. Domain routes are
resolved to IPv4 addresses before they are applied. Only routes whose gateway is an explicit
IPv4 address are removed when a route is turned off, so interface-only VPN routes are never
touched. The LAN gateway is re-checked every 10 seconds.

### DNS

The helper detects the active backend in this order:

1. **systemd-resolved** — `resolvectl dns <link> …` on every active link, with the original
   per-link list saved first.
2. **NetworkManager** — `nmcli device modify … ipv4.dns …` with the original device DNS saved.
3. **`/etc/resolv.conf`** — a marked `nameserver` block, with the original file backed up as
   base64. A symlinked `resolv.conf` is written through, not replaced.

Backups live in `/var/lib/devnet/dns-backup.json`; the currently applied preset is in
`/var/lib/devnet/dns.json`. **Automatic** restores the backup and flushes the resolver cache.
VPN links are included because changing only Wi-Fi DNS would lose to DNS pushed by a VPN.

### Projects and speed

Projects come from `ss -ltnp`, `/proc/<pid>/cwd` and `systemctl --user`. Docker/Podman
containers are listed when the CLI is available. Speed tests use the same
`speed.cloudflare.com` endpoints as the macOS app and run on a worker thread, so the UI never
blocks.

### Security model

The GUI never runs `ip` or resolver commands as root. It writes a small JSON request to a
private temporary file and calls:

```bash
pkexec /usr/libexec/devnet/devnet-helper <action> <request.json>
```

The helper accepts only fixed actions, validates every field (IPv4, strict CIDR, interface
names, server count, request ownership, size), requires root, serialises calls with `flock`,
and runs commands with a fixed `PATH`. Passwordless mode adds
`/etc/polkit-1/rules.d/50-devnet.rules`, scoped to `org.freedesktop.policykit.exec`, the exact
helper path, and the current user. Removing the package removes that rule.

## Build packages

Build a `.deb` without debhelper or network access:

```bash
./linux/package/deb/build.sh
# output: build/deb/devnet_1.2.0_all.deb
```

Build an RPM (needs `rpm-build`):

```bash
./linux/package/rpm/build.sh
# output: build/rpm/devnet-1.2.0-1.*.noarch.rpm
```

Both scripts read the version from `linux/src/devnet/__init__.py`. Set `VERSION=...` to
override it, and pass `--output DIR` to choose the output directory.

Run the tests and metadata checks:

```bash
PYTHONPATH=linux/src python3 -m unittest discover -s linux/tests -v
python3 -m compileall -q linux/src
desktop-file-validate linux/data/org.devnet.App.desktop
appstreamcli validate --no-net linux/data/org.devnet.App.metainfo.xml
```

The GitHub Actions workflow at `.github/workflows/linux.yml` runs those checks and uploads
both package formats.

## Troubleshooting

**The tray icon is missing on GNOME.** Install the AppIndicator extension. GNOME does not
show StatusNotifierItem icons natively. The shortcut and `devnet --window` still work.

**Every route change asks for a password.** Click **Enable Passwordless Mode**. If it still
prompts, check that the rule exists:

```bash
cat /etc/polkit-1/rules.d/50-devnet.rules
```

and that the helper is executable at `/usr/libexec/devnet/devnet-helper`.

**A DNS preset is not accepted.** Check the active backend:

```bash
resolvectl status
nmcli device show
cat /etc/resolv.conf
```

On systems where `/etc/resolv.conf` is managed by a container runtime or a read-only mount,
use NetworkManager or systemd-resolved instead. **Automatic** restores the saved backup.

**Routes work but sites still use the VPN.** Cached host routes can override a network route;
DevNet removes cached `/32` entries inside an enabled range when their gateway differs. Run
`ip -4 route get <address>` to see the path the kernel actually chooses.

**The global shortcut does nothing.** It is implemented with GNOME's media-key settings. On
KDE, XFCE, or other desktops, use the tray icon or `devnet --panel` and bind that command in
your desktop's own shortcut settings.

**Nothing happens when launching `devnet`.** Run `./linux/run.sh` in a terminal to see the
error. `DEVNET_DEBUG=1 devnet` enables verbose logging.

## Uninstall

```bash
# Debian / Ubuntu
sudo apt remove devnet
sudo apt purge devnet      # also removes /var/lib/devnet

# Fedora / Red Hat
sudo dnf remove devnet

# Source installer
sudo ./linux/install.sh --uninstall
sudo ./linux/install.sh --purge
```

User settings and history stay in `~/.config/devnet` and `~/.local/share/devnet`; remove
those two directories to reset the app completely. On RPM systems, remove
`/var/lib/devnet` manually after uninstalling if you also want to drop the DNS backup.

## Repository layout

```
linux/
├── src/devnet/          Python application (GTK4 + libadwaita)
├── data/                Helper, desktop entry, AppStream metadata, icons
├── package/deb/         Debian control, maintainer scripts, build script
├── package/rpm/         RPM spec and build script
├── tests/               Unit tests for parsers, routes, DNS and the helper
├── bin/devnet           Installed launcher
├── install.sh           Source installer / uninstaller
└── run.sh               Run from a checkout
```

The macOS Swift sources and installer at the repository root are untouched.

## License

MIT — see [LICENSE](../LICENSE).
