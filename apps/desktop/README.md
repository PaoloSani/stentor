# Stentor for Windows and Linux — developer guide

A Qt (PySide6) port of the macOS app with the same features: editable speech regions over a waveform or
spectrogram, per-region incremental Enhance, A/B comparison, looping, whole-file or per-region export, settings,
detailed hover help and the guided tour. The Sidon model runs on ONNX Runtime: DirectML on Windows (any
DirectX 12 GPU, with the `directml` extra), CUDA on NVIDIA (`cuda` extra), otherwise the CPU. No PyTorch.
For what Stentor does, see the [main README](../../README.md).

**Status:** feature-complete and tested headless on macOS (CPU). Not yet run on real Windows or Linux machines;
installers come next (PyInstaller, built by GitHub Actions).

## Setup

```bash
cd apps/desktop
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/python -m stentor_desktop          # or: .venv/bin/python -m stentor_desktop talk.wav
```

Linux needs PortAudio for playback (`sudo apt install libportaudio2` on Debian/Ubuntu); Windows and macOS wheels
include it. Compressed formats (m4a, mp3, video files) are decoded with PyAV's bundled FFmpeg.

The voice model is two ONNX files, `feature_extractor.onnx` and `decoder.onnx` (≈ 1 GB). The app looks in
`$STENTOR_MODELS_DIR`, the folder chosen with **Locate Models…**, the per-user data folder
(`%LOCALAPPDATA%\Stentor\ONNX`, `~/.local/share/stentor/ONNX`), stentor-engine's export folder
(`$STENTOR_WEIGHTS_DIR/onnx`, default `~/.cache/stentor/weights/onnx`) and, in a checkout, `sidon_weights/onnx`.
To produce them: `stentor weights download`, then `stentor export onnx` in stentor-engine. Once they are published
as a release asset, set `MODELS_SHA256` in `models.py` and the first-launch card offers **Download**.

## Layout

```
src/stentor_desktop/
  __main__.py     entry point (and the headless checks below)
  window.py       main window: header, editor, island, overlays, menus, shortcuts, drag & drop
  project.py      document state: regions + undo, view, playback, incremental rendering, export, model loading
  core.py         audio loading (libsndfile / PyAV), speech detection, region rules, region renderer
  models.py       locating, downloading (resume, SHA-256) and loading the ONNX model
  player.py       PortAudio playback with seamless looping
  editor.py       editor canvas (ruler, waveform / spectrogram, regions, playhead) and overview strip
  visuals.py      waveform envelopes and visible-window spectrograms
  widgets.py      control island, header, file pill, empty state, toast
  cards.py        settings panel, about card + Check for Updates, model setup, guided tour
  tips.py         detailed hover help
  theme.py        adaptive jade theme (dark / light / auto), fonts, shortcut notation
  icons.py        vector icons
  selftest.py     headless checks and UI snapshots
src/stentor/              vendored engine: the PyTorch-free runtime of stentor-engine. Do not edit it here.
scripts/vendor_engine.sh  refreshes src/stentor from a stentor-engine checkout and records its commit
tests/                    fast tests (no model, no display)
```

The vendored engine also has a command line: `.venv/bin/python -m stentor enhance talk.m4a`.
Exporters, the PyTorch / Core ML backends and the experiments stay in stentor-engine.

## Checks

```bash
.venv/bin/pytest                                                        # logic, renderer, exports, player (no model)
.venv/bin/python -m stentor_desktop --logic in.wav                      # region rules, undo, incremental rendering
.venv/bin/python -m stentor_desktop --process in.wav out.wav            # full pipeline with the ONNX model
.venv/bin/python -m stentor_desktop --export-regions in.wav outdir/     # one WAV per region + CSV
.venv/bin/python -m stentor_desktop --snapshot in.wav out.png spec enhanced zoom=0-25 theme=light scale=1.25 \
    [tour=N|about|setup|settings|tip=enhance|empty]                     # render the UI to PNG, no display needed
```

`STENTOR_DEVICE=cpu|dml|cuda` forces the device for `--process`. Settings are stored with QSettings
(registry on Windows, `~/.config/Stentor/Stentor.conf` on Linux).

The shared demo recording and icon master live in [`assets/`](../../assets); the version comes from the
repository's `VERSION` file.
