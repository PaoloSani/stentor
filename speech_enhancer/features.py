"""Torch-only replica of SeamlessM4TFeatureExtractor (w2v-BERT 2.0 input features).

Avoids depending on `transformers` (and on a network download of its config) at runtime.
"""

from __future__ import annotations

import torch
import torchaudio

SAMPLE_RATE = 16_000
NUM_MEL_BINS = 80
STRIDE = 2  # frames stacked together -> 50 Hz, 160-dim features
EDGE_PAD = 160  # samples padded on each side, as in the reference inference code


def fbank_features(wav16k: torch.Tensor) -> torch.Tensor:
    """Return w2v-BERT input features of shape (1, frames // 2, 160) for a 1-D 16 kHz waveform."""
    wav = torch.nn.functional.pad(wav16k.reshape(1, -1).float(), (EDGE_PAD, EDGE_PAD))
    feats = torchaudio.compliance.kaldi.fbank(
        waveform=wav,
        sample_frequency=SAMPLE_RATE,
        num_mel_bins=NUM_MEL_BINS,
        frame_length=25,
        frame_shift=10,
        dither=0.0,
        preemphasis_coefficient=0.97,
        remove_dc_offset=True,
        window_type="povey",
        use_energy=False,
        energy_floor=1.192092955078125e-07,
    )
    # Per-mel-bin utterance normalisation.
    mean = feats.mean(0, keepdim=True)
    var = feats.var(0, keepdim=True)
    feats = (feats - mean) / torch.sqrt(var + 1e-5)

    n = (feats.shape[0] // STRIDE) * STRIDE
    return feats[:n].reshape(1, n // STRIDE, NUM_MEL_BINS * STRIDE)
