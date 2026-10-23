<div align="center">

<img src="docs/icon.png" width="128" alt="DevNet app icon — split tunneling for macOS and Linux">

# DevNet — Split Tunneling & VPN Bypass for macOS and Linux

**Route networks, domains and entire countries around your VPN — from the menu bar or the system tray.**<br>
One-click DNS switching (Shecan, Shecan Pro, Electro, 403, Cloudflare…), a Cloudflare speed test and a dev-server manager.<br>
Native SwiftUI on macOS · Native GTK4 + libadwaita on Linux · Free & open source · No account, no telemetry

[![Download for macOS](https://img.shields.io/badge/macOS-Download%20DMG-0A84FF?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)
[![Download .deb](https://img.shields.io/badge/Ubuntu%20%2F%20Debian-.deb-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest)
[![Download .rpm](https://img.shields.io/badge/Fedora%20%2F%20RHEL-.rpm-51A2DA?style=for-the-badge&logo=fedora&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest)

[![Latest release](https://img.shields.io/github/v/release/SajjadMohabati/DevNet?style=flat-square&color=0A84FF)](https://github.com/SajjadMohabati/DevNet/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/SajjadMohabati/DevNet/total?style=flat-square&color=34C759)](https://github.com/SajjadMohabati/DevNet/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-34C759?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/SajjadMohabati/DevNet?style=flat-square&color=FFD60A)](https://github.com/SajjadMohabati/DevNet/stargazers)

**English** · [فارسی](README.fa.md) · [العربية](README.ar.md)

<img src="docs/hero.png" alt="DevNet panel: local, ISP and per-VPN public IPs, route toggles, DNS presets, live speed and running dev servers">

</div>

---

## Why DevNet?

You're on a VPN. Your company intranet, university portal, bank, a local staging server or every site in your own
country **refuses to work through it**: 403 errors, timeouts, captchas, slow everything. Your VPN client either has no
split tunneling, only "per app" rules, or one hard-coded list you can't edit.

So you end up pasting `sudo route add …` or `sudo ip route add …` into a terminal, getting `File exists`, losing it all
on the next Wi-Fi change, and never really knowing which IP a site sees.

**DevNet fixes that in one click.** It's a small native app that keeps a set of routes on your LAN gateway, outside
every VPN, and keeps them correct as networks and VPNs come and go. Same features, same layout, on **macOS and Linux**.

## Features

### 🔀 Split tunneling that works with *any* VPN
- **Networks** (`10.20.0.0/16`), **single hosts**, **domains** (`intranet.example.com`, or a full URL; DevNet resolves
  it) and **whole countries** (e.g. every Iranian IP range, ~1,700 CIDRs) bypass the VPN.
- Works alongside **WireGuard, OpenVPN, L2TP/IPsec, IKEv2, ProtonVPN, v2ray / Xray / sing-box in TUN mode** and others.
  DevNet edits the system routing table, so it doesn't care which client you use or how many are connected.
- **Self-healing:** each route stores what you *want*; DevNet reconciles the live table to it. Rapid clicks, network
  changes and partial failures all converge. No more `File exists` or half-applied lists.
- **Follows your network:** the LAN gateway is detected automatically and re-checked. Move from home Wi-Fi to the office
  and your routes move to the new router.
- Route deletes are always pinned to the gateway and interface they were added on, so DevNet never removes a route that
  belongs to your VPN.

### 🌐 Every IP at a glance, even with several VPNs at once
- **Local IP**, your real **ISP IP** (bypassing all tunnels), the IP **your routed sites see**, and **one line per
  connected VPN** with its own public IP and interface (`utun4 · default`, `wg0`, `ppp0`…).
- Copy any of them with one click.

### 🧭 DNS switching that actually takes effect under a VPN
- Presets for **Shecan (free & Pro), Electro, Begzar, 403, Radar Game, Google, Cloudflare**, plus your own.
- Most DNS changers only set Wi-Fi DNS and silently lose to the DNS your VPN pushes. DevNet applies the preset **to every
  active link, VPN links included**, and restores the originals when you go back to Automatic.
- On Linux it speaks **systemd-resolved**, **NetworkManager** or a plain `/etc/resolv.conf`, whichever your distro uses.
- Shows the resolver the system is *really* using, a latency test for each preset, and one-click cache flush.

### ⚡️ Speed test & live latency
- One-click **Cloudflare speed test** (download, upload, ping) with a live graph and history. It measures the path your
  traffic really takes, through the VPN or direct.
- Live throughput and latency to your own ping targets while DevNet is open. Nothing runs while it's hidden.

### 🛠 Dev-server manager
- Lists everything listening on a port, grouped by **project folder** (Node, Bun, Deno, Python, Java/Gradle, Go, Ruby,
  PHP, .NET, Postgres, Redis, nginx…) plus **Docker and Podman containers**.
- Open in VS Code, Cursor, IntelliJ, your file manager or the browser; **stop** with one click, including processes a
  service manager would restart after a plain `kill`.

### ✨ Native on both systems
- **macOS:** SwiftUI, a Control Center–style menu bar panel with Liquid Glass, light & dark mode, global hotkey
  (**⌃⇧I** by default, changeable).
- **Linux:** GTK4 + libadwaita, a tray icon with the same compact panel, automatic light & dark mode, a global shortcut
  on GNOME, and `devnet --panel` to bind on any other desktop.
- **Least privilege:** on macOS one prompt installs a sudoers rule limited to `route add/delete` and DNS; on Linux a tiny
  polkit helper accepts only validated route and DNS operations. Nothing else gets root.
- Small and fast: no Electron, no background daemon, no telemetry, no account. Idle cost is ~0% CPU.

## DevNet vs. the usual options

| | Shell scripts with `route` / `ip route` | VPN client split tunneling | DNS changer apps | **DevNet** |
|---|:-:|:-:|:-:|:-:|
| Works with any VPN, several at once | ⚠️ manual | ❌ its own tunnel only | — | ✅ |
| Route by domain / URL | ❌ | rarely | — | ✅ |
| Route a whole country in one click | ❌ | rarely | — | ✅ |
| Follows Wi-Fi / network changes | ❌ | ✅ | — | ✅ auto-reconcile |
| Shows ISP, routed and per-VPN public IPs | ❌ | ❌ | ❌ | ✅ |
| DNS change wins over VPN-pushed DNS | — | — | ❌ | ✅ |
| Speed test through the real path | ❌ | ❌ | ❌ | ✅ |
| Dev-server & container manager | ❌ | ❌ | ❌ | ✅ |
| Same app on macOS and Linux | ⚠️ | varies | rarely | ✅ |
| No password prompts, least privilege | ❌ | ✅ | ⚠️ | ✅ |
| Native, small, open source, free | ✅ | varies | varies | ✅ |

## Install

### macOS

1. **[Download DevNet.dmg](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)**, open it and
   drag **DevNet** into **Applications**.
2. Open DevNet. It's open source and ad-hoc signed (not notarized), so the first time macOS asks: go to
   **System Settings › Privacy & Security** and click **Open Anyway**, or run:
   ```bash
   xattr -dr com.apple.quarantine /Applications/DevNet.app
   ```
3. Click the menu bar icon (or press **⌃⇧I**). In the DevNet window, click **Enable Passwordless Mode** once.

Requires macOS 26 Tahoe or later, Apple silicon or Intel.

### Linux

Download the package for your distribution from the
**[latest release](https://github.com/SajjadMohabati/DevNet/releases/latest)**, then:

```bash
# Debian 12+ / Ubuntu 22.10+ / Linux Mint / Pop!_OS
sudo apt install ./devnet_1.3.0_all.deb

# Fedora 37+ / RHEL 9 (EPEL) / Rocky / AlmaLinux
sudo dnf install ./devnet-1.3.0-1.noarch.rpm
```

Launch **DevNet** from your app menu, or run `devnet`. On GNOME, enable the
**AppIndicator and KStatusNotifierItem Support** extension to see the tray icon; everything else works without it.

Or install from source:

```bash
git clone https://github.com/SajjadMohabati/DevNet.git
sudo ./DevNet/linux/install.sh   # or ./DevNet/linux/run.sh to try it without installing
```

See [`linux/README.md`](linux/README.md) ([فارسی](linux/README.fa.md)) for packaging, troubleshooting and the security
model.

### Build the macOS app from source

```bash
git clone https://github.com/SajjadMohabati/DevNet.git
cd DevNet
./build.sh             # universal build, installs to /Applications
sudo ./install.sh      # optional: passwordless mode + DNS helper (same as the in-app button)
./release.sh           # optional: build the styled DMG
```

Needs only the **Xcode Command Line Tools**: no Xcode project, no dependencies.

## How it works

| | macOS | Linux |
|---|---|---|
| Routes | `route(8)` via the LAN gateway; DevNet diffs wanted vs. live and applies only the difference | `ip route` batches through a polkit helper that validates every CIDR, gateway and device |
| VPN detection | `scutil --nc`, `netstat` | `ip` and NetworkManager (`nmcli`) |
| Public IPs | `curl --interface`, once per interface | an HTTPS request bound to each interface's address |
| DNS | `devnet-dns` helper writes each service's DNS state (with a backup) via `scutil` | `resolvectl` (systemd-resolved), `nmcli` (NetworkManager) or `/etc/resolv.conf` |
| Privileges | `/etc/sudoers.d/devnet`, scoped to the commands above | a polkit action for `/usr/libexec/devnet/devnet-helper` only |

Your data is stored locally as plain JSON (`~/Library/Application Support/VPNRoutes/` on macOS, `~/.config/devnet/` on
Linux).

## FAQ

**Is this a VPN?** No. DevNet decides which traffic *skips* your VPN. Use it with the VPN you already have.

**Will it leak my traffic?** Only destinations you add go around the VPN; everything else stays in the tunnel.

**Can I open all Iranian (or any country's) sites outside the VPN?** Yes: *Add › Country IP Ranges…* and enter `ir` (or
any ISO country code). Sites that block foreign IPs with a 403 then keep working while you're connected.

**I use v2rayN / v2rayNG / Hiddify / Nekoray and Iranian sites still see a foreign IP.** Those clients often set a
**system proxy**, and apps that use the proxy (browsers included) send traffic straight to it, so no routing table can
steer it. Turn off the system proxy and use **TUN mode**, or add a `geoip:ir` → direct rule in the client. In TUN mode,
DevNet's routes work normally.

**Does it work on Wayland?** Yes. The Linux app is plain GTK4. The tray icon uses the standard StatusNotifierItem
protocol (KDE, Cinnamon, XFCE, Budgie, and GNOME with the AppIndicator extension).

**What does passwordless mode change on macOS?** It installs one sudoers file allowing `route add/delete`,
`networksetup -setdnsservers`, DNS cache flush and DevNet's DNS helper. Remove it with `sudo ./install.sh --uninstall`.

## Contributing

Issues and pull requests are welcome. If DevNet saves you time, **⭐ star the repo**; it helps others find it.

## Author

Created by **[Sajjad Mohabati](https://github.com/SajjadMohabati)** · [github.com/SajjadMohabati/DevNet](https://github.com/SajjadMohabati/DevNet)

Released under the [MIT License](LICENSE). Linux icons are based on [Lucide](https://lucide.dev) (ISC).

<sub>Keywords: split tunneling for macOS and Linux, VPN bypass, exclude IP from VPN, route domain outside VPN, Ubuntu
split tunnel, Fedora split tunnel, static route manager, ip route GUI, Iran IP ranges, open Iranian sites with VPN on,
Shecan DNS, Shecan Pro, DNS changer for Mac and Linux, systemd-resolved DNS switcher, WireGuard split tunnel, OpenVPN
split tunnel, v2ray TUN split routing, menu bar network tool, system tray network tool, Cloudflare speed test, developer
tools, kill port, local dev server manager.</sub>
