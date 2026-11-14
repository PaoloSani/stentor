"""The contract every inference runtime implements.

A backend maps model input features to 48 kHz audio. Everything around it (padding, feature
extraction, trimming, chunking, gating) is runtime independent and lives in `SidonModel` and
`stentor.render`, so a new runtime (ONNX Runtime, MLX, CUDA, ...) only has to implement this.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from ..constants import HOP


@runtime_checkable
class Backend(Protocol):
    name: str  # registry key, e.g. "torchscript"
    description: str  # human readable, e.g. "Core ML on GPU (float32)"
    max_frames: int | None  # longest feature sequence accepted per call (None = unbounded)

    def __call__(self, features: np.ndarray) -> np.ndarray:
        """features: float32 (1, T, 160) at 50 Hz -> float32 1-D waveform at 48 kHz, ~T * 960 samples."""
        ...


class BackendFactory(Protocol):
    """What the registry stores: usually the backend class itself."""

    def __call__(self, weights_dir: Path, **options) -> Backend: ...

    @staticmethod
    def available(weights_dir: Path, **options) -> bool: ...


def decode_windowed(
    decoder: Callable[[np.ndarray], np.ndarray], hidden: np.ndarray, window: int, context: int
) -> np.ndarray:
    """Run a fixed-shape vocoder over (1, C, T) hidden states as overlapping windows.

    The vocoder is purely convolutional with a receptive field of about +-10 frames, so with
    `context` >= 10 frames on each side the stitched result equals a single full-length call.
    `decoder` takes (1, C, window + 2 * context) and returns that many frames of audio.
    """
    t = hidden.shape[-1]
    hidden = np.pad(hidden, ((0, 0), (0, 0), (context, context + (-t) % window)))
    frames = window + 2 * context
    out = np.empty(((t + (-t) % window) * HOP,), dtype=np.float32)
    for s in range(0, t, window):
        wav = decoder(np.ascontiguousarray(hidden[..., s:s + frames])).reshape(-1)
        out[s * HOP:(s + window) * HOP] = wav[context * HOP:(context + window) * HOP]
    return out[: t * HOP]
