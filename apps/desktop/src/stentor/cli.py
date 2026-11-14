"""Command-line interface.

    stentor segment input.m4a                     # -> input.segments.json (editable)
    stentor enhance input.m4a                     # -> input_enhanced.wav
    stentor enhance input.m4a --segments input.segments.json
    stentor weights download | status
    stentor export eager | coreml
    stentor gui                                   # extra [gui]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _perf_cores() -> int:
    try:  # Apple Silicon: performance cores only, efficiency cores slow inference down
        return int(subprocess.check_output(["sysctl", "-n", "hw.perflevel0.physicalcpu"], stderr=subprocess.DEVNULL))
    except Exception:
        return max(1, (os.cpu_count() or 4) // 2)


def _fmt(s: float) -> str:
    s = int(s)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _load(path: Path):
    from .audio import load_audio

    t = time.perf_counter()
    audio = load_audio(path)
    print(
        f"Loaded {path.name}: {_fmt(audio.duration)} ({audio.source_sr} Hz, {audio.channels} ch) "
        f"in {time.perf_counter() - t:.1f}s"
    )
    return audio


def _segment(audio, args):
    from .segmentation import SegmentationParams, segment_audio
    from .vad import get_vad

    params = SegmentationParams(target_s=args.target, max_s=args.max, min_s=args.min)
    t = time.perf_counter()
    vad = get_vad(args.vad)
    seg = segment_audio(audio.wav16k, params, vad=vad)
    lengths = [b - a for a, b in seg.segments]
    print(
        f"VAD segmentation ({vad.name}): {len(seg)} segments (len min/mean/max = "
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
    from .models import SidonModel
    from .render import SegmentRenderer
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

    options = {"precision": args.precision}
    if args.device:
        options["device"] = args.device
    t = time.perf_counter()
    model = SidonModel(
        backend=args.backend, weights_dir=args.weights, num_threads=args.threads or _perf_cores(), **options
    )
    print(f"Model: {model.description}, loaded in {time.perf_counter() - t:.1f}s")
    renderer = SegmentRenderer(model, crossfade_ms=args.crossfade_ms, speech_only=args.mode == "speech")
    if args.mode == "speech":
        work = renderer.plan_work_s(seg, audio.num_samples)
        print(f"Speech-only mode: {work:.1f}s of {audio.duration:.1f}s sent to the model, the rest stays silent")

    def report(p):
        print(
            f"\r  segment {p.segment + 1}/{p.total_segments}  {p.fraction:6.1%}  "
            f"elapsed {_fmt(p.elapsed_s)}  ETA {_fmt(p.eta_s) if p.eta_s == p.eta_s else '--'}",
            end="",
            flush=True,
        )

    stats = renderer.run(audio, seg, out, subtype=args.subtype, progress=report)
    speed = f"{1 / stats.rtf:.1f}x real time" if stats.rtf else "instant"
    print(f"\nDone in {_fmt(stats.elapsed_s)} (RTF {stats.rtf:.3f}, {speed}) -> {out}")


def cmd_weights(args) -> None:
    from . import weights

    if args.action == "download":
        d = weights.download(args.weights, cuda=args.cuda)
        print(f"Weights in {d}")
    else:
        d = weights.resolve(args.weights)
        hint = "" if os.environ.get("STENTOR_WEIGHTS_DIR") else " (set STENTOR_WEIGHTS_DIR to change)"
        print(f"Weights directory: {d}{hint}")
        for name, ok in weights.status(d).items():
            print(f"  {'ok     ' if ok else 'missing'}  {name}")


def cmd_export(args) -> None:
    try:
        _export(args)
    except ImportError as exc:
        sys.exit(f"Exporting needs PyTorch and the converters: pip install 'stentor-engine[{args.target}-export]' ({exc})"
                 if args.target != "eager" else f"Exporting needs PyTorch: pip install 'stentor-engine[torch]' ({exc})")


def _export(args) -> None:
    if args.target == "eager":
        from .export.convert_torchscript import convert_all

        convert_all(args.weights)
    elif args.target == "onnx":
        import warnings

        from .export.onnx import export

        warnings.filterwarnings("ignore")
        export(args.weights)
    else:
        import warnings

        from .export.coreml import export

        warnings.filterwarnings("ignore")
        for precision in args.precision or ["float32", "float16"]:
            export(precision, args.weights)


def cmd_gui(args) -> None:
    try:
        from .gui.server import run
    except ImportError as exc:
        sys.exit(f"The GUI needs the [gui] extra: pip install 'stentor-engine[gui]' ({exc})")
    run(port=args.port, open_browser=not args.no_browser, files=args.files)


def main(argv=None) -> None:
    import warnings

    from .models import available_backends

    warnings.filterwarnings("ignore", message=".*torch.jit.load.*is deprecated", category=FutureWarning)

    p = argparse.ArgumentParser(prog="stentor", description="Stentor: Sidon speech restoration for long recordings")
    p.add_argument("--weights", help="weights directory (default: $STENTOR_WEIGHTS_DIR or ~/.cache/stentor/weights)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def seg_opts(sp):
        sp.add_argument("--target", type=float, default=12.0, help="preferred segment length (s)")
        sp.add_argument("--max", type=float, default=20.0, help="maximum segment length (s)")
        sp.add_argument("--min", type=float, default=3.0, help="minimum segment length (s)")
        sp.add_argument("--vad", default="auto", choices=["auto", "silero", "energy"],
                        help="voice activity detector (auto: Silero if installed, else energy)")

    s = sub.add_parser("segment", help="VAD-segment a file and save editable cut points as JSON")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    seg_opts(s)
    s.set_defaults(func=cmd_segment)

    e = sub.add_parser("enhance", help="enhance a file (48 kHz mono WAV output)")
    e.add_argument("input")
    e.add_argument("-o", "--output")
    e.add_argument("--segments", help="JSON produced by `segment` (possibly hand-edited)")
    e.add_argument("--backend", default="auto", choices=["auto", *available_backends()],
                   help="auto = Core ML on GPU if exported, else TorchScript on CPU")
    e.add_argument("--precision", default="float32", choices=["float32", "float16"], help="Core ML precision")
    e.add_argument("--device", help="torch device for the eager backend (cpu, mps, cuda)")
    e.add_argument("--threads", type=int, default=0, help="CPU threads (default: performance cores)")
    e.add_argument("--mode", default="speech", choices=["speech", "full"],
                   help="speech = process only detected speech (rest silent); full = whole file")
    e.add_argument("--crossfade-ms", type=float, default=40.0)
    e.add_argument("--subtype", default="PCM_24", choices=["PCM_16", "PCM_24", "FLOAT"])
    seg_opts(e)
    e.set_defaults(func=cmd_enhance)

    w = sub.add_parser("weights", help="download or inspect the model weights")
    w.add_argument("action", choices=["download", "status"])
    w.add_argument("--cuda", action="store_true", help="also download the CUDA TorchScript files")
    w.set_defaults(func=cmd_weights)

    x = sub.add_parser("export", help="convert the TorchScript release (eager), or export Core ML / ONNX models")
    x.add_argument("target", choices=["eager", "coreml", "onnx"])
    x.add_argument("--precision", action="append", choices=["float32", "float16"], help="Core ML (repeatable)")
    x.set_defaults(func=cmd_export)

    g = sub.add_parser("gui", help="open the local graphical interface in the browser (extra [gui])")
    g.add_argument("files", nargs="*", help="audio files or folders to load at startup")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    g.set_defaults(func=cmd_gui)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
