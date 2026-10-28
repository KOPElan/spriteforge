"""Suggest loop segments from already-matted frames.

This is a suggestion, not an automatic cut: it scores how smoothly a
candidate segment would loop, and a human still confirms by preview.

Input is the finished per-frame PNGs (with alpha), so no video, no
model and no GPU are involved. Each frame is reduced to a 64x64
alpha silhouette: AI videos flicker in colour and edge detail from
frame to frame, and colour would drown the pose signal, while the
silhouette is what a walk cycle actually changes.

For a candidate segment [s, e] (length L), the score combines:

* jump ratio -- D[e][s] / (mean consecutive-frame difference inside
  the segment). D is the mean absolute silhouette difference.
  A ratio near 1 means jumping back to the first frame is no bigger
  than an ordinary step inside the segment; far above 1 is a visible
  jump; far below 1 can mean the first/last poses are duplicated,
  which reads as a hitch (see note below).
* direction -- the change e -> s should point the same way as the
  changes e-1 -> e and s -> s+1, measured by cosine similarity of
  the downscaled silhouette difference vectors. A pose can look
  similar while moving the opposite way, and that still reads as a
  jump at the loop point.
* bad-frame penalty -- if any consecutive step inside the segment
  is far above the global median step, the segment contains a
  flicker / bad frame, and is penalised even if its ends match.
* motion penalty -- a segment whose poses barely change (the
  character standing still) has a near-zero jump for free, so
  segments whose pose range from the start frame is small compared
  with an ordinary step are penalised. This keeps the ranking from
  degenerating to "pick the idle bit".

Candidates are returned best-first, deduplicated so the top 3 are
not the same segment shifted by one frame (starts at least 3 apart).

Note on ratio < 1: a segment whose last frame is almost identical
to its first frame scores a small ratio and will rank highly; that
is a loop with a one-frame hold at the boundary, which is usually
less noticeable than a large jump, so ranking it highly is the
intended behaviour, and the preview is where a human catches it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

FEATURE_SIZE = 64


def _frame_feature(path: Path) -> np.ndarray:
    """Alpha silhouette of one frame, downscaled to 64x64, in [0, 1]."""
    with Image.open(path) as img:
        alpha = img.convert("RGBA").split()[-1]
        small = alpha.resize((FEATURE_SIZE, FEATURE_SIZE), Image.Resampling.BILINEAR)
        return np.asarray(small, dtype=np.float32) / 255.0


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.clip(float(np.dot(a, b)) / (na * nb), -1.0, 1.0))


def suggest_loops(
    frame_paths: list[Path],
    min_length: int = 8,
    max_length: int | None = None,
    top_n: int = 3,
) -> list[dict]:
    """Return the top loop candidates for the given frames, best first.

    Each candidate: start/end (0-based), start_frame/end_frame
    (1-based, for display), length, jump_ratio, direction (cosine,
    -1..1), score (lower is better).
    """
    n = len(frame_paths)
    if n < 4:
        return []
    min_length = max(2, min_length)
    max_length = n if max_length is None else min(max_length, n)
    if min_length > max_length:
        return []

    feats = [_frame_feature(p).reshape(-1) for p in frame_paths]
    # Pairwise mean absolute silhouette difference.
    diff = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            d = float(np.mean(np.abs(feats[i] - feats[j])))
            diff[i, j] = diff[j, i] = d
    steps = [float(diff[i, i + 1]) for i in range(n - 1)]
    median_step = float(np.median(steps)) if steps else 0.0
    if median_step < 1e-6:
        median_step = 1e-6

    candidates = []
    for length in range(min_length, max_length + 1):
        for s in range(0, n - length + 1):
            e = s + length - 1
            if length < 2:
                continue
            inside = steps[s:e]  # consecutive steps s->s+1 .. e-1->e
            step = float(np.mean(inside)) if inside else 0.0
            if step < 1e-6:
                step = 1e-6
            jump = float(diff[e, s])
            ratio = jump / step
            # Direction: jump vector vs. motion into e and out of s.
            v_jump = feats[s] - feats[e]
            v_in = feats[e] - feats[e - 1] if e > 0 else v_jump
            v_out = feats[s + 1] - feats[s] if s + 1 < n else v_jump
            direction = (_cosine(v_jump, v_in) + _cosine(v_jump, v_out)) / 2.0
            direction_penalty = 0.5 * (1.0 - max(0.0, direction))
            # Bad frame inside the segment?
            max_step = max(inside) if inside else 0.0
            spike_penalty = 0.0
            if max_step > 3.0 * median_step:
                spike_penalty = min(2.0, max_step / median_step - 3.0)
            # Pose range: how far the segment actually moves from s.
            diversity = max((float(diff[i, s]) for i in range(s, e + 1)), default=0.0)
            motion_penalty = 1.0 if diversity < 2.5 * step else 0.0
            score = ratio + direction_penalty + spike_penalty + motion_penalty
            candidates.append({
                "start": s,
                "end": e,
                "start_frame": s + 1,
                "end_frame": e + 1,
                "length": length,
                "jump_ratio": round(ratio, 2),
                "direction": round(direction, 2),
                "score": round(score, 3),
            })
    candidates.sort(key=lambda c: c["score"])
    # Deduplicate: keep starts at least 3 apart, so the top 3 are
    # genuinely different segments, not one segment shifted by 1.
    picked: list[dict] = []
    for cand in candidates:
        if all(abs(cand["start"] - p["start"]) >= 3 for p in picked):
            picked.append(cand)
        if len(picked) >= top_n:
            break
    return picked
