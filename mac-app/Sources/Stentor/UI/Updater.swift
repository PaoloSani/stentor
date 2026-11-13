import AppKit
import Foundation
import SwiftUI

/// Manual "Check for Updates": asks GitHub for the latest Stentor release and compares versions.
/// Only runs when the user clicks the button; nothing is sent besides the request itself.
@MainActor
final class UpdateChecker: ObservableObject {
    enum State: Equatable {
        case idle, checking, upToDate(String), available(version: String, page: URL, dmg: URL?), failed(String)
    }

    static let latestAPI = URL(string: "https://api.github.com/repos/PaoloSani/speech-enhancer/releases/latest")!
    static let releasesPage = URL(string: "https://github.com/PaoloSani/speech-enhancer/releases/latest")!

    @Published private(set) var state: State = .idle

    /// Version of the running app (from Info.plist; "dev" for unbundled builds).
    static var currentVersion: String {
        if let v = ProcessInfo.processInfo.environment["STENTOR_VERSION_OVERRIDE"] { return v } // tests
        return Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    }

    private struct Release: Decodable {
        struct Asset: Decodable { let name: String; let browser_download_url: URL }
        let tag_name: String
        let html_url: URL
        let assets: [Asset]
    }

    func check() {
        guard state != .checking else { return }
        state = .checking
        let api = ProcessInfo.processInfo.environment["STENTOR_UPDATE_API"].flatMap(URL.init(string:)) ?? UpdateChecker.latestAPI // tests
        var req = URLRequest(url: api, timeoutInterval: 15)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("Stentor/\(UpdateChecker.currentVersion)", forHTTPHeaderField: "User-Agent")
        Task {
            do {
                let (data, resp) = try await URLSession.shared.data(for: req)
                guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
                let rel = try JSONDecoder().decode(Release.self, from: data)
                let latest = rel.tag_name.trimmingCharacters(in: CharacterSet(charactersIn: "vV"))
                if UpdateChecker.isNewer(latest, than: UpdateChecker.currentVersion) {
                    let dmg = rel.assets.first { $0.name.lowercased().hasSuffix(".dmg") }?.browser_download_url
                    state = .available(version: latest, page: rel.html_url, dmg: dmg)
                } else {
                    state = .upToDate(UpdateChecker.currentVersion)
                }
            } catch {
                state = .failed("Couldn't reach GitHub. Check your connection and try again.")
            }
        }
    }

    /// Semantic-version comparison ("0.10.0" > "0.9.2"); a "dev" build is never out of date.
    static func isNewer(_ a: String, than b: String) -> Bool {
        guard b != "dev" else { return false }
        let pa = a.split(separator: ".").map { Int($0) ?? 0 }, pb = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(pa.count, pb.count) {
            let x = i < pa.count ? pa[i] : 0, y = i < pb.count ? pb[i] : 0
            if x != y { return x > y }
        }
        return false
    }
}

/// "Version x.y.z · Check for Updates" line of the about card, with the result inline.
struct UpdateRow: View {
    @ObservedObject var updates: UpdateChecker

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Text("Version \(UpdateChecker.currentVersion)").font(.system(size: 10.5, design: .monospaced)).foregroundStyle(Theme.muted)
                Text("·").foregroundStyle(Theme.muted)
                Button { updates.check() } label: {
                    HStack(spacing: 4) {
                        if updates.state == .checking { ProgressView().controlSize(.mini) }
                        else { Image(systemName: "arrow.triangle.2.circlepath") }
                        Text("Check for Updates")
                    }
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(Theme.speech)
                }
                .buttonStyle(.plain)
                .disabled(updates.state == .checking)
                .help("Looks up the latest release on GitHub")
            }
            switch updates.state {
            case .upToDate(let v):
                Label("Stentor \(v) is the latest version.", systemImage: "checkmark.circle.fill")
                    .font(.system(size: 11)).foregroundStyle(Theme.speech)
            case .available(let v, let page, let dmg):
                VStack(spacing: 6) {
                    Text("Stentor \(v) is available.").font(.system(size: 11.5, weight: .semibold)).foregroundStyle(Theme.text)
                    HStack(spacing: 8) {
                        Button("Download \(v)") { NSWorkspace.shared.open(dmg ?? page) }.buttonStyle(PillStyle(active: true))
                        Button("What's new") { NSWorkspace.shared.open(page) }.buttonStyle(PillStyle())
                    }
                    Text("Open the downloaded DMG and run the installer: it replaces this version and keeps your settings.")
                        .font(.system(size: 10)).foregroundStyle(Theme.muted).multilineTextAlignment(.center).frame(maxWidth: 260)
                }
            case .failed(let msg):
                Text(msg).font(.system(size: 10.5)).foregroundStyle(Theme.danger)
            default:
                EmptyView()
            }
        }
    }
}
