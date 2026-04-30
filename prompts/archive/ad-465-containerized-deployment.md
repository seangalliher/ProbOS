# AD-465: Containerized Deployment (Docker)

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~3

---

## Problem

ProbOS has no containerized deployment option. Users must install Python 3.12+,
`uv`, NATS, and (optionally) Ollama manually. A Dockerfile + docker-compose
would allow single-command deployment with all dependencies pre-configured.

## Fix

### Section 1: Create `Dockerfile`

**File:** `Dockerfile` (new file, project root)

Multi-stage build:

```dockerfile
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

# Health check using the existing /api/health endpoint (system.py:21-35)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:18900/api/health')" || exit 1

# Volume for persistent data
VOLUME ["/data", "/config"]

ENTRYPOINT ["probos"]
CMD ["serve", "--host", "0.0.0.0", "--port", "18900", "--data-dir", "/data"]
```

**Key design decisions:**
- Multi-stage to keep runtime image small (~200MB vs ~800MB)
- `--host 0.0.0.0` required because `__main__.py` defaults to `127.0.0.1` (line 1112)
- Data volume at `/data` — Linux `_default_data_dir()` (line 46-50) uses XDG, but `--data-dir` CLI arg overrides it
- NATS URL points to compose service name `nats`, overriding the default `localhost:4222` in `NatsConfig` (config.py:1409-1443)
- `PROBOS_NATS_ENABLED=true` activates NATS (config.py env var override pattern)
- No `requirements.txt` needed — `pyproject.toml` (lines 21-36) is the single source of deps

### Section 2: Create `docker-compose.yml`

**File:** `docker-compose.yml` (new file, project root)

```yaml
version: "3.9"

services:
  probos:
    build: .
    ports:
      - "18900:18900"
    volumes:
      - probos-data:/data
      - ./config:/config:ro
    environment:
      - PROBOS_NATS_ENABLED=true
      - PROBOS_NATS_URL=nats://nats:4222
      # LLM config: set your provider URL
      # - PROBOS_LLM_URL=http://ollama:11434/v1
    depends_on:
      nats:
        condition: service_started
    restart: unless-stopped

  nats:
    image: nats:2-alpine
    ports:
      - "4222:4222"   # Client
      - "8222:8222"   # Monitoring
    command: ["--jetstream", "--store_dir", "/data/jetstream"]
    volumes:
      - nats-data:/data
    restart: unless-stopped

  # Optional: uncomment for local LLM
  # ollama:
  #   image: ollama/ollama:latest
  #   ports:
  #     - "11434:11434"
  #   volumes:
  #     - ollama-data:/root/.ollama
  #   deploy:
  #     resources:
  #       reservations:
  #         devices:
  #           - driver: nvidia
  #             count: 1
  #             capabilities: [gpu]

volumes:
  probos-data:
  nats-data:
  # ollama-data:
```

**Key design decisions:**
- NATS with JetStream enabled (required for AD-637 event bus — intent bus uses JetStream publish)
- Ollama commented out by default — user opts in. `deploy.resources` section requires nvidia-container-toolkit
- Config volume is read-only (`:ro`) — config files shouldn't be modified at runtime
- `depends_on` ensures NATS starts first. ProbOS handles NATS unavailability gracefully (config.py `PROBOS_NATS_ENABLED` flag)

### Section 3: Create `.dockerignore`

**File:** `.dockerignore` (new file, project root)

```
.git
.github
.venv
__pycache__
*.pyc
*.pyo
*.egg-info
dist
build
node_modules
tests
docs
prompts
hxi
.pytest_cache
.coverage
*.db
*.sqlite3
data/
```

Exclude test/dev files to keep build context small. HXI frontend (`hxi/`) excluded
because it's a separate Vite app — containerizing it would be a separate AD.

### Section 4: Add LLM configuration via environment variables

**File:** `src/probos/config.py`

The `CognitiveConfig` class (line 149) currently only reads LLM tier URLs from
config files. Docker users need env var overrides. Add env var support for the
primary LLM URL only — full tier config remains config-file-only per `.github/copilot-instructions.md`.

Find the `CognitiveConfig` class and add an env var override for the base URL.

Before adding, grep for the exact `CognitiveConfig` definition:
```
grep -n "class CognitiveConfig" src/probos/config.py
```

Then add a `model_validator` that reads `PROBOS_LLM_URL` if set, applying it
as the default tier-0 URL. Follow the existing pattern used by `NatsConfig`
(config.py:1409-1443) where `PROBOS_NATS_ENABLED` overrides the `enabled` field.

```python
@model_validator(mode="after")
def _apply_env_overrides(self) -> "CognitiveConfig":
    """Docker-friendly: allow PROBOS_LLM_URL to override default LLM endpoint."""
    import os
    url = os.environ.get("PROBOS_LLM_URL")
    if url and self.tiers and len(self.tiers) > 0:
        self.tiers[0].url = url
    return self
```

## Tests

**File:** `tests/test_ad465_containerized_deployment.py`

3 tests:

1. `test_dockerfile_exists` — verify `Dockerfile` exists at project root, contains
   `FROM python:3.12-slim`, `EXPOSE 18900`, and `probos serve` in CMD
2. `test_docker_compose_valid` — verify `docker-compose.yml` exists, contains `nats`
   service with JetStream flag, `probos` service with correct port mapping
3. `test_cognitive_config_env_override` — set `PROBOS_LLM_URL=http://test:1234/v1`
   in environment, instantiate `CognitiveConfig` with at least one tier, verify
   `tiers[0].url` is overridden. Use `monkeypatch.setenv`.

Do NOT add integration tests that build Docker images — those are too slow for CI
and require Docker daemon. The tests verify file existence and config behavior only.

## What This Does NOT Change

- No changes to Python source code except the `CognitiveConfig` env var override
- No changes to existing CLI behavior — `probos serve` works identically outside Docker
- No changes to NATS configuration defaults
- Does NOT containerize the HXI frontend (separate concern)
- Does NOT add Docker build step to CI (`ci.yml`) — that's a separate decision
- Does NOT add Kubernetes manifests (future AD)

## Tracking

- `PROGRESS.md`: Add AD-465 as COMPLETE
- `docs/development/roadmap.md`: Update AD-465 status
- `DECISIONS.md`: Record "Docker deployment uses multi-stage build with NATS sidecar"

## Acceptance Criteria

- `Dockerfile` builds successfully: `docker build -t probos .`
- `docker-compose up` starts ProbOS + NATS with JetStream
- Health endpoint responds: `curl http://localhost:18900/api/health`
- `PROBOS_LLM_URL` env var overrides LLM endpoint in config
- All 3 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# No existing Dockerfile
find . -name "Dockerfile" -o -name "docker-compose.yml" → empty

# Entry point
grep -n "probos.__main__:main" pyproject.toml
  64:probos = "probos.__main__:main"

# Python version
grep -n "python_requires" pyproject.toml
  8:requires-python = ">=3.12"

# Default bind address
grep -n "default=\"127.0.0.1\"" src/probos/__main__.py
  1112:    serve_parser.add_argument("--host", type=str, default="127.0.0.1")

# Default port
grep -n "default=18900" src/probos/__main__.py
  1113:    serve_parser.add_argument("--port", type=int, default=18900)

# NATS config env var pattern
grep -n "PROBOS_NATS" src/probos/config.py
  1418:    PROBOS_NATS_ENABLED overrides

# Health endpoint
grep -n "api/health" src/probos/routers/system.py
  21:@router.get("/api/health")

# Data dir logic
grep -n "_default_data_dir" src/probos/__main__.py
  38:def _default_data_dir() → Linux: XDG_DATA_HOME/ProbOS/data

# Dependencies in pyproject.toml (lines 21-36), no requirements.txt
```
