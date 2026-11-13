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


class Enhancer:
    def __init__(self, model: SidonModel, context_s: float = 0.5, crossfade_ms: float = 40.0):
        self.model = model
        self.ctx16 = int(context_s * IN_SR)
        self.half16 = int(crossfade_ms / 2000 * IN_SR)  # half crossfade, in 16 kHz samples
        assert self.ctx16 >= self.half16
        n = 2 * self.half16 * UPSAMPLE
        ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)  # equal-gain Hann ramp
        self.fade_in = ramp.astype(np.float32)
        self.fade_out = (1.0 - ramp).astype(np.float32)

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

    def _enhance_range(self, wav16k, start16: int, end16: int, n16: int) -> np.ndarray:
        """Enhance [start16-half, end16+half] (clipped) using extra model context on both sides."""
        lo = max(0, start16 - self.ctx16)
        hi = min(n16, end16 + self.ctx16)
        y = self.model.enhance(wav16k[lo:hi]).numpy()
        a = max(0, start16 - self.half16)
        b = min(n16, end16 + self.half16)
        return y[(a - lo) * UPSAMPLE:(b - lo) * UPSAMPLE]

    def enhance_segment(self, audio: LoadedAudio, start_s: float, end_s: float) -> np.ndarray:
        """Enhance one region for preview; returns exactly [start_s, end_s] at 48 kHz."""
        n16 = audio.num_samples
        s, e = int(round(start_s * IN_SR)), int(round(end_s * IN_SR))
        piece = self._enhance_range(audio.wav16k, s, e, n16)
        head = (s - max(0, s - self.half16)) * UPSAMPLE
        return piece[head:head + (e - s) * UPSAMPLE]

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
        bounds = self._bounds16(segmentation, n16)
        ov = 2 * self.half16 * UPSAMPLE  # overlap length at 48 kHz
        stats = RunStats(audio_s=audio.duration, elapsed_s=0.0)
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
                    piece = self._enhance_range(audio.wav16k, s16, e16, n16)
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
                        progress(Progress(k, len(bounds), e16 / IN_SR, audio.duration, time.perf_counter() - t0))
            tmp_path.replace(out_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        stats.elapsed_s = time.perf_counter() - t0
        return stats


def _clip(x: np.ndarray, subtype: str) -> np.ndarray:
    return x if subtype == "FLOAT" else np.clip(x, -1.0, 1.0)
