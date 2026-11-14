"""Waveform envelopes and visible-window spectrograms (NumPy; turned into QImages by the editor)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class Peaks:
    """Min/max envelope at a coarse block size, for fast waveform drawing at any zoom level."""

    BLOCK = 256

    def __init__(self, samples: np.ndarray, rate: int):
        self.samples, self.rate = samples, rate
        n = samples.shape[0]
        nb = (n + self.BLOCK - 1) // self.BLOCK
        padded = np.pad(samples, (0, nb * self.BLOCK - n), mode="edge") if n else np.zeros(self.BLOCK, np.float32)
        blocks = padded.reshape(-1, self.BLOCK)
        self.mins, self.maxs = blocks.min(axis=1), blocks.max(axis=1)

    def columns(self, t0: float, t1: float, width: int) -> tuple[np.ndarray, np.ndarray]:
        """(min, max) per pixel column for [t0, t1]."""
        n = self.samples.shape[0]
        if width <= 0 or t1 <= t0 or n == 0:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        spp = (t1 - t0) * self.rate / width
        edges = np.floor(t0 * self.rate + np.arange(width + 1) * spp).astype(np.int64)
        lo = np.clip(edges[:-1], 0, n)
        hi = np.clip(np.maximum(edges[1:], edges[:-1] + 1), 0, n)
        valid = hi > lo
        mn = np.zeros(width, np.float32)
        mx = np.zeros(width, np.float32)
        if spp < self.BLOCK * 2:
            src_mn = src_mx = self.samples
            a, b = lo, hi
        else:
            src_mn, src_mx = self.mins, self.maxs
            a = lo // self.BLOCK
            b = np.minimum(len(self.mins), (hi + self.BLOCK - 1) // self.BLOCK)
            valid &= b > a
        idx = np.where(valid)[0]
        if idx.size:
            starts = a[idx]
            # reduceat needs strictly usable starts; compute per column with the segment ends
            mn_v = np.minimum.reduceat(src_mn, starts) if starts.size else np.zeros(0)
            mx_v = np.maximum.reduceat(src_mx, starts) if starts.size else np.zeros(0)
            # reduceat reduces up to the next start; columns are contiguous so this matches [a, next a)
            mn[idx], mx[idx] = mn_v, mx_v
            # the last column runs to its own end, not to the end of the array
            last = idx[-1]
            mn[last] = src_mn[a[last]:b[last]].min()
            mx[last] = src_mx[a[last]:b[last]].max()
        return mn, mx


@dataclass
class SpecTile:
    """Spectrogram for an exact time window: column c is the STFT frame centred at t0 + (c + 0.5) * (t1 - t0) / cols."""

    rgba: np.ndarray  # (rows, cols) uint32, 0xAARRGGBB
    t0: float
    t1: float
    source: str  # "A" or "B"


ROWS = 256
MIN_FREQ = 40.0


def _palette() -> np.ndarray:
    """Dark-to-bright palette (indigo -> violet -> rose -> amber -> cream), as 0xFFRRGGBB."""
    stops = np.array([
        (0.00, 0.04, 0.04, 0.07), (0.25, 0.16, 0.10, 0.36), (0.50, 0.55, 0.17, 0.52),
        (0.75, 0.96, 0.47, 0.30), (1.00, 1.00, 0.95, 0.80),
    ])
    v = np.linspace(0, 1, 256)
    rgb = [np.interp(v, stops[:, 0], stops[:, k]) for k in (1, 2, 3)]
    r, g, b = ((c * 255).astype(np.uint32) for c in rgb)
    return (0xFF000000 | (r << 16) | (g << 8) | b).astype(np.uint32)


LUT = _palette()


def spectrogram(samples: np.ndarray, rate: int, t0: float, t1: float, cols: int) -> np.ndarray | None:
    if cols <= 0 or t1 <= t0 or samples.shape[0] < 64:
        return None
    sec_per_col = (t1 - t0) / cols
    # shorter windows when zoomed in (sharper onsets), longer when zoomed out (finer pitch)
    nfft = 256 if sec_per_col < 0.002 else 512 if sec_per_col < 0.006 else 1024 if sec_per_col < 0.03 else 2048
    half = nfft // 2
    centres = np.round((t0 + (np.arange(cols) + 0.5) * sec_per_col) * rate).astype(np.int64)
    padded = np.pad(samples, (nfft, nfft))
    idx = centres[:, None] - half + nfft + np.arange(nfft)[None, :]
    np.clip(idx, 0, padded.shape[0] - 1, out=idx)
    win = np.hanning(nfft).astype(np.float32)
    mags = np.empty((cols, half), np.float32)
    for s in range(0, cols, 512):  # bounded memory
        frames = padded[idx[s:s + 512]] * win
        mags[s:s + 512] = np.abs(np.fft.rfft(frames, axis=1)[:, :half]) ** 2
    max_freq = rate / 2
    edges = MIN_FREQ * (max_freq / MIN_FREQ) ** (np.arange(ROWS + 1) / ROWS) / rate * nfft
    lo = np.minimum(half - 2, edges[:-1])
    hi = np.minimum(half - 1, edges[1:])
    out = np.empty((cols, ROWS), np.float32)
    narrow = hi - lo < 1
    x = (lo + hi) / 2
    i = x.astype(np.int64)
    f = (x - i).astype(np.float32)
    interp = mags[:, i] * (1 - f) + mags[:, np.minimum(half - 1, i + 1)] * f
    out[:, narrow] = interp[:, narrow]
    for r in np.where(~narrow)[0]:
        out[:, r] = mags[:, int(lo[r]):int(hi[r]) + 1].max(axis=1)
    db = 10 * np.log10(out / (nfft * nfft / 4) + 1e-12)
    v = np.clip((db + 100) / 90, 0, 1)
    img = LUT[(v * 255).astype(np.int64)]
    return np.ascontiguousarray(img.T[::-1])  # rows top = high frequencies
