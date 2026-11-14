"""Entry point: `python -m stentor_desktop [file]`, the `stentor-desktop` launcher, or headless checks (see selftest)."""

import sys


def main() -> int:
    from .selftest import run_if_requested

    code = run_if_requested(sys.argv[1:])
    if code is not None:
        return code

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .window import MainWindow, follow_system_theme, load_preferences

    QApplication.setApplicationName("Stentor")
    QApplication.setOrganizationName("Stentor")
    QApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # same look on Windows and Linux; colours come from the theme
    load_preferences()
    win = MainWindow()
    follow_system_theme(win)
    win.show()
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    if files:
        win.project.open(files[0])
    else:
        QTimer.singleShot(200, win.first_launch)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
