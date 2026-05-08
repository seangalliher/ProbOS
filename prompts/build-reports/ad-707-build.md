# AD-707 build report — Workflow Cron Trigger (cron-only)

**Prompt:** `prompts/ad-707-workflow-cron-trigger-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #483 (cron-only; webhook + workflow API deferred)
**Wave:** 130 (3 of 10)

## Files Changed

- `src/probos/cognitive/workflow_cron.py` — new module: `WorkflowCronTrigger` dataclass + `WorkflowCronScheduler` (SQLite-persistent, in-process tick).
- `src/probos/config.py` — new `WorkflowCronTriggerConfig` model + wiring on `SystemConfig`.
- `src/probos/startup/finalize.py` — wire scheduler after AD-701 visiting officers; isinstance-gated to skip MagicMock contamination.
- `src/probos/startup/shutdown.py` — symmetric `await runtime.workflow_cron.stop()`.
- `tests/test_ad707_workflow_cron_trigger.py` — 11 new tests.
- `DECISIONS.md` — AD-707 entry appended.

## Sections Implemented

- **D1.** `WorkflowCronScheduler` module — done with cron validation, SQLite persistence, async tick loop, log-and-degrade on replay failure.
- **D2.** `WorkflowCronTriggerConfig` Pydantic model — done; placed at top-level `SystemConfig` (cleaner than nesting inside `CognitiveConfig` since `WorkflowCache` does not have its own nested config). D3 wiring adjusted to `getattr(config, "workflow_cron", ...)`.
- **D3.** Runtime wiring — done in `finalize.py`. Uses `runtime.process_natural_language` (verified at `runtime.py:2533`). isinstance-gated against the real `WorkflowCronTriggerConfig` class to avoid MagicMock contamination in tests using mock configs.
- **D4.** Tests — 11 cases (7 required + idempotency + in-memory mode + cron validator + first-eval-from-created_at).

## Post-Build Section Audit

All four `D*` sections from the prompt have corresponding code changes. No omissions.

## Verify-First Findings

- ✅ `WorkflowCache.store(self, user_input, dag)` at `workflow_cache.py:29`.
- ✅ `WorkflowCache.lookup(self, user_input) -> TaskDAG | None` at `workflow_cache.py:56`.
- ✅ `runtime.process_natural_language` at `runtime.py:2533` (no `process_nl` method).
- ✅ `croniter>=1.3` already declared in `pyproject.toml:37`.
- ✅ `DatabaseConnection` async-cm-cursor pattern matches existing usage in `journal.py:244`, `trust.py:533`, etc.
- ⚠️ Builder did not nest under `CognitiveConfig` because `WorkflowCache` does not have a sibling config there; placed at top-level `SystemConfig` adjacent to `visiting_officers`. D3 wiring path adjusted accordingly.

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_ad707_workflow_cron_trigger.py -v -n 0
11 passed in 0.41s
```

Full gate (after isinstance-gating fix):
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12803 passed, 1 environmental flake (test_dreaming.py::test_nl_to_dream_cycle_changes_weights), 16 skipped
```

The dreaming flake passes serially under `-n 0`; it is environmental (heavy concurrent fixture boot), not a regression. Documented per standing rule.

Test count progression: pre-AD-707: 12793 → +11 = 12804 (= 12803 passed + 1 environmental). Non-decreasing.

## MagicMock Contamination Fix

Initial wiring used `if vo_cfg is not None and vo_cfg.enabled` and `if wfc_cfg is not None and wfc_cfg.enabled`. This broke 5 tests in `test_new_crew_auto_welcome.py` because their MagicMock configs auto-create attributes that pass these checks, triggering background sweep loops with MagicMock intervals (`asyncio.sleep` raises TypeError).

Fix: replaced both checks with `isinstance(cfg, RealConfigClass) and cfg.enabled`. MagicMock no longer matches; tests pass cleanly.

## Hard Constraints Honored

- ✅ No webhook firing (forward marker AD-707b).
- ✅ No REST/CLI surface (forward marker AD-707c).
- ✅ Replay routes through `process_natural_language`, NOT direct `WorkflowCache.lookup` — preserves the cache fast-path.
- ✅ In-process asyncio only; no subprocess scheduling.
- ✅ Default `enabled=False` (convention #14).
- ✅ First-eval uses `created_at` as base, not `0.0` — verified by `test_is_due_uses_created_at_for_first_eval`.

## Pre-Commit Deletion Check

Top-5 staged files by line count — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID: scheduler has single responsibility (cron-driven workflow replay); cron eval delegated to module-level helpers `_validate_cron`, `_is_due`.
- ✅ Dependency Inversion: scheduler accepts `process_nl_fn`, `connection_factory`, `clock` as constructor params (testability).
- ✅ Type annotations on all public methods.
- ✅ Async hygiene: `_task` reference held; `asyncio.CancelledError` caught/cleanup/return in `_loop` and `stop`. `start()` is idempotent.
- ✅ Log-and-degrade on replay failure (regression-tested) and on cron eval failure.
- ✅ Boundary tests: invalid cron, empty user_input, persistence reload, cancel-twice, undue-trigger, failed-replay-no-fire-count-bump, cancelled-doesn't-fire.
- ✅ Defense in depth: cron validated at register-time AND at every `_is_due` call.
- ✅ Cloud-Ready Storage: uses abstract `ConnectionFactory` Protocol, not direct `aiosqlite.connect()`.
