import AppKit
import SwiftUI
import Foundation

/// Headless checks used to validate the Swift engine against the Python reference.
///   Stentor       --fbank in.f32 out.f32          raw float32 16 kHz -> raw float32 features (T x 160)
///   Stentor       --enhance-raw in.f32 out.f32    raw float32 16 kHz -> model output at 48 kHz
///   Stentor       --process in.wav out.wav        full pipeline (load, detect, render, write)
///   Stentor       --logic in.wav                  region editing rules + looped playback (muted)
///   Stentor       --snapshot in.wav out.png [spec] [enhanced] [zoom=a-b] [loop=a-b] [select]
enum SelfTest {
    static func runIfRequested() {
        let args = CommandLine.arguments
        if args.count >= 3, args[1] == "--incremental" { MainActor.assumeIsolated { incremental(args[2]) }; exit(0) }
        if args.count >= 3, args[1] == "--logic" { MainActor.assumeIsolated { logic(args[2]) }; exit(0) }
        if args.count >= 4, args[1] == "--snapshot" { MainActor.assumeIsolated { snapshot(args) }; exit(0) }
        guard args.count >= 4, ["--fbank", "--enhance-raw", "--process"].contains(args[1]) else { return }
        do {
            let inURL = URL(fileURLWithPath: args[2]), outURL = URL(fileURLWithPath: args[3])
            switch args[1] {
            case "--fbank":
                let x = try readF32(inURL)
                let t0 = Date()
                let (frames, data) = Fbank().features(x)
                print("fbank: \(frames) frames in \(String(format: "%.3f", Date().timeIntervalSince(t0)))s")
                try writeF32(data, outURL)
            case "--enhance-raw":
                let x = try readF32(inURL)
                let m = try SidonModel()
                _ = try m.enhance(Array(x.prefix(16_000)))
                let t0 = Date()
                let y = try m.enhance(x)
                print("enhance: \(x.count) samples in \(String(format: "%.2f", Date().timeIntervalSince(t0)))s")
                try writeF32(y, outURL)
            default:
                var t0 = Date()
                let audio = try AudioIO.load(inURL)
                print(String(format: "loaded %.1fs (%.0f Hz, %d ch) in %.2fs", audio.duration, audio.sourceRate, audio.channels, Date().timeIntervalSince(t0)))
                t0 = Date()
                let regions = VoiceDetector.detect(audio.wav16k)
                let speech = regions.reduce(0) { $0 + $1.length }
                print(String(format: "detect: %d regions, %.1fs of speech in %.3fs", regions.count, speech, Date().timeIntervalSince(t0)))
                for r in regions { print(String(format: "  %.2f - %.2f", r.start, r.end)) }
                t0 = Date()
                let model = try SidonModel { print($0) }
                print(String(format: "model ready in %.1fs", Date().timeIntervalSince(t0)))
                t0 = Date()
                let out = try Renderer(model: model).render(audio, regions: regions, progress: { _ in }, isCancelled: { false })!
                let el = Date().timeIntervalSince(t0)
                print(String(format: "render: %.1fs (%.1fx real time over the whole file)", el, audio.duration / el))
                print("cpu fallbacks: \(model.cpuFallbacks)")
                try AudioIO.writeWav(out, sampleRate: 48_000, to: outURL)
                print("wrote \(outURL.path) (\(out.count) samples)")
            }
            exit(0)
        } catch {
            FileHandle.standardError.write("error: \(error.localizedDescription)\n".data(using: .utf8)!)
            exit(1)
        }
    }

    /// --snapshot in.wav out.png [spec] [enhanced] [zoom=a-b] [loop=a-b] [select]
    @MainActor static func snapshot(_ args: [String]) {
        let opts = Set(args.dropFirst(4))
        let p = Project(preload: false)
        do {
            let model = opts.contains("enhanced") ? try SidonModel() : nil
            try p.loadSync(URL(fileURLWithPath: args[2]), enhanceWith: model)
        } catch { print("snapshot error: \(error)"); return }
        if opts.contains("spec") { p.viewMode = .spectrogram }
        if opts.contains("enhanced") { p.source = .enhanced }
        for o in opts {
            let parts = o.split(separator: "=")
            guard parts.count == 2 else { continue }
            let v = parts[1].split(separator: "-").compactMap { Double($0) }
            if parts[0] == "zoom", v.count == 2 { p.visibleStart = v[0]; p.visibleDuration = v[1] - v[0] }
            if parts[0] == "loop", v.count == 2 { p.loopRange = v[0]...v[1]; p.loopEnabled = true }
        }
        if opts.contains("select") { p.selected = p.regions.first?.id }
        p.editorWidth = 1180
        p.requestSpectrogram(sync: true)
        p.player.transport.time = p.visibleStart + p.visibleDuration * 0.4
        let tips = TipCenter()
        let catalogue: [String: TipInfo] = ["enhance": Tips.enhance, "bar": Tips.bar, "ab": Tips.ab, "logo": Tips.logo, "empty": Tips.empty, "gear": Tips.gear, "loop": Tips.loop]
        for o in opts where o.hasPrefix("tip=") {
            let parts = o.dropFirst(4).split(separator: "@")
            if let info = catalogue[String(parts[0])] {
                let xy = parts.count > 1 ? parts[1].split(separator: ",").compactMap { Double($0) } : [550, 300]
                tips.show(info, at: CGPoint(x: xy[0], y: xy[1]))
            }
        }
        p.toast = opts.contains("toast") ? "Enhanced in 11.5 s" : nil
        p.modelStatus = opts.contains("enhanced") ? "Core ML · GPU · float32" : ""
        UserDefaults.standard.set(opts.first { $0.hasPrefix("scale=") }.flatMap { Double($0.dropFirst(6)) } ?? 1.0, forKey: "iconScale")
        let win = WindowState()
        win.showAbout = opts.contains("about")
        let view = MainView(project: p, tips: tips, window: win, interactive: false)
            .frame(width: 1180, height: 620)
        let mode = AppearanceMode(rawValue: opts.first { $0.hasPrefix("theme=") }.map { String($0.dropFirst(6)) } ?? "dark") ?? .dark
        UserDefaults.standard.set(mode.rawValue, forKey: "appearance")
        NSApp?.appearance = mode.nsAppearance
        NSAppearance.current = mode.nsAppearance
        let r = ImageRenderer(content: view.environment(\.colorScheme, mode == .light ? .light : .dark))
        r.scale = 2
        guard let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else { print("render failed"); return }
        try? png.write(to: URL(fileURLWithPath: args[3]))
        print("snapshot -> \(args[3])")
    }

    /// --logic in.wav : region editing rules, undo/redo and looped playback position.
    @MainActor static func logic(_ path: String) {
        let p = Project(preload: false)
        try! p.loadSync(URL(fileURLWithPath: path))
        func show(_ tag: String) { print(tag.padding(toLength: 26, withPad: " ", startingAt: 0), p.regions.map { String(format: "%.2f-%.2f", $0.start, $0.end) }) }
        show("detected")
        p.insertRegion(at: 2.0); show("click at 2.0 (before)")
        p.insertRegion(at: 60.0); show("click at 60.0 (after)")
        let first = p.regions[0].id
        p.beginEdit(); p.moveEdge(first, isStart: false, to: 50); show("drag end of #1 to 50")
        p.beginEdit(); p.moveEdge(first, isStart: true, to: 0.5); show("drag start of #1 to 0.5")
        p.addRegion(45, 47); show("draw 45-47 (overlap)")
        p.removeRegion(p.regions.last!.id); show("remove last")
        p.undo(); show("undo"); p.undo(); show("undo")
        p.redo(); show("redo")
        print("stale before enhance:", p.enhancedStale)

        p.player.setSignal(p.audio!.listen, rate: p.audio!.sourceRate)
        p.setLoopRange(20.0...20.6)
        p.player.play(from: 20.0, loop: p.activeLoop)
        var samples: [Double] = []
        let end = Date().addingTimeInterval(1.5)
        while Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.1)); samples.append(p.player.currentTime) }
        p.player.pause()
        print(String(format: "loop 20.0-20.6, positions over 1.5 s: min %.2f max %.2f (wrapped: %@)",
                     samples.min()!, samples.max()!, samples.contains { $0 < samples.max()! - 0.3 } ? "yes" : "no"))
    }

    /// --incremental in.wav : full render, edit two regions, update only those, compare buffers.
    @MainActor static func incremental(_ path: String) {
        let p = Project(preload: false)
        let model = try! SidonModel()
        try! p.loadSync(URL(fileURLWithPath: path), enhanceWith: model)
        p.injectModel(model)
        let before = p.enhanced!
        guard p.regions.count >= 3 else { print("need >= 3 regions"); return }
        let moved = p.regions[1], deleted = p.regions[2]
        p.beginEdit(); p.moveEdge(moved.id, isStart: false, to: moved.end - 0.3)
        p.removeRegion(deleted.id)
        print("stale:", p.staleRegions.count, "orphans:", p.orphanSpans.count, "button stale flag:", p.enhancedStale)
        let t0 = Date()
        p.enhance()
        while p.processing { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
        print(String(format: "update took %.1fs (full render of %d regions took longer)", Date().timeIntervalSince(t0), p.regions.count))
        print("after: stale", p.staleRegions.count, "orphans", p.orphanSpans.count, "flag", p.enhancedStale)
        let after = p.enhanced!
        func rms(_ x: [Float], _ a: Double, _ b: Double) -> Float {
            let s = x[Int(a * 48_000)..<Int(b * 48_000)]; return sqrt(s.reduce(0) { $0 + $1 * $1 } / Float(max(1, s.count)))
        }
        print(String(format: "deleted region %.1f-%.1f: rms before %.4f, after %.6f", deleted.start, deleted.end, rms(before, deleted.start, deleted.end), rms(after, deleted.start, deleted.end)))
        print(String(format: "trimmed tail %.2f-%.2f: after %.6f", moved.end - 0.3, moved.end, rms(after, moved.end - 0.25, moved.end)))
        let r0 = p.regions[0]
        let same = zip(before[Int(r0.start * 48_000)..<Int(r0.end * 48_000)], after[Int(r0.start * 48_000)..<Int(r0.end * 48_000)]).allSatisfy { $0 == $1 }
        print("untouched region 1 bit-identical:", same)
    }

    static func readF32(_ url: URL) throws -> [Float] {
        let d = try Data(contentsOf: url)
        return d.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
    }

    static func writeF32(_ x: [Float], _ url: URL) throws {
        try x.withUnsafeBufferPointer { try Data(buffer: $0).write(to: url) }
    }
}
