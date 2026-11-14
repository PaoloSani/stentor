import Accelerate
import Foundation

/// Swift port of torchaudio.compliance.kaldi.fbank as configured for w2v-BERT 2.0
/// (SeamlessM4TFeatureExtractor): 80 mel bins, 25 ms / 10 ms povey windows, pre-emphasis 0.97,
/// DC removal, power spectrum, log mel energies, per-bin mean/variance normalisation, and
/// stacking of 2 frames -> 160-dim features at 50 Hz. Mirrors speech_enhancer/features.py.
final class Fbank {
    static let sampleRate = 16_000.0
    static let windowSize = 400
    static let windowShift = 160
    static let fftSize = 512
    static let numMel = 80
    static let edgePad = 160
    static let stride = 2

    private let window: [Float]
    private let melBanks: [Float] // numMel x (fftSize/2 + 1), row-major
    private let fft: vDSP.FFT<DSPSplitComplex>

    init() {
        // povey window = (non-periodic Hann)^0.85
        let n = Fbank.windowSize
        window = (0..<n).map { i in
            Float(pow(0.5 - 0.5 * cos(2 * Double.pi * Double(i) / Double(n - 1)), 0.85))
        }
        melBanks = Fbank.makeMelBanks()
        fft = vDSP.FFT(log2n: vDSP_Length(log2(Double(Fbank.fftSize))), radix: .radix2, ofType: DSPSplitComplex.self)!
    }

    private static func mel(_ f: Double) -> Double { 1127.0 * log(1.0 + f / 700.0) }

    private static func makeMelBanks() -> [Float] {
        let bins = fftSize / 2 // 256 (the Nyquist column stays zero)
        let lowMel = mel(20.0), highMel = mel(sampleRate / 2)
        let delta = (highMel - lowMel) / Double(numMel + 1)
        let binWidth = sampleRate / Double(fftSize)
        var out = [Float](repeating: 0, count: numMel * (bins + 1))
        for m in 0..<numMel {
            let left = lowMel + Double(m) * delta
            let center = lowMel + Double(m + 1) * delta
            let right = lowMel + Double(m + 2) * delta
            for k in 0..<bins {
                let x = mel(binWidth * Double(k))
                let up = (x - left) / (center - left)
                let down = (right - x) / (right - center)
                out[m * (bins + 1) + k] = Float(max(0, min(up, down)))
            }
        }
        return out
    }

    /// Features for a 16 kHz mono waveform: returns (frames, data) with data row-major frames x 160.
    func features(_ wav: [Float]) -> (frames: Int, data: [Float]) {
        let pad = Fbank.edgePad
        var x = [Float](repeating: 0, count: wav.count + 2 * pad)
        x.replaceSubrange(pad..<(pad + wav.count), with: wav)

        let n = Fbank.windowSize, hop = Fbank.windowShift, nfft = Fbank.fftSize
        let numFrames = x.count >= n ? 1 + (x.count - n) / hop : 0
        let nBins = nfft / 2 + 1
        var logMel = [Float](repeating: 0, count: numFrames * Fbank.numMel)

        var frame = [Float](repeating: 0, count: nfft)
        var real = [Float](repeating: 0, count: nfft / 2)
        var imag = [Float](repeating: 0, count: nfft / 2)
        var power = [Float](repeating: 0, count: nBins)
        let eps = Float(1.1920928955078125e-07)

        x.withUnsafeBufferPointer { xp in
            for f in 0..<numFrames {
                let src = xp.baseAddress! + f * hop
                // DC removal
                var mean: Float = 0
                vDSP_meanv(src, 1, &mean, vDSP_Length(n))
                // pre-emphasis with replicate padding: y[i] = x[i] - 0.97 * x[i-1], x[-1] = x[0]
                var prev = src[0] - mean
                for i in 0..<n {
                    let cur = src[i] - mean
                    frame[i] = (cur - 0.97 * prev) * window[i]
                    prev = cur
                }
                for i in n..<nfft { frame[i] = 0 }

                // real FFT: pack even/odd samples into split complex
                real.withUnsafeMutableBufferPointer { rp in
                    imag.withUnsafeMutableBufferPointer { ip in
                        var split = DSPSplitComplex(realp: rp.baseAddress!, imagp: ip.baseAddress!)
                        frame.withUnsafeBufferPointer { fp in
                            fp.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: nfft / 2) {
                                vDSP_ctoz($0, 2, &split, 1, vDSP_Length(nfft / 2))
                            }
                        }
                        fft.forward(input: split, output: &split)
                        // vDSP's real FFT is scaled by 2; DC in realp[0], Nyquist in imagp[0]
                        power[0] = (rp[0] / 2) * (rp[0] / 2)
                        power[nfft / 2] = (ip[0] / 2) * (ip[0] / 2)
                        for k in 1..<(nfft / 2) {
                            let re = rp[k] / 2, im = ip[k] / 2
                            power[k] = re * re + im * im
                        }
                    }
                }
                // mel energies, log with floor
                for m in 0..<Fbank.numMel {
                    var e: Float = 0
                    melBanks.withUnsafeBufferPointer { mb in
                        vDSP_dotpr(mb.baseAddress! + m * nBins, 1, power, 1, &e, vDSP_Length(nBins))
                    }
                    logMel[f * Fbank.numMel + m] = log(max(e, eps))
                }
            }
        }

        // per-mel-bin normalisation (unbiased variance, like torch.var)
        if numFrames > 1 {
            for m in 0..<Fbank.numMel {
                var sum: Double = 0, sq: Double = 0
                for f in 0..<numFrames { let v = Double(logMel[f * Fbank.numMel + m]); sum += v; sq += v * v }
                let mean = sum / Double(numFrames)
                let variance = max(0, (sq - Double(numFrames) * mean * mean) / Double(numFrames - 1))
                let inv = 1 / sqrt(variance + 1e-5)
                for f in 0..<numFrames {
                    let i = f * Fbank.numMel + m
                    logMel[i] = Float((Double(logMel[i]) - mean) * inv)
                }
            }
        }

        // stack pairs of frames: (frames/2) x 160
        let stacked = numFrames / Fbank.stride
        return (stacked, Array(logMel[0..<(stacked * Fbank.stride * Fbank.numMel)]))
    }
}
