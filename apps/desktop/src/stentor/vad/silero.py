"""Silero VAD (extra: `pip install stentor-engine[silero]`). The default detector."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..audio.dsp import as_numpy
from ..constants import IN_SR

WINDOW = 512  # samples per Silero frame at 16 kHz (32 ms)

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        try:
            from silero_vad import load_silero_vad
        except ImportError as exc:
            raise ImportError(
                "Silero VAD is not installed: `pip install 'stentor-engine[silero]'` (or use --vad energy)"
            ) from exc
        _MODEL = load_silero_vad()
    return _MODEL


class SileroVAD:
    name = "silero"
    hop_s = WINDOW / IN_SR

    @staticmethod
    def available() -> bool:
        try:
            import silero_vad  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def probabilities(self, wav16k, progress: Callable[[float], None] | None = None) -> np.ndarray:
        import torch  # only needed for Silero; keeps `import stentor` torch-free

        with torch.inference_mode():
            return self._probabilities(torch, wav16k, progress)

    def _probabilities(self, torch, wav16k, progress) -> np.ndarray:
        model = _model()
        model.reset_states()
        wav16k = torch.as_tensor(as_numpy(wav16k))
        n = wav16k.shape[0] // WINDOW
        probs = np.empty(n, dtype=np.float32)
        report_every = max(1, n // 100)
        for i in range(n):
            frame = wav16k[i * WINDOW:(i + 1) * WINDOW]
            probs[i] = model(frame.unsqueeze(0), IN_SR).item()
            if progress and i % report_every == 0:
                progress(i / n)
        if progress:
            progress(1.0)
        return probs
