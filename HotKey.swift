import AppKit
import Carbon.HIToolbox
import SwiftUI

struct Shortcut: Equatable {
    var keyCode: UInt32
    /// Carbon modifier flags (`cmdKey`, `shiftKey`, …).
    var modifiers: UInt32

    /// Builds a shortcut from a key press. Requires ⌘, ⌥ or ⌃ so plain typing is never hijacked.
    init?(event: NSEvent) {
        let flags = event.modifierFlags
        var modifiers: UInt32 = 0
        if flags.contains(.command) { modifiers |= UInt32(cmdKey) }
        if flags.contains(.option) { modifiers |= UInt32(optionKey) }
        if flags.contains(.control) { modifiers |= UInt32(controlKey) }
        guard modifiers != 0 else { return nil }
        if flags.contains(.shift) { modifiers |= UInt32(shiftKey) }
        self.init(keyCode: UInt32(event.keyCode), modifiers: modifiers)
    }

    init(keyCode: UInt32, modifiers: UInt32) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }

    /// Modifier symbols in Apple's order, then the key: ["⌃", "⇧", "I"].
    var keys: [String] {
        let symbols = [(controlKey, "⌃"), (optionKey, "⌥"), (shiftKey, "⇧"), (cmdKey, "⌘")]
        return symbols.filter { modifiers & UInt32($0.0) != 0 }.map(\.1) + [Self.name(of: Int(keyCode))]
    }

    private static func name(of code: Int) -> String {
        // ANSI key codes 0x00–0x2F in order.
        let ansi = Array("ASDFHGZXCV§BQWERYT123465=97-80]OU[IP↩LJ'K;\\,/NM.")
        if code < ansi.count { return String(ansi[code]) }
        let special = [
            kVK_Tab: "⇥", kVK_Space: "Space", kVK_ANSI_Grave: "`", kVK_Delete: "⌫",
            kVK_LeftArrow: "←", kVK_RightArrow: "→", kVK_DownArrow: "↓", kVK_UpArrow: "↑",
            kVK_F1: "F1", kVK_F2: "F2", kVK_F3: "F3", kVK_F4: "F4", kVK_F5: "F5", kVK_F6: "F6",
            kVK_F7: "F7", kVK_F8: "F8", kVK_F9: "F9", kVK_F10: "F10", kVK_F11: "F11", kVK_F12: "F12",
        ]
        return special[code] ?? "Key \(code)"
    }

    /// The saved shortcut; ⌃⇧I until the user records another.
    static var saved: Shortcut {
        get {
            let d = UserDefaults.standard
            guard d.object(forKey: "shortcutKeyCode") != nil else { return Shortcut(keyCode: UInt32(kVK_ANSI_I), modifiers: UInt32(controlKey | shiftKey)) }
            return Shortcut(keyCode: UInt32(d.integer(forKey: "shortcutKeyCode")), modifiers: UInt32(d.integer(forKey: "shortcutModifiers")))
        }
        set {
            UserDefaults.standard.set(Int(newValue.keyCode), forKey: "shortcutKeyCode")
            UserDefaults.standard.set(Int(newValue.modifiers), forKey: "shortcutModifiers")
        }
    }
}

/// A single system-wide hotkey registered through Carbon (works without Accessibility permission).
final class HotKey {
    static let shared = HotKey()

    private var handler: EventHandlerRef?
    private var ref: EventHotKeyRef?
    private var action: () -> Void = {}

    func install(_ action: @escaping () -> Void) {
        self.action = action
        guard handler == nil else { return }
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetEventDispatcherTarget(), { _, _, _ in
            DispatchQueue.main.async { HotKey.shared.action() }
            return noErr
        }, 1, &spec, nil, &handler)
    }

    func register(_ shortcut: Shortcut) {
        unregister()
        let id = EventHotKeyID(signature: 0x4456_4E54, id: 1)   // "DVNT"
        RegisterEventHotKey(shortcut.keyCode, shortcut.modifiers, id, GetEventDispatcherTarget(), 0, &ref)
    }

    func unregister() {
        if let ref { UnregisterEventHotKey(ref) }
        ref = nil
    }
}

/// Shows the shortcut as key caps; click to record a new one.
struct ShortcutRecorder: View {
    @State private var shortcut = Shortcut.saved
    @State private var monitor: Any?

    private var recording: Bool { monitor != nil }

    var body: some View {
        Button {
            recording ? stop() : start()
        } label: {
            HStack(spacing: 3) {
                if recording {
                    Text("Press keys…").font(.system(size: 11, weight: .medium)).foregroundStyle(.tint).padding(.horizontal, 6)
                } else {
                    ForEach(Array(shortcut.keys.enumerated()), id: \.offset) { _, key in
                        Text(key).font(.system(size: 11, weight: .medium))
                            .frame(minWidth: 18, minHeight: 18).padding(.horizontal, 2)
                            .background(Color.primary.opacity(0.1), in: .rect(cornerRadius: 5))
                    }
                }
            }
            .frame(minHeight: 22)
            .padding(.horizontal, 3)
            .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(recording ? Color.accentColor : .clear, lineWidth: 1.5) }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .help("Click, then press the new shortcut. Esc cancels.")
        .onDisappear(perform: stop)
    }

    private func start() {
        // Free the current shortcut so pressing it again can be recorded.
        HotKey.shared.unregister()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == UInt16(kVK_Escape) {
                stop()
            } else if let recorded = Shortcut(event: event) {
                shortcut = recorded
                Shortcut.saved = recorded
                stop()
            }
            return nil
        }
    }

    private func stop() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        HotKey.shared.register(shortcut)
    }
}

/// Stores shared by the menu bar panel and the main window.
enum Shared {
    static let routes = Store()
    static let procs = ProcStore()
    static let dns = DNSStore()
    static let net = NetStore()
}

extension View {
    func sharedStores() -> some View {
        environmentObject(Shared.routes).environmentObject(Shared.procs).environmentObject(Shared.dns).environmentObject(Shared.net)
    }
}

/// The main window, managed in AppKit so it can be opened from anywhere (shortcut, menu, launch flag).
final class MainWindowController: NSObject, NSWindowDelegate {
    static let shared = MainWindowController()
    private var window: NSWindow?

    var isFrontmost: Bool { window?.isVisible == true && window?.isKeyWindow == true && NSApp.isActive }

    func toggle() { isFrontmost ? window?.performClose(nil) : show() }

    func show() {
        if window == nil {
            let host = NSHostingController(rootView: MainWindow().sharedStores().frame(minWidth: 680, minHeight: 440))
            host.sceneBridgingOptions = [.toolbars, .title]
            let w = NSWindow(contentViewController: host)
            w.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
            w.title = "DevNet"
            w.isReleasedWhenClosed = false
            w.delegate = self
            w.setContentSize(NSSize(width: 820, height: 560))
            if !w.setFrameUsingName("DevNetMain") { w.center() }
            w.setFrameAutosaveName("DevNetMain")
            window = w
        }
        NSApp.setActivationPolicy(.regular)     // show in Dock and ⌘-Tab while the window is open
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func windowWillClose(_ notification: Notification) { NSApp.setActivationPolicy(.accessory) }
}

/// The menu bar panel's content in our own floating window, so the shortcut works even when the
/// status item is hidden (e.g. behind the notch when the menu bar is crowded).
final class KeyPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class PanelController: NSObject, NSWindowDelegate {
    static let shared = PanelController()
    private var panel: KeyPanel?
    private var escMonitor: Any?

    func toggle() { panel?.isVisible == true ? hide() : show() }

    private var height: CGFloat = 420
    private let width: CGFloat = 330    // MenuPanel's fixed width

    func show() {
        if panel == nil {
            // The content reports its own height; the panel follows it with its top edge fixed.
            let root = MenuPanel().sharedStores()
                .fixedSize(horizontal: false, vertical: true)
                .onGeometryChange(for: CGFloat.self, of: { $0.size.height }) { [weak self] h in self?.setHeight(h) }
                .frame(maxHeight: .infinity, alignment: .top)
            let host = NSHostingView(rootView: root)
            host.sizingOptions = []
            host.safeAreaRegions = []
            let fx = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: width, height: height))
            fx.material = .menu
            fx.state = .active
            fx.blendingMode = .behindWindow
            // Rounded corners: a visual effect view is clipped with a stretchable mask image, not a layer radius.
            let r: CGFloat = 14
            let mask = NSImage(size: NSSize(width: r * 2 + 1, height: r * 2 + 1), flipped: false) { rect in
                NSColor.black.setFill()
                NSBezierPath(roundedRect: rect, xRadius: r, yRadius: r).fill()
                return true
            }
            mask.capInsets = NSEdgeInsets(top: r, left: r, bottom: r, right: r)
            mask.resizingMode = .stretch
            fx.maskImage = mask
            host.frame = fx.bounds
            host.autoresizingMask = [.width, .height]
            fx.addSubview(host)
            let p = KeyPanel(contentRect: fx.frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.contentView = fx
            p.isFloatingPanel = true
            p.level = .statusBar
            p.hidesOnDeactivate = false
            p.isReleasedWhenClosed = false
            p.isMovable = false
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            p.backgroundColor = .clear
            p.isOpaque = false
            p.hasShadow = true
            p.delegate = self
            panel = p
        }
        guard let panel, let screen = NSScreen.main else { return }
        let area = screen.visibleFrame
        // Under the status item when it's visible on this screen, otherwise at the top-right corner.
        var x = area.maxX - width - 8
        if let b = statusButton(), let w = b.window, w.occlusionState.contains(.visible), w.screen == screen {
            let f = w.convertToScreen(b.convert(b.bounds, to: nil))
            x = min(max(f.midX - width / 2, area.minX + 8), area.maxX - width - 8)
        }
        panel.setFrame(NSRect(x: x, y: area.maxY - height - 6, width: width, height: height), display: true)
        // A non-activating panel takes the keyboard without switching away from the current app.
        panel.makeKeyAndOrderFront(nil)
        escMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            if e.keyCode == UInt16(kVK_Escape) { self?.hide(); return nil }
            return e
        }
    }

    private func setHeight(_ h: CGFloat) {
        guard h > 0, abs(h - height) > 0.5 else { return }
        height = h
        guard let panel else { return }
        var f = panel.frame
        f.origin.y += f.height - h
        f.size.height = h
        panel.setFrame(f, display: true)
    }

    func hide() {
        panel?.orderOut(nil)
        if let m = escMonitor { NSEvent.removeMonitor(m); escMonitor = nil }
    }

    func windowDidResignKey(_ notification: Notification) { hide() }

    private func statusButton() -> NSStatusBarButton? {
        func find(_ v: NSView?) -> NSStatusBarButton? {
            guard let v else { return nil }
            if let b = v as? NSStatusBarButton { return b }
            return v.subviews.lazy.compactMap { find($0) }.first
        }
        return find(NSApp.windows.first { $0.className.contains("NSStatusBarWindow") }?.contentView)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        HotKey.shared.install { PanelController.shared.toggle() }
        HotKey.shared.register(Shortcut.saved)
        if CommandLine.arguments.contains("--window") { MainWindowController.shared.show() }
        if CommandLine.arguments.contains("--panel") { DispatchQueue.main.asyncAfter(deadline: .now() + 1) { PanelController.shared.toggle() } }
    }
}
