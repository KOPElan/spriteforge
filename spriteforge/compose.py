"""Crop, standardise and compose matted frames into a sprite sheet.

Order of operations:
1. Crop, by default to the *union* alpha bbox across all frames
   (min left/top, max right/bottom). Every frame is cropped to the
   same box, so a frame's subject keeps its absolute position in the
   cell and mask noise can no longer shift it from frame to frame.
   Per-frame cropping (the old behaviour) centred each frame's own
   bbox, which turned bbox jitter -- e.g. an isnet mask edge varying
   by a few pixels -- into visible up/down/left/right jitter, and
   also changed the scale factor per frame when a target size was
   set. Use crop_mode="per-frame" to get the old behaviour back.
   ``getbbox()`` on the alpha channel keeps any pixel with alpha > 0,
   so soft edges are not clipped by a hard threshold.
2. Standardise size: if --target-size is given, scale to fit inside it
   (aspect preserved) and pad transparently to exactly that size.
   With union cropping all frames already share one size, so the
   scale factor is identical for every frame. Otherwise, pad every
   frame transparently to the largest cropped size, centred, so the
   sheet has one uniform cell size.
3. Compose row-major (left to right, top to bottom) with spacing.

Note: union cropping preserves true motion -- a subject that really
walks across the frame will move across the cell. For walk-in-place
material that motion is small (body bob, limbs), and the result is a
stable animation instead of jitter. A single outlier frame (e.g. a
far-away stray mask pixel) widens the union for all frames, making
the cell larger but still jitter-free; that is the intended trade-off.

The index.json format is Unity-friendly (no FrameRonin compatibility
is required):
{"tool": "spriteforge", "version": "1.0", "texture": "sprite.png",
 "sheet_size": {"w": W, "h": H}, "frame_size": {"w": W, "h": H},
 "columns": 6, "rows": R, "spacing": 4, "fps": 12,
 "frames": [{"name": "frame_00000", "index": 0,
             "x": 0, "y": 0, "w": W, "h": H,
             "unity_x": 0, "unity_y": H_sheet - H,
             "pivot": {"x": 0.5, "y": 0.5}, "t": 0.0}, ...]}
``x``/``y`` are top-left image coordinates; ``unity_x``/``unity_y`` are
Unity's bottom-left sprite-rect coordinates, so a Unity importer can
use them directly with Sprite.Create / TextureImporter sprite rects.
``t`` is the frame timestamp in seconds, for animation timing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image


def crop_to_alpha_bbox(img: Image.Image) -> Image.Image:
    """Crop to the non-transparent area; return unchanged if fully empty."""
    alpha = img.convert("RGBA").split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return img
    return img.crop(bbox)


def union_alpha_bbox(
    frames: list[Image.Image],
) -> tuple[int, int, int, int] | None:
    """Union of every frame's alpha bbox; None if all frames are empty."""
    left = top = None
    right = bottom = None
    for img in frames:
        bbox = img.convert("RGBA").split()[-1].getbbox()
        if bbox is None:
            continue
        l, t, r, b = bbox
        left = l if left is None else min(left, l)
        top = t if top is None else min(top, t)
        right = r if right is None else max(right, r)
        bottom = b if bottom is None else max(bottom, b)
    if left is None:
        return None
    return (left, top, right, bottom)


def crop_to_union_bbox(
    frames: list[Image.Image],
) -> list[Image.Image]:
    """Crop every frame to the union alpha bbox.

    Fully transparent frames become a transparent image of union size,
    so they keep their place in the animation instead of breaking
    the uniform cell size.
    """
    union = union_alpha_bbox(frames)
    if union is None:
        return [img.convert("RGBA") for img in frames]
    w, h = union[2] - union[0], union[3] - union[1]
    out = []
    for img in frames:
        rgba = img.convert("RGBA")
        if rgba.split()[-1].getbbox() is None:
            out.append(Image.new("RGBA", (w, h), (0, 0, 0, 0)))
        else:
            out.append(rgba.crop(union))
    return out


def _fit_and_pad(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale to fit inside target (aspect preserved), centre on transparent."""
    fitted = img.copy()
    fitted.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    x = (target_w - fitted.width) // 2
    y = (target_h - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


def standardize_frames(
    frames: list[Image.Image],
    target_size: tuple[int, int] | None,
    crop_mode: str = "union",
) -> tuple[list[Image.Image], tuple[int, int]]:
    """Crop, then unify size. Returns (frames, (frame_w, frame_h)).

    crop_mode="union" (default): crop all frames to the union bbox.
    crop_mode="per-frame": crop each frame to its own bbox (old behaviour).
    """
    if crop_mode not in ("union", "per-frame"):
        raise ValueError(f"Unknown crop_mode: {crop_mode!r} (expected 'union' or 'per-frame')")
    if crop_mode == "union":
        cropped = crop_to_union_bbox(frames)
    else:
        cropped = [crop_to_alpha_bbox(img.convert("RGBA")) for img in frames]
    if target_size is not None:
        tw, th = target_size
        return [_fit_and_pad(img, tw, th) for img in cropped], (tw, th)
    max_w = max(img.width for img in cropped)
    max_h = max(img.height for img in cropped)
    return [_fit_and_pad(img, max_w, max_h) for img in cropped], (max_w, max_h)


def compose_sheet(
    frames: list[Image.Image],
    timestamps: list[float],
    sheet_path: Path,
    index_path: Path,
    columns: int = 6,
    spacing: int = 4,
) -> dict:
    """Compose the sheet PNG and index.json; return the index dict."""
    if not frames:
        raise ValueError("No frames to compose")
    if columns < 1:
        raise ValueError("columns must be >= 1")
    if spacing < 0:
        raise ValueError("spacing must be >= 0")

    frame_w, frame_h = frames[0].width, frames[0].height
    rows = math.ceil(len(frames) / columns)
    sheet_w = columns * frame_w + (columns - 1) * spacing
    sheet_h = rows * frame_h + (rows - 1) * spacing

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    index_frames = []
    for i, img in enumerate(frames):
        col, row = i % columns, i // columns
        x = col * (frame_w + spacing)
        y = row * (frame_h + spacing)
        sheet.paste(img, (x, y), img)
        index_frames.append(
            {
                "name": f"frame_{i:05d}",
                "index": i,
                "x": x,
                "y": y,
                "w": frame_w,
                "h": frame_h,
                # Unity sprite rects use a bottom-left origin.
                "unity_x": x,
                "unity_y": sheet_h - y - frame_h,
                "pivot": {"x": 0.5, "y": 0.5},
                "t": round(float(timestamps[i]), 3),
            }
        )

    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path, "PNG")
    fps = 0.0
    if len(timestamps) > 1 and timestamps[1] > timestamps[0]:
        # Timestamps are rounded to ms, so snap near-integer fps values.
        raw_fps = 1.0 / (timestamps[1] - timestamps[0])
        fps = int(round(raw_fps)) if abs(raw_fps - round(raw_fps)) < 0.1 else round(raw_fps, 2)
    index = {
        "tool": "spriteforge",
        "version": "1.0",
        "texture": sheet_path.name,
        "sheet_size": {"w": sheet_w, "h": sheet_h},
        "frame_size": {"w": frame_w, "h": frame_h},
        "columns": columns,
        "rows": rows,
        "spacing": spacing,
        "fps": fps,
        "frames": index_frames,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    return index
