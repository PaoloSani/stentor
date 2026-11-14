# PyInstaller spec for Stentor (Windows / Linux; macOS builds work too, for testing).
#   cd apps/desktop && pyinstaller --noconfirm packaging/stentor.spec      -> dist/Stentor/
# The voice model is not bundled: the app downloads it on first launch or uses "Locate Models…".
import ctypes.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

HERE = Path(SPECPATH)
APP = HERE.parent
REPO = APP.parent.parent
ASSETS = REPO / "assets"

datas = [
    (str(ASSETS / "Demo"), "assets/Demo"),
    (str(ASSETS / "AppIcon-1024.png"), "assets"),
    (str(REPO / "LICENSE"), "."),
    (str(APP / "src" / "stentor" / "LICENSE"), "licenses/stentor-engine"),
]
binaries = collect_dynamic_libs("onnxruntime")
datas += collect_data_files("onnxruntime", includes=["capi/*.dll", "capi/*.so*", "capi/*.dylib"])

if sys.platform.startswith("linux"):
    # sounddevice wheels bundle PortAudio on Windows and macOS only; ship the system library on Linux
    name = ctypes.util.find_library("portaudio")
    for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib"):
        if name and os.path.exists(os.path.join(d, name)):
            binaries.append((os.path.join(d, name), "."))  # copied under its soname, libportaudio.so.2
            break
    else:
        raise SystemExit("libportaudio2 not found: sudo apt install libportaudio2")

hiddenimports = ["stentor.models.onnx", "scipy.signal"]

excludes = [
    "torch", "torchaudio", "tkinter", "matplotlib", "IPython", "pytest", "PIL",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus",
    "PySide6.QtConcurrent", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtXml", "PySide6.QtSvg",
]

a = Analysis(
    [str(HERE / "launch.py")],
    pathex=[str(APP / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(HERE / "windows" / "stentor.ico")  # packaging/make_icons.py
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Stentor",
    console=False,
    icon=icon if sys.platform == "win32" else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Stentor", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(coll, name="Stentor.app", icon=None, bundle_identifier="local.stentor.desktop")
