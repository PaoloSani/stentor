"""Cut placement strategies: where to split a recording into model-sized segments.

A strategy is any callable `(duration, pauses, probs, hop_s, params) -> sorted cut times`.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .model import SegmentationParams
from .regions import quietest_point


class CutStrategy(Protocol):
    def __call__(
        self,
        duration: float,
        pauses: list[tuple[float, float]],
        probs: np.ndarray,
        hop_s: float,
        params: SegmentationParams,
    ) -> list[float]: ...


def greedy_pause_cuts(
    duration: float, pauses: list[tuple[float, float]], probs: np.ndarray, hop_s: float, p: SegmentationParams
) -> list[float]:
    """Walk left to right; in each [min_s, max_s] window take the pause that best trades length
    (capped at 1.5 s) against distance from target_s. No pause: cut at the least speech-like moment."""
    cuts: list[float] = []
    pos = 0.0
    while duration - pos > p.max_s:
        lo, hi = pos + p.min_s, pos + p.max_s
        best, best_score = None, -np.inf
        for g0, g1 in pauses:
            centre = (g0 + g1) / 2
            if lo <= centre <= hi:
                pause = min(g1 - g0, 1.5)
                score = pause - 0.6 * abs(centre - (pos + p.target_s)) / p.target_s
                if score > best_score:
                    best, best_score = centre, score
        if best is None:
            best = quietest_point(probs, pos + p.target_s * 0.75, hi, hop_s)
        cuts.append(round(best, 3))
        pos = best

    # Absorb a too-short tail into the previous segment if that keeps it within max_s.
    if cuts and duration - cuts[-1] < p.min_s:
        prev = cuts[-2] if len(cuts) > 1 else 0.0
        if duration - prev <= p.max_s:
            cuts.pop()
    return cuts


STRATEGIES: dict[str, CutStrategy] = {"greedy": greedy_pause_cuts}
