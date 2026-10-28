"""Light temporal smoothing of the alpha channel only.

Image matting models process each frame independently, so alpha edges
can flicker frame to frame. Averaging the alpha channel over a
3-frame window (previous, current, next) damps that flicker.

Only the alpha channel is averaged; RGB is left untouched, so colours
are not smeared across moving frames. Endpoints use a 2-frame average.
All frames must share the same size -- true here, because frames are
normalised to a square before matting and smoothing runs before
bbox cropping.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def smooth_alpha(frames: list[Image.Image]) -> list[Image.Image]:
    """Return frames with 3-frame moving-average alpha (RGB unchanged)."""
    if len(frames) < 2:
        return list(frames)

    arrays = [np.asarray(img.convert("RGBA"), dtype=np.float32) for img in frames]
    alphas = [arr[:, :, 3] for arr in arrays]
    smoothed: list[Image.Image] = []

    for i, arr in enumerate(arrays):
        neighbours = []
        if i > 0:
            neighbours.append(alphas[i - 1])
        neighbours.append(alphas[i])
        if i + 1 < len(alphas):
            neighbours.append(alphas[i + 1])
        avg = np.mean(neighbours, axis=0)
        out = arr.copy()
        out[:, :, 3] = avg
        smoothed.append(Image.fromarray(out.astype(np.uint8), mode="RGBA"))
    return smoothed
