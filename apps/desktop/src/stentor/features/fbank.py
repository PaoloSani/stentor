"""w2v-BERT 2.0 input features: a NumPy replica of transformers' SeamlessM4TFeatureExtractor.

Kaldi fbank (80 mel bins, 25 ms / 10 ms, povey window, pre-emphasis 0.97, DC removal, power
spectrum, log mel energies) as computed by torchaudio.compliance.kaldi.fbank, per-mel-bin
utterance normalisation, then pairs of frames stacked into 160-dim vectors at 50 Hz.
No PyTorch or `transformers` at runtime. The Swift app mirrors this in Fbank.swift.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from ..audio.dsp import as_numpy
from ..constants import FEATURE_DIM, IN_SR

NUM_MEL_BINS = 80
STRIDE = FEATURE_DIM // NUM_MEL_BINS  # 2 frames stacked together
EDGE_PAD = 160  # samples padded on each side, as in the reference inference code
WINDOW = 400  # 25 ms
SHIFT = 160  # 10 ms
NFFT = 512
PREEMPH = 0.97
LOW_FREQ = 20.0
EPS = np.float32(1.1920928955078125e-07)  # float32 machine epsilon (Kaldi's log floor)


@lru_cache(maxsize=1)
def _povey_window() -> np.ndarray:
    n = np.arange(WINDOW, dtype=np.float64)
    return ((0.5 - 0.5 * np.cos(2 * math.pi * n / (WINDOW - 1))) ** 0.85).astype(np.float32)


@lru_cache(maxsize=1)
def _mel_banks() -> np.ndarray:
    """(80, 257) triangular filters in the Kaldi mel domain; the Nyquist column stays zero."""

    def mel(f):
        return 1127.0 * np.log(1.0 + np.asarray(f, dtype=np.float64) / 700.0)

    bins = NFFT // 2
    low, high = mel(LOW_FREQ), mel(IN_SR / 2)
    delta = (high - low) / (NUM_MEL_BINS + 1)
    m = np.arange(NUM_MEL_BINS, dtype=np.float64)[:, None]
    left, center, right = low + m * delta, low + (m + 1) * delta, low + (m + 2) * delta
    x = mel(IN_SR / NFFT * np.arange(bins, dtype=np.float64))[None, :]
    banks = np.maximum(0.0, np.minimum((x - left) / (center - left), (right - x) / (right - center)))
    return np.pad(banks, ((0, 0), (0, 1))).astype(np.float32)


def kaldi_fbank(wav16k) -> np.ndarray:
    """Log-mel filterbank, shape (frames, 80), after the reference's 160-sample edge padding."""
    x = np.pad(as_numpy(wav16k), (EDGE_PAD, EDGE_PAD))
    if x.shape[0] < WINDOW:
        return np.zeros((0, NUM_MEL_BINS), dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, WINDOW)[::SHIFT].astype(np.float64)
    frames = frames - frames.mean(axis=1, keepdims=True)  # DC removal
    prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)  # replicate-padded x[i-1]
    frames = (frames - PREEMPH * prev) * _povey_window()
    power = np.abs(np.fft.rfft(frames, n=NFFT, axis=1)) ** 2
    energies = (power @ _mel_banks().T.astype(np.float64)).astype(np.float32)
    return np.log(np.maximum(energies, EPS))


def normalize_per_bin(feats: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    """Zero mean, unit variance per mel bin over the whole call (unbiased variance)."""
    f = np.asarray(feats, dtype=np.float64)
    mean = f.mean(axis=0, keepdims=True)
    var = f.var(axis=0, ddof=1, keepdims=True) if f.shape[0] > 1 else np.zeros_like(mean)
    return ((f - mean) / np.sqrt(var + eps)).astype(np.float32)


def stack_frames(feats: np.ndarray, stride: int = STRIDE) -> np.ndarray:
    """(frames, 80) -> (1, frames // stride, 80 * stride); an odd last frame is dropped."""
    feats = np.asarray(feats)
    n = (feats.shape[0] // stride) * stride
    return np.ascontiguousarray(feats[:n].reshape(1, n // stride, feats.shape[1] * stride))


def fbank_features(wav16k) -> np.ndarray:
    """Model input features, float32 (1, T, 160) at 50 Hz, for a 1-D 16 kHz waveform."""
    return stack_frames(normalize_per_bin(kaldi_fbank(wav16k)))
