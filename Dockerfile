# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency spec first (cache layer)
COPY pyproject.toml ./
COPY uv.lock ./
COPY src/ ./src/
COPY config/ ./config/

# Install project with uv
RUN uv sync --no-dev --no-editable

# --- Runtime stage ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config /app/config
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Put .venv/bin on PATH so `probos` is available
ENV PATH="/app/.venv/bin:$PATH"

# Default data directory inside container
ENV PROBOS_DATA_DIR=/data

# NATS will be a sidecar — point to docker-compose service name
ENV PROBOS_NATS_ENABLED=true
ENV PROBOS_NATS_URL=nats://nats:4222

# Expose API port
EXPOSE 18900

# Health check using the existing /api/health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:18900/api/health')" || exit 1

# Volume for persistent data
VOLUME ["/data", "/config"]

ENTRYPOINT ["probos"]
CMD ["serve", "--host", "0.0.0.0", "--port", "18900", "--data-dir", "/data"]
