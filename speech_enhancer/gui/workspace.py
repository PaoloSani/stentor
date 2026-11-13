"""In-memory state of the GUI: files, their segmentation, and a single background job worker.

All model work runs on one worker thread (one GPU, one model instance); the HTTP layer only
reads state and enqueues jobs.
"""

from __future__ import annotations

import hashlib
import queue
import shutil
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from ..audio import LoadedAudio, load_audio, _decode_with_system_tool
from ..model import OUT_SR, SidonModel
from ..pipeline import Cancelled, Enhancer
from ..segmentation import Segmentation, SegmentationParams, _speech_regions, segment_audio, segment_from_probs

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".aif", ".aiff", ".caf", ".mp4"}
CACHE_ROOT = Path.home() / "Library" / "Caches" / "Stentor"
PEAKS_PER_SECOND = 100
MAX_PEAKS = 400_000
LISTEN_PEAK = 0.9  # the "original" listening copy is peak-normalised like the model input


@dataclass
class Settings:
    output_dir: str = str(Path.home() / "Desktop" / "Stentor Output")
    backend: str = "auto"
    precision: str = "float32"
    mode: str = "speech"  # speech | full
    target_s: float = 12.0
    max_s: float = 20.0
    min_s: float = 3.0


@dataclass
class FileEntry:
    id: str
    path: str
    name: str
    status: str = "new"  # new | queued | analyzing | ready | enhancing | done | error
    message: str = ""
    progress: float = 0.0
    eta_s: Optional[float] = None
    duration: Optional[float] = None
    source_sr: Optional[int] = None
    channels: Optional[int] = None
    version: int = 0  # bumped whenever segmentation/outputs change (the UI refetches details)
    output_path: Optional[str] = None
    output_stale: bool = False
    rtf: Optional[float] = None
    previews: dict = field(default_factory=dict)  # segment index -> cache path
    pending_previews: list = field(default_factory=list)
    seg: Optional[Segmentation] = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def summary(self) -> dict:
        return {
            k: getattr(self, k)
            for k in ("id", "name", "path", "status", "message", "progress", "eta_s", "duration", "version", "output_stale", "rtf")
        } | {"segments": len(self.seg) if self.seg else None, "has_output": bool(self.output_path)}


class Workspace:
    def __init__(self) -> None:
        self.settings = Settings()
        self.files: "OrderedDict[str, FileEntry]" = OrderedDict()
        self.lock = threading.RLock()
        self.jobs: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
        self.model: Optional[SidonModel] = None
        self.model_key: Optional[tuple] = None
        self.model_status = "not loaded"
        self._audio_cache: "OrderedDict[str, LoadedAudio]" = OrderedDict()  # small LRU (8 GB Macs)
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._worker, daemon=True, name="sidon-worker").start()

    # ---------------------------------------------------------------------------------
    # files
    # ---------------------------------------------------------------------------------
    def add_paths(self, paths: list[str]) -> list[str]:
        added = []
        for raw in paths:
            p = Path(raw).expanduser()
            candidates = sorted(q for q in p.rglob("*") if q.suffix.lower() in AUDIO_EXTENSIONS) if p.is_dir() else [p]
            for q in candidates:
                if not q.is_file() or q.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                fid = hashlib.sha1(str(q.resolve()).encode()).hexdigest()[:12]
                with self.lock:
                    if fid not in self.files:
                        self.files[fid] = FileEntry(id=fid, path=str(q.resolve()), name=q.name)
                        self.enqueue("analyze", fid)
                added.append(fid)
        return added

    def remove(self, fid: str) -> None:
        with self.lock:
            entry = self.files.pop(fid, None)
            self._audio_cache.pop(fid, None)
        if entry:
            entry.cancel.set()
            shutil.rmtree(self.cache_dir(fid), ignore_errors=True)

    def get(self, fid: str) -> FileEntry:
        with self.lock:
            return self.files[fid]

    def cache_dir(self, fid: str) -> Path:
        d = CACHE_ROOT / fid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def details(self, fid: str) -> dict:
        e = self.get(fid)
        out = e.summary() | {"source_sr": e.source_sr, "channels": e.channels, "output_path": e.output_path,
                             "previews": sorted(e.previews), "pending_previews": e.pending_previews,
                             "output_mtime": Path(e.output_path).stat().st_mtime if e.output_path and Path(e.output_path).exists() else None}
        if e.seg:
            speech_total = sum(b - a for a, b in e.seg.speech)
            out["segmentation"] = {
                "cuts": e.seg.cuts,
                "speech": e.seg.speech,
                "segments": [
                    {"start": a, "end": b, "speech": _overlap(a, b, e.seg.speech) / (b - a) if b > a else 0.0}
                    for a, b in e.seg.segments
                ],
                "speech_fraction": speech_total / e.duration if e.duration else 0.0,
                "params": asdict(e.seg.params),
            }
            if e.seg.vad_probs is not None:
                out["vad"] = {"hop_s": 512 / 16000, "probs": np.round(e.seg.vad_probs, 2).tolist()}
        return out

    # ---------------------------------------------------------------------------------
    # segmentation editing (instant, no job)
    # ---------------------------------------------------------------------------------
    def set_segmentation(self, fid: str, cuts: Optional[list] = None, speech: Optional[list] = None) -> None:
        """Replace cuts and/or speech regions with user edits (normalised server-side)."""
        e = self.get(fid)
        with self.lock:
            if cuts is not None:
                e.seg.cuts = sorted({round(float(c), 3) for c in cuts if 0.05 < float(c) < e.duration - 0.05})
            if speech is not None:
                e.seg.speech = normalise_regions(speech, e.duration)
            self._segmentation_changed(e)

    def reset_speech(self, fid: str) -> None:
        """Restore the speech regions detected by the VAD (cuts are left alone)."""
        e = self.get(fid)
        with self.lock:
            p = e.seg.params
            e.seg.speech = _speech_regions(e.seg.vad_probs, p.vad_threshold, p.min_pause_ms / 1000)
            self._segmentation_changed(e)

    def resegment(self, fid: str) -> None:
        e = self.get(fid)
        s = self.settings
        params = SegmentationParams(target_s=s.target_s, max_s=s.max_s, min_s=s.min_s)
        with self.lock:
            e.seg = segment_from_probs(e.seg.vad_probs, e.duration, params)
            self._segmentation_changed(e)

    def _segmentation_changed(self, e: FileEntry) -> None:
        e.previews.clear()
        if e.output_path:
            e.output_stale = True
        e.version += 1
        e.seg.to_json(self.cache_dir(e.id) / "segments.json")

    # ---------------------------------------------------------------------------------
    # jobs
    # ---------------------------------------------------------------------------------
    def enqueue(self, kind: str, fid: str, arg: object = None) -> None:
        e = self.files[fid]
        if kind == "enhance":
            e.cancel.clear()
            e.status, e.message, e.progress = "queued", "Queued", 0.0
        elif kind == "preview":
            e.pending_previews.append(arg)
        self.jobs.put((kind, fid, arg))

    def cancel(self, fid: str) -> None:
        self.get(fid).cancel.set()

    def _worker(self) -> None:
        while True:
            kind, fid, arg = self.jobs.get()
            with self.lock:
                entry = self.files.get(fid)
            if entry is None:
                continue
            try:
                {"analyze": self._analyze, "preview": self._preview, "enhance": self._enhance}[kind](entry, arg)
            except Cancelled:
                entry.status, entry.message = ("done" if entry.output_path else "ready"), "Cancelled"
            except Exception as exc:  # surfaced in the UI
                traceback.print_exc()
                entry.status, entry.message = "error", f"{type(exc).__name__}: {exc}"
            finally:
                if kind == "preview" and arg in entry.pending_previews:
                    entry.pending_previews.remove(arg)
                entry.version += 1

    def _audio(self, e: FileEntry) -> LoadedAudio:
        with self.lock:
            if e.id in self._audio_cache:
                self._audio_cache.move_to_end(e.id)
                return self._audio_cache[e.id]
        audio = load_audio(e.path)
        with self.lock:
            self._audio_cache[e.id] = audio
            while len(self._audio_cache) > 2:
                self._audio_cache.popitem(last=False)
        return audio

    def _get_model(self) -> SidonModel:
        key = (self.settings.backend, self.settings.precision)
        if self.model is None or self.model_key != key:
            self.model = None
            self.model_status = "loading"
            t = time.perf_counter()
            self.model = SidonModel(backend=key[0], precision=key[1])
            self.model_key = key
            self.model_status = f"{self.model.description} (loaded in {time.perf_counter() - t:.0f}s)"
        return self.model

    def _analyze(self, e: FileEntry, _arg) -> None:
        e.status, e.message, e.progress = "analyzing", "Reading audio", 0.0
        audio = self._audio(e)
        e.duration, e.source_sr, e.channels = audio.duration, audio.source_sr, audio.channels
        cache = self.cache_dir(e.id)

        e.message = "Preparing listening copy"
        write_listen_copy(e.path, cache / "original.wav")
        np.save(cache / "peaks_original.npy", peaks_from_file(cache / "original.wav"))

        e.message = "Detecting speech (VAD)"
        s = self.settings
        params = SegmentationParams(target_s=s.target_s, max_s=s.max_s, min_s=s.min_s)

        def vad_progress(f: float) -> None:
            e.progress = f

        e.seg = segment_audio(audio.wav16k, params, progress=vad_progress)
        e.seg.to_json(cache / "segments.json")

        existing = self._output_path(e)
        if existing.exists():  # enhanced earlier in a previous session
            e.output_path, e.output_stale = str(existing), True
            np.save(cache / "peaks_enhanced.npy", peaks_from_file(existing))
        e.status, e.message, e.progress = ("done" if e.output_path else "ready"), "", 1.0

    def _preview(self, e: FileEntry, k: int) -> None:
        start, end = e.seg.segments[k]
        model = self._get_model()
        y = self._enhancer(model).enhance_segment(self._audio(e), start, end, e.seg.speech)
        path = self.cache_dir(e.id) / f"preview_{k}_{start:.3f}_{end:.3f}.wav"
        sf.write(str(path), y, OUT_SR, subtype="PCM_24")
        e.previews[k] = str(path)

    def _enhancer(self, model: SidonModel) -> Enhancer:
        return Enhancer(model, speech_only=self.settings.mode == "speech")

    def _output_path(self, e: FileEntry) -> Path:
        return Path(self.settings.output_dir).expanduser() / f"{Path(e.name).stem}_enhanced.wav"

    def _enhance(self, e: FileEntry, _arg) -> None:
        if e.cancel.is_set():
            raise Cancelled()
        e.status, e.message, e.progress, e.eta_s = "enhancing", "Loading model", 0.0, None
        model = self._get_model()
        audio = self._audio(e)
        out = self._output_path(e)
        out.parent.mkdir(parents=True, exist_ok=True)
        e.message = model.description

        def progress(p) -> None:
            e.progress, e.eta_s = p.fraction, (None if p.eta_s != p.eta_s else p.eta_s)
            e.message = f"Segment {p.segment + 1}/{p.total_segments}"

        stats = self._enhancer(model).run(audio, e.seg, out, progress=progress, cancel=e.cancel)
        e.seg.to_json(out.with_suffix(".segments.json"))
        np.save(self.cache_dir(e.id) / "peaks_enhanced.npy", peaks_from_file(out))
        e.output_path, e.output_stale, e.rtf = str(out), False, stats.rtf
        e.status, e.message, e.progress, e.eta_s = "done", f"Done: {1 / stats.rtf:.1f}x real time", 1.0, None


# -------------------------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------------------------
def normalise_regions(regions: list, duration: float, min_len: float = 0.05) -> list[tuple[float, float]]:
    """Clamp to [0, duration], sort, merge overlaps, drop slivers."""
    clean = sorted(
        (max(0.0, min(float(a), float(b))), min(duration, max(float(a), float(b)))) for a, b in regions
    )
    out: list[list[float]] = []
    for a, b in clean:
        if b - a < min_len:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def _overlap(a: float, b: float, regions: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, r1) - max(a, r0)) for r0, r1 in regions)


def write_listen_copy(src: str, dst: Path, block_s: int = 30) -> None:
    """Mono, peak-normalised copy at the source rate (fair A/B against the enhanced output)."""
    src_path = Path(src)
    try:
        info = sf.info(str(src_path))
    except sf.LibsndfileError:
        decoded = _decode_with_system_tool(src_path, str(dst.parent))
        src_path, info = decoded, sf.info(str(decoded))
    peak = 0.0
    for block in sf.blocks(str(src_path), blocksize=block_s * info.samplerate, dtype="float32", always_2d=True):
        peak = max(peak, float(np.abs(block.mean(axis=1)).max(initial=0.0)))
    gain = LISTEN_PEAK / peak if peak > 0 else 1.0
    with sf.SoundFile(str(dst), "w", info.samplerate, 1, subtype="PCM_16") as out:
        for block in sf.blocks(str(src_path), blocksize=block_s * info.samplerate, dtype="float32", always_2d=True):
            out.write(np.clip(block.mean(axis=1) * gain, -1, 1))
    if src_path != Path(src):
        src_path.unlink(missing_ok=True)


def peaks_from_file(path: Path) -> np.ndarray:
    """Max-abs envelope for waveform display (float16, about PEAKS_PER_SECOND per second)."""
    info = sf.info(str(path))
    per = max(1, int(info.samplerate / PEAKS_PER_SECOND), int(np.ceil(info.frames / MAX_PEAKS)))
    chunks = []
    for block in sf.blocks(str(path), blocksize=per * 10_000, dtype="float32", always_2d=True):
        x = np.abs(block.mean(axis=1))
        n = len(x) // per * per
        if n:
            chunks.append(x[:n].reshape(-1, per).max(axis=1))
        if len(x) > n:
            chunks.append(np.array([x[n:].max()]))
    return np.concatenate(chunks).astype(np.float16) if chunks else np.zeros(1, np.float16)
