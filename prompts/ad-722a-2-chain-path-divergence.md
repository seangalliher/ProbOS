# AD-722a-2 — Chain-path divergence detection at compose-step emit

**Wave:** 162
**Closes:** #611
**Status:** ready to build
**Dependencies:** AD-722a (Wave 143 — DM-path divergence shipped); AD-723 (Wave 144 — sensorium dispatch unification shipped); AD-727 (safety constraints — joint review gate satisfied since AD-722a's REASONING-vs-OUTPUT signal class).
**Estimated tests:** +10 pytest.
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0.

---

## Problem

AD-722a (Wave 143) fires `DivergenceDetector` only on the DM **one-shot** path, where `mark_reply_emitted` provides a single, canonical emit point. The chain path (multi-LLM deliberative work — decompose → execute → evaluate, with WR posts + sometimes DM forwards) was deferred as forward marker [#611](https://github.com/seangalliher/ProbOS/issues/611):

> *(f) DM-only in v1; chain reply-emission has no equivalent single emit point (multi-destination, multi-phase compose) — chain-path divergence is forward marker AD-722a-2.*

Per the DECISIONS entry at `DECISIONS.md:1717` (AD-722a record). AD-723 (Wave 144) shipped sensorium dispatch unification with `SensoriumPath` enum values `{CHAIN_BASELINE, CHAIN_EXTENSIONS, CHAIN_SITUATION, DM_ONESHOT, WR_ONESHOT}` (see `src/probos/cognitive/cognitive_agent.py:71-93`). Sensorium dispatch is INPUT/context-assembly only — it does NOT provide a chain-OUTPUT emit hook. The chain compose-output site exists in code (`_execute_sub_task_chain` consumer at `cognitive_agent.py:2934` where `compose_text = chain_result.get("llm_output", "")`) but is not wrapped by a single canonical "reply emitted" method like `mark_reply_emitted` is for DM. This AD therefore (1) ADDS the canonical chain-output emit hook `mark_chain_output_emitted` as a sibling of `mark_reply_emitted`, then (2) wires divergence detection on top.

---

## Solution overview

1. **ADD** the canonical chain-output emit hook on `CognitiveAgent`: `mark_chain_output_emitted(output_text: str, *, audience: str, intent_self_tag: str | None = None, applied_modulation_rules: list[str] | None = None) -> None`. Sibling of `mark_reply_emitted` (`cognitive_agent.py:3064`). Called from the chain-compose consumer at `cognitive_agent.py:2934` immediately after `compose_text = chain_result.get("llm_output", "")`.
2. Wire `DivergenceDetector.detect()` INSIDE `mark_chain_output_emitted` so each chain output gets scored against its self-tagged intent (same as DM v1).
3. **Path-coherence design** — chain outputs that target WR audiences carry AD-727 audience-inappropriate-for-personal-presentation constraints (addendum h). The divergence detector reads OUTPUT signals (REASONING-vs-OUTPUT), which is AD-727 rule #1 authorized regardless of audience, so the detector itself is safe. But the **INTEROCEPTION note** that surfaces back to the agent must respect the audience: notes derived from WR-audience output must not be rendered in DM contexts and vice versa (cross-channel surface pollution).
4. Channel-scoped divergence notes: per-channel ring buffer of recent divergence events; the next-cycle prompt picks from the buffer matching the current channel only.

### What this does NOT change

- AD-722a DM-path behavior (DM-only divergence stays unchanged; this AD ADDS the chain path).
- The 8-emotion taxonomy (AD-722a-7 / per-agent taxonomy AD-737 already shipped).
- The OUTPUT-as-subject phrasing rule (AD-727 #8 — divergence notes phrased as "Your last reply..." not "You sounded...").
- Trust / Hebbian wiring (already in place from AD-722a; this AD just feeds MORE events into the same wiring).
- Channel routing or compose semantics — purely additive observation hook.

---

## Section 0 — New EventType (this AD introduces these; do NOT flag as missing)

In `src/probos/events.py` add:

```python
DIVERGENCE_OBSERVED_CHAIN = "divergence_observed_chain"  # AD-722a-2: chain-path divergence
```

(Sibling of the existing AD-722a DM-path event, whose name should be confirmed by grep first — if `DIVERGENCE_OBSERVED` exists unsuffixed, rename to `DIVERGENCE_OBSERVED_DM` in this AD with backward-compat alias, OR add the chain event only and leave the DM event unsuffixed. Decide at Section 0 implementation; Builder picks the lower-touch option.)

---

## Section 1 — Add `mark_chain_output_emitted` and call it from the chain compose consumer

In `src/probos/cognitive/cognitive_agent.py`, define a new public method as a sibling of `mark_reply_emitted` (currently at line 3064):

```python
def mark_chain_output_emitted(
    self,
    output_text: str,
    *,
    audience: str,
    intent_self_tag: str | None = None,
    applied_modulation_rules: list[str] | None = None,
) -> None:
    """AD-722a-2: canonical chain-output emit hook.

    Sibling of :meth:`mark_reply_emitted`. Called when a chain phase
    produces output that will be rendered (WR post, DM forward,
    sensorium block). Drives chain-path divergence detection and any
    future chain-emit side effects.

    ``audience`` is one of {"wr", "dm_forward", "sensorium"} and scopes
    the per-channel divergence buffer (see Section 2).
    """
    if self._runtime is None:
        return
    try:
        from probos.avatars.divergence_detector import (
            DivergenceContext,
            DivergenceDetector,
        )
        ctx = DivergenceContext(
            agent_id=self.agent_id,
            intent=intent_self_tag,
            applied_rules=applied_modulation_rules or [],
            channel="chain",
            audience=audience,
        )
        detector = getattr(self._runtime, "divergence_detector", None)
        if detector is None:
            return
        result = detector.detect(ctx)
        if result.divergence_detected:
            self._record_chain_divergence(result, audience=audience)
    except Exception:
        logger.debug("AD-722a-2: chain-path divergence hook failed", exc_info=True)
```

Then add the call site at `cognitive_agent.py:2934` (the chain compose consumer). The current code is:

```python
chain_result = await self._execute_sub_task_chain(full_chain, observation)

# Phase 2b: Detect undeclared actions in compose output
if chain_result and intended_actions:
    compose_text = chain_result.get("llm_output", "")
```

Add immediately after the `compose_text =` assignment:

```python
# AD-722a-2: canonical chain-output emit hook for divergence detection.
self.mark_chain_output_emitted(
    compose_text,
    audience=self._classify_chain_audience(chain_result),  # see below
    intent_self_tag=chain_result.get("intent_self_tag"),
    applied_modulation_rules=chain_result.get("applied_modulation_rules"),
)
```

Builder: `_classify_chain_audience` is a new small helper (returns one of `"wr" / "dm_forward" / "sensorium"`) — read `chain_result` keys to determine. The exact `intent_self_tag` / `applied_modulation_rules` keys may not be present in `chain_result` today; if missing, pass `None` and let DivergenceDetector skip (it already handles None intent per AD-722a-7). Do NOT invent new chain-result fields in this AD — surface as forward marker AD-722a-2a if richer self-tag data needs threading through `_execute_sub_task_chain`.

---

## Section 2 — `_record_chain_divergence` helper

New private method on `CognitiveAgent`:

```python
def _record_chain_divergence(
    self,
    result: DivergenceResult,
    *,
    audience: str,
) -> None:
    """AD-722a-2: persist chain-path divergence for next-cycle interoception note.

    Stores into a per-channel ring buffer. Cycles in the same channel pick up
    the note; cross-channel surfacing is prohibited (AD-727 addendum h).
    """
    buf = self._chain_divergence_buffer.setdefault(audience, deque(maxlen=8))
    buf.append(result)
    # Trust/Hebbian update inherits AD-722a wiring — same call, different path tag.
    self._update_trust_for_divergence(result, path_tag="chain")
```

`_update_trust_for_divergence` is an existing AD-722a method — verify the name via grep and reuse. If it's currently DM-coupled, parameterize the path tag.

Add `from collections import deque` to imports and `self._chain_divergence_buffer: dict[str, deque[DivergenceResult]] = {}` to `__init__` (or its async-init equivalent).

---

## Section 3 — Channel-scoped interoception rendering

In `_build_divergence_note_suffix` (AD-722a-7 existing function — grep to confirm exact name):

```python
def _build_divergence_note_suffix(self, channel: str) -> str:
    """AD-722a-2: scope the divergence note to the requesting channel.

    DM channels render only DM-path divergence events.
    Chain channels render only chain-path divergence events for the SAME
    audience tier (WR notes don't surface in DM-forward composition).
    """
    if channel == "dm":
        return self._render_dm_divergence_suffix()
    buf = self._chain_divergence_buffer.get(channel, deque())
    if not buf:
        return ""
    return self._render_chain_divergence_suffix(buf)
```

Builder: read the AD-722a-7 implementation of the existing suffix builder to find the exact rendering helpers it currently uses. This section parameterizes the existing path; do NOT introduce a parallel implementation.

---

## Section 4 — Audience inheritance (AD-727 addendum h)

AD-727 hard rule: WR audiences are not audiences for personal-presentation observations. The chain-path divergence signal IS OUTPUT-vs-INTENT (REASONING-vs-OUTPUT), which AD-727 rule #1 explicitly authorizes regardless of audience. **No additional audience constraint applies to the detector itself.**

But the **OUTPUT-as-subject phrasing rule (AD-727 #8)** must hold for chain rendering too. Add a regression test (Section 5) that ensures chain-path divergence notes follow the same `\byou (?:sound|sounded|...)\b` regex prohibition.

---

## Section 5 — Tests

`tests/test_ad722a_2_chain_divergence.py` — 10 tests, all using real `SystemConfig()` per AD-722b-1a:

1. `test_chain_emit_with_matching_intent_no_divergence`.
2. `test_chain_emit_with_diverging_intent_records`.
3. `test_chain_buffer_scoped_to_channel` — WR audience and DM-forward audience populate distinct ring buffers.
4. `test_dm_path_unchanged_when_chain_hook_active` — regression for AD-722a v1 DM path.
5. `test_interoception_note_renders_only_same_channel_divergences`.
6. `test_phrasing_rule_holds_chain_path` — AD-727 #8 regex applied to chain-rendered notes; no `\byou \b` agent-as-subject constructions.
7. `test_trust_update_records_chain_path_tag` — Hebbian event from chain emit carries `path_tag="chain"`.
8. `test_chain_divergence_buffer_capacity_8` — 9th event evicts oldest (deque(maxlen=8)).
9. `test_runtime_missing_detector_logs_and_continues` — when `runtime.divergence_detector` is unset, the hook is best-effort.
10. `test_wr_audience_observation_does_not_surface_in_dm_followup` — cross-channel surface pollution prevented.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-722a-2 row to SHIPPED Wave 162.
- `DECISIONS.md` — append entry pointing to the AD-722a DECISIONS record (`DECISIONS.md:1717`) and noting this AD removes the (f) deferral note.

---

## Acceptance criteria

- Chain-path divergence hook lands via NEW `mark_chain_output_emitted` method called from the chain compose consumer at `cognitive_agent.py:2934`.
- Per-channel ring buffer (maxlen=8) holds chain divergence events.
- Interoception note rendering channel-scoped; WR notes don't leak into DM and vice versa.
- AD-727 #8 phrasing rule holds for chain-rendered notes.
- AD-722a DM path unchanged — regression test green.
- Trust/Hebbian wiring carries `path_tag="chain"` for the new events.
- New `EventType.DIVERGENCE_OBSERVED_CHAIN` registered.
- 10 new pytest tests green at `-n 0` and under parallel gate.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/avatars/divergence_detector.py:1` — module docstring confirms "AD-722a: intent-vs-presentation divergence detector."
- `src/probos/avatars/divergence_detector.py:140` — `class DivergenceResult:` confirmed.
- `DECISIONS.md:1717` — AD-722a record confirms (f) deferral and names AD-722a-2 as the closer.
- `DECISIONS.md:1731-1740` — AD-723 sensorium dispatch unification shipped Wave 144 (73cbd95). `SensoriumPath` enum values confirmed: `CHAIN_BASELINE`, `CHAIN_EXTENSIONS`, `CHAIN_SITUATION`, `DM_ONESHOT`, `WR_ONESHOT` (`cognitive_agent.py:71-93`). NOTE: an earlier draft of this AD referenced a phantom AD-723 "chain compose step" dispatch hook that was never shipped — this revision drops that assumption and adds the canonical chain-output emit hook (`mark_chain_output_emitted`) as part of THIS AD's scope.
- `src/probos/cognitive/cognitive_agent.py:3064` — `def mark_reply_emitted(self) -> None:` confirmed (DM-path sibling).
- `src/probos/cognitive/cognitive_agent.py:2934` — `compose_text = chain_result.get("llm_output", "")` confirmed (chain-output call site).
- AD-727 rule #1 (REASONING-vs-OUTPUT signals authorized) and rule #8 (OUTPUT-as-subject phrasing) confirmed in DECISIONS.md AD-727 record.
- `src/probos/events.py` exists at the expected location (sibling file to other AD-722* events).
