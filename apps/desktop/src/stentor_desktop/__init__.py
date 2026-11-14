"""Stentor for Windows and Linux (Qt / PySide6 on top of stentor-engine's ONNX runtime)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stentor-desktop")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"
