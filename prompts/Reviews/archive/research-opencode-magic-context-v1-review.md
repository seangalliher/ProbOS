# Review: RESEARCH — opencode-magic-context Absorption
**Verdict:** ✅ Approved
**Solid upstream characterization; harness is a real measurement (compression ratio), not just a doc.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. D2 instantiates `EpisodicMemory(persist_directory=str(tmp_path))` — confirm the constructor signature accepts that kwarg. If the actual API needs `data_dir` or `persist_dir`, the harness will fail at import time. Add a "verify-first the constructor signature before authoring the harness" line.
3. The harness "runs ProbOS's existing dream-consolidation summary path on the conversation" but doesn't name the API. The dream pipeline is multi-step; pick the closest single entry point (likely `dreaming.run_cycle()` or `working_memory.flush()`) and pin it in the doc. Otherwise Builder will guess.
4. The compression-ratio assertion is `0.0 < ratio <= 1.0`. If ProbOS's current path *expands* a short input (rare but possible — adding metadata/anchors), `ratio > 1.0`. Loosen to `> 0.0` and document if seen.

## Nits
- The 17-table list of magic-context's SQLite schema is useful but verbose — section 2 should keep it bullet-form.
- The renamed `cortexkit/magic-context` URL is captured; the prompt also mentions the old `opencode-magic-context` URL. Pin one canonical URL in section 1 of the doc.
- Fixture file at `tests/research/data/sample_session.json` should be `~3000 chars` — quote a target range.

## Verified
- `src/probos/cognitive/episodic.py:2509` `recall_weighted` — confirmed.
- `src/probos/types.py:580–593` `class DreamCycleStats` — confirmed (in HEAD, the dataclass is in `types.py`).
- No existing `compaction/`, `historian/`, `compression/`, `caveman/` module — gap confirmed.
- Harness skipped by default via `PROBOS_RESEARCH_BENCH=1` — opt-in discipline correct.
- Hard-constraint list forbids implementation, schema additions, and verbatim TS copies.
- Forward markers (AD-711-1/2/3) cover the absorption candidates clearly.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Pass-1 had 0 Required; pass-2 confirms cross-cutting items landed.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ Working-tree integrity reminder added to Acceptance. No config.py touch — no Build Ordering Note required.
- ✅ No phantom-API regressions introduced.
- ✅ All previously-verified symbols still match HEAD.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
