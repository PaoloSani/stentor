"""Sidon inference (feature predictor + vocoder) with two interchangeable backends.

- "coreml" (default on Apple Silicon): Core ML packages exported by tools/export_coreml.py,
  run on the GPU. About 2-3x faster than the CPU path and lighter on memory; float32 is
  numerically identical to the reference, float16 is lighter with inaudible differences.
  The Neural Engine is deliberately not used: its fp16 arithmetic degrades the vocoder.
- "torchscript": the original release files on CPU. Always available, used as fallback.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import torch

from .features import fbank_features

IN_SR = 16_000
OUT_SR = 48_000
UPSAMPLE = OUT_SR // IN_SR  # 3 output samples per input sample
HOP = 960  # 48 kHz samples per 50 Hz feature frame
EDGE_PAD_SAMPLES = IN_SR // 4  # 0.25 s of zeros on each side of every model call

# Core ML shapes (shared with tools/export_coreml.py).
FE_MAX_FRAMES = 1500  # 30 s per model call (segment + context + padding)
DEC_WINDOW = 100  # frames produced per vocoder call (2 s)
DEC_CONTEXT = 16  # extra frames on each side; receptive field is ~10 frames

DEFAULT_WEIGHTS_DIR = Path(
    os.environ.get("SIDON_WEIGHTS_DIR", Path(__file__).resolve().parent.parent / "sidon_weights")
)

HF_REPO = "sarulab-speech/sidon-v0.1"
EXPECTED_SHA256 = {
    "feature_extractor_cpu.pt": "fd9abc906a9048b3c047bd3d246a25f6485d09c2d6bb85e098f527f844efc019",
    "decoder_cpu.pt": "34dcc80fab75bd1336369ba5b2063f6da475887aa824db94b495c4059c5fdea4",
}


class _TorchScriptBackend:
    name = "torchscript"

    def __init__(self, weights_dir: Path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # torch.jit.load deprecation
            self.fe = self._load(weights_dir / "feature_extractor_cpu.pt")
            self.dec = self._load(weights_dir / "decoder_cpu.pt")

    @staticmethod
    def _load(path: Path) -> torch.jit.ScriptModule:
        if not path.exists():
            raise FileNotFoundError(f"Missing Sidon weights: {path}. Download it from https://huggingface.co/{HF_REPO}")
        try:
            return torch.jit.load(str(path), map_location="cpu").eval()
        except RuntimeError as exc:
            raise RuntimeError(
                f"Could not load {path} (corrupted or truncated?). Re-download it from https://huggingface.co/{HF_REPO}"
            ) from exc

    def __call__(self, features: torch.Tensor) -> np.ndarray:
        hidden = self.fe(features)["last_hidden_state"]
        return self.dec(hidden.transpose(1, 2)).reshape(-1).numpy()


class _CoreMLBackend:
    name = "coreml"

    def __init__(self, weights_dir: Path, precision: str):
        import coremltools as ct

        folder = weights_dir / "coreml"
        paths = [folder / f"feature_extractor_{precision}.mlpackage", folder / f"decoder_{precision}.mlpackage"]
        missing = [p for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"Missing Core ML models {[p.name for p in missing]}: run tools/convert_torchscript.py "
                "then tools/export_coreml.py"
            )
        units = ct.ComputeUnit.CPU_AND_GPU
        self.fe = ct.models.MLModel(str(paths[0]), compute_units=units)
        self.dec = ct.models.MLModel(str(paths[1]), compute_units=units)

    def __call__(self, features: torch.Tensor) -> np.ndarray:
        if features.shape[1] > FE_MAX_FRAMES:
            raise ValueError(f"Segment too long for Core ML model ({features.shape[1] / 50:.1f}s > {FE_MAX_FRAMES / 50:.0f}s)")
        hidden = self.fe.predict({"features": features.numpy()})["hidden"]  # (1, T, 1024)
        hidden = np.ascontiguousarray(hidden.transpose(0, 2, 1), dtype=np.float32)  # (1, 1024, T)

        # Overlapping fixed-size windows (exact: context exceeds the receptive field).
        t = hidden.shape[-1]
        hidden = np.pad(hidden, ((0, 0), (0, 0), (DEC_CONTEXT, DEC_CONTEXT + (-t) % DEC_WINDOW)))
        frames = DEC_WINDOW + 2 * DEC_CONTEXT
        out = np.empty(((t + (-t) % DEC_WINDOW) * HOP,), dtype=np.float32)
        for s in range(0, t, DEC_WINDOW):
            wav = self.dec.predict({"hidden": hidden[..., s:s + frames]})["wav"].reshape(-1)
            out[s * HOP:(s + DEC_WINDOW) * HOP] = wav[DEC_CONTEXT * HOP:(DEC_CONTEXT + DEC_WINDOW) * HOP]
        return out[: t * HOP]


def coreml_available(weights_dir: str | Path = DEFAULT_WEIGHTS_DIR, precision: str = "float32") -> bool:
    try:
        import coremltools  # noqa: F401
    except ImportError:
        return False
    folder = Path(weights_dir) / "coreml"
    return all((folder / f"{n}_{precision}.mlpackage").exists() for n in ("feature_extractor", "decoder"))


class SidonModel:
    """Enhance a single 16 kHz mono segment into 48 kHz restored speech."""

    def __init__(
        self,
        weights_dir: str | Path = DEFAULT_WEIGHTS_DIR,
        backend: str = "auto",  # "auto" | "coreml" | "torchscript"
        precision: str = "float32",  # Core ML only: "float32" | "float16"
        num_threads: int | None = None,
    ):
        weights_dir = Path(weights_dir)
        if num_threads:
            torch.set_num_threads(num_threads)
        if backend == "auto":
            backend = "coreml" if coreml_available(weights_dir, precision) else "torchscript"
        if backend == "coreml":
            self.backend = _CoreMLBackend(weights_dir, precision)
            self.description = f"Core ML on GPU ({precision})"
        elif backend == "torchscript":
            self.backend = _TorchScriptBackend(weights_dir)
            self.description = f"TorchScript on CPU ({torch.get_num_threads()} threads)"
        else:
            raise ValueError(f"Unknown backend {backend!r}")

    @torch.inference_mode()
    def enhance(self, wav16k: torch.Tensor) -> torch.Tensor:
        """1-D float tensor @16 kHz -> 1-D float tensor @48 kHz of length 3 * len(wav16k)."""
        wav16k = wav16k.reshape(-1).float()
        n = wav16k.shape[0]
        # Zero padding on both sides: without it the vocoder produces a burst on the last
        # few milliseconds (the reference code padded 1.5 s at the end for the same reason).
        padded = torch.nn.functional.pad(wav16k, (EDGE_PAD_SAMPLES, EDGE_PAD_SAMPLES))
        out = self.backend(fbank_features(padded))

        start = EDGE_PAD_SAMPLES * UPSAMPLE
        target = start + n * UPSAMPLE
        if out.shape[0] < target:
            out = np.pad(out, (0, target - out.shape[0]))
        return torch.from_numpy(np.ascontiguousarray(out[start:target]))
