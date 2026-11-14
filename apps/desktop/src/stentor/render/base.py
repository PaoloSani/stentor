"""What a renderer is, plus the progress/stats types every renderer reports."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from ..audio import LoadedAudio
from ..segmentation import Segmentation


@dataclass
class Progress:
    segment: int  # index of the unit (segment / chunk) just finished
    total_segments: int
    audio_done_s: float  # seconds of audio sent to the model so far
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


class Renderer(Protocol):
    """Turns (audio, segmentation) into a full-length 48 kHz output.

    Strategies differ in how they chunk the work for the model (cut-based segments with
    crossfades, fixed-length buckets, overlap-add, ...). All must keep the output exactly
    3x the input length and honour `cancel` between model calls.
    """

    def plan_work_s(self, segmentation: Segmentation, n16: int) -> float:
        """Seconds of audio that will be sent to the model (for progress / ETA)."""
        ...

    def preview(self, audio: LoadedAudio, start_s: float, end_s: float, speech: list | None = None) -> np.ndarray:
        """48 kHz output for exactly [start_s, end_s] (GUI previews)."""
        ...

    def run(
        self,
        audio: LoadedAudio,
        segmentation: Segmentation,
        out_path: str | Path,
        subtype: str = "PCM_24",
        progress: Callable[[Progress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RunStats: ...


def clip_for(subtype: str, x: np.ndarray) -> np.ndarray:
    """Integer PCM clips at full scale; float output keeps overs."""
    return x if subtype == "FLOAT" else np.clip(x, -1.0, 1.0)
