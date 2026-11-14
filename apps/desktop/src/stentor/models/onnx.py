"""ONNX Runtime backend: the cross-platform runtime (Windows, Linux, macOS).

Execution providers are picked in this order, keeping only those this onnxruntime build has:
DirectML (any GPU on Windows, `onnxruntime-directml`), CUDA (NVIDIA, `onnxruntime-gpu`), CPU.
Pass `device="cpu"` (or "dml", "cuda") to force one. On macOS the Core ML backend is faster.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .. import weights
from .base import decode_windowed

OPSET = 17
DEC_WINDOW = 100  # frames produced per vocoder call (2 s)
DEC_CONTEXT = 16  # extra frames on each side; receptive field is ~10 frames

_PROVIDERS = {
    "dml": "DmlExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "cpu": "CPUExecutionProvider",
}
_AUTO = ["dml", "cuda", "cpu"]


def folder_paths(folder: str | Path) -> tuple[Path, Path]:
    d = Path(folder)
    return d / "feature_extractor.onnx", d / "decoder.onnx"


def pick_providers(device: str = "auto") -> list[str]:
    import onnxruntime as ort

    have = set(ort.get_available_providers())
    keys = _AUTO if device == "auto" else [device, "cpu"]
    chosen = [_PROVIDERS[k] for k in keys if _PROVIDERS[k] in have]
    return list(dict.fromkeys(chosen)) or ["CPUExecutionProvider"]


class OnnxBackend:
    name = "onnx"
    max_frames = None

    def __init__(
        self,
        weights_dir: Path,
        device: str = "auto",
        threads: int | None = None,
        folder: str | Path | None = None,
        **_options,
    ):
        """`folder`: a directory holding feature_extractor.onnx and decoder.onnx (default: <weights_dir>/onnx)."""
        import onnxruntime as ort

        fe_path, dec_path = folder_paths(folder) if folder else weights.onnx_paths(weights_dir)
        missing = [p for p in (fe_path, dec_path) if not p.exists()]
        if missing:
            raise FileNotFoundError(f"Missing ONNX models {[p.name for p in missing]}: run `stentor export onnx`")
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads or os.environ.get("STENTOR_THREADS"):
            so.intra_op_num_threads = int(threads or os.environ["STENTOR_THREADS"])
        providers = pick_providers(device)
        if "DmlExecutionProvider" in providers:  # DirectML wants these
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.fe = ort.InferenceSession(str(fe_path), so, providers=providers)
        self.dec = ort.InferenceSession(str(dec_path), so, providers=providers)
        used = self.fe.get_providers()[0].replace("ExecutionProvider", "")
        self.description = f"ONNX Runtime ({used})"

    @staticmethod
    def available(weights_dir: Path, folder: str | Path | None = None, **_options) -> bool:
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False
        return all(p.exists() for p in (folder_paths(folder) if folder else weights.onnx_paths(weights_dir)))

    def __call__(self, features: np.ndarray) -> np.ndarray:
        hidden = self.fe.run(None, {"features": np.ascontiguousarray(features, dtype=np.float32)})[0]  # (1, T, 1024)
        hidden = np.ascontiguousarray(hidden.transpose(0, 2, 1), dtype=np.float32)  # (1, 1024, T)
        return decode_windowed(lambda h: self.dec.run(None, {"hidden": h})[0], hidden, DEC_WINDOW, DEC_CONTEXT)
