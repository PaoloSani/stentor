"""Audio loading, speech regions and the region renderer (a port of the macOS app's engine layer).

Only the green regions are sent to the model; everything else stays digital silence and the output
has exactly the length of the input, at 48 kHz.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import soundfile as sf

from stentor.audio.dsp import resample
from stentor.audio.preprocess import prepare

IN_SR = 16_000
OUT_SR = 48_000
UP = OUT_SR // IN_SR
PEAK = 0.9

_ids = itertools.count(1)


# --------------------------------------------------------------------------- audio


@dataclass
class Audio:
    path: Path
    source_rate: int
    channels: int
    listen: np.ndarray  # mono at the source rate, peak-normalised (A side of the A/B)
    wav16k: np.ndarray  # model input: 16 kHz, 50 Hz high-pass, peak-normalised

    @property
    def duration(self) -> float:
        return self.wav16k.shape[0] / IN_SR


def _normalise(x: np.ndarray, peak: float = PEAK) -> np.ndarray:
    m = float(np.abs(x).max()) if x.size else 0.0
    return (x * np.float32(peak / m)).astype(np.float32) if m > 0 else x.astype(np.float32)


def read_any(path: str | Path) -> tuple[np.ndarray, int]:
    """(frames, channels) float32 and the sample rate; libsndfile first, then FFmpeg (PyAV) for m4a/mp3/video."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return data, int(sr)
    except (sf.LibsndfileError, RuntimeError):
        pass
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(f"Cannot read {path.name}: unsupported format") from exc
    try:
        with av.open(str(path)) as container:
            stream = next(s for s in container.streams if s.type == "audio")
            rate = stream.rate or stream.codec_context.sample_rate
            resampler = av.AudioResampler(format="fltp", layout=stream.layout.name, rate=rate)
            chunks = []
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray())
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray())
    except StopIteration:
        raise RuntimeError(f"{path.name} has no audio track") from None
    except Exception as exc:  # av.error.* and friends
        raise RuntimeError(f"Cannot read {path.name}: {exc}") from exc
    if not chunks:
        raise RuntimeError(f"{path.name} contains no audio")
    return np.ascontiguousarray(np.concatenate(chunks, axis=1).T, dtype=np.float32), int(rate)


def load(path: str | Path) -> Audio:
    data, sr = read_any(path)
    mono = data.mean(axis=1, dtype=np.float32) if data.shape[1] > 1 else data[:, 0].copy()
    wav16k = prepare(resample(mono, sr, IN_SR))
    return Audio(Path(path), sr, data.shape[1], _normalise(mono), np.ascontiguousarray(wav16k, dtype=np.float32))


def write_wav(samples: np.ndarray, rate: int, fmt: str, path: str | Path) -> None:
    subtype = {"pcm16": "PCM_16", "pcm24": "PCM_24", "float32": "FLOAT"}[fmt]
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    sf.write(str(tmp), np.clip(samples, -1, 1) if fmt != "float32" else samples, rate, subtype=subtype, format="WAV")
    tmp.replace(path)


def to_rate(enhanced: np.ndarray, audio: Audio, rate: str) -> tuple[np.ndarray, int]:
    """The 48 kHz output, or resampled to the source rate with exactly the original length."""
    if rate != "source" or audio.source_rate == OUT_SR:
        return enhanced, OUT_SR
    sr = audio.source_rate
    y = resample(enhanced, OUT_SR, sr)
    n = round(audio.wav16k.shape[0] / IN_SR * sr)
    return (y[:n] if y.shape[0] >= n else np.pad(y, (0, n - y.shape[0]))), sr


# --------------------------------------------------------------------------- regions


@dataclass(frozen=True)
class Region:
    start: float
    end: float
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def length(self) -> float:
        return self.end - self.start

    def contains(self, t: float) -> bool:
        return self.start <= t <= self.end


@dataclass
class DetectionSettings:
    threshold_db: float = -45.0  # relative to full scale of the peak-normalised signal
    pre_roll: float = 0.15
    post_roll: float = 0.25
    min_speech: float = 0.12
    merge_gap: float = 0.35


def detect(wav16k: np.ndarray, s: DetectionSettings | None = None) -> list[Region]:
    """Energy-based voice activity detection with hysteresis (same rules as the macOS app)."""
    s = s or DetectionSettings()
    frame, hop = 320, 160
    n = wav16k.shape[0]
    if n <= frame:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(wav16k, frame)[::hop]
    db = 10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    on, off = s.threshold_db, s.threshold_db - 6
    raw: list[tuple[float, float]] = []
    active, start = False, 0.0
    for i, v in enumerate(db):
        t = i * hop / IN_SR
        if not active and v >= on:
            active, start = True, t
        elif active and v < off:
            active = False
            raw.append((start, t + frame / IN_SR))
    if active:
        raw.append((start, n / IN_SR))
    dur = n / IN_SR
    merged: list[list[float]] = []
    for a, b in raw:
        if b - a < s.min_speech:
            continue
        lo, hi = max(0.0, a - s.pre_roll), min(dur, b + s.post_roll)
        if merged and lo - merged[-1][1] < s.merge_gap:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [Region(a, b) for a, b in merged]


def normalised(regions: list[Region], duration: float) -> list[Region]:
    """Sort, clamp and merge overlapping regions."""
    out: list[Region] = []
    for r in sorted(regions, key=lambda r: r.start):
        r = replace(r, start=max(0.0, min(r.start, duration)), end=max(0.0, min(r.end, duration)))
        if r.end - r.start < 0.02:
            continue
        if out and r.start <= out[-1].end:
            out[-1] = replace(out[-1], end=max(out[-1].end, r.end))
        else:
            out.append(r)
    return out


# --------------------------------------------------------------------------- renderer


class Cancelled(Exception):
    pass


def _hann(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)).astype(np.float32)


class Renderer:
    MAX_CHUNK = 10.5  # seconds of region per model call
    CONTEXT = 0.5  # real audio on each side of a call
    CROSSFADE = 0.04  # between chunks of a long region
    GATE_FADE = 0.02  # at region edges
    BUCKETS = (4.0, 12.0)  # fixed input lengths keep accelerator memory flat

    def __init__(self, model):
        self.model = model

    @staticmethod
    def split(a: int, b: int, w: np.ndarray) -> list[tuple[int, int]]:
        """[a, b) in chunks of at most MAX_CHUNK seconds, cut at the quietest 20 ms."""
        max_len = int(Renderer.MAX_CHUNK * IN_SR)
        out, s = [], a
        while b - s > max_len:
            lo, hi = s + max_len // 2, s + max_len
            seg = w[lo:hi].astype(np.float64) ** 2
            if seg.shape[0] >= 320:
                energy = np.lib.stride_tricks.sliding_window_view(seg, 320)[::160].mean(axis=1)
                best = lo + int(np.argmin(energy)) * 160 + 160
            else:
                best = hi
            out.append((s, best))
            s = best
        if b > s:
            out.append((s, b))
        return out

    @staticmethod
    def window(a: int, b: int, n: int) -> tuple[int, int, int]:
        ctx = int(Renderer.CONTEXT * IN_SR)
        need = b - a + 2 * ctx
        bucket = next((x for x in Renderer.BUCKETS if need <= x * IN_SR), Renderer.BUCKETS[-1])
        length = int(bucket * IN_SR)
        lo = a - ctx - max(0, length - need) // 2
        lo = max(0, min(lo, n - length))
        return lo, min(n, lo + length), max(length, need)

    def render_regions(
        self,
        audio: Audio,
        regions: list[Region],
        out: np.ndarray,
        clear: list[Region] = (),
        progress: Callable[[float], None] = lambda p: None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        """Silence `clear` spans, then (re)render `regions` into `out` (48 kHz, full length) in place."""
        w, n = audio.wav16k, audio.wav16k.shape[0]
        for r in [*clear, *regions]:
            a, b = max(0, int(r.start * OUT_SR)), min(out.shape[0], int(r.end * OUT_SR) + 1)
            out[a:b] = 0
        plans = [(r, self.split(int(r.start * IN_SR), min(n, int(r.end * IN_SR)), w)) for r in regions]
        total = max(1, sum(ce - cs for _, chunks in plans for cs, ce in chunks))
        done = 0
        half = int(self.CROSSFADE * IN_SR / 2)
        ramp_len = 2 * half * UP
        ramp = _hann(ramp_len) if ramp_len else np.zeros(0, np.float32)
        for region, chunks in plans:
            for k, (cs, ce) in enumerate(chunks):
                if cancelled():
                    raise Cancelled
                first, last = k == 0, k == len(chunks) - 1
                a = cs if first else cs - half
                b = ce if last else ce + half
                lo, hi, length = self.window(a, b, n)
                x = w[lo:hi]
                if x.shape[0] < length:
                    x = np.pad(x, (0, length - x.shape[0]))
                y = self.model.enhance(x)
                off, ln = (a - lo) * UP, (b - a) * UP
                seg = y[off:off + ln].copy()
                if not first and ramp_len:
                    seg[:ramp_len] *= ramp
                if not last and ramp_len:
                    seg[-ramp_len:] *= ramp[::-1]
                out[a * UP:a * UP + seg.shape[0]] += seg
                done += ce - cs
                progress(done / total)
            self._gate(out, region)

    def _gate(self, out: np.ndarray, r: Region) -> None:
        a, b = int(r.start * OUT_SR), min(out.shape[0], int(r.end * OUT_SR))
        f = min(int(self.GATE_FADE * OUT_SR), (b - a) // 2)
        if f > 0:
            g = _hann(f)
            out[a:a + f] *= g
            out[b - f:b] *= g[::-1]


def region_file_name(stem: str, k: int, start: float) -> str:
    m = int(start) // 60
    return f"{stem}_enhanced_{k:02d}_{m}m{start - m * 60:05.2f}s.wav"


def write_region_files(enhanced: np.ndarray, audio: Audio, regions: list[Region], folder: Path, rate: str, fmt: str) -> int:
    """One WAV per region, numbered and named after its start time, plus a CSV of the times."""
    samples, sr = to_rate(enhanced, audio, rate)
    stem = audio.path.stem
    rows = ["file,index,start_s,end_s,duration_s"]
    count = 0
    for k, r in enumerate(regions, 1):
        a, b = max(0, round(r.start * sr)), min(samples.shape[0], round(r.end * sr))
        if b <= a:
            continue
        name = region_file_name(stem, k, r.start)
        write_wav(samples[a:b], sr, fmt, folder / name)
        rows.append(f'"{name}",{k},{r.start:.3f},{r.end:.3f},{r.length:.3f}')
        count += 1
    (folder / f"{stem}_regions.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return count


def timecode(t: float, step: float = 1.0) -> str:
    t = max(0.0, t)
    m = int(t) // 60
    s = t - m * 60
    if step < 0.1:
        return f"{m}:{s:05.2f}"
    if step < 1:
        return f"{m}:{s:04.1f}"
    return f"{m}:{int(s):02d}"


def nice_step(raw: float) -> float:
    steps = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)
    return next((s for s in steps if s >= raw), 600)


__all__ = [
    "Audio", "Cancelled", "DetectionSettings", "Region", "Renderer", "detect", "load", "nice_step",
    "normalised", "timecode", "to_rate", "write_region_files", "write_wav",
]
