"""Edge-only green-spill removal (despill) for green-screen material.

AI matting only predicts an alpha mask; it does not change RGB. Pixels
on the subject outline in the original photo are a blend of foreground
and the green background (anti-aliasing, motion blur, green light
spilling onto light fur / fabric), so even a correct mask leaves a
thin green fringe on the outline. This module removes that fringe
without touching the interior:

* Only pixels within ``edge_width`` px of a transparent / semi-
  transparent pixel are touched. Fully opaque interior pixels are
  left exactly as they are, so green clothing or foliage inside the
  subject is not desaturated by this step.
* For an edge pixel, the green spill is ``G - max(R, B)`` (how much
  greener the pixel is than the brighter of red / blue). That spill
  is reduced by ``strength`` (1.0 = green is pulled down to
  ``max(R, B)``). Blue fabric (B > G) and white fur (R ~= G ~= B)
  therefore change little; a green-fringed outline changes a lot.
* Alpha is never changed by this module.

This is a post-matting RGB step, so it runs after ``matte_image`` /
``matte_frames`` and before temporal smoothing (smoothing only
changes alpha, but despill should use the original AI alpha to
define the edge band).
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def despill_green_edge(
    img: Image.Image,
    strength: float = 1.0,
    edge_width: int = 3,
) -> Image.Image:
    """Return a copy of ``img`` with green spill removed on the edge band.

    ``strength`` is clamped to [0, 1]; 0 returns an unchanged copy.
    ``edge_width`` is the edge band width in pixels (clamped to >= 0).
    """
    if strength <= 0 or edge_width < 0:
        return img.copy()
    strength = min(float(strength), 1.0)
    edge_width = int(edge_width)

    arr = np.asarray(img.convert("RGBA"), dtype=np.float32)
    alpha = arr[:, :, 3]
    if not np.any(alpha > 0):
        return img.copy()

    # Neighbour-minimum alpha over a (2*edge_width+1) square, with
    # out-of-bounds treated as opaque (255): a pixel at the image
    # border has no green background beyond the frame to blend with,
    # so border alone must not make an otherwise interior pixel edge.
    if edge_width == 0:
        neighbour_min = alpha
    else:
        padded = np.pad(alpha, edge_width, mode="constant", constant_values=255)
        neighbour_min = np.full_like(alpha, 255.0)
        h, w = alpha.shape
        for dy in range(2 * edge_width + 1):
            for dx in range(2 * edge_width + 1):
                window = padded[dy:dy + h, dx:dx + w]
                neighbour_min = np.minimum(neighbour_min, window)

    edge = (alpha > 0) & (neighbour_min < 255)
    if not np.any(edge):
        return img.copy()

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    spill = np.maximum(g - np.maximum(r, b), 0.0)
    out = arr.copy()
    out[:, :, 1] = np.where(edge, np.maximum(g - spill * strength, 0.0), g)
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def despill_green_edge_frames(
    frames: list[Image.Image],
    strength: float = 1.0,
    edge_width: int = 3,
) -> list[Image.Image]:
    """Apply :func:`despill_green_edge` to every frame."""
    return [despill_green_edge(img, strength=strength, edge_width=edge_width)
            for img in frames]
