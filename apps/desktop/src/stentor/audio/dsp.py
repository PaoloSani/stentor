"""NumPy signal processing used at runtime (no PyTorch needed).

`resample` reproduces torchaudio.functional.resample (windowed-sinc, Hann, lowpass_filter_width=6,
rolloff=0.99, float32 kernel) and `highpass_biquad` torchaudio.functional.highpass_biquad
(RBJ biquad, Q = 0.707, output clamped to [-1, 1]), so results match the torch pipeline to
float32 rounding.
"""

from __future__ import annotations

import math

import numpy as np

LOWPASS_FILTER_WIDTH = 6
ROLLOFF = 0.99


def _sinc_kernel(orig: int, new: int) -> tuple[np.ndarray, int]:
    """Polyphase kernel (new, 2 * width + orig) in float32, as torchaudio builds it for float32 input."""
    base_freq = min(orig, new) * ROLLOFF
    width = math.ceil(LOWPASS_FILTER_WIDTH * orig / base_freq)
    f32 = np.float32
    idx = (np.arange(-width, width + orig, dtype=f32) / f32(orig))[None, :]
    t = (np.arange(0, -new, -1, dtype=f32) / f32(new))[:, None] + idx
    t = np.clip(t * f32(base_freq), -LOWPASS_FILTER_WIDTH, LOWPASS_FILTER_WIDTH).astype(f32)
    window = (np.cos(t * f32(math.pi / LOWPASS_FILTER_WIDTH / 2)) ** 2).astype(f32)
    t = (t * f32(math.pi)).astype(f32)
    with np.errstate(divide="ignore", invalid="ignore"):
        sinc = np.where(t == 0, f32(1.0), np.sin(t) / t).astype(f32)
    return (sinc * window * f32(base_freq / orig)).astype(f32), width


def resample(x: np.ndarray, orig_sr: int, new_sr: int) -> np.ndarray:
    """1-D float32 signal from `orig_sr` to `new_sr` (output length ceil(len * new / orig))."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if orig_sr == new_sr:
        return x.copy()
    g = math.gcd(int(orig_sr), int(new_sr))
    orig, new = int(orig_sr) // g, int(new_sr) // g
    kernel, width = _sinc_kernel(orig, new)
    padded = np.pad(x, (width, width + orig))
    frames = np.lib.stride_tricks.sliding_window_view(padded, kernel.shape[1])[::orig]
    out = (frames @ kernel.T).reshape(-1)
    return np.ascontiguousarray(out[: math.ceil(new * x.shape[0] / orig)], dtype=np.float32)


def highpass_biquad(x: np.ndarray, sample_rate: int, cutoff_hz: float, q: float = 0.707) -> np.ndarray:
    from scipy.signal import lfilter

    w0 = 2 * math.pi * cutoff_hz / sample_rate
    alpha = math.sin(w0) / 2 / q
    c = math.cos(w0)
    b = np.array([(1 + c) / 2, -1 - c, (1 + c) / 2])
    a = np.array([1 + alpha, -2 * c, 1 - alpha])
    y = lfilter(b / a[0], a / a[0], np.asarray(x, dtype=np.float64).reshape(-1))
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def as_numpy(x) -> np.ndarray:
    """Accept NumPy arrays or (CPU) torch tensors and return a contiguous 1-D float32 array."""
    if hasattr(x, "detach"):  # torch.Tensor, without importing torch
        x = x.detach().cpu().numpy()
    return np.ascontiguousarray(np.asarray(x, dtype=np.float32).reshape(-1))
