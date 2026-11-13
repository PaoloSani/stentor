import SwiftUI

/// Parts of the window the guided tour can highlight.
enum TourTarget: Hashable {
    case logo, file, editor, ruler, transport, ab, view, enhance, export, gear
}

/// Collects the on-screen frame of each tour target (anchor preferences, resolved by MainView).
struct TourAnchorKey: PreferenceKey {
    static var defaultValue: [TourTarget: Anchor<CGRect>] = [:]
    static func reduce(value: inout [TourTarget: Anchor<CGRect>], nextValue: () -> [TourTarget: Anchor<CGRect>]) {
        value.merge(nextValue(), uniquingKeysWith: { $1 })
    }
}

extension View {
    /// Marks this view as a place the guided tour can highlight.
    func tourAnchor(_ target: TourTarget) -> some View {
        anchorPreference(key: TourAnchorKey.self, value: .bounds) { [target: $0] }
    }
}

struct TourStep {
    let target: TourTarget?   // nil: centred card, no spotlight
    let title: String
    let body: String
    var showsSampleTip = false
}

enum Tour {
    static let steps: [TourStep] = [
        TourStep(target: nil, title: "Welcome to Stentor",
                 body: "A one-minute tour of the app. A demo recording is open — J.F. Kennedy in a reverberant stadium — so you can try everything right away."),
        TourStep(target: .file, title: "Your recording",
                 body: "Name, format and how much of it is speech. Click here to open another file, or simply drop one onto the window."),
        TourStep(target: .editor, title: "Green regions = speech",
                 body: "Only the green regions are restored; everything else stays silent and the output keeps the original length. Click empty space to add a region, drag its edges to adjust, hover the top of an edge for ✕, right-click for more."),
        TourStep(target: .ruler, title: "Ruler",
                 body: "Click to move the playhead. Drag to set a loop range — handy to compare a single phrase over and over."),
        TourStep(target: .transport, title: "Play and loop",
                 body: "Space plays and pauses, L toggles the loop (it starts on the first speech region)."),
        TourStep(target: .ab, title: "Compare A / B",
                 body: "A is the original, level-matched; B is the restored voice. Press B to switch at the same position. B unlocks after the first Enhance."),
        TourStep(target: .view, title: "Waveform or spectrogram",
                 body: "S switches view. The spectrogram shows what the model does: noise and reverb fade, harmonics come back."),
        TourStep(target: .enhance, title: "Enhance",
                 body: "Restores every green region on your Mac's GPU (⌘↩). After editing, only the changed regions are processed again."),
        TourStep(target: .export, title: "Export",
                 body: "Saves a WAV with exactly the original length (⌘E), or each speech region as its own file (⇧⌘E)."),
        TourStep(target: .gear, title: "Tooltips and settings",
                 body: "Hover anything and a card like the one below explains it, with its shortcuts. You can turn them off here: Settings › Help › Detailed tooltips — along with theme, icon size, detection and export options.",
                 showsSampleTip: true),
        TourStep(target: .logo, title: "That's it",
                 body: "Click the logo for credits, updates and feedback. You can replay this tour from Help › Show Tour."),
    ]
}

/// Dimmed window with a spotlight on the current target and a card explaining it.
struct TourOverlay: View {
    @ObservedObject var project: Project
    let anchors: [TourTarget: Anchor<CGRect>]

    var body: some View {
        GeometryReader { geo in
            if let i = project.tourStep, Tour.steps.indices.contains(i) {
                let step = Tour.steps[i]
                let hole = step.target.flatMap { anchors[$0] }.map { geo[$0].insetBy(dx: -6, dy: -6) }
                ZStack(alignment: .topLeading) {
                    Spotlight(hole: hole)
                        .fill(Color.black.opacity(0.62), style: FillStyle(eoFill: true))
                        .contentShape(Rectangle())
                        .onTapGesture {} // swallow clicks on the dimmed area
                    if let hole {
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Theme.speech, lineWidth: 2)
                            .frame(width: hole.width, height: hole.height)
                            .offset(x: hole.minX, y: hole.minY)
                            .allowsHitTesting(false)
                    }
                    card(step, index: i)
                        .frame(width: 340)
                        .fixedSize(horizontal: false, vertical: true)
                        .modifier(Place(hole: hole, size: geo.size))
                }
                .animation(.easeInOut(duration: 0.2), value: i)
            }
        }
    }

    private func card(_ step: TourStep, index i: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("\(i + 1) of \(Tour.steps.count)").font(.system(size: 10.5, design: .monospaced)).foregroundStyle(Theme.muted)
                Spacer()
                Button("Skip tour") { project.endTour() }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
            Text(step.title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.text)
            Text(step.body).font(.system(size: 12)).foregroundStyle(Theme.text.opacity(0.85)).fixedSize(horizontal: false, vertical: true)
            if step.showsSampleTip {
                TipCard(info: Tips.enhance).scaleEffect(0.92, anchor: .topLeading).padding(.bottom, -14)
            }
            HStack {
                if i > 0 { Button("Back") { project.tourStep = i - 1 }.buttonStyle(PillStyle()) }
                Spacer()
                if i < Tour.steps.count - 1 {
                    Button("Next") { project.tourStep = i + 1 }.buttonStyle(PillStyle(active: true)).keyboardShortcut(.defaultAction)
                } else {
                    Button("Start using Stentor") { project.endTour() }.buttonStyle(PillStyle(active: true)).keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.speech.opacity(0.5), lineWidth: 1))
        .shadow(color: .black.opacity(0.4), radius: 20, y: 8)
    }
}

/// Full-window rectangle with a rounded hole (even-odd fill).
struct Spotlight: Shape {
    var hole: CGRect?
    func path(in rect: CGRect) -> Path {
        var p = Path(rect)
        if let hole { p.addRoundedRect(in: hole, cornerSize: CGSize(width: 10, height: 10)) }
        return p
    }
}

/// Puts the card next to the highlighted area (below it, or above when it is in the lower half),
/// kept inside the window; centred when there is nothing to highlight.
struct Place: ViewModifier {
    let hole: CGRect?
    let size: CGSize

    func body(content: Content) -> some View {
        let w: CGFloat = 340
        guard let h = hole else {
            return AnyView(content.frame(maxWidth: .infinity, maxHeight: .infinity))
        }
        let x = min(max(16, h.midX - w / 2), size.width - w - 16)
        let below = h.midY < size.height * 0.5
        // the editor fills most of the window: put the card inside it, near the top
        let insideTall = h.height > size.height * 0.5
        return AnyView(
            content
                .alignmentGuide(.top) { d in
                    if insideTall { return -(h.minY + 40) }
                    return below ? -(h.maxY + 14) : d.height + 14 - h.minY
                }
                .alignmentGuide(.leading) { _ in -x }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        )
    }
}
