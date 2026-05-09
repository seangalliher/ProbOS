# Research LoCoMo build report

**Prompt:** `prompts/research-locomo-benchmark-v1.md`
**Builder:** Wave 130 builder
**Date:** 2026-05-08
**Status:** SHIPPED
**Issues closed:** #497 (subsumes #494)
**Wave:** 130 (9 of 10)
**AD assigned:** AD-716

## Files Changed

- `docs/research/locomo-benchmark-absorption.md` (new) — six-section absorption study.
- `tests/benchmarks/__init__.py` (new).
- `tests/benchmarks/data/micro_locomo.json` (new) — 3 sessions × 5 turns + 5 questions; expected_substring values verified-present in each session's turns.
- `tests/benchmarks/test_locomo_episodic.py` (new) — opt-in via `PROBOS_BENCHMARK_LOCOMO=1`.
- `DECISIONS.md` — AD-716 entry appended.

## Sections Implemented

- **D1.** Six-section absorption doc.
- **D2.** Harness uses `EpisodicMemory.recall(query, k)` rather than `recall_weighted` because the live `recall_weighted` signature requires a positional `agent_id` argument the micro fixture cannot supply. Documented inline in the doc and the harness module docstring; deferred to AD-716-3 follow-up.
- **D3.** Hand-authored fixture; pre-flight self-consistency check enforces every `expected_substring` is verbatim present in its named session.

## Verify-First Findings

- ✅ `EpisodicMemory.__init__(db_path: str | Path, ...)` at `episodic.py:681`.
- ✅ `EpisodicMemory.store(self, episode: Episode)` at `episodic.py:1056`.
- ✅ `EpisodicMemory.recall(query, k)` at `episodic.py:1648`.
- ⚠️ `recall_weighted` at `episodic.py:2509` requires `agent_id` as first positional argument. Prompt's harness skeleton omitted it; corrected to use `recall` for v1, deferred `recall_weighted` benchmarking to AD-716-3.

## Tests

```
pytest tests/benchmarks/test_locomo_episodic.py
1 skipped in 0.23s

PROBOS_BENCHMARK_LOCOMO=1 pytest tests/benchmarks/test_locomo_episodic.py
1 passed in 7.74s
```

## Hard Constraints Honored

- ✅ No real LoCoMo dataset download.
- ✅ No LLM-judge in v1.
- ✅ Opt-in only; no default-gate slowdown.
- ✅ No external network calls.
- ✅ Score is directional, not for external publication.
- ✅ Every coverage citation grep-verified.
