import SwiftUI

/// Local boolean UI state (stands in for @State, whose macro plugin needs full Xcode).
final class Flag: ObservableObject { @Published var on = false }

/// Small rounded control used in the island. `scale` = Settings › Icon size; sizes are laid out
/// at that scale (not magnified afterwards) so text and symbols stay sharp.
struct PillStyle: ButtonStyle {
    var active = false
    var tint: Color = Theme.accent
    var scale: CGFloat = 1
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 11 * scale, weight: .semibold))
            .padding(.horizontal, 9 * scale).frame(height: 26 * scale)
            .foregroundStyle(active ? Theme.onAccent : Theme.text)
            .background(
                RoundedRectangle(cornerRadius: 7 * scale)
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
    var scale: CGFloat = 1
    var disabled: (T) -> Bool = { _ in false }
    let set: (T) -> Void
    var body: some View {
        HStack(spacing: 0) {
            ForEach(options.indices, id: \.self) { i in
                let (v, label) = options[i]
                Button(label) { set(v) }
                    .buttonStyle(.plain)
                    .font(.system(size: 10.5 * scale, weight: .bold))
                    .padding(.horizontal, 9 * scale).frame(height: 22 * scale)
                    .foregroundStyle(v == value ? Theme.inverse : Theme.muted)
                    .background(RoundedRectangle(cornerRadius: 5 * scale).fill(v == value ? Theme.text : .clear))
                    .disabled(disabled(v))
                    .opacity(disabled(v) ? 0.35 : 1)
            }
        }
        .padding(2 * scale)
        .background(RoundedRectangle(cornerRadius: 7 * scale).fill(Theme.ink.opacity(0.06)))
    }
}

/// Floating control island, centred at the bottom of the editor.
struct ControlIsland: View {
    @ObservedObject var project: Project
    @ObservedObject var transport: Transport
    @AppStorage("iconScale") private var iconScale = 1.0

    var body: some View {
        let s = CGFloat(iconScale)
        VStack(spacing: 8 * s) {
            if let msg = project.errorMessage ?? project.toast {
                HStack(spacing: 6 * s) {
                    if project.errorMessage != nil { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Theme.danger) }
                    Text(msg).lineLimit(2)
                    if project.errorMessage != nil {
                        Button { project.errorMessage = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }
                }
                .font(.system(size: 11 * s)).foregroundStyle(Theme.text)
                .padding(.horizontal, 12 * s).padding(.vertical, 6 * s)
                .background(Capsule().fill(Theme.card))
                .overlay(Capsule().stroke(Theme.ink.opacity(0.1), lineWidth: 1))
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }

            HStack(spacing: 12 * s) {
                HStack(spacing: 6 * s) {
                    Button { project.goToStart() } label: { Image(systemName: "backward.end.fill") }
                        .buttonStyle(RoundStyle(size: 28 * s)).tip(Tips.toStart)
                    Button { project.togglePlay() } label: {
                        Image(systemName: transport.isPlaying ? "pause.fill" : "play.fill").offset(x: transport.isPlaying ? 0 : s)
                    }
                    .buttonStyle(RoundStyle(active: true, tint: Theme.text, onTint: Theme.inverse, size: 36 * s)).tip(Tips.play)
                    Button { project.toggleLoop() } label: { Image(systemName: "repeat") }
                        .buttonStyle(RoundStyle(active: project.loopEnabled, tint: Theme.loop, size: 28 * s)).tip(Tips.loop)
                }

                VStack(alignment: .leading, spacing: 0) {
                    Text(timecode(transport.time, step: 0.01)).font(.system(size: 14 * s, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.text)
                    Text(timecode(project.duration, step: 0.01)).font(.system(size: 9.5 * s, design: .monospaced)).foregroundStyle(Theme.muted)
                }
                .frame(width: 78 * s, alignment: .leading)
                .tip(Tips.time)

                divider(s)
                Toggle2(options: [(Source.original, "A"), (Source.enhanced, "B")], value: project.source, scale: s,
                        disabled: { $0 == .enhanced && project.enhanced == nil }) { project.setSource($0) }
                    .tip(Tips.ab)
                Toggle2(options: [(ViewMode.waveform, "WAVE"), (ViewMode.spectrogram, "SPEC")], value: project.viewMode, scale: s) {
                    project.setViewMode($0)
                }
                .tip(Tips.view)
                divider(s)

                if project.processing {
                    Button { project.cancel() } label: {
                        HStack(spacing: 7 * s) {
                            ProgressView(value: project.progress).progressViewStyle(.circular).controlSize(s > 1.2 ? .small : .mini).tint(Theme.accent)
                            Text("\(Int(project.progress * 100))%").font(.system(size: 11 * s, weight: .semibold, design: .monospaced))
                            Image(systemName: "xmark").font(.system(size: 9 * s, weight: .bold))
                        }
                    }
                    .buttonStyle(PillStyle(scale: s))
                    .tip(Tips.cancel)
                } else {
                    Button { project.enhancedStale || project.enhanced == nil ? project.enhance() : project.enhanceAll() } label: {
                        HStack(spacing: 5 * s) {
                            Image(systemName: "wand.and.stars")
                            Text(project.enhanced == nil ? "Enhance"
                                 : project.enhancedStale ? (project.staleRegions.isEmpty ? "Update" : "Update \(project.staleRegions.count)")
                                 : "Re-enhance")
                            if project.enhancedStale { Circle().fill(Theme.loop).frame(width: 6 * s, height: 6 * s) }
                        }
                    }
                    .buttonStyle(PillStyle(active: true, scale: s))
                    .disabled(project.audio == nil || project.regions.isEmpty)
                    .tip(Tips.enhance)
                }
                Button { project.export() } label: { Image(systemName: "square.and.arrow.down") }
                    .buttonStyle(PillStyle(scale: s))
                    .disabled(project.enhanced == nil || project.processing)
                    .tip(Tips.export)
            }
            .padding(.horizontal, 12 * s).padding(.vertical, 8 * s)
            .background(RoundedRectangle(cornerRadius: 18 * s).fill(Theme.island))
            .overlay(RoundedRectangle(cornerRadius: 18 * s).stroke(Theme.ink.opacity(0.11), lineWidth: 1))
            .shadow(color: .black.opacity(0.35), radius: 18, y: 6)
        }
        .animation(.easeOut(duration: 0.15), value: project.toast)
        .animation(.easeOut(duration: 0.15), value: project.errorMessage)
    }

    private func divider(_ s: CGFloat) -> some View { Rectangle().fill(Theme.ink.opacity(0.1)).frame(width: 1, height: 22 * s) }
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
