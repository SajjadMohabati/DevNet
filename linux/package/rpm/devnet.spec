%global debug_package %{nil}

Name:           devnet
Version:        1.3.0
Release:        1%{?dist}
Summary:        Split tunneling, DNS switching and local dev servers
License:        MIT
URL:            https://github.com/SajjadMohabati/DevNet
Source0:        %{name}-%{version}-linux.tar.gz
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4
Requires:       libadwaita
Requires:       librsvg2
Requires:       iproute
Requires:       iputils
Requires:       polkit
Requires:       desktop-file-utils
Requires:       hicolor-icon-theme
Requires:       glib2
Recommends:     rsms-inter-fonts
Recommends:     NetworkManager
Recommends:     systemd-resolved
Recommends:     iso-codes
Recommends:     gnome-shell-extension-appindicator

%description
DevNet keeps selected networks, hosts, domains and country IP ranges on your
LAN gateway, outside every VPN. It repairs the routes when Wi-Fi or a VPN
changes, switches DNS on every active link (including VPN links), runs a
Cloudflare speed test, and lists local development servers and containers.

The app lives in the system tray, includes a compact panel and a native GTK4
window, and uses a small polkit-scoped helper for privileged operations.

%prep
%setup -q -n %{name}-%{version}-linux

%build
# Python bytecode is compiled on first use.

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_prefix}/lib/devnet
cp -a linux/src/devnet %{buildroot}%{_prefix}/lib/devnet/
find %{buildroot}%{_prefix}/lib/devnet -type d -name __pycache__ -prune -exec rm -rf {} +
find %{buildroot}%{_prefix}/lib/devnet -name '*.py[co]' -delete
chmod -R go-w %{buildroot}%{_prefix}/lib/devnet/devnet

install -d %{buildroot}%{_bindir}
install -m 0755 linux/bin/devnet %{buildroot}%{_bindir}/devnet

install -d %{buildroot}/usr/libexec/devnet
install -m 0755 linux/data/devnet-helper %{buildroot}/usr/libexec/devnet/devnet-helper

install -d %{buildroot}%{_datadir}/applications
install -m 0644 linux/data/org.devnet.App.desktop %{buildroot}%{_datadir}/applications/
install -d %{buildroot}%{_datadir}/metainfo
install -m 0644 linux/data/org.devnet.App.metainfo.xml %{buildroot}%{_datadir}/metainfo/
install -d %{buildroot}%{_datadir}/icons/hicolor
cp -a linux/data/icons/hicolor/. %{buildroot}%{_datadir}/icons/hicolor/

install -d %{buildroot}%{_docdir}/devnet
if [ -f linux/README.md ]; then
    install -m 0644 linux/README.md %{buildroot}%{_docdir}/devnet/README.linux.md
fi

%check
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate %{buildroot}%{_datadir}/applications/org.devnet.App.desktop
fi

%post
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q %{_datadir}/applications >/dev/null 2>&1 || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
fi

%preun
if [ "$1" = 0 ] && [ -x /usr/libexec/devnet/devnet-helper ]; then
    /usr/libexec/devnet/devnet-helper dns-reset >/dev/null 2>&1 || :
fi

%postun
if [ "$1" = 0 ]; then
    rm -f /etc/polkit-1/rules.d/50-devnet.rules
    rmdir /usr/libexec/devnet >/dev/null 2>&1 || :
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q %{_datadir}/applications >/dev/null 2>&1 || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md
%{_docdir}/devnet/README.linux.md
%{_prefix}/lib/devnet
%{_bindir}/devnet
%dir /usr/libexec/devnet
/usr/libexec/devnet/devnet-helper
%{_datadir}/applications/org.devnet.App.desktop
%{_datadir}/metainfo/org.devnet.App.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/org.devnet.App.png

%changelog
* Fri Oct 23 2026 Sajjad Mohabati <sajjadmohabati@users.noreply.github.com> - 1.3.0-1
- Initial native Linux release.
