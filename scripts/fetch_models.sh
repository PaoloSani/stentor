#!/bin/sh
# Download the Core ML models Stentor needs (Sidon, float32, ~930 MB) into ./Models and verify them.
# They are published as an asset of the "models-1" release. Developers working on the engine can
# instead export them with stentor-engine (`stentor export coreml`); the app also looks there.
set -eu
cd "$(dirname "$0")/.."

REPO="PaoloSani/stentor"
TAG="models-1"
ZIP="Stentor-CoreML-float32.zip"
SHA256="08f715ca202c281288e89a0d996838c1b22851cfbba7b2346c2488fc56bcc66c"

if [ -d Models/feature_extractor_float32.mlpackage ] && [ -d Models/decoder_float32.mlpackage ]; then
  echo "Models already present in ./Models"; exit 0
fi
mkdir -p Models
TMP="Models/$ZIP.part"

GH="$(command -v gh || true)"; [ -z "$GH" ] && [ -x /opt/homebrew/bin/gh ] && GH=/opt/homebrew/bin/gh
if [ -n "$GH" ] && "$GH" auth status >/dev/null 2>&1; then
  "$GH" release download "$TAG" --repo "$REPO" --pattern "$ZIP" --output "$TMP" --clobber
else
  curl -L --fail --progress-bar -o "$TMP" "https://github.com/$REPO/releases/download/$TAG/$ZIP"
fi

if [ "$(shasum -a 256 "$TMP" | cut -d' ' -f1)" != "$SHA256" ]; then
  rm -f "$TMP"; echo "Checksum mismatch for $ZIP" >&2; exit 1
fi
unzip -q -o "$TMP" -d Models && rm -f "$TMP"
echo "Models ready in ./Models"
