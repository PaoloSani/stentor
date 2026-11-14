# Stentor for Windows and Linux — developer guide

**Work in progress.** A Qt (PySide6) port of the macOS app, running the same Sidon model on ONNX Runtime:
DirectML on Windows (any DirectX 12 GPU), CUDA on NVIDIA, CPU elsewhere. No PyTorch at runtime. For what Stentor does, see the [main README](../../README.md).

## Setup

```bash
cd apps/desktop
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/python -m stentor_desktop
```

## Layout

```
src/stentor_desktop/      the Qt app
src/stentor/              vendored engine: the PyTorch-free runtime of stentor-engine (audio, features,
                          segmentation, VAD, render, ONNX backend, CLI). Do not edit it here.
scripts/vendor_engine.sh  refreshes src/stentor from a stentor-engine checkout and records its commit
```

The vendored engine also has a command line: `.venv/bin/python -m stentor enhance talk.m4a`.
Exporters, the PyTorch / Core ML backends and the experiments stay in stentor-engine.

The ONNX models come from stentor-engine (`stentor weights download`, then `stentor export onnx`); release builds
will download them on first launch, like the Mac app.

## Plan

Feature parity with [the macOS app](../macos/README.md):

- editable speech regions over a waveform / spectrogram view, zoom, pan, ruler loop
- Enhance with per-region incremental re-rendering, A/B with a level-matched original
- export of the whole file or of each region (+ CSV), settings, theme, hover help and guided tour
- first-launch model download, Check for Updates
- PyInstaller builds (Windows installer, Linux AppImage) from GitHub Actions

The shared demo recording and icon master live in [`assets/`](../../assets); the version comes from the
repository's `VERSION` file.
