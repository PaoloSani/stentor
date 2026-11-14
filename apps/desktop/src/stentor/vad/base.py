"""The contract for voice activity detectors.

A VAD turns a 16 kHz waveform into a speech probability per frame. Turning probabilities into
regions and cut points is VAD independent (stentor.segmentation), so the GUI can re-threshold
and re-segment instantly without running the detector again.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class VAD(Protocol):
    name: str
    hop_s: float  # seconds per probability frame

    def probabilities(
        self, wav16k: np.ndarray, progress: Callable[[float], None] | None = None
    ) -> np.ndarray:
        """float32 array, one speech probability in [0, 1] per `hop_s` frame."""
        ...
