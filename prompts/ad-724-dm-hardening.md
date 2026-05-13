# AD-724 Family — DM Path Hardening (724-1 + 724-2 + 724-5)

**ADs covered:** AD-724-1, AD-724-2, AD-724-5 (all children of the AD-724 DM sanity gate umbrella).
**GH issues closed:** [#627](https://github.com/seangalliher/ProbOS/issues/627), [#628](https://github.com/seangalliher/ProbOS/issues/628), [#629](https://github.com/seangalliher/ProbOS/issues/629).
**Parent AD:** AD-724 (DM one-shot sanity gate; shipped Wave 150).
**Wave:** 154. **Estimated tests:** +12 to +18. **Estimated wall-time:** ~3h.

---

## Solution Overview

Three small additive changes to the existing `DmSanityGate` in `src/probos/cognitive/dm_sanity_gate.py` and its DM caller in `src/probos/routers/agents.py`:

1. **AD-724-1 (#627) — Controlled retry on rejection.** Today the gate only logs warnings (Tier-2). Add a one-shot retry semantic: when a configurable subset of warnings fires (default `length_floor` + `orphaned_tag`), the gate returns `should_retry=True` and the DM caller re-invokes the agent's `direct_message` handler **once** with an extra hint. Strict-mode forward marker remains AD-724-3.

2. **AD-724-2 (#628) — Repetition similarity beyond exact-prefix.** Today `check_repetition` only matches the first `repetition_prefix_chars` exactly (BF-prone for trivial whitespace/punctuation churn). Replace exact-prefix with a **stdlib `difflib.SequenceMatcher` ratio** over a normalized form (lowercased, whitespace-collapsed, stripped of structured-tag noise). Threshold configurable (default 0.85). `rapidfuzz` is **not** in the venv — `pip show rapidfuzz` returned 1; staying on stdlib preserves the License hygiene rule.

3. **AD-724-5 (#629) — Lift the gate into WR/chain reply paths.** Today `proactive.py:_extract_and_execute_actions` (line 2517) hand-rolls its own BF-120 markdown strip via inline `re.sub` and never runs the orphaned-tag / length-floor / repetition checks. Introduce a tiny shared helper `apply_dm_sanity(runtime, agent_id, text) -> DmSanityResult` (callable from any caller that has a `runtime`), call it from `proactive._extract_and_execute_actions` BEFORE the inline regex strips, and remove the duplicate inline strip. WR `[REPLY]` body cleaning gets the same gate via `_extract_and_execute_replies`.

All three are Tier-2 log-and-degrade. No behavior is removed; the gate **never** blocks a reply at v1 (retry returns the original on a second rejection).

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/cognitive/dm_sanity_gate.py` | 49–60 (`DmSanityGateConfig`) + full file | **Extend `DmSanityGateConfig` with the same three new fields** (`retry_on_rejection`, `retry_warnings`, `repetition_similarity_threshold`); add `should_retry`, `_normalize_for_repetition`, `_similarity_ratio`, `apply_dm_sanity` module helper. |
| `src/probos/config.py` | 3236–3246 (`DmSanityGateConfig`) | Mirror the same three new fields on the SystemConfig-side duplicate. **Both copies must stay structurally identical** (cluster invariant from AD-724 archive prompt: "Do not split DmSanityGate, DmSanityGateConfig, and DmSanityResult across multiple files"). |
| `src/probos/routers/agents.py` | 1106–1110 (DM gate call site) | Honor `should_retry` — single re-dispatch of `direct_message` with hint. |
| `src/probos/proactive.py` | 2487–2525 (`_extract_and_execute_actions`) and 3311–3450 (`_extract_and_execute_replies`) | Replace inline `re.sub` with `apply_dm_sanity()` helper. Import `apply_dm_sanity` at module top (not function-local). |
| `tests/test_ad724_dm_hardening.py` | NEW | 12–18 boundary tests across the three sub-ADs. |

---

## Section 1 — AD-724-2: Fuzzy repetition (stdlib only)

In `src/probos/cognitive/dm_sanity_gate.py`, replace the body of `check_repetition` and add two private helpers above it.

```python
# Add near the other compiled regexes at the top of the file:
_WHITESPACE_RE = re.compile(r"\s+")
_TAG_NOISE_RE = re.compile(r"\[(?:CHALLENGE|MOVE|REPLY|/REPLY|DM|/DM|NOTEBOOK|/NOTEBOOK)[^\]]*\]")


def _normalize_for_repetition(text: str) -> str:
    """AD-724-2: lowercase, strip structured-tag noise, collapse whitespace."""
    if not text:
        return ""
    out = _TAG_NOISE_RE.sub(" ", text)
    out = _WHITESPACE_RE.sub(" ", out).strip().lower()
    return out


def _similarity_ratio(a: str, b: str) -> float:
    """AD-724-2: stdlib SequenceMatcher ratio. License hygiene: no rapidfuzz."""
    if not a or not b:
        return 0.0
    import difflib
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()
```

Then change `check_repetition`:

```python
def check_repetition(self, agent_id: str, text: str) -> tuple[str, str] | None:
    """AD-724-2: similarity-based repetition (was exact-prefix only).

    Compares the normalized form of `text` against the normalized form of
    the previous reply for this agent. Fires when ratio >= threshold.
    The exact-prefix check is preserved as the FAST PATH (ratio==1.0).
    """
    prev = self._last_reply_by_agent.get(agent_id, "")
    if not prev or not text:
        return None
    n = self.config.repetition_prefix_chars
    if text[:n] == prev[:n]:
        detail = (
            f"first {n} chars match previous reply (possible decoder loop)"
        )
        logger.warning(
            "AD-724: DM repetition detected for agent %s (exact-prefix): %s",
            agent_id, detail,
        )
        return ("repetition", detail)
    norm_a = _normalize_for_repetition(text)
    norm_b = _normalize_for_repetition(prev)
    if not norm_a or not norm_b:
        return None
    ratio = _similarity_ratio(norm_a, norm_b)
    if ratio >= self.config.repetition_similarity_threshold:
        detail = (
            f"normalized similarity={ratio:.2f} >= "
            f"threshold={self.config.repetition_similarity_threshold:.2f}"
        )
        logger.warning(
            "AD-724-2: DM repetition detected for agent %s (similarity): %s",
            agent_id, detail,
        )
        return ("repetition", detail)
    return None
```

---

## Section 2 — AD-724-1: Controlled retry semantic

Add a `should_retry: bool` field to `DmSanityResult`:

```python
@dataclass
class DmSanityResult:
    cleaned_text: str
    warnings: list[tuple[str, str]] = field(default_factory=list)
    # AD-724-1: True when a configurable subset of warnings fired AND the
    # caller has not yet retried this turn. Caller decides whether to
    # honor it; the gate itself never blocks.
    should_retry: bool = False
```

Update the tail of `process()`:

```python
# AD-724-1: surface should_retry when configured warnings fired.
fired = {name for (name, _) in warnings}
should_retry = bool(
    self.config.retry_on_rejection
    and fired & set(self.config.retry_warnings)
)

return DmSanityResult(
    cleaned_text=cleaned, warnings=warnings, should_retry=should_retry,
)
```

**Extend BOTH copies of `DmSanityGateConfig` with the same three new fields.** The class is duplicated by design (cluster invariant from the AD-724 archive prompt) and the two copies MUST stay structurally identical, otherwise existing tests at `tests/test_ad724_dm_sanity_gate.py:22,127` (which construct `DmSanityGate(DmSanityGateConfig())` against the `cognitive/dm_sanity_gate.py` copy) will `AttributeError` on the new field reads inside `check_repetition` / `process()`.

In `src/probos/cognitive/dm_sanity_gate.py` (around line 49), extend the class:

```python
class DmSanityGateConfig(BaseModel):
    """AD-724: configuration for the DM sanity gate.

    Default-ON because the three migrated behaviors (BF-120, BF-119, AD-572)
    are already running unconditionally in HEAD. Disabling this config
    DISABLES those migrations too — see warning in `process()`.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100

    # AD-724-2: similarity-based repetition. 0.85 == "almost identical
    # after normalization" — set high to avoid false positives on agents
    # with characteristic phrasing.
    repetition_similarity_threshold: float = 0.85

    # AD-724-1: controlled one-shot retry on rejection.
    retry_on_rejection: bool = True
    retry_warnings: list[str] = Field(
        default_factory=lambda: ["length_floor", "orphaned_tag"]
    )
```

(Add `from pydantic import Field` to the existing `from pydantic import BaseModel` line at `dm_sanity_gate.py:22` — `Field` is NOT yet imported there.)

In `src/probos/config.py` (around line 3236), apply the SAME three-field extension to the duplicate so SystemConfig.dm_sanity_gate parses YAML keys identically. `Field` is already imported in `config.py`.

```python
class DmSanityGateConfig(BaseModel):  # AD-724
    """Configuration for the DM one-shot sanity gate.

    Default-ON: this config gates three previously-unconditional regex
    cleanups (BF-120, BF-119, AD-572) plus three new log-only checks.
    Disabling it preserves only the BF-120 markdown strip.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100

    # AD-724-2: similarity-based repetition.
    repetition_similarity_threshold: float = 0.85

    # AD-724-1: controlled one-shot retry on rejection.
    retry_on_rejection: bool = True
    retry_warnings: list[str] = Field(
        default_factory=lambda: ["length_floor", "orphaned_tag"]
    )
```

In `src/probos/routers/agents.py`, around line 1108 where `sanity_result = sanity_gate.process(...)` is called inside `agent_chat`, honor `should_retry` with a single re-dispatch:

```python
if response_text and sanity_gate is not None:
    sanity_result = sanity_gate.process(agent_id, response_text)
    response_text = sanity_result.cleaned_text
    if sanity_result.should_retry:
        # AD-724-1: one controlled retry. The hint is appended to the
        # original Captain text so the agent sees what the gate flagged
        # without leaking gate internals into Captain-visible output.
        retry_hint = (
            "\n\n[SYSTEM_HINT: previous reply was rejected by the DM "
            "sanity gate (warnings: "
            + ", ".join(name for name, _ in sanity_result.warnings)
            + "). Please respond again, carefully.]"
        )
        retry_intent = IntentMessage(
            intent="direct_message",
            params={**_params, "text": message_text + retry_hint, "is_retry": True},
            target_agent_id=agent_id,
            ttl_seconds=60.0,
        )
        try:
            retry_resp = await runtime.intent_bus.send(retry_intent)
            retry_text = (retry_resp.payload or {}).get("text") if retry_resp else None
            if retry_text:
                # Run the gate again, but honor its result without a SECOND retry.
                retry_result = sanity_gate.process(agent_id, retry_text)
                response_text = retry_result.cleaned_text
                logger.info(
                    "AD-724-1: DM retry for agent %s — original_warnings=%s "
                    "retry_warnings=%s",
                    agent_id,
                    [n for n, _ in sanity_result.warnings],
                    [n for n, _ in retry_result.warnings],
                )
        except Exception:
            logger.warning(
                "AD-724-1: DM retry dispatch failed for agent %s; "
                "shipping original reply",
                agent_id, exc_info=True,
            )
```

Anchor the SEARCH/REPLACE on the existing block at `routers/agents.py:1106-1108`. Verify against HEAD before applying — the surrounding lines are the `sanity_gate = getattr(...)` / `if response_text and sanity_gate is not None:` / `sanity_result = sanity_gate.process(...)` triple shown in the verification footer below.

---

## Section 3 — AD-724-5: Lift gate into WR/chain reply paths

Add a module-level helper at the bottom of `src/probos/cognitive/dm_sanity_gate.py`. Use a `TYPE_CHECKING`-guarded `RuntimeOS` import so the public API is fully typed (Engineering Principles #1 — type annotations on public methods):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.runtime import RuntimeOS


def apply_dm_sanity(
    runtime: "RuntimeOS", agent_id: str, text: str
) -> DmSanityResult:
    """AD-724-5: one-line helper for non-DM callers (WR replies, chain).

    Fetches the DM sanity gate from the runtime via the public
    ``dm_sanity_gate`` attribute (wired in ``runtime.py:566``). When the
    gate is unavailable, returns a no-op DmSanityResult that preserves
    the input — Tier-2 log-and-degrade.
    """
    gate = getattr(runtime, "dm_sanity_gate", None)
    if gate is None:
        return DmSanityResult(cleaned_text=text)
    return gate.process(agent_id, text)
```

First, **add the helper import to the top of `src/probos/proactive.py`** alongside other `probos.cognitive` imports (function-local imports in hot paths violate the project's standing import-order rule):

```python
from probos.cognitive.dm_sanity_gate import apply_dm_sanity
```

Then replace the inline BF-120 strip in `_extract_and_execute_actions` (lines 2517–2520):

SEARCH:

```python
        # BF-120: Strip markdown formatting that wraps structured tags.
        # LLMs sometimes emit **[COMMAND ...]** or `[COMMAND ...]` which
        # prevents the regex patterns below from matching.
        text = re.sub(r'[`*]{1,3}\[', '[', text)
        text = re.sub(r'\][`*]{1,3}', ']', text)
```

REPLACE:

```python
        # AD-724-5: lift BF-120 markdown strip + log-only quality checks
        # (length floor, repetition, orphaned tags) into the shared DM
        # sanity gate. The gate itself never blocks; warnings log only.
        _sanity = apply_dm_sanity(rt, agent.id, text)
        text = _sanity.cleaned_text
```

In `_extract_and_execute_replies` (around line 3403 just before `reply_body = _strip_bracket_markers(reply_body)`), apply the gate to `reply_body`:

```python
                # AD-724-5: run reply body through the shared sanity gate
                # so WR replies get the same orphaned-tag / repetition /
                # length-floor visibility as DM one-shots.
                _reply_sanity = apply_dm_sanity(rt, agent.id, reply_body)
                reply_body = _reply_sanity.cleaned_text
```

(Anchor the SEARCH on the existing line `reply_body = _strip_bracket_markers(reply_body)  # BF-174` at proactive.py:3403.)

---

## What This Does NOT Change

- The gate still **never blocks** a reply — `should_retry=True` is advisory; the caller dispatches once and ships whatever comes back.
- No new event types. The gate continues to log via the existing `logger.warning` path.
- No NATS/transport changes.
- No agent-side instructions change. Agents do not see the gate.
- Strict-mode (Tier-3 propagate) remains forward marker AD-724-3 — not in scope.
- WR/chain `apply_dm_sanity` is **read-then-clean**; it does not introduce new control flow (no early-returns, no retries on the WR path — only DM has the retry semantic).

---

## Test Plan (`tests/test_ad724_dm_hardening.py`)

Boundary tests per the engineering principle: happy path + error/edge + empty/None.

### AD-724-2 — fuzzy repetition

1. `test_724_2_normalize_collapses_whitespace_and_strips_tags` — happy path
2. `test_724_2_similarity_ratio_above_threshold_fires` — happy path
3. `test_724_2_similarity_ratio_below_threshold_silent` — edge
4. `test_724_2_empty_previous_reply_no_repetition_warning` — empty/None
5. `test_724_2_exact_prefix_match_still_wins_fast_path` — backward compat

### AD-724-1 — controlled retry

6. `test_724_1_should_retry_true_when_length_floor_fires` — happy path
7. `test_724_1_should_retry_false_when_only_repetition_fires` — config-driven subset
8. `test_724_1_should_retry_false_when_disabled_in_config` — feature gate
9. `test_724_1_router_dispatches_at_most_one_retry` — DM router integration; mock `intent_bus.send` and assert call count == 2 (initial + 1 retry)

### AD-724-5 — shared helper

10. `test_724_5_apply_dm_sanity_returns_noop_when_gate_missing` — log-and-degrade
11. `test_724_5_apply_dm_sanity_strips_markdown_via_helper` — happy path
12. `test_724_5_proactive_extract_uses_shared_gate` — integration: build a fake runtime with a real `DmSanityGate`, hand it markdown-wrapped text containing `[ENDORSE post-1 UP]`, assert the endorsement extraction succeeds.

(Optional 6 more if scope allows: orphaned-tag retry path, retry that itself fires warnings, retry dispatch failure log-and-degrade, similarity threshold = 1.0 disables similarity check, chain reply path apply_dm_sanity, config Pydantic validation of `retry_warnings`.)

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad724_dm_hardening.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracker Updates

- **PROGRESS.md**: bump test count line; add bullet to Wave 154.
- **DECISIONS.md**: append `### AD-724-1`, `### AD-724-2`, `### AD-724-5` entries (one paragraph each).
- **docs/development/roadmap.md**: mark #627/#628/#629 closed.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "class DmSanityGateConfig" src/probos
  src/probos/cognitive/dm_sanity_gate.py:49: class DmSanityGateConfig(BaseModel):
  src/probos/config.py:3236:               class DmSanityGateConfig(BaseModel):  # AD-724
  (TWO copies — both must be extended; tests construct from the dm_sanity_gate.py copy)
grep -n "DmSanityGateConfig(" tests/test_ad724_dm_sanity_gate.py
  22:     return DmSanityGate(DmSanityGateConfig())
  127:    gate = DmSanityGate(DmSanityGateConfig(enabled=False))
grep -n "dm_sanity_gate: DmSanityGate" src/probos/runtime.py
  568:        self.dm_sanity_gate: DmSanityGate = DmSanityGate(
grep -n "sanity_gate = getattr" src/probos/routers/agents.py
  1106:    sanity_gate = getattr(runtime, "dm_sanity_gate", None)
grep -n "BF-120: Strip markdown" src/probos/proactive.py
  2517:        # BF-120: Strip markdown formatting that wraps structured tags.
grep -n "_strip_bracket_markers(reply_body)" src/probos/proactive.py
  3403:                reply_body = _strip_bracket_markers(reply_body)  # BF-174
grep -n "def check_repetition" src/probos/cognitive/dm_sanity_gate.py
  175:    def check_repetition(self, agent_id: str, text: str) -> tuple[str, str] | None:
grep -n "from pydantic import" src/probos/cognitive/dm_sanity_gate.py
  22: from pydantic import BaseModel
  (Field NOT yet imported — must be added alongside BaseModel)
pip show rapidfuzz  → not installed (use stdlib difflib.SequenceMatcher)
```

---

## Revision (2026-05-12)

Applied pass-1 review findings:

**Required (1 addressed):**

1. **Duplicate `DmSanityGateConfig` class.** Both copies (`src/probos/cognitive/dm_sanity_gate.py:49` and `src/probos/config.py:3236`) are now extended with the same three new fields. Chose option (a) per the reviewer's preferred path — preserves the cluster invariant from the AD-724 archive prompt ("Do not split DmSanityGate, DmSanityGateConfig, and DmSanityResult across multiple files") and avoids a layer-inversion `cognitive` → `config` import. Files-to-Modify table updated; Section 2 now spells out both extensions and notes that `Field` must be added to the `dm_sanity_gate.py` pydantic import (it is already imported in `config.py`).

**Recommended folded:**

- **#1 (typing for `apply_dm_sanity`)** — added `TYPE_CHECKING`-guarded `RuntimeOS` import and annotated the runtime param.
- **#5 (move helper import to module top of `proactive.py`)** — done; function-local imports removed from both call sites.

**Recommended deferred (scope/test-surface):**

- **#2 (cache poisoning across retry boundary)** — valid concern but adds new control flow + a 13th test. Forward-marker as a follow-up (file as BF or AD-724-1a) once the basic retry semantic is in production and we observe whether the false-positive actually fires.
- **#3 (retry-warning loop test)** — covered by the existing optional test "retry that itself fires warnings"; not promoted to required.
- **#4 (`is_retry: True` dead data)** — left in place. Useful for future log tagging / agent-side rate-limit suppression; removing it is reversible later. No cost to ship.

**Nits not addressed:** all three Nits are documentation-style; no source/spec change needed.

