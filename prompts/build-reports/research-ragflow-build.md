# Research RAGFlow build report — Context-Layer absorption study

**Prompt:** `prompts/research-ragflow-context-layer-v1.md`
**Builder:** Wave 130 builder
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #496
**Wave:** 130 (7 of 10)
**AD assigned:** AD-714

## Files Changed

- `docs/research/ragflow-absorption.md` (new) — six-section absorption study.
- `tests/research/__init__.py` (new) — package marker.
- `tests/research/test_ragflow_coverage_claims.py` (new) — option (a) coverage-claim grep guard. 5 tests.
- `DECISIONS.md` — AD-714 entry appended.

## Sections Implemented

- **D1.** Absorption doc with all six required sections (What It Does / Architecture / What ProbOS Has / Absorption Candidates / What We Reject / Recommended Follow-ups + Artifact Choice). Section 6 explicitly states "Artifact chosen: option (a)" with reasoning.
- **D2.** Option (a) chosen — coverage-claim grep test. Parses doc, extracts `path/file.py:NNN` citations, asserts file exists and line is in-bounds.

## AD-numbering

Highest pre-Wave-130 ceiling = AD-710 (roadmap). Wave 130 has consumed AD-711 (claude-bootstrap), AD-712 (Memvid), AD-713 (better-agents). RAGFlow research = AD-714.

## Tests

```
.\.venv\Scripts\pytest.exe tests/research/test_ragflow_coverage_claims.py -v -n 0
5 passed in 0.26s
```

## Hard Constraints Honored

- ✅ No `deepdoc` parser code added.
- ✅ No ES/MySQL/MinIO/Redis dependencies added.
- ✅ No verbatim upstream copy.
- ✅ Every "ProbOS already covers X" claim is grep-verified (the test enforces this).
- ✅ Exactly one of (a)/(b)/(c) shipped — option (a).
