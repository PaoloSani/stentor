"""Headless checks and UI snapshots (no display needed: QT_QPA_PLATFORM=offscreen).

    python -m stentor_desktop --process in.wav out.wav        full pipeline with the ONNX model
    python -m stentor_desktop --logic in.wav                  region editing rules, undo / redo, incremental rendering
    python -m stentor_desktop --export-regions in.wav dir/    one WAV per region + CSV (needs the model)
    python -m stentor_desktop --snapshot in.wav out.png [enhanced] [spec] [zoom=a-b] [loop=a-b] [select]
                              [theme=light|dark] [scale=1.25] [tour=N] [about] [setup] [settings] [tip=name] [empty]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

FLAGS = ("--process", "--logic", "--export-regions", "--snapshot")


def run_if_requested(argv: list[str]) -> int | None:
    if not argv or argv[0] not in FLAGS:
        return None
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    flag, args = argv[0], argv[1:]
    try:
        return {"--process": process, "--logic": logic, "--export-regions": export_regions, "--snapshot": snapshot}[flag](args)
    except AssertionError as exc:
        print(f"FAILED: {exc}")
        return 1


def _app():
    from PySide6.QtWidgets import QApplication

    QApplication.setApplicationName("Stentor")
    QApplication.setOrganizationName("Stentor-selftest")  # keep tests out of the user's settings
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    return app


def _project(path: str, model: bool):
    from . import models
    from .project import Project

    p = Project(preload=False)
    t = time.perf_counter()
    p.load_sync(path)
    print(f"loaded {Path(path).name}: {p.duration:.1f} s, {p.audio.source_rate} Hz, {len(p.regions)} regions "
          f"({p.speech_seconds:.1f} s speech) in {time.perf_counter() - t:.1f}s")
    if model:
        folder = models.locate()
        assert folder is not None, "ONNX models not found (set STENTOR_MODELS_DIR)"
        t = time.perf_counter()
        p.model = models.load_model(folder, os.environ.get("STENTOR_DEVICE", "auto"))
        p.models_folder = folder
        print(f"model: {p.model.description} from {folder} in {time.perf_counter() - t:.1f}s")
    return p


def process(args: list[str]) -> int:
    from . import core

    _app()
    src, dst = args[0], args[1]
    p = _project(src, model=True)
    t = time.perf_counter()
    p.render_sync()
    el = time.perf_counter() - t
    print(f"render: {el:.1f}s ({p.speech_seconds / max(el, 1e-9):.1f}x real time over the speech)")
    y = p.enhanced
    assert y.shape[0] == p.audio.wav16k.shape[0] * core.UP, "output length differs from the input"
    core.write_wav(y, core.OUT_SR, "float32", dst)
    import numpy as np

    rms = [float(np.sqrt(np.mean(y[i:i + 480000] ** 2))) for i in range(0, y.shape[0], 480000)]
    print("rms per 10 s:", " ".join(f"{r:.3f}" for r in rms))
    assert max(rms) > 0.01, "output is silent"
    print(f"wrote {dst} ({y.shape[0]} samples)")
    return 0


class _FakeModel:
    description = "fake"

    def enhance(self, x):
        import numpy as np

        return np.repeat(x, 3).astype(np.float32)


def logic(args: list[str]) -> int:
    import numpy as np

    from . import core

    _app()
    p = _project(args[0], model=False)
    p.model = _FakeModel()
    d = p.duration
    p.clear_regions()
    p.add_region(1.0, 2.0)
    p.add_region(4.0, 5.0)
    assert len(p.regions) == 2
    p.add_region(1.5, 4.5)  # merges all three
    assert len(p.regions) == 1 and abs(p.regions[0].start - 1.0) < 1e-9 and abs(p.regions[0].end - 5.0) < 1e-9
    p.undo()
    assert len(p.regions) == 2, "undo"
    p.redo()
    assert len(p.regions) == 1, "redo"
    p.undo()
    p.insert_region(2.5)  # from 2.5 to just before the next region
    r = next(r for r in p.regions if r.contains(3.0))
    assert abs(r.end - 3.95) < 1e-6, f"insert_region end {r.end}"
    a, b = p.regions[0], p.regions[1]
    p.begin_edit()
    p.move_edge(a.id, False, 10.0)  # stops before the neighbour
    assert p.regions[0].end <= b.start - 0.02 + 1e-9, "edge must stop at the neighbour"
    p.undo()
    print("region rules: ok")

    p.render_sync()
    first = p.enhanced.copy()
    assert not p.enhanced_stale
    target = p.regions[1]
    p.begin_edit()
    p.move_edge(target.id, False, target.end + 0.5)
    assert p.enhanced_stale and len(p.stale_regions) == 1
    out = p.enhanced.copy()
    core.Renderer(p.model).render_regions(p.audio, p.stale_regions, out, p.orphan_spans)
    untouched = p.regions[0]
    a, b = int(untouched.start * core.OUT_SR), int(untouched.end * core.OUT_SR)
    assert np.array_equal(out[a:b], first[a:b]), "untouched region changed"
    print("incremental rendering leaves untouched regions bit-identical: ok")

    p.set_loop_range((min(2.0, d), min(2.6, d)))
    assert p.player._loop is not None
    p.toggle_loop()
    assert not p.loop_enabled
    print("loop: ok")
    return 0


def export_regions(args: list[str]) -> int:
    _app()
    p = _project(args[0], model=True)
    p.render_sync()
    out = Path(args[1])
    out.mkdir(parents=True, exist_ok=True)
    if len(args) > 2 and args[2] == "source-rate":
        p.export_rate = "source"
    n = p.export_regions(out)
    print(f"exported {n} regions to {out}: {sorted(f.name for f in out.iterdir())[:4]}…")
    return 0


def snapshot(args: list[str]) -> int:
    from PySide6.QtCore import QPoint

    from .theme import Theme
    from .tips import Tips
    from .window import MainWindow

    app = _app()
    opts = dict(a.split("=", 1) if "=" in a else (a, "1") for a in args[2:])
    Theme.mode = opts.get("theme", "dark")
    Theme.icon_scale = float(opts.get("scale", 1.0))
    Theme.detailed_tips = True
    from .project import Project

    p = Project(preload=False)
    if "setup" in opts:
        p.needs_models = True
    win = MainWindow(p)
    win.resize(1180, 640)
    win.show()
    app.processEvents()
    if "empty" not in opts:
        p.load_sync(args[0])
        if "enhanced" in opts:
            from . import models

            p.model = models.load_model(models.locate())
            p.render_sync()
            from .project import model_label

            p.model_status = model_label(p.model.description)
            p.model_changed.emit()
    if "zoom" in opts:
        a, b = (float(x) for x in opts["zoom"].split("-"))
        p.set_view(a, b - a)
    if "loop" in opts:
        a, b = (float(x) for x in opts["loop"].split("-"))
        p.set_loop_range((a, b))
    if "select" in opts and p.regions:
        p.selected = p.regions[min(1, len(p.regions) - 1)].id
    if "spec" in opts:
        p.view_mode = "spec"
        p.editor_width = win.area.editor.width()
        p.spectrogram_sync()
    p.toast = None
    win._sync_setup()
    win.apply_theme()
    for _ in range(5):
        app.processEvents()
    if "tour" in opts:
        p.tour_step = int(opts["tour"])
        p.changed.emit()
    if "about" in opts:
        win.show_about()
    if "tip" in opts:
        info = getattr(Tips, opts["tip"])
        win.tips.suppressed = False
        win.tips.show_now(info, QPoint(win.root.width() // 2, win.root.height() - 120))
    if "toast" in opts:
        p.set_status("Enhanced 60.0 s of speech in 49.5 s")
    if "settings" in opts:
        win.show_settings()
    for _ in range(10):
        app.processEvents()
    img = win.grab()
    if "settings" in opts:  # the popup is a separate window: paint it onto the snapshot
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QDialog

        panel = next((w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()), None)
        if panel is not None:
            painter = QPainter(img)
            g = win.header.gear
            pos = g.mapTo(win, g.rect().bottomRight())
            painter.drawPixmap(pos.x() - panel.width(), pos.y() + 6, panel.grab())
            painter.end()
    img.save(args[1])
    print(f"snapshot -> {args[1]} ({img.width()}x{img.height()})")
    return 0
