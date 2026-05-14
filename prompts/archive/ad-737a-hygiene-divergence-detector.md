# AD-737a — Hygiene follow-ups for `divergence_detector.py`

**AD:** AD-737a. **Parent AD:** AD-737 (Wave 156, per-agent custom emotion taxonomy).
**GH issues closed:** [#648](https://github.com/seangalliher/ProbOS/issues/648).
**Wave:** 158. **Estimated tests:** +3 pytest (no Vitest). **Estimated wall-time:** ~1–1.5h.

> ### AD-numbering note — slot reuse
> Wave 156's closure block (`DECISIONS.md:2391`) reserved the name `AD-737a` for a *future* "TS-side parity for custom emotions" forward marker. **That forward marker is being superseded by this AD.** The TS-side parity gap is no longer needed — Wave 156 shipped server-side computation of custom-emotion modulation, and the TS layer never needs to see the custom name (manifest v1 INTENT_RULES is the only client-side path).
>
> The old forward-marker prose stays in DECISIONS.md as historical context (do NOT delete the Wave-156 closure block). This AD's tracker section adds a one-line clarification next to it: "Superseded by AD-737a hygiene (Wave 158) — see closure block below."

---

## Solution Overview

Three small hygiene items in `src/probos/avatars/divergence_detector.py`, all surfaced during Wave 156's GATE 2 review:

1. **Hoist `import dataclasses` to module-top.** Currently the import sits inside `apply_divergence_check` (around line 448 as `import dataclasses as _dc`). Trivial move; conforms to the repo's import-order convention.
2. **Collapse the two-pass `parse_intent_self_tag` re-parse.** `apply_divergence_check` currently parses the response twice — first v1-only (line 392), then re-parses with `custom_emotions` if v1 returned None (line 410). **Architect's caller audit** (`grep parse_intent_self_tag\(` in `src/`): the re-parse exists *only* in `apply_divergence_check` itself. The 76-caller estimate in the GH issue is wrong — there are exactly **two production call sites in the same function**. Collapse to a single call by reordering: fetch `custom_emotions` first, then parse once. Test callers (12 sites in `tests/test_ad722a_divergence_detector.py` + 3 in `tests/test_ad737_emotion_taxonomy.py`) deliberately test the v1-only signature and stay untouched.
3. **Document the test-fake contract for `getattr`/`hasattr` on `runtime.profile_store`.** **Architect picks (b)** — document, not promote-to-Protocol. Rationale: there is **no `ProbOSRuntime` Protocol class** in the codebase (`grep "class ProbOSRuntime"` returns only the concrete class at `runtime.py:200`). Adding a Protocol is significant scope. The defensive `getattr(runtime, "profile_store", None)` + `hasattr(store, "get")` pattern is already a load-bearing test contract; documenting it preserves the existing test-fake shape without scope creep.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/avatars/divergence_detector.py` | top (~16–22) | Add `import dataclasses` to module-top. |
| `src/probos/avatars/divergence_detector.py` | ~390–415 (in `apply_divergence_check`) | Reorder: fetch `custom_emotions` first, then single `parse_intent_self_tag` call. |
| `src/probos/avatars/divergence_detector.py` | ~440–450 (in same function) | Remove the inline `import dataclasses as _dc`; use module-top `dataclasses`. |
| `src/probos/avatars/divergence_detector.py` | docstring of `apply_divergence_check` (~362) | Add 6-line test-fake contract documentation. |
| `tests/test_ad737a_hygiene.py` | NEW | 3 boundary tests covering the collapsed single-pass parse. |

No new Python deps, no UI changes, no config changes.

---

## Section 1 — Hoist `import dataclasses`

In `src/probos/avatars/divergence_detector.py`, the current top-of-file imports are:

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Final
```

Add `import dataclasses` between `re` and `from dataclasses import dataclass` (preserve stdlib-first ordering):

```python
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Final
```

Then in `apply_divergence_check` (around line 448), find:

```python
    if resolved_v1 != intent:
        import dataclasses as _dc
        result = _dc.replace(result, intent_emotion=intent)
```

Replace with:

```python
    if resolved_v1 != intent:
        result = dataclasses.replace(result, intent_emotion=intent)
```

---

## Section 2 — Collapse the two-pass `parse_intent_self_tag`

In `apply_divergence_check` (around line 391–412), find the current double-parse:

```python
    intent = parse_intent_self_tag(response_text)
    # AD-737: look up the agent's custom emotion palette (tier-2
    # log-and-degrade). Then re-parse with the palette so custom names
    # like ``professional_concern`` resolve through ``inherits``.
    custom_emotions: dict[str, Any] | None = None
    store = getattr(runtime, "profile_store", None)
    if store is not None:
        try:
            crew = store.get(agent_id) if hasattr(store, "get") else None
            custom_emotions = (
                getattr(crew, "custom_emotions", None) if crew else None
            )
        except Exception:
            logger.debug(
                "AD-737: profile_store custom_emotions lookup failed for %s",
                agent_id, exc_info=True,
            )
    if intent is None and custom_emotions:
        intent = parse_intent_self_tag(
            response_text, custom_emotions=custom_emotions,
        )
```

Replace with the single-pass variant (fetch palette first, then parse once):

```python
    # AD-737a: single-pass parse — fetch the agent's custom emotion
    # palette FIRST (tier-2 log-and-degrade), then parse with the
    # palette so v1 names AND custom names both resolve in one call.
    # ``custom_emotions`` defaults to ``None`` which makes
    # ``parse_intent_self_tag`` behave identically to the legacy v1-only
    # signature, preserving backward compat with test callers that
    # don't pass the kwarg.
    custom_emotions: dict[str, Any] | None = None
    store = getattr(runtime, "profile_store", None)
    if store is not None:
        try:
            crew = store.get(agent_id) if hasattr(store, "get") else None
            custom_emotions = (
                getattr(crew, "custom_emotions", None) if crew else None
            )
        except Exception:
            logger.debug(
                "AD-737: profile_store custom_emotions lookup failed for %s",
                agent_id, exc_info=True,
            )
    intent = parse_intent_self_tag(
        response_text, custom_emotions=custom_emotions,
    )
```

**Behavior equivalence proof (paste into the AD's commit message):**

- `parse_intent_self_tag(text)` is `parse_intent_self_tag(text, custom_emotions=None)` — the kwarg defaults to None (`divergence_detector.py:206`).
- When `custom_emotions is None`, `_resolve_intent_name` (line 94–107) short-circuits identically to the v1-only path: it returns the name only if it's in `INTENT_EXPECTED_RULES`, else `None`.
- When `custom_emotions` is a populated dict, the single call matches what the old re-parse would have returned (the re-parse never had a third path).
- Conclusion: the collapsed call returns the same value in both code paths.

---

## Section 3 — Document the test-fake contract on `apply_divergence_check`

In `src/probos/avatars/divergence_detector.py` around line 362, the current docstring opens with:

```python
def apply_divergence_check(
    runtime: "ProbOSRuntime | Any",
    agent_id: str,
    agent: Any,
    response_text: str,
    t_cfg: Any,
) -> str:
    """Parse, strip, score, and wire divergence for a finalized reply.

    Single-call-site helper invoked from
    ``routers/agents.py:agent_chat`` immediately before
    ``mark_reply_emitted``. Tier-2 internally: caller wraps in try/except
    for defense in depth.
```

Append (between the existing first paragraph and the existing second paragraph "Always strips..."):

```python
    Test-fake contract for ``runtime``-shaped objects (AD-737a):
      - ``runtime.profile_store`` (optional): exposes ``get(agent_id) -> CrewProfile | None``.
        Accessed via ``getattr(..., None)``; missing attribute = no custom emotions.
        Test fakes MAY omit this attribute entirely (defaults to "no palette").
      - ``runtime.divergence_results`` (optional): mutable ``dict[str, DivergenceResult]``.
        Accessed via ``getattr(..., None)``; missing attribute = result not stored.
        Test fakes MAY omit; production runtime allocates in startup.
      - ``runtime.divergence_history`` (optional): mutable ``dict[str, deque]``.
        Same shape as ``divergence_results``; test fakes MAY omit.
      No ``ProbOSRuntime`` Protocol exists today (only the concrete class at
      ``runtime.py:200``). Promotion to a Protocol is deferred until a second
      detector needs the same shape (forward marker: AD-737a-1).
```

(Word-for-word; the precheck reads docstring lines.)

---

## What This Does NOT Change

- `parse_intent_self_tag` signature, semantics, regex. Tests in `tests/test_ad722a_divergence_detector.py` (v1-only callers) and `tests/test_ad737_emotion_taxonomy.py` (custom-emotion callers) keep their assertions.
- `_resolve_intent_name`, `compute_divergence`, `strip_intent_self_tag`. No other helper changes.
- `EmotionalIntent` enum, `INTENT_EXPECTED_RULES`, `INTENT_DIRECTION`. v1 set frozen.
- The trust + Hebbian wiring at the end of `apply_divergence_check`. Unchanged.
- The 60+ tests in `test_ad722a_*.py` / `test_ad737_*.py` — none are modified.
- No new Pydantic config; no new runtime attributes; no new Protocol classes.
- AD-731 attachment invariant (the function never touches audio).

---

## Test Plan

`tests/test_ad737a_hygiene.py` — 3 boundary tests on the single-pass parse path.

1. **`test_apply_divergence_check_single_pass_v1_intent`** (happy path). Build a `FakeRuntime` with `profile_store=None`; pass `response_text="hi.\n<intent emotion=warm>"`; assert returned stripped text contains no `<intent`, and `runtime.divergence_results[agent_id].intent_emotion == "warm"`.
2. **`test_apply_divergence_check_single_pass_custom_intent_resolves_via_palette`** (edge: custom emotion → v1 parent). Build a `FakeRuntime` whose `profile_store.get(agent_id)` returns a stub with `custom_emotions={"professional_concern": EmotionProfile(inherits="concerned", ...)}`. Pass `response_text="...<intent emotion=professional_concern>"`. Assert `intent_emotion == "professional_concern"` on the result (custom name preserved, resolved-v1 used internally for scoring).
3. **`test_apply_divergence_check_single_pass_unknown_intent_returns_stripped_only`** (error path). `profile_store=None`; pass `response_text="...<intent emotion=feisty>"`. Assert returned text is stripped of tag, AND `runtime.divergence_results[agent_id]` is not set (or is None — match whatever the function currently does for unknown intent).

Each test asserts the production code calls `parse_intent_self_tag` **at most once** by patching it with a counter:

```python
import probos.avatars.divergence_detector as dd

call_count = {"n": 0}
real_parse = dd.parse_intent_self_tag

def counting_parse(text, *, custom_emotions=None):
    call_count["n"] += 1
    return real_parse(text, custom_emotions=custom_emotions)

monkeypatch.setattr(dd, "parse_intent_self_tag", counting_parse)
# ... invoke apply_divergence_check ...
assert call_count["n"] == 1  # AD-737a single-pass guarantee
```

---

## Verification Commands

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad737a_hygiene.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722a_divergence_detector.py tests/test_ad737_emotion_taxonomy.py -q -n 0   # regression
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile   # full gate
```

No UI gate (no `ui/src/**` files touched).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## License Disposition

All-internal hygiene refactor. **No new pip deps, no new npm deps.** No external code absorbed. Apache 2.0 compliant.

---

## Tracker Updates

- **PROGRESS.md**: bump pytest count by 3; bullet under Wave 158: "AD-737a — divergence_detector hygiene (dataclasses hoist + single-pass parse + test-fake contract docs)."
- **DECISIONS.md**: append `### AD-737a — Divergence-detector hygiene (Wave 158)` closure block. Reference the supersession of the Wave-156 forward marker (one sentence: "Supersedes the Wave-156 forward-marker reservation of AD-737a for TS-side custom-emotion parity; the TS-side gap is no longer relevant since custom modulation is computed server-side and the TS layer only sees v1 manifest names.").
- **docs/development/roadmap.md**: no change (AD-737a was never in the roadmap table).
- **GH #648**: close on push, comment with the commit SHA.

---

## Forward Markers

- **AD-737a-1** — Promote `runtime.profile_store` / `divergence_results` / `divergence_history` to a `ProbOSRuntimeProtocol` once a second consumer (other than `apply_divergence_check`) needs the same shape. Not needed today.

---

## Verified Against Codebase (2026-05-13)

```
grep -n "import dataclasses" src/probos/avatars/divergence_detector.py
  448:        import dataclasses as _dc
grep -n "def parse_intent_self_tag" src/probos/avatars/divergence_detector.py
  204: def parse_intent_self_tag(
grep -n "parse_intent_self_tag(" src/probos/avatars/divergence_detector.py
  204: def parse_intent_self_tag(
  392:    intent = parse_intent_self_tag(response_text)
  410:        intent = parse_intent_self_tag(
grep -rn "parse_intent_self_tag(" src/probos/ tests/ | wc -l
  15   # 2 production sites (both in apply_divergence_check) + 12 v1-only test sites + 3 AD-737 tests + 1 def line
grep -n "class ProbOSRuntime" src/probos/runtime.py
  200: class ProbOSRuntime:
grep -rn "class ProbOSRuntime.*Protocol\|class ProbOSRuntimeProtocol" src/probos/
  (no matches — no Protocol class exists)
grep -n "getattr(runtime, \"profile_store\"" src/probos/avatars/divergence_detector.py
  345:    store = getattr(runtime, "profile_store", None)
  397:    store = getattr(runtime, "profile_store", None)
grep -n "self.profile_store" src/probos/runtime.py
  410:        self.profile_store = ProfileStore(
```
