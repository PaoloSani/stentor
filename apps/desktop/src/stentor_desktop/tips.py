"""Detailed hover help: a card for every control and part of the editor, one at a time, after a short delay."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import Theme, keys, ui_font


@dataclass(frozen=True)
class TipInfo:
    id: str
    title: str
    body: str
    shortcuts: tuple[tuple[str, str], ...] = field(default=())
    hint: str | None = None

    @property
    def short(self) -> str:
        return self.title + (f" ({self.shortcuts[0][0]})" if self.shortcuts else "")


def _k(spec: str) -> str:
    return keys(spec)


class Tips:
    logo = TipInfo("logo", "About Stentor",
                   "Opens the about card: credits, the Sidon model this app is built on, updates and feedback.")
    file_info = TipInfo(
        "fileInfo", "Open another file",
        "Click to load a different recording. Shown here: name, sample rate, channels and length of the current file, "
        "plus how much of it is speech (the green regions that will be processed).",
        ((_k("Ctrl+O"), "open another file"), ("drop", "drag a file onto the window")))
    gear = TipInfo("gear", "Settings",
                   "Theme, icon size, tooltips, speech-detection sensitivity (threshold, pre/post-roll, gap merging), "
                   "processing device and export format.", ((_k("Ctrl+,"), "open settings"),))
    cancel = TipInfo("cancel", "Cancel", "Progress of the running enhancement. Click to stop it; the previous result (if any) is kept.")
    to_start = TipInfo("toStart", "Go to start",
                       "Moves the playhead to the beginning of the file, or to the start of the loop when looping is on.",
                       (("Home", "go to start"),))
    play = TipInfo("play", "Play / Pause",
                   "Plays from the playhead. What you hear depends on the A/B switch: the original (level-matched) or the enhanced result.",
                   (("Space", "play / pause"),))
    loop = TipInfo("loop", "Loop",
                   "Repeats a range seamlessly. By default it loops the first speech region (or the selected one); "
                   "drag on the ruler to loop any other range.",
                   (("L", "loop on / off"), ("drag ruler", "set range"), ("double-click ruler", "clear range")))
    time = TipInfo("time", "Position / Length",
                   "Current playhead position and total length of the file. The enhanced output always has exactly the same length.")
    ab = TipInfo("ab", "A / B comparison",
                 "A plays the original, peak-normalised so the comparison is fair; B plays the enhanced result. Switching keeps "
                 "the playhead, so you hear the same word both ways. B is available after the first Enhance.",
                 (("B", "swap A / B"),))
    view = TipInfo("view", "Waveform / Spectrogram",
                   "Waveform shows level over time. Spectrogram shows frequencies (log scale, 40 Hz at the bottom) — useful to "
                   "see noise, hum or missing highs before and after.", (("S", "switch view"),))
    enhance = TipInfo(
        "enhance", "Enhance",
        "Runs Sidon on the green regions and builds the full-length output: speech restored to 48 kHz studio quality, "
        "silence everywhere else. After the first run only changed regions (amber top edge) are processed again — the "
        "button shows how many.",
        ((_k("Ctrl+Return"), "enhance changed"), (_k("Ctrl+Shift+Return"), "selected region only"), ("right-click", "region menu")),
        "When nothing changed, the button re-renders everything from scratch.")
    export = TipInfo(
        "export", "Export",
        "Saves the enhanced audio as a mono WAV with exactly the same length as the original, so it lines up in your DAW. "
        "Sample rate, bit depth and whether to export the whole file or each speech region as its own file are set in "
        "Settings (default: whole file, 48 kHz, 24-bit).",
        ((_k("Ctrl+E"), "export"), (_k("Ctrl+Shift+E"), "speech regions, one file each")))
    overview = TipInfo("overview", "Overview",
                       "The whole file with its green regions; the frame is the part shown above. Click or drag to jump there.")
    ruler = TipInfo("ruler", "Ruler", "Click to move the playhead. Drag to select a loop range (shown in amber).",
                    (("click", "seek"), ("drag", "set loop"), ("double-click", "clear loop")))
    empty = TipInfo("empty", "Add a region",
                    "Click to add a green region starting here and ending just before the next one (or at the end of the file). "
                    "Drag instead to draw a region of exactly that span.", (("click", "add up to next"), ("drag", "draw region")))
    region = TipInfo("region", "Green region",
                     "This span will be restored by the model. Click to select it and move the playhead here.",
                     (("click", "select + seek"), ("right-click", "enhance / loop / delete"), (_k("Ctrl+click"), "remove"),
                      ("Delete", "remove selected")))
    bar = TipInfo("bar", "Region edge",
                  "Drag to move the start or end of the region; it stops at the neighbouring regions. Hover the top of the bar "
                  "to reveal the ✕.", (("drag", "adjust"), (_k("Ctrl+click"), "remove region")))
    bar_x = TipInfo("barX", "Remove region", "Deletes this green region; that span will stay silent in the output.",
                    ((_k("Ctrl+Z"), "undo"),))


class TipCard(QFrame):
    WIDTH = 290

    def __init__(self, info: TipInfo, parent: QWidget | None = None, width: int = WIDTH):
        super().__init__(parent)
        self.setObjectName("tipcard")
        self.setFixedWidth(width)
        inner = width - 22
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 10, 11, 10)
        lay.setSpacing(6)
        title = QLabel(info.title)
        title.setFont(ui_font(12, weight=QFont.DemiBold))
        body = QLabel(info.body)
        body.setWordWrap(True)
        body.setFixedWidth(inner)
        body.setFont(ui_font(11))
        lay.addWidget(title)
        lay.addWidget(body)
        text, muted, line = Theme.c("text").name(), Theme.c("muted").name(QColor.HexArgb), Theme.c("ink", 0.12).name(QColor.HexArgb)
        for k, action in info.shortcuts:
            row = QHBoxLayout()
            row.setSpacing(6)
            kl = QLabel(k)
            kl.setFont(ui_font(10, weight=QFont.Medium))
            kl.setStyleSheet(f"background: {Theme.c('ink', 0.1).name(QColor.HexArgb)}; border: 1px solid {line}; "
                             f"border-radius: 3px; padding: 0 4px; color: {text};")
            al = QLabel(action)
            al.setFont(ui_font(10.5))
            al.setStyleSheet(f"color: {muted};")
            row.addWidget(kl)
            row.addWidget(al, 1)
            lay.addLayout(row)
        if info.hint:
            h = QLabel("💡 " + info.hint)
            h.setWordWrap(True)
            h.setFixedWidth(inner)
            h.setFont(ui_font(10.5))
            h.setStyleSheet(f"color: {muted};")
            lay.addWidget(h)
        self.setStyleSheet(
            f"QFrame#tipcard {{ background: {Theme.c('card').name(QColor.HexArgb)}; border: 1px solid {line}; border-radius: 9px; }}"
            f"QFrame#tipcard QLabel {{ color: {text}; background: transparent; }}")
        title.setStyleSheet(f"color: {text}; background: transparent;")
        body.setStyleSheet(f"color: {Theme.c('text', 0.8).name(QColor.HexArgb)}; background: transparent;")
        shadow = QGraphicsDropShadowEffect(self, blurRadius=24, offset=QPoint(0, 4))
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)
        self.adjustSize()


class TipCenter(QObject):
    """Shows one card at a time over `host` (the window's central widget)."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.card: TipCard | None = None
        self.current: TipInfo | None = None
        self._pending: tuple[TipInfo, QPoint] | None = None
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._show_pending)
        self._suppressed = False
        self._attached: dict[QWidget, TipInfo] = {}

    @property
    def suppressed(self) -> bool:
        return self._suppressed

    @suppressed.setter
    def suppressed(self, v: bool) -> None:
        self._suppressed = v
        if v:
            self.hide()

    def attach(self, widget: QWidget, info: TipInfo) -> None:
        self._attached[widget] = info
        widget.installEventFilter(self)
        widget.setToolTip("" if Theme.detailed_tips else info.short)

    def refresh_mode(self) -> None:
        for w, info in list(self._attached.items()):
            try:
                w.setToolTip("" if Theme.detailed_tips else info.short)
            except RuntimeError:  # widget deleted (island rebuilt)
                del self._attached[w]
        self.hide()

    def eventFilter(self, obj, ev) -> bool:
        info = self._attached.get(obj)
        if info is not None:
            t = ev.type()
            if t == QEvent.Enter:
                w: QWidget = obj
                p = w.mapTo(self.host, QPoint(w.width() // 2, w.height() // 2))
                anchor = QPoint(p.x(), p.y() - w.height() // 2 if p.y() > self.host.height() * 0.55 else p.y() + w.height() // 2)
                self.hover(info, anchor)
            elif t in (QEvent.Leave, QEvent.MouseButtonPress):
                self.leave(info.id)
        return False

    def hover(self, info: TipInfo, at: QPoint) -> None:
        if not Theme.detailed_tips or self._suppressed:
            self.hide()
            return
        if self.current and self.current.id == info.id:
            return
        self._pending = (info, at)
        self._timer.start(550 if self.current is None else 120)

    def leave(self, tid: str) -> None:
        if self._pending and self._pending[0].id == tid:
            self._timer.stop()
            self._pending = None
        if self.current and self.current.id == tid:
            self.hide()

    def hide(self) -> None:
        self._timer.stop()
        self._pending = None
        self.current = None
        if self.card:
            self.card.deleteLater()
            self.card = None

    def show_now(self, info: TipInfo, at: QPoint) -> None:
        self._pending = (info, at)
        self._show_pending()

    def _show_pending(self) -> None:
        if not self._pending or self._suppressed:
            return
        info, at = self._pending
        self._pending = None
        if self.card:
            self.card.deleteLater()
        self.card = TipCard(info, self.host)
        self.current = info
        w, h = self.card.width(), self.card.sizeHint().height()
        above = at.y() > self.host.height() * 0.55
        x = min(max(8, at.x() - w // 2), self.host.width() - w - 8)
        y = at.y() - h - 14 if above else at.y() + 18
        self.card.move(x, max(8, min(y, self.host.height() - h - 8)))
        self.card.show()
        self.card.raise_()
