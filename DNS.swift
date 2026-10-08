import SwiftUI

// Quick-switch DNS servers (Shecan, etc.) on a network service via networksetup.

struct DNSPreset: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var servers: [String]
    enum CodingKeys: String, CodingKey { case name, servers }
}

let defaultPresets: [DNSPreset] = [
    DNSPreset(name: "Shecan", servers: ["178.22.122.100", "185.51.231.231"]),
    DNSPreset(name: "Electro", servers: ["78.157.42.100", "78.157.42.101"]),
    DNSPreset(name: "Begzar", servers: ["185.55.226.26", "185.55.225.25"]),
    DNSPreset(name: "403", servers: ["10.202.10.202", "10.202.10.102"]),
    DNSPreset(name: "Radar Game", servers: ["10.202.10.10", "10.202.10.11"]),
    DNSPreset(name: "Google", servers: ["8.8.8.8", "8.8.4.4"]),
    DNSPreset(name: "Cloudflare", servers: ["1.1.1.1", "1.0.0.1"]),
]

final class DNSStore: ObservableObject {
    @Published var presets: [DNSPreset]
    @Published var services: [String] = []
    @Published var current: [String] = []        // DNS actually in use (first resolver from scutil --dns)
    @Published var currentIface = ""             // interface that resolver belongs to, e.g. ppp0 for a VPN
    @Published var configured: [String] = []     // DNS set on the selected service (empty = automatic)
    @Published var error: String?
    @Published var latency: [String: Int] = [:]   // server -> ms, -1 = timeout
    @Published var testing = false
    @Published var flushed = false
    @Published var service = UserDefaults.standard.string(forKey: "dnsService") ?? "Wi-Fi" {
        didSet { UserDefaults.standard.set(service, forKey: "dnsService"); refresh() }
    }

    static let file = Store.file.deletingLastPathComponent().appendingPathComponent("dns.json")

    init() {
        if let saved = try? JSONDecoder().decode([DNSPreset].self, from: Data(contentsOf: Self.file)) {
            presets = saved
        } else {
            presets = defaultPresets
            // Keep whatever DNS was configured before the first run as a preset.
            let existing = Self.read(service)
            if !existing.isEmpty && !presets.contains(where: { $0.servers == existing }) {
                presets.append(DNSPreset(name: "Previous", servers: existing))
            }
            save()
        }
        refresh()
    }

    static func read(_ service: String) -> [String] {
        sh("/usr/sbin/networksetup", "-getdnsservers", service).split(separator: "\n")
            .map(String.init).filter { parseIP($0) != nil }
    }

    /// The default resolver macOS is using right now: its servers and interface.
    static func effective() -> (servers: [String], iface: String) {
        var servers: [String] = [], iface = ""
        // Only the first block ("DNS configuration"), first resolver without a match domain.
        for block in sh("/usr/sbin/scutil", "--dns").components(separatedBy: "\n\n") {
            if block.contains("for scoped queries") { break }
            guard block.contains("resolver #"), !block.contains("domain   :") else { continue }
            for line in block.split(separator: "\n") {
                let kv = line.split(separator: ":", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
                guard kv.count == 2 else { continue }
                if kv[0].hasPrefix("nameserver"), parseIP(kv[1]) != nil { servers.append(kv[1]) }
                if kv[0] == "if_index" { iface = kv[1].split(separator: "(").last.map { String($0.dropLast()) } ?? "" }
            }
            if !servers.isEmpty { break }
        }
        return (servers, iface)
    }

    static let helper = "/usr/local/libexec/devnet-dns"
    var helperInstalled: Bool { FileManager.default.isExecutableFile(atPath: Self.helper) }

    func refresh() {
        services = sh("/usr/sbin/networksetup", "-listallnetworkservices").split(separator: "\n").dropFirst()
            .map(String.init).filter { !$0.hasPrefix("*") }
        let e = Self.effective()
        withAnimation(.snappy) {
            current = e.servers
            currentIface = e.iface
            configured = Self.read(service)
        }
    }

    /// True when the DNS in use comes from a VPN (its settings override Wi-Fi's).
    var vpnControlsDNS: Bool { ["utun", "ppp", "ipsec", "tun", "wg"].contains { currentIface.hasPrefix($0) } }

    func save() {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        try? enc.encode(presets).write(to: Self.file)
    }

    /// Matches the DNS in use; a preset counts if its servers are what macOS resolves with.
    var activePreset: DNSPreset? { presets.first { $0.servers == current } ?? presets.first { $0.servers == configured && !configured.isEmpty } }
    func isActive(_ p: DNSPreset) -> Bool { activePreset?.id == p.id }

    /// Sets DNS (empty list = automatic). Saved on the selected service, and — via the helper — applied live
    /// to every active service including VPNs, whose DNS would otherwise win.
    func apply(_ servers: [String]) {
        error = nil
        var cmds: [Cmd] = [["/usr/sbin/networksetup", "-setdnsservers", service] + (servers.isEmpty ? ["Empty"] : servers)]
        if helperInstalled { cmds.append([Self.helper] + (servers.isEmpty ? ["reset"] : ["set"] + servers)) }
        if let e = runAdmin(cmds), !e.isEmpty { error = e }
        refresh()
        if !helperInstalled && vpnControlsDNS && !servers.isEmpty && current != servers {
            error = "Your VPN (\(currentIface)) sets its own DNS. Click “Enable Passwordless Mode” in the DevNet window so it can override it."
        }
    }

    func flushCache() {
        if let e = runAdmin([["/usr/bin/dscacheutil", "-flushcache"], ["/usr/bin/killall", "-HUP", "mDNSResponder"]]) {
            if !e.isEmpty { error = e }
            return
        }
        withAnimation(.snappy) { flushed = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { withAnimation(.snappy) { self.flushed = false } }
    }

    /// Measures a DNS lookup against the first server of every preset, in parallel.
    func testLatency() {
        let servers = Array(Set(presets.compactMap(\.servers.first)))
        testing = true
        latency = [:]
        background {
            var results = [String: Int]()
            let lock = NSLock()
            DispatchQueue.concurrentPerform(iterations: servers.count) { i in
                let out = sh("/usr/bin/dig", "@\(servers[i])", "google.com", "+time=2", "+tries=1", "+noall", "+stats")
                let ms = out.split(separator: "\n").first { $0.contains("Query time:") }
                    .flatMap { Int($0.split(separator: " ").dropFirst(3).first ?? "") } ?? -1
                lock.lock(); results[servers[i]] = ms; lock.unlock()
            }
            onMain { withAnimation(.snappy) { self.latency = results; self.testing = false } }
        }
    }

    /// Adds (index nil) or edits a preset.
    func upsert(_ index: Int?, name: String, servers: String) -> String? {
        let list = servers.split(whereSeparator: { " ,،\n".contains($0) }).map(String.init)
        let name = name.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return "Enter a name." }
        guard !list.isEmpty, list.allSatisfy({ parseIP($0) != nil }) else { return "Enter one or more IPv4 addresses." }
        let p = DNSPreset(name: name, servers: list.map { ipString(parseIP($0)!) })
        withAnimation(.snappy) {
            if let i = index { presets[i].name = p.name; presets[i].servers = p.servers } else { presets.append(p) }
        }
        save()
        return nil
    }

    func remove(_ p: DNSPreset) {
        withAnimation(.snappy) { presets.removeAll { $0.id == p.id } }
        save()
    }
}

// MARK: - Window

struct DNSView: View {
    @EnvironmentObject var s: DNSStore
    @State private var editing: EditTarget?

    var body: some View {
        Form {
            Section {
                Picker("Network Service", selection: $s.service) {
                    ForEach(s.services, id: \.self) { Text($0).tag($0) }
                }
                LabeledContent("DNS Servers") {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(s.activePreset?.name ?? "Automatic")
                        Text(s.current.joined(separator: ", ") + (s.currentIface.isEmpty ? "" : " — via \(s.currentIface)"))
                            .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                if s.vpnControlsDNS && !s.helperInstalled {
                    Label("Your VPN sets its own DNS. Enable Passwordless Mode (bottom of the sidebar) so presets can override it.", systemImage: "exclamationmark.triangle")
                        .font(.callout).foregroundStyle(.orange)
                }
                if s.activePreset != nil || !s.configured.isEmpty {
                    HStack {
                        Spacer()
                        Button("Use Automatic DNS") { s.apply([]) }
                    }
                }
            }

            Section {
                ForEach(Array(s.presets.enumerated()), id: \.element.id) { i, p in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.name)
                            Text(p.servers.joined(separator: ", ")).font(.callout).foregroundStyle(.secondary).monospacedDigit()
                        }
                        Spacer()
                        if let first = p.servers.first, let ms = s.latency[first] {
                            Text(ms < 0 ? "Timeout" : "\(ms) ms")
                                .font(.callout).monospacedDigit()
                                .foregroundStyle(ms < 0 ? .red : ms < 60 ? .green : ms < 150 ? .orange : .red)
                        }
                        Button { editing = EditTarget(index: i) } label: { Image(systemName: "info.circle") }
                            .buttonStyle(.borderless).foregroundStyle(.secondary).help("Edit")
                        Toggle("", isOn: Binding(get: { s.isActive(p) }, set: { s.apply($0 ? p.servers : []) }))
                            .labelsHidden()
                    }
                    .contextMenu {
                        Button("Edit…") { editing = EditTarget(index: i) }
                        Button("Copy Servers") { copyToClipboard(p.servers.joined(separator: " ")) }
                        Divider()
                        Button("Delete", role: .destructive) { s.remove(p) }
                    }
                }
            } header: {
                Text("Presets")
            } footer: {
                Text("Turning a preset off switches back to automatic DNS from your router.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("DNS")
        .navigationSubtitle(s.activePreset?.name ?? "Automatic")
        .toolbar {
            ToolbarItem {
                Button { s.testLatency() } label: { Label("Test Speed", systemImage: "gauge.with.dots.needle.67percent") }
                    .disabled(s.testing).help("Measure response time of each preset")
            }
            ToolbarItem {
                Button { s.flushCache() } label: {
                    Label("Flush Cache", systemImage: s.flushed ? "checkmark" : "arrow.triangle.2.circlepath")
                }
                .help("Flush DNS cache")
            }
            ToolbarItem {
                Button { editing = EditTarget(index: nil) } label: { Label("Add Preset", systemImage: "plus") }
            }
        }
        .sheet(item: $editing) { DNSEditor(index: $0.index) }
        .onAppear { s.refresh() }
    }
}

struct DNSEditor: View {
    let index: Int?
    @EnvironmentObject var s: DNSStore
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var servers = ""
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                TextField("Name", text: $name, prompt: Text("Cloudflare"))
                TextField("Servers", text: $servers, prompt: Text("1.1.1.1, 1.0.0.1"))
            } header: {
                Text(index == nil ? "New DNS Preset" : "Edit DNS Preset")
            } footer: {
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
        .frame(width: 420)
        .toolbar {
            if let index {
                ToolbarItem(placement: .destructiveAction) {
                    Button("Delete Preset", role: .destructive) { s.remove(s.presets[index]); dismiss() }
                }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(index == nil ? "Add" : "Save") {
                    error = s.upsert(index, name: name, servers: servers)
                    if error == nil { dismiss() }
                }
            }
        }
        .onAppear {
            if let index { name = s.presets[index].name; servers = s.presets[index].servers.joined(separator: ", ") }
        }
    }
}
