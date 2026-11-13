"""Command-line interface.

    python -m speech_enhancer segment input.m4a            # -> input.segments.json (editable)
    python -m speech_enhancer enhance input.m4a            # -> input_enhanced.wav
    python -m speech_enhancer enhance input.m4a --segments input.segments.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def _perf_cores() -> int:
    try:  # Apple Silicon: use performance cores only, efficiency cores slow inference down
        return int(subprocess.check_output(["sysctl", "-n", "hw.perflevel0.physicalcpu"]).strip())
    except Exception:
        return 4


def _fmt(s: float) -> str:
    s = int(s)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _load(path: Path):
    from .audio import load_audio

    t = time.perf_counter()
    audio = load_audio(path)
    print(f"Loaded {path.name}: {_fmt(audio.duration)} ({audio.source_sr} Hz, {audio.channels} ch) in {time.perf_counter() - t:.1f}s")
    return audio


def _segment(audio, args):
    from .segmentation import SegmentationParams, segment_audio

    params = SegmentationParams(target_s=args.target, max_s=args.max, min_s=args.min)
    t = time.perf_counter()
    seg = segment_audio(audio.wav16k, params)
    lengths = [b - a for a, b in seg.segments]
    print(
        f"VAD segmentation: {len(seg)} segments (len min/mean/max = "
        f"{min(lengths):.1f}/{sum(lengths) / len(lengths):.1f}/{max(lengths):.1f}s) in {time.perf_counter() - t:.1f}s"
    )
    return seg


def cmd_segment(args) -> None:
    src = Path(args.input)
    audio = _load(src)
    seg = _segment(audio, args)
    out = Path(args.output) if args.output else src.with_suffix(".segments.json")
    seg.to_json(out)
    print(f"Saved -> {out}")


def cmd_enhance(args) -> None:
    from .model import SidonModel
    from .pipeline import Enhancer
    from .segmentation import Segmentation

    src = Path(args.input)
    out = Path(args.output) if args.output else src.with_name(src.stem + "_enhanced.wav")
    audio = _load(src)
    if args.segments:
        seg = Segmentation.from_json(args.segments)
        if abs(seg.duration - audio.duration) > 0.1:
            sys.exit(f"Segmentation is for a {seg.duration:.1f}s file, input is {audio.duration:.1f}s")
        print(f"Using {len(seg)} segments from {args.segments}")
    else:
        seg = _segment(audio, args)

    threads = args.threads or _perf_cores()
    t = time.perf_counter()
    model = SidonModel(backend=args.backend, precision=args.precision, num_threads=threads)
    print(f"Model: {model.description}, loaded in {time.perf_counter() - t:.1f}s")
    enhancer = Enhancer(model, crossfade_ms=args.crossfade_ms, speech_only=args.mode == "speech")
    if args.mode == "speech":
        work = enhancer.plan(seg, audio.num_samples)[2]
        print(f"Speech-only mode: {work:.1f}s of {audio.duration:.1f}s sent to the model, the rest stays silent")

    def report(p):
        print(
            f"\r  segment {p.segment + 1}/{p.total_segments}  {p.fraction:6.1%}  "
            f"elapsed {_fmt(p.elapsed_s)}  ETA {_fmt(p.eta_s) if p.eta_s == p.eta_s else '--'}",
            end="",
            flush=True,
        )

    stats = enhancer.run(audio, seg, out, subtype=args.subtype, progress=report)
    print(f"\nDone in {_fmt(stats.elapsed_s)} (RTF {stats.rtf:.3f}, {1 / stats.rtf:.1f}x real time) -> {out}")


def cmd_gui(args) -> None:
    from .gui.server import run

    run(port=args.port, open_browser=not args.no_browser, files=args.files)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="speech_enhancer", description="Sidon speech enhancement for long recordings")
    sub = p.add_subparsers(dest="cmd", required=True)

    def seg_opts(sp):
        sp.add_argument("--target", type=float, default=12.0, help="preferred segment length (s)")
        sp.add_argument("--max", type=float, default=20.0, help="maximum segment length (s)")
        sp.add_argument("--min", type=float, default=3.0, help="minimum segment length (s)")

    s = sub.add_parser("segment", help="VAD-segment a file and save editable cut points as JSON")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    seg_opts(s)
    s.set_defaults(func=cmd_segment)

    e = sub.add_parser("enhance", help="enhance a file (48 kHz mono WAV output)")
    e.add_argument("input")
    e.add_argument("-o", "--output")
    e.add_argument("--segments", help="JSON produced by `segment` (possibly hand-edited)")
    e.add_argument("--backend", default="auto", choices=["auto", "coreml", "torchscript"],
                   help="auto = Core ML on GPU if exported, else TorchScript on CPU")
    e.add_argument("--precision", default="float32", choices=["float32", "float16"], help="Core ML precision")
    e.add_argument("--threads", type=int, default=0, help="CPU threads (default: performance cores)")
    e.add_argument("--mode", default="speech", choices=["speech", "full"],
                   help="speech = process only detected speech (rest silent); full = whole file")
    e.add_argument("--crossfade-ms", type=float, default=40.0)
    e.add_argument("--subtype", default="PCM_24", choices=["PCM_16", "PCM_24", "FLOAT"])
    seg_opts(e)
    e.set_defaults(func=cmd_enhance)

    g = sub.add_parser("gui", help="open the local graphical interface in the browser")
    g.add_argument("files", nargs="*", help="audio files or folders to load at startup")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    g.set_defaults(func=cmd_gui)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
