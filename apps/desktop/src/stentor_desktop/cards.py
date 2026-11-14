"""Settings panel, about card (with Check for Updates), first-launch model setup and the guided tour."""

from __future__ import annotations

import json
import os
import platform
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import __version__, models
from .project import Project, settings
from .theme import Theme, keys, ui_font
from .tips import TipCard, Tips
from .widgets import PillButton, Wordmark, _shadow


class Links:
    wikipedia = "https://en.wikipedia.org/wiki/Stentor"
    sidon = "https://github.com/sarulab-speech/Sidon"
    issues = "https://github.com/PaoloSani/stentor/issues/new"
    releases = "https://github.com/PaoloSani/stentor/releases/latest"
    latest_api = os.environ.get("STENTOR_UPDATE_API", "https://api.github.com/repos/PaoloSani/stentor/releases/latest")

    @staticmethod
    def open(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))


def _label(text: str, size: float = 11, muted: bool = False, bold: bool = False, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(ui_font(size, QFont.DemiBold if bold else QFont.Normal))
    lbl.setWordWrap(wrap)
    lbl.setStyleSheet(f"color: {Theme.c('muted' if muted else 'text').name(QColor.HexArgb)}; background: transparent;")
    return lbl


class Overlay(QWidget):
    """Dims the window and swallows clicks; `card` is centred."""

    closed = Signal()

    def __init__(self, parent: QWidget, dismiss_on_click: bool = False):
        super().__init__(parent)
        self.dismiss = dismiss_on_click
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self._style_card()
        _shadow(self.card, 50, 10, 120)
        self.setGeometry(parent.rect())

    def _style_card(self) -> None:
        self.card.setStyleSheet(
            f"QFrame#card {{ background: {Theme.c('card').name(QColor.HexArgb)}; border-radius: 16px; "
            f"border: 1px solid {Theme.c('ink', 0.1).name(QColor.HexArgb)}; }}")

    def layout_card(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.card.adjustSize()
        sz = self.card.sizeHint()
        self.card.setGeometry((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2, sz.width(), sz.height())

    def resizeEvent(self, _e) -> None:
        self.layout_card()

    def paintEvent(self, _e) -> None:
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 115))

    def mousePressEvent(self, e) -> None:
        if self.dismiss and not self.card.geometry().contains(e.position().toPoint()):
            self.close_card()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape and self.dismiss:
            self.close_card()
        else:
            super().keyPressEvent(e)

    def close_card(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()


# ---------------------------------------------------------------------------------------------- updates


def is_newer(a: str, b: str) -> bool:
    def parts(v: str) -> list[int]:
        out = []
        for x in v.strip("vV").split("."):
            digits = "".join(ch for ch in x if ch.isdigit())
            out.append(int(digits or 0))
        return out + [0] * (3 - len(out))

    return parts(a) > parts(b)


class UpdateChecker(QObject):
    result = Signal(str, str)  # state ("latest" | "available" | "error"), detail (version or message)

    def check(self) -> None:
        current = os.environ.get("STENTOR_VERSION_OVERRIDE", __version__)

        def work():
            try:
                req = urllib.request.Request(Links.latest_api, headers={"User-Agent": "Stentor", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    tag = json.load(r)["tag_name"].lstrip("vV")
                self.result.emit("available" if is_newer(tag, current) else "latest", tag)
            except Exception as exc:
                self.result.emit("error", f"Couldn't check for updates ({exc.__class__.__name__}).")

        threading.Thread(target=work, daemon=True).start()


class AboutCard(Overlay):
    def __init__(self, parent: QWidget):
        super().__init__(parent, dismiss_on_click=True)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(34, 26, 34, 24)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignHCenter)
        logo = Wordmark(38, greek=True)
        logo.clicked.connect(lambda: Links.open(Links.wikipedia))
        logo.setToolTip("Stentor, herald of the Greeks in the Iliad — open Wikipedia")
        who = QPushButton("Who was Stentor? ↗")
        who.setFlat(True)
        who.setCursor(Qt.PointingHandCursor)
        who.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {Theme.c('muted').name(QColor.HexArgb)}; }}"
                          f"QPushButton:hover {{ color: {Theme.c('speech').name()}; text-decoration: underline; }}")
        who.clicked.connect(lambda: Links.open(Links.wikipedia))
        lay.addWidget(logo, 0, Qt.AlignHCenter)
        lay.addWidget(who, 0, Qt.AlignHCenter)
        lay.addWidget(_label("Voice restoration for Windows and Linux", 12, wrap=False), 0, Qt.AlignHCenter)
        line = QFrame()
        line.setFixedSize(220, 1)
        line.setStyleSheet(f"background: {Theme.c('ink', 0.08).name(QColor.HexArgb)};")
        lay.addWidget(line, 0, Qt.AlignHCenter)
        lay.addWidget(_label("Built by Paolo Sani", 12.5, bold=True, wrap=False), 0, Qt.AlignHCenter)
        powered = QLabel(f'Powered by <a style="color:{Theme.c("speech").name()}; text-decoration:none" href="{Links.sidon}">'
                         f"Sidon ↗</a> · University of Tokyo")
        powered.setFont(ui_font(11))
        powered.setStyleSheet(f"color: {Theme.c('muted').name(QColor.HexArgb)};")
        powered.setOpenExternalLinks(True)
        lay.addWidget(powered, 0, Qt.AlignHCenter)
        fb = PillButton("Send Feedback")
        fb.clicked.connect(lambda: Links.open(Links.issues))
        lay.addWidget(fb, 0, Qt.AlignHCenter)

        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        v = _label(f"Version {__version__}", 10.5, muted=True, wrap=False)
        v.setFont(ui_font(10.5, mono=True))
        self.check_btn = QPushButton("Check for Updates")
        self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.clicked.connect(self._check)
        row.addWidget(v)
        row.addWidget(self.check_btn)
        lay.addLayout(row)
        self.update_msg = _label("", 11)
        self.update_msg.setAlignment(Qt.AlignCenter)
        self.update_msg.setOpenExternalLinks(True)
        self.update_msg.setMaximumWidth(340)
        self.update_msg.hide()
        lay.addWidget(self.update_msg)
        close = QPushButton("✕", self.card)
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"QPushButton {{ border: none; border-radius: 11px; background: {Theme.c('ink', 0.06).name(QColor.HexArgb)};"
                            f" color: {Theme.c('muted').name(QColor.HexArgb)}; font-size: 10px; padding: 0; }}")
        close.clicked.connect(self.close_card)
        self._close = close
        self.checker = UpdateChecker(self)
        self.checker.result.connect(self._result)
        self.layout_card()
        self.setFocus()

    def layout_card(self) -> None:
        super().layout_card()
        if hasattr(self, "_close"):
            self._close.move(self.card.width() - 32, 10)

    def _check(self) -> None:
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Checking…")
        self.checker.check()

    def _result(self, state: str, detail: str) -> None:
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Check for Updates")
        if state == "available":
            self.update_msg.setText(f'<b>Stentor {detail} is available.</b> '
                                    f'<a style="color:{Theme.c("speech").name()}" href="{Links.releases}">Download</a>')
        elif state == "latest":
            self.update_msg.setText("You have the latest version.")
        else:
            self.update_msg.setText(detail)
        self.update_msg.show()
        self.layout_card()


# ---------------------------------------------------------------------------------------------- settings


class SettingsPanel(QDialog):
    """Popover-like panel under the gear: appearance, help, speech detection, processing, export, models."""

    def __init__(self, project: Project, parent: QWidget, on_theme: Callable[[], None], on_scale: Callable[[], None],
                 on_tips: Callable[[], None], on_locate: Callable[[], None]):
        super().__init__(parent, Qt.Popup)
        self.p = project
        self.setFixedWidth(392)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("settingsContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(4)
        self._content, self._scroll = content, scroll
        s = settings()

        def combo(items: list[tuple[str, str]], value: str, on: Callable[[str], None]) -> QComboBox:
            c = QComboBox()
            for k, lbl in items:
                c.addItem(lbl, k)
            c.setCurrentIndex(max(0, [k for k, _ in items].index(value) if value in [k for k, _ in items] else 0))
            c.currentIndexChanged.connect(lambda _i: on(c.currentData()))
            return c

        # appearance
        g = QGroupBox("Appearance")
        f = QFormLayout(g)

        def set_theme(v):
            Theme.mode = v
            s.setValue("appearance", v)
            on_theme()

        def set_scale(v):
            Theme.icon_scale = float(v)
            s.setValue("iconScale", float(v))
            on_scale()

        f.addRow("Theme", combo([("auto", "Auto (follow the system)"), ("dark", "Dark"), ("light", "Light")], Theme.mode, set_theme))
        f.addRow("Icon size", combo([("1.0", "Standard"), ("1.25", "Large"), ("1.5", "Extra large")],
                                    str(Theme.icon_scale) if str(Theme.icon_scale) in ("1.0", "1.25", "1.5") else "1.0", set_scale))
        root.addWidget(g)

        # help
        g = QGroupBox("Help")
        v = QVBoxLayout(g)
        cb = QCheckBox("Detailed tooltips")
        cb.setChecked(Theme.detailed_tips)

        def set_tips(on):
            Theme.detailed_tips = bool(on)
            s.setValue("detailedTooltips", bool(on))
            on_tips()

        cb.toggled.connect(set_tips)
        v.addWidget(cb)
        v.addWidget(_label("Hovering any control or part of the editor explains what it does, with shortcuts. "
                           "Off: short tooltips only.", 10.5, muted=True))
        root.addWidget(g)

        # detection
        g = QGroupBox("Speech detection")
        f = QFormLayout(g)
        d = project.detection
        for attr, label, lo, hi, step, fmt in (("threshold_db", "Threshold", -70, -20, 1, "{:.0f} dB"),
                                                ("pre_roll", "Pre-roll", 0, 0.5, 0.01, "{:.2f} s"),
                                                ("post_roll", "Post-roll", 0, 0.8, 0.01, "{:.2f} s"),
                                                ("merge_gap", "Merge gaps under", 0, 1.5, 0.01, "{:.2f} s")):
            f.addRow(label, self._slider(d, attr, lo, hi, step, fmt))
        row = QHBoxLayout()
        clear = QPushButton("Clear regions")
        clear.clicked.connect(project.clear_regions)
        again = QPushButton("Detect again")
        again.setEnabled(project.audio is not None)
        again.clicked.connect(project.detect)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(again)
        f.addRow(row)
        root.addWidget(g)

        # processing
        g = QGroupBox("Processing")
        f = QFormLayout(g)
        devs = [("auto", models.DEVICE_LABELS["auto"])] + [(k, models.DEVICE_LABELS[k]) for k in models.available_devices()]
        f.addRow("Run the model on", combo(devs, project.device, project.set_device))
        folder = str(project.models_folder) if project.models_folder else "not installed"
        lbl = _label(f"Model: {folder}", 10, muted=True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addRow(lbl)
        loc = QPushButton("Locate Models…")
        loc.clicked.connect(lambda: (self.close(), on_locate()))
        f.addRow(loc)
        root.addWidget(g)

        # export
        g = QGroupBox("Export")
        f = QFormLayout(g)

        def setter(attr):
            def set_(v):
                setattr(project, attr, v)
                project.save_settings()
            return set_

        f.addRow("Export", combo([("whole", "Whole file (same length as the original)"), ("regions", "Speech regions, one file each")],
                                 project.export_scope, setter("export_scope")))
        f.addRow("Sample rate", combo([("model", "48 kHz (model output)"), ("source", "Same as source")],
                                      project.export_rate, setter("export_rate")))
        f.addRow("Format", combo([("pcm16", "WAV 16-bit"), ("pcm24", "WAV 24-bit"), ("float32", "WAV 32-bit float")],
                                 project.export_format, setter("export_format")))
        root.addWidget(g)
        self.setStyleSheet(Theme.stylesheet() + f"QDialog {{ border: 1px solid {Theme.c('ink', 0.12).name(QColor.HexArgb)}; "
                                                 f"border-radius: 10px; }} QLabel {{ color: {Theme.c('text').name(QColor.HexArgb)}; }}"
                                                 f"QWidget#settingsContent {{ background: {Theme.c('card').name(QColor.HexArgb)}; }}")

    def fit(self, max_height: int) -> None:
        """Show everything when it fits, otherwise scroll within `max_height`."""
        self._content.adjustSize()
        self.setFixedHeight(min(self._content.sizeHint().height() + 4, max_height))

    def _slider(self, d, attr: str, lo: float, hi: float, step: float, fmt: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        sl = QSlider(Qt.Horizontal)
        n = round((hi - lo) / step)
        sl.setRange(0, n)
        sl.setValue(round((getattr(d, attr) - lo) / step))
        val = _label(fmt.format(getattr(d, attr)), 11, wrap=False)
        val.setFont(ui_font(11, mono=True))
        val.setFixedWidth(64)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def changed(i):
            x = lo + i * step
            setattr(d, attr, x)
            val.setText(fmt.format(x))
            self.p.save_settings()

        sl.valueChanged.connect(changed)
        h.addWidget(sl, 1)
        h.addWidget(val)
        return w


# ---------------------------------------------------------------------------------------------- model setup


class ModelSetup(Overlay):
    def __init__(self, parent: QWidget, project: Project, on_locate: Callable[[], None]):
        super().__init__(parent)
        self.p = project
        inst = project.installer
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignHCenter)
        title = _label("One more step: the voice model", 15, bold=True, wrap=False)
        lay.addWidget(title, 0, Qt.AlignHCenter)
        if inst.configured:
            text = ("Stentor restores speech with Sidon, a neural model of about 1 GB. It is downloaded once from GitHub, "
                    "verified and kept on this computer — app updates won't download it again.")
        else:
            text = ("Stentor restores speech with Sidon, a neural model of about 1 GB (feature_extractor.onnx and decoder.onnx). "
                    "Choose the folder that contains them, or export them with stentor-engine (stentor export onnx).")
        body = _label(text, 12)
        body.setAlignment(Qt.AlignCenter)
        body.setFixedWidth(400)
        lay.addWidget(body, 0, Qt.AlignHCenter)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(360)
        self.bar.hide()
        self.info = _label("", 11, muted=True, wrap=False)
        self.info.setAlignment(Qt.AlignCenter)
        self.info.hide()
        self.err = _label("", 11.5)
        self.err.setStyleSheet(f"color: {Theme.c('danger').name()};")
        self.err.setAlignment(Qt.AlignCenter)
        self.err.setFixedWidth(380)
        self.err.hide()
        lay.addWidget(self.bar, 0, Qt.AlignHCenter)
        lay.addWidget(self.info, 0, Qt.AlignHCenter)
        lay.addWidget(self.err, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        self.download = PillButton("Download (≈ 1 GB)", active=True)
        self.download.clicked.connect(self._download)
        self.cancel = PillButton("Cancel")
        self.cancel.clicked.connect(project.installer.cancel)
        self.cancel.hide()
        locate = PillButton("Locate Models…", active=not inst.configured)
        locate.clicked.connect(on_locate)
        if inst.configured:
            row.addWidget(self.download)
            row.addWidget(self.cancel)
        row.addWidget(locate)
        lay.addLayout(row)
        project.install_progress.connect(self._progress)
        self.layout_card()

    def _download(self) -> None:
        self.err.hide()
        self.download.hide()
        self.cancel.show()
        self.bar.show()
        self.info.show()
        self.p.install_models()

    def _progress(self, frac: float, text: str) -> None:
        if frac < 0:
            self.p.install_finished(False)
            self.cancel.hide()
            self.download.show()
            self.bar.hide()
            self.info.hide()
            self.err.setText(text)
            self.err.show()
        elif text == "done":
            self.p.install_finished(True)
        else:
            self.bar.setValue(int(frac * 1000))
            self.info.setText("Verifying and installing…" if frac >= 1 else text)
        self.layout_card()


# ---------------------------------------------------------------------------------------------- guided tour


@dataclass
class TourStep:
    target: str | None
    title: str
    body: str
    sample_tip: bool = False


def tour_steps() -> list[TourStep]:
    return [
        TourStep(None, "Welcome to Stentor",
                 "A one-minute tour of the app. A demo recording is open — J.F. Kennedy in a reverberant stadium — so you can "
                 "try everything right away."),
        TourStep("file", "Your recording",
                 "Name, format and how much of it is speech. Click here to open another file, or simply drop one onto the window."),
        TourStep("editor", "Green regions = speech",
                 "Only the green regions are restored; everything else stays silent and the output keeps the original length. "
                 "Click empty space to add a region, drag its edges to adjust, hover the top of an edge for ✕, right-click for more."),
        TourStep("ruler", "Ruler",
                 "Click to move the playhead. Drag to set a loop range — handy to compare a single phrase over and over."),
        TourStep("transport", "Play and loop", "Space plays and pauses, L toggles the loop (it starts on the first speech region)."),
        TourStep("ab", "Compare A / B",
                 "A is the original, level-matched; B is the restored voice. Press B to switch at the same position. "
                 "B unlocks after the first Enhance."),
        TourStep("view", "Waveform or spectrogram",
                 "S switches view. The spectrogram shows what the model does: noise and reverb fade, harmonics come back."),
        TourStep("enhance", "Enhance",
                 f"Restores every green region on your GPU, or the CPU when there is none ({keys('Ctrl+Return')}). "
                 "After editing, only the changed regions are processed again."),
        TourStep("export", "Export",
                 f"Saves a WAV with exactly the original length ({keys('Ctrl+E')}), or each speech region as its own file "
                 f"({keys('Ctrl+Shift+E')})."),
        TourStep("gear", "Tooltips and settings",
                 "Hover anything and a card like the one below explains it, with its shortcuts. You can turn them off here: "
                 "Settings › Help › Detailed tooltips — along with theme, icon size, detection and export options.", True),
        TourStep("logo", "That's it",
                 "Click the logo for credits, updates and feedback. You can replay this tour from Help › Show Tour."),
    ]


class TourOverlay(QWidget):
    """Dimmed window with a spotlight on the current target and a card explaining it."""

    def __init__(self, parent: QWidget, project: Project, anchor: Callable[[str], QRect | None]):
        super().__init__(parent)
        self.p, self.anchor = project, anchor
        self.steps = tour_steps()
        self.card: QFrame | None = None
        self.hole: QRectF | None = None
        self.setGeometry(parent.rect())

    def sync(self) -> None:
        i = self.p.tour_step
        if i is None or not (0 <= i < len(self.steps)):
            self.hide()
            return
        self.setGeometry(self.parentWidget().rect())
        step = self.steps[i]
        r = self.anchor(step.target) if step.target else None
        self.hole = QRectF(r).adjusted(-6, -6, 6, 6) if r is not None else None
        if self.card:
            self.card.deleteLater()
        self.card = self._card(step, i)
        self.card.adjustSize()
        self._place()
        self.card.show()
        self.show()
        self.raise_()
        self.update()

    def _card(self, step: TourStep, i: int) -> QFrame:
        card = QFrame(self)
        card.setObjectName("tour")
        card.setFixedWidth(340)
        card.setStyleSheet(f"QFrame#tour {{ background: {Theme.c('card').name(QColor.HexArgb)}; border-radius: 14px; "
                           f"border: 1px solid {Theme.c('speech', 0.5).name(QColor.HexArgb)}; }}")
        _shadow(card, 40, 8, 100)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        top = QHBoxLayout()
        n = _label(f"{i + 1} of {len(self.steps)}", 10.5, muted=True, wrap=False)
        n.setFont(ui_font(10.5, mono=True))
        skip = QPushButton("Skip tour")
        skip.setCursor(Qt.PointingHandCursor)
        skip.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {Theme.c('muted').name(QColor.HexArgb)}; }}")
        skip.clicked.connect(self.p.end_tour)
        top.addWidget(n)
        top.addStretch(1)
        top.addWidget(skip)
        lay.addLayout(top)
        lay.addWidget(_label(step.title, 15, bold=True))
        body = _label(step.body, 12)
        body.setStyleSheet(f"color: {Theme.c('text', 0.85).name(QColor.HexArgb)};")
        lay.addWidget(body)
        if step.sample_tip:
            tip = TipCard(Tips.enhance, width=306)
            tip.setGraphicsEffect(None)
            lay.addWidget(tip)
        row = QHBoxLayout()
        if i > 0:
            back = PillButton("Back")
            back.clicked.connect(lambda: self._go(i - 1))
            row.addWidget(back)
        row.addStretch(1)
        last = i == len(self.steps) - 1
        nxt = PillButton("Start using Stentor" if last else "Next", active=True)
        nxt.clicked.connect(self.p.end_tour if last else (lambda: self._go(i + 1)))
        row.addWidget(nxt)
        lay.addLayout(row)
        return card

    def _go(self, i: int) -> None:
        self.p.tour_step = i
        self.p.changed.emit()

    def _place(self) -> None:
        w, size = 340, self.size()
        h = self.card.sizeHint().height()
        if self.hole is None:
            self.card.setGeometry((size.width() - w) // 2, (size.height() - h) // 2, w, h)
            return
        hr = self.hole
        x = min(max(16, hr.center().x() - w / 2), size.width() - w - 16)
        if hr.height() > size.height() * 0.5:  # the editor: card inside it, near the top
            y = hr.top() + 40
        elif hr.center().y() < size.height() * 0.5:
            y = hr.bottom() + 14
        else:
            y = hr.top() - h - 14
        self.card.setGeometry(int(x), int(max(8, min(y, size.height() - h - 8))), w, h)

    def resizeEvent(self, _e) -> None:
        if self.p.tour_step is not None:
            self.sync()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if self.hole is not None:
            path.addRoundedRect(self.hole, 10, 10)
        path.setFillRule(Qt.OddEvenFill)
        p.fillPath(path, QColor(0, 0, 0, 158))
        if self.hole is not None:
            p.setPen(QPen(Theme.c("speech"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.hole, 10, 10)

    def mousePressEvent(self, e) -> None:
        e.accept()  # swallow clicks on the dimmed area

    def keyPressEvent(self, e) -> None:
        i = self.p.tour_step
        if i is None:
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right):
            self.p.end_tour() if i == len(self.steps) - 1 else self._go(i + 1)
        elif e.key() == Qt.Key_Left and i > 0:
            self._go(i - 1)
        elif e.key() == Qt.Key_Escape:
            self.p.end_tour()


def system_info() -> str:
    return f"{platform.system()} {platform.release()}"


__all__ = ["AboutCard", "Links", "ModelSetup", "QFileDialog", "QPointF", "QSize", "SettingsPanel", "TourOverlay", "system_info"]
