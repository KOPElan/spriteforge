"""Video normalisation and frame extraction, via ffmpeg/ffprobe.

Input rule (updated): inputs are 720x720 or below. No forced square
upscaling and no squashing. If a video is larger than ``max_size`` on
either side it is scaled down to fit inside ``max_size`` x ``max_size``
(aspect preserved, no crop, no squash); if it is already at or below
that size it is used as-is, so small inputs are never upscaled.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def check_ffmpeg() -> None:
    """Raise a clear error if ffmpeg/ffprobe are missing."""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(
            "Missing external requirement: "
            + ", ".join(missing)
            + ". Please install FFmpeg (which provides ffmpeg and ffprobe) "
            "and make sure it is on PATH, then retry."
        )


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )


def get_video_size(input_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream via ffprobe."""
    import json

    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", str(input_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {input_path}: {result.stderr.strip()}")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream found in {input_path}")
    return int(streams[0]["width"]), int(streams[0]["height"])


def normalize_to_square(
    input_path: Path, output_path: Path, size: int = 720
) -> Path:
    """Backwards-compatible alias for :func:`normalize_to_max_size`."""
    return normalize_to_max_size(input_path, output_path, max_size=size)


def normalize_to_max_size(
    input_path: Path, output_path: Path, max_size: int = 720
) -> Path:
    """Cap a video to ``max_size`` x ``max_size`` without upscaling.

    If both sides are already <= ``max_size``, the input is returned
    unchanged (no re-encode, no upscale). Otherwise it is scaled down
    to fit inside the box, aspect preserved, no squash, no crop.
    """
    w, h = get_video_size(input_path)
    if w <= max_size and h <= max_size:
        return input_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale={max_size}:{max_size}:force_original_aspect_ratio=decrease"
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]
    )
    return output_path


def extract_frames(
    video_path: Path, frames_dir: Path, fps: float = 12.0
) -> list[tuple[Path, float]]:
    """Extract frames at ``fps`` fps. Returns [(path, timestamp_seconds)]."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(frames_dir / "frame_%05d.png")
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            pattern,
        ]
    )
    files = sorted(frames_dir.glob("frame_*.png"))
    if not files:
        raise RuntimeError(f"No frames extracted from {video_path}")
    return [(path, round(i / fps, 3)) for i, path in enumerate(files)]
