# AD-487 Build Report

**Wave:** 14 (single-prompt)
**Date:** 2026-05-03
**Builder mode:** continuous, single commit

## Outcome

- **Tests:** 10693 passed, 15 skipped (delta **+16** vs baseline 10677)
- **Focused gate:** `tests/test_ad487_self_distillation.py` — 16/16 pass at `-n 0`
- **Full gate:** `pytest tests/ -q -n 8 --dist=loadfile` — green
- **Hard-stops triggered:** 0
- **Flakes observed:** 0

## Sections shipped (all 6 audited)

| § | Description | Files touched |
|---|---|---|
| 0 | 2 EventTypes (`ONTOLOGY_PROBE_RECORDED`, `ONTOLOGY_PROBE_RATE_LIMITED`) | `events.py` |
| 1 | New `cognitive/self_distillation/` package | `__init__.py`, `prober.py` |
| 2 | `ProbeResult` frozen dc + `ProbeLLMError` + `ProbeRateLimitedError` | `prober.py` |
| 3 | `PersonalOntologyProber` class — async lifecycle + Map probe + recent-list | `prober.py` |
| 4 | `SelfDistillationConfig` Pydantic + `SystemConfig.self_distillation` | `config.py` |
| 5 | `_wire_self_distillation` phase function + call site | `startup/finalize.py` |

## Confirmations (review-mandated)

- ✅ `runtime.llm_client.complete(LLMRequest(...), priority=Priority.NORMAL)` — NOT phantom `chat()`. Verified at the call site (`prober.py:147-150`).
- ✅ `SystemConfig.self_distillation` — NOT phantom `Config.self_distillation`. Wired at `config.py:1908`.
- ✅ Constructor follows Wave 5 convention #2: `connection_factory: ConnectionFactory | None = None` keyword-only with `default_factory` fallback. `_db: DatabaseConnection | None` typed against the protocol surface (NOT phantom `ConnectionFactory` field type from pass-1 R3).

## Beyond-prompt repair

The prompt's wire function `if not config.self_distillation.enabled:` early-return guards against MagicMock-config tests for purely in-memory wirings (e.g., `_wire_anomaly_window`). It does NOT guard against a wire function that performs I/O — `tests/test_new_crew_auto_welcome.py` passes `MagicMock` for `config`, which:
1. makes `.enabled` a truthy MagicMock — bypasses the early return;
2. makes `config.self_distillation.db_path` a MagicMock that aiosqlite cannot stringify into an openable path.

The first invocation triggered 4 pre-existing test failures. Repair: defensive `isinstance(config.self_distillation, SelfDistillationConfig)` boundary check at the top of `_wire_self_distillation`. This matches the "Defense in Depth: Validate at every boundary" standing order. Documented in PROGRESS.md and DECISIONS.md so the smell is tracked, not hidden.

## Test count breakdown

- 16 new tests in `tests/test_ad487_self_distillation.py` (1 over the prompt's stated 15 target — added `test_probe_domain_llm_error_raises_probe_llm_error` for the `response.error` path coverage; brings boundary count to 3 for `probe_domain`: happy / rate-limited / LLM-error).

## Pre-commit deletion sanity check

Will run `git diff --cached --stat` before commit. Expected: small additions to `events.py`, `config.py`, `startup/finalize.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`; new files in `src/probos/cognitive/self_distillation/` and `tests/`. No large deletions anywhere.
