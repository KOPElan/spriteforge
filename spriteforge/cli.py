"""Command-line entry point.

Example:
    python -m spriteforge --input video.mp4 --output out_dir
    python -m spriteforge --input video.mp4 --output out_dir \\
        --fps 12 --columns 6 --spacing 4 --model birefnet-general
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .compose import compose_sheet, standardize_frames
from .despill import despill_green_edge_frames
from .extraction import check_ffmpeg, extract_frames, normalize_to_max_size
from .matting import DEFAULT_MODEL, matte_frames
from .smoothing import smooth_alpha


def parse_target_size(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    parts = value.lower().replace("×", "x").split("x")
    if len(parts) == 1:
        w = h = int(parts[0])
    elif len(parts) == 2:
        w, h = int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"Invalid --target-size: {value!r} (expected WxH, e.g. 512x512)")
    if w <= 0 or h <= 0:
        raise ValueError("--target-size dimensions must be positive")
    return (w, h)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spriteforge",
        description="Video -> BiRefNet matting -> sprite sheet + index.json",
    )
    p.add_argument("--input", required=True, help="Input video file")
    p.add_argument("--output", required=True, help="Output directory")
    p.add_argument("--fps", type=float, default=12.0, help="Frames per second (default: 12)")
    p.add_argument("--columns", type=int, default=6, help="Sprite sheet columns (default: 6)")
    p.add_argument("--spacing", type=int, default=4, help="Pixels between cells (default: 4)")
    p.add_argument(
        "--model", default=DEFAULT_MODEL,
        help="rembg model name (default: birefnet-general). RMBG-2.0 is not the default.",
    )
    p.add_argument(
        "--no-temporal-smoothing", action="store_true",
        help="Disable the 3-frame alpha smoothing",
    )
    p.add_argument(
        "--no-despill", action="store_true",
        help="Disable edge-only green-spill removal (on by default, "
        "for green-screen material)",
    )
    p.add_argument(
        "--despill-strength", type=float, default=1.0,
        help="Green-spill removal strength 0-1 (default: 1.0)",
    )
    p.add_argument(
        "--despill-edge-width", type=int, default=3,
        help="Edge band width in pixels for green-spill removal (default: 3)",
    )
    p.add_argument(
        "--target-size", default=None,
        help="Optional per-frame size WxH, e.g. 512x512. Default: keep cropped size, "
        "padded to the largest frame.",
    )
    p.add_argument(
        "--max-size", type=int, default=720,
        help="Maximum input side in pixels (default: 720). Inputs at or "
        "below this are used as-is, never upscaled; larger inputs are "
        "scaled down to fit, aspect preserved.",
    )
    # Backwards-compatible alias for the old --square-size flag.
    p.add_argument(
        "--square-size", type=int, default=None,
        help="Deprecated alias for --max-size.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output)

    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 2
    try:
        target_size = parse_target_size(args.target_size)
        check_ffmpeg()
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    frames_out = output_dir / "frames"
    frames_out.mkdir(parents=True, exist_ok=True)

    max_size = args.square_size if args.square_size is not None else args.max_size
    with tempfile.TemporaryDirectory(prefix="spriteforge_") as tmp:
        tmp_path = Path(tmp)
        normalized = normalize_to_max_size(
            input_path, tmp_path / "normalized.mp4", max_size=max_size
        )
        extracted = extract_frames(normalized, tmp_path / "extracted", fps=args.fps)
        print(f"Extracted {len(extracted)} frames at {args.fps} fps, "
              f"input capped at {max_size}px per side (no upscale)")

        print(f"Matting with model: {args.model} "
              "(first run downloads the model weights; GPU used if available)")
        matted = matte_frames([p for p, _ in extracted], model=args.model)

        if args.no_despill:
            print("Green-spill removal: off")
        else:
            matted = despill_green_edge_frames(
                matted, strength=args.despill_strength,
                edge_width=args.despill_edge_width,
            )
            print(f"Green-spill removal: on (strength={args.despill_strength}, "
                  f"edge_width={args.despill_edge_width}px)")

        if args.no_temporal_smoothing:
            print("Temporal smoothing: off")
        else:
            matted = smooth_alpha(matted)
            print("Temporal smoothing: 3-frame alpha moving average")

        timestamps = [t for _, t in extracted]
        frames, (frame_w, frame_h) = standardize_frames(matted, target_size)

        for i, img in enumerate(frames):
            img.save(frames_out / f"frame_{i:05d}.png", "PNG")

        index = compose_sheet(
            frames, timestamps,
            sheet_path=output_dir / "sprite.png",
            index_path=output_dir / "index.json",
            columns=args.columns, spacing=args.spacing,
        )

    print(f"Frames: {len(frames)}  Frame size: {frame_w}x{frame_h}")
    print(f"Sheet: {output_dir / 'sprite.png'} "
          f"({index['sheet_size']['w']}x{index['sheet_size']['h']})")
    print(f"Index: {output_dir / 'index.json'}")
    print(f"Individual frames: {frames_out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
