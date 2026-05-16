# AD-722a-6 — Cross-agent divergence observations (consumer of AD-722a-1 + AD-729)

**Status:** Draft for Wave 163
**Dependencies:** AD-728 ✅ (Wave 163), AD-729 ✅ (Wave 163, governance contract must ship first), AD-722a-1 ✅ (Wave 162, intent-vs-render divergence detector).
**Closes:** #615
**Estimated tests:** 10 pytest
**Build order:** THIRD — AFTER AD-728 and AD-729.

## Scope discipline — what Wave 163 ships under AD-722a-6

The issue body says hard precondition is "AD-729 family must ship and be operationally stable." Wave 163 ships AD-729's governance contract but NOT the conduct content (AD-729a is deferred). Therefore AD-722a-6 ships in Wave 163 as a **default-OFF capability** that consumes the AD-729 surface — it goes live only when AD-729's capability gate goes live.

This is the scaffolding tier: surface the API, exercise the gates, leave the flip default-OFF behind both `cfg.avatars.peer_perception_enabled` AND a new dedicated flag `cfg.avatars.cross_agent_divergence_observation_enabled`.

## Problem

AD-722a-1 ships per-agent self-observation: Ezri observes her OWN intent-vs-presentation divergence. AD-722a-6 lets one agent (Maya) observe another agent's (Ezri's) intent-vs-presentation divergence pattern — with consent. This is the cross-agent analog of AD-722a, naturally pair-built with AD-729 peer perception.

## Solution overview

Adds `observe_peer_divergence(observer_id, observed_id) -> PeerObservation | None` to `src/probos/avatars/peer_perception.py`. It builds on AD-722a-1's divergence detector and routes through AD-729's `observe_peer()` so the same governance gates apply.

## Section 0: Event Types

Add to `src/probos/events.py:EventType`:

```python
CROSS_AGENT_DIVERGENCE_OBSERVED = "cross_agent_divergence_observed"  # AD-722a-6: peer perception of intent-vs-presentation
```

Inserted directly after the AD-729 PEER_OBSERVATION_* values.

## Section 1: Config

Extend `AvatarsConfig`:

```python
cross_agent_divergence_observation_enabled: bool = Field(
    default=False,
    description="AD-722a-6 peer perception of intent-vs-presentation. Default OFF; requires peer_perception_enabled True AND AD-729a Standing Orders shipped.",
)
```

## Section 2: API

```python
def observe_peer_divergence(
    runtime: ProbOSRuntime,
    observer_id: str,
    observed_id: str,
    *,
    register: ObservationRegister = ObservationRegister.OPERATIONAL,
    permission_grant_id: str | None = None,
) -> PeerObservation | None:
    """Peer perception of intent-vs-presentation divergence.

    Reads AD-722a-1's divergence_history for `observed_id` via the
    existing VisionIntentDivergenceDetector surface, summarizes recent
    divergence patterns into observation content, then routes the
    observation through observe_peer() so AD-729's governance gates
    apply.

    Returns None on honest-degrade or any AD-729 gate decline.
    """
```

Hard gates (in order, BEFORE delegating to `observe_peer()`):

1. `cfg.avatars.cross_agent_divergence_observation_enabled` (default False) — honest-degrade if False.
2. `cfg.avatars.vision_intent_divergence_enabled` (AD-722a-1's flag) — must be True for `observed_id` to have a divergence history. Honest-degrade if False with `skipped_reason="upstream_detector_disabled"`.
3. observed agent has at least one entry in `divergence_history` within the last 24h — otherwise nothing to observe; honest-degrade with `skipped_reason="no_recent_divergence_data"`.

Then construct the observation content as a short, descriptive summary (template-rendered, NOT free-form LLM output — phrasing predictability matters at the AD-729 governance layer) and delegate to `observe_peer()`. The AD-729 gates handle:

- observer certification (AD-729b)
- observed opt-out
- permission grant for PERSONAL register
- backend render check
- federation gate
- per-pair-per-thread rate limit

When `observe_peer()` returns a `PeerObservation`, emit `CROSS_AGENT_DIVERGENCE_OBSERVED` with the observation's `observation_id` (or the underlying RecordsStore artifact ID — Builder verify the exact identifier shape from AD-729 Section 5).

## Section 3: Summary content template

Pure-template, NO LLM call, NO embedding lookup:

```python
def _format_divergence_summary(history: list[DivergenceResult]) -> str:
    """Render a stable, predictable summary of an observed agent's recent
    intent-vs-presentation divergence. Used as the `content` field of the
    resulting PeerObservation."""
    # Aggregates: count of divergences, dominant emotion category, mean magnitude.
    # OPERATIONAL phrasing only — no value judgments, no personal language.
```

The template emits sentences like:
- ✅ "Observed 3 intent-vs-presentation divergences over 24h, dominant in the 'concerned' category, mean magnitude 0.42."
- ❌ "She seems stressed today." (PERSONAL phrasing — not allowed in OPERATIONAL register)

## Section 4: Tests (≥10 boundary cases)

`tests/test_ad722a_6_cross_agent_divergence.py`:

1. happy path: enabled, observer certified, observed has divergence data, OPERATIONAL register → PeerObservation returned
2. `cross_agent_divergence_observation_enabled=False` → honest-degrade
3. `vision_intent_divergence_enabled=False` (upstream) → honest-degrade
4. observed has no recent divergence data → honest-degrade
5. AD-729 gate: observer uncertified → declined (delegated)
6. AD-729 gate: observed opt-out → declined (delegated)
7. AD-729 gate: PERSONAL register without permission_grant → declined (delegated)
8. summary template renders predictable OPERATIONAL phrasing (regex check: no value-judgment vocabulary)
9. `CROSS_AGENT_DIVERGENCE_OBSERVED` event emitted on happy path with correct payload
10. AD-731 invariant: payload carries no inline image bytes (textual divergence summary only)

Use **real `SystemConfig()` fixtures** and **real `AgentRegistry`** — BF-287 retrospective.

## Section 5: Builder Standing Rules

- BF-274: single `replace_string_in_file` for adjacent edits.
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production.
- BF-287: real registry fixture.
- AD-738b: no UI in this AD; no `npm run build` gate.
- AD-731 invariant: verified by Test 10.
- AD-722c-3: forward markers use TECHNICAL triggers.
- **NO LLM call in this AD** — summary is template-rendered. Adding LLM rendering would re-couple AD-722a-6 to vision tier infrastructure unnecessarily.

## What this does NOT change

- AD-722a-1 divergence detector internals.
- AD-729 governance gate semantics — AD-722a-6 ONLY delegates.
- `observe_peer()` signature.
- Trust / Hebbian / routing.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #615.
- `docs/development/roadmap.md`: move AD-722a-6 from forward markers to shipped (default-OFF).
- `DECISIONS.md`: append AD-722a-6 entry — consumer of AD-722a-1 via AD-729.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-722a-6-flip — default-ON for OPERATIONAL register.** Trigger: when AD-729a Standing Orders ship AND AD-729 capability is default-ON for crew. Issue filed.

## Acceptance Criteria

1. All Section 0-3 deliverables landed.
2. ≥10 pytest tests pass.
3. Full gate green.
4. No new pip deps; no new top-level config class (only an `AvatarsConfig` field).
5. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "VisionIntentDivergenceDetector\|divergence_history" src/probos/avatars/vision_intent_divergence.py
  (AD-722a-1 ships these per PROGRESS.md line 18)

grep -n "is_render_phrased\|VisionLLMRateLimit" src/probos/avatars/vision_intent_divergence.py
  (both exported per AD-722a-1)
```

**Builder verify-first flags:** confirm exact `DivergenceResult` dataclass shape and `divergence_history` access pattern from AD-722a-1 before drafting `_format_divergence_summary`. Confirm `observe_peer()` return shape and `observation_id` field name from the AD-729 implementation in this same wave.
