#!/bin/zsh
# Build the distributable "Stentor-<version>.dmg": a disk image with a guided installer
# (Welcome -> License -> Destination -> Install -> Summary), plugin-style.
#
#   ./package.sh            # -> build/Stentor-0.1.0.dmg
#
# Needs the Core ML models in ../sidon_weights/coreml (tools/export_coreml.py).
# Unsigned build: see README for Gatekeeper; set SIGN_APP / SIGN_PKG to Developer ID identities to sign.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${VERSION:-0.1.0}"
ID="local.stentor"
OUT=build
STAGE="$OUT/pkgroot"
DMGDIR="$OUT/dmg"

echo "==> App with bundled models"
./build_app.sh --with-models
if [[ -n "${SIGN_APP:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_APP" "$OUT/Stentor.app"
fi

echo "==> Component package"
rm -rf "$STAGE" && mkdir -p "$STAGE/Applications"
cp -R "$OUT/Stentor.app" "$STAGE/Applications/"
# no extended attributes in the payload (they would show up as ._ files)
xattr -cr "$STAGE"
export COPYFILE_DISABLE=1
pkgbuild --analyze --root "$STAGE" "$OUT/component.plist" >/dev/null
# Always install into /Applications (not "relocate" onto another copy found on disk)
plutil -replace 0.BundleIsRelocatable -bool NO "$OUT/component.plist"
pkgbuild --root "$STAGE" --component-plist "$OUT/component.plist" --identifier "$ID" --version "$VERSION" \
         --install-location / "$OUT/Stentor-component.pkg" >/dev/null

echo "==> Guided installer"
sed "s/__VERSION__/$VERSION/" Installer/Distribution.xml > "$OUT/Distribution.xml"
SIGN_ARGS=()
[[ -n "${SIGN_PKG:-}" ]] && SIGN_ARGS=(--sign "$SIGN_PKG")
productbuild --distribution "$OUT/Distribution.xml" --resources Installer/resources --package-path "$OUT" \
             "${SIGN_ARGS[@]}" "$OUT/Install Stentor.pkg" >/dev/null

echo "==> Disk image"
rm -rf "$DMGDIR" && mkdir -p "$DMGDIR/.background"
cp "$OUT/Install Stentor.pkg" "$DMGDIR/"
tiffutil -cathidpicheck Installer/dmg-background.png Installer/dmg-background@2x.png -out "$DMGDIR/.background/background.tiff" >/dev/null
RW="$OUT/rw.dmg"; FINAL="$OUT/Stentor-$VERSION.dmg"
rm -f "$RW" "$FINAL"
SIZE=$(( $(du -sm "$DMGDIR" | cut -f1) + 60 ))
hdiutil create -quiet -srcfolder "$DMGDIR" -volname "Stentor" -fs HFS+ -format UDRW -size ${SIZE}m "$RW"
MOUNT=$(hdiutil attach -readwrite -noverify -noautoopen "$RW" | awk -F'\t' '/\/Volumes\// {print $NF}')

# Window layout (needs Finder automation permission the first time; skipped if denied)
osascript <<APPLESCRIPT || echo "   (Finder layout skipped: allow Terminal to control Finder for the styled window)"
tell application "Finder"
  tell disk "Stentor"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 840, 520}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 112
    set text size of opts to 13
    set background picture of opts to file ".background:background.tiff"
    set position of item "Install Stentor.pkg" of container window to {500, 200}
    update without registering applications
    delay 1
    close
  end tell
end tell
APPLESCRIPT
cp Resources/Stentor.icns "$MOUNT/.VolumeIcon.icns" && SetFile -a C "$MOUNT" 2>/dev/null || true
sync
hdiutil detach -quiet "$MOUNT"
hdiutil convert -quiet "$RW" -format UDZO -imagekey zlib-level=9 -o "$FINAL"
rm -f "$RW"
echo "==> $FINAL ($(du -h "$FINAL" | cut -f1))"
