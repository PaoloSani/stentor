import AVFoundation
import Combine
import Foundation

/// Playhead clock, published separately so only the playhead views redraw while playing.
final class Transport: ObservableObject {
    @Published var time: Double = 0
    @Published var isPlaying = false
}

/// AVAudioEngine playback of either the original (A) or the enhanced (B) signal,
/// with seeking and gapless looping of a time range.
final class Player {
    private let engine = AVAudioEngine()
    private let node = AVAudioPlayerNode()
    private var connectedFormat: AVAudioFormat?
    private var buffer: AVAudioPCMBuffer?
    private var rate: Double = 48_000
    private var startTime: Double = 0
    private var loop: ClosedRange<Double>?
    private var timer: Timer?
    private var generation = 0
    let transport = Transport()

    init() {
        engine.attach(node)
        if CommandLine.arguments.contains("--logic") { engine.mainMixerNode.outputVolume = 0 } // silent tests
    }

    /// Replace the signal being played (keeps the playhead position).
    func setSignal(_ samples: [Float], rate: Double) {
        let wasPlaying = transport.isPlaying
        let t = currentTime
        stopNode()
        self.rate = rate
        let fmt = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1)!
        let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(samples.count))!
        buf.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { buf.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        buffer = buf
        if connectedFormat != fmt {
            engine.disconnectNodeOutput(node)
            engine.connect(node, to: engine.mainMixerNode, format: fmt)
            connectedFormat = fmt
        }
        transport.time = t
        if wasPlaying { play(from: t) }
    }

    var duration: Double { buffer.map { Double($0.frameLength) / rate } ?? 0 }

    var currentTime: Double {
        guard transport.isPlaying, let nt = node.lastRenderTime, let pt = node.playerTime(forNodeTime: nt) else {
            return transport.time
        }
        let t = startTime + Double(pt.sampleTime) / pt.sampleRate
        if let l = loop, t >= l.upperBound {
            let len = max(0.001, l.upperBound - l.lowerBound)
            return l.lowerBound + (t - l.upperBound).truncatingRemainder(dividingBy: len)
        }
        return t
    }

    func play(from t: Double, loop: ClosedRange<Double>? = nil) {
        guard let buffer else { return }
        stopNode()
        var start = min(max(0, t), duration)
        if let l = loop, !(l.contains(start)) { start = l.lowerBound }
        if loop == nil && start >= duration - 0.01 { start = 0 }
        self.loop = loop
        startTime = start
        if !engine.isRunning { try? engine.start() }

        generation += 1
        let gen = generation
        let endT = loop?.upperBound ?? duration
        if let first = slice(buffer, from: start, to: endT) {
            node.scheduleBuffer(first, at: nil, options: []) { [weak self] in
                guard let self, loop == nil else { return }
                DispatchQueue.main.async { if self.generation == gen { self.pause() } }
            }
        }
        if let l = loop, let body = slice(buffer, from: l.lowerBound, to: l.upperBound) {
            node.scheduleBuffer(body, at: nil, options: [.loops])
        }
        node.play()
        transport.isPlaying = true
        startTimer()
    }

    func pause() {
        let t = currentTime
        stopNode()
        transport.time = t
    }

    func seek(_ t: Double) {
        if transport.isPlaying { play(from: t, loop: loop) } else { transport.time = min(max(0, t), duration) }
    }

    /// Change the loop while playing (or arm it for the next play).
    func setLoop(_ l: ClosedRange<Double>?) {
        if transport.isPlaying { play(from: currentTime, loop: l) } else { loop = l }
    }

    private func stopNode() {
        generation += 1
        node.stop()
        transport.isPlaying = false
        timer?.invalidate(); timer = nil
    }

    private func startTimer() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.transport.time = self.currentTime
        }
    }

    private func slice(_ b: AVAudioPCMBuffer, from t0: Double, to t1: Double) -> AVAudioPCMBuffer? {
        let a = Int(t0 * rate), z = min(Int(b.frameLength), Int(t1 * rate))
        guard z > a else { return nil }
        let out = AVAudioPCMBuffer(pcmFormat: b.format, frameCapacity: AVAudioFrameCount(z - a))!
        out.frameLength = AVAudioFrameCount(z - a)
        out.floatChannelData![0].update(from: b.floatChannelData![0] + a, count: z - a)
        return out
    }
}
