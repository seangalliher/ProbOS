# Review: AD-668 Salience Filter

**Prompt:** `prompts/ad-668-salience-filter.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved with minor polish.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Default weights as inline dict literal.** `weights = {"relevance": 0.30, ...}` should be a module-level `_DEFAULT_WEIGHTS` constant or a `Field(default_factory=...)` on `SalienceConfig`. As written, every constructor call without explicit weights creates a fresh dict and risks drift between the dataclass default and the constructor default.
2. **Weight normalization on construction** — prompt says "if they don't sum to 1.0, normalize them". Specify the behavior on degenerate inputs (all-zero weights → divide by zero). Either reject (raise ValueError at construction) or fall back to equal weights with a warning log.
3. **`agent_context: dict[str, Any]` is untyped.** Define an `AgentScoringContext` TypedDict (or dataclass) in the same module. Loose dicts undermine type safety and make refactors brittle. Even a TypedDict with all-Optional fields is better than `dict[str, Any]`.

## Nits

4. **`SalienceScore` includes `entry: WorkingMemoryEntry` reference** — document the lifetime expectation (caller must not mutate the entry while holding the score).
5. **Threshold 0.3 is "low bar — most events promote".** Revisit after AD-670 lands; if metabolism actively forgets, the gate may want to tighten.
6. **No "Do not build" constraints** beyond the (good) Out-of-scope list. Consider naming tempting next features explicitly.
7. **No acceptance criteria with Engineering Principles compliance line.**

## Verified

- **Excellent dependency discipline** — explicitly notes AD-667 not yet implemented and designs to work standalone with current ring buffers.
- Pure computation principle stated and adhered to (no I/O, no async, no LLM).
- `from_config` classmethod pattern matches existing constructor-injection idiom.
- `TYPE_CHECKING` guard for `NoveltyGate` import — correct circular-import prevention.
- Five scoring dimensions are well-justified and orthogonal.
- Standalone-operation principle prevents this AD from blocking on AD-667.

---

## Recommendation

Ship after the typed context (item 3) and weight constant (item 1) cleanup. This is a model of good dependency discipline for ADs that depend on as-yet-unimplemented work.
