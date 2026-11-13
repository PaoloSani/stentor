# Changelog

## Stentor 0.2.0

**Update:** download `Stentor-0.2.0.dmg` and run the installer — it replaces 0.1.0 and keeps your settings.

### New
- Export each speech region as its own WAV (numbered, named after its start time) plus a CSV of start/end times; whole-file export stays the default (Settings › Export, or File › Export Speech Regions… ⇧⌘E).

## Stentor 0.1.0 — first release

Native macOS app for voice restoration, built on the open-source [Sidon](https://github.com/sarulab-speech/Sidon) model.

**Install:** download `Stentor-0.1.0.dmg`, open it and double-click **Install Stentor**.
Builds are not yet signed with an Apple Developer ID: if macOS blocks the installer, right-click it and choose
**Open**, or use **System Settings › Privacy & Security › Open Anyway**.
Requires an Apple Silicon Mac (M1 or later) and macOS 14 or newer.

### Highlights
- Restores noisy, reverberant or band-limited speech to 48 kHz studio quality, entirely on the Mac's GPU (Core ML).
- Processes only the detected speech: green, editable regions; the output keeps the original length.
- Per-region and incremental re-rendering, A/B comparison, waveform and spectrogram views, looping.
- Dark / light / auto theme, detailed hover help, adjustable icon size, WAV export (16/24-bit, 32-bit float).
- Check for Updates in the about card (click the logo); reinstalling a newer DMG upgrades cleanly.
- Guided installer; a one-minute public-domain demo (J.F. Kennedy at Rice University, 1962) opens on first launch.

### Known limitations
- Speech detection is energy based: on noisy or very reverberant recordings it may mark the whole file as speech.
- Sidon is trained on speech; singing can come out softer or less natural.
- The whole file is kept in memory, so very long recordings (hours) need a lot of RAM.
