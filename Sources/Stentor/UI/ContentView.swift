import SwiftUI
import UniformTypeIdentifiers

/// Window-level UI state.
final class WindowState: ObservableObject {
    @Published var dropTarget = false
    @Published var showAbout = false
    @Published var showSettings = false
}

struct ContentView: View {
    @ObservedObject var project: Project
    @StateObject private var tips = TipCenter()
    @StateObject private var window = WindowState()

    var body: some View {
        MainView(project: project, tips: tips, window: window, interactive: true)
            .onDrop(of: [.fileURL], isTargeted: $window.dropTarget) { providers in
                guard let item = providers.first else { return false }
                _ = item.loadObject(ofClass: URL.self) { url, _ in
                    if let url { Task { @MainActor in project.open(url) } }
                }
                return true
            }
            .frame(minWidth: 880, minHeight: 460)
            .onAppear { project.openDemoOnFirstLaunch() }
            .ignoresSafeArea(.container, edges: .top)
    }
}

/// The whole window: header, editor with the floating control island, overview, overlays.
/// Shared by the app and the headless snapshot renderer (`interactive: false`).
struct MainView: View {
    @ObservedObject var project: Project
    @ObservedObject var tips: TipCenter
    @ObservedObject var window: WindowState
    var interactive = true
    @AppStorage("appearance") private var appearance = AppearanceMode.auto.rawValue

    var body: some View {
        VStack(spacing: 0) {
            HeaderBar(project: project, window: window)
            ZStack(alignment: .bottom) {
                if project.audio == nil {
                    EmptyStateView(project: project, highlighted: window.dropTarget)
                } else {
                    VStack(spacing: 0) {
                        EditorView(project: project, interactive: interactive)
                        OverviewView(project: project)
                    }
                }
                ControlIsland(project: project, transport: project.player.transport)
                    .padding(.bottom, project.audio == nil ? 22 : 44)
            }
        }
        .background(Theme.bg)
        .coordinateSpace(name: "root")
        .overlay { if project.needsModels { ModelSetupView(project: project, installer: project.installer) } }
        .overlay { if window.showAbout { AboutCard(window: window) } }
        .overlay(TipOverlay(tips: tips))
        .environmentObject(tips)
        .preferredColorScheme(AppearanceMode(rawValue: appearance)?.colorScheme)
    }
}

struct EmptyStateView: View {
    @ObservedObject var project: Project
    let highlighted: Bool

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "waveform").font(.system(size: 40, weight: .light)).foregroundStyle(Theme.speech)
            Text(project.loading ? project.status : "Drop a voice recording here")
                .font(.system(size: 16, weight: .medium)).foregroundStyle(Theme.text)
            if project.loading { ProgressView().controlSize(.small) }
            else {
                HStack(spacing: 8) {
                    Button("Open…") { project.openPanel() }.buttonStyle(PillStyle(active: true)).keyboardShortcut("o")
                    if Project.demoURL != nil {
                        Button("Try the demo") { project.openDemo() }.buttonStyle(PillStyle())
                    }
                }
                Text("Speech is detected automatically and shown in green — only those parts are restored;\nthe rest stays silent and the output keeps the original length.")
                    .font(.system(size: 11)).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(highlighted ? Theme.speech : Theme.ink.opacity(0.1), style: StrokeStyle(lineWidth: 1.5, dash: [6, 5]))
                .padding(24)
        )
    }
}
