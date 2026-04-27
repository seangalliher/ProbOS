# Review: AD-651 Standing Order Decomposition

**Prompt:** `prompts/ad-651-standing-order-decomposition.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved — model prompt.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **`step_categories: dict[str, str] = {...}` on `StepInstructionConfig`.** Mutable dict default — switch to `Field(default_factory=lambda: {...})`. Pydantic v2 may accept this in some cases, but the default_factory pattern is the documented standard.

## Nits

2. **`<!-- category: name -->` marker convention** — document the ABNF or regex once at the top of the file so reviewers know exactly what `analyze.py` will parse. The implementation section shows it but a single normative definition would help.
3. **20-test breakdown** could call out the backward-compat test explicitly (no markers → returns full text unchanged).

## Verified

- **Tracker section is gold standard** — full PROGRESS.md / docs/development/roadmap.md / DECISIONS.md updates with exact AD numbers and dates.
- **Explicit "DO NOT" hard rules** — names adjacent features (no LLM-based decomposition, no marker syntax extension, no caching layer) and forbids them.
- **Backward compatibility sacred** — un-marked standing orders return the full text, no behavior change for existing manuals.
- **Scope boundaries crisp** — 4 files modified, 1 new test file, no cross-cutting refactor.
- **Find/Replace blocks anchored on live code** in analyze.py / compose.py.
- **Acceptance criteria includes Engineering Principles compliance line.**
- Default `enabled: bool = False` — opt-in rollout, matches the safety budget axiom.

---

## Recommendation

Ship. Other prompts should be benchmarked against this one's structure (tracker section, scope discipline, DO NOT block, opt-in default).
