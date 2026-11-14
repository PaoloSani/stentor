import CryptoKit
import Foundation

/// Downloads the Core ML models on first launch, so the DMG stays small.
///
/// The zip is a release asset of the app repository (`models-1`). Download resumes after
/// interruptions, the archive is verified with SHA-256 and extracted into
/// ~/Library/Application Support/Stentor/Models, which app updates keep.
@MainActor
final class ModelInstaller: ObservableObject {
    enum Phase: Equatable {
        case idle
        case downloading(received: Int64, total: Int64)
        case verifying
        case installing
        case done
        case failed(String)
    }

    static let modelsURL = URL(string: ProcessInfo.processInfo.environment["STENTOR_MODELS_URL"]
        ?? "https://github.com/PaoloSani/stentor/releases/download/models-1/Stentor-CoreML-float32.zip")!
    nonisolated static let sha256 = "08f715ca202c281288e89a0d996838c1b22851cfbba7b2346c2488fc56bcc66c"
    static let approxSize: Int64 = 933_404_520

    /// Where installed models live (also searched by SidonModel).
    nonisolated static var destination: URL {
        if let d = ProcessInfo.processInfo.environment["STENTOR_MODELS_DEST"] { return URL(fileURLWithPath: d) } // tests
        return SidonModel.appSupport.appendingPathComponent("Models")
    }

    @Published private(set) var phase: Phase = .idle
    var onInstalled: (() -> Void)?

    private var session: URLSession?
    private var task: URLSessionDownloadTask?
    private var resumeData: Data?
    private let delegate = DownloadDelegate()

    var isBusy: Bool {
        switch phase {
        case .downloading, .verifying, .installing: return true
        default: return false
        }
    }

    func start() {
        guard !isBusy else { return }
        phase = .downloading(received: 0, total: ModelInstaller.approxSize)
        delegate.progress = { [weak self] got, total in
            Task { @MainActor in self?.phase = .downloading(received: got, total: total > 0 ? total : ModelInstaller.approxSize) }
        }
        delegate.finished = { [weak self] result in
            Task { @MainActor in self?.downloadFinished(result) }
        }
        let s = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        session = s
        let t = resumeData.map { s.downloadTask(withResumeData: $0) } ?? s.downloadTask(with: ModelInstaller.modelsURL)
        resumeData = nil
        task = t
        t.resume()
    }

    func cancel() {
        task?.cancel { [weak self] data in Task { @MainActor in self?.resumeData = data } }
        task = nil
        phase = .idle
    }

    private func downloadFinished(_ result: Result<URL, Error>) {
        session?.finishTasksAndInvalidate()
        session = nil
        switch result {
        case .failure(let error):
            if let data = (error as NSError).userInfo[NSURLSessionDownloadTaskResumeData] as? Data { resumeData = data }
            if (error as NSError).code == NSURLErrorCancelled { return }
            phase = .failed(Self.describe(error))
        case .success(let zip):
            phase = .verifying
            Task.detached(priority: .userInitiated) {
                let outcome: Result<Void, Error> = Result { try ModelInstaller.verifyAndInstall(zip) }
                await MainActor.run {
                    switch outcome {
                    case .success: self.phase = .done; self.onInstalled?()
                    case .failure(let e): self.phase = .failed(Self.describe(e))
                    }
                }
            }
        }
    }

    private nonisolated static func verifyAndInstall(_ zip: URL) throws {
        defer { try? FileManager.default.removeItem(at: zip) }
        // SHA-256, streamed in 8 MB chunks
        let fh = try FileHandle(forReadingFrom: zip)
        var hasher = SHA256()
        while let chunk = try fh.read(upToCount: 8 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        try fh.close()
        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard digest == sha256 else { throw InstallError.checksum }

        // extract next to the destination, then swap in atomically
        let fm = FileManager.default
        let dest = destination
        let staging = dest.deletingLastPathComponent().appendingPathComponent("Models.partial")
        try? fm.removeItem(at: staging)
        try fm.createDirectory(at: staging, withIntermediateDirectories: true)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        p.arguments = ["-x", "-k", zip.path, staging.path]
        try p.run()
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { throw InstallError.unzip }
        for name in ["feature_extractor_float32.mlpackage", "decoder_float32.mlpackage"] {
            guard fm.fileExists(atPath: staging.appendingPathComponent(name).path) else { throw InstallError.incomplete }
        }
        try? fm.removeItem(at: dest)
        try fm.moveItem(at: staging, to: dest)
    }

    enum InstallError: LocalizedError {
        case checksum, unzip, incomplete
        var errorDescription: String? {
            switch self {
            case .checksum: return "The download is corrupted (checksum mismatch). Please try again."
            case .unzip: return "The model archive could not be extracted."
            case .incomplete: return "The model archive is incomplete."
            }
        }
    }

    private static func describe(_ e: Error) -> String {
        if let http = e as? HTTPError { return http.code == 404
            ? "The voice model isn't available for download right now (HTTP 404)."
            : "Download failed (HTTP \(http.code))." }
        return e.localizedDescription
    }
}

struct HTTPError: Error { let code: Int }

/// URLSession delegate (callbacks arrive on a background queue).
final class DownloadDelegate: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    var progress: ((Int64, Int64) -> Void)?
    var finished: ((Result<URL, Error>) -> Void)?

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask, didWriteData _: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        progress?(totalBytesWritten, totalBytesExpectedToWrite)
    }

    func urlSession(_ s: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        if let http = downloadTask.response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            finished?(.failure(HTTPError(code: http.statusCode))); return
        }
        // the temporary file is deleted when this method returns: move it first
        let dir = SidonModel.appSupport
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let dest = dir.appendingPathComponent("models-download.zip")
        try? FileManager.default.removeItem(at: dest)
        do { try FileManager.default.moveItem(at: location, to: dest); finished?(.success(dest)) }
        catch { finished?(.failure(error)) }
    }

    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { finished?(.failure(error)) }
    }
}
