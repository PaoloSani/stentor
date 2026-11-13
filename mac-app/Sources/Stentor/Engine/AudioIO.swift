import AVFoundation
import Accelerate
import Foundation

enum AudioError: LocalizedError {
    case unreadable(String)
    case conversion(String)
    var errorDescription: String? {
        switch self {
        case .unreadable(let s): return "Cannot read audio: \(s)"
        case .conversion(let s): return "Audio conversion failed: \(s)"
        }
    }
}

/// A loaded source file, prepared like speech_enhancer/audio.py.
struct LoadedAudio {
    let url: URL
    let sourceRate: Double
    let channels: Int
    /// Mono listening copy at the source rate, peak-normalised to 0.9 (A side of the A/B).
    let listen: [Float]
    /// Model input: mono, 16 kHz, high-passed at 50 Hz, peak-normalised to 0.9.
    let wav16k: [Float]

    var duration: Double { Double(wav16k.count) / 16_000 }
}

enum AudioIO {
    static let peak: Float = 0.9

    static func load(_ url: URL) throws -> LoadedAudio {
        let file: AVAudioFile
        do { file = try AVAudioFile(forReading: url) } catch { throw AudioError.unreadable(error.localizedDescription) }
        let fmt = file.processingFormat // deinterleaved float32
        let frames = AVAudioFrameCount(file.length)
        guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: frames) else { throw AudioError.unreadable("buffer") }
        try file.read(into: buf)
        let n = Int(buf.frameLength), ch = Int(fmt.channelCount)

        // mono mix-down
        var mono = [Float](repeating: 0, count: n)
        for c in 0..<ch {
            vDSP_vadd(mono, 1, buf.floatChannelData![c], 1, &mono, 1, vDSP_Length(n))
        }
        if ch > 1 { vDSP.multiply(1 / Float(ch), mono, result: &mono) }

        // model input: resample -> high-pass -> peak-normalise (same order as the Python code)
        var w16 = try resample(mono, from: fmt.sampleRate, to: 16_000)
        w16 = highpassBiquad(w16, sampleRate: 16_000, cutoff: 50)
        normalise(&w16, to: peak)

        var listen = mono
        normalise(&listen, to: peak)
        return LoadedAudio(url: url, sourceRate: fmt.sampleRate, channels: ch, listen: listen, wav16k: w16)
    }

    static func normalise(_ x: inout [Float], to target: Float) {
        let m = vDSP.maximumMagnitude(x)
        if m > 0 { vDSP.multiply(target / m, x, result: &x) }
    }

    /// High-quality sample-rate conversion with AVAudioConverter.
    static func resample(_ x: [Float], from: Double, to: Double) throws -> [Float] {
        if from == to { return x }
        guard let inFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: from, channels: 1, interleaved: false),
              let outFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: to, channels: 1, interleaved: false),
              let conv = AVAudioConverter(from: inFmt, to: outFmt) else { throw AudioError.conversion("formats") }
        conv.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        conv.sampleRateConverterAlgorithm = AVSampleRateConverterAlgorithm_Mastering

        let inBuf = AVAudioPCMBuffer(pcmFormat: inFmt, frameCapacity: AVAudioFrameCount(x.count))!
        inBuf.frameLength = AVAudioFrameCount(x.count)
        x.withUnsafeBufferPointer { inBuf.floatChannelData![0].update(from: $0.baseAddress!, count: x.count) }
        let expected = Int((Double(x.count) * to / from).rounded())
        let outBuf = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: AVAudioFrameCount(expected + 4096))!

        var fed = false
        var err: NSError?
        let status = conv.convert(to: outBuf, error: &err) { _, outStatus in
            if fed { outStatus.pointee = .endOfStream; return nil }
            fed = true
            outStatus.pointee = .haveData
            return inBuf
        }
        if status == .error { throw AudioError.conversion(err?.localizedDescription ?? "unknown") }
        var out = Array(UnsafeBufferPointer(start: outBuf.floatChannelData![0], count: Int(outBuf.frameLength)))
        if out.count < expected { out += [Float](repeating: 0, count: expected - out.count) }
        return Array(out.prefix(expected))
    }

    /// torchaudio.functional.highpass_biquad (Q = 0.707), output clamped to [-1, 1] like lfilter.
    static func highpassBiquad(_ x: [Float], sampleRate: Double, cutoff: Double, q: Double = 0.707) -> [Float] {
        let w0 = 2 * Double.pi * cutoff / sampleRate
        let alpha = sin(w0) / 2 / q
        let c = cos(w0)
        let a0 = 1 + alpha
        let b0 = (1 + c) / 2 / a0, b1 = -(1 + c) / a0, b2 = (1 + c) / 2 / a0
        let a1 = -2 * c / a0, a2 = (1 - alpha) / a0
        var y = [Float](repeating: 0, count: x.count)
        var x1 = 0.0, x2 = 0.0, y1 = 0.0, y2 = 0.0
        for i in 0..<x.count {
            let xi = Double(x[i])
            let yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2 = x1; x1 = xi; y2 = y1; y1 = yi
            y[i] = Float(min(1, max(-1, yi)))
        }
        return y
    }

    /// Mono WAV (16/24-bit PCM or 32-bit float).
    static func writeWav(_ samples: [Float], sampleRate: Double, format: ExportFormat = .pcm24, to url: URL) throws {
        let bits = format == .pcm16 ? 16 : format == .pcm24 ? 24 : 32
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: bits,
            AVLinearPCMIsFloatKey: format == .float32,
            AVLinearPCMIsBigEndianKey: false,
        ]
        try? FileManager.default.removeItem(at: url)
        let file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        let fmt = file.processingFormat
        let chunk = 1 << 18
        var pos = 0
        while pos < samples.count {
            let n = min(chunk, samples.count - pos)
            let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(n))!
            buf.frameLength = AVAudioFrameCount(n)
            samples.withUnsafeBufferPointer { sp in
                var lo: Float = -1, hi: Float = 1
                vDSP_vclip(sp.baseAddress! + pos, 1, &lo, &hi, buf.floatChannelData![0], 1, vDSP_Length(n))
            }
            try file.write(from: buf)
            pos += n
        }
    }

    static func readMono(_ url: URL) throws -> (samples: [Float], rate: Double) {
        let file = try AVAudioFile(forReading: url)
        let buf = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length))!
        try file.read(into: buf)
        return (Array(UnsafeBufferPointer(start: buf.floatChannelData![0], count: Int(buf.frameLength))), file.processingFormat.sampleRate)
    }
}
