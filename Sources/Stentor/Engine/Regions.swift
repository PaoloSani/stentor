import Accelerate
import Foundation

/// A span of the file that will be sent to the model (shown in green).
struct Region: Identifiable, Equatable, Codable {
    var id = UUID()
    var start: Double
    var end: Double
    var length: Double { end - start }
    func contains(_ t: Double) -> Bool { t >= start && t <= end }
}

struct DetectionSettings: Equatable {
    var thresholdDb: Double = -45 // relative to full scale of the peak-normalised signal
    var preRoll: Double = 0.15
    var postRoll: Double = 0.25
    var minSpeech: Double = 0.12
    var mergeGap: Double = 0.35
}

/// Energy-based voice activity detection with hysteresis. The input material is expected to
/// be voice only (no ambience), so speech vs. silence is mostly a level decision.
enum VoiceDetector {
    static func detect(_ wav16k: [Float], settings s: DetectionSettings = .init()) -> [Region] {
        let sr = 16_000.0, frame = 320, hop = 160
        guard wav16k.count > frame else { return [] }
        let nFrames = 1 + (wav16k.count - frame) / hop
        var db = [Float](repeating: -120, count: nFrames)
        wav16k.withUnsafeBufferPointer { p in
            for i in 0..<nFrames {
                var ms: Float = 0
                vDSP_measqv(p.baseAddress! + i * hop, 1, &ms, vDSP_Length(frame))
                db[i] = 10 * log10(ms + 1e-12)
            }
        }
        let on = Float(s.thresholdDb), off = Float(s.thresholdDb - 6)
        var raw: [(Double, Double)] = []
        var active = false
        var startT = 0.0
        for i in 0..<nFrames {
            let t = Double(i * hop) / sr
            if !active && db[i] >= on { active = true; startT = t }
            else if active && db[i] < off { active = false; raw.append((startT, t + Double(frame) / sr)) }
        }
        if active { raw.append((startT, Double(wav16k.count) / sr)) }

        let dur = Double(wav16k.count) / sr
        var merged: [(Double, Double)] = []
        for (a, b) in raw where b - a >= s.minSpeech {
            let lo = max(0, a - s.preRoll), hi = min(dur, b + s.postRoll)
            if let last = merged.last, lo - last.1 < s.mergeGap { merged[merged.count - 1].1 = max(last.1, hi) }
            else { merged.append((lo, hi)) }
        }
        return merged.map { Region(start: $0.0, end: $0.1) }
    }

    /// Sort, clamp and merge overlapping regions.
    static func normalised(_ regions: [Region], duration: Double) -> [Region] {
        var out: [Region] = []
        for r in regions.sorted(by: { $0.start < $1.start }) {
            var r = r
            r.start = max(0, min(r.start, duration)); r.end = max(0, min(r.end, duration))
            if r.end - r.start < 0.02 { continue }
            if let last = out.last, r.start <= last.end { out[out.count - 1].end = max(last.end, r.end) }
            else { out.append(r) }
        }
        return out
    }
}

/// Runs the model on the green regions only; everything else stays digital silence, and the
/// output has exactly the length of the input (at 48 kHz).
final class Renderer {
    static let maxChunk = 10.5 // seconds of region per model call
    static let context = 0.5 // extra audio on each side of a model call
    static let crossfade = 0.04 // between chunks of a long region
    static let gateFade = 0.02 // at region edges
    /// Every model call uses one of these exact input lengths (seconds). Core ML keeps a compiled
    /// GPU graph per input shape; arbitrary lengths exhaust GPU memory on long files and Core ML
    /// then silently returns near-silent output. Two fixed shapes keep memory flat.
    static let buckets = [4.0, 12.0]

    let model: SidonModel
    init(model: SidonModel) { self.model = model }

    struct Plan { let region: Region; let chunks: [(Int, Int)] } // 16 kHz sample ranges

    static func plan(_ regions: [Region], wav16k: [Float]) -> [Plan] {
        regions.map { r in
            let a = Int(r.start * 16_000), b = min(wav16k.count, Int(r.end * 16_000))
            return Plan(region: r, chunks: split(a, b, wav16k))
        }
    }

    /// Split [a, b) into chunks of at most maxChunk seconds, cutting at the quietest 20 ms.
    static func split(_ a: Int, _ b: Int, _ w: [Float]) -> [(Int, Int)] {
        let maxLen = Int(maxChunk * 16_000)
        var out: [(Int, Int)] = []
        var s = a
        while b - s > maxLen {
            let lo = s + maxLen / 2, hi = s + maxLen
            var best = hi, bestE = Float.infinity
            var i = lo
            while i + 320 <= hi {
                var e: Float = 0
                w.withUnsafeBufferPointer { vDSP_measqv($0.baseAddress! + i, 1, &e, 320) }
                if e < bestE { bestE = e; best = i + 160 }
                i += 160
            }
            out.append((s, best)); s = best
        }
        if b > s { out.append((s, b)) }
        return out
    }

    /// Model input window of a fixed bucket length around [a, b) (real audio as context),
    /// zero-padded only when the file itself is shorter than the bucket.
    static func window(_ a: Int, _ b: Int, n: Int) -> (lo: Int, hi: Int, length: Int) {
        let ctx = Int(context * 16_000)
        let need = b - a + 2 * ctx
        let len = Int((buckets.first { Double(need) <= $0 * 16_000 } ?? buckets.last!) * 16_000)
        var lo = a - ctx - max(0, len - need) / 2
        lo = max(0, min(lo, n - len))
        return (lo, min(n, lo + len), max(len, need))
    }

    /// Full-length output: silence everywhere except the rendered regions.
    func render(_ audio: LoadedAudio, regions: [Region],
                progress: (Double) -> Void, isCancelled: () -> Bool) throws -> [Float]? {
        var out = [Float](repeating: 0, count: audio.wav16k.count * SidonModel.upsample)
        return try renderRegions(audio, regions: regions, into: &out, progress: progress, isCancelled: isCancelled) ? out : nil
    }

    /// Clear `clear` spans (e.g. regions that were deleted or moved), then (re)render `regions` in place.
    /// Each region is independent, so a single region can be regenerated without touching the rest.
    func renderRegions(_ audio: LoadedAudio, regions: [Region], clear: [Region] = [], into out: inout [Float],
                       progress: (Double) -> Void, isCancelled: () -> Bool) throws -> Bool {
        let w = audio.wav16k, n = w.count, up = SidonModel.upsample
        for r in clear + regions { zero(&out, r) }
        let plans = Renderer.plan(regions, wav16k: w)
        let total = max(1, plans.reduce(0) { $0 + $1.chunks.reduce(0) { $0 + ($1.1 - $1.0) } })
        var done = 0
        let half = Int(Renderer.crossfade * 16_000 / 2)

        for p in plans {
            for (k, (cs, ce)) in p.chunks.enumerated() {
                if isCancelled() { return false }
                let first = k == 0, last = k == p.chunks.count - 1
                let a = first ? cs : cs - half          // overlap neighbours by half a crossfade
                let b = last ? ce : ce + half
                let win = Renderer.window(a, b, n: n)
                var input = Array(w[win.lo..<win.hi])
                if input.count < win.length { input += [Float](repeating: 0, count: win.length - input.count) }
                let y = try model.enhance(input)
                let off = (a - win.lo) * up
                let len = (b - a) * up
                let rampLen = 2 * half * up
                out.withUnsafeMutableBufferPointer { op in
                    for i in 0..<len {
                        var g: Float = 1
                        if !first && i < rampLen { g = hann(i, rampLen) }                    // fade in
                        if !last && i >= len - rampLen { g = 1 - hann(i - (len - rampLen), rampLen) } // fade out
                        op[a * up + i] += g * y[off + i]
                    }
                }
                done += ce - cs
                progress(Double(done) / Double(total))
            }
            applyGate(&out, region: p.region, count: n * up)
        }
        return true
    }

    private func zero(_ out: inout [Float], _ r: Region) {
        let a = max(0, Int(r.start * 48_000)), b = min(out.count, Int(r.end * 48_000) + 1)
        if b > a { out.withUnsafeMutableBufferPointer { op in for i in a..<b { op[i] = 0 } } }
    }

    /// Short Hann fades at the region edges so the gate never clicks.
    private func applyGate(_ out: inout [Float], region r: Region, count: Int) {
        let a = Int(r.start * 48_000), b = min(count, Int(r.end * 48_000))
        let f = min(Int(Renderer.gateFade * 48_000), (b - a) / 2)
        guard f > 0 else { return }
        for i in 0..<f {
            let g = hann(i, f)
            out[a + i] *= g
            out[b - 1 - i] *= g
        }
    }
}

@inline(__always) func hann(_ i: Int, _ n: Int) -> Float {
    0.5 - 0.5 * cos(Float.pi * (Float(i) + 0.5) / Float(n))
}
