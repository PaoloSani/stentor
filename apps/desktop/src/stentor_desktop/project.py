"""Document state: file, regions (with undo), view, playback, incremental rendering, export."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from . import core, models
from .core import Audio, DetectionSettings, Region
from .player import Player
from .visuals import Peaks, SpecTile, spectrogram

DEMO_NAME = "JFK - Rice University 1962 (excerpt)"


def demo_path() -> Path | None:
    import sys

    roots = [Path(getattr(sys, "_MEIPASS", "")) / "assets"] if getattr(sys, "frozen", False) else []
    roots += [p / "assets" for p in Path(__file__).resolve().parents]
    for r in roots:
        for ext in ("m4a", "flac", "wav"):
            p = r / "Demo" / f"{DEMO_NAME}.{ext}"
            if p.is_file():
                return p
    return None


def model_label(description: str) -> str:
    """'ONNX Runtime (Dml)' -> 'ONNX Runtime · GPU (DirectML)'."""
    names = {"CPU": "CPU", "Dml": "GPU (DirectML)", "CUDA": "NVIDIA GPU (CUDA)"}
    if "(" in description:
        head, dev = description.rstrip(")").split("(", 1)
        return f"{head.strip()} · {names.get(dev, dev)}"
    return description


def settings() -> QSettings:
    return QSettings("Stentor", "Stentor")


class Project(QObject):
    changed = Signal()  # anything the island / header / menus show
    view_changed = Signal()  # zoom, scroll, regions, signal: the editor repaints
    spec_ready = Signal()
    status_changed = Signal(str)
    error = Signal(str)
    model_changed = Signal()
    install_progress = Signal(float, str)
    _loaded = Signal(object, object, object)  # audio, regions, peaks (from the loader thread)
    _rendered = Signal(object)
    _model_ready = Signal(object, str)
    _spec = Signal(object, int)
    _progress = Signal(float)

    def __init__(self, preload: bool = True):
        super().__init__()
        s = settings()
        self.audio: Audio | None = None
        self.loading = False
        self.regions: list[Region] = []
        self.selected: int | None = None
        self.detection = DetectionSettings(
            threshold_db=float(s.value("detect/threshold", -45.0)),
            pre_roll=float(s.value("detect/pre", 0.15)),
            post_roll=float(s.value("detect/post", 0.25)),
            merge_gap=float(s.value("detect/gap", 0.35)),
        )
        self._undo: list[list[Region]] = []
        self._redo: list[list[Region]] = []

        self.view_mode = "wave"  # or "spec"
        self.source = "A"
        self.visible_start = 0.0
        self.visible_duration = 1.0
        self.loop_range: tuple[float, float] | None = None
        self.loop_enabled = False
        self.editor_width = 1000

        self.enhanced: np.ndarray | None = None
        self.processing = False
        self.progress = 0.0
        self.status = ""
        self.toast: str | None = None
        self._toast_timer = QTimer(self, singleShot=True, interval=3500)
        self._toast_timer.timeout.connect(self._clear_toast)
        self._rendered_spans: dict[int, Region] = {}
        self._cancel = threading.Event()

        self.original_peaks: Peaks | None = None
        self.enhanced_peaks: Peaks | None = None
        self.spec_tile: SpecTile | None = None
        self._spec_token = 0
        self._spec_timer = QTimer(self, singleShot=True, interval=30)
        self._spec_timer.timeout.connect(self._compute_spectrogram)

        self.export_scope = s.value("export/scope", "whole")
        self.export_rate = s.value("export/rate", "model")
        self.export_format = s.value("export/format", "pcm24")
        self.device = s.value("model/device", "auto")

        self.player = Player()
        self.model = None
        self.model_status = "Model not loaded"
        self.models_folder: Path | None = None
        self.needs_models = False
        self._model_event = threading.Event()
        self.installer = models.Installer()
        self.installing = False
        self.tour_step: int | None = None

        self._loaded.connect(self._on_loaded)
        self._rendered.connect(self._on_rendered)
        self._model_ready.connect(self._on_model_ready)
        self._spec.connect(self._on_spec)
        self._progress.connect(self._on_progress)
        if preload:
            self.preload_model()

    # ------------------------------------------------------------------ helpers

    @property
    def duration(self) -> float:
        return self.audio.duration if self.audio else 0.0

    @property
    def file_name(self) -> str:
        return self.audio.path.name if self.audio else "Stentor"

    @property
    def speech_seconds(self) -> float:
        return sum(r.length for r in self.regions)

    def set_status(self, msg: str) -> None:
        self.status = msg
        if msg:
            self.toast = msg
            self._toast_timer.start()
        self.status_changed.emit(msg)
        self.changed.emit()

    def _clear_toast(self) -> None:
        self.toast = None
        self.changed.emit()

    def fail(self, msg: str) -> None:
        self.error.emit(msg)

    def _emit_all(self) -> None:
        self.changed.emit()
        self.view_changed.emit()

    def save_settings(self) -> None:
        s = settings()
        d = self.detection
        for k, v in (("detect/threshold", d.threshold_db), ("detect/pre", d.pre_roll), ("detect/post", d.post_roll),
                     ("detect/gap", d.merge_gap), ("export/scope", self.export_scope), ("export/rate", self.export_rate),
                     ("export/format", self.export_format), ("model/device", self.device)):
            s.setValue(k, v)

    # ------------------------------------------------------------------ file

    def open(self, path: str | Path) -> None:
        self.player.pause()
        self.loading = True
        self.set_status(f"Loading {Path(path).name}…")
        settings_ = DetectionSettings(**vars(self.detection))

        def work():
            try:
                audio = core.load(path)
                regions = core.detect(audio.wav16k, settings_)
                peaks = Peaks(audio.listen, audio.source_rate)
                self._loaded.emit(audio, regions, peaks)
            except Exception as exc:
                self._loaded.emit(exc, None, None)

        threading.Thread(target=work, daemon=True).start()

    def load_sync(self, path: str | Path) -> None:
        """Synchronous load (headless tests)."""
        audio = core.load(path)
        self._on_loaded(audio, core.detect(audio.wav16k, self.detection), Peaks(audio.listen, audio.source_rate))

    def _on_loaded(self, audio, regions, peaks) -> None:
        self.loading = False
        if isinstance(audio, Exception):
            self.set_status("")
            self.fail(str(audio))
            self._emit_all()
            return
        self.audio = audio
        self.original_peaks = peaks
        self.enhanced = None
        self.enhanced_peaks = None
        self.spec_tile = None
        self.regions = regions
        self._rendered_spans = {}
        self._undo, self._redo = [], []
        self.selected = None
        self.loop_range = (regions[0].start, regions[0].end) if regions else None
        self.loop_enabled = False
        self.player.set_loop(None)
        self.source = "A"
        self.visible_start, self.visible_duration = 0.0, max(audio.duration, 0.05)
        self.player.set_signal(audio.listen, audio.source_rate)
        self.player.seek(0)
        n = len(regions)
        self.set_status(f"{n} speech region{'' if n == 1 else 's'} detected")
        self.request_spectrogram()
        self._emit_all()

    def open_demo(self) -> None:
        p = demo_path()
        if p:
            self.open(p)

    def open_demo_on_first_launch(self) -> bool:
        s = settings()
        if self.audio is not None or s.value("demoShown", False, type=bool) or demo_path() is None:
            return False
        s.setValue("demoShown", True)
        self.open_demo()
        return True

    # ------------------------------------------------------------------ regions

    def _set_regions(self, regions: list[Region]) -> None:
        self.regions = regions
        self._emit_all()

    def checkpoint(self) -> None:
        self._undo.append(list(self.regions))
        del self._undo[:-200]
        self._redo.clear()

    begin_edit = checkpoint

    def undo(self) -> None:
        if self._undo:
            self._redo.append(list(self.regions))
            self._set_regions(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(list(self.regions))
            self._set_regions(self._redo.pop())

    def detect(self) -> None:
        if not self.audio:
            return
        self.checkpoint()
        self.selected = None
        self._set_regions(core.detect(self.audio.wav16k, self.detection))
        if not self.loop_enabled:
            self.loop_range = (self.regions[0].start, self.regions[0].end) if self.regions else None
        n = len(self.regions)
        self.set_status(f"{n} speech region{'' if n == 1 else 's'} detected")

    def region(self, rid: int | None) -> Region | None:
        return next((r for r in self.regions if r.id == rid), None)

    def insert_region(self, t: float) -> None:
        """Click on empty space: a region from t up to just before the next region (or the end)."""
        nxt = next((r.start for r in self.regions if r.start > t), self.duration)
        end = nxt - 0.05 if nxt < self.duration else self.duration
        if end - t < 0.05:
            return
        self.checkpoint()
        self._set_regions(core.normalised([*self.regions, Region(t, end)], self.duration))
        self.selected = next((r.id for r in self.regions if r.contains(t + 0.01)), None)

    def add_region(self, a: float, b: float) -> None:
        if abs(b - a) < 0.05:
            return
        self.checkpoint()
        self._set_regions(core.normalised([*self.regions, Region(min(a, b), max(a, b))], self.duration))
        self.selected = next((r.id for r in self.regions if r.contains((a + b) / 2)), None)

    def remove_region(self, rid: int) -> None:
        self.checkpoint()
        if self.selected == rid:
            self.selected = None
        self._set_regions([r for r in self.regions if r.id != rid])

    def move_edge(self, rid: int, is_start: bool, t: float) -> None:
        """Move one edge between the neighbours (call begin_edit first)."""
        i = next((k for k, r in enumerate(self.regions) if r.id == rid), None)
        if i is None:
            return
        r = self.regions[i]
        if is_start:
            lo = self.regions[i - 1].end + 0.02 if i > 0 else 0.0
            r = Region(min(max(t, lo), r.end - 0.05), r.end, r.id)
        else:
            hi = self.regions[i + 1].start - 0.02 if i + 1 < len(self.regions) else self.duration
            r = Region(r.start, max(min(t, hi), r.start + 0.05), r.id)
        regions = list(self.regions)
        regions[i] = r
        self._set_regions(regions)

    def clear_regions(self) -> None:
        self.checkpoint()
        self.selected = None
        self._set_regions([])

    # ------------------------------------------------------------------ view

    def clamp_start(self, s: float) -> float:
        return min(max(0.0, s), max(0.0, self.duration - self.visible_duration))

    def set_view(self, start: float, dur: float | None = None) -> None:
        if dur is not None:
            self.visible_duration = dur
        self.visible_start = self.clamp_start(start)
        self.request_spectrogram()
        self.view_changed.emit()

    def zoom(self, factor: float, around: float) -> None:
        if self.duration <= 0:
            return
        new = min(self.duration, max(0.05, self.visible_duration / factor))
        frac = (around - self.visible_start) / self.visible_duration
        self.visible_duration = new
        self.set_view(around - frac * new)

    def zoom_to_fit(self) -> None:
        self.set_view(0, max(self.duration, 0.05))

    def scroll(self, seconds: float) -> None:
        self.set_view(self.visible_start + seconds)

    def set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        self.request_spectrogram()
        self._emit_all()

    def toggle_view_mode(self) -> None:
        self.set_view_mode("spec" if self.view_mode == "wave" else "wave")

    @property
    def display_peaks(self) -> Peaks | None:
        return self.enhanced_peaks if self.source == "B" else self.original_peaks

    @property
    def display_spec(self) -> SpecTile | None:
        t = self.spec_tile
        return t if t and t.source == self.source else None

    def request_spectrogram(self) -> None:
        if self.view_mode == "spec" and self.audio is not None:
            self._spec_token += 1
            self._spec_timer.start()

    def _signal(self) -> tuple[np.ndarray, int, str]:
        if self.source == "B" and self.enhanced is not None:
            return self.enhanced, core.OUT_SR, "B"
        return self.audio.listen, self.audio.source_rate, "A"

    def _spec_window(self) -> tuple[float, float, int]:
        margin = self.visible_duration * 0.5  # half a screen each side: panning never shows gaps
        t0 = max(0.0, self.visible_start - margin)
        t1 = min(self.duration, self.visible_start + self.visible_duration + margin)
        cols = int(max(64, min(4096, self.editor_width * 1.5 * (t1 - t0) / max(self.visible_duration, 1e-6))))
        return t0, t1, cols

    def _compute_spectrogram(self) -> None:
        if self.audio is None:
            return
        x, rate, src = self._signal()
        t0, t1, cols = self._spec_window()
        token = self._spec_token

        def work():
            img = spectrogram(x, rate, t0, t1, cols)
            if img is not None:
                self._spec.emit(SpecTile(img, t0, t1, src), token)

        threading.Thread(target=work, daemon=True).start()

    def spectrogram_sync(self) -> None:
        x, rate, src = self._signal()
        t0, t1, cols = self._spec_window()
        img = spectrogram(x, rate, t0, t1, cols)
        self.spec_tile = SpecTile(img, t0, t1, src) if img is not None else None

    def _on_spec(self, tile: SpecTile, token: int) -> None:
        if token == self._spec_token:
            self.spec_tile = tile
            self.spec_ready.emit()
            self.view_changed.emit()

    # ------------------------------------------------------------------ transport

    @property
    def active_loop(self) -> tuple[float, float] | None:
        return self.loop_range if self.loop_enabled else None

    def toggle_play(self) -> None:
        if not self.audio:
            return
        if self.player.playing:
            self.player.pause()
        else:
            self.player.set_loop(self.active_loop)
            self.player.play()
            if self.player.error:
                self.fail(self.player.error)
        self.changed.emit()

    def seek(self, t: float) -> None:
        self.player.seek(min(max(0.0, t), self.duration))
        self.view_changed.emit()
        self.changed.emit()

    def go_to_start(self) -> None:
        self.seek(self.loop_range[0] if self.loop_enabled and self.loop_range else 0.0)

    def set_loop_range(self, r: tuple[float, float] | None) -> None:
        self.loop_range = r
        self.loop_enabled = r is not None
        self.player.set_loop(self.active_loop)
        self._emit_all()

    def toggle_loop(self) -> None:
        if not self.loop_enabled and self.loop_range is None:
            sel = self.region(self.selected)
            if sel:
                self.loop_range = (sel.start, sel.end)
            elif self.regions:
                self.loop_range = (self.regions[0].start, self.regions[0].end)
            else:
                self.loop_range = (self.visible_start, self.visible_start + self.visible_duration)
        if not self.loop_enabled and self.loop_range and not (self.loop_range[0] <= self.player.time <= self.loop_range[1]):
            self.player.seek(self.loop_range[0])
        self.loop_enabled = not self.loop_enabled
        self.player.set_loop(self.active_loop)
        self._emit_all()

    def set_source(self, s: str) -> None:
        if s == self.source or not self.audio:
            return
        if s == "B":
            if self.enhanced is None:
                return
            self.player.set_signal(self.enhanced, core.OUT_SR)
        else:
            self.player.set_signal(self.audio.listen, self.audio.source_rate)
        self.player.set_loop(self.active_loop)
        self.source = s
        self.request_spectrogram()
        self._emit_all()

    def toggle_source(self) -> None:
        self.set_source("B" if self.source == "A" else "A")

    # ------------------------------------------------------------------ model

    def preload_model(self) -> None:
        folder = models.locate(settings().value("modelsFolder", "") or None)
        if folder is None:
            self.needs_models = True
            self.model_status = "Voice model not installed"
            self.model_changed.emit()
            self.changed.emit()
            return
        self.needs_models = False
        self.models_folder = folder
        self.model = None
        self._model_event.clear()
        self.model_status = "Loading model…"
        self.model_changed.emit()
        device = self.device

        def work():
            try:
                m = models.load_model(folder, device)
                self._model_ready.emit(m, "")
            except Exception as exc:
                self._model_ready.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_model_ready(self, model, err: str) -> None:
        self.model = model
        self._model_event.set()
        if model is None:
            self.model_status = "Model unavailable"
            self.fail(f"The voice model could not be loaded: {err}")
        else:
            self.model_status = model_label(model.description)
        self.model_changed.emit()
        self.changed.emit()

    def set_device(self, device: str) -> None:
        if device != self.device and not self.processing:
            self.device = device
            self.save_settings()
            self.preload_model()

    def use_models_folder(self, folder: str | Path) -> bool:
        if not models.has_models(folder):
            return False
        settings().setValue("modelsFolder", str(folder))
        self.models_installed()
        return True

    def models_installed(self) -> None:
        self.needs_models = False
        self.set_status("Voice model installed")
        self.preload_model()
        self.model_changed.emit()

    def install_models(self) -> None:
        if self.installing:
            return
        self.installing = True
        self.install_progress.emit(0.0, "Connecting…")

        def work():
            def prog(done, total):
                mb = done / 1e6
                self.install_progress.emit(done / total if total else 0.0,
                                           f"{mb:,.0f} of {total / 1e6:,.0f} MB" if total else f"{mb:,.0f} MB")

            try:
                self.installer.run(prog)
                self.install_progress.emit(1.0, "done")
            except models.Cancelled:
                self.install_progress.emit(-1.0, "Download paused — click Download to resume.")
            except Exception as exc:
                self.install_progress.emit(-1.0, f"Download failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def install_finished(self, ok: bool) -> None:
        self.installing = False
        if ok:
            self.models_installed()

    # ------------------------------------------------------------------ guided tour

    def start_tour(self) -> None:
        self.tour_step = 0
        self.changed.emit()

    def end_tour(self) -> None:
        self.tour_step = None
        settings().setValue("tourShown", True)
        self.changed.emit()

    def start_tour_if_first_time(self) -> None:
        if not self.needs_models and self.tour_step is None and not settings().value("tourShown", False, type=bool):
            self.start_tour()

    # ------------------------------------------------------------------ rendering

    def is_stale(self, r: Region) -> bool:
        return self.enhanced is not None and self._rendered_spans.get(r.id) != r

    @property
    def stale_regions(self) -> list[Region]:
        if self.enhanced is None:
            return list(self.regions)
        return [r for r in self.regions if self._rendered_spans.get(r.id) != r]

    @property
    def orphan_spans(self) -> list[Region]:
        return [r for r in self._rendered_spans.values() if r not in self.regions]

    @property
    def enhanced_stale(self) -> bool:
        return self.enhanced is not None and bool(self.stale_regions or self.orphan_spans)

    def enhance(self) -> None:
        """The whole file the first time, afterwards only what changed since the last run."""
        if self.enhanced is None or not self.enhanced_stale:
            return self.enhance_all()
        n = len(self.stale_regions)
        self._run(self.stale_regions, self.orphan_spans, f"{n} changed region{'' if n == 1 else 's'}")

    def enhance_all(self) -> None:
        if self.regions:
            self._run(list(self.regions), [], f"{self.speech_seconds:.1f} s of speech", fresh=True)

    def enhance_region(self, rid: int) -> None:
        r = self.region(rid)
        if r is None:
            return
        old = self._rendered_spans.get(rid)
        self._run([r], [old] if old is not None and old != r else [], f"region {self.regions.index(r) + 1}")

    def _run(self, targets: list[Region], clear: list[Region], label: str, fresh: bool = False) -> None:
        if self.audio is None or self.processing or not (targets or clear):
            return
        if self.needs_models:
            self.changed.emit()
            return
        self.processing = True
        self.progress = 0.0
        self.set_status(f"Enhancing {label}…")
        self._cancel = threading.Event()
        cancel = self._cancel
        audio = self.audio
        base = None if fresh or self.enhanced is None else self.enhanced.copy()
        started = time.perf_counter()

        def work():
            try:
                if self.model is None:
                    self._model_event.wait()
                if self.model is None:
                    raise RuntimeError("The voice model is not available.")
                out = base if base is not None else np.zeros(audio.wav16k.shape[0] * core.UP, np.float32)
                core.Renderer(self.model).render_regions(
                    audio, targets, out, clear, progress=self._progress.emit, cancelled=cancel.is_set)
                self._rendered.emit((out, targets, clear, fresh, label, time.perf_counter() - started, audio))
            except core.Cancelled:
                self._rendered.emit(None)
            except Exception as exc:
                self._rendered.emit(exc)

        self.changed.emit()
        threading.Thread(target=work, daemon=True).start()

    def render_sync(self) -> None:
        """Synchronous full render (headless tests)."""
        out = np.zeros(self.audio.wav16k.shape[0] * core.UP, np.float32)
        core.Renderer(self.model).render_regions(self.audio, self.regions, out)
        self._on_rendered((out, list(self.regions), [], True, "all", 0.0, self.audio))

    def _on_progress(self, p: float) -> None:
        self.progress = p
        self.changed.emit()

    def _on_rendered(self, result) -> None:
        self.processing = False
        if result is None:
            self.set_status("Cancelled")
            return
        if isinstance(result, Exception):
            self.set_status("")
            self.fail(str(result))
            return
        out, targets, clear, fresh, label, elapsed, audio = result
        if audio is not self.audio:  # another file was opened meanwhile
            self.changed.emit()
            return
        if fresh:
            self._rendered_spans = {}
        for c in clear:
            if self._rendered_spans.get(c.id) == c:
                del self._rendered_spans[c.id]
        for t in targets:
            self._rendered_spans[t.id] = t
        self.enhanced = out
        self.enhanced_peaks = Peaks(out, core.OUT_SR)
        self.set_status(f"Enhanced {label} in {elapsed:.1f} s")
        if self.source == "B":
            self.player.set_signal(out, core.OUT_SR)
            self.request_spectrogram()
        else:
            self.set_source("B")
        self._emit_all()

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------ export

    def export_whole(self, path: str | Path) -> None:
        samples, rate = core.to_rate(self.enhanced, self.audio, self.export_rate)
        core.write_wav(samples, rate, self.export_format, path)
        self.set_status(f"Exported {Path(path).name}")

    def export_regions(self, folder: str | Path) -> int:
        n = core.write_region_files(self.enhanced, self.audio, self.regions, Path(folder), self.export_rate, self.export_format)
        self.set_status(f"Exported {n} region{'' if n == 1 else 's'} to {Path(folder).name}")
        return n
