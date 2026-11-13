"""Segment-wise enhancement of long recordings with streaming, crossfaded output."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from .audio import LoadedAudio
from .model import IN_SR, OUT_SR, UPSAMPLE, SidonModel
from .segmentation import Segmentation


@dataclass
class Progress:
    segment: int  # index of the segment just finished
    total_segments: int
    audio_done_s: float
    audio_total_s: float
    elapsed_s: float

    @property
    def fraction(self) -> float:
        return self.audio_done_s / self.audio_total_s if self.audio_total_s else 1.0

    @property
    def eta_s(self) -> float:
        if self.audio_done_s <= 0:
            return float("nan")
        return self.elapsed_s / self.audio_done_s * (self.audio_total_s - self.audio_done_s)


@dataclass
class RunStats:
    audio_s: float
    elapsed_s: float
    segment_times: list[float] = field(default_factory=list)

    @property
    def rtf(self) -> float:
        return self.elapsed_s / self.audio_s if self.audio_s else 0.0


class Cancelled(Exception):
    pass


def _hann_ramp(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)).astype(np.float32)


class Enhancer:
    """Segment-wise enhancement.

    speech_only=True (default): only the VAD speech regions, widened by `speech_pad_s`, are
    sent to the model; everything else is written as digital silence (with `gate_fade_ms`
    ramps at region edges). Segments without speech are skipped entirely, and inside a
    segment the model only runs from the first to the last speech region (plus context).
    """

    def __init__(
        self,
        model: SidonModel,
        context_s: float = 0.5,
        crossfade_ms: float = 40.0,
        speech_only: bool = True,
        speech_pad_s: float = 0.3,
        gate_fade_ms: float = 40.0,
        min_gap_s: float = 0.3,
    ):
        self.model = model
        self.ctx16 = int(context_s * IN_SR)
        self.half16 = int(crossfade_ms / 2000 * IN_SR)  # half crossfade, in 16 kHz samples
        assert self.ctx16 >= self.half16
        ramp = _hann_ramp(2 * self.half16 * UPSAMPLE)  # equal-gain crossfade between segments
        self.fade_in = ramp
        self.fade_out = 1.0 - ramp
        self.speech_only = speech_only
        self.pad16 = int(speech_pad_s * IN_SR)
        self.gate_fade48 = int(gate_fade_ms / 1000 * OUT_SR)
        self.min_gap16 = int(min_gap_s * IN_SR)

    # -----------------------------------------------------------------------------------
    # speech gating
    # -----------------------------------------------------------------------------------
    def active_regions16(self, speech: list[tuple[float, float]], n16: int) -> list[tuple[int, int]]:
        """VAD speech regions widened by the pad and merged across short gaps (16 kHz samples)."""
        out: list[list[int]] = []
        for a, b in speech:
            lo = max(0, int(a * IN_SR) - self.pad16)
            hi = min(n16, int(b * IN_SR) + self.pad16)
            if out and lo - out[-1][1] < self.min_gap16:
                out[-1][1] = max(out[-1][1], hi)
            else:
                out.append([lo, hi])
        return [(a, b) for a, b in out]

    def _gate(self, a16: int, b16: int, active: list[tuple[int, int]]) -> Optional[np.ndarray]:
        """48 kHz gain mask for [a16, b16): 1 inside active regions, 0 outside, Hann ramps
        placed inside each region. None if the range contains no speech."""
        hits = [(s, e) for s, e in active if s < b16 and e > a16]
        if not hits:
            return None
        A, B = a16 * UPSAMPLE, b16 * UPSAMPLE
        mask = np.zeros(B - A, dtype=np.float32)
        for rs, re in hits:
            # Defined on absolute time, so overlapping ranges (crossfades) see the same gain.
            r0, r1 = rs * UPSAMPLE, re * UPSAMPLE
            n = min(self.gate_fade48, (r1 - r0) // 2)
            idx = np.arange(max(A, r0), min(B, r1))
            g = np.ones(len(idx), dtype=np.float32)
            if n > 0:
                ramp = _hann_ramp(n)
                head = idx < r0 + n
                g[head] = ramp[idx[head] - r0]
                tail = idx >= r1 - n
                g[tail] = ramp[::-1][idx[tail] - (r1 - n)]
            mask[idx - A] = np.maximum(mask[idx - A], g)
        return mask

    def _enhance_window(self, wav16k, a16: int, b16: int, n16: int) -> np.ndarray:
        """Enhanced audio for exactly [a16, b16) at 48 kHz, with model context on both sides."""
        lo = max(0, a16 - self.ctx16)
        hi = min(n16, b16 + self.ctx16)
        y = self.model.enhance(wav16k[lo:hi]).numpy()
        return y[(a16 - lo) * UPSAMPLE:(b16 - lo) * UPSAMPLE]

    def _render(self, wav16k, a16: int, b16: int, n16: int, active) -> tuple[np.ndarray, float]:
        """Output for [a16, b16) and the seconds of audio actually sent to the model."""
        if not self.speech_only:
            return self._enhance_window(wav16k, a16, b16, n16), (b16 - a16) / IN_SR
        mask = self._gate(a16, b16, active)
        if mask is None:
            return np.zeros((b16 - a16) * UPSAMPLE, dtype=np.float32), 0.0
        nz = np.flatnonzero(mask)
        lo16 = a16 + nz[0] // UPSAMPLE
        hi16 = min(b16, a16 + nz[-1] // UPSAMPLE + 1)
        out = np.zeros_like(mask)
        out[(lo16 - a16) * UPSAMPLE:(hi16 - a16) * UPSAMPLE] = self._enhance_window(wav16k, lo16, hi16, n16)
        return out * mask, (hi16 - lo16) / IN_SR

    # -----------------------------------------------------------------------------------
    def _bounds16(self, seg: Segmentation, n16: int) -> list[tuple[int, int]]:
        cuts = [int(round(c * IN_SR)) for c in seg.cuts]
        # A cut closer than one crossfade to its neighbour cannot be crossfaded: drop it.
        clean: list[int] = []
        for c in cuts:
            prev = clean[-1] if clean else 0
            if c - prev > 2 * self.half16 and n16 - c > 2 * self.half16:
                clean.append(c)
        edges = [0, *clean, n16]
        return list(zip(edges[:-1], edges[1:]))

    def enhance_segment(
        self, audio: LoadedAudio, start_s: float, end_s: float, speech: Optional[list[tuple[float, float]]] = None
    ) -> np.ndarray:
        """Enhance one region for preview; returns exactly [start_s, end_s] at 48 kHz."""
        n16 = audio.num_samples
        s, e = int(round(start_s * IN_SR)), int(round(end_s * IN_SR))
        active = self.active_regions16(speech or [], n16)
        return self._render(audio.wav16k, s, e, n16, active)[0]

    def plan(self, segmentation: Segmentation, n16: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]], float]:
        """Segment bounds, active regions and the seconds of audio the model will process."""
        bounds = self._bounds16(segmentation, n16)
        active = self.active_regions16(segmentation.speech, n16)
        if not self.speech_only:
            return bounds, active, n16 / IN_SR
        work = sum(min(n16, e + self.half16) - max(0, s - self.half16) for s, e in active) / IN_SR
        return bounds, active, work

    # -----------------------------------------------------------------------------------
    def run(
        self,
        audio: LoadedAudio,
        segmentation: Segmentation,
        out_path: str | Path,
        subtype: str = "PCM_24",
        progress: Optional[Callable[[Progress], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> RunStats:
        n16 = audio.num_samples
        bounds, active, work_total = self.plan(segmentation, n16)
        ov = 2 * self.half16 * UPSAMPLE  # overlap length at 48 kHz
        stats = RunStats(audio_s=audio.duration, elapsed_s=0.0)
        work_done = 0.0
        t0 = time.perf_counter()

        out_path = Path(out_path)
        tmp_path = out_path.with_name(out_path.name + ".part")
        try:
            with sf.SoundFile(str(tmp_path), "w", OUT_SR, 1, subtype=subtype, format="WAV") as out:
                tail: Optional[np.ndarray] = None
                for k, (s16, e16) in enumerate(bounds):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    ts = time.perf_counter()
                    a16, b16 = max(0, s16 - self.half16), min(n16, e16 + self.half16)
                    piece, worked = self._render(audio.wav16k, a16, b16, n16, active)
                    work_done += worked
                    last = k == len(bounds) - 1

                    if tail is not None:  # crossfade with the previous segment around the cut
                        out.write(_clip(tail * self.fade_out + piece[:ov] * self.fade_in, subtype))
                        piece = piece[ov:]
                    if last:
                        out.write(_clip(piece, subtype))
                    else:
                        out.write(_clip(piece[:-ov], subtype))
                        tail = piece[-ov:]

                    stats.segment_times.append(time.perf_counter() - ts)
                    if progress:
                        # Progress counts audio actually sent to the model, so the ETA stays honest
                        # when silent segments are skipped.
                        done = min(work_done, work_total) if work_total > 0 else e16 / IN_SR
                        total = work_total if work_total > 0 else audio.duration
                        progress(Progress(k, len(bounds), done, total, time.perf_counter() - t0))
            tmp_path.replace(out_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        stats.elapsed_s = time.perf_counter() - t0
        return stats


def _clip(x: np.ndarray, subtype: str) -> np.ndarray:
    return x if subtype == "FLOAT" else np.clip(x, -1.0, 1.0)
