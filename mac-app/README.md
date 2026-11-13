# Stentor — native macOS app (v0.1)

Named after [Stentor](https://en.wikipedia.org/wiki/Stentor), the herald of the Iliad whose voice was as loud as fifty men.
Powered by the Sidon speech-restoration model.

SwiftUI + Core ML port of the Python pipeline. Only the green speech regions are restored;
everything else stays digital silence and the output keeps the original length (48 kHz / 24-bit WAV).

## Build (Command Line Tools are enough, no Xcode)

    ./build_app.sh                 # build/Stentor.app, models read from ../sidon_weights/coreml
    ./build_app.sh --with-models   # standalone: copies the float32 .mlpackage files into the bundle

Models are searched in `$SIDON_MODELS_DIR`, the bundle's `Resources/Models`,
`~/Library/Application Support/Stentor/Models` and `../sidon_weights/coreml`
(export them with `tools/export_coreml.py`). They are compiled once and cached in Application Support.

## Editing

| Action | How |
|---|---|
| Add a region | click empty space → region up to just before the next one (or the end); drag to draw one |
| Adjust | drag a green bar |
| Remove | hover the top of a bar and click ✕, or ⌘-click a bar/region, or select + Delete |
| Seek / loop | click the ruler to seek, drag on it to set a loop range; L toggles looping |
| Navigate | vertical scroll / pinch = zoom at pointer, horizontal scroll = pan, overview strip |
| Listen | Space play/pause · B toggles A (original, level-matched) / B (enhanced) · S wave/spectrogram |
| Process | ⌘↩ Enhance · ⌘E Export · ⌘Z / ⇧⌘Z undo/redo · ⇧⌘D re-detect speech |

## Engine checks against the Python reference

    .build/release/Stentor --fbank in.f32 out.f32        # features: max abs diff 3e-4
    .build/release/Stentor --enhance-raw in.f32 out.f32  # model output: 81.6 dB SNR vs Python Core ML
    .build/release/Stentor --process in.wav out.wav      # full pipeline
    .build/release/Stentor --logic in.wav                # editing rules + looped playback

## Packaging (DMG with a guided installer)

    ./package.sh                   # -> build/Stentor-0.1.0.dmg  (~900 MB, models included)

The DMG contains `Install Stentor.pkg`, a standard macOS installer with Welcome, License,
Destination, Install and Summary steps; it installs `Stentor.app` into /Applications.
Artwork: `Resources/make_icon.swift` (app icon) and `Installer/make_art.swift` (installer and DMG
backgrounds); installer pages are in `Installer/resources/`.

### Installing (users)

1. Open `Stentor-0.1.0.dmg` and double-click **Install Stentor**.
2. Follow the steps (Continue → Agree → Install, then your Mac password).
3. Launch **Stentor** from Applications.

Until builds are signed with an Apple Developer ID and notarized, macOS blocks the installer the
first time: right-click it and choose **Open** (or System Settings › Privacy & Security › Open Anyway).
To sign: `SIGN_APP="Developer ID Application: …" SIGN_PKG="Developer ID Installer: …" ./package.sh`,
then notarize with `xcrun notarytool submit build/Stentor-0.1.0.dmg --wait` and `xcrun stapler staple`.
