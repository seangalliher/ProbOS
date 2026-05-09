# Review: Memvid Pattern 1 — QueryPlanner Relational
**Verdict:** ✅ Approved
**Clean greenfield router; opt-in flag respects convention #14; Protocol-widening conditional already present.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. The classifier regex `_WHO_RE` group 2 is `[A-Za-z0-9_\\- ]+` — greedy match swallows trailing words like "?" "." (the code strips `?.!,` but not interior punctuation). Add a test for "who works at engineering, please?" to lock the trim behavior. Optional but cheap.
3. D3 says "Inject `_query_planner` via a setter (`set_query_planner`) per the Hebbian-injection pattern at `trust.py:165`" — actual line is `:150`. Same drift as AD-702; tighten.
4. `recall_with_fallback` swallows ALL exceptions from `recall_by_anchor` and quietly falls back. This is the right tier (log-and-degrade), but the log call uses `.debug` — bump to `.warning` per Engineering-Principle "guard clause log levels" (anchor lookup failure is a real degradation, not normal operation).

## Nits
- `QueryPlan.anchor_kwargs` is mutable `dict[str, Any]` on a `frozen=True` dataclass via `field(default_factory=dict)` — works, but unusual. Consider `Mapping[str, Any]` typing if the contract is read-only.
- `QueryShape = str` with comment listing literals — okay for v1; `Literal[...]` would self-document.

## Verified
- `src/probos/cognitive/episodic.py:1648` `async def recall(self, query: str, k: int = 5)` — confirmed.
- `src/probos/cognitive/episodic.py:2747` `async def recall_by_anchor(*, ...)` — confirmed.
- `src/probos/cognitive/episodic.py:1755` `recall_by_anchor_scored` — confirmed.
- `src/probos/cognitive/episodic.py:2509` `recall_weighted` — confirmed.
- `src/probos/types.py:358` `class AnchorFrame` — confirmed.
- **Protocol-widening conditional present** ("Do not widen `EpisodicMemoryProtocol` if doing so requires updating > 5 mock sites — accept `Any`"). This satisfies the dispatch's special-focus rule for memvid.
- `enabled: bool = False` default — convention #14 honored.
- Hard-constraint list correctly defers VersionRelation and per-engine-version follow-ups.

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
- ✅ Build Ordering Note added; `recall_by_anchor` signature verified at HEAD (`episodic.py:2747`).
- ✅ No phantom-API regressions introduced.
- ✅ All previously-verified symbols still match HEAD.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
