"""Playback of a mono signal with seamless looping (PortAudio through sounddevice)."""

from __future__ import annotations

import threading

import numpy as np


class Player:
    def __init__(self):
        self._lock = threading.Lock()
        self.signal = np.zeros(0, np.float32)
        self.rate = 48_000
        self._pos = 0  # next frame to send
        self._loop: tuple[int, int] | None = None
        self._loop_s: tuple[float, float] | None = None
        self._stream = None
        self.playing = False
        self.error: str | None = None
        self._latency = 0.0

    # ---- state ------------------------------------------------------------------

    @property
    def duration(self) -> float:
        return self.signal.shape[0] / self.rate if self.rate else 0.0

    @property
    def time(self) -> float:
        """Position being heard (what is sent minus the output latency, wrapped inside the loop)."""
        with self._lock:
            t = self._pos / self.rate
            if not self.playing:
                return t
            t -= self._latency
            if self._loop:
                a, b = self._loop[0] / self.rate, self._loop[1] / self.rate
                if t < a and b > a:
                    t = b - (a - t) % (b - a)
            return max(0.0, t)

    def set_signal(self, samples: np.ndarray, rate: int) -> None:
        """Swap what is played (A/B) keeping the position; restarts the stream if the rate changes."""
        t, was = self.time, self.playing
        if was and rate != self.rate:
            self._close()
        with self._lock:
            self.signal = np.ascontiguousarray(samples, dtype=np.float32)
            self.rate = int(rate)
            self._pos = min(int(t * self.rate), self.signal.shape[0])
            if self._loop:
                self._loop = self._loop_frames(self._loop_s)
        if was and self._stream is None:
            self.play()

    def set_loop(self, loop: tuple[float, float] | None) -> None:
        with self._lock:
            self._loop_s = loop
            self._loop = self._loop_frames(loop) if loop else None

    def _loop_frames(self, loop) -> tuple[int, int] | None:
        if not loop:
            return None
        a, b = int(loop[0] * self.rate), int(loop[1] * self.rate)
        b = min(b, self.signal.shape[0])
        return (a, b) if b - a > 32 else None

    def seek(self, t: float) -> None:
        with self._lock:
            self._pos = max(0, min(int(t * self.rate), self.signal.shape[0]))

    # ---- transport ----------------------------------------------------------------

    def play(self, start: float | None = None) -> None:
        if start is not None:
            self.seek(start)
        with self._lock:
            if self._loop and not (self._loop[0] <= self._pos < self._loop[1]):
                self._pos = self._loop[0]
            if not self._loop and self._pos >= self.signal.shape[0]:
                self._pos = 0
        if self._stream is not None:
            return
        try:
            import sounddevice as sd

            self._stream = sd.OutputStream(
                samplerate=self.rate, channels=2, dtype="float32", latency="low",
                callback=self._callback, finished_callback=self._finished,
            )
            self._latency = float(self._stream.latency)
            self.playing = True
            self._stream.start()
            self.error = None
        except Exception as exc:  # no device, PortAudio missing, ...
            self._stream = None
            self.playing = False
            self.error = f"Audio output unavailable: {exc}"

    def pause(self) -> None:
        if self.playing:
            t = self.time
            self._close()
            self.seek(t)

    def _close(self) -> None:
        s, self._stream = self._stream, None
        self.playing = False
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _finished(self) -> None:
        self.playing = False
        self._stream = None

    def _callback(self, out, frames, _time, _status) -> None:
        import sounddevice as sd

        with self._lock:
            x, n = self.signal, self.signal.shape[0]
            filled = 0
            while filled < frames:
                end = self._loop[1] if self._loop else n
                take = min(frames - filled, max(0, end - self._pos))
                if take:
                    out[filled:filled + take, 0] = x[self._pos:self._pos + take]
                    filled += take
                    self._pos += take
                if filled < frames:
                    if self._loop:
                        self._pos = self._loop[0]
                    else:
                        out[filled:, 0] = 0
                        out[:, 1] = out[:, 0]
                        raise sd.CallbackStop
            out[:, 1] = out[:, 0]

    def close(self) -> None:
        self._close()
