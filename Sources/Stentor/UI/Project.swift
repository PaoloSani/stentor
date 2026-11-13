import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

enum ViewMode: String, CaseIterable { case waveform = "Wave", spectrogram = "Spectrum" }
enum Source: String { case original = "A", enhanced = "B" }
enum ExportRate: String { case model, source }
enum ExportFormat: String { case pcm16, pcm24, float32 }
enum ExportScope: String { case wholeFile, regions }

@MainActor
final class Project: ObservableObject {
    // file
    @Published var audio: LoadedAudio?
    @Published var loading = false

    // regions (what gets processed)
    @Published var regions: [Region] = [] { didSet { if regions != oldValue { updateStale() } } }
    @Published var selected: UUID?
    @Published var detection = DetectionSettings()
    private var undoStack: [[Region]] = []
    private var redoStack: [[Region]] = []

    // view
    @Published var viewMode: ViewMode = .waveform
    @Published var source: Source = .original
    @Published var visibleStart: Double = 0 { didSet { if visibleStart != oldValue { requestSpectrogram() } } }
    @Published var visibleDuration: Double = 1 { didSet { if visibleDuration != oldValue { requestSpectrogram() } } }
    @Published var loopRange: ClosedRange<Double>?
    @Published var loopEnabled = false

    // processing
    @Published var enhanced: [Float]?
    @Published var enhancedStale = false
    @Published var processing = false
    @Published var progress: Double = 0
    /// Last status message; also shown briefly as a toast above the control island.
    @Published var status = "" { didSet { if !status.isEmpty { flash(status) } } }
    @Published var toast: String?
    private var toastToken = 0

    // export options (persisted)
    @Published var exportRate: ExportRate = ExportRate(rawValue: UserDefaults.standard.string(forKey: "exportRate") ?? "") ?? .model {
        didSet { UserDefaults.standard.set(exportRate.rawValue, forKey: "exportRate") }
    }
    @Published var exportScope: ExportScope = ExportScope(rawValue: UserDefaults.standard.string(forKey: "exportScope") ?? "") ?? .wholeFile {
        didSet { UserDefaults.standard.set(exportScope.rawValue, forKey: "exportScope") }
    }
    @Published var exportFormat: ExportFormat = ExportFormat(rawValue: UserDefaults.standard.string(forKey: "exportFormat") ?? "") ?? .pcm24 {
        didSet { UserDefaults.standard.set(exportFormat.rawValue, forKey: "exportFormat") }
    }
    @Published var modelStatus = "Model not loaded"
    @Published var errorMessage: String?

    // derived visuals
    private(set) var originalPeaks: PeakData?
    private(set) var enhancedPeaks: PeakData?
    @Published private(set) var specTile: SpecTile?
    /// Editor width in points, reported by the view (spectrogram resolution).
    var editorWidth: Double = 1000 { didSet { if abs(editorWidth - oldValue) > 1 { requestSpectrogram() } } }
    private var specToken = 0

    let player = Player()
    private var model: SidonModel?
    private var modelTask: Task<SidonModel, Error>?
    private var cancelFlag = CancelFlag()

    var duration: Double { audio?.duration ?? 0 }
    var fileName: String { audio?.url.lastPathComponent ?? "Stentor" }
    var speechSeconds: Double { regions.reduce(0) { $0 + $1.length } }

    @Published var precision: String = UserDefaults.standard.string(forKey: "precision") ?? "float32"

    init(preload: Bool = true) {
        installer.onInstalled = { [weak self] in self?.modelsInstalled() }
        if preload { preloadModel() }
    }

    /// Switch float32 / float16 Core ML models (reloads them in the background).
    func setPrecision(_ p: String) {
        guard p != precision, !processing else { return }
        precision = p
        UserDefaults.standard.set(p, forKey: "precision")
        model = nil
        preloadModel()
    }

    /// Tests: use an already loaded model.
    func injectModel(_ m: SidonModel) { model = m }

    /// Synchronous load used by the headless snapshot test.
    func loadSync(_ url: URL, enhanceWith model: SidonModel? = nil) throws {
        let a = try AudioIO.load(url)
        audio = a
        originalPeaks = PeakData(samples: a.listen, rate: a.sourceRate)
        regions = VoiceDetector.detect(a.wav16k, settings: detection)
        visibleStart = 0; visibleDuration = a.duration
        loopRange = regions.first.map { $0.start...$0.end }
        if let model {
            let out = try Renderer(model: model).render(a, regions: regions, progress: { _ in }, isCancelled: { false })!
            enhanced = out; enhancedPeaks = PeakData(samples: out, rate: 48_000)
            rendered = Dictionary(uniqueKeysWithValues: regions.map { ($0.id, $0) })
            enhancedStale = false
        }
        status = "\(regions.count) speech region\(regions.count == 1 ? "" : "s") detected"
    }

    // MARK: - file

    func openPanel() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audio]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { open(url) }
    }

    // MARK: demo

    static let demoName = "JFK - Rice University 1962 (excerpt)"

    /// The bundled public-domain demo (Resources/Demo), also found next to a development build.
    static var demoURL: URL? {
        if let u = Bundle.main.url(forResource: demoName, withExtension: "m4a", subdirectory: "Demo") { return u }
        var p = Bundle.main.bundleURL
        for _ in 0..<4 {
            p = p.deletingLastPathComponent()
            let u = p.appendingPathComponent("Resources/Demo/\(demoName).m4a")
            if FileManager.default.fileExists(atPath: u.path) { return u }
        }
        return nil
    }

    func openDemo() { if let u = Project.demoURL { open(u) } }

    /// First launch: open the demo so there is something to try right away.
    func openDemoOnFirstLaunch() {
        guard audio == nil, !UserDefaults.standard.bool(forKey: "demoShown"), Project.demoURL != nil else { return }
        UserDefaults.standard.set(true, forKey: "demoShown")
        openDemo()
        status = "Demo: JFK at Rice University, 1962 — a distant, reverberant recording. Press Enhance."
    }

    func open(_ url: URL) {
        player.pause()
        loading = true
        status = "Loading \(url.lastPathComponent)…"
        let settings = detection
        Task.detached(priority: .userInitiated) {
            do {
                let audio = try AudioIO.load(url)
                let regions = VoiceDetector.detect(audio.wav16k, settings: settings)
                let peaks = PeakData(samples: audio.listen, rate: audio.sourceRate)
                await MainActor.run {
                    self.audio = audio
                    self.originalPeaks = peaks
                    self.enhanced = nil; self.enhancedPeaks = nil
                    self.specTile = nil
                    self.regions = regions
                    self.enhancedStale = false
                    self.rendered = [:]
                    self.undoStack = []; self.redoStack = []
                    self.selected = nil
                    self.loopRange = regions.first.map { $0.start...$0.end }; self.loopEnabled = false
                    self.source = .original
                    self.visibleStart = 0; self.visibleDuration = audio.duration
                    self.player.setSignal(audio.listen, rate: audio.sourceRate)
                    self.player.transport.time = 0
                    self.loading = false
                    self.status = "\(regions.count) speech region\(regions.count == 1 ? "" : "s") detected"
                    self.requestSpectrogram()
                }
            } catch {
                await MainActor.run { self.loading = false; self.status = ""; self.errorMessage = error.localizedDescription }
            }
        }
    }

    // MARK: - regions

    private func checkpoint() {
        undoStack.append(regions)
        if undoStack.count > 200 { undoStack.removeFirst() }
        redoStack.removeAll()
    }

    func beginEdit() { checkpoint() }

    func undo() {
        guard let prev = undoStack.popLast() else { return }
        redoStack.append(regions); regions = prev
    }

    func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(regions); regions = next
    }

    func detect() {
        guard let audio else { return }
        checkpoint()
        regions = VoiceDetector.detect(audio.wav16k, settings: detection)
        selected = nil
        if !loopEnabled { loopRange = regions.first.map { $0.start...$0.end } }
        status = "\(regions.count) speech region\(regions.count == 1 ? "" : "s") detected"
    }

    /// Click on an empty area: a region from `t` up to just before the next region (or the end).
    func insertRegion(at t: Double) {
        let next = regions.first { $0.start > t }?.start ?? duration
        let end = next < duration ? next - 0.05 : duration
        guard end - t >= 0.05 else { return }
        checkpoint()
        let r = Region(start: t, end: end)
        regions = VoiceDetector.normalised(regions + [r], duration: duration)
        selected = regions.first { $0.contains(t + 0.01) }?.id
    }

    func addRegion(_ a: Double, _ b: Double) {
        guard abs(b - a) >= 0.05 else { return }
        checkpoint()
        regions = VoiceDetector.normalised(regions + [Region(start: min(a, b), end: max(a, b))], duration: duration)
        selected = regions.first { $0.contains((a + b) / 2) }?.id
    }

    func removeRegion(_ id: UUID) {
        checkpoint()
        regions.removeAll { $0.id == id }
        if selected == id { selected = nil }
    }

    /// Move one edge, constrained between the neighbours (no checkpoint: call beginEdit first).
    func moveEdge(_ id: UUID, isStart: Bool, to t: Double) {
        guard let i = regions.firstIndex(where: { $0.id == id }) else { return }
        var r = regions[i]
        if isStart {
            let lo = i > 0 ? regions[i - 1].end + 0.02 : 0
            r.start = min(max(t, lo), r.end - 0.05)
        } else {
            let hi = i + 1 < regions.count ? regions[i + 1].start - 0.02 : duration
            r.end = max(min(t, hi), r.start + 0.05)
        }
        regions[i] = r
    }

    func clearRegions() { checkpoint(); regions = []; selected = nil }

    // MARK: - view

    func zoom(by factor: Double, around t: Double) {
        guard duration > 0 else { return }
        let newDur = min(duration, max(0.05, visibleDuration / factor))
        let frac = (t - visibleStart) / visibleDuration
        visibleDuration = newDur
        visibleStart = clampStart(t - frac * newDur)
    }

    func zoomToFit() { visibleStart = 0; visibleDuration = max(duration, 0.05) }

    func scroll(bySeconds d: Double) { visibleStart = clampStart(visibleStart + d) }

    func clampStart(_ s: Double) -> Double { min(max(0, s), max(0, duration - visibleDuration)) }

    func setViewMode(_ m: ViewMode) {
        viewMode = m
        requestSpectrogram()
    }

    /// Recompute the spectrogram for exactly the visible window (debounced, off the main thread).
    /// The previous tile stays on screen meanwhile, drawn at its own times, so it never misaligns.
    func requestSpectrogram(sync: Bool = false) {
        guard viewMode == .spectrogram, let audio else { return }
        let (samples, rate): ([Float], Double) = source == .enhanced && enhanced != nil ? (enhanced!, 48_000) : (audio.listen, audio.sourceRate)
        let src = source == .enhanced && enhanced != nil ? Source.enhanced : Source.original
        // Retina resolution, plus half a screen of margin on each side so panning and autoscroll
        // during playback never reveal empty or stretched areas while the next tile renders.
        let margin = visibleDuration * 0.5
        let t0 = max(0, visibleStart - margin), t1 = min(duration, visibleStart + visibleDuration + margin)
        let scale = Double(NSScreen.main?.backingScaleFactor ?? 2)
        let cols = max(64, min(8192, Int(editorWidth * scale * (t1 - t0) / max(visibleDuration, 1e-6))))
        if sync {
            if let img = SpectrogramRenderer.render(samples: samples, rate: rate, t0: t0, t1: t1, columns: cols) {
                specTile = SpecTile(image: img, t0: t0, t1: t1, source: src)
            }
            return
        }
        specToken += 1
        let token = specToken
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) { [weak self] in
            guard let self, self.specToken == token else { return }
            Task.detached(priority: .userInitiated) {
                let img = SpectrogramRenderer.render(samples: samples, rate: rate, t0: t0, t1: t1, columns: cols)
                await MainActor.run {
                    if let img, self.specToken == token { self.specTile = SpecTile(image: img, t0: t0, t1: t1, source: src) }
                }
            }
        }
    }

    // MARK: - transport

    func togglePlay() {
        if player.transport.isPlaying { player.pause() } else { player.play(from: player.transport.time, loop: activeLoop) }
    }

    func seek(_ t: Double) { player.seek(min(max(0, t), duration)) }

    func goToStart() { seek(loopEnabled ? loopRange?.lowerBound ?? 0 : 0) }

    func flash(_ msg: String) {
        toast = msg
        toastToken += 1
        let token = toastToken
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) { [weak self] in
            if self?.toastToken == token { self?.toast = nil }
        }
    }

    var activeLoop: ClosedRange<Double>? { loopEnabled ? loopRange : nil }

    func setLoopRange(_ r: ClosedRange<Double>?) {
        loopRange = r
        loopEnabled = r != nil
        player.setLoop(activeLoop)
    }

    /// L: toggle looping. The range defaults to the first speech region (or the selected one);
    /// dragging on the ruler sets any other range.
    func toggleLoop() {
        if !loopEnabled && loopRange == nil {
            if let id = selected, let r = regions.first(where: { $0.id == id }) { loopRange = r.start...r.end }
            else if let r = regions.first { loopRange = r.start...r.end }
            else { loopRange = visibleStart...(visibleStart + visibleDuration) }
        }
        if !loopEnabled, let l = loopRange, !(l.contains(player.transport.time)) { player.seek(l.lowerBound) }
        loopEnabled.toggle()
        player.setLoop(activeLoop)
    }

    func setSource(_ s: Source) {
        guard s != source, let audio else { return }
        if s == .enhanced {
            guard let e = enhanced else { return }
            player.setSignal(e, rate: 48_000)
        } else {
            player.setSignal(audio.listen, rate: audio.sourceRate)
        }
        source = s
        requestSpectrogram()
    }

    func toggleSource() { setSource(source == .original ? .enhanced : .original) }

    // MARK: - model & processing

    // MARK: voice model installation (first launch)

    /// True when the Core ML models are not on this Mac yet: the setup card offers to download them.
    @Published var needsModels = false
    let installer = ModelInstaller()

    func modelsInstalled() {
        needsModels = false
        status = "Voice model installed"
        preloadModel()
    }

    /// Point Stentor at a folder that already contains the .mlpackage files.
    func locateModelsFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.message = "Choose the folder containing feature_extractor_float32.mlpackage and decoder_float32.mlpackage"
        guard panel.runModal() == .OK, let dir = panel.url else { return }
        let ok = ["feature_extractor", "decoder"].allSatisfy {
            FileManager.default.fileExists(atPath: dir.appendingPathComponent("\($0)_\(precision).mlpackage").path)
        }
        guard ok else { errorMessage = "That folder doesn't contain the Stentor Core ML models."; return }
        UserDefaults.standard.set(dir.path, forKey: "modelsFolder")
        modelsInstalled()
    }

    private func preloadModel() {
        guard SidonModel.locate(precision: precision) != nil else {
            needsModels = true
            modelTask = nil
            modelStatus = "Voice model not installed"
            return
        }
        modelStatus = "Loading model…"
        let precision = self.precision
        let task = Task.detached(priority: .utility) { () throws -> SidonModel in
            try SidonModel(precision: precision) { msg in Task { @MainActor in self.modelStatus = msg } }
        }
        modelTask = task
        Task {
            do { model = try await task.value; modelStatus = "Core ML · GPU · \(model!.precision)" }
            catch { modelStatus = "Model unavailable"; errorMessage = error.localizedDescription }
        }
    }

    // MARK: incremental rendering

    /// Each region as it was when last rendered into `enhanced`.
    private var rendered: [UUID: Region] = [:]

    /// Regions whose current span has not been rendered yet (all of them before the first run).
    var staleRegions: [Region] { enhanced == nil ? regions : regions.filter { rendered[$0.id] != $0 } }
    /// Rendered spans that no longer correspond to a region (deleted, moved or merged): to be silenced.
    var orphanSpans: [Region] { rendered.values.filter { r in !regions.contains(r) } }
    func isStale(_ r: Region) -> Bool { enhanced != nil && rendered[r.id] != r }

    private func updateStale() { enhancedStale = enhanced != nil && (!staleRegions.isEmpty || !orphanSpans.isEmpty) }

    /// Enhance: the whole file the first time, afterwards only what changed since the last run.
    func enhance() {
        guard enhanced == nil || enhancedStale else { return enhanceAll() }
        if enhanced == nil { return enhanceAll() }
        run(targets: staleRegions, clear: orphanSpans, label: "\(staleRegions.count) changed region\(staleRegions.count == 1 ? "" : "s")")
    }

    /// Re-render every region from scratch.
    func enhanceAll() {
        guard !regions.isEmpty else { return }
        run(targets: regions, clear: [], label: String(format: "%.1f s of speech", speechSeconds), fresh: true)
    }

    /// Regenerate a single region (its previous span, if it moved, is silenced first).
    func enhanceRegion(_ id: UUID) {
        guard let r = regions.first(where: { $0.id == id }) else { return }
        let old = rendered[id].map { $0 == r ? [] : [$0] } ?? []
        run(targets: [r], clear: old, label: "region \((regions.firstIndex(of: r) ?? 0) + 1)")
    }

    private func run(targets: [Region], clear: [Region], label: String, fresh: Bool = false) {
        guard let audio, !processing else { return }
        guard !targets.isEmpty || !clear.isEmpty else { return }
        processing = true
        progress = 0
        status = "Enhancing \(label)…"
        let flag = CancelFlag()
        cancelFlag = flag
        let started = Date()
        let base = fresh ? nil : enhanced
        let all = regions
        Task {
            do {
                let model: SidonModel
                if let m = self.model { model = m } else {
                    status = "Waiting for the model…"
                    guard let t = modelTask else { processing = false; status = ""; needsModels = true; return }
                    model = try await t.value
                }
                let out = try await Task.detached(priority: .userInitiated) { () throws -> [Float]? in
                    var buf = base ?? [Float](repeating: 0, count: audio.wav16k.count * SidonModel.upsample)
                    let ok = try Renderer(model: model).renderRegions(audio, regions: targets, clear: clear, into: &buf, progress: { p in
                        Task { @MainActor in self.progress = p }
                    }, isCancelled: { flag.cancelled })
                    return ok ? buf : nil
                }.value
                processing = false
                guard let out else { status = "Cancelled"; return }
                if fresh { rendered = [:] }
                for c in clear where rendered[c.id] == c { rendered[c.id] = nil } // silenced spans
                for t in targets { rendered[t.id] = t }
                _ = all
                enhanced = out
                enhancedPeaks = PeakData(samples: out, rate: 48_000)
                updateStale()
                requestSpectrogram()
                status = String(format: "Enhanced %@ in %.1f s", label, Date().timeIntervalSince(started))
                if source == .enhanced { player.setSignal(out, rate: 48_000) } else { setSource(.enhanced) }
            } catch {
                processing = false
                status = ""
                errorMessage = error.localizedDescription
            }
        }
    }

    func cancel() { cancelFlag.cancelled = true }

    /// Export according to Settings › Export (whole file by default).
    func export() { exportScope == .regions ? exportRegions() : exportWholeFile() }

    /// The enhanced signal at the chosen export rate (48 kHz, or resampled to the source rate).
    private func exportSignal(_ enhanced: [Float], _ audio: LoadedAudio) throws -> (samples: [Float], rate: Double) {
        guard exportRate == .source, audio.sourceRate != 48_000 else { return (enhanced, 48_000) }
        let rate = audio.sourceRate
        var samples = try AudioIO.resample(enhanced, from: 48_000, to: rate)
        let n = Int((Double(audio.wav16k.count) / 16_000 * rate).rounded()) // exact original length
        samples = Array(samples.prefix(n)) + [Float](repeating: 0, count: max(0, n - samples.count))
        return (samples, rate)
    }

    func exportWholeFile() {
        guard let enhanced, let audio else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.wav]
        panel.nameFieldStringValue = audio.url.deletingPathExtension().lastPathComponent + "_enhanced.wav"
        panel.directoryURL = audio.url.deletingLastPathComponent()
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let (samples, rate) = try exportSignal(enhanced, audio)
            try AudioIO.writeWav(samples, sampleRate: rate, format: exportFormat, to: url)
            status = "Exported \(url.lastPathComponent)"
        } catch { errorMessage = error.localizedDescription }
    }

    /// One WAV per green region, numbered and named after its start time, plus a CSV of the times
    /// so the clips can be placed back on a DAW timeline.
    func exportRegions() {
        guard let enhanced, let audio, !regions.isEmpty else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Export Here"
        panel.message = "Choose a folder for the \(regions.count) speech region\(regions.count == 1 ? "" : "s")"
        panel.directoryURL = audio.url.deletingLastPathComponent()
        guard panel.runModal() == .OK, let dir = panel.url else { return }
        do {
            let n = try writeRegionFiles(to: dir)
            status = "Exported \(n) region\(n == 1 ? "" : "s") to \(dir.lastPathComponent)"
        } catch { errorMessage = error.localizedDescription }
    }

    @discardableResult
    func writeRegionFiles(to dir: URL) throws -> Int {
        guard let enhanced, let audio else { return 0 }
        do {
            let (samples, rate) = try exportSignal(enhanced, audio)
            let stem = audio.url.deletingPathExtension().lastPathComponent
            var csv = "file,index,start_s,end_s,duration_s\n"
            for (k, r) in regions.enumerated() {
                let a = max(0, Int((r.start * rate).rounded())), b = min(samples.count, Int((r.end * rate).rounded()))
                guard b > a else { continue }
                let m = Int(r.start) / 60, sec = r.start - Double(m * 60)
                let name = String(format: "%@_enhanced_%02d_%dm%05.2fs.wav", stem, k + 1, m, sec)
                try AudioIO.writeWav(Array(samples[a..<b]), sampleRate: rate, format: exportFormat, to: dir.appendingPathComponent(name))
                csv += String(format: "\"%@\",%d,%.3f,%.3f,%.3f\n", name, k + 1, r.start, r.end, r.length)
            }
            try csv.write(to: dir.appendingPathComponent("\(stem)_regions.csv"), atomically: true, encoding: .utf8)
            return regions.count
        }
    }

    // MARK: - display helpers

    var displayPeaks: PeakData? { source == .enhanced ? enhancedPeaks : originalPeaks }
    var displaySpectrogram: SpecTile? { specTile.flatMap { $0.source == source ? $0 : nil } }
}

final class CancelFlag: @unchecked Sendable { var cancelled = false }
