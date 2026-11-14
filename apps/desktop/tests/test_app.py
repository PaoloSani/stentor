"""Fast checks of the desktop app's logic (no voice model, no display)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import soundfile as sf

from stentor_desktop import core, visuals
from stentor_desktop.cards import is_newer
from stentor_desktop.project import model_label

SR = 16_000


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    QApplication.setOrganizationName("Stentor-tests")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tone_file(tmp_path):
    """3 s at 44.1 kHz stereo: silence, 1 s of tone, silence."""
    sr = 44_100
    x = np.zeros((sr * 3, 2), np.float32)
    t = np.arange(sr) / sr
    x[sr:2 * sr, 0] = x[sr:2 * sr, 1] = 0.5 * np.sin(2 * np.pi * 220 * t)
    path = tmp_path / "tone.wav"
    sf.write(path, x, sr)
    return path


class FakeModel:
    description = "fake"

    def enhance(self, x):
        return np.repeat(np.asarray(x, np.float32), 3)


def test_load_and_detect(tone_file):
    a = core.load(tone_file)
    assert a.source_rate == 44_100 and a.channels == 2
    assert abs(a.duration - 3.0) < 1e-3
    assert abs(float(np.abs(a.listen).max()) - 0.9) < 1e-3
    regions = core.detect(a.wav16k)
    assert len(regions) == 1
    assert abs(regions[0].start - (1.0 - 0.15)) < 0.05 and abs(regions[0].end - (2.0 + 0.25)) < 0.05


def test_normalised_merges_and_clamps():
    r = core.normalised([core.Region(1, 2), core.Region(1.5, 3), core.Region(-1, 0.5), core.Region(9, 12)], 10)
    assert [(x.start, x.end) for x in r] == [(0, 0.5), (1, 3), (9, 10)]


def test_renderer_output_length_and_silence(tone_file):
    a = core.load(tone_file)
    out = np.zeros(a.wav16k.shape[0] * 3, np.float32)
    core.Renderer(FakeModel()).render_regions(a, [core.Region(1.0, 2.0)], out)
    assert out.shape[0] == a.wav16k.shape[0] * 3
    assert np.all(out[: int(0.99 * core.OUT_SR)] == 0) and np.all(out[int(2.01 * core.OUT_SR):] == 0)
    mid = slice(int(1.2 * core.OUT_SR), int(1.8 * core.OUT_SR))
    np.testing.assert_allclose(out[mid], np.repeat(a.wav16k, 3)[mid], atol=1e-6)


def test_long_region_is_split_and_crossfaded_seamlessly():
    w = (np.random.default_rng(0).standard_normal(SR * 30) * 0.1).astype(np.float32)
    a = core.Audio(path=None, source_rate=SR, channels=1, listen=w, wav16k=w)
    chunks = core.Renderer.split(0, w.shape[0], w)
    assert len(chunks) >= 3 and all((b - c) / SR <= core.Renderer.MAX_CHUNK for c, b in chunks)
    out = np.zeros(w.shape[0] * 3, np.float32)
    core.Renderer(FakeModel()).render_regions(a, [core.Region(0, 30)], out)
    inner = slice(core.OUT_SR, 29 * core.OUT_SR)
    np.testing.assert_allclose(out[inner], np.repeat(w, 3)[inner], atol=1e-5)  # Hann crossfades sum to one


def test_project_editing_and_incremental_render(qapp, tone_file):
    from stentor_desktop.project import Project

    p = Project(preload=False)
    p.load_sync(tone_file)
    p.model = FakeModel()
    p.clear_regions()
    p.add_region(0.2, 0.8)
    p.add_region(1.5, 2.5)
    p.render_sync()
    assert not p.enhanced_stale
    first = p.enhanced.copy()
    p.begin_edit()
    p.move_edge(p.regions[1].id, True, 1.4)
    assert p.enhanced_stale and len(p.stale_regions) == 1
    p.undo()
    assert not p.enhanced_stale
    p.remove_region(p.regions[0].id)
    assert p.orphan_spans and p.enhanced_stale
    np.testing.assert_array_equal(p.enhanced, first)


def test_exports(qapp, tone_file, tmp_path):
    from stentor_desktop.project import Project

    p = Project(preload=False)
    p.load_sync(tone_file)
    p.model = FakeModel()
    p.render_sync()
    p.export_rate, p.export_format = "source", "pcm16"
    out = tmp_path / "whole.wav"
    p.export_whole(out)
    info = sf.info(out)
    assert info.samplerate == 44_100 and info.frames == 3 * 44_100 and info.subtype == "PCM_16"
    folder = tmp_path / "regions"
    folder.mkdir()
    assert p.export_regions(folder) == len(p.regions)
    assert (folder / "tone_regions.csv").read_text().startswith("file,index,start_s")


def test_peaks_match_brute_force_when_zoomed_in():
    x = np.random.default_rng(1).standard_normal(48_000).astype(np.float32)
    pk = visuals.Peaks(x, 48_000)
    mn, mx = pk.columns(0.1, 0.2, 300)
    edges = np.floor(0.1 * 48_000 + np.arange(301) * 4800 / 300).astype(int)
    np.testing.assert_array_equal(mx, [x[a:max(b, a + 1)].max() for a, b in zip(edges[:-1], edges[1:])])
    np.testing.assert_array_equal(mn, [x[a:max(b, a + 1)].min() for a, b in zip(edges[:-1], edges[1:])])


def test_spectrogram_shape_and_palette():
    x = np.sin(2 * np.pi * 1000 * np.arange(48_000) / 48_000).astype(np.float32)
    img = visuals.spectrogram(x, 48_000, 0, 1, 200)
    assert img.shape == (visuals.ROWS, 200) and img.dtype == np.uint32
    row = int(np.argmax((img[:, 100] & 0xFF).astype(int) + ((img[:, 100] >> 16) & 0xFF)))  # brightest row
    freq = visuals.MIN_FREQ * (24_000 / visuals.MIN_FREQ) ** ((visuals.ROWS - 1 - row + 0.5) / visuals.ROWS)
    assert 850 < freq < 1200


def test_versions_and_labels():
    assert is_newer("0.4.0", "0.3.1") and not is_newer("0.3.1", "0.3.1") and is_newer("v1.0", "0.9.9")
    assert model_label("ONNX Runtime (Dml)") == "ONNX Runtime · GPU (DirectML)"
    assert core.region_file_name("talk", 3, 75.5) == "talk_enhanced_03_1m15.50s.wav"
    assert core.timecode(75.25, 0.01) == "1:15.25"


def test_player_loops_seamlessly_and_stops_at_the_end():
    import sounddevice as sd

    from stentor_desktop.player import Player

    pl = Player()
    x = np.arange(1000, dtype=np.float32)
    pl.set_signal(x, 1000)
    pl.set_loop((0.1, 0.2))  # frames 100..200
    pl.seek(0.15)
    out = np.zeros((120, 2), np.float32)
    pl._callback(out, 120, None, None)
    expected = np.concatenate([np.arange(150, 200), np.arange(100, 170)])
    np.testing.assert_array_equal(out[:, 0], expected)
    np.testing.assert_array_equal(out[:, 1], expected)
    pl.set_loop(None)
    pl.seek(0.95)
    out = np.zeros((100, 2), np.float32)
    with pytest.raises(sd.CallbackStop):
        pl._callback(out, 100, None, None)
    np.testing.assert_array_equal(out[:50, 0], np.arange(950, 1000))
    assert np.all(out[50:] == 0)
