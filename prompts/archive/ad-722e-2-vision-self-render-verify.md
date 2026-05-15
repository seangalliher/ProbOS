# AD-722e-2 — Vision-LLM verification of self-render (digital-vs-render coherence)

**Wave:** 162
**Closes:** #644
**Status:** ready to build
**Dependencies:** AD-722e (Wave — #571 deterministic self-perception); AD-727 (safety constraints + joint review gate); AD-732 + ten-guard stack (vision tier); AD-731 (AttachmentStore refs); AD-728 (vision-LLM mirror — companion AD; this AD ships its digital-side counterpart).
**Estimated tests:** +9 pytest.
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0. AD-727 hard rules apply.

---

## Problem

[Issue #644](https://github.com/seangalliher/ProbOS/issues/644) — AD-722e v1 (#571) shipped deterministic structured self-projection with **zero vision-LLM calls**. The agent's self-image is computed from its digital state (avatar DSL) without any pixel-level inspection. This is safe (AD-727 rule #1) but misses one class of failure: **renderer drift** — when the backend renderer output doesn't match the digital state (e.g., a color blends wrong, a feature is occluded by a layer-order bug).

Companion AD-728 (DECISIONS.md:1804-1823) covers the vision-LLM mirror function for digital-analog coherence. This AD (AD-722e-2) is the **AD-722e side** of that work: it adds a verification path inside `self_perception.py` that optionally runs a vision-LLM against the backend render and surfaces divergence as a `self_perception` observation block.

The issue body asks: *"Companion: AD-728 (#586) overlaps in scope; resolve which AD owns the vision-LLM render-coherence check at design time."*

**Resolution:** AD-728 owns the GENERIC vision-LLM mirror primitive (the rate-limited, AD-727-compliant call). AD-722e-2 owns the SELF-PERCEPTION integration that consumes the primitive and folds the result into the agent's structured self-projection. Both ADs are needed; AD-728 is the engine, AD-722e-2 is the wiring. **If AD-728 has not shipped, ship its primitive as part of this AD's Section 1**, and the eventual AD-728 build becomes a no-op consolidation. (Coordinate with the AD-722a-1 author — both ADs in this wave introduce the same vision-LLM mirror primitive; pick ONE to ship it, mark the other as consumer.)

---

## Solution overview

1. New `SelfRenderVerifier` (sibling of AD-722e's `SelfPerceptionProjection`) consumes the existing backend render + the digital state + an LLM client and produces a `RenderCoherenceObservation` dataclass.
2. AD-727 enforcement: backend-server-side render only (rule #5); browser capture FORBIDDEN. Verifier rejects refs lacking backend provenance.
3. Phrasing rule (AD-728 #8): observations describe the RENDERER, not the agent. `"Render output for Ezri differs from her digital state in the lip-color channel"` ✓ — `"Ezri looks wrong"` ✗.
4. Read-only on trust/Hebbian (AD-727 rule #1): observations surface to the agent and to logs; they do NOT modify trust or Hebbian weights. The detector category (digital-vs-render) is OUTPUT-vs-OUTPUT, not REASONING-vs-OUTPUT, so AD-727 rule #1 does NOT authorize trust wiring here.
5. Cost gate: same 3-per-hour-per-agent ceiling as AD-728 / AD-722a-1.
6. Output: observation wraps in a `self_perception` block on the agent's next-cycle prompt; UI surface for SelfImageTab is forward marker AD-722e-2a.

### What this does NOT change

- AD-722e v1 deterministic projection (still runs every cycle; this AD ADDS an optional vision-LLM pass).
- The `PIPELINE_VERSION` constant (the verifier is a sidecar, not part of the deterministic pipeline — version stays 1.0.0).
- AD-727 rule set.
- AD-721i backend renderer (CONSUMER not producer).
- Trust / Hebbian wiring (READ-ONLY).
- AD-731 attachment-ref invariant.

---

## Section 0 — New EventType + config

`src/probos/events.py`:
```python
SELF_RENDER_COHERENCE_OBSERVED = "self_render_coherence_observed"  # AD-722e-2
```

`src/probos/config.py` — extend `AvatarsConfig`:
```python
# AD-722e-2: vision-LLM self-render verification.
self_render_verify_enabled: bool = False  # default-OFF transitional flag
self_render_verify_max_per_hour_per_agent: int = 3  # AD-728 ceiling
```

---

## Section 1 — `SelfRenderVerifier` class

NEW FILE: `src/probos/cognitive/self_render_verify.py`

```python
"""AD-722e-2: vision-LLM verification of self-render (digital-vs-render coherence).

Consumes a backend-server-side render of the agent's avatar and asks a vision LLM
whether the render matches the digital state. Outputs surface as a self_perception
observation block.

AD-727 hard rules enforced:
  rule #1 — READ-ONLY on trust + Hebbian (digital-vs-render is NOT REASONING-vs-OUTPUT).
  rule #5 — backend-server-side render only; browser capture rejected at the gate.
  rule #8 — phrasing: "Render output for <agent> differs from her digital state..."
            NOT "<agent> looks wrong."
  joint review — AD-722e inheritance (AD-722e is the parent under joint Counselor +
    Architect review; this AD's vision-LLM extension inherits the gate).
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_AGENT_AS_SUBJECT_RE = re.compile(
    r"\b(?:she|he|they|the (?:agent|counselor|captain|officer))\s+"
    r"(?:looks|appears|seems|is|looked|appeared|seemed|was)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RenderCoherenceObservation:
    coherent: bool
    observation: str  # render-as-subject phrasing, ≤200 chars
    confidence: float
    screenshot_ref: str
    skipped_reason: str | None = None  # rate_limit / provenance_invalid / tier_unavailable / phrasing_violation


class SelfRenderVerifier:
    _rate_state: dict[str, deque[float]] = {}

    def __init__(self, llm_client, max_per_hour: int = 3):
        self._llm = llm_client
        self._max_per_hour = max_per_hour

    async def verify(
        self,
        agent_id: str,
        digital_state_summary: str,  # short text projection of avatar DSL
        backend_render_ref: str,
        provenance_backend: bool,
    ) -> RenderCoherenceObservation:
        if not provenance_backend:
            return RenderCoherenceObservation(
                coherent=True, observation="",
                confidence=0.0, screenshot_ref=backend_render_ref,
                skipped_reason="provenance_invalid",
            )
        if not self._under_rate_limit(agent_id):
            return RenderCoherenceObservation(
                coherent=True, observation="",
                confidence=0.0, screenshot_ref=backend_render_ref,
                skipped_reason="rate_limit",
            )

        prompt = (
            f"Compare this rendered avatar against its digital description.\n\n"
            f"Digital description: {digital_state_summary}\n\n"
            "Respond with JSON: "
            "{coherent: bool, confidence: number 0-1, "
            "observation: \"<≤200 char description, phrased about the RENDER "
            "OUTPUT — e.g. 'Render output differs from digital state in the lip-color channel'. "
            "Do NOT use agent-as-subject phrasing like 'she looks...' or "
            "'the agent appears...'>\"}."
        )
        try:
            resp = await self._llm.call_with_attachments(
                tier="vision",
                prompt=prompt,
                attachment_refs=[backend_render_ref],
            )
        except Exception:
            logger.warning(
                "AD-722e-2: vision tier call failed agent_id=%s", agent_id,
                exc_info=True,
            )
            return RenderCoherenceObservation(
                coherent=True, observation="",
                confidence=0.0, screenshot_ref=backend_render_ref,
                skipped_reason="tier_unavailable",
            )
        self._note_call(agent_id)
        return self._parse(resp, backend_render_ref)

    def _parse(self, resp, ref) -> RenderCoherenceObservation:
        # Builder: implement JSON parse.
        # AD-727 #8 phrasing check on the observation field.
        parsed = ...  # JSON parse with honest-degrade
        if _AGENT_AS_SUBJECT_RE.search(parsed["observation"] or ""):
            return RenderCoherenceObservation(
                coherent=True, observation="",
                confidence=0.0, screenshot_ref=ref,
                skipped_reason="phrasing_violation",
            )
        return RenderCoherenceObservation(
            coherent=bool(parsed["coherent"]),
            observation=parsed["observation"] or "",
            confidence=float(parsed.get("confidence", 0.0)),
            screenshot_ref=ref,
        )

    def _under_rate_limit(self, agent_id: str) -> bool:
        now = time.time()
        window = self._rate_state.setdefault(agent_id, deque())
        cutoff = now - 3600
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < self._max_per_hour

    def _note_call(self, agent_id: str) -> None:
        self._rate_state.setdefault(agent_id, deque()).append(time.time())
```

---

## Section 2 — Wire from `self_perception.py`

Extend the existing `SelfPerceptionProjection` builder to optionally include a `render_coherence` block from the verifier:

```python
# AD-722e-2: optional vision-LLM render-coherence observation.
render_coherence_block: dict | None = None
if runtime.config.avatars.self_render_verify_enabled:
    render_ref = self._get_latest_backend_render_ref()
    if render_ref is not None:
        obs = await runtime.self_render_verifier.verify(
            agent_id=agent_id,
            digital_state_summary=self._summarize_digital_state(),
            backend_render_ref=render_ref,
            provenance_backend=True,
        )
        if obs.skipped_reason is None:
            render_coherence_block = {
                "coherent": obs.coherent,
                "observation": obs.observation,
                "confidence": obs.confidence,
                "screenshot_ref": obs.screenshot_ref,
            }
            if not obs.coherent:
                runtime.emit_event(
                    EventType.SELF_RENDER_COHERENCE_OBSERVED,
                    {"agent_id": agent_id, **render_coherence_block},
                )
```

Builder: read `src/probos/cognitive/self_perception.py:42-113` to find the canonical projection builder. The `_summarize_digital_state` helper may already exist under a different name — reuse.

---

## Section 3 — Runtime wiring

`runtime.py`:
```python
from probos.cognitive.self_render_verify import SelfRenderVerifier

self.self_render_verifier = SelfRenderVerifier(
    llm_client=self.llm_client,
    max_per_hour=self.config.avatars.self_render_verify_max_per_hour_per_agent,
)
```

If AD-722a-1's `VisionIntentDivergenceDetector` is also being built in this wave (it is — see prompts/ad-722a-1-vision-llm-intent-divergence.md), Builder coordinates: BOTH detectors share the `_rate_state` shape but should have INDEPENDENT class-level dicts (separate concerns) OR share a `VisionLLMBudget` singleton — Builder picks ONE pattern across both ADs. Recommended: independent class dicts in v1 (simpler), consolidate into a shared budget primitive in AD-728 build.

---

## Tests

`tests/test_ad722e_2_self_render_verify.py` — 9 tests:

1. `test_coherent_render_no_event_emitted`.
2. `test_incoherent_render_emits_event_with_render_subject_phrasing`.
3. `test_agent_as_subject_phrasing_skipped_with_reason` — LLM emits "Ezri looks pale" → `skipped_reason="phrasing_violation"`.
4. `test_rate_limit_3_per_hour_per_agent`.
5. `test_provenance_invalid_skips_without_llm_call` — non-backend ref short-circuits.
6. `test_tier_unavailable_skips_gracefully`.
7. `test_default_off_flag_disables_wire_up` — `self_render_verify_enabled=False` → no LLM call.
8. `test_read_only_on_trust` — coherence observation does NOT mutate trust scores (regression for AD-727 rule #1).
9. `test_attachment_ref_only_no_inline_bytes` — AD-731 invariant.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-722e-2 row to SHIPPED Wave 162 (or partial if AD-721i renderer ref helper not ready — same gating note as AD-722a-1). File forward marker AD-722e-2a (HXI SelfImageTab surface for render-coherence observations).
- `DECISIONS.md` — append AD-722e-2 entry; cross-reference AD-728 (vision-LLM mirror primitive — coordinated build).

---

## Acceptance criteria

- `SelfRenderVerifier` lands at `src/probos/cognitive/self_render_verify.py`.
- AD-727 rule #1 (read-only on trust/Hebbian), rule #5 (backend-server-side only), rule #8 (render-as-subject phrasing), joint-review inheritance — all enforced.
- AD-731 invariant preserved.
- Cost gate aligned with AD-728's 3-per-hour ceiling.
- Default-OFF transitional flag.
- New `EventType.SELF_RENDER_COHERENCE_OBSERVED` registered.
- 9 new pytest tests green at `-n 0` and parallel.
- No trust/Hebbian mutations from this code path (test 8 is the regression).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/cognitive/self_perception.py:42` — `PIPELINE_VERSION: str = "1.0.0"` confirmed.
- `src/probos/cognitive/self_perception.py:46` — `class SelfPerceptionProjection:` confirmed.
- `src/probos/cognitive/self_perception.py:58, 113` — pipeline_version field + projection-builder use confirmed.
- `DECISIONS.md:1780` — AD-727 record confirmed (joint review gate, rules 1/5/8).
- `DECISIONS.md:1804-1823` — AD-728 record confirmed (vision-LLM mirror; phrasing rule #8 explicit).
- `docs/architecture/self-perception-framing.md` — referenced in issue body; Builder should read for context (not yet verified to exist by this Architect pass — if missing, surface).
- `tests/test_ad727_safety_constraints.py` — referenced in issue body for the safety regression pattern; this AD's test_8 follows the same shape.
