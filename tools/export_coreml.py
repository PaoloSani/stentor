"""Export the eager Sidon modules to Core ML packages for Apple Silicon.

Run after tools/convert_torchscript.py (from the repo root):
    .venv/bin/python tools/export_coreml.py            # float32 + float16
    .venv/bin/python tools/export_coreml.py float32

Outputs sidon_weights/coreml/{feature_extractor,decoder}_{float32,float16}.mlpackage

- Feature extractor: flexible length, 1 .. MAX_FRAMES frames at 50 Hz.
- Decoder: fixed window of DEC_WINDOW + 2 * DEC_CONTEXT frames. The vocoder is purely
  convolutional with a receptive field of about +-10 frames, so decoding a long sequence as
  overlapping fixed windows is exact (and keeps a single compiled Metal graph).
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from speech_enhancer.model import DEC_CONTEXT, DEC_WINDOW, FE_MAX_FRAMES  # noqa: E402
from speech_enhancer._generated.decoder import Decoder  # noqa: E402
from speech_enhancer._generated.feature_extractor import FeatureExtractor  # noqa: E402

EAGER = ROOT / "sidon_weights" / "eager"
OUT = ROOT / "sidon_weights" / "coreml"


class _FE(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.m = FeatureExtractor()
        self.m.load_state_dict(torch.load(EAGER / "feature_extractor.pt"))

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.m(features)["last_hidden_state"]


def _decoder() -> torch.nn.Module:
    m = Decoder()
    m.load_state_dict(torch.load(EAGER / "decoder.pt"))
    return m


def export(precision: str) -> None:
    import coremltools as ct

    prec = {"float32": ct.precision.FLOAT32, "float16": ct.precision.FLOAT16}[precision]
    common = dict(compute_precision=prec, minimum_deployment_target=ct.target.macOS14, convert_to="mlprogram")
    OUT.mkdir(parents=True, exist_ok=True)

    with torch.inference_mode(False), torch.no_grad():
        t = time.perf_counter()
        fe = torch.jit.trace(_FE().eval(), torch.randn(1, 600, 160))
        ml = ct.convert(
            fe,
            inputs=[ct.TensorType(name="features", shape=(1, ct.RangeDim(1, FE_MAX_FRAMES, default=600), 160))],
            outputs=[ct.TensorType(name="hidden")],
            **common,
        )
        ml.save(OUT / f"feature_extractor_{precision}.mlpackage")
        print(f"feature_extractor_{precision}: {time.perf_counter() - t:.0f}s")

        t = time.perf_counter()
        frames = DEC_WINDOW + 2 * DEC_CONTEXT
        dec = torch.jit.trace(_decoder().eval(), torch.randn(1, 1024, frames))
        ml = ct.convert(
            dec,
            inputs=[ct.TensorType(name="hidden", shape=(1, 1024, frames))],
            outputs=[ct.TensorType(name="wav")],
            **common,
        )
        ml.save(OUT / f"decoder_{precision}.mlpackage")
        print(f"decoder_{precision}: {time.perf_counter() - t:.0f}s")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    for p in sys.argv[1:] or ["float32", "float16"]:
        export(p)
