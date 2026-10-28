"""Edge-only spill removal (despill) for solid-colour backdrops.

AI matting only predicts an alpha mask; it does not change RGB. Pixels
on the subject outline in the original photo are a blend of foreground
and the backdrop (anti-aliasing, motion blur, backdrop light spilling
onto light fur / fabric), so even a correct mask leaves a thin fringe
of the backdrop colour on the outline. This module removes that fringe
without touching the interior:

* Only pixels within ``edge_width`` px of a transparent / semi-
  transparent pixel are touched. Fully opaque interior pixels are
  left exactly as they are, so clothing of the backdrop colour inside
  the subject is not desaturated by this step.
* The backdrop colour is given as a name (``green``, ``blue``, ``red``,
  ``cyan``, ``magenta``, ``yellow``) or a hex colour (``#RRGGBB``,
  ``#RGB``). Its dominant channels are the "key" channels: channels
  whose backdrop value is at least half the backdrop's maximum channel
  (so green -> G only, cyan -> G+B, magenta -> R+B, yellow -> R+G).
  For an edge pixel, the spill is ``min(key channels) -
  max(other channels)``; that spill is reduced by ``strength``
  (1.0 = the key channels are pulled down to ``max(other channels)``).
  Green therefore reduces to the old formula ``G - max(R, B)``.
* A grey / white / black backdrop has no dominant channel (all
  channels key, or none), so despill is a no-op for it: luminance
  spill is not a colour spill and this method does not apply.
* Alpha is never changed by this module.

This is a post-matting RGB step, so it runs after ``matte_image`` /
``matte_frames`` and before temporal smoothing (smoothing only
changes alpha, but despill should use the original AI alpha to
define the edge band).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

NAMED_COLORS = {
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "red": (255, 0, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
}


def resolve_color(color: str) -> tuple[int, int, int]:
    """Resolve a colour name or hex string to an (R, G, B) tuple."""
    if color is None:
        raise ValueError("despill colour is required")
    name = str(color).strip().lower()
    if name in NAMED_COLORS:
        return NAMED_COLORS[name]
    hexpart = name[1:] if name.startswith("#") else name
    if len(hexpart) == 3 and all(c in "0123456789abcdef" for c in hexpart):
        hexpart = "".join(c * 2 for c in hexpart)
    if len(hexpart) != 6 or not all(c in "0123456789abcdef" for c in hexpart):
        raise ValueError(
            f"Invalid despill colour: {color!r} "
            f"(expected green/blue/red/cyan/magenta/yellow or #RRGGBB)"
        )
    return (int(hexpart[0:2], 16), int(hexpart[2:4], 16), int(hexpart[4:6], 16))


def _key_channels(rgb: tuple[int, int, int]) -> tuple[int, ...]:
    """Indices of the backdrop's dominant channels, or () if none."""
    peak = max(rgb)
    if peak == 0:
        return ()
    return tuple(i for i, v in enumerate(rgb) if v >= peak * 0.5)


def despill_edge(
    img: Image.Image,
    strength: float = 1.0,
    edge_width: int = 3,
    color: str = "green",
) -> Image.Image:
    """Return a copy of ``img`` with backdrop spill removed on the edge band.

    ``strength`` is clamped to [0, 1]; 0 returns an unchanged copy.
    ``edge_width`` is the edge band width in pixels (clamped to >= 0).
    ``color`` is a name or hex colour, see :func:`resolve_color`.
    """
    if strength <= 0 or edge_width < 0:
        return img.copy()
    strength = min(float(strength), 1.0)
    edge_width = int(edge_width)
    key = _key_channels(resolve_color(color))
    if not key or len(key) == 3:
        return img.copy()  # grey/white/black backdrop: no colour spill to remove

    arr = np.asarray(img.convert("RGBA"), dtype=np.float32)
    alpha = arr[:, :, 3]
    if not np.any(alpha > 0):
        return img.copy()

    # Neighbour-minimum alpha over a (2*edge_width+1) square, with
    # out-of-bounds treated as opaque (255): a pixel at the image
    # border has no backdrop beyond the frame to blend with,
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

    other = [i for i in range(3) if i not in key]
    key_min = np.min(arr[:, :, list(key)], axis=2)
    other_max = np.max(arr[:, :, other], axis=2) if other else np.zeros_like(key_min)
    spill = np.maximum(key_min - other_max, 0.0)
    out = arr.copy()
    for i in key:
        ch = arr[:, :, i]
        out[:, :, i] = np.where(edge, np.maximum(ch - spill * strength, 0.0), ch)
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def despill_edge_frames(
    frames: list[Image.Image],
    strength: float = 1.0,
    edge_width: int = 3,
    color: str = "green",
) -> list[Image.Image]:
    """Apply :func:`despill_edge` to every frame."""
    return [despill_edge(img, strength=strength, edge_width=edge_width, color=color)
            for img in frames]


# Backwards-compatible aliases for the original green-only API.
def despill_green_edge(
    img: Image.Image,
    strength: float = 1.0,
    edge_width: int = 3,
) -> Image.Image:
    return despill_edge(img, strength=strength, edge_width=edge_width, color="green")


def despill_green_edge_frames(
    frames: list[Image.Image],
    strength: float = 1.0,
    edge_width: int = 3,
) -> list[Image.Image]:
    return despill_edge_frames(frames, strength=strength, edge_width=edge_width, color="green")
