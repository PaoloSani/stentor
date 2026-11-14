"""Icons for the installers, from the shared 1024 px master: a multi-size .ico (Windows) and a 256 px PNG (Linux).

    python packaging/make_icons.py          (needs Pillow: pip install -e ".[build]")
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
MASTER = HERE.parents[2] / "assets" / "AppIcon-1024.png"


def main() -> None:
    img = Image.open(MASTER).convert("RGBA")
    img.save(HERE / "windows" / "stentor.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    img.resize((256, 256), Image.LANCZOS).save(HERE / "linux" / "stentor.png")
    print("wrote windows/stentor.ico and linux/stentor.png")


if __name__ == "__main__":
    main()
