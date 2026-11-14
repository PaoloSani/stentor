import AppKit
import SwiftUI

/// Content of a detailed hover card.
struct TipInfo: Equatable {
    let id: String
    let title: String
    let body: String
    var shortcuts: [(keys: String, action: String)] = []
    var hint: String? = nil

    static func == (a: TipInfo, b: TipInfo) -> Bool { a.id == b.id }

    /// One-line fallback used when detailed tooltips are off.
    var short: String {
        let keys = shortcuts.first.map { " (\($0.keys))" } ?? ""
        return title + keys
    }
}

/// Catalogue of every function in the window.
enum Tips {
    static let logo = TipInfo(
        id: "logo", title: "About Stentor",
        body: "Opens the about card: credits, the Sidon model this app is built on, and — clicking the logo there — who Stentor was.")
    static let fileInfo = TipInfo(
        id: "fileInfo", title: "Open another file",
        body: "Click to load a different recording. Shown here: name, sample rate, channels and length of the current file, plus how much of it is speech (the green regions that will be processed).",
        shortcuts: [("⌘ O", "open another file"), ("drop", "drag a file onto the window")])
    static let gear = TipInfo(
        id: "gear", title: "Settings",
        body: "Tooltips, speech-detection sensitivity (threshold, pre/post-roll, gap merging), model precision and export format.",
        shortcuts: [("⌘ ,", "open settings")])
    static let cancel = TipInfo(
        id: "cancel", title: "Cancel",
        body: "Progress of the running enhancement. Click to stop it; the previous result (if any) is kept.")
    static let brand = TipInfo(
        id: "brand", title: "Stentor",
        body: "Named after the herald of the Greeks in Homer's Iliad, whose voice was as loud as fifty men. Click to read about him on Wikipedia.",
        hint: "Speech restoration by the open-source Sidon model, running on this Mac's GPU.")
    static let toStart = TipInfo(
        id: "toStart", title: "Go to start",
        body: "Moves the playhead to the beginning of the file, or to the start of the loop when looping is on.",
        shortcuts: [("Home", "go to start")])
    static let play = TipInfo(
        id: "play", title: "Play / Pause",
        body: "Plays from the playhead. What you hear depends on the A/B switch: the original (level-matched) or the enhanced result.",
        shortcuts: [("Space", "play / pause")])
    static let loop = TipInfo(
        id: "loop", title: "Loop",
        body: "Repeats a range seamlessly. By default it loops the first speech region (or the selected one); drag on the ruler to loop any other range.",
        shortcuts: [("L", "loop on / off"), ("drag ruler", "set range"), ("double-click ruler", "clear range")])
    static let time = TipInfo(
        id: "time", title: "Position / Length",
        body: "Current playhead position and total length of the file. The enhanced output always has exactly the same length.")
    static let ab = TipInfo(
        id: "ab", title: "A / B comparison",
        body: "A plays the original, peak-normalised so the comparison is fair; B plays the enhanced result. Switching keeps the playhead, so you hear the same word both ways. B is available after the first Enhance.",
        shortcuts: [("B", "swap A / B")])
    static let view = TipInfo(
        id: "view", title: "Waveform / Spectrogram",
        body: "Waveform shows level over time. Spectrogram shows frequencies (log scale, 40 Hz at the bottom) — useful to see noise, hum or missing highs before and after.",
        shortcuts: [("S", "switch view")])
    static let zoomOut = TipInfo(id: "zoomOut", title: "Zoom out", body: "Shows more of the file around the centre.",
                                 shortcuts: [("⌘ −", "zoom out"), ("scroll ↓", "zoom at pointer")])
    static let fit = TipInfo(id: "fit", title: "Zoom to fit", body: "Shows the whole file.", shortcuts: [("⌘ 0", "fit")])
    static let zoomIn = TipInfo(id: "zoomIn", title: "Zoom in", body: "Shows a shorter stretch in more detail.",
                                shortcuts: [("⌘ =", "zoom in"), ("scroll ↑ / pinch", "zoom at pointer"), ("scroll ↔", "pan")])
    static let regions = TipInfo(
        id: "regions", title: "Speech regions",
        body: "Number and total length of the green regions — the only parts sent to the model. Click to tune automatic detection (threshold, pre/post-roll, gap merging) and re-detect.",
        shortcuts: [("⇧⌘D", "detect again")],
        hint: "Less green = faster processing. Everything outside stays silent.")
    static let status = TipInfo(
        id: "status", title: "Status",
        body: "Progress and messages. Hover here after an error to read the full message; the model status appears in the window subtitle before a file is open.")
    static let enhance = TipInfo(
        id: "enhance", title: "Enhance",
        body: "Runs Sidon on the green regions and builds the full-length output: speech restored to 48 kHz studio quality, silence everywhere else. After the first run only changed regions (amber top edge) are processed again — the button shows how many.",
        shortcuts: [("⌘ ↩", "enhance changed"), ("⇧⌘ ↩", "selected region only"), ("right-click", "region menu")],
        hint: "When nothing changed, the button re-renders everything from scratch.")
    static let export = TipInfo(
        id: "export", title: "Export",
        body: "Saves the enhanced audio as a mono WAV with exactly the same length as the original, so it lines up in your DAW. Sample rate, bit depth and whether to export the whole file or each speech region as its own file are set in Settings (default: whole file, 48 kHz, 24-bit).",
        shortcuts: [("⌘ E", "export"), ("⇧⌘ E", "speech regions, one file each")])
    static let overview = TipInfo(
        id: "overview", title: "Overview",
        body: "The whole file with its green regions; the frame is the part shown above. Click or drag to jump there.")

    // editor
    static let ruler = TipInfo(
        id: "ruler", title: "Ruler",
        body: "Click to move the playhead. Drag to select a loop range (shown in amber).",
        shortcuts: [("click", "seek"), ("drag", "set loop"), ("double-click", "clear loop")])
    static let empty = TipInfo(
        id: "empty", title: "Add a region",
        body: "Click to add a green region starting here and ending just before the next one (or at the end of the file). Drag instead to draw a region of exactly that span.",
        shortcuts: [("click", "add up to next"), ("drag", "draw region")])
    static let region = TipInfo(
        id: "region", title: "Green region",
        body: "This span will be restored by the model. Click to select it and move the playhead here.",
        shortcuts: [("click", "select + seek"), ("right-click", "enhance / loop / delete"), ("⌘ click", "remove"), ("Delete", "remove selected")])
    static let bar = TipInfo(
        id: "bar", title: "Region edge",
        body: "Drag to move the start or end of the region; it stops at the neighbouring regions. Hover the top of the bar to reveal the ✕.",
        shortcuts: [("drag", "adjust"), ("⌘ click", "remove region")])
    static let barX = TipInfo(
        id: "barX", title: "Remove region",
        body: "Deletes this green region; that span will stay silent in the output.",
        shortcuts: [("⌘ Z", "undo")])
}

/// Shows one detailed card at a time, after a short delay.
@MainActor
final class TipCenter: ObservableObject {
    @Published private(set) var current: TipInfo?
    @Published private(set) var point: CGPoint = .zero
    private var pending: DispatchWorkItem?
    private var pendingID: String?

    var enabled: Bool { UserDefaults.standard.object(forKey: "detailedTooltips") as? Bool ?? true }

    /// True while a modal card (model download, about) covers the window: no tips from what's underneath.
    @Published var suppressed = false { didSet { if suppressed { hide() } } }

    func hover(_ info: TipInfo, at p: CGPoint) {
        guard enabled, !suppressed else { hide(); return }
        if current == info { point = p; return }
        if pendingID == info.id { point = p; return }
        pending?.cancel()
        pendingID = info.id
        let work = DispatchWorkItem { [weak self] in
            self?.current = info
            self?.pendingID = nil
        }
        pending = work
        point = p
        DispatchQueue.main.asyncAfter(deadline: .now() + (current == nil ? 0.55 : 0.12), execute: work)
    }

    func leave(_ id: String) {
        if pendingID == id { pending?.cancel(); pendingID = nil }
        if current?.id == id { current = nil }
    }

    func hide() { pending?.cancel(); pendingID = nil; current = nil }

    /// Show immediately (snapshot tests).
    func show(_ info: TipInfo, at p: CGPoint) { current = info; point = p }
}

extension View {
    /// Detailed hover card when enabled in Settings, otherwise a one-line native tooltip.
    func tip(_ info: TipInfo) -> some View { modifier(TipModifier(info: info)) }
}

struct TipModifier: ViewModifier {
    let info: TipInfo
    @EnvironmentObject var tips: TipCenter
    @AppStorage("detailedTooltips") var detailed = true

    func body(content: Content) -> some View {
        if detailed {
            content.onContinuousHover(coordinateSpace: .named("root")) { phase in
                switch phase {
                case .active(let p): tips.hover(info, at: p)
                case .ended: tips.leave(info.id)
                }
            }
        } else {
            content.help(info.short)
        }
    }
}

/// The floating card, placed near the pointer and kept inside the window.
struct TipOverlay: View {
    @ObservedObject var tips: TipCenter

    var body: some View {
        GeometryReader { geo in
            if let info = tips.current, !tips.suppressed {
                let w: CGFloat = 290
                let above = tips.point.y > geo.size.height * 0.55
                let x = min(max(8, tips.point.x - w / 2), geo.size.width - w - 8)
                TipCard(info: info)
                    .frame(width: w)
                    .fixedSize(horizontal: false, vertical: true)
                    .alignmentGuide(.top) { d in above ? d.height + 14 - tips.point.y : -(tips.point.y + 18) }
                    .alignmentGuide(.leading) { _ in -x }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .transition(.opacity)
            }
        }
        .allowsHitTesting(false)
        .animation(.easeOut(duration: 0.12), value: tips.current?.id)
    }
}

struct TipCard: View {
    let info: TipInfo

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(info.title).font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.text)
            Text(info.body).font(.system(size: 11)).foregroundStyle(Theme.text.opacity(0.8))
                .fixedSize(horizontal: false, vertical: true)
            if !info.shortcuts.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(info.shortcuts.indices, id: \.self) { i in
                        HStack(spacing: 6) {
                            Text(info.shortcuts[i].keys)
                                .font(.system(size: 10, weight: .medium, design: .rounded))
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(RoundedRectangle(cornerRadius: 3).fill(Theme.ink.opacity(0.1)))
                                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Theme.ink.opacity(0.15), lineWidth: 0.5))
                                .foregroundStyle(Theme.text)
                            Text(info.shortcuts[i].action).font(.system(size: 10.5)).foregroundStyle(Theme.muted)
                        }
                    }
                }
            }
            if let hint = info.hint {
                HStack(alignment: .top, spacing: 5) {
                    Image(systemName: "lightbulb").font(.system(size: 9.5)).foregroundStyle(Theme.loop)
                    Text(hint).font(.system(size: 10.5)).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(11)
        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(Theme.ink.opacity(0.12), lineWidth: 1))
        .shadow(color: .black.opacity(0.3), radius: 12, y: 4)
    }
}
