# better-agents (AD-713) build report — Behavior Contract integration

**Prompt:** `prompts/better-agents-behavior-contract-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #493
**Wave:** 130 (6 of 10)
**AD assigned:** AD-713

## Files Changed

- `src/probos/cognitive/behavior_contract.py` — new module: `_MustRule` + `ContractCase` + `BehaviorContract` Pydantic models, `load_contract()` YAML loader, `evaluate_contract()` async evaluator returning AD-566a `TestResult`-shaped dict.
- `src/probos/__main__.py` — new `_cmd_qa_run_contracts()` handler, new `qa run-contracts` argparse subparser, dispatch wiring.
- `config/contracts/sample_refusal.yaml` — example YAML contract.
- `tests/test_better_agents_behavior_contract.py` — 14 new tests.
- `DECISIONS.md` — AD-713 entry appended.

## Sections Implemented

- **D1.** `BehaviorContract` module — done. Pydantic models with `_MustRule` model_validator (R2: exactly-one-field rule) + `BehaviorContract.cases` non-empty validator + `threshold` range validator. `evaluate_contract` returns `TestResult`-shaped dict with `last_error`-style behavior (R3): `error` field is `None` unless at least one case raised.
- **D2.** CLI subcommand — done. `_cmd_qa_run_contracts` returns 0/1/2 (pass/fail/path-missing). Subparser registered alongside `doctor`. Dispatch wired in main.
- **D3.** `pyyaml` already present in `pyproject.toml:26`. No new dependency.
- **D4.** Sample contract — done at `config/contracts/sample_refusal.yaml`.
- **D5.** Tests — 14 cases (10 required + 2 R2 must-rule edge cases + 2 CLI rc=2 / empty-dir rc=0).

## Post-Build Section Audit

All five `D*` sections from the prompt have corresponding code changes. No omissions.

## Verify-First Findings

- ✅ `QualificationTest` Protocol at `qualification.py:40`; `TestResult` frozen dataclass at `:71` with all returned fields confirmed.
- ✅ `QualificationStore` at `qualification.py:136`.
- ✅ Greenfield: no existing `behavior_contract` / `qa_run_contracts` symbol.
- ✅ `pyyaml>=6.0` already in `pyproject.toml`.
- ✅ Existing CLI subparser pattern at `__main__.py:1270` — mirrored for `qa` parent + `run-contracts` child.

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_better_agents_behavior_contract.py -v -n 0
14 passed in 0.59s
```

Full gate:
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12847 passed, 16 skipped, 175 warnings in 480.10s
```

Pre-better-agents: 12833 → +14 = 12847. Test count non-decreasing.

## Hard Constraints Honored

- ✅ No `langwatch` SDK import.
- ✅ No scenario simulator (multi-turn judge-LLM); v1 is static substring/regex/regex_any only.
- ✅ Stub invoker only; hot-runtime invoker forward marker (`AD-713-1`).
- ✅ No new persistence table; result shape compatible with `QualificationStore`.
- ✅ CLI runnable against static directory in CI; does not start runtime.

## AD-numbering note

Prompt did not cite an AD number. Builder assigned AD-713 (next free above AD-712 Memvid; consistent with the other Wave 130 unassigned-prompts sequence).

## Pre-Commit Deletion Check

Top-5 staged files by line count — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID: `_MustRule` is single-responsibility; `evaluate_contract` is a pure function over `(contract, invoker) -> dict`. Loader / model / evaluator / CLI handler are all separable.
- ✅ Open/Closed: new rule types (e.g. `regex_any`, `length_range`) land as new `_MustRule` fields + branches, no existing branch needs modification.
- ✅ Dependency Inversion: `evaluate_contract` accepts an `InvokeAgentFn` callable; CLI uses a stub; AD-713-1 will swap.
- ✅ Type annotations on all public methods + the `InvokeAgentFn` Callable type alias.
- ✅ Defense in depth: pydantic validates threshold range, non-empty cases, exactly-one rule field.
- ✅ Boundary tests: empty cases (raises), out-of-range threshold (raises), empty `_MustRule` (raises), multi-field `_MustRule` (raises), invoker exception (logged-and-degrade), missing path (rc=2), empty dir (rc=0), passing/failing CLI runs.
- ✅ Test isolation: every test uses `tmp_path` for files; no shared state.
