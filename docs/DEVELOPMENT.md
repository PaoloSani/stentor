# Stentor for macOS — developer guide

SwiftUI + Core ML app. For what Stentor does, downloads and usage, see the [README](../README.md).

## Prerequisites

- Apple Silicon Mac, macOS 14+, Xcode **Command Line Tools** (`xcode-select --install`) — full Xcode is not needed.
- The Core ML models in `./Models`:

```bash
scripts/fetch_models.sh          # release asset "models-1", ~930 MB, SHA-256 verified
```

  To regenerate them (or try other precisions), use stentor-engine: `stentor weights download`,
  then `stentor export coreml`; the app also finds models in its export folder
  (`$STENTOR_WEIGHTS_DIR/coreml`, default `~/.cache/stentor/weights/coreml`).

Without Xcode the SwiftUI macro plug-ins are unavailable, so the code avoids `@State` and `@Observable`
(it uses `@StateObject` / `ObservableObject` instead).

## Build and run

```bash
./build_app.sh                 # build/Stentor.app; models are read from ./Models
./build_app.sh --with-models   # standalone bundle with the float32 models in Contents/Resources/Models
open build/Stentor.app
```

Models are looked up in `$SIDON_MODELS_DIR`, `Contents/Resources/Models`,
`~/Library/Application Support/Stentor/Models`, the stentor-engine export folder and `./Models`; they are compiled on first use and
cached in `~/Library/Application Support/Stentor/Compiled`.

## Code layout

```
Sources/Stentor/
  App.swift              app, menus and keyboard shortcuts
  Engine/
    ModelInstaller.swift first-launch download of the Core ML models (resume, SHA-256, atomic install)
    AudioIO.swift        loading (AVFoundation), resampling, high-pass, WAV writing
    Fbank.swift          Kaldi fbank features (Accelerate), port of the stentor-engine fbank
    SidonModel.swift     Core ML feature predictor + windowed vocoder, CPU fallback
    Regions.swift        speech detection and the region renderer (fixed-length model calls)
    SelfTest.swift       headless checks and UI snapshots
  UI/
    ContentView.swift    window layout (header, editor, island, overlays), drag & drop
    Project.swift        document state: regions, undo, playback, incremental rendering, export
    ModelSetupView.swift first-launch card that downloads the voice model
    Updater.swift        Check for Updates (GitHub releases/latest)
    EditorView.swift     waveform / spectrogram canvas, region editing (NSView events), playhead
    ControlBar.swift     floating control island and overview strip
    Header.swift         wordmark, about card, settings panel
    Theme.swift          adaptive colours (dark / light / auto)
    Tips.swift           detailed hover help
    Tour.swift           guided tour: anchors on UI parts, spotlight overlay, step cards
    Visuals.swift        waveform peaks and visible-window spectrogram
    Player.swift         AVAudioEngine playback with seamless looping
Resources/               app icon (+ make_icon.swift) and the demo recording
scripts/fetch_models.sh  downloads the Core ML models
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
$B --export-regions in.wav outdir/ # one WAV per region + CSV (add source-rate for the input sample rate)
$B --install-models                # run the model installer (STENTOR_MODELS_URL / STENTOR_MODELS_DEST override)
$B --check-updates                 # query the latest release (STENTOR_VERSION_OVERRIDE / STENTOR_UPDATE_API override)
$B --tips                          # tooltips are suppressed under modal cards
$B --snapshot in.wav out.png spec enhanced zoom=0-25 theme=light scale=1.25 [setup|about|toast|tour=N]   # render the UI to PNG
```

## Packaging

```bash
./package.sh                   # build/Stentor-<version>.dmg; the version comes from VERSION
```

Release checklist: bump `VERSION`, run `./package.sh`, add a CHANGELOG entry, then
`gh release create v<version> build/Stentor-<version>.dmg --title "Stentor <version>" --notes-file …`. Installed apps find it through
**Check for Updates** (GitHub `releases/latest`, so the repository must be public). The installer's `preinstall`
script removes the previous `Stentor.app`, so upgrades are clean; if that app still carries the models (0.2.0 and
earlier), it first moves them to the user's `~/Library/Application Support/Stentor/Models`.

The DMG holds `Install Stentor.pkg`, a guided installer (Welcome, License, Destination, Install, Summary) that puts
`Stentor.app` into /Applications. The models are not bundled: on first launch `ModelInstaller` downloads the
`models-1` release asset into `~/Library/Application Support/Stentor/Models` (resume, SHA-256, atomic install).
When the models change, publish a new `models-N` release and update the URL and checksum in `ModelInstaller.swift`
and `scripts/fetch_models.sh`. Signed builds:

```bash
SIGN_APP="Developer ID Application: …" SIGN_PKG="Developer ID Installer: …" ./package.sh
xcrun notarytool submit build/Stentor-<version>.dmg --keychain-profile <profile> --wait
xcrun stapler staple build/Stentor-<version>.dmg
```

Unsigned builds work, but macOS asks users to confirm the first launch of the installer (right-click › Open).
