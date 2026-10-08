import SwiftUI

// Lists the current user's processes listening on TCP ports (dev servers) and Docker containers, and lets you stop them.

struct DevProcess: Identifiable {
    let id: Int32            // pid
    let name: String
    var ports: [Int]
    var cwd = ""
    var command = ""
    var launchdLabel: String?   // set when a LaunchAgent keeps this process alive
    // App helpers (e.g. IntelliJ's cef_server) run from inside an .app bundle — not projects.
    var hasProject: Bool { !cwd.isEmpty && cwd != "/" && !cwd.contains(".app/Contents") }
    var project: String {
        if cwd.contains("/.gradle/daemon/") { return "Gradle Daemon \((cwd as NSString).lastPathComponent)" }
        return hasProject ? (cwd as NSString).lastPathComponent : name
    }

    /// Two-letter runtime glyph + color for the row icon.
    var runtime: (String, Color) { runtimeGlyph(name) }
}

func runtimeGlyph(_ name: String) -> (String, Color) {
    let n = name.lowercased()
    let table: [(String, String, Color)] = [
        ("node", "JS", .green), ("bun", "Bun", .pink), ("deno", "De", .teal),
        ("python", "Py", .blue), ("uvicorn", "Py", .blue), ("gunicorn", "Py", .blue),
        ("java", "Jv", .orange), ("ruby", "Rb", .red), ("php", "Php", .indigo),
        ("dotnet", ".N", .purple), ("com.docker", "Dk", .blue), ("docker", "Dk", .blue),
        ("postgres", "Pg", .blue), ("redis", "Rd", .red), ("mysql", "SQL", .cyan), ("mongod", "Mg", .green),
        ("nginx", "Nx", .green), ("go", "Go", .cyan),
    ]
    if let hit = table.first(where: { n.hasPrefix($0.0) }) { return (hit.1, hit.2) }
    return (String(name.prefix(2)).capitalized, .gray)
}

struct Container: Identifiable {
    let id: String
    let name: String
    let image: String
    let status: String
    let ports: String
}

final class ProcStore: ObservableObject {
    @Published var items: [DevProcess] = []
    @Published var containers: [Container] = []
    @Published var dockerUp = false
    @Published var stopping: Set<String> = []   // pids / container ids being stopped
    @Published var showAll = UserDefaults.standard.bool(forKey: "showAllProcs") {
        didSet { UserDefaults.standard.set(showAll, forKey: "showAllProcs"); refresh() }
    }

    static let docker = ["/usr/local/bin/docker", "/opt/homebrew/bin/docker"].first { FileManager.default.isExecutableFile(atPath: $0) }

    func refresh() {
        let showAll = showAll
        background {
            let list = Self.scan(showAll: showAll)
            let (up, cs) = Self.scanDocker()
            onMain {
                withAnimation(.snappy) {
                    self.items = list
                    self.containers = cs
                    self.dockerUp = up
                }
                let alive = Set(list.map { String($0.id) } + cs.map(\.id))
                self.stopping.formIntersection(alive)
            }
        }
    }

    static func scan(showAll: Bool) -> [DevProcess] {
        // lsof -F output: "p<pid>", "c<command>", "n<addr:port>"
        var procs: [Int32: DevProcess] = [:]
        var pid: Int32 = 0
        for line in sh("/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn").split(separator: "\n") {
            let v = String(line.dropFirst())
            switch line.first {
            case "p": pid = Int32(v) ?? 0
            case "c": procs[pid] = DevProcess(id: pid, name: v, ports: [])
            case "n":
                if let port = Int(v.split(separator: ":").last ?? ""), procs[pid]?.ports.contains(port) == false {
                    procs[pid]?.ports.append(port)
                }
            default: break
            }
        }
        procs[getpid()] = nil
        guard !procs.isEmpty else { return [] }
        let pids = procs.keys.map(String.init).joined(separator: ",")

        for line in sh("/usr/sbin/lsof", "-a", "-d", "cwd", "-Fpn", "-p", pids).split(separator: "\n") {
            let v = String(line.dropFirst())
            if line.first == "p" { pid = Int32(v) ?? 0 } else if line.first == "n" { procs[pid]?.cwd = v }
        }
        for line in sh("/bin/ps", "-o", "pid=,command=", "-p", pids).split(separator: "\n") {
            let parts = line.trimmingCharacters(in: .whitespaces).split(separator: " ", maxSplits: 1)
            if parts.count == 2, let p = Int32(parts[0]) { procs[p]?.command = String(parts[1]) }
        }

        // pid -> LaunchAgent label (columns: PID, Status, Label)
        for line in sh("/bin/launchctl", "list").split(separator: "\n").dropFirst() {
            let f = line.split(separator: "\t")
            if f.count == 3, let p = Int32(f[0]) { procs[p]?.launchdLabel = String(f[2]) }
        }

        // System apps and daemons run from "/" — project servers run from their project folder.
        return procs.values
            .filter { showAll || $0.hasProject }
            .map { var p = $0; p.ports.sort(); return p }
            .sorted { ($0.ports.first ?? 0) < ($1.ports.first ?? 0) }
    }

    static func scanDocker() -> (Bool, [Container]) {
        guard let docker else { return (false, []) }
        // Cheap check so we don't wait on the CLI when Docker Desktop isn't running.
        let sock = NSHomeDirectory() + "/.docker/run/docker.sock"
        guard FileManager.default.fileExists(atPath: sock) || FileManager.default.fileExists(atPath: "/var/run/docker.sock") else { return (false, []) }
        let out = sh(docker, "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")
        let cs = out.split(separator: "\n").compactMap { line -> Container? in
            let f = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard f.count >= 4 else { return nil }
            return Container(id: f[0], name: f[1], image: f[2], status: f[3], ports: f.count > 4 ? f[4] : "")
        }
        return (true, cs)
    }

    func stop(_ p: DevProcess) {
        // KeepAlive agents get restarted by launchd after a kill, so unload the agent instead.
        if let label = p.launchdLabel {
            stopping.insert(String(p.id))
            background { _ = sh("/bin/launchctl", "bootout", "gui/\(getuid())/\(label)"); onMain { self.refresh() } }
            return
        }
        let force = stopping.contains(String(p.id))
        kill(p.id, force ? SIGKILL : SIGTERM)
        stopping.insert(String(p.id))
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.refresh() }
    }

    func stop(_ c: Container) {
        guard let docker = Self.docker else { return }
        stopping.insert(c.id)
        background { _ = sh(docker, "stop", c.id); onMain { self.refresh() } }
    }

    func stopAll() { items.forEach(stop) }
}

let editors: [(name: String, id: String, symbol: String)] = [
    ("VS Code", "com.microsoft.VSCode", "chevron.left.forwardslash.chevron.right"),
    ("Cursor", "com.todesktop.230313mzl4w4u92", "cursorarrow.rays"),
    ("IntelliJ IDEA", "com.jetbrains.intellij", "hammer"),
    ("Zed", "dev.zed.Zed", "bolt"),
    ("Terminal", "com.apple.Terminal", "terminal"),
    ("iTerm", "com.googlecode.iterm2", "terminal"),
    ("Ghostty", "com.mitchellh.ghostty", "terminal"),
    ("Warp", "dev.warp.Warp-Stable", "terminal"),
].filter { isInstalled($0.id) }

/// System Settings–style rounded-square icon.
struct AppIcon: View {
    let text: String?
    var symbol: String?
    let color: Color
    var size: CGFloat = 26

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.27, style: .continuous)
            .fill(color.gradient)
            .frame(width: size, height: size)
            .overlay {
                if let symbol { Image(systemName: symbol).font(.system(size: size * 0.5, weight: .semibold)) }
                else if let text { Text(text).font(.system(size: size * (text.count > 2 ? 0.32 : 0.42), weight: .bold, design: .rounded)) }
            }
            .foregroundStyle(.white)
    }
}

struct OpenMenuItems: View {
    let p: DevProcess
    var body: some View {
        if p.hasProject {
            ForEach(editors, id: \.id) { e in Button("Open in \(e.name)") { open(p.cwd, withApp: e.id) } }
            Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p.cwd)]) }
            Divider()
        }
        ForEach(p.ports, id: \.self) { port in
            Button("Open localhost:\(String(port))") { NSWorkspace.shared.open(URL(string: "http://localhost:\(port)")!) }
        }
        Divider()
        if p.hasProject { Button("Copy Path") { copyToClipboard(p.cwd) } }
        Button("Copy PID") { copyToClipboard(String(p.id)) }
    }
}

struct ProjectsView: View {
    @EnvironmentObject var s: ProcStore
    let timer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if s.items.isEmpty && s.containers.isEmpty {
                ContentUnavailableView("No Running Projects", systemImage: "moon.zzz",
                                       description: Text("Dev servers listening on a port will appear here."))
            } else {
                Form {
                    if !s.items.isEmpty {
                        Section("Processes") { ForEach(s.items) { row($0) } }
                    }
                    if s.dockerUp && !s.containers.isEmpty {
                        Section("Docker Containers") { ForEach(s.containers) { row($0) } }
                    }
                }
                .formStyle(.grouped)
            }
        }
        .navigationTitle("Projects")
        .navigationSubtitle("\(s.items.count + s.containers.count) running")
        .toolbar {
            ToolbarItem {
                Menu {
                    Toggle("Show System Processes", isOn: $s.showAll)
                } label: { Label("Filter", systemImage: "line.3.horizontal.decrease") }
            }
            ToolbarItem {
                Button { s.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
            }
            ToolbarItem {
                Button { s.stopAll() } label: { Label("Stop All", systemImage: "stop.fill") }
                    .disabled(s.items.isEmpty).help("Stop all processes")
            }
        }
        .onAppear { s.refresh() }
        .onReceive(timer) { _ in s.refresh() }
    }

    func ports(_ ports: [Int]) -> some View {
        HStack(spacing: 4) {
            ForEach(ports, id: \.self) { port in
                Link(":\(String(port))", destination: URL(string: "http://localhost:\(port)")!)
                    .font(.callout.monospacedDigit())
                    .help("Open http://localhost:\(port)")
            }
        }
    }

    func row(_ p: DevProcess) -> some View {
        let stopping = s.stopping.contains(String(p.id))
        return HStack(spacing: 10) {
            AppIcon(text: p.runtime.0, color: p.runtime.1)
            VStack(alignment: .leading, spacing: 2) {
                Text(p.project)
                Text(p.launchdLabel.map { "LaunchAgent \($0)" } ?? p.command).font(.caption).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle).help(p.command)
            }
            Spacer()
            ports(p.ports)
            Menu { OpenMenuItems(p: p) } label: { Image(systemName: "ellipsis.circle") }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().foregroundStyle(.secondary)
            Button(stopping ? "Force Quit" : "Stop") { s.stop(p) }
                .help(stopping ? "Send SIGKILL" : "Send SIGTERM")
        }
        .contextMenu {
            OpenMenuItems(p: p)
            Divider()
            Button("Force Quit", role: .destructive) { kill(p.id, SIGKILL); s.refresh() }
        }
    }

    func row(_ c: Container) -> some View {
        // "0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp" -> [5432]
        let published = Array(Set(c.ports.split(separator: ",").compactMap { m -> Int? in
            guard m.contains("->"), let host = m.split(separator: "-").first else { return nil }
            return Int(host.split(separator: ":").last ?? "")
        })).sorted()
        return HStack(spacing: 10) {
            AppIcon(text: nil, symbol: "shippingbox.fill", color: .blue)
            VStack(alignment: .leading, spacing: 2) {
                Text(c.name)
                Text("\(c.image) — \(c.status)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            ports(published)
            Button(s.stopping.contains(c.id) ? "Stopping…" : "Stop") { s.stop(c) }
                .disabled(s.stopping.contains(c.id))
        }
        .contextMenu { Button("Copy Container ID") { copyToClipboard(c.id) } }
    }
}
