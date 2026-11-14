#!/bin/zsh
# Build "Stentor.app" with SwiftPM (no Xcode needed).
#   ./build_app.sh                 app only; models are read from ./Models (scripts/fetch_models.sh)
#   ./build_app.sh --with-models   also copy the float32 Core ML packages into the bundle (standalone)
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(cat ../../VERSION)"   # single source of the version, shared by all apps
swift build -c release
APP="build/Stentor.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/Stentor "$APP/Contents/MacOS/Stentor"
cp Resources/Stentor.icns "$APP/Contents/Resources/Stentor.icns"
cp -R ../../assets/Demo "$APP/Contents/Resources/Demo"   # shared with the desktop app

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Stentor</string>
  <key>CFBundleDisplayName</key><string>Stentor</string>
  <key>CFBundleIdentifier</key><string>local.stentor</string>
  <key>CFBundleExecutable</key><string>Stentor</string>
  <key>CFBundleIconFile</key><string>Stentor</string>
  <key>NSHumanReadableCopyright</key><string>Built by Paolo Sani · powered by Sidon (MIT)</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Audio</string>
      <key>CFBundleTypeRole</key><string>Editor</string>
      <key>LSItemContentTypes</key><array><string>public.audio</string></array>
    </dict>
  </array>
</dict>
</plist>
PLIST

plutil -replace CFBundleShortVersionString -string "$VERSION" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION" "$APP/Contents/Info.plist"

if [[ "${1:-}" == "--with-models" ]]; then
  mkdir -p "$APP/Contents/Resources/Models"
  for m in feature_extractor_float32 decoder_float32; do
    [[ -d "Models/$m.mlpackage" ]] || { echo "Missing Models/$m.mlpackage: run scripts/fetch_models.sh" >&2; exit 1; }
    cp -R "Models/$m.mlpackage" "$APP/Contents/Resources/Models/"
  done
fi

codesign --force --deep --sign - "$APP" >/dev/null
echo "Built $APP"
