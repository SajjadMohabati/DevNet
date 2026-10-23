// Converts Lucide (ISC) stroke icons into filled GTK symbolic icons.
// GTK recolours symbolic icons by filling every shape, which turns stroke-only icons into blobs,
// so each stroke is expanded into its outline here (CoreGraphics) and written back as one path.
//
//   swift linux/tools/make_icons.swift <lucide-static/icons> linux/src/devnet/resources/hicolor/scalable/actions
// (They must sit in a hicolor theme folder: GTK only recolours symbolic icons found through a theme.)
import CoreGraphics
import Foundation

let width: CGFloat = 1.75   // a touch lighter than Lucide's 2, closer to SF Symbols' regular weight

// devnet name -> Lucide name
let icons: [String: String] = [
    "routes": "split", "projects": "server", "dns": "globe", "speed": "gauge",
    "local": "laptop", "isp": "earth", "tunnel": "shield", "tunnel-default": "shield-check",
    "copy": "copy", "check": "check", "chevron-right": "chevron-right", "chevron-down": "chevron-down",
    "window": "app-window", "quit": "power", "add": "plus", "more": "ellipsis", "refresh": "rotate-cw",
    "play": "play", "stop": "square", "close": "circle-x", "down": "arrow-down", "up": "arrow-up",
    "clock": "clock", "info": "info", "warning": "triangle-alert", "key": "key-round", "flag": "flag",
    "network": "waypoints", "domain": "globe", "trash": "trash-2", "folder": "folder-open",
    "edit": "pencil", "star": "star", "tools": "wrench", "radio": "radio", "list": "list",
    "package": "package", "menu": "menu", "monitor": "monitor", "lock": "lock", "terminal": "square-terminal",
    "broadcast": "radio-tower", "vpn": "shield-half", "wired": "ethernet-port",
]

// MARK: - Minimal SVG geometry (the subset Lucide uses)

func attr(_ tag: String, _ name: String) -> String? {
    guard let r = tag.range(of: "\\s\(name)=\"([^\"]*)\"", options: .regularExpression) else { return nil }
    let s = tag[r]
    return String(s[s.index(after: s.firstIndex(of: "\"")!)..<s.index(before: s.endIndex)])
}

func num(_ tag: String, _ name: String) -> CGFloat { CGFloat(Double(attr(tag, name) ?? "0") ?? 0) }

/// Splits path data into commands and numbers (handles "1.5.5", "-1-2", "1e-3").
func tokens(_ d: String) -> [String] {
    var out: [String] = [], cur = ""
    var prev: Character = " "
    for c in d {
        if c.isLetter && c != "e" && c != "E" {
            if !cur.isEmpty { out.append(cur); cur = "" }
            out.append(String(c))
        } else if c == "," || c == " " || c == "\n" || c == "\t" {
            if !cur.isEmpty { out.append(cur); cur = "" }
        } else if c == "-" && !cur.isEmpty && prev != "e" && prev != "E" {
            out.append(cur); cur = "-"
        } else if c == "." && cur.contains(".") && !cur.contains("e") {
            out.append(cur); cur = "."
        } else {
            cur.append(c)
        }
        prev = c
    }
    if !cur.isEmpty { out.append(cur) }
    return out
}

/// SVG elliptical arc -> cubic Béziers (endpoint parameterisation, SVG spec F.6).
func addArc(_ p: CGMutablePath, from p0: CGPoint, rx rx0: CGFloat, ry ry0: CGFloat, phi deg: CGFloat,
            large: Bool, sweep: Bool, to p1: CGPoint) {
    if p0 == p1 { return }
    var rx = abs(rx0), ry = abs(ry0)
    if rx == 0 || ry == 0 { p.addLine(to: p1); return }
    let phi = deg * .pi / 180, c = cos(phi), s = sin(phi)
    let dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2
    let x1 = c * dx + s * dy, y1 = -s * dx + c * dy
    let lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lambda > 1 { rx *= sqrt(lambda); ry *= sqrt(lambda) }
    let num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    let den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    var k = sqrt(max(0, num / den))
    if large == sweep { k = -k }
    let cx1 = k * rx * y1 / ry, cy1 = -k * ry * x1 / rx
    let cx = c * cx1 - s * cy1 + (p0.x + p1.x) / 2, cy = s * cx1 + c * cy1 + (p0.y + p1.y) / 2
    func angle(_ ux: CGFloat, _ uy: CGFloat, _ vx: CGFloat, _ vy: CGFloat) -> CGFloat {
        let a = atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    }
    let t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    var dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if !sweep && dt > 0 { dt -= 2 * .pi } else if sweep && dt < 0 { dt += 2 * .pi }
    let segs = Int(ceil(abs(dt) / (.pi / 2)))
    let delta = dt / CGFloat(segs)
    let t = 4.0 / 3.0 * tan(delta / 4)
    var a = t1
    func pt(_ ang: CGFloat) -> CGPoint {
        CGPoint(x: cx + rx * cos(ang) * c - ry * sin(ang) * s, y: cy + rx * cos(ang) * s + ry * sin(ang) * c)
    }
    func deriv(_ ang: CGFloat) -> CGPoint {
        CGPoint(x: -rx * sin(ang) * c - ry * cos(ang) * s, y: -rx * sin(ang) * s + ry * cos(ang) * c)
    }
    for _ in 0..<segs {
        let b = a + delta
        let pa = pt(a), pb = pt(b), da = deriv(a), db = deriv(b)
        p.addCurve(to: pb, control1: CGPoint(x: pa.x + t * da.x, y: pa.y + t * da.y),
                   control2: CGPoint(x: pb.x - t * db.x, y: pb.y - t * db.y))
        a = b
    }
}

func pathFrom(_ d: String) -> CGMutablePath {
    let p = CGMutablePath()
    let t = tokens(d)
    var i = 0, cmd: Character = "M"
    var cur = CGPoint.zero, start = CGPoint.zero, lastCtl: CGPoint? = nil, lastQ: CGPoint? = nil
    func n() -> CGFloat { defer { i += 1 }; return CGFloat(Double(t[i]) ?? 0) }
    while i < t.count {
        if let ch = t[i].first, t[i].count == 1, ch.isLetter { cmd = ch; i += 1 }
        let rel = cmd.isLowercase
        func P(_ x: CGFloat, _ y: CGFloat) -> CGPoint { rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y) }
        switch cmd.uppercased().first! {
        case "M":
            cur = P(n(), n()); start = cur; p.move(to: cur); cmd = rel ? "l" : "L"; lastCtl = nil; lastQ = nil
        case "L": cur = P(n(), n()); p.addLine(to: cur); lastCtl = nil; lastQ = nil
        case "H": let x = n(); cur = CGPoint(x: rel ? cur.x + x : x, y: cur.y); p.addLine(to: cur); lastCtl = nil; lastQ = nil
        case "V": let y = n(); cur = CGPoint(x: cur.x, y: rel ? cur.y + y : y); p.addLine(to: cur); lastCtl = nil; lastQ = nil
        case "C":
            let c1 = P(n(), n()), c2 = P(n(), n()), e = P(n(), n())
            p.addCurve(to: e, control1: c1, control2: c2); lastCtl = c2; cur = e; lastQ = nil
        case "S":
            let c1 = lastCtl.map { CGPoint(x: 2 * cur.x - $0.x, y: 2 * cur.y - $0.y) } ?? cur
            let c2 = P(n(), n()), e = P(n(), n())
            p.addCurve(to: e, control1: c1, control2: c2); lastCtl = c2; cur = e; lastQ = nil
        case "Q":
            let c1 = P(n(), n()), e = P(n(), n())
            p.addQuadCurve(to: e, control: c1); lastQ = c1; cur = e; lastCtl = nil
        case "T":
            let c1 = lastQ.map { CGPoint(x: 2 * cur.x - $0.x, y: 2 * cur.y - $0.y) } ?? cur
            let e = P(n(), n())
            p.addQuadCurve(to: e, control: c1); lastQ = c1; cur = e; lastCtl = nil
        case "A":
            let rx = n(), ry = n(), rot = n(), large = n() != 0, sweep = n() != 0
            let e = P(n(), n())
            addArc(p, from: cur, rx: rx, ry: ry, phi: rot, large: large, sweep: sweep, to: e)
            cur = e; lastCtl = nil; lastQ = nil
        case "Z": p.closeSubpath(); cur = start; lastCtl = nil; lastQ = nil
        default: i += 1
        }
    }
    return p
}

func shapes(_ svg: String) -> CGMutablePath {
    let all = CGMutablePath()
    let re = try! NSRegularExpression(pattern: "<(path|circle|rect|line|polyline|polygon|ellipse)\\b[^>]*>")
    for m in re.matches(in: svg, range: NSRange(svg.startIndex..., in: svg)) {
        let tag = String(svg[Range(m.range, in: svg)!])
        let kind = String(svg[Range(m.range(at: 1), in: svg)!])
        switch kind {
        case "path": all.addPath(pathFrom(attr(tag, "d") ?? ""))
        case "circle":
            let r = num(tag, "r"); all.addEllipse(in: CGRect(x: num(tag, "cx") - r, y: num(tag, "cy") - r, width: 2 * r, height: 2 * r))
        case "ellipse":
            let rx = num(tag, "rx"), ry = num(tag, "ry")
            all.addEllipse(in: CGRect(x: num(tag, "cx") - rx, y: num(tag, "cy") - ry, width: 2 * rx, height: 2 * ry))
        case "rect":
            let r = CGRect(x: num(tag, "x"), y: num(tag, "y"), width: num(tag, "width"), height: num(tag, "height"))
            let rx = attr(tag, "rx").flatMap(Double.init).map { CGFloat($0) } ?? 0
            let ry = attr(tag, "ry").flatMap(Double.init).map { CGFloat($0) } ?? rx
            if rx > 0 { all.addRoundedRect(in: r, cornerWidth: min(rx, r.width / 2), cornerHeight: min(ry, r.height / 2)) } else { all.addRect(r) }
        case "line":
            all.move(to: CGPoint(x: num(tag, "x1"), y: num(tag, "y1"))); all.addLine(to: CGPoint(x: num(tag, "x2"), y: num(tag, "y2")))
        case "polyline", "polygon":
            let v = tokens(attr(tag, "points") ?? "").compactMap { Double($0) }.map { CGFloat($0) }
            guard v.count >= 4 else { continue }
            all.move(to: CGPoint(x: v[0], y: v[1]))
            stride(from: 2, to: v.count - 1, by: 2).forEach { all.addLine(to: CGPoint(x: v[$0], y: v[$0 + 1])) }
            if kind == "polygon" { all.closeSubpath() }
        default: break
        }
    }
    return all
}

func f(_ v: CGFloat) -> String {
    var s = String(format: "%.3f", Double(v))
    while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
    return s == "-0" ? "0" : s
}

func svgPath(_ p: CGPath) -> String {
    var d = ""
    p.applyWithBlock { e in
        let pts = e.pointee.points
        switch e.pointee.type {
        case .moveToPoint: d += "M\(f(pts[0].x)) \(f(pts[0].y))"
        case .addLineToPoint: d += "L\(f(pts[0].x)) \(f(pts[0].y))"
        case .addQuadCurveToPoint: d += "Q\(f(pts[0].x)) \(f(pts[0].y)) \(f(pts[1].x)) \(f(pts[1].y))"
        case .addCurveToPoint:
            d += "C\(f(pts[0].x)) \(f(pts[0].y)) \(f(pts[1].x)) \(f(pts[1].y)) \(f(pts[2].x)) \(f(pts[2].y))"
        case .closeSubpath: d += "Z"
        @unknown default: break
        }
    }
    return d
}

// Heavier variants for white glyphs on the small coloured squares (sidebar, project rows): at ~14 px the
// regular weight drops below a pixel and looks faint, while the Mac uses bold System-Settings-style glyphs.
let bold: [String: String] = [
    "routes-bold": "split", "projects-bold": "server", "dns-bold": "globe", "speed-bold": "gauge",
    "package-bold": "package",
]

let src = URL(fileURLWithPath: CommandLine.arguments[1]), out = URL(fileURLWithPath: CommandLine.arguments[2])
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
let jobs = icons.map { ($0.key, $0.value, width) } + bold.map { ($0.key, $0.value, CGFloat(2.6)) }
for (name, lucide, width) in jobs.sorted(by: { $0.0 < $1.0 }) {
    guard let svg = try? String(contentsOf: src.appendingPathComponent("\(lucide).svg"), encoding: .utf8) else {
        print("missing \(lucide)"); continue
    }
    // Stroke every shape, then merge the outlines so overlaps don't punch holes.
    let outline = shapes(svg).copy(strokingWithWidth: width, lineCap: .round, lineJoin: .round, miterLimit: 10)
        .normalized(using: .winding)
    // Centre the glyph on its real ink box (Lucide centres the centreline, so heavy strokes can sit off-centre
    // or poke past the edge) and keep 1 unit of padding, like SF Symbols in their frame.
    let box = outline.boundingBoxOfPath
    let k = min(1, 22 / max(box.width, box.height))
    var t = CGAffineTransform(translationX: 12, y: 12).scaledBy(x: k, y: k).translatedBy(x: -box.midX, y: -box.midY)
    let centred = outline.copy(using: &t) ?? outline
    let file = """
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24">
      <!-- Lucide "\(lucide)" (ISC, https://lucide.dev), stroke expanded for GTK symbolic recolouring -->
      <path fill="#2e3436" d="\(svgPath(centred))"/>
    </svg>

    """
    try! file.write(to: out.appendingPathComponent("devnet-\(name)-symbolic.svg"), atomically: true, encoding: .utf8)
}
print("wrote \(jobs.count) icons")
