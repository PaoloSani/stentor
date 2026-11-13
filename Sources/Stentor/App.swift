import SwiftUI

@main
struct StentorApp: App {
    @StateObject private var project = Project()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    init() {
        SelfTest.runIfRequested()
        NSApp?.appearance = AppearanceMode.current.nsAppearance
    }

    var body: some Scene {
        Window("Stentor", id: "main") {
            ContentView(project: project)
                .onAppear { delegate.project = project }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1180, height: 640)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open…") { project.openPanel() }.keyboardShortcut("o")
                Button("Open Demo Recording") { project.openDemo() }
            }
            CommandGroup(replacing: .saveItem) {
                Button("Export Enhanced…") { project.export() }.keyboardShortcut("e").disabled(project.enhanced == nil)
                Button("Export Speech Regions…") { project.exportRegions() }
                    .keyboardShortcut("e", modifiers: [.command, .shift]).disabled(project.enhanced == nil || project.regions.isEmpty)
            }
            CommandGroup(replacing: .undoRedo) {
                Button("Undo") { project.undo() }.keyboardShortcut("z")
                Button("Redo") { project.redo() }.keyboardShortcut("z", modifiers: [.command, .shift])
            }
            CommandMenu("Transport") {
                Button("Play / Pause") { project.togglePlay() }.keyboardShortcut(.space, modifiers: [])
                Button("Go to Start") { project.goToStart() }.keyboardShortcut(.home, modifiers: [])
                Button("Loop") { project.toggleLoop() }.keyboardShortcut("l", modifiers: [])
                Button("Compare A / B") { project.toggleSource() }.keyboardShortcut("b", modifiers: [])
            }
            CommandMenu("Regions") {
                Button("Detect Speech") { project.detect() }.keyboardShortcut("d", modifiers: [.command, .shift])
                Button("Delete Selected Region") {
                    if let id = project.selected { project.removeRegion(id) }
                }.keyboardShortcut(.delete, modifiers: [])
                Button("Clear All Regions") { project.clearRegions() }
                Divider()
                Button("Enhance (changed regions)") { project.enhance() }.keyboardShortcut(.return, modifiers: [.command])
                Button("Enhance Selected Region") {
                    if let id = project.selected { project.enhanceRegion(id) }
                }.keyboardShortcut(.return, modifiers: [.command, .shift])
                Button("Re-enhance Everything") { project.enhanceAll() }
            }
            CommandGroup(after: .toolbar) {
                Button("Waveform / Spectrogram") {
                    project.setViewMode(project.viewMode == .waveform ? .spectrogram : .waveform)
                }.keyboardShortcut("s", modifiers: [])
                Button("Zoom In") { project.zoom(by: 1.6, around: project.visibleStart + project.visibleDuration / 2) }.keyboardShortcut("=")
                Button("Zoom Out") { project.zoom(by: 1 / 1.6, around: project.visibleStart + project.visibleDuration / 2) }.keyboardShortcut("-")
                Button("Zoom to Fit") { project.zoomToFit() }.keyboardShortcut("0")
            }
            CommandGroup(replacing: .help) {
                Button("Send Feedback…") { NSWorkspace.shared.open(Links.feedback) }
                Button("Check for Updates…") { NSWorkspace.shared.open(UpdateChecker.releasesPage) }
                Button("Report an Issue on GitHub…") { NSWorkspace.shared.open(Links.githubIssues) }
                Divider()
                Button("Who was Stentor?") { NSWorkspace.shared.open(Links.wikipedia) }
                Button("Sidon on GitHub") { NSWorkspace.shared.open(Links.sidon) }
            }
        }

        Settings {
            SettingsPanel(project: project).frame(width: 420)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var project: Project?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = AppearanceMode.current.nsAppearance
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func application(_ application: NSApplication, open urls: [URL]) {
        if let url = urls.first { Task { @MainActor in self.project?.open(url) } }
    }
}
