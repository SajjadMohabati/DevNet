// Renders the Liquid Glass–style app icon: swift tools/make_icon.swift out.png
import AppKit
import CoreImage

let S: CGFloat = 1024
let cs = CGColorSpace(name: CGColorSpace.displayP3)!
func canvas() -> CGContext {
    CGContext(data: nil, width: Int(S), height: Int(S), bitsPerComponent: 8, bytesPerRow: 0, space: cs,
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
}
func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor { CGColor(colorSpace: cs, components: [r, g, b, a])! }
func gradient(_ c: [CGColor], _ l: [CGFloat]) -> CGGradient { CGGradient(colorsSpace: cs, colors: c as CFArray, locations: l)! }

let ctx = canvas()

// macOS icon grid: 824pt squircle centred on a 1024 canvas.
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let tilePath = CGPath(roundedRect: tile, cornerWidth: 186, cornerHeight: 186, transform: nil)

// Drop shadow
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 34, color: rgb(0, 0, 0, 0.45))
ctx.addPath(tilePath); ctx.setFillColor(rgb(0.05, 0.08, 0.2)); ctx.fillPath()
ctx.restoreGState()

// Background: deep blue with soft coloured light, blurred so the glass has something to refract.
let bg = canvas()
bg.drawLinearGradient(gradient([rgb(0.04, 0.07, 0.22), rgb(0.06, 0.20, 0.45), rgb(0.02, 0.45, 0.62)], [0, 0.55, 1]),
                      start: CGPoint(x: 150, y: 950), end: CGPoint(x: 900, y: 80), options: [])
for (x, y, r, c) in [(300.0, 760.0, 330.0, rgb(0.45, 0.30, 1.0, 0.95)),
                     (780.0, 300.0, 360.0, rgb(0.0, 0.85, 0.95, 0.9)),
                     (760.0, 820.0, 220.0, rgb(1.0, 0.35, 0.65, 0.55)),
                     (260.0, 260.0, 240.0, rgb(0.15, 0.55, 1.0, 0.8))] {
    bg.drawRadialGradient(gradient([c, rgb(0, 0, 0, 0)], [0, 1]), startCenter: CGPoint(x: x, y: y), startRadius: 0,
                          endCenter: CGPoint(x: x, y: y), endRadius: r, options: [])
}
let full = CGRect(x: 0, y: 0, width: S, height: S)
let blurred = CIImage(cgImage: bg.makeImage()!).clampedToExtent().applyingGaussianBlur(sigma: 40).cropped(to: full)
let bgImage = CIContext().createCGImage(blurred, from: full)!

ctx.saveGState()
ctx.addPath(tilePath); ctx.clip()
ctx.draw(bgImage, in: full)

// Glass slab: a frosted rounded pane floating in the tile.
let pane = tile.insetBy(dx: 120, dy: 120)
let panePath = CGPath(roundedRect: pane, cornerWidth: 130, cornerHeight: 130, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -22), blur: 50, color: rgb(0, 0, 0.1, 0.45))
ctx.addPath(panePath); ctx.setFillColor(rgb(1, 1, 1, 0.14)); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addPath(panePath); ctx.clip()
ctx.drawLinearGradient(gradient([rgb(1, 1, 1, 0.38), rgb(1, 1, 1, 0.06), rgb(1, 1, 1, 0.16)], [0, 0.55, 1]),
                       start: CGPoint(x: pane.minX, y: pane.maxY), end: CGPoint(x: pane.maxX, y: pane.minY), options: [])
ctx.drawRadialGradient(gradient([rgb(1, 1, 1, 0.45), rgb(1, 1, 1, 0)], [0, 1]),
                       startCenter: CGPoint(x: pane.minX + 120, y: pane.maxY - 40), startRadius: 0,
                       endCenter: CGPoint(x: pane.minX + 120, y: pane.maxY - 40), endRadius: 360, options: [])
ctx.restoreGState()
// Rim light: bright on the top-left edge, fading to the bottom-right.
ctx.saveGState()
ctx.addPath(panePath); ctx.setLineWidth(7); ctx.replacePathWithStrokedPath(); ctx.clip()
ctx.drawLinearGradient(gradient([rgb(1, 1, 1, 0.95), rgb(1, 1, 1, 0.15), rgb(0.6, 0.95, 1, 0.7)], [0, 0.5, 1]),
                       start: CGPoint(x: pane.minX, y: pane.maxY), end: CGPoint(x: pane.maxX, y: pane.minY), options: [])
ctx.restoreGState()

// Glyph: a route that splits — one way through the tunnel, one straight to the local network.
let cfg = NSImage.SymbolConfiguration(pointSize: 300, weight: .semibold)
let sym = NSImage(systemSymbolName: "arrow.triangle.branch", accessibilityDescription: nil)!.withSymbolConfiguration(cfg)!
var proposed = CGRect(origin: .zero, size: sym.size)
let glyph = sym.cgImage(forProposedRect: &proposed, context: nil, hints: nil)!
let gs = sym.size
let gRect = CGRect(x: (S - gs.width) / 2, y: (S - gs.height) / 2 - 6, width: gs.width, height: gs.height)
// Shadow pass, then the gradient-filled glyph on top.
let shadow = canvas()
shadow.setShadow(offset: CGSize(width: 0, height: -12), blur: 26, color: rgb(0, 0.05, 0.25, 0.6))
shadow.beginTransparencyLayer(auxiliaryInfo: nil)
shadow.clip(to: gRect, mask: glyph)
shadow.setFillColor(rgb(1, 1, 1)); shadow.fill(gRect)
shadow.endTransparencyLayer()
ctx.draw(shadow.makeImage()!, in: full)
ctx.saveGState()
ctx.clip(to: gRect, mask: glyph)
ctx.drawLinearGradient(gradient([rgb(1, 1, 1), rgb(0.80, 0.94, 1)], [0, 1]),
                       start: CGPoint(x: 0, y: gRect.maxY), end: CGPoint(x: 0, y: gRect.minY), options: [])
ctx.restoreGState()

// Outer tile rim
ctx.addPath(tilePath); ctx.setLineWidth(5); ctx.replacePathWithStrokedPath(); ctx.clip()
ctx.drawLinearGradient(gradient([rgb(1, 1, 1, 0.6), rgb(1, 1, 1, 0.05)], [0, 1]),
                       start: CGPoint(x: 0, y: tile.maxY), end: CGPoint(x: 0, y: tile.minY), options: [])
ctx.restoreGState()

let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
