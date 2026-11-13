import SwiftUI

/// Local boolean UI state (stands in for @State, whose macro plugin needs full Xcode).
final class Flag: ObservableObject { @Published var on = false }

/// Small rounded control used in the island.
struct PillStyle: ButtonStyle {
    var active = false
    var tint: Color = Theme.accent
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 9).frame(height: 26)
            .foregroundStyle(active ? Theme.onAccent : Theme.text)
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(active ? tint : Theme.ink.opacity(configuration.isPressed ? 0.16 : 0.07))
            )
            .contentShape(Rectangle())
    }
}

/// Round transport button.
struct RoundStyle: ButtonStyle {
    var active = false
    var tint: Color = Theme.text
    var onTint: Color = Theme.onAccent
    var size: CGFloat = 30
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: size * 0.38, weight: .bold))
            .frame(width: size, height: size)
            .foregroundStyle(active ? onTint : Theme.text)
            .background(Circle().fill(active ? tint : Theme.ink.opacity(configuration.isPressed ? 0.18 : 0.08)))
            .contentShape(Circle())
    }
}

/// Two-option switch (A/B, Wave/Spec).
struct Toggle2<T: Equatable>: View {
    let options: [(T, String)]
    let value: T
    var disabled: (T) -> Bool = { _ in false }
    let set: (T) -> Void
    var body: some View {
        HStack(spacing: 0) {
            ForEach(options.indices, id: \.self) { i in
                let (v, label) = options[i]
                Button(label) { set(v) }
                    .buttonStyle(.plain)
                    .font(.system(size: 10.5, weight: .bold))
                    .padding(.horizontal, 9).frame(height: 22)
                    .foregroundStyle(v == value ? Theme.inverse : Theme.muted)
                    .background(RoundedRectangle(cornerRadius: 5).fill(v == value ? Theme.text : .clear))
                    .disabled(disabled(v))
                    .opacity(disabled(v) ? 0.35 : 1)
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 7).fill(Theme.ink.opacity(0.06)))
    }
}

/// Floating control island, centred at the bottom of the editor.
struct ControlIsland: View {
    @ObservedObject var project: Project
    @ObservedObject var transport: Transport
    @AppStorage("iconScale") private var iconScale = 1.0

    var body: some View {
        VStack(spacing: 8) {
            if let msg = project.errorMessage ?? project.toast {
                HStack(spacing: 6) {
                    if project.errorMessage != nil { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Theme.danger) }
                    Text(msg).lineLimit(2)
                    if project.errorMessage != nil {
                        Button { project.errorMessage = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }
                }
                .font(.system(size: 11)).foregroundStyle(Theme.text)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(Capsule().fill(Theme.card))
                .overlay(Capsule().stroke(Theme.ink.opacity(0.1), lineWidth: 1))
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }

            HStack(spacing: 12) {
                HStack(spacing: 6) {
                    Button { project.goToStart() } label: { Image(systemName: "backward.end.fill") }
                        .buttonStyle(RoundStyle(size: 28)).tip(Tips.toStart)
                    Button { project.togglePlay() } label: {
                        Image(systemName: transport.isPlaying ? "pause.fill" : "play.fill").offset(x: transport.isPlaying ? 0 : 1)
                    }
                    .buttonStyle(RoundStyle(active: true, tint: Theme.text, onTint: Theme.inverse, size: 36)).tip(Tips.play)
                    Button { project.toggleLoop() } label: { Image(systemName: "repeat") }
                        .buttonStyle(RoundStyle(active: project.loopEnabled, tint: Theme.loop, size: 28)).tip(Tips.loop)
                }

                VStack(alignment: .leading, spacing: 0) {
                    Text(timecode(transport.time, step: 0.01)).font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.text)
                    Text(timecode(project.duration, step: 0.01)).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Theme.muted)
                }
                .frame(width: 78, alignment: .leading)
                .tip(Tips.time)

                divider
                Toggle2(options: [(Source.original, "A"), (Source.enhanced, "B")], value: project.source,
                        disabled: { $0 == .enhanced && project.enhanced == nil }) { project.setSource($0) }
                    .tip(Tips.ab)
                Toggle2(options: [(ViewMode.waveform, "WAVE"), (ViewMode.spectrogram, "SPEC")], value: project.viewMode) {
                    project.setViewMode($0)
                }
                .tip(Tips.view)
                divider

                if project.processing {
                    Button { project.cancel() } label: {
                        HStack(spacing: 7) {
                            ProgressView(value: project.progress).progressViewStyle(.circular).controlSize(.mini).tint(Theme.accent)
                            Text("\(Int(project.progress * 100))%").font(.system(size: 11, weight: .semibold, design: .monospaced))
                            Image(systemName: "xmark").font(.system(size: 9, weight: .bold))
                        }
                    }
                    .buttonStyle(PillStyle())
                    .tip(Tips.cancel)
                } else {
                    Button { project.enhancedStale || project.enhanced == nil ? project.enhance() : project.enhanceAll() } label: {
                        HStack(spacing: 5) {
                            Image(systemName: "wand.and.stars")
                            Text(project.enhanced == nil ? "Enhance"
                                 : project.enhancedStale ? (project.staleRegions.isEmpty ? "Update" : "Update \(project.staleRegions.count)")
                                 : "Re-enhance")
                            if project.enhancedStale { Circle().fill(Theme.loop).frame(width: 6, height: 6) }
                        }
                    }
                    .buttonStyle(PillStyle(active: true))
                    .disabled(project.audio == nil || project.regions.isEmpty)
                    .tip(Tips.enhance)
                }
                Button { project.export() } label: { Image(systemName: "square.and.arrow.down") }
                    .buttonStyle(PillStyle())
                    .disabled(project.enhanced == nil || project.processing)
                    .tip(Tips.export)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 18)
                    .fill(Theme.island)
            )
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Theme.ink.opacity(0.11), lineWidth: 1))
            .shadow(color: .black.opacity(0.55), radius: 18, y: 6)
        }
        .scaleEffect(iconScale, anchor: .bottom) // vector UI: stays crisp at any size
        .animation(.easeOut(duration: 0.15), value: project.toast)
        .animation(.easeOut(duration: 0.15), value: project.errorMessage)
    }

    private var divider: some View { Rectangle().fill(Theme.ink.opacity(0.1)).frame(width: 1, height: 22) }
}

/// Whole-file strip with the visible window; click or drag to navigate.
struct OverviewView: View {
    @ObservedObject var project: Project

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height, d = max(project.duration, 0.001)
            Canvas { ctx, size in
                ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Theme.bg))
                for r in project.regions {
                    ctx.fill(Path(CGRect(x: r.start / d * w, y: 0, width: max(1, r.length / d * w), height: h)),
                             with: .color(Theme.speech.opacity(0.22)))
                }
                if let peaks = project.displayPeaks {
                    var p = Path()
                    for (i, (mn, mx)) in peaks.columns(t0: 0, t1: d, width: Int(w)).enumerated() {
                        p.move(to: CGPoint(x: CGFloat(i), y: h / 2 - CGFloat(mx) * h * 0.45))
                        p.addLine(to: CGPoint(x: CGFloat(i), y: h / 2 - CGFloat(mn) * h * 0.45 + 0.5))
                    }
                    ctx.stroke(p, with: .color(Theme.muted), lineWidth: 1)
                }
                if let l = project.loopRange, project.loopEnabled {
                    ctx.fill(Path(CGRect(x: l.lowerBound / d * w, y: 0, width: (l.upperBound - l.lowerBound) / d * w, height: 3)),
                             with: .color(Theme.loop))
                }
                let vr = CGRect(x: project.visibleStart / d * w, y: 0.5, width: max(4, project.visibleDuration / d * w), height: h - 1)
                ctx.fill(Path(roundedRect: vr, cornerRadius: 3), with: .color(Theme.ink.opacity(0.07)))
                ctx.stroke(Path(roundedRect: vr, cornerRadius: 3), with: .color(Theme.ink.opacity(0.35)), lineWidth: 1)
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                let t = Double(g.location.x / w) * d
                project.visibleStart = project.clampStart(t - project.visibleDuration / 2)
            })
        }
        .frame(height: 30)
        .tip(Tips.overview)
        .overlay(alignment: .top) { Rectangle().fill(Theme.ink.opacity(0.06)).frame(height: 1) }
    }
}
