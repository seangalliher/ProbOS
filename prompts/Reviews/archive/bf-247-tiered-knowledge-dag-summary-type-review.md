# Review: BF-247 — TieredKnowledgeLoader Treats `dag_summary` as String

**Reviewer:** Architect
**Date:** 2026-04-29
**Verdict:** ✅ **Approved** with two minor improvements.

**Re-review (2026-04-29, second pass): ✅ Approved.** Prompt was rescoped after the
production fix landed in commit `8be47d5`. Now covers test additions only. See the
"Re-review" section at the end of this file.

---

## Summary

Clean bug fix. Diagnosis is correct, all line references verified, the SEARCH blocks match
the live code, and the proposed fix matches the pattern already used in `dreaming.py`
and `guided_reminiscence.py`. Test plan is appropriate.

Verified references:

- `src/probos/types.py:417` — `dag_summary: dict[str, Any] = field(default_factory=dict)` ✓
- `src/probos/cognitive/tiered_knowledge.py:161` — `or getattr(episode, "dag_summary", "")` ✓
- `src/probos/cognitive/tiered_knowledge.py:211` — `summary = getattr(episode, "dag_summary", "") or ""` ✓
- `tests/test_ad585_tiered_knowledge.py:20` — `dag_summary: str = "Analyzed security patterns"` ✓ (the test fake the prompt targets)

---

## Required

None.

---

## Recommended

### R1. The `summary_text = ... or str(dag.get("faithfulness_score", ""))` fallback is questionable

In Section 1:

```python
summary_text = dag.get("summary", "") or str(dag.get("faithfulness_score", ""))
```

If `dag["summary"]` is missing but `faithfulness_score` is present, this stuffs a bare
float (e.g., `"0.73"`) into the snippet list. That's a meaningless context fragment for an
LLM consumer. The reflection fallback that follows is much more useful — promote it ahead
of the faithfulness-score string:

```python
summary_text = (
    dag.get("summary", "")
    or getattr(episode, "reflection", "")
    or ""
)
```

Drop the `faithfulness_score` fallback entirely. If the `dag` dict carries no readable
summary AND there's no reflection, there's nothing useful to surface.

### R2. Section 2's logic ordering swaps the priority — verify intent

The current (buggy) code reads `reflection or dag_summary`. The proposed fix keeps that
ordering for the text source. Good. But the new code now *only* checks `dag.get("summary")`
when reflection is empty — so the search loop will miss episodes whose dag dict has a rich
summary text and a short stub reflection. If that's the desired behavior (reflection is
always preferred when present), say so in a comment. If not, build a combined haystack:

```python
texts: list[str] = []
reflection = getattr(episode, "reflection", "") or ""
if reflection:
    texts.append(reflection)
dag = getattr(episode, "dag_summary", None) or {}
if isinstance(dag, dict):
    summary = dag.get("summary", "") or ""
    if summary:
        texts.append(summary)
elif isinstance(dag, str):
    texts.append(dag)
text = " ".join(texts)
```

Either is defensible — pick one and document the choice in the prompt.

---

## Nits

- The SEARCH/REPLACE blocks should preserve the trailing newline-after-block convention
  the rest of the file uses (visible by reading the file end-to-end).
- The `from dataclasses import field` import addition note is correct and well-placed.
- "Verify all existing tests still pass after this change" — strengthen to "run
  `pytest tests/test_ad585_tiered_knowledge.py -v` and confirm the existing 25+ tests
  still pass before declaring the fix complete."

---

## Verified

- Bug is real — verified `dag_summary: dict[str, Any]` is the production type.
- Test fake mismatch (`str` vs `dict`) is exactly why the bug escaped — the prompt
  correctly identifies this and proposes the symmetrical fix.
- Pattern matches `dreaming.py` (isinstance guard for dict) and `guided_reminiscence.py`
  (default `{}` not `""`). Consistency check passes.
- Four-test plan covers: dict path (1), empty dict path (2), on-demand dict path (3),
  reflection-empty fallback (4). Reasonable coverage.
- "What This Does NOT Change" section is accurate.
- The legacy `isinstance(dag, str)` branch is good defensive code — handles old episodes
  serialized when `dag_summary` was a string.

---

## Recommended Disposition

**Approve.** R1 and R2 are quality-of-output improvements, not correctness bugs. The
builder can proceed and incorporate them at code-review time, or the author can fold
them into the prompt before building. No re-review needed.

---

## Re-review (2026-04-29, second pass)

**Verdict:** ✅ **Approved — ready for builder.**

The prompt was rescoped: the production fix landed out-of-band in commit `8be47d5`
(Sections 1-3 of the original prompt). The current prompt is now a focused test-only
follow-up that adds 4 tests covering the fixed code paths.

The rescope is well-handled:

- New "Status" header makes the rescope explicit.
- The 4-test plan from the original prompt is preserved verbatim — those tests are
  still the right coverage for the fixed code.
- "What This Does NOT Change" preserved.
- Acceptance criteria updated: now correctly states 32 existing tests must still pass
  (rather than the original "verify existing tests pass" hand-wave).

### Process note

R1 and R2 from the first pass (faithfulness-score fallback, search-haystack ordering)
are moot — the production fix has already chosen its approach (single-source
`dag.get("summary", "") or reflection`). The fix landed without those nits applied.
That's fine; the simpler shape is correct.

### Nits remaining (non-blocking)

- The "What Was Fixed" summary should cite the file paths (`tiered_knowledge.py:161,
  211` and `tests/test_ad585_tiered_knowledge.py:20`) so future readers can find the
  changes without trawling git log.
- Tracking section says "Add BF-247 as CLOSED" — but with the fix already merged and
  tests pending, BF-247 is partially closed. Either ship the tests in the same commit
  that closes the BF, or status it as "Open (tests pending)" until the test PR lands.

**Ship it.**
