"""Stentor engine: Sidon speech restoration for long recordings, with interchangeable runtimes.

    audio -> segmentation (VAD + cuts) -> render (chunking, gating) -> SidonModel -> Backend
"""

from .audio import LoadedAudio, load_audio
from .models import SidonModel, available_backends, register_backend
from .render import SegmentRenderer
from .segmentation import Segmentation, SegmentationParams, segment_audio, segment_from_probs

__version__ = "0.1.0"

__all__ = [
    "LoadedAudio",
    "Segmentation",
    "SegmentationParams",
    "SegmentRenderer",
    "SidonModel",
    "available_backends",
    "load_audio",
    "register_backend",
    "segment_audio",
    "segment_from_probs",
]
