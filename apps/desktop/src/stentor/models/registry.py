"""Name -> backend lookup, "auto" resolution and third-party plugins.

Built-ins are registered lazily (by import path) so importing stentor never imports
coremltools. External packages can add a backend without touching this repo through the
`stentor.backends` entry-point group:

    [project.entry-points."stentor.backends"]
    onnx = "stentor_onnx:OnnxBackend"
"""

from __future__ import annotations

import importlib
import importlib.util
from importlib.metadata import entry_points
from pathlib import Path

from .base import Backend

_BUILTIN = {
    "coreml": "stentor.models.coreml:CoreMLBackend",
    "torchscript": "stentor.models.torchscript:TorchScriptBackend",
    "eager": "stentor.models.eager:EagerBackend",
    "onnx": "stentor.models.onnx:OnnxBackend",
}
_REGISTRY: dict[str, object] = {}  # name -> class or "module:attr"

# "auto" tries these in order and picks the first one whose artefacts are present.
AUTO_ORDER = ["coreml", "onnx", "torchscript"]


def register_backend(name: str, factory, auto_priority: int | None = None) -> None:
    """Register a backend class (or "module:Class" string). `auto_priority` inserts it into AUTO_ORDER."""
    _REGISTRY[name] = factory
    if auto_priority is not None and name not in AUTO_ORDER:
        AUTO_ORDER.insert(auto_priority, name)


def _present(target) -> bool:
    """False for a built-in whose module is not shipped (e.g. a trimmed, vendored copy of the engine)."""
    if not isinstance(target, str):
        return True
    try:
        return importlib.util.find_spec(target.split(":")[0]) is not None
    except ModuleNotFoundError:
        return False


def available_backends() -> list[str]:
    _load_plugins()
    return sorted(name for name, target in {**_BUILTIN, **_REGISTRY}.items() if _present(target))


def get_backend_class(name: str):
    _load_plugins()
    target = _REGISTRY.get(name, _BUILTIN.get(name))
    if target is None:
        raise ValueError(f"Unknown backend {name!r}; known: {available_backends()}")
    if isinstance(target, str):
        module, attr = target.split(":")
        target = getattr(importlib.import_module(module), attr)
        _REGISTRY[name] = target
    return target


def resolve_auto(weights_dir: Path, **options) -> str:
    for name in AUTO_ORDER:
        try:
            cls = get_backend_class(name)
        except ImportError:
            continue
        if cls.available(weights_dir, **options):
            return name
    return "torchscript"  # its constructor raises a helpful "missing weights" error


def create_backend(name: str, weights_dir: Path, **options) -> Backend:
    if name == "auto":
        name = resolve_auto(weights_dir, **options)
    return get_backend_class(name)(weights_dir, **options)


_plugins_loaded = False


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    for ep in entry_points(group="stentor.backends"):
        _REGISTRY.setdefault(ep.name, ep.value)
