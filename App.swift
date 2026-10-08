import SwiftUI
import ServiceManagement

// MARK: - Network status

/// A connected VPN / tunnel.
struct Tunnel: Identifiable, Equatable {
    var id: String { iface }
    let name: String        // VPN service name, e.g. "Office L2TP"
    let kind: String        // "L2TP", "WireGuard", …
    let iface: String       // "ppp0", "utun4"
    var publicIP = ""
}

final class NetStore: ObservableObject {
    @Published var defaultIface = ""
    @Published var localIP = ""
    @Published var physicalIface = ""
    @Published var gatewayUp: Bool?
    @Published var directIP = ""    // public IP of the ISP connection, bypassing every VPN
    @Published var routedIP = ""    // public IP seen by Iranian sites (through the routes)
    @Published var tunnels: [Tunnel] = []

    static func isTunnel(_ iface: String) -> Bool { ["utun", "ppp", "ipsec", "tun", "wg"].contains { iface.hasPrefix($0) } }
    var vpn: Bool { !tunnels.isEmpty || Self.isTunnel(defaultIface) }
    /// Public IP seen by foreign sites (whatever carries the default route).
    var vpnIP: String { tunnels.first { $0.iface == defaultIface }?.publicIP ?? (vpn ? "" : directIP) }

    /// Connected VPNs from System Settings (`scutil --nc`), plus a default-route tunnel not listed there.
    static func scanTunnels(defaultIface: String) -> [Tunnel] {
        var list: [Tunnel] = []
        for line in sh("/usr/sbin/scutil", "--nc", "list").split(separator: "\n") where line.contains("(Connected)") {
            let f = line.split(separator: " ", omittingEmptySubsequences: true)
            guard let i = f.firstIndex(where: { $0.hasSuffix(")") }), i + 1 < f.count else { continue }
            let id = String(f[i + 1])
            let name = line.split(separator: "\"").dropFirst().first.map(String.init) ?? id
            let type = line.split(separator: "[").last.map { String($0.dropLast()) } ?? ""   // "PPP:L2TP", "VPN:com.wireguard.macos"
            let sub = String(type.split(separator: ":").last ?? "")
            let kind = sub.contains("wireguard") ? "WireGuard" : sub.contains("proton") ? "ProtonVPN"
                : sub.contains(".") ? String(sub.split(separator: ".").last ?? "").capitalized : sub
            let iface = keyValues(sh("/usr/sbin/scutil", "--nc", "status", id))["InterfaceName"] ?? ""
            if !iface.isEmpty { list.append(Tunnel(name: name, kind: kind, iface: iface)) }
        }
        if isTunnel(defaultIface), !list.contains(where: { $0.iface == defaultIface }) {
            list.append(Tunnel(name: "Tunnel", kind: "", iface: defaultIface))
        }
        // The one carrying the default route first.
        return list.sorted { ($0.iface == defaultIface ? 0 : 1) < ($1.iface == defaultIface ? 0 : 1) }
    }

    func refresh(gateway: String) {
        background {
            let iface = keyValues(sh("/sbin/route", "-n", "get", "default"))["interface"] ?? ""
            var phys = "", ip = ""
            for i in ["en0", "en1", "en2", "en3"] {
                let a = sh("/usr/sbin/ipconfig", "getifaddr", i).trimmingCharacters(in: .whitespacesAndNewlines)
                if !a.isEmpty { phys = i; ip = a; break }
            }
            let up = sh("/sbin/ping", "-c", "1", "-t", "1", "-q", gateway).contains(" 0.0% packet loss")
            var tunnels = Self.scanTunnels(defaultIface: iface)
            onMain {
                self.defaultIface = iface; self.localIP = ip; self.physicalIface = phys; self.gatewayUp = up
                // Keep already-known public IPs while new ones load.
                for i in tunnels.indices { tunnels[i].publicIP = self.tunnels.first { $0.iface == tunnels[i].iface }?.publicIP ?? "" }
                self.tunnels = tunnels
            }

            // Public IPs: one request per path, in parallel. ipify is abroad; ipapi.ir is in Iran (so it goes through the routes).
            let curl = { (extra: [String], url: String) in
                firstIPv4(sh("/usr/bin/curl", ["-s", "--max-time", "4"] + extra + [url]))
            }
            var jobs: [(String, () -> String)] = [
                ("routed", { curl([], "https://ipapi.ir") }),
                ("direct", { phys.isEmpty ? "" : curl(["--interface", phys], "https://api.ipify.org") }),
            ]
            for t in tunnels { jobs.append((t.iface, { curl(["--interface", t.iface], "https://api.ipify.org") })) }
            var results = [String: String]()
            let lock = NSLock()
            DispatchQueue.concurrentPerform(iterations: jobs.count) { i in
                let r = jobs[i].1()
                lock.lock(); results[jobs[i].0] = r; lock.unlock()
            }
            onMain {
                self.routedIP = results["routed"] ?? ""
                self.directIP = results["direct"] ?? ""
                for i in self.tunnels.indices { self.tunnels[i].publicIP = results[self.tunnels[i].iface] ?? "" }
            }
        }
    }
}

func firstIPv4(_ s: String) -> String {
    s.split(whereSeparator: { !$0.isNumber && $0 != "." }).map(String.init).first { parseIP($0) != nil } ?? ""
}

/// "label  value  [copy]" row; the button shows a checkmark briefly after copying.
struct IPLine: View {
    let symbol: String
    let label: String
    var detail: String?
    let value: String
    @State private var copied = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 11)).foregroundStyle(.secondary).frame(width: 14)
            VStack(alignment: .leading, spacing: 0) {
                Text(label).foregroundStyle(.secondary).lineLimit(1).truncationMode(.tail)
                if let detail { Text(detail).font(.system(size: 9.5)).foregroundStyle(.tertiary) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Text(value.isEmpty ? "—" : value).monospacedDigit().textSelection(.enabled).lineLimit(1).fixedSize()
            Button {
                copyToClipboard(value)
                withAnimation(.snappy) { copied = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { withAnimation(.snappy) { copied = false } }
            } label: {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(copied ? Color.green : Color.secondary)
                    .frame(width: 20, height: 20)
                    .contentShape(Rectangle())
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .disabled(value.isEmpty)
            .help("Copy \(label) IP")
        }
        .font(.system(size: 12))
    }
}

// MARK: - Main window

enum Pane: String, CaseIterable, Identifiable {
    case routes, projects, dns
    var id: Self { self }
    var title: String { switch self { case .routes: "Routes"; case .projects: "Projects"; case .dns: "DNS" } }
    var symbol: String { switch self { case .routes: "arrow.triangle.branch"; case .projects: "server.rack"; case .dns: "globe" } }
    var color: Color { switch self { case .routes: .blue; case .projects: .green; case .dns: .indigo } }
}

struct MainWindow: View {
    @EnvironmentObject var routes: Store
    @EnvironmentObject var procs: ProcStore
    @EnvironmentObject var dns: DNSStore
    @EnvironmentObject var net: NetStore
    @AppStorage("pane") private var pane = Pane.routes

    var body: some View {
        NavigationSplitView {
            List(selection: Binding(get: { Optional(pane) }, set: { if let p = $0 { pane = p } })) {
                Section {
                    ForEach(Pane.allCases) { p in
                        Label { Text(p.title) } icon: { AppIcon(text: nil, symbol: p.symbol, color: p.color, size: 20) }
                            .badge(badge(p))
                            .tag(p)
                    }
                }
                Section("Network") {
                    LabeledContent("Default Route", value: net.vpn ? "VPN (\(net.defaultIface))" : net.defaultIface.isEmpty ? "—" : net.defaultIface)
                    LabeledContent("Local IP", value: net.localIP.isEmpty ? "—" : net.localIP)
                    LabeledContent("ISP IP", value: net.directIP.isEmpty ? "—" : net.directIP)
                    LabeledContent("Iran IP", value: net.routedIP.isEmpty ? "—" : net.routedIP)
                    ForEach(net.tunnels) { t in
                        LabeledContent("\(t.name) (\(t.iface))", value: t.publicIP.isEmpty ? "—" : t.publicIP)
                    }
                    LabeledContent("Gateway") {
                        HStack(spacing: 5) {
                            Circle().fill(net.gatewayUp == true ? .green : net.gatewayUp == false ? .red : .gray).frame(width: 7, height: 7)
                            Text(net.gatewayUp == true ? "Reachable" : net.gatewayUp == false ? "Unreachable" : "—")
                        }
                    }
                }
                .font(.callout)
                .foregroundStyle(.secondary)
                .selectionDisabled()
            }
            .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
            .safeAreaInset(edge: .bottom) { SidebarFooter() }
        } detail: {
            Group {
                switch pane {
                case .routes: RoutesView()
                case .projects: ProjectsView()
                case .dns: DNSView()
                }
            }
            .disabled(routes.busy)
        }
        .alert("Couldn’t Apply Change", isPresented: Binding(get: { routes.error != nil || dns.error != nil },
                                                            set: { if !$0 { routes.error = nil; dns.error = nil } })) {
            Button("OK") {}
        } message: {
            Text(routes.error ?? dns.error ?? "")
        }
        .onAppear {
            net.refresh(gateway: routes.currentGateway)
            procs.refresh()
        }
    }

    func badge(_ p: Pane) -> Int {
        switch p {
        case .routes: routes.activeCount
        case .projects: procs.items.count + procs.containers.count
        case .dns: 0
        }
    }
}

/// Bottom of the sidebar: passwordless setup, launch at login, credits.
struct SidebarFooter: View {
    @EnvironmentObject var routes: Store
    @EnvironmentObject var dns: DNSStore
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var passwordless = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !passwordless {
                Button {
                    DispatchQueue.global(qos: .userInitiated).async {
                        let e = AppInfo.enablePasswordless()
                        let ok = AppInfo.passwordless
                        onMain {
                            passwordless = ok
                            if let e, !e.isEmpty { routes.error = e }
                            dns.refresh()
                        }
                    }
                } label: { Label("Enable Passwordless Mode…", systemImage: "key.fill") }
                .help("Installs a sudoers rule limited to route and DNS changes, so DevNet never asks for your password")
            }
            Toggle("Launch at Login", isOn: $launchAtLogin)
                .toggleStyle(.checkbox)
                .onChange(of: launchAtLogin) { _, on in
                    do { try on ? SMAppService.mainApp.register() : SMAppService.mainApp.unregister() }
                    catch { launchAtLogin = !on }
                }
            Divider()
            HStack(spacing: 4) {
                Text("DevNet \(AppInfo.version) · by").foregroundStyle(.tertiary)
                Link(AppInfo.author, destination: AppInfo.profile)
                Spacer()
                Button { AppInfo.showAbout() } label: { Image(systemName: "info.circle") }
                    .buttonStyle(.borderless).help("About DevNet")
            }
            .font(.caption)
        }
        .font(.callout)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .onAppear { DispatchQueue.global(qos: .userInitiated).async { let ok = AppInfo.passwordless; onMain { passwordless = ok } } }
    }
}

// MARK: - Menu bar panel (styled like the Wi-Fi / Control Center menus)

/// Control Center–style tile: icon, title, subtitle; tinted when on.
struct Tile<Accessory: View>: View {
    let symbol: String
    let on: Bool
    let title: String
    let subtitle: String
    var action: (() -> Void)?
    @ViewBuilder var accessory: Accessory
    @State private var hover = false
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(on ? Color.white : Color.primary)
                .frame(width: 26, height: 26)
                .background(Circle().fill(on ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(.quaternary)))
            VStack(alignment: .leading, spacing: 0) {
                Text(title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                Text(subtitle).font(.system(size: 10.5)).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            accessory
        }
        .padding(8)
        .frame(maxWidth: .infinity)
        .background(Color.primary.opacity(hover && enabled ? 0.1 : 0.06), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .modifier(TapIf(action: enabled ? action : nil))
    }
}

/// Adds a tap gesture only when there is an action, so the view doesn't block an enclosing Menu/Button.
struct TapIf: ViewModifier {
    let action: (() -> Void)?
    func body(content: Content) -> some View {
        if let action { content.onTapGesture(perform: action) } else { content }
    }
}

extension Tile where Accessory == EmptyView {
    init(symbol: String, on: Bool, title: String, subtitle: String, action: (() -> Void)? = nil) {
        self.init(symbol: symbol, on: on, title: title, subtitle: subtitle, action: action) { EmptyView() }
    }
}

struct MenuPanel: View {
    @EnvironmentObject var routes: Store
    @EnvironmentObject var procs: ProcStore
    @EnvironmentObject var dns: DNSStore
    @EnvironmentObject var net: NetStore
    @AppStorage("menuShowRoutes") private var showRoutes = false

    var dnsName: String {
        if let p = dns.activePreset { return p.name }
        return dns.vpnControlsDNS ? "From VPN (\(dns.currentIface))" : "Automatic"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header
            HStack(spacing: 6) {
                Text("DevNet").font(.system(size: 13, weight: .bold))
                Spacer()
                if routes.busy {
                    ProgressView().controlSize(.mini)
                    Text("Applying…").font(.system(size: 11)).foregroundStyle(.secondary)
                } else {
                    Circle().fill(net.vpn ? Color.green : Color.secondary).frame(width: 6, height: 6)
                    Text(net.tunnels.count > 1 ? "\(net.tunnels.count) VPNs on" : net.vpn ? "VPN on" : "No VPN")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }

            // IPs
            VStack(spacing: 2) {
                IPLine(symbol: "laptopcomputer", label: "Local", value: net.localIP)
                IPLine(symbol: "network", label: "ISP", value: net.directIP)
                IPLine(symbol: "arrow.triangle.branch", label: "Iran", value: net.routedIP)
                if !net.tunnels.isEmpty { Divider().padding(.vertical, 2) }
                ForEach(net.tunnels) { t in
                    IPLine(symbol: t.iface == net.defaultIface ? "lock.shield.fill" : "lock.shield",
                           label: t.name, detail: t.iface + (t.iface == net.defaultIface ? " · default" : ""), value: t.publicIP)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

            if let e = routes.error ?? dns.error {
                Label(e, systemImage: "exclamationmark.triangle.fill").font(.system(size: 11)).foregroundStyle(.red).lineLimit(2)
            }

            Group {
                // Quick toggles
                HStack(spacing: 8) {
                    Tile(symbol: "arrow.triangle.branch", on: routes.activeCount > 0, title: "Routes",
                         subtitle: "\(routes.activeCount) of \(routes.config.routes.count) on") {
                        routes.setAll(!routes.allOn)
                    } accessory: {
                        Button { withAnimation(.snappy) { showRoutes.toggle() } } label: {
                            Image(systemName: "chevron.right").rotationEffect(.degrees(showRoutes ? 90 : 0))
                                .font(.system(size: 10, weight: .bold)).foregroundStyle(.secondary)
                                .frame(width: 18, height: 26).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).help("Show routes")
                    }
                    Menu {
                        ForEach(dns.presets) { p in
                            Button { dns.apply(p.servers) } label: {
                                if dns.isActive(p) { Label(p.name, systemImage: "checkmark") } else { Text(p.name) }
                            }
                        }
                        Divider()
                        Button("Automatic (DHCP)") { dns.apply([]) }
                    } label: {
                        Tile(symbol: "globe", on: dns.activePreset != nil, title: "DNS", subtitle: dnsName)
                    }
                    .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden)
                }

                if showRoutes {
                    VStack(spacing: 0) {
                        ForEach(routes.config.routes) { r in
                            let on = routes.active[r.id] ?? false
                            HStack(spacing: 8) {
                                Image(systemName: r.isList ? "flag" : r.isDomain ? "globe.americas" : "point.3.connected.trianglepath.dotted")
                                    .font(.system(size: 10)).foregroundStyle(.secondary).frame(width: 14)
                                Text(r.net).font(.system(size: 12)).monospacedDigit().lineLimit(1).truncationMode(.middle)
                                if routes.isPartial(r) {
                                    Text("\(routes.hits[r.id] ?? 0)/\(r.targets.count)").font(.system(size: 10)).foregroundStyle(.orange)
                                }
                                Spacer()
                                Toggle("", isOn: Binding(get: { on }, set: { routes.set(r, $0) }))
                                    .toggleStyle(.switch).labelsHidden().controlSize(.mini)
                            }
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                        }
                    }
                    .padding(.vertical, 4)
                    .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                // Projects
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Projects").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                        Spacer()
                        if procs.items.count + procs.containers.count > 4 {
                            Button("All \(procs.items.count + procs.containers.count)") {
                                UserDefaults.standard.set(Pane.projects.rawValue, forKey: "pane")
                                MainWindowController.shared.show()
                            }
                            .buttonStyle(.link).font(.system(size: 11))
                        }
                    }
                    if procs.items.isEmpty && procs.containers.isEmpty {
                        Text("Nothing running").font(.system(size: 12)).foregroundStyle(.tertiary)
                    }
                    ForEach(procs.items.prefix(4)) { p in
                        projectRow(icon: p.runtime, title: p.project, ports: p.ports) { procs.stop(p) }
                    }
                    ForEach(procs.containers.prefix(max(0, 4 - procs.items.count))) { c in
                        projectRow(icon: ("Dk", .blue), title: c.name, ports: []) { procs.stop(c) }
                    }
                }
            }
            // Nothing can be changed while route changes are being applied.
            .disabled(routes.busy)
            .opacity(routes.busy ? 0.45 : 1)

            Divider()
            HStack {
                Button { MainWindowController.shared.show() } label: { Label("Open DevNet", systemImage: "macwindow") }
                Spacer()
                Text("⌃⇧I").foregroundStyle(.tertiary)
                Spacer()
                Button { NSApp.terminate(nil) } label: { Label("Quit", systemImage: "power") }
            }
            .buttonStyle(.plain)
            .font(.system(size: 12))
            .foregroundStyle(.secondary)
            HStack(spacing: 3) {
                Text("DevNet \(AppInfo.version) · Created by")
                Link(AppInfo.author, destination: AppInfo.repo).foregroundStyle(.secondary)
            }
            .font(.system(size: 10))
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity)
        }
        .padding(12)
        .frame(width: 330)
        .onAppear {
            routes.refresh()
            dns.refresh()
            procs.refresh()
            net.refresh(gateway: routes.currentGateway)
        }
    }

    func projectRow(icon: (String, Color), title: String, ports: [Int], stop: @escaping () -> Void) -> some View {
        HStack(spacing: 8) {
            AppIcon(text: icon.0, color: icon.1, size: 20)
            Text(title).font(.system(size: 12)).lineLimit(1)
            Spacer(minLength: 4)
            ForEach(ports.prefix(2), id: \.self) { port in
                Button(":\(String(port))") { NSWorkspace.shared.open(URL(string: "http://localhost:\(port)")!) }
                    .buttonStyle(.link).font(.system(size: 11).monospacedDigit())
            }
            StopButton(action: stop)
        }
    }
}

struct StopButton: View {
    let action: () -> Void
    @State private var hover = false
    var body: some View {
        Button(action: action) {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 15))
                .foregroundStyle(hover ? Color.red : Color.secondary)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("Stop")
    }
}

// MARK: - App

#if !PREVIEW
@main
#endif
struct DevNetApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var store = Shared.routes

    init() {
        // Create the stores before SwiftUI observes them (their init publishes changes).
        _ = (Shared.routes, Shared.procs, Shared.dns, Shared.net)
    }

    var body: some Scene {
        MenuBarExtra {
            MenuPanel().sharedStores()
        } label: {
            Image(systemName: store.activeCount > 0 ? "network.badge.shield.half.filled" : "network")
        }
        .menuBarExtraStyle(.window)
    }
}
