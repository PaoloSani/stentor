"""From per-frame VAD probabilities to speech regions (seconds), and region utilities."""

from __future__ import annotations

import numpy as np

SMOOTH_S = 0.224  # smoothing window for quietest-point search (7 Silero frames)


def speech_regions(probs: np.ndarray, threshold: float, min_pause_s: float, hop_s: float) -> list[tuple[float, float]]:
    """Hysteresis thresholding (on at `threshold`, off 0.15 below); pauses shorter than `min_pause_s` are bridged."""
    on, off = threshold, max(threshold - 0.15, 0.01)
    regions: list[list[float]] = []
    active = False
    for i, p in enumerate(probs):
        t = i * hop_s
        if not active and p >= on:
            if regions and t - regions[-1][1] < min_pause_s:
                regions[-1][1] = t + hop_s  # pause too short: continue previous region
            else:
                regions.append([t, t + hop_s])
            active = True
        elif active:
            if p < off:
                active = False
            else:
                regions[-1][1] = t + hop_s
    return [(round(a, 3), round(b, 3)) for a, b in regions]


def pauses(speech: list[tuple[float, float]], duration: float, min_pause_s: float) -> list[tuple[float, float]]:
    """Gaps between speech regions (plus leading/trailing silence) at least `min_pause_s` long."""
    bounds = [(0.0, 0.0), *speech, (duration, duration)]
    return [(a[1], b[0]) for a, b in zip(bounds[:-1], bounds[1:]) if b[0] - a[1] >= min_pause_s]


def quietest_point(probs: np.ndarray, start: float, end: float, hop_s: float) -> float:
    """Time (s) of the lowest smoothed VAD probability within [start, end]."""
    i0, i1 = int(start / hop_s), int(end / hop_s)
    if i1 <= i0 + 1:
        return (start + end) / 2
    k = max(1, round(SMOOTH_S / hop_s))
    smooth = np.convolve(probs, np.ones(k) / k, mode="same")
    return (i0 + int(np.argmin(smooth[i0:i1]))) * hop_s + hop_s / 2


def normalise_regions(regions: list, duration: float, min_len: float = 0.05) -> list[tuple[float, float]]:
    """Clamp to [0, duration], sort, merge overlaps, drop slivers (for user-edited regions)."""
    clean = sorted((max(0.0, min(float(a), float(b))), min(duration, max(float(a), float(b)))) for a, b in regions)
    out: list[list[float]] = []
    for a, b in clean:
        if b - a < min_len:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def overlap(a: float, b: float, regions: list[tuple[float, float]]) -> float:
    """Seconds of [a, b] covered by `regions`."""
    return sum(max(0.0, min(b, r1) - max(a, r0)) for r0, r1 in regions)
