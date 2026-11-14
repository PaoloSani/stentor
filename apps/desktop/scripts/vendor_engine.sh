#!/bin/sh
# Copy the PyTorch-free runtime of stentor-engine into src/stentor (the package the desktop app imports).
#   scripts/vendor_engine.sh [path/to/stentor-engine]      default: ../../../stentor-engine
# Kept: audio, features, segmentation, VAD, render, weights, the ONNX backend and the CLI.
# Left out: exporters, the Flask GUI and the PyTorch / Core ML backends (they live in stentor-engine).
# Do not edit src/stentor by hand: change stentor-engine, then run this again.
set -eu
cd "$(dirname "$0")/.."
ENGINE="$(cd "${1:-../../../stentor-engine}" && pwd)"
SRC="$ENGINE/src/stentor"
[ -f "$SRC/__init__.py" ] || { echo "Not a stentor-engine checkout: $ENGINE" >&2; exit 1; }

DEST=src/stentor
rm -rf "$DEST"
rsync -a \
  --exclude '__pycache__/' --exclude 'export/' --exclude 'gui/' --exclude 'models/_generated/' \
  --exclude 'models/torchscript.py' --exclude 'models/eager.py' --exclude 'models/coreml.py' \
  "$SRC/" "$DEST/"
cp "$ENGINE/LICENSE" "$DEST/LICENSE"

COMMIT="$(git -C "$ENGINE" rev-parse --short HEAD)"
DIRTY="$(git -C "$ENGINE" status --porcelain -- src | head -1)"
cat > "$DEST/VENDORED.md" <<EOF
Vendored from stentor-engine $COMMIT${DIRTY:+ (with uncommitted changes)} by scripts/vendor_engine.sh.
Do not edit these files here: change stentor-engine and run the script again.
EOF
echo "Vendored stentor-engine $COMMIT${DIRTY:+ (dirty)} into $DEST ($(find "$DEST" -name '*.py' | wc -l | tr -d ' ') modules)"
