# spriteforge Web UI — one-click deploy (no GPU build here; for GPU
# inference, run locally on an NVIDIA machine instead, see README).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPRITEFORGE_JOBS_DIR=/app/jobs

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY spriteforge ./spriteforge

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir .

RUN mkdir -p /app/jobs

EXPOSE 8000
CMD ["uvicorn", "spriteforge.web_app:app", "--host", "0.0.0.0", "--port", "8000"]
