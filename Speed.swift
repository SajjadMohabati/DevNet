import SwiftUI
import Network

// Speed tools built on Cloudflare's public endpoints (speed.cloudflare.com):
//   GET  /__down?bytes=N   download N bytes (ping uses bytes=0)
//   POST /__up             upload a body (raw socket: URLSession reports upload progress unreliably)
//   GET  /meta             client IP, ISP, datacenter serving the test
//
// Besides the on-demand test, the store runs lightweight monitors while DevNet is on screen:
// interface byte counters via getifaddrs (live throughput, no process spawn) and ICMP pings to
// the user's targets (live latency). All published state is touched on the main thread only.

// MARK: - Model

struct SpeedResult: Codable, Identifiable, Equatable {
    var id = UUID()
    var date: Date
    var down: Double      // bytes/s
    var up: Double        // bytes/s
    var ping: Int         // milliseconds
}

struct SpeedSample: Identifiable {
    let id = UUID()
    let t: Double         // seconds since the test started
    let phase: SpeedPhase
    let value: Double     // bytes/s (smoothed)
}

enum SpeedPhase: Equatable {
    case idle, ping, download, upload
}

struct SpeedMeta: Codable {
    struct Colo: Codable { var iata: String?; var city: String? }
    var clientIp: String?
    var asOrganization: String?
    var colo: Colo?
    var city: String?
    var country: String?
    var httpProtocol: String?
}

/// A host the user wants watched: any IPv4 address or domain.
struct PingTarget: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var host: String
    var enabled = true
}

/// Live status of one target (not persisted).
struct TargetStat: Equatable {
    var ping: Int?
    var iface: String?
}

/// "3_400_000 bytes/s" -> "27.2 Mbps" (or "3.4 MB/s" in byte mode).
func formatSpeed(_ bytesPerSec: Double, bytes: Bool = false) -> String {
    if bytes { return formatRate(bytesPerSec) }
    let m = bytesPerSec * 8 / 1_000_000
    if m >= 100 { return String(format: "%.0f Mbps", m) }
    if m >= 10 { return String(format: "%.1f Mbps", m) }
    if m >= 1 { return String(format: "%.2f Mbps", m) }
    return String(format: "%.0f kbps", m * 1000)
}

/// "3_400_000 bytes/s" -> "3.4 MB/s" — for the always-on interface counters.
func formatRate(_ bytesPerSec: Double) -> String {
    if bytesPerSec >= 1_000_000 { return String(format: "%.1f MB/s", bytesPerSec / 1_000_000) }
    if bytesPerSec >= 1_000 { return String(format: "%.0f KB/s", bytesPerSec / 1_000) }
    return String(format: "%.0f B/s", bytesPerSec)
}

// MARK: - Transfer tracker (download)

/// URLSession delegate that records (time, cumulative bytes) as data arrives, thread-safely.
/// Handles several requests per measurement: progress restarts at 0 per task, so `base`
/// keeps the running total across segments.
final class TransferTracker: NSObject, URLSessionDataDelegate, URLSessionTaskDelegate {
    private let lock = NSLock()
    private var events: [(t: Double, bytes: Int64)] = []
    private var base: Int64 = 0
    private var done = true
    private var t0 = Date()

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock(); defer { lock.unlock() }
        events.append((Date().timeIntervalSince(t0), (events.last?.bytes ?? 0) + Int64(data.count)))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        lock.lock(); defer { lock.unlock() }
        let total = base + totalBytesSent
        guard (events.last?.bytes ?? 0) != total else { return }
        events.append((Date().timeIntervalSince(t0), total))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock(); done = true; lock.unlock()
    }

    func restart() { lock.lock(); base = events.last?.bytes ?? 0; done = false; lock.unlock() }
    var isFinished: Bool { lock.lock(); defer { lock.unlock() }; return done }

    func snapshot() -> (t: Double, bytes: Int64) {
        lock.lock(); defer { lock.unlock() }
        return (events.last?.t ?? 0, events.last?.bytes ?? 0)
    }

    func average(ramp: Double) -> Double { lock.lock(); defer { lock.unlock() }; return Self.average(events, ramp: ramp) }

    /// Average bytes/s over the events, skipping the first `ramp` seconds (TCP/TLS ramp-up).
    static func average(_ events: [(t: Double, bytes: Int64)], ramp: Double) -> Double {
        guard let last = events.last, last.t > 0.1, last.bytes > 0 else { return 0 }
        let skip = last.t > ramp * 3 ? ramp : 0
        let b = skip > 0 ? events.last(where: { $0.t <= skip })?.bytes ?? 0 : 0
        return Double(last.bytes - b) / max(last.t - skip, 0.1)
    }
}

// MARK: - Raw uploader

/// Measures upload speed over a plain TLS socket. URLSession only reports upload progress
/// in one early burst (and stalls), so we push zero-filled chunks ourselves and count each
/// chunk the transport accepts — which tracks the real uplink rate.
final class RawUploader {
    private let lock = NSLock()
    private var events: [(t: Double, bytes: Int64)] = []
    private var done = false
    private var conn: NWConnection?
    private let t0 = Date()
    private let cap = 25_000_000
    private let chunk = Data(repeating: 0, count: 262_144)   // 256 KB
    private let header = Data("POST /__up HTTP/1.1\r\nHost: speed.cloudflare.com\r\nContent-Type: application/octet-stream\r\nContent-Length: 25000000\r\nConnection: close\r\n\r\n".utf8)

    func start() {
        let c = NWConnection(host: "speed.cloudflare.com", port: 443, using: .tls)
        conn = c
        c.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready: self?.send(isHeader: true)
            case .failed, .cancelled: self?.finish()
            default: break
            }
        }
        c.start(queue: .global(qos: .utility))
    }

    private func send(isHeader: Bool) {
        guard let conn, !isFinished else { return }
        let payload = isHeader ? header : chunk
        conn.send(content: payload, completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            if error != nil { self.finish(); return }
            if isHeader {
                DispatchQueue.global(qos: .utility).async { self.send(isHeader: false) }
                return
            }
            self.lock.lock()
            let total = (self.events.last?.bytes ?? 0) + Int64(self.chunk.count)
            self.events.append((Date().timeIntervalSince(self.t0), total))
            self.lock.unlock()
            if total >= Int64(self.cap) { self.finish() }
            else { DispatchQueue.global(qos: .utility).async { self.send(isHeader: false) } }
        })
    }

    private func finish() {
        lock.lock()
        if done { lock.unlock(); return }
        done = true
        lock.unlock()
        conn?.cancel()
    }

    func cancel() { finish() }
    var isFinished: Bool { lock.lock(); defer { lock.unlock() }; return done }

    func snapshot() -> Int64 { lock.lock(); defer { lock.unlock() }; return events.last?.bytes ?? 0 }
    func average(ramp: Double) -> Double { lock.lock(); defer { lock.unlock() }; return TransferTracker.average(events, ramp: ramp) }
}

// MARK: - Store

final class SpeedStore: ObservableObject {
    // Full test
    @Published var phase: SpeedPhase = .idle
    @Published var live: Double = 0        // bytes/s in the running phase
    @Published var progress: Double = 0    // 0…1 through the whole test
    @Published var samples: [SpeedSample] = []
    @Published var result: SpeedResult?    // last completed test
    @Published var history: [SpeedResult] = []
    @Published var meta: SpeedMeta?
    @Published var error: String?

    // Always-on monitors
    @Published var activityDown: Double = 0     // bytes/s, interface counters
    @Published var activityUp: Double = 0
    @Published var livePing: Int?               // ms to the menu-bar host
    @Published var liveIface: String?           // interface carrying the menu-bar host
    @Published var liveHostName: String = "Cloudflare"
    @Published var targets: [PingTarget] = []
    @Published var targetStats: [UUID: TargetStat] = [:]

    /// Which target drives the menu bar's latency line — a target id, or nil for Cloudflare.
    @Published var menuHostID: UUID? {
        didSet { UserDefaults.standard.setValue(menuHostID?.uuidString, forKey: "speedMenuHost") }
    }
    /// Show speeds in bytes/s (MB/s) instead of bits/s (Mbps).
    @Published var useBytes: Bool {
        didSet { UserDefaults.standard.set(useBytes, forKey: "speedUseBytes") }
    }

    var running: Bool { phase != .idle }

    static let base = URL(string: "https://speed.cloudflare.com")!
    static let file = Store.file.deletingLastPathComponent().appendingPathComponent("speed.json")
    static let targetsFile = Store.file.deletingLastPathComponent().appendingPathComponent("targets.json")
    private static let chunkBytes = 25_000_000       // Cloudflare rejects larger single requests
    private static let phaseSeconds: Double = 8      // cap per direction
    static let defaultTargets = [
        PingTarget(name: "Cloudflare", host: "1.1.1.1"),
        PingTarget(name: "Google", host: "8.8.8.8"),
        PingTarget(name: "Shecan", host: "178.22.122.100"),
    ]

    private var task: Task<Void, Never>?
    private var testStart = Date()

    // Monitors — main thread only
    private var monitorTimer: Timer?
    private var tick = 0
    private var prevNet: (t: Date, counters: [String: (down: UInt32, up: UInt32)])?
    private var targetIndex = 0
    private var pinging = Set<UUID>()
    private var livePingBusy = false

    /// The host the menu bar pings: the chosen target, or Cloudflare by default.
    var menuHost: PingTarget {
        targets.first { $0.id == menuHostID } ?? PingTarget(name: "Cloudflare", host: "1.1.1.1")
    }

    init() {
        menuHostID = UserDefaults.standard.string(forKey: "speedMenuHost").flatMap(UUID.init(uuidString:))
        useBytes = UserDefaults.standard.bool(forKey: "speedUseBytes")
        load()
        startMonitors()
    }

    // MARK: Persistence

    private func load() {
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        history = (try? dec.decode([SpeedResult].self, from: Data(contentsOf: Self.file))) ?? []
        if let data = try? Data(contentsOf: Self.targetsFile),
           let saved = try? JSONDecoder().decode([PingTarget].self, from: data), !saved.isEmpty {
            targets = saved
        } else {
            targets = Self.defaultTargets
            saveTargets()
        }
    }

    func save() {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        enc.dateEncodingStrategy = .iso8601
        try? enc.encode(history).write(to: Self.file)
    }

    private func saveTargets() {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        try? enc.encode(targets).write(to: Self.targetsFile)
    }

    func clearHistory() {
        withAnimation(.snappy) { history = [] }
        save()
    }

    // MARK: Targets

    /// Adds (index nil) or edits a target. Returns an error message for invalid input.
    func upsertTarget(_ index: Int?, name: String, host: String) -> String? {
        let h = host.trimmingCharacters(in: .whitespaces)
        guard parseIP(h) != nil || normalizeDomain(h) != nil else {
            return "Enter an IP address (1.1.1.1) or a domain (example.com)."
        }
        let label = name.trimmingCharacters(in: .whitespaces)
        if let i = index {
            targets[i].name = label.isEmpty ? h : label
            targets[i].host = h
        } else {
            targets.append(PingTarget(name: label.isEmpty ? h : label, host: h))
        }
        saveTargets()
        return nil
    }

    func removeTarget(_ t: PingTarget) {
        targets.removeAll { $0.id == t.id }
        targetStats[t.id] = nil
        if menuHostID == t.id { menuHostID = nil }
        saveTargets()
    }

    func setTarget(_ t: PingTarget, _ on: Bool) {
        guard let i = targets.firstIndex(where: { $0.id == t.id }) else { return }
        targets[i].enabled = on
        saveTargets()
    }

    // MARK: Monitors

    private func startMonitors() {
        let t = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.monitorTick() }
        t.tolerance = 0.5
        RunLoop.main.add(t, forMode: .common)
        monitorTimer = t
    }

    /// True while a DevNet window or panel is actually being looked at: visible on the current Space and
    /// not fully covered. Windows on another Space or minimized, the status item's window and SwiftUI's
    /// tiny off-screen helper window don't count.
    private static var onScreen: Bool {
        if PanelController.shared.isShown { return true }
        return NSApp.windows.contains { w in
            w.isVisible && w.occlusionState.contains(.visible) && !w.className.contains("StatusBar")
                && w.frame.width > 200 && NSScreen.screens.contains { $0.frame.intersects(w.frame) }
        }
    }

    /// Samples right away — called when the panel opens so values don't wait for the next tick.
    func poke() { monitorTick(force: true) }

    private func monitorTick(force: Bool = false) {
        // Nothing to show: don't spend CPU, battery or network.
        guard force || Self.onScreen else { prevNet = nil; return }
        tick += 1
        sampleActivity()
        if !running {
            if force || tick % 3 == 0 { sampleLivePing() }
            rotateTarget()
        }
    }

    private func sampleActivity() {
        let now = Date(), counters = Self.netCounters()
        defer { prevNet = (now, counters) }
        guard let p = prevNet else { return }
        let dt = now.timeIntervalSince(p.t)
        guard dt > 0.5 else { return }
        // 32-bit kernel counters wrap at 4 GB: wrapping subtraction gives the right delta.
        var down: UInt64 = 0, up: UInt64 = 0
        for (name, c) in counters {
            guard let old = p.counters[name] else { continue }
            down += UInt64(c.down &- old.down)
            up += UInt64(c.up &- old.up)
        }
        let d = Double(down) / dt, u = Double(up) / dt
        activityDown = activityDown == 0 ? d : activityDown * 0.5 + d * 0.5
        activityUp = activityUp == 0 ? u : activityUp * 0.5 + u * 0.5
    }

    /// Byte counters of every physical `en*` interface, straight from the kernel.
    private static func netCounters() -> [String: (down: UInt32, up: UInt32)] {
        var out: [String: (down: UInt32, up: UInt32)] = [:]
        var head: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&head) == 0 else { return out }
        defer { freeifaddrs(head) }
        var p = head
        while let ifa = p {
            defer { p = ifa.pointee.ifa_next }
            guard let addr = ifa.pointee.ifa_addr, addr.pointee.sa_family == UInt8(AF_LINK),
                  let data = ifa.pointee.ifa_data?.assumingMemoryBound(to: if_data.self) else { continue }
            let name = String(cString: ifa.pointee.ifa_name)
            guard name.hasPrefix("en"), name.dropFirst(2).allSatisfy(\.isNumber) else { continue }
            out[name] = (data.pointee.ifi_ibytes, data.pointee.ifi_obytes)
        }
        return out
    }

    private func sampleLivePing() {
        guard !livePingBusy else { return }
        livePingBusy = true
        let host = menuHost
        liveHostName = host.name
        background {
            let ms = Self.pingOnce(host.host)
            let iface = keyValues(sh("/sbin/route", "-n", "get", host.host))["interface"]
            onMain { self.livePing = ms; self.liveIface = iface; self.livePingBusy = false }
        }
    }

    private func rotateTarget() {
        let enabled = targets.filter(\.enabled)
        guard !enabled.isEmpty else { return }
        let t = enabled[targetIndex % enabled.count]
        targetIndex += 1
        ping(t)
    }

    private func ping(_ t: PingTarget) {
        guard !pinging.contains(t.id) else { return }
        pinging.insert(t.id)
        background {
            let ms = Self.pingOnce(t.host)
            let iface = keyValues(sh("/sbin/route", "-n", "get", t.host))["interface"]
            onMain {
                self.pinging.remove(t.id)
                if self.targets.contains(where: { $0.id == t.id }) { self.targetStats[t.id] = TargetStat(ping: ms, iface: iface) }
            }
        }
    }

    /// One ICMP echo. Returns milliseconds, or nil when the host doesn't answer.
    static func pingOnce(_ host: String) -> Int? {
        let out = sh("/sbin/ping", "-c", "1", "-t", "2", "-n", host)
        guard let r = out.range(of: "time=") else { return nil }
        let digits = out[r.upperBound...].prefix { $0.isNumber || $0 == "." }
        return Double(digits).map { Int($0.rounded()) }
    }

    // MARK: Full test

    func start() {
        guard !running else { return }
        error = nil
        samples = []
        live = 0
        progress = 0
        testStart = Date()
        fetchMeta()
        withAnimation(.snappy) { phase = .ping }
        task = Task { await run() }
    }

    func stop() { task?.cancel() }

    private func run() async {
        do {
            let ping = try await measurePing()
            onMain { withAnimation(.snappy) { self.phase = .download } }
            let down = try await measureDownload()
            if down > 0 {
                onMain { withAnimation(.snappy) { self.phase = .upload } }
                let up = try await measureUpload()
                let r = SpeedResult(date: .now, down: down, up: up, ping: ping)
                onMain {
                    withAnimation(.snappy) { self.result = r }
                    self.history.insert(r, at: 0)
                    if self.history.count > 30 { self.history = Array(self.history.prefix(30)) }
                    self.save()
                }
            } else {
                onMain { self.error = "Couldn’t reach speed.cloudflare.com — check your connection." }
            }
        } catch {}   // user pressed stop — keep the last completed result
        onMain { withAnimation(.snappy) { self.phase = .idle; self.live = 0; self.progress = 0 } }
    }

    /// Who the test server thinks we are: IP, ISP/VPN organization, datacenter.
    func fetchMeta() {
        Task {
            var req = URLRequest(url: Self.base.appendingPathComponent("meta"))
            req.setValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15", forHTTPHeaderField: "User-Agent")
            guard let (data, _) = try? await URLSession.shared.data(for: req),
                  let m = try? JSONDecoder().decode(SpeedMeta.self, from: data), m.clientIp != nil else { return }
            onMain { withAnimation(.snappy) { self.meta = m } }
        }
    }

    /// Latency: four 0-byte requests on a kept-alive connection; the first includes the TLS handshake,
    /// so the best of the rest is the real round-trip.
    private func measurePing() async throws -> Int {
        let url = Self.base.appendingPathComponent("__down").appending(queryItems: [URLQueryItem(name: "bytes", value: "0")])
        var ms: [Double] = []
        for i in 0..<4 {
            try Task.checkCancellation()
            var req = URLRequest(url: url)
            req.timeoutInterval = 4
            let t0 = Date()
            _ = try? await URLSession.shared.data(for: req)
            ms.append(Date().timeIntervalSince(t0) * 1000)
            let p = 0.15 * Double(i + 1) / 4
            onMain { self.progress = p }
            try await Task.sleep(for: .milliseconds(120))
        }
        return Int((ms.dropFirst().min() ?? ms.min() ?? 0).rounded())
    }

    /// Downloads 25 MB segments back to back until the time cap. Returns average bytes/s.
    private func measureDownload() async throws -> Double {
        let tracker = TransferTracker()
        let session = URLSession(configuration: .ephemeral, delegate: tracker, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let url = Self.base.appendingPathComponent("__down").appending(queryItems: [URLQueryItem(name: "bytes", value: String(Self.chunkBytes))])
        func newTask() -> URLSessionTask {
            tracker.restart()
            let t = session.dataTask(with: url)
            t.resume()
            return t
        }
        return try await drive(tracker, first: newTask(), makeTask: newTask)
    }

    /// Polls the tracker ~10×/s, publishing the live speed and chart samples, starting a new segment
    /// when one finishes early, and stopping at the time cap.
    private func drive(_ tracker: TransferTracker, first: URLSessionTask,
                       makeTask: () -> URLSessionTask) async throws -> Double {
        let start = Date()
        var last = (t: 0.0, bytes: Int64(0))
        var smoothed: Double = 0
        var task = first
        while true {
            try Task.checkCancellation()
            let snap = tracker.snapshot()
            let elapsed = Date().timeIntervalSince(start)
            let dt = snap.t - last.t
            if dt >= 0.1 {
                let inst = Double(snap.bytes - last.bytes) / dt
                smoothed = smoothed == 0 ? inst : smoothed * 0.55 + inst * 0.45
                publish(smoothed, progress: 0.15 + 0.425 * min(elapsed / Self.phaseSeconds, 1), phase: .download)
                last = snap
            }
            if tracker.isFinished {
                if elapsed < Self.phaseSeconds - 1 { task = makeTask(); continue }
                break
            }
            if elapsed >= Self.phaseSeconds { task.cancel(); break }
            try await Task.sleep(for: .milliseconds(100))
        }
        return tracker.average(ramp: 0.4)
    }

    /// Uploads raw zero chunks over a TLS socket until the time cap, restarting segments as needed.
    private func measureUpload() async throws -> Double {
        let start = Date()
        var offset: Int64 = 0
        var events: [(t: Double, bytes: Int64)] = []
        var up = RawUploader()
        up.start()
        var last = (t: 0.0, bytes: Int64(0))
        var smoothed: Double = 0
        while true {
            try Task.checkCancellation()
            let now = up.snapshot()
            guard !events.isEmpty || now > 0 else {
                if Date().timeIntervalSince(start) >= Self.phaseSeconds { break }
                try await Task.sleep(for: .milliseconds(100)); continue
            }
            let t = Date().timeIntervalSince(start)
            let total = offset + now
            if t - last.t >= 0.1 {
                let inst = Double(total - last.bytes) / (t - last.t)
                smoothed = smoothed == 0 ? inst : smoothed * 0.55 + inst * 0.45
                events.append((t, total))
                publish(smoothed, progress: 0.575 + 0.425 * min(t / Self.phaseSeconds, 1), phase: .upload)
                last = (t, total)
            }
            if up.isFinished {
                if t < Self.phaseSeconds - 1 {
                    offset += up.snapshot()
                    up = RawUploader()
                    up.start()
                    continue
                }
                break
            }
            if t >= Self.phaseSeconds { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        up.cancel()
        return TransferTracker.average(events, ramp: 0.4)
    }

    private func publish(_ value: Double, progress: Double, phase: SpeedPhase) {
        let t = Date().timeIntervalSince(testStart)
        onMain {
            self.live = value
            self.progress = min(0.999, progress)
            self.samples.append(SpeedSample(t: t, phase: phase, value: value))
        }
    }
}

// MARK: - Menu bar panel

/// Compact speed tile: the menu bar host's latency plus live throughput, a run/stop button
/// and a chevron into the full view.
struct SpeedCompact: View {
    @EnvironmentObject var speed: SpeedStore
    @State private var hover = false

    private var running: Bool { speed.running }
    private var bytes: Bool { speed.useBytes }

    /// Current latency of the menu bar host, coloured by how healthy it looks.
    private var pingTint: Color {
        switch speed.livePing {
        case .some(let ms) where ms < 80: return .green
        case .some(let ms) where ms < 200: return .yellow
        case .some: return .red
        case nil: return .secondary
        }
    }

    private var pingText: String { speed.livePing.map { "\($0)" } ?? "—" }

    var body: some View {
        HStack(spacing: 10) {
            // Latency badge
            VStack(spacing: -1) {
                Text(pingText)
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(pingTint)
                    .contentTransition(.numericText())
                Text("ms").font(.system(size: 8, weight: .medium)).foregroundStyle(.tertiary)
            }
            .frame(width: 40, height: 34)
            .background(pingTint.opacity(0.12), in: RoundedRectangle(cornerRadius: 9, style: .continuous))

            // Throughput + host
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 10) {
                    rate("arrow.down", speed.activityDown, .blue)
                    rate("arrow.up", speed.activityUp, .orange)
                }
                .font(.system(size: 11.5, weight: .medium))

                Text(speed.liveHostName)
                    .font(.system(size: 9.5)).foregroundStyle(.tertiary).lineLimit(1)
            }

            Spacer(minLength: 0)

            if running {
                Button { speed.stop() } label: {
                    Image(systemName: "stop.fill")
                        .font(.system(size: 9, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 22, height: 22).background(Circle().fill(Color.red))
                }
                .buttonStyle(.plain).help("Stop test")
            }

            Button { open() } label: {
                Image(systemName: "chevron.right").font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.secondary).frame(width: 16, height: 34).contentShape(Rectangle())
            }
            .buttonStyle(.plain).help("Full speed test view")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity)
        .background(Color.primary.opacity(hover ? 0.1 : 0.055), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(alignment: .bottom) {
            if running {
                GeometryReader { g in
                    Capsule().fill(Color.accentColor)
                        .frame(width: max(8, g.size.width * speed.progress), height: 2)
                }
                .frame(height: 2).padding(.horizontal, 8)
                .animation(.snappy, value: speed.progress)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .onTapGesture { running ? speed.stop() : speed.start() }
    }

    private func rate(_ symbol: String, _ value: Double, _ color: Color) -> some View {
        HStack(spacing: 3) {
            Image(systemName: symbol).font(.system(size: 9, weight: .bold))
            Text(running ? "…" : formatSpeed(value, bytes: bytes)).monospacedDigit()
        }
        .foregroundStyle(running ? AnyShapeStyle(.tertiary) : AnyShapeStyle(color))
    }

    private func open() {
        UserDefaults.standard.set(Pane.speed.rawValue, forKey: "pane")
        MainWindowController.shared.show()
    }
}

// MARK: - Chart

/// Live chart of the running (or last) test: download in blue, upload in orange, one timeline.
struct SpeedChart: View {
    let samples: [SpeedSample]
    let running: Bool

    var body: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            if samples.count < 2 {
                Text(samples.isEmpty ? "Run a test to see the graph" : "…")
                    .font(.callout).foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let maxV = max(1, samples.map(\.value).max() ?? 1)
                let maxT = max(0.001, samples.map(\.t).max() ?? 1)
                let downs = points(samples.filter { $0.phase == .download }, maxT: maxT, maxV: maxV, w: w, h: h)
                let ups = points(samples.filter { $0.phase == .upload }, maxT: maxT, maxV: maxV, w: w, h: h)
                ZStack(alignment: .topLeading) {
                    series(ups, color: .orange, h: h)
                    series(downs, color: .blue, h: h)
                    if let last = samples.last {
                        let p = point(last, maxT: maxT, maxV: maxV, w: w, h: h)
                        let color: Color = last.phase == .download ? .blue : .orange
                        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !running)) { ctx in
                            let pulse = running ? 1 + 0.5 * (0.5 + 0.5 * sin(ctx.date.timeIntervalSinceReferenceDate * 6)) : 1
                            Circle().fill(color)
                                .frame(width: 6, height: 6)
                                .background(Circle().fill(color.opacity(0.25)).scaleEffect(pulse))
                                .position(p)
                        }
                    }
                }
            }
        }
        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private func point(_ s: SpeedSample, maxT: Double, maxV: Double, w: CGFloat, h: CGFloat) -> CGPoint {
        CGPoint(x: s.t / maxT * w, y: h - 1 - s.value / maxV * (h - 4))
    }

    private func points(_ s: [SpeedSample], maxT: Double, maxV: Double, w: CGFloat, h: CGFloat) -> [CGPoint] {
        s.map { point($0, maxT: maxT, maxV: maxV, w: w, h: h) }
    }

    /// Catmull-Rom through the points, converted to cubic Béziers — a smooth curve, not a zig-zag.
    private func curve(_ p: [CGPoint]) -> Path {
        var path = Path()
        guard let first = p.first else { return path }
        path.move(to: first)
        guard p.count > 2 else {
            p.dropFirst().forEach { path.addLine(to: $0) }
            return path
        }
        for i in 0..<p.count - 1 {
            let p0 = p[max(i - 1, 0)]
            let p1 = p[i]
            let p2 = p[i + 1]
            let p3 = p[min(i + 2, p.count - 1)]
            let c1 = CGPoint(x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6)
            let c2 = CGPoint(x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6)
            path.addCurve(to: p2, control1: c1, control2: c2)
        }
        return path
    }

    @ViewBuilder
    private func series(_ p: [CGPoint], color: Color, h: CGFloat) -> some View {
        if p.count > 1 {
            curve(p).fill(color.gradient.opacity(0.18))
            area(p, h: h).fill(color.opacity(0.12))
            curve(p).stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
    }

    private func area(_ p: [CGPoint], h: CGFloat) -> Path {
        var path = curve(p)
        guard let first = p.first, let last = p.last else { return path }
        path.addLine(to: CGPoint(x: last.x, y: h))
        path.addLine(to: CGPoint(x: first.x, y: h))
        path.closeSubpath()
        return path
    }
}

// MARK: - Full window view

struct SpeedView: View {
    @EnvironmentObject var s: SpeedStore
    @State private var editing: EditTarget?

    private var downValue: String { (s.phase == .download ? formatSpeed(s.live, bytes: s.useBytes) : s.result.map { formatSpeed($0.down, bytes: s.useBytes) }) ?? "—" }
    private var upValue: String { (s.phase == .upload ? formatSpeed(s.live, bytes: s.useBytes) : s.result.map { formatSpeed($0.up, bytes: s.useBytes) }) ?? "—" }
    private var pingValue: String {
        if s.phase == .ping { return "…" }
        return s.result.map { "\($0.ping) ms" } ?? "—"
    }

    var body: some View {
        Form {
            Section {
                VStack(spacing: 10) {
                    HStack(spacing: 0) {
                        stat("Ping", "clock", s.livePing.map { "\($0) ms" } ?? "—", .secondary, false)
                        stat("Down", "arrow.down.circle", formatSpeed(s.activityDown, bytes: s.useBytes), .blue, false)
                        stat("Up", "arrow.up.circle", formatSpeed(s.activityUp, bytes: s.useBytes), .orange, false)
                    }
                    if let iface = s.liveIface {
                        Label("\(s.liveHostName) → \(iface)", systemImage: "point.3.connected.trianglepath.dotted")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 2)
            } header: {
                Text("Live")
            } footer: {
                Text("Sampled in the background every couple of seconds: latency to the menu bar host and this Mac's throughput.")
            }

            Section {
                VStack(spacing: 14) {
                    HStack(spacing: 0) {
                        stat("Download", "arrow.down.circle", downValue, .blue, s.phase == .download)
                        stat("Upload", "arrow.up.circle", upValue, .orange, s.phase == .upload)
                        stat("Ping", "clock", pingValue, .secondary, s.phase == .ping)
                    }
                    SpeedChart(samples: s.samples, running: s.running).frame(height: 120)
                    Button {
                        s.running ? s.stop() : s.start()
                    } label: {
                        Label(s.running ? "Stop Test" : "Start Test", systemImage: s.running ? "stop.fill" : "play.fill")
                            .frame(maxWidth: 240)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(s.running ? .red : .accentColor)
                    if let e = s.error {
                        Label(e, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(.orange)
                    }
                }
                .padding(.vertical, 4)
            } header: {
                Text("Cloudflare Speed Test")
            } footer: {
                Text("Measures the path your traffic takes right now — through the VPN or direct, whichever the routing table says.")
            }

            Section {
                if s.targets.isEmpty {
                    Text("No targets yet. Click + to add one.").foregroundStyle(.secondary)
                }
                ForEach(Array(s.targets.enumerated()), id: \.element.id) { i, t in
                    let st = s.targetStats[t.id]
                    HStack {
                        Button {
                            s.menuHostID = t.id
                        } label: {
                            Image(systemName: s.menuHost.id == t.id ? "dot.radiowaves.left.and.right" : "dot.radiowaves.left.and.right")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(s.menuHost.id == t.id ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(.tertiary))
                                .frame(width: 18)
                        }
                        .buttonStyle(.plain)
                        .disabled(!t.enabled)
                        .help("Show this target's latency in the menu bar")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(t.name)
                            Text(t.host + (st?.iface.map { " · via \($0)" } ?? ""))
                                .font(.callout).foregroundStyle(.secondary).monospacedDigit()
                        }
                        Spacer()
                        if t.enabled {
                            Text(st?.ping.map { "\($0) ms" } ?? (st == nil ? "…" : "timeout"))
                                .font(.callout).monospacedDigit()
                                .foregroundStyle(st?.ping == nil && st != nil ? .red : .secondary)
                        } else {
                            Text("off").font(.callout).foregroundStyle(.tertiary)
                        }
                        Toggle("", isOn: Binding(get: { t.enabled }, set: { s.setTarget(t, $0) }))
                            .labelsHidden()
                    }
                    .contextMenu {
                        Button("Edit…") { editing = EditTarget(index: i) }
                        Button("Show in Menu Bar") { s.menuHostID = t.id }.disabled(!t.enabled)
                        Button("Copy Host") { copyToClipboard(t.host) }
                        Divider()
                        Button("Delete", role: .destructive) { s.removeTarget(t) }
                    }
                }
            } header: {
                HStack {
                    Text("Ping Targets")
                    Spacer()
                    Button { editing = EditTarget(index: nil) } label: { Image(systemName: "plus") }
                        .buttonStyle(.borderless).help("Add target")
                }
            } footer: {
                Text("Each enabled target is pinged in turn. Click the broadcast icon to show that target's latency in the menu bar (defaults to Cloudflare).")
                    .font(.footnote).foregroundStyle(.secondary)
            }

            if let m = s.meta {
                Section("Connection") {
                    LabeledContent("Your IP", value: m.clientIp ?? "—")
                    if let org = m.asOrganization { LabeledContent("Network", value: org) }
                    LabeledContent("Server", value: "Cloudflare" + (m.colo?.iata.map { " — \($0)" } ?? ""))
                    let loc = [m.city, m.country].compactMap({ $0 }).joined(separator: ", ")
                    if !loc.isEmpty { LabeledContent("Location", value: loc) }
                }
            }

            Section {
                if s.history.isEmpty {
                    Text("No tests yet.").foregroundStyle(.secondary)
                }
                ForEach(s.history) { r in
                    HStack {
                        Text(r.date, format: .dateTime.month().day().hour().minute())
                        Spacer()
                        Text("↓ " + formatSpeed(r.down, bytes: s.useBytes)).foregroundStyle(.blue)
                        Text("↑ " + formatSpeed(r.up, bytes: s.useBytes)).foregroundStyle(.orange)
                        Text("\(r.ping) ms").foregroundStyle(.secondary)
                    }
                    .font(.callout).monospacedDigit()
                    .contextMenu {
                        Button("Copy Result") {
                            copyToClipboard("↓ \(formatSpeed(r.down, bytes: s.useBytes)) · ↑ \(formatSpeed(r.up, bytes: s.useBytes)) · \(r.ping) ms")
                        }
                    }
                }
            } header: {
                Text("History")
            } footer: {
                if !s.history.isEmpty {
                    Text("The last 30 tests are kept on this Mac.").font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Speed")
        .navigationSubtitle(subtitle)
        .toolbar {
            ToolbarItem {
                Button { s.running ? s.stop() : s.start() } label: {
                    Label(s.running ? "Stop" : "Test Speed", systemImage: s.running ? "stop.fill" : "speedometer")
                }
            }
            ToolbarItem {
                Button { editing = EditTarget(index: nil) } label: { Label("Add Target", systemImage: "plus") }
            }
            ToolbarItem {
                Picker("Units", selection: Binding(get: { s.useBytes }, set: { s.useBytes = $0 })) {
                    Text("Bits (Mbps)").tag(false)
                    Text("Bytes (MB/s)").tag(true)
                }
                .pickerStyle(.segmented)
                .help("Show speeds in bits or bytes per second")
            }
            ToolbarItem {
                Menu {
                    Button("Clear History", role: .destructive) { s.clearHistory() }
                        .disabled(s.history.isEmpty)
                } label: {
                    Label("More", systemImage: "ellipsis.circle")
                }
                .fixedSize()
            }
        }
        .sheet(item: $editing) { TargetEditor(index: $0.index) }
        .onAppear { s.fetchMeta() }
    }

    private var subtitle: String {
        if s.running {
            switch s.phase {
            case .ping: return "Measuring latency…"
            case .download: return "Testing download…"
            case .upload: return "Testing upload…"
            case .idle: return ""
            }
        }
        return s.result.map { "↓ \(formatSpeed($0.down)) · ↑ \(formatSpeed($0.up))" } ?? "Not tested yet"
    }

    private func stat(_ title: String, _ symbol: String, _ value: String, _ color: Color, _ active: Bool) -> some View {
        VStack(spacing: 3) {
            Label(title, systemImage: symbol).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.system(size: 19, weight: .semibold, design: .rounded)).monospacedDigit()
                .foregroundStyle(color).contentTransition(.numericText())
                .animation(.snappy, value: value)
        }
        .frame(maxWidth: .infinity)
        .opacity(active || !s.running ? 1 : 0.45)
    }
}

/// Adds (index nil) or edits a ping target.
struct TargetEditor: View {
    let index: Int?
    @EnvironmentObject var s: SpeedStore
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var host = ""
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                TextField("Name", text: $name, prompt: Text("Cloudflare"))
                TextField("Host", text: $host, prompt: Text("1.1.1.1 or example.com"))
            } header: {
                Text(index == nil ? "New Target" : "Edit Target")
            } footer: {
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
        .frame(width: 380)
        .toolbar {
            if let index {
                ToolbarItem(placement: .destructiveAction) {
                    Button("Delete Target", role: .destructive) { s.removeTarget(s.targets[index]); dismiss() }
                }
            }
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(index == nil ? "Add" : "Save") {
                    error = s.upsertTarget(index, name: name, host: host)
                    if error == nil { dismiss() }
                }
            }
        }
        .onAppear {
            if let index { let t = s.targets[index]; name = t.name; host = t.host }
        }
    }
}
