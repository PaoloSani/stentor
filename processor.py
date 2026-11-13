"""Speech denoising/enhancement processor based on Sidon TorchScript models."""

from __future__ import annotations

import time
from typing import List, Sequence, Tuple, Dict, List, Optional, Union
import warnings

import numpy as np
import torch
import torchaudio
import transformers

PaddingStrategy = Union[bool, str]
ReturnType = Union[torch.Tensor, np.ndarray]


def _pad_batch(
    features: List[torch.Tensor],
    padding_strategy: PaddingStrategy = "longest",
    max_length: Optional[int] = None,
    pad_to_multiple_of: Optional[int] = None,
    padding_value: float = 0.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Pad a list of feature tensors and return an attention mask."""
    if padding_strategy == "longest":
        target_length = max(f.shape[0] for f in features)
    elif max_length is not None:
        target_length = max_length
    else:
        raise ValueError(
            "max_length must be provided when padding_strategy is not 'longest'"
        )

    if pad_to_multiple_of is not None:
        target_length = (
            (target_length + pad_to_multiple_of - 1)
            // pad_to_multiple_of
            * pad_to_multiple_of
        )

    batch_size = len(features)
    feature_dim = features[0].shape[1]
    device = features[0].device

    padded_features = torch.full(
        (batch_size, target_length, feature_dim),
        padding_value,
        dtype=torch.float32,
        device=device,
    )
    attention_mask = torch.zeros(
        (batch_size, target_length),
        dtype=torch.int64,
        device=device,
    )

    for index, feature_tensor in enumerate(features):
        seq_len = feature_tensor.shape[0]
        padded_features[index, :seq_len] = feature_tensor
        attention_mask[index, :seq_len] = 1

    return padded_features, attention_mask


def extract_seamless_m4t_features(
    raw_speech: Union[torch.Tensor, List[float], List[torch.Tensor], List[List[float]]],
    sampling_rate: int = 16000,
    num_mel_bins: int = 80,
    frame_length: int = 25,
    frame_shift: int = 10,
    preemphasis_coefficient: float = 0.97,
    dither: float = 0.0,
    window_type: str = "povey",
    do_normalize_per_mel_bins: bool = True,
    stride: int = 2,
    padding: PaddingStrategy = "longest",
    max_length: Optional[int] = None,
    pad_to_multiple_of: Optional[int] = 2,
    return_tensors: Optional[str] = "pt",
    return_attention_mask: bool = True,
    padding_value: float = 0.0,
    device: str = "cuda",
) -> Dict[str, ReturnType]:
    """Extract SeamlessM4T features using Torch-only operators."""
    if device == "cuda" and not torch.cuda.is_available():
        torch_device = torch.device("cpu")
    else:
        torch_device = torch.device(device)

    if not isinstance(raw_speech, list):
        raw_speech = [raw_speech]

    processed_speech = [
        torch.as_tensor(sample, dtype=torch.float32, device=torch_device)
        for sample in raw_speech
    ]

    features: List[torch.Tensor] = []
    for waveform in processed_speech:
        if waveform.ndim > 1:
            waveform = waveform[0]
        waveform_tensor = waveform.unsqueeze(0)
        feature = torchaudio.compliance.kaldi.fbank(
            waveform=waveform_tensor,
            sample_frequency=sampling_rate,
            num_mel_bins=num_mel_bins,
            frame_length=frame_length,
            frame_shift=frame_shift,
            dither=dither,
            preemphasis_coefficient=preemphasis_coefficient,
            remove_dc_offset=True,
            window_type=window_type,
            use_energy=False,
            energy_floor=1.192092955078125e-07,
        )
        features.append(feature.squeeze(0))

    if do_normalize_per_mel_bins:
        normalised: List[torch.Tensor] = []
        for feature in features:
            mean = feature.mean(0, keepdim=True)
            var = feature.var(0, keepdim=True)
            normalised.append((feature - mean) / torch.sqrt(var + 1e-5))
        features = normalised

    input_features, attention_mask = _pad_batch(
        features,
        padding_strategy=padding,
        max_length=max_length,
        pad_to_multiple_of=pad_to_multiple_of,
        padding_value=padding_value,
    )

    batch_size, num_frames, num_channels = input_features.shape
    new_num_frames = (num_frames // stride) * stride
    input_features = input_features[:, :new_num_frames, :]
    if return_attention_mask:
        attention_mask = attention_mask[:, :new_num_frames]

    input_features = input_features.reshape(
        batch_size, new_num_frames // stride, num_channels * stride
    )

    output: Dict[str, ReturnType] = {"input_features": input_features}
    if return_attention_mask:
        output["attention_mask"] = attention_mask[:, 1::stride]

    if return_tensors == "np":
        for key, value in output.items():
            output[key] = value.cpu().numpy()  # type: ignore[assignment]

    return output

class SpeechDenoisingProcessor:
    """Run the TorchScripted feature extractor and decoder."""

    def __init__(
        self,
        
        device: str,
        chunk_seconds: float,
        target_sample_rate: int,
    ) -> None:
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        
        feature_extractor_path=f'enhance_audio/sidon_weights/feature_extractor_{device}.pt'
        decoder_path=f'enhance_audio/sidon_weights/decoder_{device}.pt'

        self.feature_extractor = torch.jit.load(
            feature_extractor_path, map_location=self.device
        )
        self.decoder = torch.jit.load(decoder_path, map_location=self.device)
        self.feature_extractor.eval()
        self.decoder.eval()
        self.chunk_samples = max(int(chunk_seconds * 16_000), 1_600)
        self.target_sample_rate = target_sample_rate

        self.preprocessor = transformers.SeamlessM4TFeatureExtractor.from_pretrained(
                                "facebook/w2v-bert-2.0"
                            )

    def _prepare_waveform_batch(
        self,
        waveforms: Sequence[torch.Tensor] | torch.Tensor,
        sample_rates: Sequence[int],
    ) -> torch.Tensor:
        """Pad/truncate a batch of waveforms to the batch's own max length,
        capped at self.chunk_samples."""
        if isinstance(waveforms, torch.Tensor):
            batch_max_len = waveforms.shape[-1]
        else:
            batch_max_len = max(w.shape[-1] for w in waveforms)

        target_len = min(batch_max_len, self.chunk_samples)

        if batch_max_len > self.chunk_samples:
            warnings.warn(f"sample truncated to {self.chunk_samples} samples")

        waveforms_padded = torch.zeros(
            len(waveforms), target_len, dtype=torch.float32
        )

        if isinstance(waveforms, torch.Tensor):
            n = min(waveforms.shape[-1], target_len)
            waveforms_padded[:, :n] = waveforms[:, :n]
        else:
            for idx, waveform in enumerate(waveforms):
                length = min(waveform.shape[-1], target_len)
                waveforms_padded[idx, :length] = waveform[..., :length]

        return waveforms_padded
    
    def _to_mono_16k(self, waveform: np.ndarray, sample_rate: int) -> torch.Tensor:
        """Normalize, mono-ify, highpass, resample to 16kHz. Returns 1D tensor."""
        #sample_rate, waveform = audio
        waveform = 0.9 * (waveform / np.abs(waveform).max())
        target_n_samples = int(48_000/sample_rate* waveform.shape[0])
        # Ensure waveform is a tensor
        if not isinstance(waveform, torch.Tensor):
            waveform = torch.tensor(waveform, dtype=torch.float32)
        
        # If stereo, convert to mono
        if waveform.ndim > 1 and waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=1)
        
        waveform = waveform.view(1, -1)

        wav = torchaudio.functional.highpass_biquad(waveform, sample_rate, 50)
        wav_16k = torchaudio.functional.resample(wav, sample_rate, 16_000)
        return wav_16k.view(-1)
    
    def _prepare_waveform(
        self, waveform: torch.Tensor, sample_rate: int
    ) -> torch.Tensor:
        return self._prepare_waveform_batch([waveform], [sample_rate])[0]

    @torch.inference_mode()
    def process(self, waveform: torch.Tensor, sample_rate: int) -> torch.Tensor:
        return self.process_batch([waveform], [sample_rate])[0]

    @torch.inference_mode()
    def process_single(self, waveform, sample_rate):

        #sample_rate, waveform = audio
        waveform = 0.9 * (waveform / np.abs(waveform).max())
        target_n_samples = int(48_000/sample_rate* waveform.shape[0])
        # Ensure waveform is a tensor
        if not isinstance(waveform, torch.Tensor):
            waveform = torch.tensor(waveform, dtype=torch.float32)

        # If stereo, convert to mono
        if waveform.ndim > 1 and waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=1)

        # Add a batch dimension
        waveform = waveform.view(1, -1)
        wav = torchaudio.functional.highpass_biquad(waveform, sample_rate, 50)
        wav_16k = torchaudio.functional.resample(wav, sample_rate, 16_000)
        restoreds = []
        features =[]
        feature_cache = None
        wav_16k = torch.nn.functional.pad(wav_16k,(0,24000))
        for chunk in wav_16k.view(-1).split(16000 * 96):
            inputs = self.preprocessor(torch.nn.functional.pad(chunk, (160, 160)), return_tensors="pt", sampling_rate=16000).to(self.device)
            with torch.inference_mode():
                feature = self.feature_extractor(inputs["input_features"].to(self.device))["last_hidden_state"]
                if feature_cache is not None:
                    feature = torch.cat([feature_cache,feature],dim=1)
                restoreds.append(self.decoder(feature.transpose(1,2)).view(-1)[:-960])
                feature_cache = feature[:,-1:]

        restored_wav = torch.cat(restoreds,dim=0)

        return (restored_wav.view(-1, 1).cpu().numpy()).astype(np.float32)[:target_n_samples]
    

    @torch.inference_mode()
    def process_batch(
        self,
        waveforms: Sequence[torch.Tensor] | torch.Tensor,
        sample_rates: Optional[Sequence[int]] = None,
        expected_lengths: Optional[Sequence[int]] = None,
    ) -> List[torch.Tensor]:
        if expected_lengths is None:
            expected_lengths: list[int] = []
            for waveform, sample_rate in zip(waveforms, sample_rates):
                duration_seconds = waveform.shape[-1] / float(sample_rate)
                expected_lengths.append(
                    int(round(duration_seconds * self.target_sample_rate))
                )
        prepared_waveforms = self._prepare_waveform_batch(waveforms, sample_rates)

        start_time = time.perf_counter()
        features = extract_seamless_m4t_features(
            [x for x in prepared_waveforms],
            return_tensors="pt",
            padding_value=1.0,
            device=str(self.device),
        )
        feature_tensor = self.feature_extractor(
            features["input_features"].to(self.device)
        )["last_hidden_state"]
        restored_waveforms = self.decoder(feature_tensor.transpose(1, 2)).cpu()
        end_time = time.perf_counter()

        results: List[torch.Tensor] = []
        for sample_idx, sample in enumerate(restored_waveforms):
            restored_waveform = sample.view(-1)
            target_length = expected_lengths[sample_idx]
            current_length = restored_waveform.shape[-1]
            if target_length > 0 and current_length != target_length:
                diff = target_length - current_length
                if diff > 0:
                    restored_waveform = torch.nn.functional.pad(
                        restored_waveform, (0, diff)
                    )
                elif diff < 0:
                    restored_waveform = restored_waveform[:target_length]
            results.append(restored_waveform.contiguous())

        return results