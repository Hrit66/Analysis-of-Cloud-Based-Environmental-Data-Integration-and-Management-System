# ml_model/Dockerfile
# ====================
# Multi-stage build for the ML inference service.
# The backend container consumes this image; it does NOT need cloud credentials
# because model_loader.py handles all cloud fetching internally.

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app/ml_model

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY . .

# Create models cache directory (local fallback)
RUN mkdir -p models/anomaly models/forecast models/aqi_predictor models/reports

# Non-root user for security
RUN useradd -m -u 1001 mluser && chown -R mluser:mluser /app
USER mluser

# Environment defaults (override at runtime)
ENV CLOUD_PROVIDER=local \
    CLOUD_BUCKET="" \
    CLOUD_PREFIX="ml_model/" \
    LOG_LEVEL=INFO \
    ANOMALY_THRESHOLD=-0.1 \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "serving.api:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
