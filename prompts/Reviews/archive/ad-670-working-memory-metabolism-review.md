# Review: AD-670 Working Memory Metabolism

**Prompt:** `prompts/ad-670-working-memory-metabolism.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved with minor cleanup.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **`run_cycle` periodic invocation site not specified in the read range.** The prompt says "background execution during idle cognitive cycles via a periodic `run_cycle()`" but doesn't name the scheduler/owner. Add a Section explicitly editing `startup/cognitive_services.py` (or wherever periodic tasks are registered) to schedule the cycle at `cycle_interval_seconds`. Without this, metabolism never runs.
2. **Task reference for the periodic loop** — when `run_cycle` is scheduled via `asyncio.create_task`, store the reference per the async discipline standard. Document the cancellation handler (catch `CancelledError`, perform cleanup, re-raise).
3. **AUDIT consistency check is described but the contradiction-detection algorithm isn't.** Specify either (a) keyword/embedding overlap heuristic, or (b) defer to a follow-up AD and disable AUDIT by default. As specified, AUDIT is a black box.

## Nits

4. **`MetabolismConfig` defaults are sensible** but `decay_half_life_seconds: 3600.0` is aggressive — verify against episodic dwell-time observations once AD-585 lands.
5. **`forget_threshold: 0.05`** combined with `min_entries_per_buffer: 2` is a good safety net — confirm the FORGET algorithm respects the minimum (prompt implies this but doesn't show the code).
6. **Stateless service design** is the right call — explicitly noted in the docstring. Good.
7. **No "Do not build" constraints** beyond the (good) "What this does NOT include" list.
8. **No acceptance criteria with Engineering Principles compliance line.**

## Verified

- **Excellent dependency discipline** — explicitly notes AD-667 (named buffers) and AD-668 (salience filter) are not implemented and designs around them. Computes salience internally rather than blocking.
- Four-operation taxonomy (DECAY/AUDIT/FORGET/TRIAGE) is biologically grounded and orthogonal.
- `MetabolismReport` and `AuditFlag` dataclasses are `frozen=True` — immutable, good.
- Cloud-ready: stateless service, no implicit storage assumptions.
- 16 test target is reasonable.
- File change set scoped (1 new module, 1 EDIT to working memory, 1 EDIT to config, 1 new test file).

---

## Recommendation

Items 1–2 (scheduling + task reference) are the only real concerns. Item 3 (AUDIT algorithm) can be deferred if AUDIT is disabled by default, but say so explicitly.
