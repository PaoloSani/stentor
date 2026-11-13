"""Enhance all audio files in a folder using SpeechDenoisingProcessor.

Writes outputs into a sibling folder 'audio_48kHz_enh' next to the input folder.
Supports multiple parallel workers (one process per GPU/device-slot) and batching.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
from pathlib import Path
from typing import List

import soundfile as sf
import numpy as np
import torch
from tqdm import tqdm
import stat
import os

from enhance_audio.processor import SpeechDenoisingProcessor

AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".ogg", ".m4a")


def set_permissions(target_dir: str = '.'):
    if not os.path.isdir(target_dir):
        print(f"The path '{target_dir}' doesn't exist.")
        return

    for root, dirs, files in os.walk(target_dir):
        for d in dirs:
            os.chmod(os.path.join(root, d), stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        for f in files:
            os.chmod(os.path.join(root, f), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)

    os.chmod(target_dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)


def find_audio_files(input_dir: Path) -> List[Path]:
    files = [
        p for p in sorted(input_dir.rglob("*"))
        if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file()
    ]
    return files


def filter_unprocessed(
    files: List[Path], input_root: Path, output_root: Path, force: bool
) -> List[Path]:
    """Keep only files whose enhanced output doesn't already exist."""
    if force:
        return files
    pending = []
    for file_path in files:
        relative = file_path.relative_to(input_root)
        out_path = (output_root / relative).with_suffix(".wav")
        if not out_path.exists():
            pending.append(file_path)
    return pending


def sort_by_size(files: List[Path]) -> List[Path]:
    """Sort files by on-disk size (cheap proxy for duration) to group
    similar-length files into the same batch, minimizing padding waste.
    Uses only filesystem metadata -- no audio decoding."""
    sized = [(f, f.stat().st_size) for f in files]
    sized.sort(key=lambda item: item[1])
    return [f for f, _ in sized]


def chunk_list(items: List[Path], n_chunks: int) -> List[List[Path]]:
    chunks: List[List[Path]] = [[] for _ in range(n_chunks)]
    for idx, item in enumerate(items):
        chunks[idx % n_chunks].append(item)
    return chunks


def batched(items: List[Path], batch_size: int) -> List[List[Path]]:
    """Split a list into consecutive batches of at most batch_size."""
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def worker(
    worker_id: int,
    files: List[Path],
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> None:
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = SpeechDenoisingProcessor(
        device=device,
        chunk_seconds=args.chunk_seconds,
        target_sample_rate=args.target_sample_rate,
    )

    max_batch_samples = processor.chunk_samples  # 16kHz samples

    files = sort_by_size(files)
    batches = batched(files, args.batch_size)

    iterator = tqdm(batches, desc=f"Worker {worker_id}", position=worker_id)
    for batch_paths in iterator:
        out_paths: List[Path] = []
        waveforms: List[torch.Tensor] = []
        sample_rates: List[int] = []
        long_items = []

        for file_path in batch_paths:
            relative = file_path.relative_to(input_root)
            out_path = (output_root / relative).with_suffix(".wav")
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if out_path.exists() and not args.force:
                continue

            try:
                x, sr = sf.read(str(file_path), dtype=np.float32)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[Worker {worker_id}] Failed reading {file_path}: {exc}")
                if not args.skip_errors:
                    raise
                continue

            try:
                wav_16k = processor._to_mono_16k(x, sr)  # 1D tensor @ 16kHz
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[Worker {worker_id}] Failed preprocessing {file_path}: {exc}")
                if not args.skip_errors:
                    raise
                continue

            if wav_16k.shape[-1] <= max_batch_samples:
                out_paths.append(out_path)
                waveforms.append(wav_16k)
                sample_rates.append(16_000)
            else:
                long_items.append((file_path, out_path, x, sr))

        if waveforms:
            expected_lengths = [
                int(round(wav.shape[-1] / 16_000 * args.target_sample_rate))
                for wav in waveforms
            ]
            try:
                results = processor.process_batch(
                    waveforms,
                    sample_rates=sample_rates,
                    expected_lengths=expected_lengths,
                )
                for out_path, restored in zip(out_paths, results):
                    sf.write(
                        str(out_path),
                        restored.numpy().astype(np.float32),
                        args.target_sample_rate,
                    )
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[Worker {worker_id}] Batch failed: {exc}")
                if not args.skip_errors:
                    raise

        for file_path, out_path, x, sr in long_items:
            try:
                enhanced = processor.process_single(x, sr)
                sf.write(str(out_path), np.squeeze(enhanced), processor.target_sample_rate)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[Worker {worker_id}] Failed on {file_path}: {exc}")
                if not args.skip_errors:
                    raise


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", help="Folder containing audio files to enhance")
    parser.add_argument("--device", default="auto", help="cuda, cpu, or auto")
    parser.add_argument("--chunk-seconds", type=float, default=20.0)
    parser.add_argument("--target-sample-rate", type=int, default=48_000)
    parser.add_argument("--highpass-cutoff", type=float, default=50.0)
    parser.add_argument(
        "--num-workers", type=int, default=1,
        help="Number of parallel worker processes",
    )
    parser.add_argument(
        "--batch-size", type=int, default=8,
        help="Number of files to batch together per inference call",
    )
    parser.add_argument(
        "--skip-errors", action="store_true",
        help="Continue when a file fails to process",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reprocess files even if output already exists",
    )
    return parser


def main() -> None:
    parser = build_argparser()
    args = parser.parse_args()

    input_root = Path(args.input_dir).expanduser().resolve()
    if not input_root.is_dir():
        parser.error(f"Input folder not found: {input_root}")

    all_files = find_audio_files(input_root)
    if not all_files:
        print(f"No audio files found in {input_root}")
        return

    output_root = input_root.parent / "audio_48kHz_enh"
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        files = filter_unprocessed(all_files, input_root, output_root, args.force)
        skipped = len(all_files) - len(files)
        print(
            f"Found {len(all_files)} files, {skipped} already processed, "
            f"{len(files)} pending. Output -> {output_root}"
        )

        if not files:
            print("Nothing to do.")
            return

        if args.num_workers <= 1:
            worker(0, files, input_root, output_root, args)
        else:
            chunks = chunk_list(files, args.num_workers)
            mp.set_start_method("spawn", force=True)
            processes = []
            for worker_id, chunk in enumerate(chunks):
                if not chunk:
                    continue
                p = mp.Process(
                    target=worker,
                    args=(worker_id, chunk, input_root, output_root, args),
                )
                p.start()
                processes.append(p)
            for p in processes:
                p.join()

        print("Done.")
    finally:
        set_permissions(str(output_root))


if __name__ == "__main__":
    main()