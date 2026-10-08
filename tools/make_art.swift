// Renders marketing art in the app's glass style.
//   swift tools/make_art.swift dmg  out.png               DMG window background (1320×800, @2x)
//   swift tools/make_art.swift hero out.png icon.png panel.png   README hero
// Created by Sajjad Mohabati — https://github.com/SajjadMohabati/DevNet
import AppKit
import CoreImage

let args = CommandLine.arguments
let cs = CGColorSpace(name: CGColorSpace.displayP3)!
func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor { CGColor(colorSpace: cs, components: [r, g, b, a])! }
func gradient(_ c: [CGColor], _ l: [CGFloat]) -> CGGradient { CGGradient(colorsSpace: cs, colors: c as CFArray, locations: l)! }

/// Night-blue backdrop with blurred colour light, matching the icon.
func backdrop(_ w: CGFloat, _ h: CGFloat) -> CGImage {
    let c = CGContext(data: nil, width: Int(w), height: Int(h), bitsPerComponent: 8, bytesPerRow: 0, space: cs,
                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    c.drawLinearGradient(gradient([rgb(0.04, 0.06, 0.18), rgb(0.06, 0.16, 0.38), rgb(0.02, 0.32, 0.48)], [0, 0.6, 1]),
                         start: CGPoint(x: 0, y: h), end: CGPoint(x: w, y: 0), options: [])
    for (x, y, r, col) in [(0.15, 0.85, 0.45, rgb(0.45, 0.30, 1.0, 0.8)), (0.85, 0.2, 0.5, rgb(0.0, 0.8, 0.95, 0.65)),
                           (0.8, 0.95, 0.3, rgb(1.0, 0.35, 0.65, 0.35)), (0.1, 0.1, 0.35, rgb(0.15, 0.5, 1.0, 0.6))] {
        let p = CGPoint(x: x * w, y: y * h)
        c.drawRadialGradient(gradient([col, rgb(0, 0, 0, 0)], [0, 1]), startCenter: p, startRadius: 0, endCenter: p,
                             endRadius: r * max(w, h), options: [])
    }
    let full = CGRect(x: 0, y: 0, width: w, height: h)
    let img = CIImage(cgImage: c.makeImage()!).clampedToExtent().applyingGaussianBlur(sigma: 60).cropped(to: full)
    return CIContext().createCGImage(img, from: full)!
}

func text(_ s: String, size: CGFloat, weight: NSFont.Weight, alpha: CGFloat = 1, at p: CGPoint, center: Bool = false) {
    let attr: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: size, weight: weight),
                                               .foregroundColor: NSColor.white.withAlphaComponent(alpha)]
    let a = NSAttributedString(string: s, attributes: attr)
    a.draw(at: CGPoint(x: center ? p.x - a.size().width / 2 : p.x, y: p.y))
}

func glassPill(_ r: CGRect, radius: CGFloat, in c: CGContext) {
    let path = CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil)
    c.saveGState(); c.addPath(path); c.setFillColor(rgb(1, 1, 1, 0.10)); c.fillPath(); c.restoreGState()
    c.saveGState(); c.addPath(path); c.setLineWidth(2); c.replacePathWithStrokedPath(); c.clip()
    c.drawLinearGradient(gradient([rgb(1, 1, 1, 0.7), rgb(1, 1, 1, 0.08)], [0, 1]),
                         start: CGPoint(x: r.minX, y: r.maxY), end: CGPoint(x: r.maxX, y: r.minY), options: [])
    c.restoreGState()
}

func render(_ w: CGFloat, _ h: CGFloat, _ draw: (CGContext) -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(w), pixelsHigh: Int(h), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let c = NSGraphicsContext.current!.cgContext
    c.draw(backdrop(w, h), in: CGRect(x: 0, y: 0, width: w, height: h))
    draw(c)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func image(_ path: String) -> CGImage {
    var r = CGRect.zero
    return NSImage(contentsOfFile: path)!.cgImage(forProposedRect: &r, context: nil, hints: nil)!
}

let rep: NSBitmapImageRep
switch args[1] {
case "dmg":
    // Finder places the icons at (165,200) and (495,200) in a 660×400 window; this is the @2x canvas.
    rep = render(1320, 800) { c in
        text("Install DevNet", size: 44, weight: .bold, at: CGPoint(x: 660, y: 680), center: true)
        text("Drag DevNet into your Applications folder", size: 24, weight: .medium, alpha: 0.75, at: CGPoint(x: 660, y: 632), center: true)
        glassPill(CGRect(x: 180, y: 220, width: 300, height: 300), radius: 64, in: c)
        glassPill(CGRect(x: 840, y: 220, width: 300, height: 300), radius: 64, in: c)
        // Arrow
        c.setStrokeColor(rgb(1, 1, 1, 0.85)); c.setLineWidth(9); c.setLineCap(.round); c.setLineJoin(.round)
        c.move(to: CGPoint(x: 540, y: 400)); c.addLine(to: CGPoint(x: 775, y: 400)); c.strokePath()
        c.move(to: CGPoint(x: 740, y: 440)); c.addLine(to: CGPoint(x: 782, y: 400)); c.addLine(to: CGPoint(x: 740, y: 360)); c.strokePath()
        text("Then open DevNet from the menu bar  ·  ⌃⇧I", size: 22, weight: .regular, alpha: 0.7, at: CGPoint(x: 660, y: 120), center: true)
        text("Created by Sajjad Mohabati  ·  github.com/SajjadMohabati/DevNet", size: 20, weight: .medium, alpha: 0.55,
             at: CGPoint(x: 660, y: 56), center: true)
    }
case "hero":
    let icon = image(args[3]), panel = image(args[4])
    let W: CGFloat = 2400, H: CGFloat = 1400
    rep = render(W, H) { c in
        c.draw(icon, in: CGRect(x: 150, y: 820, width: 380, height: 380))
        text("DevNet", size: 150, weight: .bold, at: CGPoint(x: 190, y: 600))
        text("Split tunneling for macOS developers.", size: 58, weight: .semibold, alpha: 0.9, at: CGPoint(x: 196, y: 500))
        text("Route networks, domains and whole countries around", size: 44, weight: .regular, alpha: 0.7, at: CGPoint(x: 196, y: 400))
        text("your VPN — plus DNS switching and dev servers.", size: 44, weight: .regular, alpha: 0.7, at: CGPoint(x: 196, y: 345))
        text("Native SwiftUI · Liquid Glass · Menu bar · ⌃⇧I", size: 36, weight: .medium, alpha: 0.55, at: CGPoint(x: 196, y: 230))
        text("Created by Sajjad Mohabati", size: 32, weight: .medium, alpha: 0.45, at: CGPoint(x: 196, y: 150))
        // Panel screenshot as a floating glass card.
        let ph: CGFloat = 1220, pw = ph * CGFloat(panel.width) / CGFloat(panel.height)
        let pr = CGRect(x: W - pw - 170, y: (H - ph) / 2, width: pw, height: ph)
        let path = CGPath(roundedRect: pr, cornerWidth: 40, cornerHeight: 40, transform: nil)
        c.saveGState()
        c.setShadow(offset: CGSize(width: 0, height: -30), blur: 80, color: rgb(0, 0, 0.05, 0.6))
        c.addPath(path); c.setFillColor(rgb(0.12, 0.12, 0.14)); c.fillPath()
        c.restoreGState()
        c.saveGState(); c.addPath(path); c.clip(); c.draw(panel, in: pr); c.restoreGState()
        glassPill(pr, radius: 40, in: c)
    }
default: fatalError("usage: make_art dmg|hero out.png …")
}
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
