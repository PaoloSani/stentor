import AppKit
import SwiftUI


/// What the pointer is over, shared between the event view and the drawing.
final class HoverState: ObservableObject {
    @Published var bar: (id: UUID, isStart: Bool)?
    @Published var overX = false
    @Published var x: CGFloat?
    @Published var dragPreview: ClosedRange<Double>? // region being drawn
    @Published var loopPreview: ClosedRange<Double>?
}

struct EditorView: View {
    @Environment(\.displayScale) private var displayScale
    @ObservedObject var project: Project
    @AppStorage("iconScale") private var iconScale = 1.0 // redraws the canvas when changed
    @EnvironmentObject var tips: TipCenter
    var interactive = true
    @StateObject private var hover = HoverState()

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                Canvas { ctx, size in draw(&ctx, size) }
                PlayheadView(transport: project.player.transport, project: project)
                if interactive { InteractionView(project: project, hover: hover, tips: tips, origin: geo.frame(in: .named("root")).origin) }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .overlay(alignment: .top) {
                VStack(spacing: 0) {
                    Color.clear.frame(height: Theme.rulerHeight).tourAnchor(.ruler)
                    Color.clear.tourAnchor(.editor)
                }
                .allowsHitTesting(false)
            }
            .onAppear { project.editorWidth = geo.size.width }
            .onChange(of: geo.size.width) { _, w in project.editorWidth = w }
        }
        .background(Theme.bg)
    }

    private func x(_ t: Double, _ w: CGFloat) -> CGFloat {
        CGFloat((t - project.visibleStart) / project.visibleDuration) * w
    }

    private func draw(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let w = size.width, rh = Theme.rulerHeight
        let lane = CGRect(x: 0, y: rh, width: w, height: size.height - rh)
        let t0 = project.visibleStart, t1 = t0 + project.visibleDuration
        ctx.fill(Path(lane), with: .color(Theme.lane))

        // --- signal ------------------------------------------------------------------
        if project.viewMode == .spectrogram, let tile = project.displaySpectrogram {
            // drawn at the tile's own times: exact while current, correctly shifted while a new one renders
            let rect = CGRect(x: x(tile.t0, w), y: lane.minY, width: x(tile.t1, w) - x(tile.t0, w), height: lane.height)
            ctx.draw(Image(decorative: tile.image, scale: 1), in: rect)
        } else if let peaks = project.displayPeaks {
            if project.viewMode == .spectrogram {
                ctx.draw(Text("Computing spectrogram…").font(.system(size: 11)).foregroundColor(Theme.muted),
                         at: CGPoint(x: w / 2, y: lane.midY))
            } else {
                // one column per device pixel (2 per point on Retina), so the waveform stays sharp
                let px = max(1, displayScale)
                let cols = peaks.columns(t0: t0, t1: t1, width: Int(w * px))
                let mid = lane.midY, amp = lane.height / 2 * 0.92
                var path = Path()
                for (i, (mn, mx)) in cols.enumerated() {
                    let xx = (CGFloat(i) + 0.5) / px
                    path.move(to: CGPoint(x: xx, y: mid - CGFloat(mx) * amp))
                    path.addLine(to: CGPoint(x: xx, y: mid - CGFloat(mn) * amp + 0.5))
                }
                ctx.stroke(path, with: .color(project.source == .enhanced ? Theme.waveEnh : Theme.wave), lineWidth: 1 / px)
                ctx.stroke(Path { $0.move(to: CGPoint(x: 0, y: mid)); $0.addLine(to: CGPoint(x: w, y: mid)) },
                           with: .color(Theme.grid), lineWidth: 1)
            }
        }

        // --- loop ----------------------------------------------------------------------
        if let l = hover.loopPreview ?? project.loopRange {
            let r = CGRect(x: x(l.lowerBound, w), y: 0, width: x(l.upperBound, w) - x(l.lowerBound, w), height: size.height)
            let on = project.loopEnabled || hover.loopPreview != nil
            ctx.fill(Path(r), with: .color(Theme.loop.opacity(on ? 0.07 : 0.03)))
            ctx.fill(Path(CGRect(x: r.minX, y: 2, width: r.width, height: rh - 6)), with: .color(Theme.loop.opacity(on ? 0.55 : 0.2)))
        }

        // --- regions ---------------------------------------------------------------------
        var all = project.regions.map { ($0, $0.id == project.selected) }
        if let d = hover.dragPreview { all.append((Region(start: d.lowerBound, end: d.upperBound), true)) }
        for (r, sel) in all where r.end >= t0 && r.start <= t1 {
            let xa = x(r.start, w), xb = x(r.end, w)
            let box = CGRect(x: xa, y: lane.minY, width: max(1, xb - xa), height: lane.height)
            ctx.fill(Path(box), with: .color(Theme.speech.opacity(sel ? 0.2 : 0.11)))
            let stale = project.isStale(r)
            ctx.fill(Path(CGRect(x: xa, y: lane.minY, width: max(1, xb - xa), height: stale ? 4 : 3)),
                     with: .color(stale ? Theme.loop.opacity(0.9) : Theme.speech.opacity(0.7)))
            for (bx, isStart) in [(xa, true), (xb, false)] {
                let hot = hover.bar.map { $0.id == r.id && $0.isStart == isStart } ?? false
                ctx.fill(Path(CGRect(x: bx - (hot ? 1.5 : 1), y: lane.minY, width: hot ? 3 : 2, height: lane.height)),
                         with: .color(Theme.speech.opacity(hot ? 1 : 0.85)))
                // grip tab at the top of each bar (start tab points right, end tab points left)
                let s = CGFloat(iconScale)
                let tab = CGRect(x: isStart ? bx : bx - 9 * s, y: lane.minY, width: 9 * s, height: 12 * s)
                ctx.fill(Path(roundedRect: tab, cornerRadius: 2), with: .color(Theme.speech.opacity(hot ? 1 : 0.8)))
                if hot && hover.overX {
                    let c = CGPoint(x: isStart ? bx + 11 * s : bx - 11 * s, y: lane.minY + 15 * s)
                    ctx.fill(Path(ellipseIn: CGRect(x: c.x - 8 * s, y: c.y - 8 * s, width: 16 * s, height: 16 * s)), with: .color(Theme.danger))
                    var xp = Path()
                    let k = 3.5 * s
                    xp.move(to: CGPoint(x: c.x - k, y: c.y - k)); xp.addLine(to: CGPoint(x: c.x + k, y: c.y + k))
                    xp.move(to: CGPoint(x: c.x + k, y: c.y - k)); xp.addLine(to: CGPoint(x: c.x - k, y: c.y + k))
                    ctx.stroke(xp, with: .color(.white), lineWidth: 1.6 * s)
                }
            }
        }

        // --- ruler -------------------------------------------------------------------------
        ctx.fill(Path(CGRect(x: 0, y: 0, width: w, height: rh)), with: .color(Theme.bg))
        let step = niceStep(project.visibleDuration / Double(max(1, w / 90)))
        var t = (t0 / step).rounded(.down) * step
        while t <= t1 {
            let xx = x(t, w)
            ctx.fill(Path(CGRect(x: xx, y: rh - 7, width: 1, height: 7)), with: .color(Theme.muted))
            ctx.fill(Path(CGRect(x: xx, y: rh, width: 1, height: lane.height)), with: .color(Theme.grid))
            ctx.draw(Text(timecode(t, step: step)).font(.system(size: 9.5, design: .monospaced)).foregroundColor(Theme.muted),
                     at: CGPoint(x: xx + 3, y: 8), anchor: .leading)
            t += step
        }
        if let l = hover.loopPreview ?? (project.loopEnabled ? project.loopRange : nil) {
            ctx.fill(Path(CGRect(x: x(l.lowerBound, w), y: 2, width: x(l.upperBound, w) - x(l.lowerBound, w), height: rh - 6)),
                     with: .color(Theme.loop.opacity(0.35)))
        }
        ctx.fill(Path(CGRect(x: 0, y: rh - 1, width: w, height: 1)), with: .color(Theme.ink.opacity(0.1)))
    }

    private func niceStep(_ raw: Double) -> Double {
        let steps: [Double] = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
        return steps.first { $0 >= raw } ?? 600
    }
}

func timecode(_ t: Double, step: Double = 1) -> String {
    let m = Int(t) / 60, s = t - Double(m * 60)
    if step < 0.1 { return String(format: "%d:%05.2f", m, s) }
    if step < 1 { return String(format: "%d:%04.1f", m, s) }
    return String(format: "%d:%02d", m, Int(s))
}

/// Playhead line, redrawn on its own at the transport rate.
struct PlayheadView: View {
    @ObservedObject var transport: Transport
    @ObservedObject var project: Project

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let xx = CGFloat((transport.time - project.visibleStart) / project.visibleDuration) * w
            if xx >= 0 && xx <= w {
                ZStack(alignment: .topLeading) {
                    Rectangle().fill(Theme.ink.opacity(0.92)).frame(width: 1.5, height: geo.size.height).offset(x: xx - 0.75)
                    Triangle().fill(Theme.ink).frame(width: 10, height: 7).offset(x: xx - 5, y: Theme.rulerHeight - 7)
                }
            }
        }
        .allowsHitTesting(false)
        .onChange(of: transport.time) { _, t in
            // keep the playhead in view while playing
            guard transport.isPlaying else { return }
            if t > project.visibleStart + project.visibleDuration * 0.95 || t < project.visibleStart {
                project.visibleStart = project.clampStart(t - project.visibleDuration * 0.05)
            }
        }
    }
}

struct Triangle: Shape {
    func path(in r: CGRect) -> Path {
        Path { p in p.move(to: CGPoint(x: r.minX, y: r.minY)); p.addLine(to: CGPoint(x: r.maxX, y: r.minY)); p.addLine(to: CGPoint(x: r.midX, y: r.maxY)); p.closeSubpath() }
    }
}

// MARK: - mouse / trackpad handling

struct InteractionView: NSViewRepresentable {
    let project: Project
    let hover: HoverState
    let tips: TipCenter
    var origin: CGPoint = .zero

    func makeNSView(context: Context) -> EditorEventView {
        let v = EditorEventView()
        v.project = project; v.hover = hover; v.tips = tips; v.origin = origin
        return v
    }

    func updateNSView(_ v: EditorEventView, context: Context) { v.project = project; v.hover = hover; v.tips = tips; v.origin = origin }
}

final class EditorEventView: NSView {
    weak var project: Project?
    weak var hover: HoverState?
    weak var tips: TipCenter?
    var origin: CGPoint = .zero // editor origin in the window's "root" space (for tip placement)
    private var tipID: String?
    private enum Drag {
        case none, ruler(anchor: Double, moved: Bool)
        case edge(id: UUID, isStart: Bool)
        case create(anchor: Double, moved: Bool)
        case inside(id: UUID, t: Double)
    }
    private var drag: Drag = .none
    private var tracking: NSTrackingArea?

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        if let tracking { removeTrackingArea(tracking) }
        tracking = NSTrackingArea(rect: bounds, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect, .cursorUpdate], owner: self)
        addTrackingArea(tracking!)
    }

    @MainActor private func time(_ x: CGFloat) -> Double {
        guard let p = project else { return 0 }
        return min(p.duration, max(0, p.visibleStart + Double(x / bounds.width) * p.visibleDuration))
    }

    @MainActor private func xOf(_ t: Double) -> CGFloat {
        guard let p = project else { return 0 }
        return CGFloat((t - p.visibleStart) / p.visibleDuration) * bounds.width
    }

    /// Nearest region edge within 6 px.
    @MainActor private func barHit(_ pt: NSPoint) -> (id: UUID, isStart: Bool)? {
        guard let p = project, pt.y > Theme.rulerHeight else { return nil }
        var best: (UUID, Bool, CGFloat)?
        for r in p.regions {
            for (t, s) in [(r.start, true), (r.end, false)] {
                let d = abs(xOf(t) - pt.x)
                if d <= 6, d < (best?.2 ?? .infinity) { best = (r.id, s, d) }
            }
        }
        return best.map { ($0.0, $0.1) }
    }

    @MainActor private func inXZone(_ pt: NSPoint, bar: (id: UUID, isStart: Bool)) -> Bool {
        guard let p = project, let r = p.regions.first(where: { $0.id == bar.id }) else { return false }
        let bx = xOf(bar.isStart ? r.start : r.end)
        let s = Theme.iconScale
        let cx = bar.isStart ? bx + 11 * s : bx - 11 * s
        return pt.y >= Theme.rulerHeight && pt.y <= Theme.rulerHeight + 26 * s && abs(pt.x - cx) <= 10 * s
    }

    @MainActor private func xHit(_ pt: NSPoint) -> UUID? {
        guard let h = hover?.bar, hover?.overX == true, inXZone(pt, bar: h) else { return nil }
        return h.id
    }

    /// The editor sits under the model-download card while the model is missing: ignore it then.
    @MainActor private var blocked: Bool { (project?.needsModels ?? false) || project?.tourStep != nil }

    override func mouseMoved(with e: NSEvent) {
        MainActor.assumeIsolated {
            if blocked { hover?.bar = nil; hover?.overX = false; NSCursor.arrow.set(); return }
            updateHover(convert(e.locationInWindow, from: nil))
        }
    }
    override func mouseExited(with e: NSEvent) {
        MainActor.assumeIsolated { hover?.bar = nil; hover?.overX = false; NSCursor.arrow.set(); tips?.hide(); tipID = nil }
    }

    /// Detailed card for whatever is under the pointer (editor coordinates == root coordinates).
    @MainActor private func showTip(_ info: TipInfo, _ pt: NSPoint) {
        if tipID != info.id, let old = tipID { tips?.leave(old) }
        tipID = info.id
        tips?.hover(info, at: CGPoint(x: pt.x + origin.x, y: pt.y + origin.y))
    }

    @MainActor private func updateHover(_ pt: NSPoint) {
        guard let hover else { return }
        // keep the X visible while the pointer travels from the bar to the badge
        if let h = hover.bar, inXZone(pt, bar: h) { hover.overX = true; NSCursor.pointingHand.set(); showTip(Tips.barX, pt); return }
        let b = barHit(pt)
        if hover.bar?.id != b?.id || hover.bar?.isStart != b?.isStart { hover.bar = b }
        let showX = b != nil && pt.y <= Theme.rulerHeight + 26 * Theme.iconScale
        if hover.overX != showX { hover.overX = showX }
        if b != nil { (showX ? NSCursor.pointingHand : NSCursor.resizeLeftRight).set(); showTip(showX ? Tips.barX : Tips.bar, pt) }
        else if pt.y <= Theme.rulerHeight { NSCursor.pointingHand.set(); showTip(Tips.ruler, pt) }
        else {
            NSCursor.iBeam.set()
            let t = time(pt.x)
            showTip(project?.regions.contains { $0.contains(t) } == true ? Tips.region : Tips.empty, pt)
        }
    }

    override func mouseDown(with e: NSEvent) {
        MainActor.assumeIsolated {
            guard !blocked else { return }
            window?.makeFirstResponder(self)
            tips?.hide(); tipID = nil
            guard let p = project else { return }
            let pt = convert(e.locationInWindow, from: nil)
            let t = time(pt.x)
            let cmd = e.modifierFlags.contains(.command)
            if pt.y <= Theme.rulerHeight { drag = .ruler(anchor: t, moved: false); return }
            if let id = xHit(pt) { p.removeRegion(id); hover?.bar = nil; hover?.overX = false; return }
            if let b = barHit(pt) {
                if cmd { p.removeRegion(b.id); return }
                p.beginEdit()
                p.selected = b.id
                drag = .edge(id: b.id, isStart: b.isStart)
                return
            }
            if let r = p.regions.first(where: { $0.contains(t) }) {
                if cmd { p.removeRegion(r.id); return }
                drag = .inside(id: r.id, t: t)
                return
            }
            drag = .create(anchor: t, moved: false)
        }
    }

    override func mouseDragged(with e: NSEvent) {
        MainActor.assumeIsolated {
            guard !blocked else { return }
            guard let p = project else { return }
            let pt = convert(e.locationInWindow, from: nil)
            let t = time(pt.x)
            switch drag {
            case .ruler(let a, _):
                drag = .ruler(anchor: a, moved: true)
                hover?.loopPreview = min(a, t)...max(a, t)
            case .edge(let id, let isStart):
                p.moveEdge(id, isStart: isStart, to: t)
            case .create(let a, _):
                if abs(xOf(a) - pt.x) > 3 {
                    drag = .create(anchor: a, moved: true)
                    hover?.dragPreview = min(a, t)...max(a, t)
                }
            default: break
            }
            autoscroll(with: e)
        }
    }

    override func mouseUp(with e: NSEvent) {
        MainActor.assumeIsolated {
            guard !blocked else { return }
            guard let p = project else { return }
            let pt = convert(e.locationInWindow, from: nil)
            let t = time(pt.x)
            switch drag {
            case .ruler(let a, let moved):
                hover?.loopPreview = nil
                if moved, abs(t - a) > 0.02 { p.setLoopRange(min(a, t)...max(a, t)) }
                else if e.clickCount == 2 { p.setLoopRange(nil) }
                else { p.seek(t) }
            case .create(let a, let moved):
                hover?.dragPreview = nil
                if moved { p.addRegion(a, t) } else { p.insertRegion(at: a) }
            case .inside(let id, let t0):
                p.selected = id
                p.seek(t0)
            default: break
            }
            drag = .none
            updateHover(pt)
        }
    }

    // Right-click menu: regenerate / loop / delete a region, or add one.
    override func menu(for event: NSEvent) -> NSMenu? {
        MainActor.assumeIsolated {
            guard !blocked else { return nil }
            guard let p = project, p.audio != nil else { return nil }
            let pt = convert(event.locationInWindow, from: nil)
            let t = time(pt.x)
            tips?.hide()
            let menu = NSMenu()
            let hit = barHit(pt).flatMap { b in p.regions.first { $0.id == b.id } } ?? p.regions.first { $0.contains(t) }
            if let r = hit {
                p.selected = r.id
                let n = (p.regions.firstIndex(of: r) ?? 0) + 1
                menu.addItem(ClosureMenuItem(String(format: "Enhance Region %d (%.1f s)", n, r.length), enabled: !p.processing) { p.enhanceRegion(r.id) })
                menu.addItem(ClosureMenuItem("Loop Region \(n)") { p.setLoopRange(r.start...r.end) })
                menu.addItem(ClosureMenuItem("Play Region \(n)") { p.seek(r.start); if !p.player.transport.isPlaying { p.togglePlay() } })
                menu.addItem(.separator())
                menu.addItem(ClosureMenuItem("Delete Region \(n)") { p.removeRegion(r.id) })
            } else if pt.y > Theme.rulerHeight {
                menu.addItem(ClosureMenuItem("Add Region Here") { p.insertRegion(at: t) })
            }
            return menu.items.isEmpty ? nil : menu
        }
    }

    override func scrollWheel(with e: NSEvent) {
        MainActor.assumeIsolated {
            guard !blocked else { return }
            guard let p = project, p.duration > 0 else { return }
            let t = time(convert(e.locationInWindow, from: nil).x)
            let dx = e.scrollingDeltaX, dy = e.scrollingDeltaY
            let scale = e.hasPreciseScrollingDeltas ? 1.0 : 8.0
            if abs(dy) > abs(dx) {
                // vertical: zoom around the pointer
                p.zoom(by: exp(Double(dy) * 0.01 * scale), around: t)
            } else {
                // horizontal: pan
                p.scroll(bySeconds: -Double(dx) * scale / Double(bounds.width) * p.visibleDuration)
            }
        }
    }

    override func magnify(with e: NSEvent) {
        MainActor.assumeIsolated {
            guard !blocked else { return }
            guard let p = project else { return }
            p.zoom(by: 1 + Double(e.magnification), around: time(convert(e.locationInWindow, from: nil).x))
        }
    }
}

/// NSMenuItem running a closure.
final class ClosureMenuItem: NSMenuItem {
    private let handler: () -> Void
    init(_ title: String, enabled: Bool = true, _ handler: @escaping () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        target = self
        isEnabled = enabled
    }
    required init(coder: NSCoder) { fatalError() }
    @objc private func fire() { handler() }
}
