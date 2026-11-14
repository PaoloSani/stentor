"""Speech gating: which samples go to the model, and the gain mask applied to its output."""

from __future__ import annotations

import numpy as np

from ..constants import IN_SR, UPSAMPLE


def hann_ramp(n: int) -> np.ndarray:
    """Rising half-Hann of length n (0 -> 1, exclusive). 1 - ramp is the matching fade-out."""
    return (0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)).astype(np.float32)


def active_regions16(
    speech: list[tuple[float, float]], n16: int, pad16: int, min_gap16: int
) -> list[tuple[int, int]]:
    """Speech regions (seconds) widened by `pad16` and merged across gaps < `min_gap16` (16 kHz samples)."""
    out: list[list[int]] = []
    for a, b in speech:
        lo = max(0, int(a * IN_SR) - pad16)
        hi = min(n16, int(b * IN_SR) + pad16)
        if out and lo - out[-1][1] < min_gap16:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(a, b) for a, b in out]


def gate_mask(a16: int, b16: int, active: list[tuple[int, int]], fade48: int) -> np.ndarray | None:
    """48 kHz gain for [a16, b16): 1 inside active regions, 0 outside, Hann ramps of `fade48`
    samples placed inside each region. None if the range contains no speech.

    The mask is defined on absolute time, so overlapping ranges (crossfades) see the same gain.
    """
    hits = [(s, e) for s, e in active if s < b16 and e > a16]
    if not hits:
        return None
    A, B = a16 * UPSAMPLE, b16 * UPSAMPLE
    mask = np.zeros(B - A, dtype=np.float32)
    for rs, re in hits:
        r0, r1 = rs * UPSAMPLE, re * UPSAMPLE
        n = min(fade48, (r1 - r0) // 2)
        idx = np.arange(max(A, r0), min(B, r1))
        g = np.ones(len(idx), dtype=np.float32)
        if n > 0:
            ramp = hann_ramp(n)
            head = idx < r0 + n
            g[head] = ramp[idx[head] - r0]
            tail = idx >= r1 - n
            g[tail] = ramp[::-1][idx[tail] - (r1 - n)]
        mask[idx - A] = np.maximum(mask[idx - A], g)
    return mask
