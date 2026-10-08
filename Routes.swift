import SwiftUI

// MARK: - Model

struct Route: Codable, Identifiable, Equatable {
    var id = UUID()
    var net: String
    var gateway: String?
    var note: String = ""
    var resolved: [String]?     // for domain routes: IPv4 addresses routed last time
    var country: String?        // for country lists: ISO code, e.g. "ir"
    var list: [String]?         // for country lists: the CIDRs
    var enabled: Bool?          // what the user wants; the routing table is reconciled to this
    enum CodingKeys: String, CodingKey { case net, gateway, note, resolved, country, list, enabled }

    var isList: Bool { list != nil }
    var isDomain: Bool { !isList && parseCIDR(net) == nil }
    /// CIDRs this entry routes: the network itself, a country's ranges, or one /32 per resolved domain address.
    var targets: [String] {
        if let list { return list }
        return isDomain ? (resolved ?? []).map { "\($0)/32" } : [net]
    }
}

/// Aggregated IPv4 ranges for a country from ipdeny.com.
func fetchCountryRanges(_ code: String) -> [String] {
    guard let url = URL(string: "https://www.ipdeny.com/ipblocks/data/aggregated/\(code)-aggregated.zone"),
          let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
    return text.split(separator: "\n").compactMap { parseCIDR(String($0))?.cidr }
}

/// Current IPv4 routing table as "a.b.c.d/bits" -> gateway, from one netstat call.
func routingTable() -> [String: String] {
    var t: [String: String] = [:]
    for line in sh("/usr/sbin/netstat", "-rn", "-f", "inet").split(separator: "\n") {
        let f = line.split(separator: " ", omittingEmptySubsequences: true)
        guard f.count >= 2, f[0].first?.isNumber == true else { continue }
        // netstat drops trailing zero octets: "10.20/16", "10" (= 10.0.0.0/8), "1.2.3.4" (host)
        let parts = f[0].split(separator: "/")
        var octets = parts[0].split(separator: ".").map(String.init)
        let bits = parts.count == 2 ? String(parts[1]) : String(octets.count * 8)
        while octets.count < 4 { octets.append("0") }
        t["\(octets.joined(separator: "."))/\(bits)"] = String(f[1])
    }
    return t
}

/// "https://portal.example.com/path" -> "portal.example.com"; nil if not a plausible hostname.
func normalizeDomain(_ s: String) -> String? {
    var h = s.trimmingCharacters(in: .whitespaces).lowercased()
    if let r = h.range(of: "://") { h = String(h[r.upperBound...]) }
    h = String(h.split(separator: "/").first ?? "").split(separator: ":").first.map(String.init) ?? ""
    let ok = h.contains(".") && h.allSatisfy { $0.isLetter || $0.isNumber || $0 == "." || $0 == "-" }
    return ok ? h : nil
}

/// IPv4 addresses for a hostname via the system resolver.
func resolveIPv4(_ host: String) -> [String] {
    let out = sh("/usr/bin/dscacheutil", "-q", "host", "-a", "name", host)
    return Array(Set(out.split(separator: "\n").compactMap { line -> String? in
        guard line.hasPrefix("ip_address:") else { return nil }
        let ip = line.dropFirst("ip_address:".count).trimmingCharacters(in: .whitespaces)
        return parseIP(ip) != nil ? ip : nil
    })).sorted()
}

struct Config: Codable {
    var gateway: String     // "" = automatic (the current network's router)
    var routes: [Route]
}

let defaultConfig = Config(gateway: "", routes: [])

/// Router of the first physical interface that has one (en0 = Wi-Fi on most Macs).
func detectGateway() -> String {
    for i in ["en0", "en1", "en2", "en3"] {
        let g = sh("/usr/sbin/ipconfig", "getoption", i, "router").trimmingCharacters(in: .whitespacesAndNewlines)
        if parseIP(g) != nil { return g }
    }
    return ""
}

// MARK: - Store
//
// Each route stores what the user wants (`enabled`). `reconcile()` compares that with the live routing
// table and applies only the difference, one run at a time — so rapid clicks, network changes and
// partial failures all converge to the wanted state.

final class Store: ObservableObject {
    @Published var config: Config
    @Published var error: String?
    @Published var pending = 0                  // reconcile runs queued or running
    @Published var hits: [UUID: Int] = [:]      // how many of each entry's targets are in the table
    @Published var lanGateway = detectGateway()

    var busy: Bool { pending > 0 }
    var active: [UUID: Bool] { Dictionary(uniqueKeysWithValues: config.routes.map { ($0.id, $0.enabled ?? false) }) }
    var activeCount: Int { config.routes.filter { $0.enabled == true }.count }
    var allOn: Bool { !config.routes.isEmpty && activeCount == config.routes.count }
    func isPartial(_ r: Route) -> Bool { r.enabled == true && (hits[r.id] ?? 0) < r.targets.count }

    /// The gateway routes use unless they set their own.
    var currentGateway: String { config.gateway.isEmpty ? lanGateway : config.gateway }
    func gw(_ r: Route) -> String { r.gateway ?? currentGateway }

    private let queue = DispatchQueue(label: "devnet.routes")
    private var timer: Timer?

    static let file: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("VPNRoutes")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("routes.json")
    }()

    init() {
        config = (try? JSONDecoder().decode(Config.self, from: Data(contentsOf: Store.file))) ?? defaultConfig
        // Older versions had no saved on/off state: take it from the live table, and switch to the automatic gateway.
        if config.routes.allSatisfy({ $0.enabled == nil }) {
            let table = routingTable()
            for i in config.routes.indices {
                let t = config.routes[i].targets
                config.routes[i].enabled = !t.isEmpty && t.contains { table[$0] != nil && parseIP(table[$0]!) != nil }
            }
            config.gateway = ""
        }
        save()
        reconcile()
        // Follow network changes: when the router changes, re-apply routes via the new one.
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            background {
                let g = detectGateway()
                onMain {
                    guard let self, g != self.lanGateway else { return }
                    self.lanGateway = g
                    self.reconcile()
                }
            }
        }
    }

    func save() {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        try? enc.encode(config).write(to: Store.file)
    }

    /// Re-reads the routing table for the status counts.
    func refresh() {
        guard pending == 0 else { return }
        let routes = config.routes.map { ($0.id, $0.targets, gw($0)) }
        background {
            let table = routingTable()
            let h = Dictionary(uniqueKeysWithValues: routes.map { id, t, g in (id, t.filter { table[$0] == g }.count) })
            onMain { self.hits = h }
        }
    }

    /// route(8) arguments for a CIDR: host routes for /32, network routes otherwise.
    func dest(_ cidr: String) -> [String] {
        cidr.hasSuffix("/32") ? ["-host", String(cidr.dropLast(3))] : ["-net", cidr]
    }

    /// Brings the routing table in line with what's enabled. `alsoRemove` lists targets that no longer belong to any entry.
    func reconcile(alsoRemove: [String] = []) {
        let wanted = config.routes.map { (on: $0.enabled == true, targets: $0.targets, gw: gw($0)) }
        pending += 1
        queue.async {
            func plan() -> [Cmd] {
                let table = routingTable()
                var cmds: [Cmd] = []
                var keep = Set<String>()
                for w in wanted where w.on && parseIP(w.gw) != nil {
                    for t in w.targets {
                        keep.insert(t)
                        guard table[t] != w.gw else { continue }
                        if table[t] != nil { cmds.append(["/sbin/route", "-n", "delete"] + self.dest(t)) }
                        cmds.append(["/sbin/route", "-n", "add"] + self.dest(t) + [w.gw])
                    }
                }
                // Cached host routes (cloned while traffic went elsewhere, e.g. into the VPN) override our
                // network routes for that address — drop the ones inside an enabled range that use another path.
                let enabled = wanted.filter { $0.on && parseIP($0.gw) != nil }
                    .flatMap { w in w.targets.compactMap { parseCIDR($0) }.map { (net: parseIP($0.addr)!, mask: parseIP($0.mask)!, gw: w.gw) } }
                for (key, g) in table where key.hasSuffix("/32") && !keep.contains(key) {
                    guard let ip = parseIP(String(key.dropLast(3))),
                          let r = enabled.first(where: { $0.mask != UInt32.max && ip & $0.mask == $0.net }), g != r.gw else { continue }
                    cmds.append(["/sbin/route", "-n", "delete"] + self.dest(key))
                }
                // Remove our routes that are off (only ones via an IP gateway, never interface routes from the VPN).
                let off = wanted.filter { !$0.on }.flatMap(\.targets) + alsoRemove
                for t in Set(off) where !keep.contains(t) {
                    if let g = table[t], parseIP(g) != nil { cmds.append(["/sbin/route", "-n", "delete"] + self.dest(t)) }
                }
                return cmds
            }
            var err = runAdmin(plan())
            let retry = plan()                       // anything that didn't stick gets one more try
            if !retry.isEmpty, err == nil { err = runAdmin(retry) }
            onMain {
                self.pending -= 1
                if let err, !err.isEmpty { self.error = err }
                self.refresh()
            }
        }
    }

    /// Re-resolves a domain entry; returns addresses that are no longer used.
    private func resolve(_ i: Int) -> [String] {
        let r = config.routes[i]
        guard r.isDomain else { return [] }
        let ips = resolveIPv4(r.net)
        if ips.isEmpty { error = "Couldn’t resolve \(r.net)."; return [] }
        config.routes[i].resolved = ips
        return r.targets.filter { !config.routes[i].targets.contains($0) }
    }

    func set(_ r: Route, _ on: Bool) {
        guard let i = config.routes.firstIndex(where: { $0.id == r.id }) else { return }
        let stale = on ? resolve(i) : []
        withAnimation(.snappy) { config.routes[i].enabled = on }
        save()
        reconcile(alsoRemove: stale)
    }

    func setAll(_ on: Bool) {
        var stale: [String] = []
        for i in config.routes.indices {
            if on { stale += resolve(i) }
            config.routes[i].enabled = on
        }
        save()
        reconcile(alsoRemove: stale)
    }

    /// Adds (index nil) or edits a route. Returns an error message for invalid input.
    func upsert(_ index: Int?, net: String, gateway: String, note: String) -> String? {
        let target: String
        if let c = parseCIDR(net) { target = c.cidr }
        else if let d = normalizeDomain(net) { target = d }
        else { return "Enter a network (10.20.30.0/24) or a domain (example.com)." }
        let g = gateway.trimmingCharacters(in: .whitespaces)
        if !g.isEmpty && parseIP(g) == nil { return "The gateway must be an IPv4 address." }
        var r = Route(net: target, gateway: g.isEmpty ? nil : ipString(parseIP(g)!), note: note.trimmingCharacters(in: .whitespaces))
        var stale: [String] = []
        if let i = index {
            let old = config.routes[i]
            r.id = old.id
            r.enabled = old.enabled
            if old.net == r.net { r.resolved = old.resolved } else { stale = old.targets }
            config.routes[i] = r
            if r.enabled == true && old.net != r.net { stale += resolve(i) }
        } else {
            r.enabled = false
            config.routes.append(r)
        }
        save()
        reconcile(alsoRemove: stale)
        return nil
    }

    /// Downloads a country's IP ranges and adds (or updates) them as one entry.
    func addCountry(_ code: String) {
        let code = code.trimmingCharacters(in: .whitespaces).lowercased()
        guard code.count == 2, code.allSatisfy(\.isLetter) else { error = "Enter a two-letter country code, e.g. IR."; return }
        pending += 1
        background {
            let ranges = fetchCountryRanges(code)
            onMain {
                self.pending -= 1
                guard !ranges.isEmpty else { self.error = "Couldn’t download IP ranges for \(code.uppercased())."; return }
                var stale: [String] = []
                if let i = self.config.routes.firstIndex(where: { $0.country == code }) {
                    stale = Array(Set(self.config.routes[i].list ?? []).subtracting(ranges))
                    self.config.routes[i].list = ranges
                } else {
                    let name = "\(Locale.current.localizedString(forRegionCode: code) ?? code.uppercased()) IP ranges"
                    var r = Route(net: name, country: code, list: ranges)
                    r.enabled = false
                    self.config.routes.append(r)
                }
                self.save()
                self.reconcile(alsoRemove: stale)
            }
        }
    }

    func remove(_ r: Route) {
        withAnimation(.snappy) { config.routes.removeAll { $0.id == r.id } }
        save()
        reconcile(alsoRemove: r.targets)
    }

    /// Empty string = automatic.
    func setGateway(_ s: String) -> Bool {
        let s = s.trimmingCharacters(in: .whitespaces)
        if s.isEmpty || s.lowercased() == "auto" || s.lowercased() == "automatic" {
            config.gateway = ""
        } else {
            guard let ip = parseIP(s) else { error = "The gateway must be an IPv4 address."; return false }
            config.gateway = ipString(ip)
        }
        save()
        reconcile()
        return true
    }
}

// MARK: - Window

struct EditTarget: Identifiable {
    let index: Int?
    var id: Int { index ?? -1 }
}

struct RoutesView: View {
    @EnvironmentObject var s: Store
    @State private var editing: EditTarget?
    @State private var gateway = ""
    @State private var addingCountry = false
    @State private var countryCode = "IR"

    var body: some View {
        Form {
            Section {
                Toggle(isOn: Binding(get: { s.allOn }, set: { s.setAll($0) })) {
                    Text("All Routes")
                    if s.busy { Text("Applying changes…") }
                    Text("\(s.activeCount) of \(s.config.routes.count) active")
                }
            }

            Section {
                if s.config.routes.isEmpty {
                    Text("No routes yet. Click + to add one.").foregroundStyle(.secondary)
                }
                ForEach(Array(s.config.routes.enumerated()), id: \.element.id) { i, r in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.net).monospacedDigit()
                            if s.isPartial(r) {
                                Button("Only \(s.hits[r.id] ?? 0) of \(r.targets.count) ranges applied — Apply Missing") { s.set(r, true) }
                                    .buttonStyle(.link).font(.callout).foregroundStyle(.orange)
                            }
                            Text((r.isList ? "\(s.hits[r.id] ?? 0) of \(r.targets.count) ranges " : r.isDomain ? (r.resolved ?? []).joined(separator: ", ") + " " : "") + "via \(s.gw(r))" + (r.note.isEmpty ? "" : " — \(r.note)"))
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if r.isList {
                            Button { s.addCountry(r.country ?? "") } label: { Image(systemName: "arrow.down.circle") }
                                .buttonStyle(.borderless).foregroundStyle(.secondary).help("Update List")
                        } else {
                            Button { editing = EditTarget(index: i) } label: { Image(systemName: "info.circle") }
                                .buttonStyle(.borderless).foregroundStyle(.secondary).help("Edit Route")
                        }
                        Toggle("", isOn: Binding(get: { s.active[r.id] ?? false }, set: { s.set(r, $0) }))
                            .labelsHidden()
                    }
                    .contextMenu {
                        if r.isList { Button("Update List") { s.addCountry(r.country ?? "") } }
                        else { Button("Edit…") { editing = EditTarget(index: i) } }
                        Button("Copy Command") { copyToClipboard(r.targets.map { "sudo route -n add \(s.dest($0).joined(separator: " ")) \(s.gw(r))" }.joined(separator: "\n")) }
                        Divider()
                        Button("Delete", role: .destructive) { s.remove(r) }
                    }
                }
            } header: {
                Text("Routes")
            } footer: {
                Text("Traffic to these networks is sent through the gateway instead of the default route.")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            Section {
                TextField("Default Gateway", text: $gateway, prompt: Text("Automatic (\(s.lanGateway.isEmpty ? "no network" : s.lanGateway))"))
                    .onSubmit { if !s.setGateway(gateway) { gateway = s.config.gateway } }
            } footer: {
                Text("Leave empty to use the router of the network you're on. Routes follow it when you switch networks.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Routes")
        .navigationSubtitle("\(s.activeCount) of \(s.config.routes.count) active")
        .toolbar {
            ToolbarItem {
                Button { s.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                    .disabled(s.busy)
            }
            if s.busy { ToolbarItem { ProgressView().controlSize(.small) } }
            ToolbarItem {
                Menu {
                    Button("Network or Domain…") { editing = EditTarget(index: nil) }
                    Button("Country IP Ranges…") { addingCountry = true }
                } label: { Label("Add", systemImage: "plus") }
                .disabled(s.busy)
            }
        }
        .sheet(item: $editing) { RouteEditor(index: $0.index) }
        .alert("Add Country IP Ranges", isPresented: $addingCountry) {
            TextField("Country code", text: $countryCode)
            Button("Cancel", role: .cancel) {}
            Button("Add") { s.addCountry(countryCode) }
        } message: {
            Text("Routes every IPv4 range registered to that country (from ipdeny.com) through the gateway. Use IR for Iran.")
        }
        .onAppear { s.refresh(); gateway = s.config.gateway }
        .onChange(of: s.config.gateway) { _, g in gateway = g }
    }
}

struct RouteEditor: View {
    let index: Int?
    @EnvironmentObject var s: Store
    @Environment(\.dismiss) private var dismiss
    @State private var net = ""
    @State private var gateway = ""
    @State private var note = ""
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                TextField("Network or Domain", text: $net, prompt: Text("10.20.30.0/24 or example.com"))
                TextField("Gateway", text: $gateway, prompt: Text(s.currentGateway))
                TextField("Note", text: $note, prompt: Text("Optional"))
            } header: {
                Text(index == nil ? "New Route" : "Edit Route")
            } footer: {
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
        .frame(width: 420)
        .toolbar {
            if let index {
                ToolbarItem(placement: .destructiveAction) {
                    Button("Delete Route", role: .destructive) { s.remove(s.config.routes[index]); dismiss() }
                }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(index == nil ? "Add" : "Save") {
                    error = s.upsert(index, net: net, gateway: gateway, note: note)
                    if error == nil { dismiss() }
                }
            }
        }
        .onAppear {
            if let index { let r = s.config.routes[index]; net = r.net; gateway = r.gateway ?? ""; note = r.note }
        }
    }
}
