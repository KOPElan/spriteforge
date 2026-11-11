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
    # -hide_banner keeps stderr short: without it, ffmpeg's ~2KB
    # version banner alone fills the UI error field and pushes the
    # actual error line out of view (that is what happened with the
    # 5% failure: the real error was past the truncation point).
    if cmd and cmd[0] == "ffmpeg" and "-hide_banner" not in cmd:
        cmd = [cmd[0], "-hide_banner"] + cmd[1:]
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

    The scaled size is forced to even dimensions
    (``force_divisible_by=2``): without it, a 1920x1080 video scales
    to 720x405 and a 1080x1920 video to 405x720, and the default
    libx264 encoder with yuv420p rejects odd widths/heights
    ("height not divisible by 2"), failing the whole job at 5%.
    """
    w, h = get_video_size(input_path)
    if w <= max_size and h <= max_size:
        return input_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={max_size}:{max_size}:force_original_aspect_ratio=decrease"
          f":force_divisible_by=2")
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


def read_gif_durations(gif_path: Path) -> list[float]:
    """Per-frame durations of a GIF in seconds, via Pillow.

    Falls back to 0.1 s per frame when a frame has no duration stored.
    Raises if the file is not a readable GIF.
    """
    from PIL import Image

    durations: list[float] = []
    with Image.open(gif_path) as im:
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            ms = im.info.get("duration", 100)
            try:
                ms = int(ms)
            except (TypeError, ValueError):
                ms = 100
            durations.append(max(ms, 1) / 1000.0)
    if not durations:
        raise RuntimeError(f"No frames found in GIF {gif_path}")
    return durations


def extract_gif_frames(
    gif_path: Path, frames_dir: Path
) -> list[tuple[Path, float]]:
    """Extract every frame of a GIF, exactly once, with real timestamps.

    Unlike :func:`extract_frames` this does NOT resample to a uniform
    fps: ``-vsync 0`` keeps one PNG per GIF frame (ffmpeg composites
    delta frames correctly, which a naive Pillow seek would not), and
    timestamps come from the GIF's own per-frame durations, so a
    variable-delay GIF keeps its rhythm instead of being flattened
    to a fixed rate. Returns [(path, timestamp_seconds)].
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(frames_dir / "frame_%05d.png")
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(gif_path),
            "-vsync", "0",
            pattern,
        ]
    )
    files = sorted(frames_dir.glob("frame_*.png"))
    if not files:
        raise RuntimeError(f"No frames extracted from {gif_path}")
    try:
        durations = read_gif_durations(gif_path)
    except Exception:
        durations = []
    timestamps: list[float] = []
    t = 0.0
    for i in range(len(files)):
        timestamps.append(round(t, 3))
        # Durations unreadable (or shorter than the frame list):
        # fall back to 0.1 s per frame, the GIF default.
        t += durations[i] if i < len(durations) else 0.1
    return list(zip(files, timestamps))


def frames_have_transparency(frame_paths: list[Path]) -> bool:
    """True if any extracted frame has a pixel with alpha < 255.

    Checked on ffmpeg-composited PNGs, not on raw GIF frames: an
    optimised GIF stores later frames as small deltas whose raw
    pixels are transparent outside the delta region, so checking the
    raw frames would false-positive on opaque GIFs.
    """
    from PIL import Image

    for path in frame_paths:
        with Image.open(path) as im:
            alpha = im.convert("RGBA").split()[-1]
            if alpha.getextrema()[0] < 255:
                return True
    return False
