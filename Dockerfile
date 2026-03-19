# Dockerfile
FROM python:3.12-slim

# ---- System deps (opencv-python on slim needs these) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---- Create non-root user ----
RUN useradd -m appuser

WORKDIR /app

# ---- Install Python deps (cache-friendly) ----
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ---- Copy application code ----
COPY . /app

# ---- Runtime dirs (may be overridden by volumes) ----
RUN mkdir -p /app/uploads /app/results /app/logs \
    && chown -R appuser:appuser /app

USER appuser

# ---- Default env (override in compose / BreedBase config) ----
ENV MAX_UPLOAD_MB=25 \
    PROCESS_TIMEOUT_S=180 \
    PIPELINE_NAME=seed_size_shape \
    PIPELINE_VERSION=0.1.0

EXPOSE 8000

# Serve the Connexion app directly so its middleware handles /upload routing
CMD ["gunicorn", "-b", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "180", "api.app:app"]