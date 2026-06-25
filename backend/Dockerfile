# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Backend image — serves FastAPI (uvicorn) AND runs the Celery worker/beat.
# Same image, different start command (set per Container App / compose service).
# Build context MUST be the repo root so we can copy both `backend/` and `seed/`.
#   docker build -f backend/Dockerfile -t <tag> .
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # backend root holds BOTH `app/` and top-level `core/` packages
    PYTHONPATH=/app

# System dependencies for OCR / PDF / image processing:
#   tesseract-ocr        -> pytesseract
#   libgl1 + libglib2.0  -> opencv (cv2)
#   poppler-utils        -> PDF rasterisation helpers
#   libpq5               -> postgres client libs (safety for native drivers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt gunicorn

# Copy application code (app/, core/, alembic/, alembic.ini) and seed scripts
COPY backend/ /app/
COPY seed/ /app/seed/

# Tesseract is on PATH inside the container
ENV TESSERACT_CMD=/usr/bin/tesseract \
    UPLOAD_DIR=/app/uploads

RUN mkdir -p /app/uploads/raw /app/uploads/processed /app/uploads/ocr /app/uploads/extracted \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000

# entrypoint optionally runs migrations (RUN_MIGRATIONS=true) then execs the CMD
ENTRYPOINT ["/app/entrypoint.sh"]

# Default = API server. Worker/beat override this command.
# 2 uvicorn workers; tune via container scaling instead of cramming workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
