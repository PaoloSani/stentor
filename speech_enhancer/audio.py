"""Memory-friendly audio loading (any length) and output writing."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

MODEL_SR = 16_000
BLOCK_SECONDS = 60
CONTEXT_SECONDS = 0.5  # resampling context on each side of a block
HIGHPASS_HZ = 50.0
PEAK = 0.9


@dataclass
class LoadedAudio:
    wav16k: torch.Tensor  # 1-D float32, high-passed, peak-normalised
    source_sr: int
    channels: int
    duration: float  # seconds

    @property
    def num_samples(self) -> int:
        return self.wav16k.shape[0]


def _decode_with_system_tool(path: Path, tmpdir: str) -> Path:
    """Decode formats libsndfile can't read (m4a/aac/mp4/...) to a float WAV."""
    out = Path(tmpdir) / "decoded.wav"
    if shutil.which("afconvert"):  # ships with macOS
        cmd = ["afconvert", "-f", "WAVE", "-d", "LEF32", str(path), str(out)]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-c:a", "pcm_f32le", str(out)]
    else:
        raise RuntimeError(f"Unsupported audio format and no decoder available: {path}")
    subprocess.run(cmd, check=True)
    return out


def _read_mono_16k(path: Path) -> tuple[torch.Tensor, int, int]:
    """Read a file block by block, mix to mono and resample to 16 kHz."""
    info = sf.info(str(path))
    sr, channels, total = info.samplerate, info.channels, info.frames
    block = BLOCK_SECONDS * sr  # whole seconds -> maps to an exact number of 16 kHz samples
    ctx = int(CONTEXT_SECONDS * sr)

    pieces: list[torch.Tensor] = []
    with sf.SoundFile(str(path)) as f:
        for start in range(0, total, block):
            lo = max(0, start - ctx)
            hi = min(total, start + block + ctx)
            f.seek(lo)
            data = f.read(hi - lo, dtype="float32", always_2d=True).mean(axis=1)
            x = torch.from_numpy(np.ascontiguousarray(data))
            if sr != MODEL_SR:
                x = torchaudio.functional.resample(x, sr, MODEL_SR)
            head = int(round((start - lo) * MODEL_SR / sr))
            n_out = int(round((min(start + block, total) - start) * MODEL_SR / sr))
            pieces.append(x[head:head + n_out].clone())
            del x, data
    return torch.cat(pieces), sr, channels


def load_audio(path: str | Path) -> LoadedAudio:
    """Load any audio file as 16 kHz mono, high-passed at 50 Hz and peak-normalised to 0.9."""
    path = Path(path)
    try:
        sf.info(str(path))
        wav, sr, channels = _read_mono_16k(path)
    except (sf.LibsndfileError, RuntimeError):
        with tempfile.TemporaryDirectory() as tmp:
            wav, sr, channels = _read_mono_16k(_decode_with_system_tool(path, tmp))

    wav = torchaudio.functional.highpass_biquad(wav, MODEL_SR, HIGHPASS_HZ)
    peak = float(wav.abs().max())
    if peak > 0:
        wav = wav * (PEAK / peak)
    return LoadedAudio(wav16k=wav.contiguous(), source_sr=sr, channels=channels, duration=wav.shape[0] / MODEL_SR)
