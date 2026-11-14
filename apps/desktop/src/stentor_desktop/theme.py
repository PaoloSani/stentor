"""Adaptive jade theme (dark / light / auto), fonts and the keyboard-shortcut notation of the platform."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

# (dark rgba, light rgba), 0..1 like the Swift theme
_TOKENS = {
    "bg": ((0.075, 0.078, 0.09, 1), (0.945, 0.948, 0.955, 1)),
    "lane": ((0.095, 0.1, 0.115, 1), (0.985, 0.986, 0.99, 1)),
    "header": ((0.085, 0.088, 0.1, 1), (0.915, 0.92, 0.93, 1)),
    "island": ((0.12, 0.125, 0.145, 0.97), (1, 1, 1, 0.97)),
    "card": ((0.135, 0.14, 0.16, 0.99), (1, 1, 1, 0.99)),
    "ink": ((1, 1, 1, 1), (0, 0, 0, 1)),
    "text": ((1, 1, 1, 0.86), (0.08, 0.09, 0.1, 0.9)),
    "muted": ((1, 1, 1, 0.48), (0, 0, 0, 0.5)),
    "grid": ((1, 1, 1, 0.06), (0, 0, 0, 0.07)),
    "inverse": ((0.08, 0.085, 0.1, 1), (1, 1, 1, 1)),
    "onAccent": ((0.04, 0.06, 0.05, 0.9), (1, 1, 1, 1)),
    "wave": ((0.55, 0.6, 0.68, 1), (0.36, 0.4, 0.48, 1)),
    "waveEnh": ((0.74, 0.67, 0.93, 1), (0.47, 0.36, 0.74, 1)),
    "speech": ((0.40, 0.74, 0.58, 1), (0.20, 0.55, 0.42, 1)),
    "loop": ((0.98, 0.72, 0.32, 1), (0.84, 0.53, 0.1, 1)),
    "danger": ((0.98, 0.42, 0.4, 1), (0.86, 0.24, 0.22, 1)),
    "wordTop": ((0.80, 0.93, 0.86, 1), (0.33, 0.62, 0.50, 1)),
    "wordBottom": ((0.40, 0.74, 0.58, 1), (0.15, 0.44, 0.33, 1)),
}

RULER_H = 22
X_ZONE = 20


class Theme:
    mode = "auto"  # auto | dark | light
    icon_scale = 1.0
    detailed_tips = True

    @classmethod
    def dark(cls) -> bool:
        if cls.mode != "auto":
            return cls.mode == "dark"
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            return hints.colorScheme() != Qt.ColorScheme.Light
        return True

    @classmethod
    def c(cls, name: str, alpha: float | None = None) -> QColor:
        rgba = _TOKENS[name][0 if cls.dark() else 1]
        col = QColor.fromRgbF(*rgba)
        if alpha is not None:
            col.setAlphaF(rgba[3] * alpha)
        return col

    @classmethod
    def palette(cls) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window, cls.c("bg"))
        p.setColor(QPalette.Base, cls.c("lane"))
        p.setColor(QPalette.AlternateBase, cls.c("header"))
        p.setColor(QPalette.Button, cls.c("card"))
        p.setColor(QPalette.WindowText, cls.c("text"))
        p.setColor(QPalette.Text, cls.c("text"))
        p.setColor(QPalette.ButtonText, cls.c("text"))
        p.setColor(QPalette.PlaceholderText, cls.c("muted"))
        p.setColor(QPalette.Highlight, cls.c("speech"))
        p.setColor(QPalette.HighlightedText, cls.c("onAccent"))
        p.setColor(QPalette.ToolTipBase, cls.c("card"))
        p.setColor(QPalette.ToolTipText, cls.c("text"))
        p.setColor(QPalette.Link, cls.c("speech"))
        return p

    @classmethod
    def stylesheet(cls) -> str:
        t, m, card, ink = (cls.c(k).name(QColor.HexArgb) for k in ("text", "muted", "card", "ink"))
        line = cls.c("ink", 0.12).name(QColor.HexArgb)
        fill = cls.c("ink", 0.06).name(QColor.HexArgb)
        acc = cls.c("speech").name()
        return f"""
        QDialog, QMenu {{ background: {card}; color: {t}; }}
        QMenu {{ border: 1px solid {line}; padding: 4px; border-radius: 8px; }}
        QMenu::item {{ padding: 5px 18px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {fill}; }}
        QMenu::item:disabled {{ color: {m}; }}
        QMenu::separator {{ height: 1px; background: {line}; margin: 4px 8px; }}
        QLabel[muted="true"] {{ color: {m}; }}
        QGroupBox {{ border: 1px solid {line}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {m}; font-weight: 600; }}
        QComboBox, QPushButton {{ background: {fill}; border: 1px solid {line}; border-radius: 6px; padding: 4px 10px; color: {t}; }}
        QPushButton:hover, QComboBox:hover {{ border-color: {acc}; }}
        QPushButton:disabled {{ color: {m}; }}
        QPushButton[accent="true"] {{ background: {acc}; color: {cls.c("onAccent").name()}; border: none; font-weight: 600; }}
        QComboBox QAbstractItemView {{ background: {card}; color: {t}; selection-background-color: {fill}; }}
        QSlider::groove:horizontal {{ height: 4px; background: {fill}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: {acc}; width: 14px; margin: -6px 0; border-radius: 7px; }}
        QSlider::sub-page:horizontal {{ background: {acc}; border-radius: 2px; }}
        QCheckBox {{ color: {t}; }}
        QProgressBar {{ background: {fill}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
        QProgressBar::chunk {{ background: {acc}; border-radius: 4px; }}
        QScrollArea {{ background: transparent; border: none; }}
        QToolTip {{ background: {card}; color: {t}; border: 1px solid {line}; padding: 4px; }}
        """ + f"/* {ink} */"


def ui_font(size: float, weight: QFont.Weight = QFont.Normal, mono: bool = False) -> QFont:
    if mono:
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    else:
        f = QFont(QGuiApplication.font())
    f.setPixelSize(max(6, round(size)))  # pixels, like the SwiftUI sizes of the Mac app
    f.setWeight(weight)
    return f


_SERIF = ("Didot", "Bodoni 72", "Bodoni MT", "Playfair Display", "GFS Didot", "Libre Bodoni", "Noto Serif Display",
          "Georgia", "Times New Roman", "DejaVu Serif")


def wordmark_font(size: float) -> QFont:
    families = set(QFontDatabase.families())
    fam = next((f for f in _SERIF if f in families), "serif")
    f = QFont(fam)
    f.setPixelSize(max(6, round(size)))
    f.setWeight(QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, size * 0.22)
    return f


MAC = sys.platform == "darwin"


def keys(spec: str) -> str:
    """'Ctrl+Shift+E' -> '⇧⌘E' on macOS, 'Ctrl+Shift+E' elsewhere."""
    if not MAC:
        return spec.replace("Return", "Enter")
    out = spec.replace("Ctrl+Shift+", "⇧⌘").replace("Ctrl+", "⌘").replace("Shift+", "⇧")
    return out.replace("Return", "↩").replace("Del", "⌫")
