import AppKit
import SwiftUI

enum Links {
    static let wikipedia = URL(string: "https://en.wikipedia.org/wiki/Stentor")!
    static let sidon = URL(string: "https://github.com/sarulab-speech/Sidon")!
    /// Public form (Tally) for feedback without a GitHub account. Paste the form's share link here;
    /// while it is empty, "Send Feedback" falls back to GitHub issues.
    static let feedbackForm = ""
    static let githubIssues = URL(string: "https://github.com/PaoloSani/speech-enhancer/issues/new")!

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    }

    /// The feedback form with app and macOS version pre-filled (Tally hidden fields `version`, `macos`),
    /// or the GitHub issue page if no form is configured.
    static var feedback: URL {
        guard var c = URLComponents(string: feedbackForm), c.host != nil else { return githubIssues }
        let os = ProcessInfo.processInfo.operatingSystemVersion
        c.queryItems = (c.queryItems ?? []) + [
            URLQueryItem(name: "version", value: appVersion),
            URLQueryItem(name: "macos", value: "\(os.majorVersion).\(os.minorVersion).\(os.patchVersion)"),
        ]
        return c.url ?? githubIssues
    }
}

/// The STENTOR wordmark: Didot capitals, wide tracking, mint-to-green gradient.
struct Wordmark: View {
    var size: CGFloat = 26
    var showGreek = false

    static let gradient = LinearGradient(
        colors: [Theme.wordTop, Theme.wordBottom],
        startPoint: .top, endPoint: .bottom)

    var body: some View {
        VStack(alignment: .center, spacing: size * 0.12) {
            Text("STENTOR")
                .font(.custom("Didot-Bold", size: size))
                .tracking(size * 0.22)
                .foregroundStyle(Wordmark.gradient)
            if showGreek {
                // Greek name: larger, brighter and less spaced than a typical subtitle so it stays legible
                Text("Στέντωρ")
                    .font(.system(size: size * 0.46, weight: .medium, design: .serif))
                    .tracking(size * 0.04)
                    .foregroundStyle(Theme.text.opacity(0.78))
            }
        }
        .fixedSize()
    }
}

struct HeaderBar: View {
    @ObservedObject var project: Project
    @ObservedObject var window: WindowState

    @StateObject private var fileHover = Flag()
    @AppStorage("iconScale") private var iconScale = 1.0

    var body: some View {
        HStack(spacing: 18) {
            Button { window.showAbout = true } label: { Wordmark(size: 25) }
                .buttonStyle(.plain)
                .tip(Tips.logo)
                .padding(.leading, 82) // clear of the window's traffic lights
            Spacer(minLength: 12)
            Text(project.modelStatus).font(.system(size: 10.5)).foregroundStyle(Theme.muted).lineLimit(1)
            Button { window.showSettings.toggle() } label: {
                Image(systemName: "gearshape").font(.system(size: 14 * iconScale, weight: .medium)).foregroundStyle(Theme.text)
                    .frame(width: 30 * iconScale, height: 26 * iconScale)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Theme.ink.opacity(window.showSettings ? 0.14 : 0.06)))
            }
            .buttonStyle(.plain)
            .tip(Tips.gear)
            .popover(isPresented: $window.showSettings, arrowEdge: .bottom) {
                SettingsPanel(project: project).frame(width: 360)
            }
            .padding(.trailing, 14)
        }
        .frame(height: 56)
        .overlay { if let a = project.audio { filePill(a) } } // centred in the window, independent of the sides
        .background(Theme.header)
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.ink.opacity(0.07)).frame(height: 1) }
        .windowDraggable()
    }

    /// File name + details, centred; the whole pill (and its folder icon) opens another file.
    private func filePill(_ a: LoadedAudio) -> some View {
        Button { project.openPanel() } label: {
            HStack(spacing: 10) {
                Image(systemName: "folder.badge.plus")
                    .font(.system(size: 14 * iconScale, weight: .medium))
                    .foregroundStyle(fileHover.on ? Theme.speech : Theme.muted)
                    .frame(width: 28 * iconScale, height: 28 * iconScale)
                    .background(RoundedRectangle(cornerRadius: 7).fill(Theme.ink.opacity(fileHover.on ? 0.1 : 0.05)))
                VStack(alignment: .leading, spacing: 1) {
                    Text(a.url.lastPathComponent).font(.system(size: 12.5, weight: .semibold)).foregroundStyle(Theme.text)
                        .lineLimit(1).truncationMode(.middle)
                    Text(meta(a)).font(.system(size: 10.5, design: .monospaced)).foregroundStyle(Theme.muted).lineLimit(1)
                }
            }
            .padding(.leading, 6).padding(.trailing, 14).padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 10).fill(Theme.ink.opacity(fileHover.on ? 0.06 : 0)))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.ink.opacity(fileHover.on ? 0.12 : 0), lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { fileHover.on = $0 }
        .frame(maxWidth: 520)
        .tip(Tips.fileInfo)
    }

    private func meta(_ a: LoadedAudio) -> String {
        let speech = String(format: "%.1f s speech in %d region%@", project.speechSeconds, project.regions.count, project.regions.count == 1 ? "" : "s")
        return String(format: "%.1f kHz · %@ · %@ · ", a.sourceRate / 1000, a.channels == 1 ? "mono" : "\(a.channels) ch",
                      timecode(a.duration, step: 0.1)) + speech
    }
}

/// Small centred card: credits, link to Sidon; the wordmark links to Stentor on Wikipedia.
struct AboutCard: View {
    @ObservedObject var window: WindowState
    @StateObject private var hoverLogo = Flag()
    @StateObject private var updates = UpdateChecker()

    var body: some View {
        ZStack {
            Color.black.opacity(0.45).ignoresSafeArea()
                .onTapGesture { window.showAbout = false }
            VStack(spacing: 16) {
                Button { NSWorkspace.shared.open(Links.wikipedia) } label: {
                    VStack(spacing: 6) {
                        Wordmark(size: 38, showGreek: true)
                        HStack(spacing: 4) {
                            Text("Who was Stentor?")
                            Image(systemName: "arrow.up.right")
                        }
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(hoverLogo.on ? Theme.speech : Theme.muted)
                        .underline(hoverLogo.on)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Theme.ink.opacity(hoverLogo.on ? 0.05 : 0)))
                }
                .buttonStyle(.plain)
                .onHover { inside in
                    hoverLogo.on = inside
                    if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
                }
                .help("Stentor, herald of the Greeks in the Iliad — open Wikipedia")

                Text("Voice restoration for macOS").font(.system(size: 12)).foregroundStyle(Theme.text.opacity(0.75))

                Rectangle().fill(Theme.ink.opacity(0.08)).frame(width: 220, height: 1)

                VStack(spacing: 4) {
                    Text("Built by Paolo Sani").font(.system(size: 12.5, weight: .semibold)).foregroundStyle(Theme.text)
                    HStack(spacing: 4) {
                        Text("Powered by")
                        Button { NSWorkspace.shared.open(Links.sidon) } label: {
                            HStack(spacing: 2) { Text("Sidon"); Image(systemName: "arrow.up.right").font(.system(size: 9)) }
                                .foregroundStyle(Theme.speech)
                        }
                        .buttonStyle(.plain)
                        .help("Sidon on GitHub — the open-source speech restoration model")
                        Text("· University of Tokyo")
                    }
                    .font(.system(size: 11)).foregroundStyle(Theme.muted)
                }

                Button { NSWorkspace.shared.open(Links.feedback) } label: {
                    HStack(spacing: 5) { Image(systemName: "bubble.left"); Text("Send Feedback") }
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(Theme.speech)
                        .padding(.horizontal, 12).padding(.vertical, 5)
                        .background(Capsule().fill(Theme.speech.opacity(0.12)))
                }
                .buttonStyle(.plain)
                .help("Ideas, bugs or anything else — opens a short form in your browser")

                UpdateRow(updates: updates)
            }
            .padding(.horizontal, 34).padding(.vertical, 26)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.ink.opacity(0.1), lineWidth: 1))
            .overlay(alignment: .topTrailing) {
                Button { window.showAbout = false } label: {
                    Image(systemName: "xmark").font(.system(size: 10, weight: .bold)).foregroundStyle(Theme.muted)
                        .frame(width: 22, height: 22).background(Circle().fill(Theme.ink.opacity(0.06)))
                }
                .buttonStyle(.plain).keyboardShortcut(.cancelAction).padding(10)
            }
            .shadow(color: .black.opacity(0.5), radius: 30, y: 10)
        }
    }
}

/// Settings: help, speech detection, processing and export. Used in the gear popover and ⌘,.
struct SettingsPanel: View {
    @ObservedObject var project: Project
    @AppStorage("detailedTooltips") var detailedTooltips = true
    @AppStorage("iconScale") var iconScale = 1.0
    @AppStorage("appearance") var appearance = AppearanceMode.auto.rawValue

    var body: some View {
        Form {
            Section("Appearance") {
                Picker("Theme", selection: $appearance) {
                    Text("Auto").tag(AppearanceMode.auto.rawValue)
                    Text("Dark").tag(AppearanceMode.dark.rawValue)
                    Text("Light").tag(AppearanceMode.light.rawValue)
                }
                .pickerStyle(.segmented)
                .onChange(of: appearance) { _, v in NSApp.appearance = AppearanceMode(rawValue: v)?.nsAppearance }
                Picker("Icon size", selection: $iconScale) {
                    Text("Standard").tag(1.0)
                    Text("Large").tag(1.25)
                    Text("Extra large").tag(1.5)
                }
                .pickerStyle(.segmented)
                Text("Auto follows macOS (System Settings › Appearance). Icon size scales the control island, header icons and the handles and ✕ on the green regions.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Section("Help") {
                Toggle("Detailed tooltips", isOn: $detailedTooltips)
                Text("Hovering any control or part of the editor explains what it does, with shortcuts. Off: short native tooltips only.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Section("Speech detection") {
                slider("Threshold", value: $project.detection.thresholdDb, range: -70 ... -20, format: "%.0f dB")
                slider("Pre-roll", value: $project.detection.preRoll, range: 0...0.5, format: "%.2f s")
                slider("Post-roll", value: $project.detection.postRoll, range: 0...0.8, format: "%.2f s")
                slider("Merge gaps under", value: $project.detection.mergeGap, range: 0...1.5, format: "%.2f s")
                HStack {
                    Button("Clear regions") { project.clearRegions() }
                    Spacer()
                    Button("Detect again") { project.detect() }.disabled(project.audio == nil)
                }
            }
            Section("Processing") {
                Picker("Model precision", selection: Binding(get: { project.precision }, set: { project.setPrecision($0) })) {
                    Text("float32 · maximum fidelity").tag("float32")
                    if SidonModel.locate(precision: "float16") != nil {
                        Text("float16 · faster, less memory").tag("float16")
                    }
                }
            }
            Section("Export") {
                Picker("Sample rate", selection: $project.exportRate) {
                    Text("48 kHz (model output)").tag(ExportRate.model)
                    Text("Same as source").tag(ExportRate.source)
                }
                Picker("Format", selection: $project.exportFormat) {
                    Text("WAV 16-bit").tag(ExportFormat.pcm16)
                    Text("WAV 24-bit").tag(ExportFormat.pcm24)
                    Text("WAV 32-bit float").tag(ExportFormat.float32)
                }
            }
        }
        .formStyle(.grouped)
        .controlSize(.small)
    }

    private func slider(_ label: String, value: Binding<Double>, range: ClosedRange<Double>, format: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(label)
                Spacer()
                Text(String(format: format, value.wrappedValue)).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
            }
            Slider(value: value, in: range).labelsHidden()
        }
    }
}

extension View {
    /// Lets the header move the window (the title bar is hidden).
    @ViewBuilder func windowDraggable() -> some View {
        if #available(macOS 15.0, *) { self.gesture(WindowDragGesture()) } else { self }
    }
}
