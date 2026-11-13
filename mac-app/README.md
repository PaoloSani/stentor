# Stentor for macOS — developer guide

SwiftUI + Core ML app. For what Stentor does, downloads and usage, see the [main README](../README.md).

## Prerequisites

- Apple Silicon Mac, macOS 14+, Xcode **Command Line Tools** (`xcode-select --install`) — full Xcode is not needed.
- Core ML models exported from the repository root:

```bash
tools/download_weights.sh
.venv/bin/python tools/convert_torchscript.py
.venv/bin/python tools/export_coreml.py      # -> sidon_weights/coreml/*.mlpackage
```

Without Xcode the SwiftUI macro plug-ins are unavailable, so the code avoids `@State` and `@Observable`
(it uses `@StateObject` / `ObservableObject` instead).

## Build and run

```bash
./build_app.sh                 # build/Stentor.app; models are read from ../sidon_weights/coreml
./build_app.sh --with-models   # standalone bundle with the float32 models in Contents/Resources/Models
open build/Stentor.app
```

Models are looked up in `$SIDON_MODELS_DIR`, `Contents/Resources/Models`,
`~/Library/Application Support/Stentor/Models` and `../sidon_weights/coreml`; they are compiled on first use and
cached in `~/Library/Application Support/Stentor/Compiled`.

## Code layout

```
Sources/Stentor/
  App.swift              app, menus and keyboard shortcuts
  Engine/
    AudioIO.swift        loading (AVFoundation), resampling, high-pass, WAV writing
    Fbank.swift          Kaldi fbank features (Accelerate), port of speech_enhancer/features.py
    SidonModel.swift     Core ML feature predictor + windowed vocoder, CPU fallback
    Regions.swift        speech detection and the region renderer (fixed-length model calls)
    SelfTest.swift       headless checks and UI snapshots
  UI/
    Project.swift        document state: regions, undo, playback, incremental rendering, export
    EditorView.swift     waveform / spectrogram canvas, region editing (NSView events), playhead
    ControlBar.swift     floating control island and overview strip
    Header.swift         wordmark, about card, settings panel
    Theme.swift          adaptive colours (dark / light / auto)
    Tips.swift           detailed hover help
    Visuals.swift        waveform peaks and visible-window spectrogram
    Player.swift         AVAudioEngine playback with seamless looping
Resources/               app icon (+ make_icon.swift) and the demo recording
Installer/               installer pages, license, artwork (+ make_art.swift), Distribution.xml
```

## Headless checks

```bash
B=.build/release/Stentor
$B --fbank in.f32 out.f32          # features vs Python: max abs diff 3e-4
$B --enhance-raw in.f32 out.f32    # model output vs Python Core ML: 81.6 dB SNR
$B --process in.wav out.wav        # full pipeline, prints regions, speed and CPU fallbacks
$B --logic in.wav                  # region editing rules, undo/redo, looped playback (muted)
$B --incremental in.wav            # per-region re-rendering leaves untouched regions bit-identical
$B --snapshot in.wav out.png spec enhanced zoom=0-25 theme=light scale=1.25   # render the UI to PNG
```

## Packaging

```bash
./package.sh                   # build/Stentor-<version>.dmg; the version comes from mac-app/VERSION
```

Release checklist: bump `VERSION`, run `./package.sh`, add a CHANGELOG entry, then
`gh release create v<version> build/Stentor-<version>.dmg --notes-file …`. Installed apps find it through
**Check for Updates** (GitHub `releases/latest`, so the repository must be public). The installer's `preinstall`
script removes the previous `Stentor.app`, so upgrades are clean.

The DMG holds `Install Stentor.pkg`, a guided installer (Welcome, License, Destination, Install, Summary) that puts
`Stentor.app` with its models into /Applications. Signed builds:

```bash
SIGN_APP="Developer ID Application: …" SIGN_PKG="Developer ID Installer: …" ./package.sh
xcrun notarytool submit build/Stentor-<version>.dmg --keychain-profile <profile> --wait
xcrun stapler staple build/Stentor-<version>.dmg
```

Unsigned builds work, but macOS asks users to confirm the first launch of the installer (right-click › Open).
