import SwiftUI

/// First-launch card: downloads the voice model (the DMG ships without it).
struct ModelSetupView: View {
    @ObservedObject var project: Project
    @ObservedObject var installer: ModelInstaller

    var body: some View {
        ZStack {
            Color.black.opacity(0.4).ignoresSafeArea()
            VStack(spacing: 16) {
                Wordmark(size: 30)
                Text("One more step: the voice model").font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.text)
                Text("Stentor restores speech with Sidon, a neural model of about 930 MB. It is downloaded once from GitHub, verified and kept on this Mac — app updates won't download it again.")
                    .font(.system(size: 12)).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
                    .frame(maxWidth: 380).fixedSize(horizontal: false, vertical: true)

                content
            }
            .padding(.horizontal, 34).padding(.vertical, 28)
            .frame(width: 470)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.ink.opacity(0.1), lineWidth: 1))
            .shadow(color: .black.opacity(0.4), radius: 30, y: 10)
        }
    }

    @ViewBuilder private var content: some View {
        switch installer.phase {
        case .idle:
            buttons(primary: "Download (930 MB)")
        case .downloading(let got, let total):
            VStack(spacing: 8) {
                ProgressView(value: Double(got), total: Double(max(total, 1))).tint(Theme.accent).frame(width: 320)
                Text(String(format: "%.0f of %.0f MB", Double(got) / 1e6, Double(total) / 1e6))
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.muted)
                Button("Cancel") { installer.cancel() }.buttonStyle(PillStyle())
            }
        case .verifying, .installing:
            HStack(spacing: 8) { ProgressView().controlSize(.small); Text("Verifying and installing…").font(.system(size: 12)) }
                .foregroundStyle(Theme.text)
        case .done:
            Label("Voice model installed", systemImage: "checkmark.circle.fill").foregroundStyle(Theme.speech)
        case .failed(let msg):
            VStack(spacing: 10) {
                Text(msg).font(.system(size: 11.5)).foregroundStyle(Theme.danger).multilineTextAlignment(.center).frame(maxWidth: 380)
                buttons(primary: "Try Again")
            }
        }
    }

    private func buttons(primary: String) -> some View {
        HStack(spacing: 10) {
            Button { installer.start() } label: { Label(primary, systemImage: "arrow.down.circle") }
                .buttonStyle(PillStyle(active: true))
            Button("Locate Models…") { project.locateModelsFolder() }
                .buttonStyle(PillStyle())
                .help("Use a folder that already contains the .mlpackage files (e.g. exported with stentor-engine)")
        }
    }
}
