#!/bin/sh
# Download the Sidon TorchScript weights (MIT) from Hugging Face into sidon_weights/ and verify them.
#   tools/download_weights.sh          # CPU weights (needed for macOS / Core ML export)
#   tools/download_weights.sh --cuda   # also the CUDA weights (Linux batch processing)
set -eu
cd "$(dirname "$0")/.."
REPO="https://huggingface.co/sarulab-speech/sidon-v0.1/resolve/main"
mkdir -p sidon_weights

fetch() { # name sha256
  dest="sidon_weights/$1"
  if [ -f "$dest" ] && [ "$(shasum -a 256 "$dest" | cut -d' ' -f1)" = "$2" ]; then
    echo "ok        $1"; return
  fi
  echo "download  $1"
  curl -L --fail --progress-bar -o "$dest.part" "$REPO/$1"
  if [ "$(shasum -a 256 "$dest.part" | cut -d' ' -f1)" != "$2" ]; then
    rm -f "$dest.part"; echo "checksum mismatch for $1" >&2; exit 1
  fi
  mv "$dest.part" "$dest"
}

fetch feature_extractor_cpu.pt fd9abc906a9048b3c047bd3d246a25f6485d09c2d6bb85e098f527f844efc019
fetch decoder_cpu.pt 34dcc80fab75bd1336369ba5b2063f6da475887aa824db94b495c4059c5fdea4
if [ "${1:-}" = "--cuda" ]; then
  fetch feature_extractor_cuda.pt c3739c332da4ce00cc9019a328bcb19ee8f863ac5eb0b52386672772aab836ce
  fetch decoder_cuda.pt a789c71f54ca7db4b28becdc87c5e8b9260cb568cca462d502c54900db74a1cc
fi
