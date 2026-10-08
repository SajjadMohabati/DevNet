import AppKit
import Carbon.HIToolbox
import SwiftUI

/// System-wide shortcut via Carbon's RegisterEventHotKey (works without Accessibility permission).
enum HotKey {
    private static var handler: (() -> Void)?
    private static var ref: EventHotKeyRef?

    /// Registers ⌃⇧I. Returns false if it couldn't be registered (e.g. another app owns it).
    @discardableResult
    static func register(_ action: @escaping () -> Void) -> Bool {
        handler = action
        guard ref == nil else { return true }
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetEventDispatcherTarget(), { _, _, _ in
            DispatchQueue.main.async { HotKey.handler?() }
            return noErr
        }, 1, &spec, nil, nil)
        let id = EventHotKeyID(signature: OSType(0x44564E54), id: 1)   // "DVNT"
        return RegisterEventHotKey(UInt32(kVK_ANSI_I), UInt32(controlKey | shiftKey), id,
                                   GetEventDispatcherTarget(), 0, &ref) == noErr
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

    private var host: NSHostingView<AnyView>?

    func show() {
        if panel == nil {
            // Standard menu material (like system menus); the SwiftUI content sizes itself.
            let host = NSHostingView(rootView: AnyView(MenuPanel().sharedStores()))
            host.sizingOptions = [.intrinsicContentSize]
            host.translatesAutoresizingMaskIntoConstraints = false
            let fx = NSVisualEffectView()
            fx.material = .menu
            fx.state = .active
            fx.blendingMode = .behindWindow
            fx.wantsLayer = true
            fx.layer?.cornerRadius = 12
            fx.layer?.masksToBounds = true
            fx.addSubview(host)
            NSLayoutConstraint.activate([
                host.topAnchor.constraint(equalTo: fx.topAnchor),
                host.leadingAnchor.constraint(equalTo: fx.leadingAnchor),
                host.trailingAnchor.constraint(equalTo: fx.trailingAnchor),
            ])
            let p = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: 300, height: 400), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
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
            self.host = host
            // Keep the panel's top edge fixed when the content grows/shrinks (e.g. expanding DNS).
            host.postsFrameChangedNotifications = true
            NotificationCenter.default.addObserver(forName: NSView.frameDidChangeNotification, object: host, queue: .main) { [weak self] _ in
                self?.fitHeight()
            }
        }
        guard let panel, let screen = NSScreen.main else { return }
        let size = host?.fittingSize ?? NSSize(width: 300, height: 600)
        let area = screen.visibleFrame
        // Under the status item when it's visible on this screen, otherwise at the top-right corner.
        var x = area.maxX - size.width - 8
        if let b = statusButton(), let w = b.window, w.occlusionState.contains(.visible), w.screen == screen {
            let f = w.convertToScreen(b.convert(b.bounds, to: nil))
            x = min(max(f.midX - size.width / 2, area.minX + 8), area.maxX - size.width - 8)
        }
        panel.setFrame(NSRect(x: x, y: area.maxY - size.height - 6, width: size.width, height: size.height), display: true)
        // A non-activating panel takes the keyboard without switching away from the current app.
        panel.makeKeyAndOrderFront(nil)
        escMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            if e.keyCode == UInt16(kVK_Escape) { self?.hide(); return nil }
            return e
        }
    }

    private func fitHeight() {
        guard let panel, let host, panel.isVisible else { return }
        let h = host.fittingSize.height
        guard abs(h - panel.frame.height) > 0.5 else { return }
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
        let ok = HotKey.register { PanelController.shared.toggle() }
        NSLog("DevNet: hotkey ⌃⇧I registered=%d", ok ? 1 : 0)
        if CommandLine.arguments.contains("--window") { MainWindowController.shared.show() }
        if CommandLine.arguments.contains("--panel") { DispatchQueue.main.asyncAfter(deadline: .now() + 1) { PanelController.shared.toggle() } }
    }
}
