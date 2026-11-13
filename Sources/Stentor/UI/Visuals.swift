import Accelerate
import CoreGraphics
import Foundation

/// Min/max envelope at a coarse block size, for fast waveform drawing at any zoom level.
final class PeakData {
    static let block = 256
    let samples: [Float]
    let rate: Double
    private let mins: [Float]
    private let maxs: [Float]

    init(samples: [Float], rate: Double) {
        self.samples = samples
        self.rate = rate
        let nb = (samples.count + PeakData.block - 1) / PeakData.block
        var mn = [Float](repeating: 0, count: nb), mx = [Float](repeating: 0, count: nb)
        samples.withUnsafeBufferPointer { p in
            for b in 0..<nb {
                let s = b * PeakData.block, n = min(PeakData.block, samples.count - s)
                mn[b] = vDSP.minimum(UnsafeBufferPointer(rebasing: p[s..<(s + n)]))
                mx[b] = vDSP.maximum(UnsafeBufferPointer(rebasing: p[s..<(s + n)]))
            }
        }
        mins = mn; maxs = mx
    }

    var duration: Double { Double(samples.count) / rate }

    /// (min, max) per pixel column for the time range [t0, t1].
    func columns(t0: Double, t1: Double, width: Int) -> [(Float, Float)] {
        guard width > 0, t1 > t0 else { return [] }
        let spp = (t1 - t0) * rate / Double(width) // samples per pixel
        var out = [(Float, Float)](repeating: (0, 0), count: width)
        for x in 0..<width {
            let a = Int((t0 * rate + Double(x) * spp).rounded(.down))
            let b = Int((t0 * rate + Double(x + 1) * spp).rounded(.up))
            let lo = max(0, a), hi = min(samples.count, max(b, a + 1))
            guard hi > lo else { continue }
            if hi - lo < PeakData.block * 2 {
                var mn = Float.infinity, mx = -Float.infinity
                for i in lo..<hi { mn = min(mn, samples[i]); mx = max(mx, samples[i]) }
                out[x] = (mn, mx)
            } else {
                let bl = lo / PeakData.block, bh = min(mins.count, (hi + PeakData.block - 1) / PeakData.block)
                var mn = Float.infinity, mx = -Float.infinity
                for i in bl..<bh { mn = min(mn, mins[i]); mx = max(mx, maxs[i]) }
                out[x] = (mn, mx)
            }
        }
        return out
    }
}

/// A spectrogram image for an exact time window: column c is the STFT frame centred at
/// t0 + (c + 0.5) * (t1 - t0) / columns, so it lines up with the waveform at any zoom.
struct SpecTile {
    let image: CGImage
    let t0: Double
    let t1: Double
    let source: Source
}

enum SpectrogramRenderer {
    static let rows = 256
    static let minFreq = 40.0
    private static let lut = palette()

    static func render(samples: [Float], rate: Double, t0: Double, t1: Double, columns: Int) -> CGImage? {
        guard columns > 0, t1 > t0, samples.count > 64 else { return nil }
        // shorter windows when zoomed in (sharper onsets), longer when zoomed out (finer pitch)
        let secPerCol = (t1 - t0) / Double(columns)
        let nfft = secPerCol < 0.002 ? 256 : secPerCol < 0.006 ? 512 : secPerCol < 0.03 ? 1024 : 2048
        let half = nfft / 2
        let win = vDSP.window(ofType: Float.self, usingSequence: .hanningDenormalized, count: nfft, isHalfWindow: false)
        let fft = vDSP.FFT(log2n: vDSP_Length(log2(Double(nfft))), radix: .radix2, ofType: DSPSplitComplex.self)!

        let maxFreq = rate / 2
        let edge: (Int) -> Double = { r in
            minFreq * pow(maxFreq / minFreq, Double(r) / Double(rows)) / rate * Double(nfft)
        }
        let rowRange: [(Double, Double)] = (0..<rows).map { r in (min(Double(half - 2), edge(r)), min(Double(half - 1), edge(r + 1))) }

        var pixels = [UInt32](repeating: 0, count: columns * rows)
        var frame = [Float](repeating: 0, count: nfft)
        var re = [Float](repeating: 0, count: half), im = [Float](repeating: 0, count: half)
        var mag = [Float](repeating: 0, count: half)
        let n = samples.count

        samples.withUnsafeBufferPointer { sp in
            for c in 0..<columns {
                let centre = Int(((t0 + (Double(c) + 0.5) * secPerCol) * rate).rounded())
                let start = centre - half
                // copy with zero padding outside the file
                let lo = max(0, start), hi = min(n, start + nfft)
                for i in 0..<nfft { frame[i] = 0 }
                if hi > lo {
                    vDSP_vmul(sp.baseAddress! + lo, 1, win.withUnsafeBufferPointer { $0.baseAddress! + (lo - start) }, 1,
                              &frame[lo - start], 1, vDSP_Length(hi - lo))
                }
                re.withUnsafeMutableBufferPointer { rp in
                    im.withUnsafeMutableBufferPointer { ip in
                        var split = DSPSplitComplex(realp: rp.baseAddress!, imagp: ip.baseAddress!)
                        frame.withUnsafeBufferPointer { fp in
                            fp.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: half) {
                                vDSP_ctoz($0, 2, &split, 1, vDSP_Length(half))
                            }
                        }
                        fft.forward(input: split, output: &split)
                        vDSP_zvmags(&split, 1, &mag, 1, vDSP_Length(half))
                    }
                }
                for r in 0..<rows {
                    let (a, b) = rowRange[r]
                    var m: Float
                    if b - a < 1 {
                        let x = (a + b) / 2, i = Int(x), f = Float(x - Double(i))
                        m = mag[i] * (1 - f) + mag[min(half - 1, i + 1)] * f
                    } else {
                        m = 0
                        for k in Int(a)...min(half - 1, Int(b)) { m = max(m, mag[k]) }
                    }
                    let db = 10 * log10(m / Float(nfft * nfft) + 1e-12)
                    let v = min(1, max(0, (db + 100) / 90)) // -100 dB .. -10 dB
                    pixels[(rows - 1 - r) * columns + c] = lut[Int(v * 255)]
                }
            }
        }
        guard let ctx = CGContext(data: &pixels, width: columns, height: rows, bitsPerComponent: 8, bytesPerRow: columns * 4,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
        else { return nil }
        return ctx.makeImage()
    }

    /// Dark-to-bright palette (indigo -> violet -> rose -> amber -> cream), RGBA packed.
    static func palette() -> [UInt32] {
        let stops: [(Float, Float, Float, Float)] = [
            (0.00, 0.04, 0.04, 0.07), (0.25, 0.16, 0.10, 0.36), (0.50, 0.55, 0.17, 0.52),
            (0.75, 0.96, 0.47, 0.30), (1.00, 1.00, 0.95, 0.80),
        ]
        return (0..<256).map { i in
            let v = Float(i) / 255
            let k = max(0, min(stops.count - 2, Int(v * Float(stops.count - 1))))
            let (p0, r0, g0, b0) = stops[k], (p1, r1, g1, b1) = stops[k + 1]
            let f = (v - p0) / (p1 - p0)
            let r = UInt32((r0 + (r1 - r0) * f) * 255), g = UInt32((g0 + (g1 - g0) * f) * 255), b = UInt32((b0 + (b1 - b0) * f) * 255)
            return r | (g << 8) | (b << 16) | (255 << 24)
        }
    }
}
