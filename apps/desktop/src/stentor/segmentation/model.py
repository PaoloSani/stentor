"""The editable segmentation of a recording: cut points plus speech regions.

A `Segmentation` is a list of cut points (seconds) that tile the whole recording, plus the
speech regions the renderer is allowed to process. Both are user-editable (the GUI adds,
moves and removes them) and round-trip through JSON. The JSON format is shared with the
legacy speech_enhancer package.
"""

from __future__ import annotations

import json
from bisect import bisect_left, insort
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .regions import quietest_point

DEFAULT_HOP_S = 512 / 16_000  # Silero frame


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
    speech: list[tuple[float, float]] = field(default_factory=list)  # regions the renderer processes
    vad_probs: np.ndarray | None = None  # per VAD frame, for display / forced cuts / re-thresholding
    params: SegmentationParams = field(default_factory=SegmentationParams)
    vad_hop_s: float = DEFAULT_HOP_S

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

    def split(self, segment_index: int, t: float | None = None) -> None:
        """Split a segment at `t`, or at its quietest point (lowest VAD probability)."""
        start, end = self.segments[segment_index]
        if t is None:
            if self.vad_probs is not None:
                t = quietest_point(self.vad_probs, start + 0.5, end - 0.5, self.vad_hop_s)
            else:
                t = (start + end) / 2
        self.add_cut(t)

    def nearest_cut(self, t: float) -> int | None:
        if not self.cuts:
            return None
        i = bisect_left(self.cuts, t)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(self.cuts)]
        return min(candidates, key=lambda j: abs(self.cuts[j] - t))

    # ---- persistence ---------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"duration": self.duration, "cuts": self.cuts, "speech": self.speech, "params": asdict(self.params)}

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, data: dict) -> Segmentation:
        return cls(
            duration=data["duration"],
            cuts=sorted(data["cuts"]),
            speech=[tuple(s) for s in data.get("speech", [])],
            params=SegmentationParams(**data.get("params", {})),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> Segmentation:
        return cls.from_dict(json.loads(Path(path).read_text()))
