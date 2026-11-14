"""SidonModel: one 16 kHz mono span in, the same span restored at 48 kHz out."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import weights
from ..audio.dsp import as_numpy
from ..constants import EDGE_PAD_SAMPLES, UPSAMPLE
from ..features import fbank_features
from .base import Backend
from .registry import create_backend


class SidonModel:
    """Runtime-independent wrapper: edge padding, features, backend call, trimming.

    backend: "auto" | "coreml" | "torchscript" | "eager" | any registered name, or a Backend instance.
    Extra keyword options go to the backend (precision="float16" for Core ML, device="mps" for eager).
    """

    def __init__(
        self,
        backend: str | Backend = "auto",
        weights_dir: str | Path | None = None,
        num_threads: int | None = None,
        **options,
    ):
        if num_threads:
            options.setdefault("threads", num_threads)
            try:  # torch-based backends; harmless when torch is not installed
                import torch

                torch.set_num_threads(num_threads)
            except ImportError:
                pass
        if isinstance(backend, str):
            backend = create_backend(backend, weights.resolve(weights_dir), **options)
        self.backend = backend

    @property
    def description(self) -> str:
        return self.backend.description

    @property
    def max_input_samples(self) -> int | None:
        """Longest 16 kHz input (excluding edge padding) the backend accepts per call."""
        if self.backend.max_frames is None:
            return None
        return self.backend.max_frames * 320 - 2 * EDGE_PAD_SAMPLES

    def enhance(self, wav16k) -> np.ndarray:
        """1-D float @16 kHz (NumPy array or torch tensor) -> 1-D float32 @48 kHz of length exactly 3 * len(wav16k)."""
        wav16k = as_numpy(wav16k)
        n = wav16k.shape[0]
        padded = np.pad(wav16k, (EDGE_PAD_SAMPLES, EDGE_PAD_SAMPLES))
        out = self.backend(fbank_features(padded))

        start = EDGE_PAD_SAMPLES * UPSAMPLE
        target = start + n * UPSAMPLE
        if out.shape[0] < target:
            out = np.pad(out, (0, target - out.shape[0]))
        return np.ascontiguousarray(out[start:target])
