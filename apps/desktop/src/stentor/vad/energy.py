"""Level-based detector with no model and no extra dependency.

Same idea as VoiceDetector in the Swift app (20 ms frames, 10 ms hop, threshold relative to
full scale of the peak-normalised signal), expressed as a probability so it plugs into the
shared hysteresis/cut logic: p = sigmoid((level_dB - threshold_dB) / slope_dB), i.e. 0.5 exactly
at the threshold. Good for clean voice-only material; Silero is better with ambience.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..audio.dsp import as_numpy
from ..constants import IN_SR

FRAME = 320  # 20 ms
HOP = 160  # 10 ms


class EnergyVAD:
    name = "energy"
    hop_s = HOP / IN_SR

    def __init__(self, threshold_db: float = -45.0, slope_db: float = 3.0):
        self.threshold_db = threshold_db
        self.slope_db = slope_db

    def levels_db(self, wav16k) -> np.ndarray:
        x = as_numpy(wav16k)
        if x.shape[0] < FRAME:
            return np.zeros(0, dtype=np.float32)
        frames = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::HOP]
        return (10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)).astype(np.float32)

    def probabilities(self, wav16k, progress: Callable[[float], None] | None = None) -> np.ndarray:
        db = self.levels_db(wav16k)
        probs = 1.0 / (1.0 + np.exp(-(db - self.threshold_db) / self.slope_db))
        if progress:
            progress(1.0)
        return probs.astype(np.float32)
