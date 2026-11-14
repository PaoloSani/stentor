"""Reading audio of any length as 16 kHz mono, and writing 48 kHz output atomically."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from ..constants import IN_SR, OUT_SR
from .dsp import resample
from .preprocess import prepare

BLOCK_SECONDS = 60
CONTEXT_SECONDS = 0.5  # resampling context on each side of a block


@dataclass
class LoadedAudio:
    wav16k: np.ndarray  # 1-D float32 at 16 kHz (preprocessed unless load_audio(preprocess=False))
    source_sr: int
    channels: int
    duration: float  # seconds

    @property
    def num_samples(self) -> int:
        return self.wav16k.shape[0]


def decode_with_system_tool(path: Path, tmpdir: str | Path) -> Path:
    """Decode formats libsndfile can't read (m4a/aac/mp4/...) to a float WAV in `tmpdir`."""
    out = Path(tmpdir) / "decoded.wav"
    if shutil.which("afconvert"):  # ships with macOS
        cmd = ["afconvert", "-f", "WAVE", "-d", "LEF32", str(path), str(out)]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-c:a", "pcm_f32le", str(out)]
    else:
        raise RuntimeError(f"Unsupported audio format and no decoder (afconvert/ffmpeg) available: {path}")
    subprocess.run(cmd, check=True)
    return out


def read_mono_16k(path: str | Path) -> tuple[np.ndarray, int, int]:
    """Read a file block by block, mix to mono and resample to 16 kHz.

    Blocks are whole seconds (an exact number of 16 kHz samples) resampled with half a second of
    context on each side, so memory stays flat on multi-hour files.
    """
    info = sf.info(str(path))
    sr, channels, total = info.samplerate, info.channels, info.frames
    block = BLOCK_SECONDS * sr
    ctx = int(CONTEXT_SECONDS * sr)

    pieces: list[np.ndarray] = []
    with sf.SoundFile(str(path)) as f:
        for start in range(0, total, block):
            lo = max(0, start - ctx)
            hi = min(total, start + block + ctx)
            f.seek(lo)
            data = f.read(hi - lo, dtype="float32", always_2d=True).mean(axis=1)
            x = np.ascontiguousarray(data, dtype=np.float32)
            if sr != IN_SR:
                x = resample(x, sr, IN_SR)
            head = int(round((start - lo) * IN_SR / sr))
            n_out = int(round((min(start + block, total) - start) * IN_SR / sr))
            pieces.append(x[head:head + n_out].copy())
            del x, data
    return (np.concatenate(pieces) if pieces else np.zeros(0, np.float32)), sr, channels


def load_audio(path: str | Path, preprocess: bool = True) -> LoadedAudio:
    """Load any audio file as 16 kHz mono; by default high-passed and peak-normalised (see preprocess)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such audio file: {path}")
    try:
        sf.info(str(path))
        wav, sr, channels = read_mono_16k(path)
    except (sf.LibsndfileError, RuntimeError):
        with tempfile.TemporaryDirectory() as tmp:
            wav, sr, channels = read_mono_16k(decode_with_system_tool(path, tmp))
    if preprocess:
        wav = prepare(wav)
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    return LoadedAudio(wav16k=wav, source_sr=sr, channels=channels, duration=wav.shape[0] / IN_SR)


@contextmanager
def open_output(path: str | Path, subtype: str = "PCM_24", samplerate: int = OUT_SR) -> Iterator[sf.SoundFile]:
    """Mono WAV writer that only appears at `path` once complete (written to `<path>.part` first)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    try:
        with sf.SoundFile(str(tmp), "w", samplerate, 1, subtype=subtype, format="WAV") as out:
            yield out
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
