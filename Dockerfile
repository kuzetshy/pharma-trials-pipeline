# syntax=docker/dockerfile:1
# ==============================================================================
# PharmaInsight Multi-Stage Dockerfile (Python 3.13-slim)
# Stage 1: Builder (Compiles wheels and dependencies in isolated venv)
# Stage 2: Runtime (Minimal, secure attack-surface, non-root user execution)
# ==============================================================================

# --- STAGE 1: BUILDER ---
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies required for native wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# --- STAGE 2: RUNTIME ---
FROM python:3.13-slim AS runtime

# Security: Create non-root system user and group (UID/GID 10001)
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/false -M -d /app appuser

# Install curl for container healthcheck and cleanup apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy isolated virtualenv from builder stage
COPY --from=builder /opt/venv /opt/venv

# Configure Python runtime environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    BRONZE_DIR=/app/data/bronze \
    SILVER_DIR=/app/data/silver \
    GOLD_DIR=/app/data/gold \
    LLM_PROVIDER=mock

# Copy application source code and seed data
COPY src/ /app/src/
COPY run_pipeline.py /app/run_pipeline.py
COPY data/ /app/data/

# Set ownership to unprivileged user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default entrypoint starts the Data-as-a-Service REST API
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
