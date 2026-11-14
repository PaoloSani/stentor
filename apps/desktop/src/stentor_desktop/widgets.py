"""Window chrome: the floating control island, header with wordmark and file pill, empty state, toast."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import core, icons
from .project import Project, demo_path
from .theme import Theme, ui_font, wordmark_font
from .tips import TipCenter, Tips


def _shadow(w: QWidget, blur: int = 36, dy: int = 6, alpha: int = 90) -> None:
    eff = QGraphicsDropShadowEffect(w, blurRadius=blur, offset=QPointF(0, dy))
    eff.setColor(QColor(0, 0, 0, alpha))
    w.setGraphicsEffect(eff)


class RoundButton(QAbstractButton):
    """Round transport button."""

    def __init__(self, icon: str, size: float = 30, active: bool = False, tint: str = "text", parent=None):
        super().__init__(parent)
        self.icon_name, self.diameter, self.active, self.tint = icon, size, active, tint
        self.setFixedSize(QSize(round(size), round(size)))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        down = self.isDown()
        if self.active:
            p.setBrush(Theme.c(self.tint))
        else:
            p.setBrush(Theme.c("ink", 0.18 if down else 0.12 if self.underMouse() else 0.08))
        p.setPen(Qt.NoPen)
        p.drawEllipse(r)
        on = "inverse" if self.tint == "text" else "onAccent"
        col = Theme.c(on) if self.active else Theme.c("text")
        if not self.isEnabled():
            col.setAlphaF(0.35)
        icons.draw(p, self.icon_name, r.adjusted(r.width() * 0.22, r.height() * 0.22, -r.width() * 0.22, -r.height() * 0.22), col)


class PillButton(QAbstractButton):
    """Rounded control with optional icon, text, progress ring and status dot."""

    def __init__(self, text: str = "", icon: str | None = None, active: bool = False, scale: float = 1.0, parent=None):
        super().__init__(parent)
        self.label, self.icon_name, self.active, self.s = text, icon, active, scale
        self.progress: float | None = None
        self.dot = False
        self.setCursor(Qt.PointingHandCursor)
        self._resize()

    def set(self, text: str | None = None, icon: str | None = None, active: bool | None = None,
            progress: float | None = None, dot: bool = False) -> None:
        if text is not None:
            self.label = text
        if icon is not None:
            self.icon_name = icon
        if active is not None:
            self.active = active
        self.progress, self.dot = progress, dot
        self._resize()
        self.update()

    def _text(self) -> str:
        return f"{int((self.progress or 0) * 100)}%" if self.progress is not None else self.label

    def _resize(self) -> None:
        s = self.s
        f = ui_font(11 * s, QFont.DemiBold, mono=self.progress is not None)
        self.setFont(f)
        tw = self.fontMetrics().horizontalAdvance(self._text()) if self._text() else 0
        w = 9 * s * 2 + tw
        if self.icon_name or self.progress is not None:
            w += 14 * s + (5 * s if tw else 0)
        if self.progress is not None:
            w += 14 * s
        if self.dot:
            w += 11 * s
        self.setFixedSize(QSize(round(w), round(26 * s)))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.s
        r = QRectF(self.rect())
        if self.active and self.isEnabled():
            p.setBrush(Theme.c("speech"))
        else:
            p.setBrush(Theme.c("ink", 0.16 if self.isDown() else 0.11 if self.underMouse() and self.isEnabled() else 0.07))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 7 * s, 7 * s)
        col = Theme.c("onAccent") if self.active and self.isEnabled() else Theme.c("text")
        if not self.isEnabled():
            col.setAlphaF(0.35)
        x = 9 * s
        cy = r.center().y()
        if self.progress is not None:
            ring = QRectF(x, cy - 6 * s, 12 * s, 12 * s)
            p.setPen(QPen(Theme.c("ink", 0.15), 2 * s))
            p.drawEllipse(ring)
            p.setPen(QPen(Theme.c("speech"), 2 * s, cap=Qt.RoundCap))
            p.drawArc(ring, 90 * 16, -int(360 * 16 * max(0.0, min(1.0, self.progress))))
            x += 19 * s
        elif self.icon_name:
            icons.draw(p, self.icon_name, QRectF(x - 1 * s, cy - 8 * s, 16 * s, 16 * s), col)
            x += 19 * s if self._text() else 14 * s
        if self._text():
            p.setPen(col)
            p.setFont(self.font())
            tw = self.fontMetrics().horizontalAdvance(self._text())
            p.drawText(QRectF(x, 0, tw + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text())
            x += tw + 6 * s
        if self.progress is not None:
            icons.draw(p, "close", QRectF(x - 2 * s, cy - 6 * s, 12 * s, 12 * s), col)
        if self.dot:
            p.setPen(Qt.NoPen)
            p.setBrush(Theme.c("loop"))
            p.drawEllipse(QPointF(x + 1 * s, cy), 3 * s, 3 * s)


class Segmented(QWidget):
    """Two-option switch (A/B, WAVE/SPEC)."""

    picked = Signal(str)

    def __init__(self, options: list[tuple[str, str]], scale: float = 1.0, parent=None):
        super().__init__(parent)
        self.options, self.s = options, scale
        self.value = options[0][0]
        self.disabled: set[str] = set()
        self.setFont(ui_font(10.5 * scale, QFont.Bold))
        fm = self.fontMetrics()
        self._widths = [fm.horizontalAdvance(lbl) + 18 * scale for _, lbl in options]
        self.setFixedSize(QSize(round(sum(self._widths) + 4 * scale), round(26 * scale)))
        self.setCursor(Qt.PointingHandCursor)

    def set(self, value: str, disabled: set[str] = frozenset()) -> None:
        self.value, self.disabled = value, set(disabled)
        self.update()

    def _segments(self):
        x = 2 * self.s
        for (v, lbl), w in zip(self.options, self._widths):
            yield v, lbl, QRectF(x, 2 * self.s, w, self.height() - 4 * self.s)
            x += w

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.s
        p.setPen(Qt.NoPen)
        p.setBrush(Theme.c("ink", 0.06))
        p.drawRoundedRect(QRectF(self.rect()), 7 * s, 7 * s)
        p.setFont(self.font())
        for v, lbl, r in self._segments():
            sel = v == self.value
            if sel:
                p.setBrush(Theme.c("text"))
                p.drawRoundedRect(r, 5 * s, 5 * s)
            col = Theme.c("inverse") if sel else Theme.c("muted")
            if v in self.disabled:
                col.setAlphaF(0.35)
            p.setPen(col)
            p.drawText(r, Qt.AlignCenter, lbl)
            p.setPen(Qt.NoPen)

    def mousePressEvent(self, e) -> None:
        for v, _lbl, r in self._segments():
            if r.contains(e.position()) and v not in self.disabled:
                self.picked.emit(v)


class Divider(QWidget):
    def __init__(self, scale: float, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(1, round(22 * scale)))

    def paintEvent(self, _e) -> None:
        QPainter(self).fillRect(self.rect(), Theme.c("ink", 0.1))


class Island(QWidget):
    """Floating control island, centred at the bottom of the editor."""

    def __init__(self, project: Project, tips: TipCenter, parent=None):
        super().__init__(parent)
        self.p, self.tips = project, tips
        self.anchors: dict[str, QWidget] = {}
        self._build()
        project.changed.connect(self.refresh)

    def _build(self) -> None:
        s = Theme.icon_scale
        self.s = s
        if self.layout():
            QWidget().setLayout(self.layout())  # drop the old layout and its children
        lay = QHBoxLayout(self)
        lay.setContentsMargins(round(12 * s), round(8 * s), round(12 * s), round(8 * s))
        lay.setSpacing(round(12 * s))

        transport = QWidget()
        tl = QHBoxLayout(transport)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(round(6 * s))
        self.to_start = RoundButton("to_start", 28 * s)
        self.play = RoundButton("play", 36 * s, active=True, tint="text")
        self.loop = RoundButton("loop", 28 * s, tint="loop")
        for b in (self.to_start, self.play, self.loop):
            tl.addWidget(b)
        self.to_start.clicked.connect(self.p.go_to_start)
        self.play.clicked.connect(self.p.toggle_play)
        self.loop.clicked.connect(self.p.toggle_loop)

        timebox = QWidget()
        vl = QVBoxLayout(timebox)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.time = QLabel("0:00.00")
        self.time.setFont(ui_font(14 * s, QFont.DemiBold, mono=True))
        self.length = QLabel("0:00.00")
        self.length.setFont(ui_font(9.5 * s, mono=True))
        vl.addWidget(self.time)
        vl.addWidget(self.length)
        timebox.setFixedWidth(round(80 * s))

        self.ab = Segmented([("A", "A"), ("B", "B")], s)
        self.ab.picked.connect(self.p.set_source)
        self.view = Segmented([("wave", "WAVE"), ("spec", "SPEC")], s)
        self.view.picked.connect(self.p.set_view_mode)
        self.enhance = PillButton("Enhance", "wand", active=True, scale=s)
        self.enhance.clicked.connect(self._enhance_clicked)
        self.export = PillButton("", "export", scale=s)

        lay.addWidget(transport)
        lay.addWidget(timebox)
        lay.addWidget(Divider(s))
        lay.addWidget(self.ab)
        lay.addWidget(self.view)
        lay.addWidget(Divider(s))
        lay.addWidget(self.enhance)
        lay.addWidget(self.export)

        self.anchors = {"transport": transport, "ab": self.ab, "view": self.view, "enhance": self.enhance,
                        "export": self.export}
        for w, info in ((self.to_start, Tips.to_start), (self.play, Tips.play), (self.loop, Tips.loop),
                        (timebox, Tips.time), (self.ab, Tips.ab), (self.view, Tips.view), (self.enhance, Tips.enhance),
                        (self.export, Tips.export)):
            self.tips.attach(w, info)
        _shadow(self)
        self.refresh()
        self.adjustSize()

    def rebuild(self) -> None:
        self._build()

    def _enhance_clicked(self) -> None:
        p = self.p
        if p.processing:
            p.cancel()
        elif p.enhanced_stale or p.enhanced is None:
            p.enhance()
        else:
            p.enhance_all()

    def refresh(self) -> None:
        p = self.p
        text, muted = Theme.c("text").name(QColor.HexArgb), Theme.c("muted").name(QColor.HexArgb)
        self.time.setStyleSheet(f"color: {text};")
        self.length.setStyleSheet(f"color: {muted};")
        self.play.icon_name = "pause" if p.player.playing else "play"
        self.loop.active = p.loop_enabled
        self.ab.set(p.source, {"B"} if p.enhanced is None else set())
        self.view.set(p.view_mode)
        self.length.setText(core.timecode(p.duration, 0.01))
        if p.processing:
            self.enhance.set(active=False, progress=p.progress)
            self.enhance.setEnabled(True)
        else:
            if p.enhanced is None:
                label = "Enhance"
            elif p.enhanced_stale:
                n = len(p.stale_regions)
                label = f"Update {n}" if n else "Update"
            else:
                label = "Re-enhance"
            self.enhance.set(label, "wand", active=True, progress=None, dot=p.enhanced_stale)
            self.enhance.setEnabled(p.audio is not None and bool(p.regions))
        self.export.setEnabled(p.enhanced is not None and not p.processing)
        for b in (self.to_start, self.play, self.loop):
            b.setEnabled(p.audio is not None)
            b.update()
        self.tick()
        self.adjustSize()

    def tick(self) -> None:
        self.time.setText(core.timecode(self.p.player.time, 0.01))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(Theme.c("island"))
        p.setPen(QPen(Theme.c("ink", 0.11), 1))
        p.drawRoundedRect(r, 18 * self.s, 18 * self.s)


class Toast(QWidget):
    """Status / error capsule shown above the island."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.is_error = False
        self.on_close: Callable[[], None] | None = None
        self.setFont(ui_font(11))
        self.hide()

    def show_message(self, text: str | None, error: bool = False) -> None:
        if not text:
            self.hide()
            return
        self.text, self.is_error = text, error
        fm = self.fontMetrics()
        w = min(fm.horizontalAdvance(text) + (13 + 18 + 26 + 6 if error else 13 + 26 + 6), 640)
        self.setFixedSize(w, 28)
        self.setCursor(Qt.PointingHandCursor if error else Qt.ArrowCursor)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(Theme.c("card"))
        p.setPen(QPen(Theme.c("ink", 0.1), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = 13
        if self.is_error:
            icons.draw(p, "warning", QRectF(x - 2, 6, 16, 16), Theme.c("danger"))
            x += 18
            icons.draw(p, "close", QRectF(r.right() - 22, 8, 12, 12), Theme.c("muted"))
        p.setPen(Theme.c("text"))
        p.setFont(self.font())
        p.drawText(QRectF(x, 0, r.width() - x - (26 if self.is_error else 12), r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.fontMetrics().elidedText(self.text, Qt.ElideRight, int(r.width() - x - 26)))

    def mousePressEvent(self, _e) -> None:
        if self.is_error and self.on_close:
            self.on_close()


class Wordmark(QAbstractButton):
    """The STENTOR wordmark: Didot-like capitals, wide tracking, mint-to-green gradient."""

    def __init__(self, size: float = 25, greek: bool = False, parent=None):
        super().__init__(parent)
        self.size_, self.greek = size, greek
        self.setFont(wordmark_font(size))
        fm = self.fontMetrics()
        w = fm.horizontalAdvance("STENTOR") + 4
        h = fm.height() + (size * 0.7 if greek else 0)
        self.setFixedSize(QSize(round(w), round(h)))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        fm = self.fontMetrics()
        g = QLinearGradient(0, 0, 0, fm.height())
        g.setColorAt(0, Theme.c("wordTop"))
        g.setColorAt(1, Theme.c("wordBottom"))
        p.setPen(QPen(g, 1))
        p.setFont(self.font())
        p.drawText(QRectF(0, 0, self.width(), fm.height()), Qt.AlignHCenter | Qt.AlignTop, "STENTOR")
        if self.greek:
            f = QFont(self.font())
            f.setWeight(QFont.Medium)
            f.setPixelSize(round(self.size_ * 0.46))
            f.setLetterSpacing(QFont.AbsoluteSpacing, self.size_ * 0.04)
            p.setFont(f)
            p.setPen(Theme.c("text", 0.78))
            p.drawText(QRectF(0, fm.height() + self.size_ * 0.08, self.width(), self.size_ * 0.6), Qt.AlignHCenter | Qt.AlignTop,
                       "Στέντωρ")


class FilePill(QAbstractButton):
    """File name + details, centred in the header; clicking opens another file."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.p = project
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        project.changed.connect(self._update)
        project.view_changed.connect(self._update)

    def _meta(self) -> str:
        a, p = self.p.audio, self.p
        n = len(p.regions)
        ch = "mono" if a.channels == 1 else f"{a.channels} ch"
        return (f"{a.source_rate / 1000:.1f} kHz · {ch} · {core.timecode(a.duration, 0.1)} · "
                f"{p.speech_seconds:.1f} s speech in {n} region{'' if n == 1 else 's'}")

    def _update(self) -> None:
        if self.p.audio is None:
            self.hide()
            return
        self.show()
        f1, f2 = ui_font(12.5, QFont.DemiBold), ui_font(10.5, mono=True)
        from PySide6.QtGui import QFontMetrics

        w = max(QFontMetrics(f1).horizontalAdvance(self.p.file_name), QFontMetrics(f2).horizontalAdvance(self._meta()))
        self.setFixedWidth(min(560, round(w + 6 + 28 * Theme.icon_scale + 10 + 14 + 4)))
        self.update()

    def paintEvent(self, _e) -> None:
        if self.p.audio is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hov = self.underMouse()
        if hov:
            p.setBrush(Theme.c("ink", 0.06))
            p.setPen(QPen(Theme.c("ink", 0.12), 1))
            p.drawRoundedRect(r, 10, 10)
        s = Theme.icon_scale
        box = QRectF(6, (r.height() - 28 * s) / 2, 28 * s, 28 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(Theme.c("ink", 0.1 if hov else 0.05))
        p.drawRoundedRect(box, 7, 7)
        icons.draw(p, "folder", box.adjusted(6 * s, 6 * s, -6 * s, -6 * s), Theme.c("speech") if hov else Theme.c("muted"))
        x = box.right() + 10
        p.setPen(Theme.c("text"))
        p.setFont(ui_font(12.5, QFont.DemiBold))
        p.drawText(QRectF(x, 4, r.width() - x - 10, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.p.file_name, Qt.ElideMiddle, int(r.width() - x - 10)))
        p.setPen(Theme.c("muted"))
        p.setFont(ui_font(10.5, mono=True))
        p.drawText(QRectF(x, 21, r.width() - x - 10, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self._meta(), Qt.ElideRight, int(r.width() - x - 10)))

    def enterEvent(self, _e) -> None:
        self.update()

    def leaveEvent(self, _e) -> None:
        self.update()


class GearButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.open = False
        self.setCursor(Qt.PointingHandCursor)
        self.rescale()

    def rescale(self) -> None:
        s = Theme.icon_scale
        self.setFixedSize(QSize(round(30 * s), round(26 * s)))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(Theme.c("ink", 0.14 if self.open or self.isDown() else 0.1 if self.underMouse() else 0.06))
        p.drawRoundedRect(r, 6, 6)
        s = min(r.width(), r.height()) * 0.62
        icons.draw(p, "gear", QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), Theme.c("text"))


class Header(QWidget):
    def __init__(self, project: Project, tips: TipCenter, parent=None):
        super().__init__(parent)
        self.p = project
        self.setFixedHeight(56)
        self.logo = Wordmark(25)
        self.status = QLabel(project.model_status)
        self.status.setFont(ui_font(10.5))
        self.gear = GearButton()
        self.file = FilePill(project, self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 14, 0)
        lay.setSpacing(18)
        lay.addWidget(self.logo)
        lay.addStretch(1)
        lay.addWidget(self.status)
        lay.addWidget(self.gear)
        tips.attach(self.logo, Tips.logo)
        tips.attach(self.gear, Tips.gear)
        tips.attach(self.file, Tips.file_info)
        project.model_changed.connect(lambda: self.status.setText(project.model_status))
        project.changed.connect(self._place_file)
        self.file.hide()

    def _place_file(self) -> None:
        self.file._update()
        self.file.move((self.width() - self.file.width()) // 2, (self.height() - self.file.height()) // 2)

    def resizeEvent(self, _e) -> None:
        self._place_file()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Theme.c("header"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), Theme.c("ink", 0.07))

    def retheme(self) -> None:
        self.status.setStyleSheet(f"color: {Theme.c('muted').name(QColor.HexArgb)};")
        self.gear.rescale()
        self.update()


class EmptyState(QWidget):
    open_clicked = Signal()
    demo_clicked = Signal()

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.p = project
        self.highlight = False
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(14)
        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        self.title = QLabel("Drop a voice recording here")
        self.title.setFont(ui_font(16, QFont.Medium))
        self.title.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        self.open_btn = PillButton("Open…", active=True)
        self.demo_btn = PillButton("Try the demo")
        self.open_btn.clicked.connect(self.open_clicked)
        self.demo_btn.clicked.connect(self.demo_clicked)
        row.addWidget(self.open_btn)
        if demo_path():
            row.addWidget(self.demo_btn)
        self.sub = QLabel("Speech is detected automatically and shown in green — only those parts are restored;\n"
                          "the rest stays silent and the output keeps the original length.")
        self.sub.setFont(ui_font(11))
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.icon, 0, Qt.AlignCenter)
        lay.addWidget(self.title)
        lay.addLayout(row)
        lay.addWidget(self.sub)
        project.changed.connect(self._update)

    def _update(self) -> None:
        self.title.setText(self.p.status if self.p.loading else "Drop a voice recording here")
        self.open_btn.setVisible(not self.p.loading)
        self.demo_btn.setVisible(not self.p.loading and demo_path() is not None)
        self.sub.setVisible(not self.p.loading)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), Theme.c("bg"))
        pen = QPen(Theme.c("speech") if self.highlight else Theme.c("ink", 0.1), 1.5, Qt.CustomDashLine)
        pen.setDashPattern([4, 3.3])
        p.setPen(pen)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(24, 24, -24, -84), 14, 14)
        ir = QRectF(self.icon.geometry())
        icons.draw(p, "waveform", ir, Theme.c("speech"))

    def retheme(self) -> None:
        self.title.setStyleSheet(f"color: {Theme.c('text').name(QColor.HexArgb)};")
        self.sub.setStyleSheet(f"color: {Theme.c('muted').name(QColor.HexArgb)};")
        self.update()
