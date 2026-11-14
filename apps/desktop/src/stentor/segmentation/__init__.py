"""VAD-driven, user-editable segmentation: VAD -> probabilities -> speech regions -> cut points."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..constants import IN_SR
from .cuts import STRATEGIES, CutStrategy, greedy_pause_cuts
from .model import Segmentation, SegmentationParams
from .regions import normalise_regions, overlap, pauses, quietest_point, speech_regions


def segment_from_probs(
    probs: np.ndarray,
    duration: float,
    params: SegmentationParams | None = None,
    hop_s: float = 512 / IN_SR,
    strategy: CutStrategy = greedy_pause_cuts,
) -> Segmentation:
    """Place cuts from precomputed VAD probabilities (instant: lets the GUI re-segment live)."""
    params = params or SegmentationParams()
    min_pause_s = params.min_pause_ms / 1000
    speech = speech_regions(probs, params.vad_threshold, min_pause_s, hop_s)
    cuts = strategy(duration, pauses(speech, duration, min_pause_s), probs, hop_s, params)
    return Segmentation(duration=duration, cuts=cuts, speech=speech, vad_probs=probs, params=params, vad_hop_s=hop_s)


def segment_audio(
    wav16k,
    params: SegmentationParams | None = None,
    progress: Callable[[float], None] | None = None,
    vad=None,
    strategy: CutStrategy = greedy_pause_cuts,
) -> Segmentation:
    """Run a VAD (Silero by default, the energy detector when Silero/torch are not installed) and place cuts."""
    if vad is None:
        from ..vad import EnergyVAD, SileroVAD

        vad = SileroVAD() if SileroVAD.available() else EnergyVAD()
    probs = vad.probabilities(wav16k, progress)
    return segment_from_probs(probs, len(wav16k) / IN_SR, params, vad.hop_s, strategy)


__all__ = [
    "STRATEGIES",
    "CutStrategy",
    "Segmentation",
    "SegmentationParams",
    "greedy_pause_cuts",
    "normalise_regions",
    "overlap",
    "pauses",
    "quietest_point",
    "segment_audio",
    "segment_from_probs",
    "speech_regions",
]
