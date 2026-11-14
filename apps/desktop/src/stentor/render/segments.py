"""Cut-based rendering: one model call per segment, equal-gain crossfades at the cuts.

This is the strategy of the legacy `speech_enhancer.Enhancer` and produces identical output.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..audio import LoadedAudio, open_output
from ..constants import IN_SR, OUT_SR, UPSAMPLE
from ..models import SidonModel
from ..segmentation import Segmentation
from .base import Cancelled, Progress, RunStats, clip_for
from .gating import active_regions16, gate_mask, hann_ramp


class SegmentRenderer:
    """Segment-wise enhancement along the segmentation's cut points.

    speech_only=True (default): only the speech regions, widened by `speech_pad_s` and merged
    across gaps shorter than `min_gap_s`, are sent to the model; everything else is written as
    digital silence (with `gate_fade_ms` ramps at region edges). Segments without speech are
    skipped entirely, and inside a segment the model only runs from the first to the last
    speech region (plus `context_s` of real audio on each side).
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
        if self.ctx16 < self.half16:
            raise ValueError("context_s must cover half the crossfade")
        ramp = hann_ramp(2 * self.half16 * UPSAMPLE)
        self.fade_in = ramp
        self.fade_out = 1.0 - ramp
        self.speech_only = speech_only
        self.pad16 = int(speech_pad_s * IN_SR)
        self.gate_fade48 = int(gate_fade_ms / 1000 * OUT_SR)
        self.min_gap16 = int(min_gap_s * IN_SR)

    # ---- building blocks ----------------------------------------------------------------
    def active_regions16(self, speech: list[tuple[float, float]], n16: int) -> list[tuple[int, int]]:
        return active_regions16(speech, n16, self.pad16, self.min_gap16)

    def _enhance_window(self, wav16k, a16: int, b16: int, n16: int) -> np.ndarray:
        """Enhanced audio for exactly [a16, b16) at 48 kHz, with model context on both sides."""
        lo = max(0, a16 - self.ctx16)
        hi = min(n16, b16 + self.ctx16)
        y = self.model.enhance(wav16k[lo:hi])
        return y[(a16 - lo) * UPSAMPLE:(b16 - lo) * UPSAMPLE]

    def _render(self, wav16k, a16: int, b16: int, n16: int, active) -> tuple[np.ndarray, float]:
        """Output for [a16, b16) and the seconds of audio actually sent to the model."""
        if not self.speech_only:
            return self._enhance_window(wav16k, a16, b16, n16), (b16 - a16) / IN_SR
        mask = gate_mask(a16, b16, active, self.gate_fade48)
        if mask is None:
            return np.zeros((b16 - a16) * UPSAMPLE, dtype=np.float32), 0.0
        nz = np.flatnonzero(mask)
        lo16 = a16 + nz[0] // UPSAMPLE
        hi16 = min(b16, a16 + nz[-1] // UPSAMPLE + 1)
        out = np.zeros_like(mask)
        out[(lo16 - a16) * UPSAMPLE:(hi16 - a16) * UPSAMPLE] = self._enhance_window(wav16k, lo16, hi16, n16)
        return out * mask, (hi16 - lo16) / IN_SR

    def bounds16(self, seg: Segmentation, n16: int) -> list[tuple[int, int]]:
        """Segment bounds in 16 kHz samples; a cut closer than one crossfade to its neighbour is dropped."""
        cuts = [int(round(c * IN_SR)) for c in seg.cuts]
        clean: list[int] = []
        for c in cuts:
            prev = clean[-1] if clean else 0
            if c - prev > 2 * self.half16 and n16 - c > 2 * self.half16:
                clean.append(c)
        edges = [0, *clean, n16]
        return list(zip(edges[:-1], edges[1:]))

    # ---- Renderer protocol --------------------------------------------------------------
    def plan(self, segmentation: Segmentation, n16: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]], float]:
        """Segment bounds, active regions and the seconds of audio the model will process."""
        bounds = self.bounds16(segmentation, n16)
        active = self.active_regions16(segmentation.speech, n16)
        if not self.speech_only:
            return bounds, active, n16 / IN_SR
        work = sum(min(n16, e + self.half16) - max(0, s - self.half16) for s, e in active) / IN_SR
        return bounds, active, work

    def plan_work_s(self, segmentation: Segmentation, n16: int) -> float:
        return self.plan(segmentation, n16)[2]

    def preview(self, audio: LoadedAudio, start_s: float, end_s: float, speech: list | None = None) -> np.ndarray:
        n16 = audio.num_samples
        s, e = int(round(start_s * IN_SR)), int(round(end_s * IN_SR))
        active = self.active_regions16(speech or [], n16)
        return self._render(audio.wav16k, s, e, n16, active)[0]

    def run(
        self,
        audio: LoadedAudio,
        segmentation: Segmentation,
        out_path: str | Path,
        subtype: str = "PCM_24",
        progress: Callable[[Progress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RunStats:
        n16 = audio.num_samples
        bounds, active, work_total = self.plan(segmentation, n16)
        ov = 2 * self.half16 * UPSAMPLE  # overlap length at 48 kHz
        stats = RunStats(audio_s=audio.duration, elapsed_s=0.0)
        work_done = 0.0
        t0 = time.perf_counter()

        with open_output(out_path, subtype) as out:
            tail: np.ndarray | None = None
            for k, (s16, e16) in enumerate(bounds):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                ts = time.perf_counter()
                a16, b16 = max(0, s16 - self.half16), min(n16, e16 + self.half16)
                piece, worked = self._render(audio.wav16k, a16, b16, n16, active)
                work_done += worked
                last = k == len(bounds) - 1

                if tail is not None:  # crossfade with the previous segment around the cut
                    out.write(clip_for(subtype, tail * self.fade_out + piece[:ov] * self.fade_in))
                    piece = piece[ov:]
                if last:
                    out.write(clip_for(subtype, piece))
                else:
                    out.write(clip_for(subtype, piece[:-ov]))
                    tail = piece[-ov:]

                stats.segment_times.append(time.perf_counter() - ts)
                if progress:
                    # Progress counts audio actually sent to the model, so the ETA stays honest
                    # when silent segments are skipped.
                    done = min(work_done, work_total) if work_total > 0 else e16 / IN_SR
                    total = work_total if work_total > 0 else audio.duration
                    progress(Progress(k, len(bounds), done, total, time.perf_counter() - t0))

        stats.elapsed_s = time.perf_counter() - t0
        return stats
