# db_sidon Environment Setup

This guide replicates the `db_sidon` environment using `uv`, avoiding known CUDA/cuDNN dependency conflicts (notably an `nvidia-cudnn-cu12` vs `nvidia-cudnn-cu13` clash that causes `RuntimeError: cuDNN error: CUDNN_STATUS_NOT_INITIALIZED`).

## Prerequisites

- NVIDIA driver supporting CUDA 12.8 (check with `nvidia-smi`)
- `uv` installed (https://docs.astral.sh/uv/)
- Python 3.12 available to `uv`

## Setup Steps

### 1. Create a clean virtual environment

    uv venv envs/db_sidon --python 3.12
    source envs/db_sidon/bin/activate

### 2. Install PyTorch first (required before flash-attn build)

`flash-attn` imports `torch` during its own build process, so torch must be installed before attempting a full `sidon_requirements.txt` install.

    uv pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
      --extra-index-url https://download.pytorch.org/whl/cu128 \
      --index-strategy unsafe-best-match

Verify:

    python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"

### 3. Install the rest of the dependencies

    uv pip install -r sidon_requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cu128 \
      --index-strategy unsafe-best-match \
      --no-build-isolation

Note on `--index-strategy unsafe-best-match`: this allows `uv` to pull package versions from both PyPI and the PyTorch index. Only use this because both indexes are trusted official sources.

Note on `--no-build-isolation`: required for `flash-attn`, which needs direct access to the already-installed `torch` in the environment during its build step.

## Usage: Audio Enhancement Script

`enhance_audio/enhance_folder.py` enhances all audio files in a folder using
`SpeechDenoisingProcessor`. Outputs are written into a sibling folder named
`audio_48kHz_enh`, next to the input folder.

### Basic usage

    python enhance_audio/enhance_folder.py /path/to/input_folder

This will create `/path/to/audio_48kHz_enh` containing the enhanced `.wav` files,
mirroring the input folder's structure.

### Key options

| Argument | Description | Default |
|---|---|---|
| `input_dir` | Folder containing audio files to enhance | *(required)* |
| `--device` | `cuda`, `cpu`, or `auto` | `auto` |
| `--chunk-seconds` | Chunk length (seconds) for processing | `20.0` |
| `--target-sample-rate` | Output sample rate (Hz) | `48000` |
| `--num-workers` | Number of parallel worker processes (one per GPU/device-slot) | `1` |
| `--batch-size` | Number of files batched together per inference call | `8` |
| `--skip-errors` | Continue processing if a file fails | off |
| `--force` | Reprocess files even if output already exists | off |

### Running with multiple workers (multi-GPU)

    python enhance_audio/enhance_folder.py /path/to/input_folder --num-workers 4 --batch-size 16

Each worker processes a subset of files. Set `--device cuda` with `CUDA_VISIBLE_DEVICES`
configured per process if targeting specific GPUs.

### Resuming / skipping already-processed files

By default, files whose enhanced output already exists are skipped. Use `--force`
to reprocess everything:

    python enhance_audio/enhance_folder.py /path/to/input_folder --force
## macOS / Apple Silicon (`speech_enhancer` package)

Local, CPU-only pipeline for long recordings, with VAD-based segmentation that can be
edited before enhancement (the basis of the upcoming Mac app).

    /opt/homebrew/bin/python3.12 -m venv .venv
    .venv/bin/pip install -r requirements-mac.txt

Weights: `sidon_weights/feature_extractor_cpu.pt` and `decoder_cpu.pt` from
https://huggingface.co/sarulab-speech/sidon-v0.1 (override the folder with `SIDON_WEIGHTS_DIR`).

    # 1. VAD segmentation -> editable JSON of cut points (cuts always fall in pauses)
    .venv/bin/python -m speech_enhancer segment recording.m4a
    # 2. enhancement -> recording_enhanced.wav (48 kHz mono, 24-bit)
    .venv/bin/python -m speech_enhancer enhance recording.m4a --segments recording.segments.json

### Graphical interface

    .venv/bin/python -m speech_enhancer gui            # opens http://127.0.0.1:8765 in the browser

Add files or folders (native macOS picker), inspect the waveform with detected speech and
the VAD curve, drag / add (double-click) / remove (Alt+click) cuts, preview single
segments, enhance whole files and compare A/B (key `B`) against a level-matched original.
Outputs go to `~/Desktop/Sidon Output` by default (changeable in Settings).

### Fast backend: Core ML on the Apple GPU (recommended)

The TorchScript release only runs on CPU. Convert it once to eager PyTorch and then to
Core ML (about 2 minutes, ~2 GB of generated files, git-ignored):

    .venv/bin/python tools/convert_torchscript.py   # -> speech_enhancer/_generated + sidon_weights/eager
    .venv/bin/python tools/export_coreml.py         # -> sidon_weights/coreml/*.mlpackage

`enhance` then picks Core ML automatically (`--backend torchscript` forces the CPU path,
`--precision float16` trades a tiny bit of fidelity for speed and memory).
Measured on an M1 (8 GB), 5-minute file:

| Backend | Speed | Peak memory | Fidelity vs. reference |
|---|---|---|---|
| TorchScript, CPU | 1.6-1.8x real time | 5.1 GB | reference |
| Core ML float32, GPU | 4.2x real time | 1.8 GB | identical (>84 dB SNR) |
| Core ML float16, GPU | 5.2x real time | 1.2 GB | ~28 dB SNR |

The Neural Engine is not used: its fp16 arithmetic audibly degrades the vocoder.

Any format readable by libsndfile works, plus m4a/aac/mp4 via macOS `afconvert`.
Segments are processed one at a time with 0.5 s of context per side and joined with a
40 ms crossfade centred in the pause; output is streamed to disk, so memory does not grow
with file length.
