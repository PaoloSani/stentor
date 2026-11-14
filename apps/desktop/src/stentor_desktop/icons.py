"""Small vector icons drawn with QPainter (crisp at any scale, no icon font needed)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen


def draw(p: QPainter, name: str, r: QRectF, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = min(r.width(), r.height())
    c = r.center()
    pen = QPen(color, max(1.2, s * 0.11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    fn = _ICONS.get(name)
    if fn:
        fn(p, c, s, color, pen)
    p.restore()


def _fill(p: QPainter, path: QPainterPath, color: QColor) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _play(p, c, s, col, pen):
    h = s * 0.62
    path = QPainterPath(QPointF(c.x() - h * 0.36, c.y() - h / 2))
    path.lineTo(c.x() + h * 0.52, c.y())
    path.lineTo(c.x() - h * 0.36, c.y() + h / 2)
    path.closeSubpath()
    _fill(p, path, col)


def _pause(p, c, s, col, pen):
    w, h = s * 0.17, s * 0.58
    path = QPainterPath()
    path.addRoundedRect(QRectF(c.x() - w * 1.6, c.y() - h / 2, w, h), w * 0.25, w * 0.25)
    path.addRoundedRect(QRectF(c.x() + w * 0.6, c.y() - h / 2, w, h), w * 0.25, w * 0.25)
    _fill(p, path, col)


def _to_start(p, c, s, col, pen):
    h = s * 0.5
    path = QPainterPath(QPointF(c.x() + h * 0.45, c.y() - h / 2))
    path.lineTo(c.x() - h * 0.3, c.y())
    path.lineTo(c.x() + h * 0.45, c.y() + h / 2)
    path.closeSubpath()
    path.addRect(QRectF(c.x() - h * 0.55, c.y() - h / 2, h * 0.16, h))
    _fill(p, path, col)


def _loop(p, c, s, col, pen):
    w, h = s * 0.62, s * 0.38
    r = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
    path = QPainterPath()
    path.moveTo(r.left() + w * 0.25, r.bottom())
    path.lineTo(r.left() + h / 2, r.bottom())
    path.arcTo(QRectF(r.left(), r.top(), h, h), 270, -180)
    path.lineTo(r.right() - w * 0.15, r.top())
    path.moveTo(r.right() - w * 0.25, r.top())
    path.lineTo(r.right() - h / 2, r.top())
    path.arcTo(QRectF(r.right() - h, r.top(), h, h), 90, -180)
    path.lineTo(r.left() + w * 0.15, r.bottom())
    p.drawPath(path)
    a = s * 0.11
    for x, y, d in ((r.right() - w * 0.15, r.top(), 1), (r.left() + w * 0.15, r.bottom(), -1)):
        tri = QPainterPath(QPointF(x + d * a, y))
        tri.lineTo(x - d * a * 0.6, y - a)
        tri.lineTo(x - d * a * 0.6, y + a)
        tri.closeSubpath()
        p.save()
        _fill(p, tri, col)
        p.restore()


def _wand(p, c, s, col, pen):
    a, b = QPointF(c.x() - s * 0.3, c.y() + s * 0.3), QPointF(c.x() + s * 0.12, c.y() - s * 0.12)
    p.drawLine(a, b)
    for dx, dy, k in ((0.24, -0.3, 0.09), (0.32, 0.02, 0.06), (-0.04, -0.34, 0.06)):
        x, y = c.x() + s * dx, c.y() + s * dy
        p.drawLine(QPointF(x - s * k, y), QPointF(x + s * k, y))
        p.drawLine(QPointF(x, y - s * k), QPointF(x, y + s * k))


def _export(p, c, s, col, pen):
    top, mid = c.y() - s * 0.34, c.y() + s * 0.06
    p.drawLine(QPointF(c.x(), top), QPointF(c.x(), mid))
    p.drawLine(QPointF(c.x() - s * 0.18, mid - s * 0.18), QPointF(c.x(), mid))
    p.drawLine(QPointF(c.x() + s * 0.18, mid - s * 0.18), QPointF(c.x(), mid))
    path = QPainterPath(QPointF(c.x() - s * 0.32, c.y() + s * 0.04))
    path.lineTo(c.x() - s * 0.32, c.y() + s * 0.32)
    path.lineTo(c.x() + s * 0.32, c.y() + s * 0.32)
    path.lineTo(c.x() + s * 0.32, c.y() + s * 0.04)
    p.drawPath(path)


def _gear(p, c, s, col, pen):
    ro, ri, n = s * 0.4, s * 0.3, 8
    path = QPainterPath()
    for i in range(n * 2):
        ang = math.pi * i / n
        rad = ro if i % 2 == 0 else ri
        for da in (-0.17, 0.17):
            pt = QPointF(c.x() + rad * math.cos(ang + da), c.y() + rad * math.sin(ang + da))
            path.moveTo(pt) if i == 0 and da < 0 else path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)
    p.drawEllipse(c, s * 0.11, s * 0.11)


def _folder(p, c, s, col, pen):
    w, h = s * 0.7, s * 0.5
    x, y = c.x() - w / 2, c.y() - h / 2 + s * 0.04
    path = QPainterPath(QPointF(x, y + h))
    path.lineTo(x, y)
    path.lineTo(x + w * 0.35, y)
    path.lineTo(x + w * 0.45, y + h * 0.16)
    path.lineTo(x + w, y + h * 0.16)
    path.lineTo(x + w, y + h)
    path.closeSubpath()
    p.drawPath(path)
    k = s * 0.1
    cy = y + h * 0.58
    p.drawLine(QPointF(c.x() - k, cy), QPointF(c.x() + k, cy))
    p.drawLine(QPointF(c.x(), cy - k), QPointF(c.x(), cy + k))


def _close(p, c, s, col, pen):
    k = s * 0.22
    p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
    p.drawLine(QPointF(c.x() + k, c.y() - k), QPointF(c.x() - k, c.y() + k))


def _waveform(p, c, s, col, pen):
    hs = (0.2, 0.5, 0.85, 0.6, 1.0, 0.45, 0.7, 0.3)
    step = s * 0.11
    x0 = c.x() - step * (len(hs) - 1) / 2
    for i, h in enumerate(hs):
        x = x0 + i * step
        p.drawLine(QPointF(x, c.y() - h * s * 0.38), QPointF(x, c.y() + h * s * 0.38))


def _warning(p, c, s, col, pen):
    path = QPainterPath(QPointF(c.x(), c.y() - s * 0.38))
    path.lineTo(c.x() + s * 0.42, c.y() + s * 0.34)
    path.lineTo(c.x() - s * 0.42, c.y() + s * 0.34)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(c.x(), c.y() - s * 0.1), QPointF(c.x(), c.y() + s * 0.1))
    p.drawPoint(QPointF(c.x(), c.y() + s * 0.22))


def _arrow_up_right(p, c, s, col, pen):
    k = s * 0.25
    p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
    p.drawLine(QPointF(c.x() - k * 0.2, c.y() - k), QPointF(c.x() + k, c.y() - k))
    p.drawLine(QPointF(c.x() + k, c.y() - k), QPointF(c.x() + k, c.y() + k * 0.2))


_ICONS = {
    "play": _play, "pause": _pause, "to_start": _to_start, "loop": _loop, "wand": _wand, "export": _export,
    "gear": _gear, "folder": _folder, "close": _close, "waveform": _waveform, "warning": _warning,
    "arrow": _arrow_up_right,
}
