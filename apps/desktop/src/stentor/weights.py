"""Where the Sidon weights live, and how to fetch them.

Layout of a weights directory:

    <weights>/feature_extractor_cpu.pt, decoder_cpu.pt     TorchScript release (Hugging Face)
    <weights>/eager/{feature_extractor,decoder}.pt         state dicts (stentor export eager)
    <weights>/coreml/{feature_extractor,decoder}_<p>.mlpackage   (stentor export coreml)
    <weights>/onnx/{feature_extractor,decoder}.onnx              (stentor export onnx)

The directory is `$STENTOR_WEIGHTS_DIR` if set, else `~/.cache/stentor/weights`.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

HF_REPO = "sarulab-speech/sidon-v0.1"
HF_URL = f"https://huggingface.co/{HF_REPO}/resolve/main"


@dataclass(frozen=True)
class WeightFile:
    name: str
    sha256: str
    cuda: bool = False


RELEASE_FILES = [
    WeightFile("feature_extractor_cpu.pt", "fd9abc906a9048b3c047bd3d246a25f6485d09c2d6bb85e098f527f844efc019"),
    WeightFile("decoder_cpu.pt", "34dcc80fab75bd1336369ba5b2063f6da475887aa824db94b495c4059c5fdea4"),
    WeightFile("feature_extractor_cuda.pt", "c3739c332da4ce00cc9019a328bcb19ee8f863ac5eb0b52386672772aab836ce", cuda=True),
    WeightFile("decoder_cuda.pt", "a789c71f54ca7db4b28becdc87c5e8b9260cb568cca462d502c54900db74a1cc", cuda=True),
]


def default_weights_dir() -> Path:
    env = os.environ.get("STENTOR_WEIGHTS_DIR")
    return Path(env).expanduser() if env else Path.home() / ".cache" / "stentor" / "weights"


def resolve(weights_dir: str | Path | None) -> Path:
    return Path(weights_dir).expanduser() if weights_dir else default_weights_dir()


def torchscript_paths(weights_dir: str | Path | None = None) -> tuple[Path, Path]:
    d = resolve(weights_dir)
    return d / "feature_extractor_cpu.pt", d / "decoder_cpu.pt"


def eager_paths(weights_dir: str | Path | None = None) -> tuple[Path, Path]:
    d = resolve(weights_dir) / "eager"
    return d / "feature_extractor.pt", d / "decoder.pt"


def coreml_paths(weights_dir: str | Path | None = None, precision: str = "float32") -> tuple[Path, Path]:
    d = resolve(weights_dir) / "coreml"
    return d / f"feature_extractor_{precision}.mlpackage", d / f"decoder_{precision}.mlpackage"


def onnx_paths(weights_dir: str | Path | None = None) -> tuple[Path, Path]:
    d = resolve(weights_dir) / "onnx"
    return d / "feature_extractor.onnx", d / "decoder.onnx"


def sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def missing_hint(path: Path) -> str:
    return (
        f"Missing Sidon weights: {path}. Run `stentor weights download` "
        f"(or set STENTOR_WEIGHTS_DIR to a folder that has them)."
    )


def download(weights_dir: str | Path | None = None, cuda: bool = False, verbose: bool = True) -> Path:
    """Fetch the TorchScript release from Hugging Face, verifying SHA-256. Existing good files are kept."""
    d = resolve(weights_dir)
    d.mkdir(parents=True, exist_ok=True)
    for wf in RELEASE_FILES:
        if wf.cuda and not cuda:
            continue
        dest = d / wf.name
        if dest.exists() and sha256(dest) == wf.sha256:
            if verbose:
                print(f"ok        {wf.name}")
            continue
        if verbose:
            print(f"download  {wf.name}")
        part = dest.with_name(dest.name + ".part")
        _fetch(f"{HF_URL}/{wf.name}", part, verbose)
        if sha256(part) != wf.sha256:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum mismatch for {wf.name}")
        part.replace(dest)
    return d


def _fetch(url: str, dest: Path, verbose: bool) -> None:
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while block := r.read(1 << 20):
            f.write(block)
            done += len(block)
            if verbose and total:
                print(f"\r          {done / total:6.1%} of {total / 1e6:.0f} MB", end="", file=sys.stderr, flush=True)
        if verbose and total:
            print(file=sys.stderr)


def status(weights_dir: str | Path | None = None) -> dict[str, bool]:
    """Which artefacts are present (no hashing)."""
    d = resolve(weights_dir)
    out = {wf.name: (d / wf.name).exists() for wf in RELEASE_FILES}
    out |= {f"eager/{p.name}": p.exists() for p in eager_paths(d)}
    for precision in ("float32", "float16"):
        out |= {f"coreml/{p.name}": p.exists() for p in coreml_paths(d, precision)}
    return out
