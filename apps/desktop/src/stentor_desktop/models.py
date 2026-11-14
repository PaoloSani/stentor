"""Finding, downloading and loading the ONNX voice model (feature_extractor.onnx + decoder.onnx, ~1 GB)."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

FILES = ("feature_extractor.onnx", "decoder.onnx")

# Release asset with the two ONNX files at the root of the zip. SHA256 is filled in when it is published;
# while it is empty the setup card offers only "Locate Models…".
MODELS_TAG = "models-onnx-1"
MODELS_ZIP = "Stentor-ONNX-float32.zip"
MODELS_URL = os.environ.get(
    "STENTOR_MODELS_URL", f"https://github.com/PaoloSani/stentor/releases/download/{MODELS_TAG}/{MODELS_ZIP}"
)
MODELS_SHA256 = os.environ.get("STENTOR_MODELS_SHA256", "")


def data_dir() -> Path:
    """Per-user application data: %LOCALAPPDATA%\\Stentor, ~/.local/share/stentor, ~/Library/Application Support/Stentor."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Stentor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Stentor"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "stentor"


def install_dir() -> Path:
    return Path(os.environ.get("STENTOR_MODELS_DEST") or data_dir() / "ONNX")


def has_models(folder: str | Path | None) -> bool:
    return bool(folder) and all((Path(folder) / f).is_file() for f in FILES)


def candidates(saved: str | None = None) -> list[Path]:
    dirs: list[Path] = []
    if os.environ.get("STENTOR_MODELS_DIR"):
        dirs.append(Path(os.environ["STENTOR_MODELS_DIR"]))
    if saved:
        dirs.append(Path(saved))
    dirs.append(install_dir())
    if getattr(sys, "frozen", False):  # PyInstaller build with the models next to the executable
        dirs.append(Path(sys.executable).parent / "models")
    weights = Path(os.environ.get("STENTOR_WEIGHTS_DIR") or Path.home() / ".cache" / "stentor" / "weights")
    dirs.append(weights / "onnx")  # stentor-engine's `stentor export onnx`
    p = Path(__file__).resolve()
    for parent in list(p.parents)[:6]:  # development checkout: <repo>/sidon_weights/onnx or <repo>/Models/onnx
        dirs += [parent / "sidon_weights" / "onnx", parent / "Models" / "onnx"]
    return dirs


def locate(saved: str | None = None) -> Path | None:
    return next((d for d in candidates(saved) if has_models(d)), None)


def available_devices() -> list[str]:
    """Execution providers this onnxruntime build offers, as the engine's device names."""
    try:
        import onnxruntime as ort
    except ImportError:
        return []
    have = set(ort.get_available_providers())
    names = {"DmlExecutionProvider": "dml", "CUDAExecutionProvider": "cuda", "CPUExecutionProvider": "cpu"}
    return [v for k, v in names.items() if k in have]


DEVICE_LABELS = {"auto": "Automatic", "dml": "GPU (DirectML)", "cuda": "NVIDIA GPU (CUDA)", "cpu": "CPU"}


def load_model(folder: Path, device: str = "auto"):
    """A stentor SidonModel on ONNX Runtime for the models in `folder`."""
    from stentor.models import SidonModel
    from stentor.models.onnx import OnnxBackend

    return SidonModel(backend=OnnxBackend(folder, device=device, folder=folder))


class Cancelled(Exception):
    pass


class Installer:
    """Download (resumable), verify (SHA-256) and unpack the models into install_dir(), atomically."""

    def __init__(self, url: str = MODELS_URL, sha256: str = MODELS_SHA256, dest: Path | None = None):
        self.url, self.sha256, self.dest = url, sha256, dest or install_dir()
        self._cancel = threading.Event()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.sha256)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
        self._cancel.clear()
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        part = self.dest.parent / (MODELS_ZIP + ".part")
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(self.url, headers={"User-Agent": "Stentor"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:  # server ignored the range: start over
                have = 0
            total = have + int(r.headers.get("Content-Length") or 0)
            with open(part, "ab" if have else "wb") as f:
                done = have
                while chunk := r.read(1 << 20):
                    if self._cancel.is_set():
                        raise Cancelled
                    f.write(chunk)
                    done += len(chunk)
                    progress(done, total)
        h = hashlib.sha256()
        with open(part, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        if self.sha256 and h.hexdigest() != self.sha256.lower():
            part.unlink(missing_ok=True)
            raise RuntimeError("The downloaded model is damaged (checksum mismatch). Please try again.")
        tmp = Path(tempfile.mkdtemp(prefix="models-", dir=self.dest.parent))
        try:
            with zipfile.ZipFile(part) as z:
                for name in z.namelist():
                    if Path(name).name in FILES:
                        with z.open(name) as src, open(tmp / Path(name).name, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 22)
            if not has_models(tmp):
                raise RuntimeError("The model archive does not contain the expected files.")
            if self.dest.exists():
                shutil.rmtree(self.dest)
            tmp.replace(self.dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        part.unlink(missing_ok=True)
        return self.dest
