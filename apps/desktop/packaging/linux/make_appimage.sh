#!/bin/sh
# Wrap the PyInstaller build (build/dist/Stentor) into Stentor-<version>-x86_64.AppImage and a .tar.gz.
#   packaging/linux/make_appimage.sh <version> [path/to/appimagetool]
set -eu
cd "$(dirname "$0")/../.."
VERSION="$1"
TOOL="${2:-appimagetool}"
DIST=build/dist/Stentor
[ -x "$DIST/Stentor" ] || { echo "Build first: pyinstaller packaging/stentor.spec" >&2; exit 1; }

APPDIR=build/Stentor.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$DIST/." "$APPDIR/usr/bin/"
cp packaging/linux/stentor.desktop "$APPDIR/usr/share/applications/stentor.desktop"
cp packaging/linux/stentor.desktop "$APPDIR/stentor.desktop"
cp packaging/linux/stentor.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/stentor.png"
cp packaging/linux/stentor.png "$APPDIR/stentor.png"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Stentor" "$@"
EOF
chmod +x "$APPDIR/AppRun"

OUT="build/Stentor-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" "$OUT"
tar -C build/dist -czf "build/Stentor-$VERSION-linux-x86_64.tar.gz" Stentor
echo "==> $OUT"
