<p align="center"><img src="docs/icon.png" width="128" alt="Stentor icon"></p>

<h1 align="center">Stentor</h1>

<p align="center"><b>Studio-quality voice restoration for macOS, running entirely on your Mac.</b><br>
A native app built on <a href="https://github.com/sarulab-speech/Sidon">Sidon</a>, the open-source speech restoration model from the University of Tokyo.</p>

<p align="center"><img src="docs/stentor-dark.jpg" alt="Stentor — enhanced speech in the spectrogram view, dark theme"></p>

| Before (reverberant stadium recording) | After Stentor |
|---|---|
| ![before](docs/stentor-before-light.jpg) | ![after](docs/stentor-after-light.jpg) |

*Demo: J.F. Kennedy at Rice University, 1962 (public domain) — reverb, crowd and band-limiting removed.*

Named after [Stentor](https://en.wikipedia.org/wiki/Stentor), the herald of the Greeks in the *Iliad* whose voice was as loud as fifty men.

---

## Features

- **Restores speech** — removes noise, reverb and codec damage and rebuilds full 48 kHz bandwidth (Sidon: w2v-BERT 2.0 feature predictor + HiFi-GAN vocoder).
- **Only the voice is processed.** Speech is detected automatically and shown as green regions; everything else stays digital silence and the output keeps **exactly the original length**, so it lines up in your DAW.
- **Editable regions** — click to add, drag edges, hover the top of an edge for ✕, right-click to re-render, loop or delete a single region. After the first run only changed regions are processed again.
- **A/B comparison** with a level-matched original, waveform and spectrogram views, seamless looping, zoom and pan.
- **Fast and private** — Core ML on the Apple GPU, nothing leaves your computer. On an M1 (8 GB): ~3–5× real time, about 1 GB of memory.
- Dark / light / auto theme, detailed hover help, adjustable icon size.
- WAV export (16/24-bit, 32-bit float; 48 kHz or source rate): the whole file, or each speech region as its own file plus a CSV of start/end times (`⇧⌘E`).

## Download and install

**[⬇︎ Download Stentor for macOS](https://github.com/PaoloSani/stentor/releases/latest)** — a small DMG; the voice model (≈ 930 MB) is downloaded on first launch.

Requirements: Apple Silicon Mac (M1 or later), macOS 14 Sonoma or newer, ~2 GB free disk space.

1. Open the downloaded `Stentor-<version>.dmg`.
2. Double-click **Install Stentor** and follow the steps: Welcome → License → Destination → Install (your Mac password is needed to write to Applications) → Summary.
3. Open **Stentor** from Applications and click **Download** to fetch the voice model (≈ 930 MB, once; verified, kept across updates). A public-domain demo recording opens on first launch.

> **"Install Stentor can't be opened"?** Current builds are not yet signed with an Apple Developer ID.
> Right-click the installer and choose **Open**, or go to **System Settings › Privacy & Security** and click **Open Anyway**.

After the download the model is prepared for your GPU (about 10 s, once).

### Updating

Click the **STENTOR** logo › **Check for Updates** (or Help › Check for Updates…). When a newer version exists,
download its DMG and run the installer: it replaces the installed app and keeps your settings and the downloaded model.

## Using Stentor

1. **Open** a recording — drop it on the window, press `⌘O`, or click the file name in the header.
2. **Check the green regions.** Only these are restored; tune detection in Settings (gear, top right) if needed.
3. **Enhance** (`⌘↩`), then press `B` to compare with the original.
4. **Export** (`⌘E`).

| Action | How |
|---|---|
| Add a region | click empty space (up to the next region) or drag to draw one |
| Adjust / remove | drag a green edge · hover its top and click ✕ · `⌘`-click · select + `Delete` |
| Region menu | right-click: enhance only this region, loop, play, delete |
| Seek / loop | click the ruler · drag on it to set a loop · `L` toggles loop (defaults to the first region) |
| Navigate | scroll ↕ or pinch = zoom at pointer · scroll ↔ = pan · overview strip at the bottom |
| Listen | `Space` play/pause · `B` original ↔ enhanced · `S` waveform ↔ spectrogram |
| Edit history | `⌘Z` / `⇧⌘Z` |

Hover anything for a detailed explanation (Settings › Help › Detailed tooltips).

## Build from source

Builds with the Xcode **Command Line Tools** (`xcode-select --install`); full Xcode is not required.

```bash
git clone https://github.com/PaoloSani/stentor.git && cd stentor
scripts/fetch_models.sh        # Core ML models (~930 MB) into ./Models, checksum-verified
./build_app.sh                 # build/Stentor.app
open build/Stentor.app
./package.sh                   # build/Stentor-<version>.dmg: guided installer (models are downloaded on first launch)
```

Developer notes (code layout, headless tests, packaging, signing, releases): [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## How it works

1. **Load** any format (WAV, AIFF, FLAC, MP3, M4A…), mix to mono, resample to 16 kHz, 50 Hz high-pass, peak-normalise.
2. **Detect speech** and turn it into editable regions.
3. **Restore each region**: Kaldi fbank features → w2v-BERT 2.0 feature predictor (Sidon, 8 layers + LoRA) → HiFi-GAN vocoder at 48 kHz, all on the GPU with Core ML. Long regions are split at the quietest point and joined with crossfades; every model call uses one of two fixed lengths so GPU memory stays flat.
4. **Assemble** a full-length 48 kHz file: restored regions with short fades, silence elsewhere.

The models are derived from the official Sidon TorchScript release: the CPU-only graphs are transcribed into bit-exact
PyTorch modules and exported to Core ML. That conversion, the Python reference pipeline the app is validated
against (features within 3·10⁻⁴, audio at 81 dB SNR), a CLI and the experiments live in a separate project,
**stentor-engine**.

| Backend (M1, 8 GB, 5-min file) | Speed | Peak memory | Fidelity |
|---|---|---|---|
| TorchScript, CPU | 1.6–1.8× real time | 5.1 GB | reference |
| **Core ML float32, GPU (Stentor)** | 4.2× real time | 1.8 GB | identical (>84 dB SNR) |
| Core ML float16, GPU | 5.2× real time | 1.2 GB | ~28 dB SNR |

The Neural Engine is not used: its fp16 arithmetic audibly degrades the vocoder.

## Repository layout

```
Sources/Stentor/      the app: Engine/ (audio I/O, fbank, Core ML model, regions) and UI/ (SwiftUI)
Resources/            app icon (+ generator) and the public-domain demo recording
Installer/            guided installer pages, license, artwork, preinstall script
scripts/              fetch_models.sh
build_app.sh          builds build/Stentor.app
package.sh            builds the DMG with the guided installer
VERSION               app version (Info.plist and package)
docs/                 developer guide and README images
CHANGELOG.md          release notes
```

## Roadmap

- Native builds for Windows and Linux (ONNX Runtime: DirectML / CUDA / CPU).
- Neural voice activity detection (Silero) for noisy or reverberant material.
- Signed and notarized releases.

## Credits and licenses

- **Stentor** — built by Paolo Sani. MIT License (see [LICENSE](LICENSE)).
- **Sidon** — W. Nakata, Y. Saito, Y. Ueda, H. Saruwatari, The University of Tokyo ([paper](https://arxiv.org/abs/2509.17052), [code](https://github.com/sarulab-speech/Sidon), [weights](https://huggingface.co/sarulab-speech/sidon-v0.1)). MIT License.
- **w2v-BERT 2.0** — Meta AI ([model](https://huggingface.co/facebook/w2v-bert-2.0)). MIT License.
- **Demo recording** — John F. Kennedy, address at Rice University, 12 September 1962. John F. Kennedy Presidential Library and Museum, via [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Jfk_rice_university_we_choose_to_go_to_the_moon.ogg). Public domain.
