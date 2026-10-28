"""Web UI backend for spriteforge (FastAPI, no Redis, no auth).

This module only wires HTTP + background threads around the existing
pipeline modules -- it does not duplicate matting or compose logic:

* :func:`spriteforge.extraction.normalize_to_max_size` /
  :func:`spriteforge.extraction.extract_frames` -- frame extraction
* :func:`spriteforge.matting.get_session` /
  :func:`spriteforge.matting.matte_image` -- per-frame matting, so the
  worker can report progress (``matte_frames`` would be all-or-nothing)
* :func:`spriteforge.smoothing.smooth_alpha` -- alpha temporal smoothing
* :func:`spriteforge.compose.standardize_frames` /
  :func:`spriteforge.compose.compose_sheet` -- sheet + Unity index.json

Run locally (from the project root, after ``pip install -r requirements.txt``)::

    spriteforge-web
    # or: python -m spriteforge.web_app --host 127.0.0.1 --port 8000

Then open http://127.0.0.1:8000 .

Jobs are kept in memory and stored on disk under ``SPRITEFORGE_JOBS_DIR``
(default ``./jobs``). This is intentionally simple: one worker thread
per job, no auth, no persistent queue. Suitable for local / LAN use
only -- do not expose it to the public internet without adding auth
and a reverse proxy in front of it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .cli import parse_target_size
from .compose import compose_sheet, standardize_frames
from .despill import despill_green_edge_frames
from .extraction import check_ffmpeg, extract_frames, normalize_to_max_size
from .matting import DEFAULT_MODEL, get_session, matte_image
from .smoothing import smooth_alpha

WEB_DIR = Path(__file__).resolve().parent / "web"
JOBS_DIR = Path(os.environ.get("SPRITEFORGE_JOBS_DIR", "./jobs"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB, same cap as the CLI docs
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}

app = FastAPI(title="spriteforge", version="0.1.0")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _public_job(job: dict) -> dict:
    """Job dict safe to return over the API (no filesystem paths)."""
    out = {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "error": job["error"],
        "params": job["params"],
    }
    if job["status"] == "completed":
        out["frames"] = job.get("frames", [])
        out["frame_count"] = len(job.get("frames", []))
        out["sheet_size"] = job.get("sheet_size")
        out["frame_size"] = job.get("frame_size")
    return out


def _set(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _run_job(job_id: str) -> None:
    job = _jobs[job_id]
    params = job["params"]
    job_dir = _job_dir(job_id)
    out_dir = job_dir / "output"
    frames_out = out_dir / "frames"
    try:
        _set(job_id, status="processing", progress=5)
        check_ffmpeg()
        target_size = parse_target_size(params.get("target_size") or None)
        input_path = job_dir / "input.mp4"
        with tempfile.TemporaryDirectory(prefix="spriteforge_web_") as tmp:
            tmp_path = Path(tmp)
            normalized = normalize_to_max_size(
                input_path, tmp_path / "normalized.mp4",
                max_size=params["max_size"],
            )
            extracted = extract_frames(
                normalized, tmp_path / "extracted", fps=params["fps"]
            )
            if not extracted:
                raise RuntimeError("没有从视频中提取到任何帧")
            _set(job_id, progress=20)
            # Per-frame matting (same session, same matte_image as the
            # CLI path) so progress can advance during the slow step.
            # First run downloads the model (~1 GB for BiRefNet-general)
            # and will sit at ~20-30% for a while -- that is expected.
            session = get_session(params["model"])
            total = len(extracted)
            matted = []
            for i, (path, _ts) in enumerate(extracted):
                matted.append(matte_image(path, session))
                _set(job_id, progress=20 + int(60 * (i + 1) / total))
            if params.get("despill", True):
                matted = despill_green_edge_frames(
                    matted, strength=params.get("despill_strength", 1.0),
                    edge_width=params.get("despill_edge_width", 3),
                )
            if params["temporal_smoothing"]:
                matted = smooth_alpha(matted)
            timestamps = [t for _, t in extracted]
            frames, (frame_w, frame_h) = standardize_frames(matted, target_size)
            frames_out.mkdir(parents=True, exist_ok=True)
            names = []
            for i, img in enumerate(frames):
                name = f"frame_{i:05d}.png"
                img.save(frames_out / name, "PNG")
                names.append(name)
            _set(job_id, progress=95)
            index = compose_sheet(
                frames, timestamps,
                sheet_path=out_dir / "sprite.png",
                index_path=out_dir / "index.json",
                columns=params["columns"], spacing=params["spacing"],
            )
        _set(
            job_id, status="completed", progress=100,
            frames=names, sheet_size=index["sheet_size"],
            frame_size=index["frame_size"],
        )
    except Exception as exc:  # surfaced in the UI, not just the console
        _set(job_id, status="failed", error=str(exc)[:2000])


def _safe_frame_path(job_id: str, name: str) -> Path:
    """Resolve a frame file, rejecting any path traversal attempt."""
    frames_dir = (_job_dir(job_id) / "output" / "frames").resolve()
    candidate = (frames_dir / Path(name).name).resolve()
    if candidate.parent != frames_dir or not candidate.is_file():
        raise HTTPException(status_code=404, detail="帧文件不存在")
    return candidate


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    fps: float = Form(default=12.0),
    columns: int = Form(default=6),
    spacing: int = Form(default=4),
    model: str = Form(default=DEFAULT_MODEL),
    max_size: int = Form(default=720),
    target_size: str | None = Form(default=None),
    temporal_smoothing: str = Form(default="true"),
    despill: str = Form(default="true"),
    despill_strength: float = Form(default=1.0),
    despill_edge_width: int = Form(default=3),
) -> JSONResponse:
    """Upload a video and start a job. Returns {"id": ...}."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="请上传视频文件")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的格式，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    if fps <= 0 or columns < 1 or spacing < 0 or max_size <= 0:
        raise HTTPException(status_code=400, detail="参数不合法：fps 须 > 0，列数 >= 1，间距 >= 0，max-size > 0")
    try:
        parse_target_size(target_size or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if model.strip().lower() == "bria-rmbg" or "rmbg-2" in model.lower():
        # RMBG-2.0 is non-commercial; refuse it as a default choice here
        # rather than silently producing commercially unusable output.
        raise HTTPException(
            status_code=400,
            detail="RMBG-2.0 为非商业授权，Web 界面不提供该选项，请使用 birefnet-general 等模型",
        )

    job_id = uuid.uuid4().hex[:12]
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    # Stream to disk with a hard size cap, instead of reading the
    # whole upload into memory.
    written = 0
    dest = job_dir / "input.mp4"
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件过大，上限 200MB")
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    if written == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传的文件为空")

    smoothing = temporal_smoothing.strip().lower() in ("true", "1", "on", "yes")
    despill_on = despill.strip().lower() in ("true", "1", "on", "yes")
    if not 0 <= despill_strength <= 1 or despill_edge_width < 0:
        raise HTTPException(status_code=400, detail="去绿边参数不合法：强度须在 0-1 之间，边缘宽度 >= 0")
    params = {
        "fps": fps, "columns": columns, "spacing": spacing,
        "model": model.strip(), "max_size": max_size,
        "target_size": target_size or None,
        "temporal_smoothing": smoothing,
        "despill": despill_on,
        "despill_strength": despill_strength,
        "despill_edge_width": despill_edge_width,
        "filename": file.filename,
    }
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id, "status": "queued", "progress": 0,
            "error": None, "params": params,
        }
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()
    return JSONResponse(status_code=202, content={"id": job_id})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在（服务重启后任务记录会丢失）")
    return _public_job(job)


def _require_output(job_id: str, filename: str) -> Path:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"任务尚未完成，当前状态：{job['status']}")
    path = _job_dir(job_id) / "output" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return path


@app.get("/api/jobs/{job_id}/sprite.png")
def get_sprite(job_id: str):
    return FileResponse(_require_output(job_id, "sprite.png"), media_type="image/png")


@app.get("/api/jobs/{job_id}/index.json")
def get_index(job_id: str):
    return FileResponse(
        _require_output(job_id, "index.json"), media_type="application/json"
    )


@app.get("/api/jobs/{job_id}/frames/{name}")
def get_frame(job_id: str, name: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")
    return FileResponse(_safe_frame_path(job_id, name), media_type="image/png")


@app.get("/api/jobs/{job_id}/export.zip")
def get_export_zip(job_id: str):
    sprite = _require_output(job_id, "sprite.png")
    index = _require_output(job_id, "index.json")
    frames_dir = _job_dir(job_id) / "output" / "frames"
    zip_path = _job_dir(job_id) / "output" / "export.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(sprite, "sprite.png")
        zf.write(index, "index.json")
        for frame in sorted(frames_dir.glob("frame_*.png")):
            zf.write(frame, f"frames/{frame.name}")
    return FileResponse(
        zip_path, media_type="application/zip", filename="spriteforge-export.zip"
    )


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index():
    page = WEB_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="Web 界面文件缺失：spriteforge/web/index.html")
    return FileResponse(page, media_type="text/html")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spriteforge-web",
        description="spriteforge Web UI: video -> sprite sheet + Unity index.json",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument(
        "--jobs-dir", default=None,
        help="Job storage dir (default: $SPRITEFORGE_JOBS_DIR or ./jobs)",
    )
    args = parser.parse_args(argv)
    if args.jobs_dir:
        global JOBS_DIR
        JOBS_DIR = Path(args.jobs_dir)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"spriteforge Web UI: http://{args.host}:{args.port}  (jobs dir: {JOBS_DIR})")
    import uvicorn

    uvicorn.run("spriteforge.web_app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
