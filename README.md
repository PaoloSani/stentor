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