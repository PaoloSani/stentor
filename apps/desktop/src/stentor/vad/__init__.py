from __future__ import annotations

from .base import VAD
from .energy import EnergyVAD
from .silero import SileroVAD

VADS: dict[str, type] = {"silero": SileroVAD, "energy": EnergyVAD}


def get_vad(name: str = "auto", **options) -> VAD:
    """"auto" is Silero when silero-vad and torch are installed, otherwise the energy detector."""
    if name == "auto":
        name = "silero" if SileroVAD.available() else "energy"
    try:
        return VADS[name](**options)
    except KeyError:
        raise ValueError(f"Unknown VAD {name!r}; known: {sorted(VADS)}") from None


__all__ = ["VAD", "VADS", "EnergyVAD", "SileroVAD", "get_vad"]
