import AppKit

// MARK: - IPv4 helpers

func parseIP(_ s: String) -> UInt32? {
    let o = s.trimmingCharacters(in: .whitespaces).split(separator: ".", omittingEmptySubsequences: false).compactMap { UInt32($0) }
    guard o.count == 4, o.allSatisfy({ $0 < 256 }) else { return nil }
    return o.reduce(0) { $0 << 8 | $1 }
}

func ipString(_ n: UInt32) -> String { (0..<4).map { String(n >> (24 - 8 * $0) & 255) }.joined(separator: ".") }

/// "10.20.30.5/24" -> ("10.20.30.0/24", "10.20.30.0", "255.255.255.0")
func parseCIDR(_ s: String) -> (cidr: String, addr: String, mask: String)? {
    let p = s.trimmingCharacters(in: .whitespaces).split(separator: "/")
    guard p.count == 2, let bits = Int(p[1]), (0...32).contains(bits), let ip = parseIP(String(p[0])) else { return nil }
    let m: UInt32 = bits == 0 ? 0 : UInt32.max << (32 - bits)
    return ("\(ipString(ip & m))/\(bits)", ipString(ip & m), ipString(m))
}

// MARK: - Shell

/// Runs a command and returns its stdout.
func sh(_ path: String, _ args: String...) -> String { sh(path, args) }
func sh(_ path: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = Pipe()
    guard (try? p.run()) != nil else { return "" }
    let out = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    p.waitUntilExit()
    return out
}

/// Parses "key: value" lines (output of `route get`, etc.).
func keyValues(_ s: String) -> [String: String] {
    var f: [String: String] = [:]
    for line in s.split(separator: "\n") {
        let kv = line.split(separator: ":", maxSplits: 1)
        if kv.count == 2 { f[kv[0].trimmingCharacters(in: .whitespaces)] = kv[1].trimmingCharacters(in: .whitespaces) }
    }
    return f
}

typealias Cmd = [String]   // argv

/// True if sudoers lets us run `cmd` without a password (see sudoers/devnet).
func sudoAllowed(_ cmd: Cmd) -> Bool {
    !sh("/usr/bin/sudo", ["-n", "-l"] + cmd).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
}

/// Runs commands as root: passwordless via sudo when sudoers allows it, otherwise via the macOS password dialog.
/// Failures of individual commands are ignored; callers re-read state afterwards.
/// Returns nil on success, "" if the user cancelled, or an error message.
func runAdmin(_ cmds: [Cmd]) -> String? {
    guard !cmds.isEmpty else { return nil }
    // Check each distinct command shape once (e.g. "route -n add -net"), not every command.
    if Set(cmds.map { Array($0.prefix(4)) + ["0.0.0.0/0"] }).allSatisfy(sudoAllowed) {
        // Commands for the same destination (e.g. delete then add) must run in order;
        // different destinations are independent and run in parallel.
        var groups: [[Cmd]] = []
        var index: [[String]: Int] = [:]
        for c in cmds {
            let key = Array(c.dropFirst(3).prefix(2))   // route: ["-net", cidr]; others: their arguments
            if let i = index[key] { groups[i].append(c) } else { index[key] = groups.count; groups.append([c]) }
        }
        DispatchQueue.concurrentPerform(iterations: groups.count) { i in
            for c in groups[i] { _ = sh("/usr/bin/sudo", ["-n"] + c) }
        }
        return nil
    }
    // Single-quote each argument for the shell; reject anything that could break out of the quoting.
    guard !cmds.joined().contains(where: { $0.contains(where: { "'\"\\".contains($0) }) }) else { return "Invalid characters in command" }
    let lines = cmds.map { $0.map { "'\($0)'" }.joined(separator: " ") + " >/dev/null 2>&1" }
    let script = "do shell script \"" + (lines + ["true"]).joined(separator: "; ") + "\" with administrator privileges"
    var err: NSDictionary?
    NSApp.activate(ignoringOtherApps: true)
    NSAppleScript(source: script)?.executeAndReturnError(&err)
    guard let err else { return nil }
    return (err[NSAppleScript.errorNumber] as? Int) == -128 ? "" : err[NSAppleScript.errorMessage] as? String ?? "Error"
}

func background(_ work: @escaping () -> Void) { DispatchQueue.global(qos: .userInitiated).async(execute: work) }
func onMain(_ work: @escaping () -> Void) { DispatchQueue.main.async(execute: work) }

func copyToClipboard(_ s: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(s, forType: .string)
}

/// Opens a folder with an installed app (by bundle id).
func open(_ path: String, withApp bundleID: String) {
    guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else { return }
    NSWorkspace.shared.open([URL(fileURLWithPath: path)], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
}

func isInstalled(_ bundleID: String) -> Bool { NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) != nil }

// MARK: - App info & privileged setup

enum AppInfo {
    static let author = "Sajjad Mohabati"
    static let repo = URL(string: "https://github.com/SajjadMohabati/DevNet")!
    static let profile = URL(string: "https://github.com/SajjadMohabati")!
    static var version: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0" }

    /// True once install.sh has put the DNS helper and sudoers rule in place.
    static var passwordless: Bool {
        FileManager.default.isExecutableFile(atPath: DNSStore.helper) && sudoAllowed([DNSStore.helper, "reset"])
    }

    /// Runs the bundled install.sh as root (one password prompt). Returns nil on success.
    static func enablePasswordless() -> String? {
        guard let res = Bundle.main.resourcePath, FileManager.default.fileExists(atPath: res + "/install.sh") else {
            return "install.sh is missing from the app bundle"
        }
        return runAdmin([["/bin/sh", res + "/install.sh", NSUserName()]])
    }

    static func showAbout() {
        let credits = NSMutableAttributedString(string: "Created by \(author)\n", attributes: [.font: NSFont.systemFont(ofSize: 11)])
        credits.append(NSAttributedString(string: "github.com/SajjadMohabati/DevNet",
                                          attributes: [.link: repo, .font: NSFont.systemFont(ofSize: 11)]))
        let p = NSMutableParagraphStyle(); p.alignment = .center
        credits.addAttribute(.paragraphStyle, value: p, range: NSRange(location: 0, length: credits.length))
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits])
    }
}
