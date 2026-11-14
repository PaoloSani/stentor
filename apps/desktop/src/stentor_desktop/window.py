"""Main window: header, editor with the floating control island, overview, overlays, menus and shortcuts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QVBoxLayout, QWidget

from . import core
from .cards import AboutCard, Links, ModelSetup, SettingsPanel, TourOverlay
from .editor import EditorWidget, OverviewWidget
from .project import Project, demo_path, settings
from .theme import Theme
from .tips import TipCenter, Tips
from .widgets import EmptyState, Header, Island, Toast

AUDIO_FILTER = "Audio files (*.wav *.flac *.aif *.aiff *.mp3 *.m4a *.aac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm);;All files (*)"


class EditorArea(QWidget):
    """Editor + overview (or the empty state) with the island and toast floating on top."""

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        p = win.project
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.empty = EmptyState(p)
        self.editor = EditorWidget(p, win.tips)
        self.overview = OverviewWidget(p)
        win.tips.attach(self.overview, Tips.overview)
        lay.addWidget(self.empty, 1)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.overview)
        self.island = Island(p, win.tips, self)
        self.toast = Toast(self)
        self.empty.open_clicked.connect(win.open_dialog)
        self.empty.demo_clicked.connect(p.open_demo)
        p.changed.connect(self.sync)
        self.sync()

    def sync(self) -> None:
        has = self.win.project.audio is not None
        self.empty.setVisible(not has)
        self.editor.setVisible(has)
        self.overview.setVisible(has)
        self.place()

    def place(self) -> None:
        self.island.adjustSize()
        iw, ih = self.island.width(), self.island.height()
        bottom = 44 if self.win.project.audio is not None else 22
        self.island.move((self.width() - iw) // 2, self.height() - bottom - ih)
        self.island.raise_()
        if self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.island.y() - self.toast.height() - 8)
            self.toast.raise_()

    def resizeEvent(self, _e) -> None:
        self.place()


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = p = project or Project()
        self.setWindowTitle("Stentor")
        icon = _app_icon()
        if icon:
            self.setWindowIcon(icon)
        self.resize(1180, 640)
        self.setMinimumSize(880, 460)
        self.setAcceptDrops(True)

        self.root = QWidget()
        self.setCentralWidget(self.root)
        self.tips = TipCenter(self.root)
        v = QVBoxLayout(self.root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = Header(p, self.tips)
        self.area = EditorArea(self)
        v.addWidget(self.header)
        v.addWidget(self.area, 1)
        self.header.logo.clicked.connect(self.show_about)
        self.header.gear.clicked.connect(self.show_settings)
        self.header.file.clicked.connect(self.open_dialog)

        self.setup: ModelSetup | None = None
        self.about: AboutCard | None = None
        self.tour = TourOverlay(self.root, p, self.anchor)
        self.tour.hide()
        self._error: str | None = None

        p.changed.connect(self._on_changed)
        p.status_changed.connect(lambda _s: self._show_toast())
        p.error.connect(self._on_error)
        p.model_changed.connect(self._sync_setup)
        self._build_menus()

        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._was_playing = False
        self.apply_theme()
        self._sync_setup()

    # ---- startup ----------------------------------------------------------------------

    def first_launch(self) -> None:
        self.project.open_demo_on_first_launch()
        self.project.start_tour_if_first_time()

    # ---- theme ------------------------------------------------------------------------------

    def apply_theme(self) -> None:
        app = QApplication.instance()
        app.setPalette(Theme.palette())
        app.setStyleSheet(Theme.stylesheet())
        self.header.retheme()
        self.area.empty.retheme()
        self.area.island.refresh()
        self._repaint_all()

    def apply_scale(self) -> None:
        self.area.island.rebuild()
        self.header.retheme()
        self.area.place()
        self._repaint_all()

    def _repaint_all(self) -> None:
        for w in self.root.findChildren(QWidget):
            w.update()
        if self.project.tour_step is not None:
            self.tour.sync()

    # ---- state ------------------------------------------------------------------------------

    def _modal(self) -> bool:
        return self.project.needs_models or self.project.tour_step is not None or self.about is not None

    def _on_changed(self) -> None:
        self.tips.suppressed = self._modal()
        if self.project.tour_step is not None:
            if not self.tour.isVisible() or self.tour.card is None or self.tour.property("step") != self.project.tour_step:
                self.tour.setProperty("step", self.project.tour_step)
                self.tour.sync()
                self.tour.setFocus()
        elif self.tour.isVisible():
            self.tour.hide()
        self._update_actions()
        self._show_toast()

    def _sync_setup(self) -> None:
        p = self.project
        if p.needs_models and self.setup is None:
            self.setup = ModelSetup(self.root, p, self.locate_models)
            self.setup.show()
            self.setup.raise_()
        elif not p.needs_models and self.setup is not None:
            self.setup.close_card()
            self.setup = None
            p.start_tour_if_first_time()
        self.tips.suppressed = self._modal()
        self._update_actions()

    def _on_error(self, msg: str) -> None:
        self._error = msg
        self._show_toast()

    def _show_toast(self) -> None:
        t = self.area.toast
        t.on_close = self._clear_error
        if self._error:
            t.show_message(self._error, error=True)
        else:
            t.show_message(self.project.toast)
        self.area.place()

    def _clear_error(self) -> None:
        self._error = None
        self._show_toast()

    def _tick(self) -> None:
        pl = self.project.player
        if pl.playing or self._was_playing:
            self.area.island.tick()
            self.area.editor.update()
            if pl.playing:
                self.area.editor.follow_playhead()
        if pl.playing != self._was_playing:
            self._was_playing = pl.playing
            self.area.island.refresh()

    def anchor(self, name: str) -> QRect | None:
        """Rectangle of a tour target in the root widget's coordinates."""
        h, a = self.header, self.area
        widgets = {"logo": h.logo, "gear": h.gear, "file": h.file, **a.island.anchors}
        if name in widgets:
            w = widgets[name]
            if not w.isVisible():
                return None
            return QRect(w.mapTo(self.root, w.rect().topLeft()), w.size())
        if name in ("editor", "ruler") and a.editor.isVisible():
            r = a.editor.lane_rect() if name == "editor" else a.editor.ruler_rect()
            return QRect(a.editor.mapTo(self.root, r.topLeft().toPoint()), r.size().toSize())
        return None

    # ---- dialogs -----------------------------------------------------------------------------

    def open_dialog(self) -> None:
        if self.project.needs_models:
            return
        start = str(self.project.audio.path.parent) if self.project.audio else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open a recording", start, AUDIO_FILTER)
        if path:
            self.project.open(path)

    def export(self) -> None:
        if self.project.export_scope == "regions":
            self.export_regions()
        else:
            self.export_whole()

    def export_whole(self) -> None:
        p = self.project
        if p.enhanced is None:
            return
        default = p.audio.path.with_name(p.audio.path.stem + "_enhanced.wav")
        path, _ = QFileDialog.getSaveFileName(self, "Export enhanced audio", str(default), "WAV (*.wav)")
        if path:
            if not path.lower().endswith(".wav"):
                path += ".wav"
            try:
                p.export_whole(path)
            except Exception as exc:
                self._on_error(f"Export failed: {exc}")

    def export_regions(self) -> None:
        p = self.project
        if p.enhanced is None or not p.regions:
            return
        n = len(p.regions)
        folder = QFileDialog.getExistingDirectory(
            self, f"Choose a folder for the {n} speech region{'' if n == 1 else 's'}", str(p.audio.path.parent))
        if folder:
            try:
                p.export_regions(folder)
            except Exception as exc:
                self._on_error(f"Export failed: {exc}")

    def locate_models(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder containing feature_extractor.onnx and decoder.onnx")
        if not folder:
            return
        if not self.project.use_models_folder(folder):
            self._on_error("That folder doesn't contain the Stentor ONNX models (feature_extractor.onnx, decoder.onnx).")

    def show_about(self) -> None:
        if self.about is not None or self.project.needs_models:
            return
        self.tips.hide()
        self.about = AboutCard(self.root)
        self.about.closed.connect(self._about_closed)
        self.about.show()
        self.about.raise_()
        self.tips.suppressed = True

    def _about_closed(self) -> None:
        self.about = None
        self.tips.suppressed = self._modal()

    def show_settings(self) -> None:
        if self.project.needs_models:
            return
        self.tips.hide()
        panel = SettingsPanel(self.project, self, self.apply_theme, self.apply_scale, self.tips.refresh_mode, self.locate_models)
        g = self.header.gear
        pos = g.mapToGlobal(g.rect().bottomRight())
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        panel.fit(max(320, min(screen.bottom() - pos.y() - 16, 720)))
        panel.move(pos.x() - panel.width(), pos.y() + 6)
        self.header.gear.open = True
        panel.finished.connect(lambda _r: setattr(self.header.gear, "open", False))
        panel.show()

    # ---- menus & shortcuts -------------------------------------------------------------------

    def _act(self, menu, text: str, slot, shortcut: str | QKeySequence | None = None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        a.triggered.connect(slot)
        menu.addAction(a)
        self.addAction(a)  # shortcuts work even when the menu bar is hidden
        return a

    def _build_menus(self) -> None:
        p = self.project
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._act(f, "Open…", self.open_dialog, QKeySequence.Open)
        self.a_demo = self._act(f, "Open Demo Recording", p.open_demo)
        self.a_demo.setVisible(demo_path() is not None)
        f.addSeparator()
        self.a_export = self._act(f, "Export Enhanced…", self.export, "Ctrl+E")
        self.a_export_regions = self._act(f, "Export Speech Regions…", self.export_regions, "Ctrl+Shift+E")
        f.addSeparator()
        self._act(f, "Settings…", self.show_settings, "Ctrl+,")
        f.addSeparator()
        quit_ = self._act(f, "Quit", self.close, QKeySequence.Quit)
        quit_.setMenuRole(QAction.QuitRole)

        e = mb.addMenu("&Edit")
        self._act(e, "Undo", p.undo, QKeySequence.Undo)
        self._act(e, "Redo", p.redo, QKeySequence("Ctrl+Shift+Z"))

        t = mb.addMenu("&Transport")
        self._act(t, "Play / Pause", p.toggle_play, "Space")
        self._act(t, "Go to Start", p.go_to_start, "Home")
        self._act(t, "Loop", p.toggle_loop, "L")
        self._act(t, "Compare A / B", p.toggle_source, "B")

        r = mb.addMenu("&Regions")
        self._act(r, "Detect Speech", p.detect, "Ctrl+Shift+D")
        self._act(r, "Delete Selected Region", self._delete_selected, QKeySequence.Delete)
        self.addAction(self._hidden("Backspace", self._delete_selected))
        self._act(r, "Clear All Regions", p.clear_regions)
        r.addSeparator()
        self.a_enhance = self._act(r, "Enhance (changed regions)", p.enhance, "Ctrl+Return")
        self._act(r, "Enhance Selected Region", lambda: p.selected is not None and p.enhance_region(p.selected), "Ctrl+Shift+Return")
        self._act(r, "Re-enhance Everything", p.enhance_all)

        v = mb.addMenu("&View")
        self._act(v, "Waveform / Spectrogram", p.toggle_view_mode, "S")
        self._act(v, "Zoom In", lambda: p.zoom(1.6, p.visible_start + p.visible_duration / 2), QKeySequence.ZoomIn)
        self._act(v, "Zoom Out", lambda: p.zoom(1 / 1.6, p.visible_start + p.visible_duration / 2), QKeySequence.ZoomOut)
        self._act(v, "Zoom to Fit", p.zoom_to_fit, "Ctrl+0")

        h = mb.addMenu("&Help")
        self._act(h, "Show Tour", self._start_tour)
        h.addSeparator()
        self._act(h, "Send Feedback…", lambda: Links.open(Links.issues))
        self._act(h, "Check for Updates…", self.show_about)
        h.addSeparator()
        self._act(h, "Who was Stentor?", lambda: Links.open(Links.wikipedia))
        self._act(h, "Sidon on GitHub", lambda: Links.open(Links.sidon))
        about = self._act(h, "About Stentor", self.show_about)
        about.setMenuRole(QAction.AboutRole)
        self._update_actions()

    def _hidden(self, key: str, slot) -> QAction:
        a = QAction(self)
        a.setShortcut(QKeySequence(key))
        a.triggered.connect(slot)
        return a

    def _delete_selected(self) -> None:
        if self.project.selected is not None:
            self.project.remove_region(self.project.selected)

    def _start_tour(self) -> None:
        if not self.project.needs_models:
            if self.project.audio is None:
                self.project.open_demo()
            self.project.start_tour()

    def _update_actions(self) -> None:
        p = self.project
        if hasattr(self, "a_export"):
            self.a_export.setEnabled(p.enhanced is not None and not p.processing)
            self.a_export_regions.setEnabled(p.enhanced is not None and bool(p.regions) and not p.processing)

    # ---- drag & drop ---------------------------------------------------------------------------

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and not self.project.needs_models:
            e.acceptProposedAction()
            self.area.empty.highlight = True
            self.area.empty.update()

    def dragLeaveEvent(self, _e) -> None:
        self.area.empty.highlight = False
        self.area.empty.update()

    def dropEvent(self, e) -> None:
        self.area.empty.highlight = False
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.project.open(urls[0])

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        for ov in (self.setup, self.about):
            if ov is not None:
                ov.layout_card()
        if self.project.tour_step is not None:
            self.tour.sync()
        self.tips.hide()

    def closeEvent(self, e) -> None:
        self.project.player.close()
        self.project.save_settings()
        super().closeEvent(e)


def _app_icon() -> QIcon | None:
    import sys

    roots = [Path(getattr(sys, "_MEIPASS", ""))] if getattr(sys, "frozen", False) else []
    roots += list(Path(__file__).resolve().parents)
    for r in roots:
        f = r / "assets" / "AppIcon-1024.png"
        if f.is_file():
            return QIcon(str(f))
    return None


def load_preferences() -> None:
    s = settings()
    Theme.mode = s.value("appearance", "auto")
    Theme.icon_scale = float(s.value("iconScale", 1.0))
    Theme.detailed_tips = s.value("detailedTooltips", True, type=bool)


def follow_system_theme(win: MainWindow) -> None:
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _s: Theme.mode == "auto" and win.apply_theme())


__all__ = ["MainWindow", "core", "follow_system_theme", "load_preferences"]
