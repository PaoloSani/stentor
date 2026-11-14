"""Entry point: `python -m stentor_desktop` or the `stentor-desktop` launcher."""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel

    from . import __version__

    app = QApplication(sys.argv)
    app.setApplicationName("Stentor")
    app.setApplicationVersion(__version__)
    label = QLabel(f"Stentor {__version__} for Windows and Linux: work in progress")
    label.resize(520, 120)
    label.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
