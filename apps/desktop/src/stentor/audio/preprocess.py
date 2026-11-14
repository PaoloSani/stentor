"""Conditioning applied to the 16 kHz signal before segmentation and the model.

Kept apart from I/O so experiments can swap it (loudness normalisation, denoise pre-pass, ...).
"""

from __future__ import annotations

import numpy as np

from ..constants import IN_SR
from .dsp import as_numpy, highpass_biquad

HIGHPASS_HZ = 50.0
PEAK = 0.9


def highpass(wav16k, cutoff_hz: float = HIGHPASS_HZ) -> np.ndarray:
    return highpass_biquad(as_numpy(wav16k), IN_SR, cutoff_hz)


def peak_normalize(wav, peak: float = PEAK) -> np.ndarray:
    x = as_numpy(wav)
    current = float(np.abs(x).max()) if x.size else 0.0
    return (x * np.float32(peak / current)).astype(np.float32) if current > 0 else x


def prepare(wav16k) -> np.ndarray:
    """Default conditioning: 50 Hz high-pass, then peak-normalise to 0.9."""
    return peak_normalize(highpass(wav16k))
