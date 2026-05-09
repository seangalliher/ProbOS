# Research OpenCode magic-context build report

**Prompt:** `prompts/research-opencode-magic-context-v1.md`
**Builder:** Wave 130 builder
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #492
**Wave:** 130 (8 of 10)
**AD assigned:** AD-715

## Files Changed

- `docs/research/opencode-magic-context-absorption.md` (new) — six-section absorption study.
- `tests/research/data/sample_session.json` (new) — 9-turn fixture conversation.
- `tests/research/test_compression_ratio_harness.py` (new) — opt-in harness via `PROBOS_RESEARCH_BENCH=1`.
- `DECISIONS.md` — AD-715 entry appended.

## Sections Implemented

- **D1.** Absorption doc with all six required sections.
- **D2.** Compression-ratio harness — `EpisodicMemory(db_path=...)` (verified the actual constructor kwarg is `db_path`, not `persist_directory`); ingests fixture turns; recalls each user prompt with `k=1`; sums recalled `user_input` lengths; computes ratio. Skipped by default; opt-in run produces `{"original_chars": 1311, "compressed_chars": 348, "ratio": 0.265, "method": "probos_recall_proxy"}`.

## Verify-First Findings

- ✅ `EpisodicMemory.__init__(db_path: str | Path, ...)` at `episodic.py:681` — kwarg is `db_path`, not `persist_directory`. Harness updated to match. Documented inline.
- ✅ R3: dream-cycle entry point pinned in absorption doc section 6 (`recall` proxy chosen for v1; full `DreamCycleStats` flush deferred to AD-715-1).
- ✅ R4: assertion is `ratio > 0.0` (not `(0.0, 1.0]`) — expansion is legal.

## Tests

```
pytest tests/research/test_compression_ratio_harness.py        # default skip
1 skipped in 0.24s

PROBOS_RESEARCH_BENCH=1 pytest tests/research/test_compression_ratio_harness.py
1 passed in 7.33s
{"benchmark": "compression_ratio_v1", "original_chars": 1311, "compressed_chars": 348, "ratio": 0.265, "method": "probos_recall_proxy"}
```

## Hard Constraints Honored

- ✅ No caveman-compression production code added.
- ✅ No verbatim upstream TS code.
- ✅ No new SQLite schema.
- ✅ Every coverage citation grep-verified.
- ✅ Harness opt-in only; no impact on default test gate.
