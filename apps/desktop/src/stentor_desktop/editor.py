"""The editor canvas (ruler, waveform / spectrogram, green regions, loop, playhead) and the overview strip."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from . import core
from .project import Project
from .theme import RULER_H, Theme, ui_font
from .tips import TipCenter, Tips


class EditorWidget(QWidget):
    def __init__(self, project: Project, tips: TipCenter | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.p = project
        self.tips = tips
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumHeight(160)
        self.hover_bar: tuple[int, bool] | None = None
        self.over_x = False
        self.drag_preview: tuple[float, float] | None = None
        self.loop_preview: tuple[float, float] | None = None
        self._drag: tuple | None = None  # ("ruler", anchor, moved) | ("edge", id, is_start) | ("create", anchor, moved) | ("inside", id, t)
        self._img_cache: tuple[int, QImage] | None = None
        self._tip_id: str | None = None
        project.view_changed.connect(self.update)
        project.spec_ready.connect(self.update)
        self.grabGesture(Qt.PinchGesture)

    # ---- geometry --------------------------------------------------------------------

    def ruler_rect(self) -> QRectF:
        return QRectF(0, 0, self.width(), RULER_H)

    def lane_rect(self) -> QRectF:
        return QRectF(0, RULER_H, self.width(), self.height() - RULER_H)

    def x_of(self, t: float) -> float:
        return (t - self.p.visible_start) / self.p.visible_duration * self.width()

    def time_at(self, x: float) -> float:
        return min(self.p.duration, max(0.0, self.p.visible_start + x / max(1, self.width()) * self.p.visible_duration))

    def resizeEvent(self, e) -> None:
        self.p.editor_width = self.width()
        self.p.request_spectrogram()

    @property
    def blocked(self) -> bool:
        return self.p.needs_models or self.p.tour_step is not None

    # ---- drawing ---------------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        lane = self.lane_rect()
        pr = self.p
        p.fillRect(lane, Theme.c("lane"))
        if pr.audio is None:
            return
        t0, t1 = pr.visible_start, pr.visible_start + pr.visible_duration
        s = Theme.icon_scale

        # signal
        if pr.view_mode == "spec":
            tile = pr.display_spec
            if tile is not None:
                img = self._image(tile)
                x0, x1 = self.x_of(tile.t0), self.x_of(tile.t1)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawImage(QRectF(x0, lane.top(), x1 - x0, lane.height()), img)
            else:
                p.setPen(Theme.c("muted"))
                p.setFont(ui_font(11))
                p.drawText(lane, Qt.AlignCenter, "Computing spectrogram…")
        elif pr.display_peaks is not None:
            dpr = self.devicePixelRatioF()
            cols = int(w * dpr)
            mn, mx = pr.display_peaks.columns(t0, t1, cols)
            mid, amp = lane.center().y(), lane.height() / 2 * 0.92
            xs = (np.arange(mn.shape[0]) + 0.5) / dpr
            pen = QPen(Theme.c("waveEnh" if pr.source == "B" else "wave"), 1 / dpr)
            p.setPen(pen)
            path = QPainterPath()
            top, bot = mid - mx * amp, mid - mn * amp + 0.5
            for x, a, b in zip(xs.tolist(), top.tolist(), bot.tolist()):
                path.moveTo(x, a)
                path.lineTo(x, b)
            p.drawPath(path)
            p.fillRect(QRectF(0, mid, w, 1), Theme.c("grid"))

        p.setRenderHint(QPainter.Antialiasing)
        # loop
        loop = self.loop_preview or pr.loop_range
        if loop:
            on = pr.loop_enabled or self.loop_preview is not None
            xa, xb = self.x_of(loop[0]), self.x_of(loop[1])
            p.fillRect(QRectF(xa, 0, xb - xa, h), Theme.c("loop", 0.07 if on else 0.03))

        # regions
        items = [(r, r.id == pr.selected) for r in pr.regions]
        if self.drag_preview:
            items.append((core.Region(*self.drag_preview, id=-1), True))
        for r, sel in items:
            if r.end < t0 or r.start > t1:
                continue
            xa, xb = self.x_of(r.start), self.x_of(r.end)
            p.fillRect(QRectF(xa, lane.top(), max(1, xb - xa), lane.height()), Theme.c("speech", 0.2 if sel else 0.11))
            stale = pr.is_stale(r)
            p.fillRect(QRectF(xa, lane.top(), max(1, xb - xa), 4 if stale else 3),
                       Theme.c("loop", 0.9) if stale else Theme.c("speech", 0.7))
            for bx, is_start in ((xa, True), (xb, False)):
                hot = self.hover_bar == (r.id, is_start)
                p.fillRect(QRectF(bx - (1.5 if hot else 1), lane.top(), 3 if hot else 2, lane.height()),
                           Theme.c("speech", 1 if hot else 0.85))
                tab = QRectF(bx if is_start else bx - 9 * s, lane.top(), 9 * s, 12 * s)
                p.setPen(Qt.NoPen)
                p.setBrush(Theme.c("speech", 1 if hot else 0.8))
                p.drawRoundedRect(tab, 2, 2)
                if hot and self.over_x:
                    c = QPointF(bx + 11 * s if is_start else bx - 11 * s, lane.top() + 15 * s)
                    p.setBrush(Theme.c("danger"))
                    p.drawEllipse(c, 8 * s, 8 * s)
                    k = 3.5 * s
                    p.setPen(QPen(QColor("white"), 1.6 * s, cap=Qt.RoundCap))
                    p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
                    p.drawLine(QPointF(c.x() + k, c.y() - k), QPointF(c.x() - k, c.y() + k))
                    p.setPen(Qt.NoPen)

        # ruler
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(QRectF(0, 0, w, RULER_H), Theme.c("bg"))
        step = core.nice_step(pr.visible_duration / max(1, w / 90))
        t = math.floor(t0 / step) * step
        p.setFont(ui_font(9.5, mono=True))
        while t <= t1:
            xx = self.x_of(t)
            p.fillRect(QRectF(xx, RULER_H - 7, 1, 7), Theme.c("muted"))
            p.fillRect(QRectF(xx, RULER_H, 1, lane.height()), Theme.c("grid"))
            p.setPen(Theme.c("muted"))
            p.drawText(QPointF(xx + 3, 12), core.timecode(t, step))
            t += step
        rl = self.loop_preview or (pr.loop_range if pr.loop_enabled else None)
        if rl:
            p.fillRect(QRectF(self.x_of(rl[0]), 2, self.x_of(rl[1]) - self.x_of(rl[0]), RULER_H - 6), Theme.c("loop", 0.35))
        p.fillRect(QRectF(0, RULER_H - 1, w, 1), Theme.c("ink", 0.1))

        # playhead
        xx = self.x_of(pr.player.time)
        if 0 <= xx <= w:
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(QRectF(xx - 0.75, 0, 1.5, h), Theme.c("ink", 0.92))
            tri = QPainterPath(QPointF(xx - 5, RULER_H - 7))
            tri.lineTo(xx + 5, RULER_H - 7)
            tri.lineTo(xx, RULER_H)
            tri.closeSubpath()
            p.fillPath(tri, Theme.c("ink"))

    def _image(self, tile) -> QImage:
        key = id(tile)
        if self._img_cache and self._img_cache[0] == key:
            return self._img_cache[1]
        rows, cols = tile.rgba.shape
        img = QImage(tile.rgba.data, cols, rows, cols * 4, QImage.Format_RGB32).copy()
        self._img_cache = (key, img)
        return img

    # ---- hit testing --------------------------------------------------------------------

    def bar_hit(self, pt: QPointF) -> tuple[int, bool] | None:
        if pt.y() <= RULER_H:
            return None
        best = None
        for r in self.p.regions:
            for t, is_start in ((r.start, True), (r.end, False)):
                d = abs(self.x_of(t) - pt.x())
                if d <= 6 and (best is None or d < best[2]):
                    best = (r.id, is_start, d)
        return (best[0], best[1]) if best else None

    def in_x_zone(self, pt: QPointF, bar: tuple[int, bool]) -> bool:
        r = self.p.region(bar[0])
        if r is None:
            return False
        s = Theme.icon_scale
        bx = self.x_of(r.start if bar[1] else r.end)
        cx = bx + 11 * s if bar[1] else bx - 11 * s
        return RULER_H <= pt.y() <= RULER_H + 26 * s and abs(pt.x() - cx) <= 10 * s

    def x_hit(self, pt: QPointF) -> int | None:
        if self.hover_bar and self.over_x and self.in_x_zone(pt, self.hover_bar):
            return self.hover_bar[0]
        return None

    # ---- hover & tips ---------------------------------------------------------------------

    def _tip(self, info, pt: QPointF) -> None:
        if self.tips is None:
            return
        if self._tip_id and self._tip_id != info.id:
            self.tips.leave(self._tip_id)
        self._tip_id = info.id
        self.tips.hover(info, self.mapTo(self.tips.host, pt.toPoint()))

    def _update_hover(self, pt: QPointF) -> None:
        if self.hover_bar and self.in_x_zone(pt, self.hover_bar):
            self.over_x = True
            self.setCursor(Qt.PointingHandCursor)
            self._tip(Tips.bar_x, pt)
            self.update()
            return
        b = self.bar_hit(pt)
        show_x = b is not None and pt.y() <= RULER_H + 26 * Theme.icon_scale
        if b != self.hover_bar or show_x != self.over_x:
            self.hover_bar, self.over_x = b, show_x
            self.update()
        if b is not None:
            self.setCursor(Qt.PointingHandCursor if show_x else Qt.SizeHorCursor)
            self._tip(Tips.bar_x if show_x else Tips.bar, pt)
        elif pt.y() <= RULER_H:
            self.setCursor(Qt.PointingHandCursor)
            self._tip(Tips.ruler, pt)
        else:
            self.setCursor(Qt.IBeamCursor)
            t = self.time_at(pt.x())
            self._tip(Tips.region if any(r.contains(t) for r in self.p.regions) else Tips.empty, pt)

    def leaveEvent(self, _e) -> None:
        self.hover_bar, self.over_x = None, False
        self.unsetCursor()
        if self.tips:
            self.tips.hide()
        self._tip_id = None
        self.update()

    # ---- mouse ----------------------------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if self.blocked or self.p.audio is None or e.button() != Qt.LeftButton:
            return
        if self.tips:
            self.tips.hide()
        self._tip_id = None
        pt = e.position()
        t = self.time_at(pt.x())
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if pt.y() <= RULER_H:
            if e.type() == QEvent.MouseButtonDblClick:
                self.p.set_loop_range(None)
                self._drag = None
                return
            self._drag = ("ruler", t, False)
            return
        rid = self.x_hit(pt)
        if rid is not None:
            self.p.remove_region(rid)
            self.hover_bar, self.over_x = None, False
            return
        b = self.bar_hit(pt)
        if b:
            if ctrl:
                self.p.remove_region(b[0])
                return
            self.p.begin_edit()
            self.p.selected = b[0]
            self._drag = ("edge", b[0], b[1])
            return
        r = next((r for r in self.p.regions if r.contains(t)), None)
        if r:
            if ctrl:
                self.p.remove_region(r.id)
                return
            self._drag = ("inside", r.id, t)
            return
        self._drag = ("create", t, False)

    mouseDoubleClickEvent = mousePressEvent

    def mouseMoveEvent(self, e) -> None:
        pt = e.position()
        if self.blocked:
            return
        if self._drag is None:
            self._update_hover(pt)
            return
        t = self.time_at(pt.x())
        kind = self._drag[0]
        if kind == "ruler":
            a = self._drag[1]
            self._drag = ("ruler", a, True)
            self.loop_preview = (min(a, t), max(a, t))
            self.update()
        elif kind == "edge":
            self.p.move_edge(self._drag[1], self._drag[2], t)
        elif kind == "create":
            a = self._drag[1]
            if abs(self.x_of(a) - pt.x()) > 3:
                self._drag = ("create", a, True)
                self.drag_preview = (min(a, t), max(a, t))
                self.update()
        # autoscroll while dragging past the edges
        if pt.x() < 0 or pt.x() > self.width():
            self.p.scroll((pt.x() - (0 if pt.x() < 0 else self.width())) / max(1, self.width()) * self.p.visible_duration * 0.2)

    def mouseReleaseEvent(self, e) -> None:
        if self.blocked or self._drag is None:
            return
        pt = e.position()
        t = self.time_at(pt.x())
        kind = self._drag[0]
        if kind == "ruler":
            a, moved = self._drag[1], self._drag[2]
            self.loop_preview = None
            if moved and abs(t - a) > 0.02:
                self.p.set_loop_range((min(a, t), max(a, t)))
            else:
                self.p.seek(t)
        elif kind == "create":
            a, moved = self._drag[1], self._drag[2]
            self.drag_preview = None
            if moved:
                self.p.add_region(a, t)
            else:
                self.p.insert_region(a)
        elif kind == "inside":
            self.p.selected = self._drag[1]
            self.p.seek(self._drag[2])
        self._drag = None
        self._update_hover(pt)
        self.update()
        self.p.changed.emit()

    def contextMenuEvent(self, e) -> None:
        if self.blocked or self.p.audio is None:
            return
        pt = QPointF(e.pos())
        t = self.time_at(pt.x())
        if self.tips:
            self.tips.hide()
        b = self.bar_hit(pt)
        r = self.p.region(b[0]) if b else next((r for r in self.p.regions if r.contains(t)), None)
        menu = QMenu(self)
        if r:
            self.p.selected = r.id
            n = self.p.regions.index(r) + 1
            a = QAction(f"Enhance Region {n} ({r.length:.1f} s)", menu, enabled=not self.p.processing)
            a.triggered.connect(lambda: self.p.enhance_region(r.id))
            menu.addAction(a)
            menu.addAction(f"Loop Region {n}", lambda: self.p.set_loop_range((r.start, r.end)))
            menu.addAction(f"Play Region {n}", lambda: self._play_from(r.start))
            menu.addSeparator()
            menu.addAction(f"Delete Region {n}", lambda: self.p.remove_region(r.id))
        elif pt.y() > RULER_H:
            menu.addAction("Add Region Here", lambda: self.p.insert_region(t))
        if not menu.isEmpty():
            self.update()
            menu.exec(e.globalPos())

    def _play_from(self, t: float) -> None:
        self.p.seek(t)
        if not self.p.player.playing:
            self.p.toggle_play()

    # ---- wheel, pinch ---------------------------------------------------------------------

    def wheelEvent(self, e) -> None:
        if self.blocked or self.p.duration <= 0:
            return
        t = self.time_at(e.position().x())
        pix, ang = e.pixelDelta(), e.angleDelta()
        if not pix.isNull():
            dx, dy = pix.x(), pix.y()
            k_zoom, k_pan = 0.01, 1.0
        else:
            dx, dy = ang.x() / 120 * 40, ang.y() / 120 * 40
            k_zoom, k_pan = 0.004, 1.0
            if e.modifiers() & Qt.ShiftModifier:
                dx, dy = dy, 0
        if abs(dy) > abs(dx):
            self.p.zoom(math.exp(dy * k_zoom), t)
        else:
            self.p.scroll(-dx * k_pan / max(1, self.width()) * self.p.visible_duration)
        e.accept()

    def event(self, e) -> bool:
        if e.type() == QEvent.NativeGesture and not self.blocked:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self.p.zoom(1 + e.value(), self.time_at(e.position().x()))
                return True
        return super().event(e)

    def follow_playhead(self) -> None:
        """Keep the playhead in view while playing."""
        pr = self.p
        t = pr.player.time
        if t > pr.visible_start + pr.visible_duration * 0.95 or t < pr.visible_start:
            pr.set_view(t - pr.visible_duration * 0.05)


class OverviewWidget(QWidget):
    def __init__(self, project: Project, parent: QWidget | None = None):
        super().__init__(parent)
        self.p = project
        self.setFixedHeight(30)
        project.view_changed.connect(self.update)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        d = max(self.p.duration, 0.001)
        p.fillRect(self.rect(), Theme.c("bg"))
        for r in self.p.regions:
            p.fillRect(QRectF(r.start / d * w, 0, max(1, r.length / d * w), h), Theme.c("speech", 0.22))
        pk = self.p.display_peaks
        if pk is not None:
            mn, mx = pk.columns(0, d, w)
            path = QPainterPath()
            for i, (a, b) in enumerate(zip(mn.tolist(), mx.tolist())):
                path.moveTo(i + 0.5, h / 2 - b * h * 0.45)
                path.lineTo(i + 0.5, h / 2 - a * h * 0.45 + 0.5)
            p.setPen(QPen(Theme.c("muted"), 1))
            p.drawPath(path)
        if self.p.loop_range and self.p.loop_enabled:
            a, b = self.p.loop_range
            p.fillRect(QRectF(a / d * w, 0, (b - a) / d * w, 3), Theme.c("loop"))
        p.setRenderHint(QPainter.Antialiasing)
        vr = QRectF(self.p.visible_start / d * w, 0.5, max(4, self.p.visible_duration / d * w), h - 1)
        p.setBrush(Theme.c("ink", 0.07))
        p.setPen(QPen(Theme.c("ink", 0.35), 1))
        p.drawRoundedRect(vr, 3, 3)
        p.fillRect(QRectF(0, 0, w, 1), Theme.c("ink", 0.06))

    def _jump(self, x: float) -> None:
        if self.p.audio is None or self.p.needs_models or self.p.tour_step is not None:
            return
        t = x / max(1, self.width()) * self.p.duration
        self.p.set_view(t - self.p.visible_duration / 2)

    def mousePressEvent(self, e) -> None:
        self._jump(e.position().x())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.LeftButton:
            self._jump(e.position().x())


__all__ = ["EditorWidget", "OverviewWidget"]
