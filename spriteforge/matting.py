"""Background matting via rembg, with soft alpha preserved.

Default model is BiRefNet-general (``birefnet-general`` in rembg).
RMBG-2.0 is deliberately NOT the default, for licensing reasons
(non-commercial licence; commercial use needs a paid BRIA agreement).
Users may still pass another rembg model name via --model if they
have checked its licence themselves.

No hard binary threshold is applied to the alpha channel: the model's
soft alpha values are kept as-is, so hair, ribbons and translucent
edges keep their partial transparency.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Friendly aliases -> rembg session names. Unknown names are passed
# through to rembg unchanged, so newer rembg models still work.
MODEL_ALIASES = {
    "birefnet-general": "birefnet-general",
    "birefnet": "birefnet-general",
    "birefnet-general-lite": "birefnet-general-lite",
    "birefnet-portrait": "birefnet-portrait",
    "birefnet-dis": "birefnet-dis",
    "u2net": "u2net",
    "u2netp": "u2netp",
    "isnet-general-use": "isnet-general-use",
}

DEFAULT_MODEL = "birefnet-general"


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name.strip().lower(), name.strip())


def get_session(model: str = DEFAULT_MODEL):
    """Create a rembg session, preferring GPU (CUDA) when available.

    Falls back to CPU if onnxruntime-gpu / CUDA is not present, or if
    the installed rembg does not accept a ``providers`` argument.
    First run downloads the model weights (BiRefNet-general is ~1 GB),
    so the first run needs network access; later runs are offline.
    """
    from rembg import new_session

    session_name = resolve_model(model)
    providers = None
    try:
        import onnxruntime

        available = onnxruntime.get_available_providers()
        if "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:
        providers = None

    if providers:
        try:
            return new_session(session_name, providers=providers)
        except TypeError:
            pass  # older rembg: no providers argument
    return new_session(session_name)


def matte_image(image_path: Path, session) -> Image.Image:
    """Matte one image file, returning an RGBA image with soft alpha."""
    from rembg import remove

    with open(image_path, "rb") as f:
        data = f.read()
    result = remove(data, session=session)
    # remove() returns PNG bytes; load them without touching alpha.
    from io import BytesIO

    img = Image.open(BytesIO(result)).convert("RGBA")
    return img


def matte_frames(paths: list[Path], model: str = DEFAULT_MODEL) -> list[Image.Image]:
    """Matte frames in order, reusing one session (model loaded once)."""
    session = get_session(model)
    return [matte_image(path, session) for path in paths]
