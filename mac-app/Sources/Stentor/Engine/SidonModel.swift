import Accelerate
import CoreML
import Foundation

enum ModelError: LocalizedError {
    case notFound(String)
    case badOutput(String)
    var errorDescription: String? {
        switch self {
        case .notFound(let s): return "Sidon Core ML models not found. \(s)"
        case .badOutput(let s): return "Unexpected model output: \(s)"
        }
    }
}

/// Core ML port of speech_enhancer/model.py (Core ML backend, GPU).
final class SidonModel {
    static let inRate = 16_000
    static let outRate = 48_000
    static let upsample = 3
    static let hop = 960 // 48 kHz samples per 50 Hz frame
    static let edgePad = 4_000 // 0.25 s of zeros on each side of every call
    static let feMaxFrames = 1_500
    static let decWindow = 100
    static let decContext = 16

    let precision: String
    private let fe: MLModel
    private let dec: MLModel
    private let fbank = Fbank()
    private let feURL: URL
    private let decURL: URL
    /// CPU copies, created only if the GPU ever returns a broken result (e.g. out of GPU memory).
    private var cpuModels: (MLModel, MLModel)?
    private(set) var cpuFallbacks = 0

    /// Folders searched for feature_extractor_<precision>.mlpackage / decoder_<precision>.mlpackage.
    static func searchFolders() -> [URL] {
        var dirs: [URL] = []
        if let env = ProcessInfo.processInfo.environment["SIDON_MODELS_DIR"] { dirs.append(URL(fileURLWithPath: env)) }
        if let custom = UserDefaults.standard.string(forKey: "modelsFolder") { dirs.append(URL(fileURLWithPath: custom)) }
        if let res = Bundle.main.resourceURL { dirs.append(res.appendingPathComponent("Models")) }
        dirs.append(appSupport.appendingPathComponent("Models"))
        // development: <repo>/sidon_weights/coreml next to the built app or the executable
        var p = Bundle.main.bundleURL
        for _ in 0..<5 {
            p = p.deletingLastPathComponent()
            dirs.append(p.appendingPathComponent("sidon_weights/coreml"))
        }
        return dirs
    }

    static var appSupport: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Stentor")
    }

    static func locate(precision: String) -> URL? {
        searchFolders().first { dir in
            ["feature_extractor", "decoder"].allSatisfy {
                FileManager.default.fileExists(atPath: dir.appendingPathComponent("\($0)_\(precision).mlpackage").path)
            }
        }
    }

    init(precision: String = "float32", status: ((String) -> Void)? = nil) throws {
        self.precision = precision
        guard let dir = SidonModel.locate(precision: precision) else {
            throw ModelError.notFound("Export them with tools/export_coreml.py, then put the .mlpackage files in "
                + SidonModel.appSupport.appendingPathComponent("Models").path)
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuAndGPU // the Neural Engine's fp16 degrades the vocoder
        status?("Preparing feature extractor…")
        feURL = try SidonModel.compiled(dir.appendingPathComponent("feature_extractor_\(precision).mlpackage"))
        fe = try MLModel(contentsOf: feURL, configuration: config)
        status?("Preparing vocoder…")
        decURL = try SidonModel.compiled(dir.appendingPathComponent("decoder_\(precision).mlpackage"))
        dec = try MLModel(contentsOf: decURL, configuration: config)
    }

    /// Compile an .mlpackage once and cache the .mlmodelc in Application Support.
    private static func compiled(_ pkg: URL) throws -> URL {
        let cacheDir = appSupport.appendingPathComponent("Compiled")
        try FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
        let attrs = try? FileManager.default.attributesOfItem(atPath: pkg.appendingPathComponent("Manifest.json").path)
        let stamp = Int((attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0)
        let dest = cacheDir.appendingPathComponent("\(pkg.deletingPathExtension().lastPathComponent)-\(stamp).mlmodelc")
        if FileManager.default.fileExists(atPath: dest.path) { return dest }
        let tmp = try MLModel.compileModel(at: pkg)
        try? FileManager.default.removeItem(at: dest)
        try FileManager.default.moveItem(at: tmp, to: dest)
        return dest
    }

    /// 16 kHz mono -> 48 kHz restored speech of exactly 3 * count samples.
    /// Falls back to the CPU if the GPU result is broken (NaN, or silent while the input is not).
    func enhance(_ wav16k: [Float]) throws -> [Float] {
        let y = try autoreleasepool { try enhance(wav16k, fe: fe, dec: dec) }
        if SidonModel.looksBroken(input: wav16k, output: y) {
            if cpuModels == nil {
                let cfg = MLModelConfiguration()
                cfg.computeUnits = .cpuOnly
                cpuModels = (try MLModel(contentsOf: feURL, configuration: cfg), try MLModel(contentsOf: decURL, configuration: cfg))
            }
            cpuFallbacks += 1
            return try autoreleasepool { try enhance(wav16k, fe: cpuModels!.0, dec: cpuModels!.1) }
        }
        return y
    }

    static func looksBroken(input: [Float], output: [Float]) -> Bool {
        if output.contains(where: { !$0.isFinite }) { return true }
        let inRMS = sqrt(vDSP.meanSquare(input)), outRMS = sqrt(vDSP.meanSquare(output))
        return inRMS > 0.01 && outRMS < inRMS * 0.02
    }

    private func enhance(_ wav16k: [Float], fe: MLModel, dec: MLModel) throws -> [Float] {
        let n = wav16k.count
        var padded = [Float](repeating: 0, count: n + 2 * SidonModel.edgePad)
        padded.replaceSubrange(SidonModel.edgePad..<(SidonModel.edgePad + n), with: wav16k)
        let (t, feats) = fbank.features(padded)
        guard t > 0 else { return [Float](repeating: 0, count: n * SidonModel.upsample) }
        guard t <= SidonModel.feMaxFrames else { throw ModelError.badOutput("segment too long (\(t) frames)") }

        // feature extractor: (1, T, 160) -> (1, T, 1024)
        let input = try MLMultiArray(shape: [1, NSNumber(value: t), 160], dataType: .float32)
        feats.withUnsafeBufferPointer { src in
            input.dataPointer.assumingMemoryBound(to: Float.self).update(from: src.baseAddress!, count: feats.count)
        }
        let feOut = try fe.prediction(from: MLDictionaryFeatureProvider(dictionary: ["features": input]))
        guard let hidden = feOut.featureValue(for: "hidden")?.multiArrayValue else { throw ModelError.badOutput("hidden") }
        let h = SidonModel.floats(hidden) // row-major (T, 1024) with strides
        let hStride0 = hidden.strides[1].intValue, hStride1 = hidden.strides[2].intValue

        // vocoder over overlapping fixed windows of (1, 1024, 132)
        let win = SidonModel.decWindow, ctx = SidonModel.decContext, frames = win + 2 * ctx, hop = SidonModel.hop
        let decIn = try MLMultiArray(shape: [1, 1024, NSNumber(value: frames)], dataType: .float32)
        let dIn = decIn.dataPointer.assumingMemoryBound(to: Float.self)
        let dS0 = decIn.strides[1].intValue, dS1 = decIn.strides[2].intValue
        let padded48 = ((t + win - 1) / win) * win
        var out = [Float](repeating: 0, count: padded48 * hop)
        var s = 0
        while s < t {
            // window covers hidden frames [s - ctx, s + win + ctx), zero outside [0, T)
            for j in 0..<frames {
                let src = s - ctx + j
                if src < 0 || src >= t {
                    for c in 0..<1024 { dIn[c * dS0 + j * dS1] = 0 }
                } else {
                    for c in 0..<1024 { dIn[c * dS0 + j * dS1] = h[src * hStride0 + c * hStride1] }
                }
            }
            let w: [Float] = try autoreleasepool {
                let decOut = try dec.prediction(from: MLDictionaryFeatureProvider(dictionary: ["hidden": decIn]))
                guard let wav = decOut.featureValue(for: "wav")?.multiArrayValue else { throw ModelError.badOutput("wav") }
                return SidonModel.floats(wav)
            }
            let base = ctx * hop
            out.withUnsafeMutableBufferPointer { op in
                for i in 0..<(win * hop) where base + i < w.count { op[s * hop + i] = w[base + i] }
            }
            s += win
        }

        let start = SidonModel.edgePad * SidonModel.upsample
        let target = n * SidonModel.upsample
        var result = [Float](repeating: 0, count: target)
        let avail = max(0, min(target, out.count - start))
        if avail > 0 { result.replaceSubrange(0..<avail, with: out[start..<(start + avail)]) }
        return result
    }

    /// Copy any float16/float32 MLMultiArray into a flat Float array (respecting its memory layout).
    static func floats(_ a: MLMultiArray) -> [Float] {
        let count = a.strides.first.map { $0.intValue * a.shape[0].intValue } ?? a.count
        switch a.dataType {
        case .float32:
            return Array(UnsafeBufferPointer(start: a.dataPointer.assumingMemoryBound(to: Float.self), count: count))
        case .float16:
            let p = a.dataPointer.assumingMemoryBound(to: Float16.self)
            return (0..<count).map { Float(p[$0]) }
        default:
            return (0..<a.count).map { a[$0].floatValue }
        }
    }
}
