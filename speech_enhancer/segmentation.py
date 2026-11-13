"""VAD-driven, user-editable segmentation of long recordings.

A `Segmentation` is a list of cut points (seconds) that tile the whole recording. Cuts are
placed in pauses detected by Silero VAD, so the model never sees a boundary in the middle
of a word. The GUI edits the cut list directly (add / move / remove), and the result can be
saved to and loaded from JSON.
"""

from __future__ import annotations

import json
from bisect import bisect_left, insort
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import torch

SR = 16_000
VAD_WINDOW = 512  # samples per Silero frame at 16 kHz (32 ms)
VAD_HOP_S = VAD_WINDOW / SR


@dataclass
class SegmentationParams:
    target_s: float = 12.0  # preferred segment length (attention cost is quadratic: keep it short)
    max_s: float = 20.0  # hard upper bound per segment
    min_s: float = 3.0  # avoid tiny segments (per-segment feature normalisation needs context)
    vad_threshold: float = 0.5
    min_pause_ms: int = 250  # shortest pause considered a valid cut location


@dataclass
class Segmentation:
    duration: float
    cuts: list[float] = field(default_factory=list)  # sorted, strictly inside (0, duration)
    speech: list[tuple[float, float]] = field(default_factory=list)  # VAD regions, for display
    vad_probs: Optional[np.ndarray] = None  # per 32 ms frame, for display / forced cuts
    params: SegmentationParams = field(default_factory=SegmentationParams)

    # ---- derived view -------------------------------------------------------------
    @property
    def segments(self) -> list[tuple[float, float]]:
        bounds = [0.0, *self.cuts, self.duration]
        return list(zip(bounds[:-1], bounds[1:]))

    def __len__(self) -> int:
        return len(self.cuts) + 1

    # ---- editing (used by the GUI) -------------------------------------------------
    def add_cut(self, t: float) -> None:
        t = round(float(t), 3)
        if 0.0 < t < self.duration and t not in self.cuts:
            insort(self.cuts, t)

    def remove_cut(self, index: int) -> None:
        del self.cuts[index]

    def move_cut(self, index: int, t: float) -> None:
        lo = self.cuts[index - 1] if index > 0 else 0.0
        hi = self.cuts[index + 1] if index + 1 < len(self.cuts) else self.duration
        self.cuts[index] = round(min(max(float(t), lo + 0.05), hi - 0.05), 3)

    def merge(self, segment_index: int) -> None:
        """Merge segment `segment_index` with the following one."""
        if segment_index < len(self.cuts):
            self.remove_cut(segment_index)

    def split(self, segment_index: int, t: Optional[float] = None) -> None:
        """Split a segment at `t`, or at its quietest point (lowest VAD probability)."""
        start, end = self.segments[segment_index]
        if t is None:
            t = _quietest_point(self.vad_probs, start + 0.5, end - 0.5) if self.vad_probs is not None else (start + end) / 2
        self.add_cut(t)

    def nearest_cut(self, t: float) -> Optional[int]:
        if not self.cuts:
            return None
        i = bisect_left(self.cuts, t)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(self.cuts)]
        return min(candidates, key=lambda j: abs(self.cuts[j] - t))

    # ---- persistence ---------------------------------------------------------------
    def to_json(self, path: str | Path) -> None:
        data = {
            "duration": self.duration,
            "cuts": self.cuts,
            "speech": self.speech,
            "params": asdict(self.params),
        }
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> "Segmentation":
        data = json.loads(Path(path).read_text())
        return cls(
            duration=data["duration"],
            cuts=sorted(data["cuts"]),
            speech=[tuple(s) for s in data.get("speech", [])],
            params=SegmentationParams(**data.get("params", {})),
        )


# ---------------------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------------------
_VAD_MODEL = None


def _vad_model():
    global _VAD_MODEL
    if _VAD_MODEL is None:
        from silero_vad import load_silero_vad

        _VAD_MODEL = load_silero_vad()
    return _VAD_MODEL


@torch.inference_mode()
def vad_probabilities(wav16k: torch.Tensor, progress: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """Speech probability for each 32 ms frame."""
    model = _vad_model()
    model.reset_states()
    n = wav16k.shape[0] // VAD_WINDOW
    probs = np.empty(n, dtype=np.float32)
    report_every = max(1, n // 100)
    for i in range(n):
        frame = wav16k[i * VAD_WINDOW:(i + 1) * VAD_WINDOW]
        probs[i] = model(frame.unsqueeze(0), SR).item()
        if progress and i % report_every == 0:
            progress(i / n)
    if progress:
        progress(1.0)
    return probs


def _speech_regions(probs: np.ndarray, threshold: float, min_pause_s: float) -> list[tuple[float, float]]:
    """Hysteresis thresholding of VAD probabilities into speech regions (seconds)."""
    on, off = threshold, max(threshold - 0.15, 0.01)
    regions: list[list[float]] = []
    active = False
    for i, p in enumerate(probs):
        t = i * VAD_HOP_S
        if not active and p >= on:
            if regions and t - regions[-1][1] < min_pause_s:
                regions[-1][1] = t + VAD_HOP_S  # pause too short: continue previous region
            else:
                regions.append([t, t + VAD_HOP_S])
            active = True
        elif active:
            if p < off:
                active = False
            else:
                regions[-1][1] = t + VAD_HOP_S
    return [(round(a, 3), round(b, 3)) for a, b in regions]


def _quietest_point(probs: np.ndarray, start: float, end: float) -> float:
    """Time (s) of the lowest smoothed VAD probability within [start, end]."""
    i0, i1 = int(start / VAD_HOP_S), int(end / VAD_HOP_S)
    if i1 <= i0 + 1:
        return (start + end) / 2
    smooth = np.convolve(probs, np.ones(7) / 7, mode="same")
    return (i0 + int(np.argmin(smooth[i0:i1]))) * VAD_HOP_S + VAD_HOP_S / 2


def _place_cuts(duration: float, gaps: list[tuple[float, float]], probs: np.ndarray, p: SegmentationParams) -> list[float]:
    """Greedy cut placement: prefer long pauses near the target length, never exceed max_s."""
    cuts: list[float] = []
    pos = 0.0
    while duration - pos > p.max_s:
        lo, hi = pos + p.min_s, pos + p.max_s
        best, best_score = None, -np.inf
        for g0, g1 in gaps:
            centre = (g0 + g1) / 2
            if lo <= centre <= hi:
                pause = min(g1 - g0, 1.5)
                score = pause - 0.6 * abs(centre - (pos + p.target_s)) / p.target_s
                if score > best_score:
                    best, best_score = centre, score
        if best is None:  # no pause in range: cut at the least speech-like moment
            best = _quietest_point(probs, pos + p.target_s * 0.75, hi)
        cuts.append(round(best, 3))
        pos = best

    # Absorb a too-short tail into the previous segment if that keeps it within max_s.
    if cuts and duration - cuts[-1] < p.min_s:
        prev = cuts[-2] if len(cuts) > 1 else 0.0
        if duration - prev <= p.max_s:
            cuts.pop()
    return cuts


def segment_audio(
    wav16k: torch.Tensor,
    params: Optional[SegmentationParams] = None,
    progress: Optional[Callable[[float], None]] = None,
) -> Segmentation:
    params = params or SegmentationParams()
    duration = wav16k.shape[0] / SR
    probs = vad_probabilities(wav16k, progress)
    speech = _speech_regions(probs, params.vad_threshold, params.min_pause_ms / 1000)

    # Pauses between speech regions, plus leading/trailing silence.
    bounds = [(0.0, 0.0), *speech, (duration, duration)]
    gaps = [(a[1], b[0]) for a, b in zip(bounds[:-1], bounds[1:]) if b[0] - a[1] >= params.min_pause_ms / 1000]

    cuts = _place_cuts(duration, gaps, probs, params)
    return Segmentation(duration=duration, cuts=cuts, speech=speech, vad_probs=probs, params=params)
