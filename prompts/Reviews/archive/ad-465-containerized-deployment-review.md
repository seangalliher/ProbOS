# Review: AD-465 — Containerized Deployment

**Verdict:** ✅ Approved
**Headline:** Dockerfile, docker-compose, and config env vars all match existing patterns.

## Required

1. **Validator pattern mismatch.** Prompt specifies `@model_validator(mode="after")` for `CognitiveConfig` env var override; codebase uses `@field_validator` throughout (see [config.py:1418](src/probos/config.py#L1418), `NatsConfig`). Use `field_validator` with `@classmethod`. Add a test that sets the env var and verifies the override.

## Recommended

1. Dockerfile health check hits `/api/health`. That endpoint calls `runtime.status()` and aggregates pool health — risk of slowness/timeout under load. Consider a lightweight `/health` returning `{"status": "ok"}` for the container probe and reserve `/api/health` for full status.
2. `PROBOS_NATS_ENABLED=false` should document graceful fallback. Add a test: ProbOS boots without NATS and logs the expected warning.

## Nits

- "Line 1112" for the default host should be "around line 1112."
- Optional Ollama service in compose is correctly commented out — note that pulling `ollama:latest` (~9GB) is a one-time cost on first `docker-compose up`.

## Verified

- `pyproject.toml`: `requires-python = ">=3.12"` ✓.
- `__main__.py:1112-1113`: `--host 127.0.0.1`, `--port 18900` defaults ✓.
- `config.py:1415-1422`: `PROBOS_NATS_ENABLED` env var pattern with `field_validator` ✓.
- `routers/system.py:21`: `/api/health` endpoint exists ✓.
- `__main__.py:38-50`: `_default_data_dir()` and `--data-dir` ✓.
- NATS image `nats:2-alpine` with JetStream flag matches `mesh/intent.py` usage ✓.
