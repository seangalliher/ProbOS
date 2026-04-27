# Review: AD-671 Dream-Working Memory Integration

**Prompt:** `prompts/ad-671-dream-working-memory-integration.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved with minor cleanup.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **`dream_wm: DreamWMConfig = DreamWMConfig()`** — mutable default at the SystemConfig level. Confirm Pydantic v2 handles this safely (it usually does for BaseModel defaults, unlike dict/list), or switch to `Field(default_factory=DreamWMConfig)` to be unambiguous. Same pattern issue applies elsewhere — recommend codifying the default_factory rule project-wide.
2. **`pre_dream_flush` reads via `to_dict()`** — good (avoids private-attribute access per Demeter). Confirm `to_dict()` exists on the live `AgentWorkingMemory` (verified: yes), and document that the snapshot semantics are intentional (deep copy vs. reference).
3. **Integration into `dreaming.py` and `startup/dreaming.py`** described but no SEARCH/REPLACE blocks shown in read range. Anchor with real text per the AD-651 standard.

## Nits

4. **`max_priming_entries: 3`** — small enough to be safe, but document the rationale (avoid drowning the agent's fresh WM with stale priming).
5. **`flush_min_entries: 5`** — sensible threshold; confirm the count logic includes all five buffers (actions + observations + conversations + events + reasoning).
6. **`priming_category: str = "observation"`** — string-typed category. Once AD-667 named buffers land, this should become a typed `BufferName` enum reference.
7. **No "Do not build" constraints** beyond the good "What this does NOT include" list. Consider adding: "do not modify Step 0–15 dream behavior", "do not introduce LLM calls in the bridge".
8. **No acceptance criteria with Engineering Principles compliance line.**

## Verified

- **Pure-logic module** — no I/O, no async, no LLM. Stated explicitly. Excellent.
- `DreamReport` extension is additive (two new fields with defaults) — safe for existing consumers.
- Bridge constructor takes only `DreamWMConfig` — minimal dependencies, clean DI.
- Mechanical aggregation (no LLM summarization) is the right call — keeps the bridge fast and deterministic.
- Six-file change set is appropriately scoped (NEW bridge, EDIT dreaming, EDIT startup, EDIT config, EDIT types, NEW tests).

---

## Recommendation

Ship after SEARCH/REPLACE anchoring (item 3). Bidirectional bridge architecture is sound — pre-flush + post-seed is the minimal correct design.
