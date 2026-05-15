# AD-722a-1 — Vision-LLM intent-divergence (semantic match against rendered avatar)

**Wave:** 162
**Closes:** #610
**Status:** ready to build
**Dependencies:** AD-722a (Wave 143 — rule-table intent-divergence); AD-732 + BF-268..273 (vision tier + ten-guard stack); AD-731 (AttachmentStore refs); AD-727 (safety constraints — joint review gate). **Overlaps:** #644 (AD-722e-2 vision-LLM self-render verification) — distinct: this AD checks INTENT vs RENDER; AD-722e-2 checks DIGITAL vs RENDER. **Companion:** AD-728 (vision-LLM mirror) — this AD is the intent-side mirror; AD-728 is the digital-state-side mirror.
**Estimated tests:** +9 pytest (+2 vitest if any UI surface).
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0. Uses local vision tier (qwen3.6:27b per Wave 153 default).

---

## Problem

AD-722a v1 detects intent-vs-presentation divergence by comparing the LLM's self-tagged emotion against fired modulation rules — structured, deterministic, sub-LLM. This catches "you said warm but the modulation pipeline produced blocked_rate_pitch."

It does NOT catch: "the LLM said warm AND the modulation rules fired warm, but the rendered facial expression on the avatar does not actually convey warmth to a human observer." That's a vision-LLM semantic match against the rendered output — the present AD.

Forward marker [#610](https://github.com/seangalliher/ProbOS/issues/610). Per the issue body:

> *Distinct from AD-728 (#586) which checks digital-vs-analog render coherence, not intent-vs-render coherence. Deferred — vision-LLM cost gating must align with AD-728's 3-per-hour ceiling.*

---

## Solution overview

1. New `VisionIntentDivergenceDetector` (sibling of `DivergenceDetector`) that takes (a) the agent's self-tagged intent, (b) the rendered avatar image (AttachmentStore SHA-256 ref), (c) a vision-tier LLM client and asks: "Does this facial expression convey `<intent>` (yes/no, confidence 0-1, observation note)?"
2. Cost-gate: shared global rate limit aligned with AD-728's 3-per-hour-per-agent ceiling. Implementation reuses the same rate-limit store AD-728 uses (or introduces it if AD-728 hasn't shipped yet — see "AD-728 ordering" below).
3. AD-727 inheritance: joint review already satisfied for the AD-722a family. The vision-LLM extension is REASONING-vs-RENDER (still rule #1 authorized) but ADDS pixel ingestion — must satisfy AD-727 rule #5 (backend-server-side render only; browser-side capture prohibited).
4. Honest-degrade: when vision tier unconfigured / unhealthy / over-budget, the detector returns "no observation" and the agent's interoception note carries no vision-derived line. AD-722a v1 rule-table divergence continues unchanged in parallel.
5. **AD-731 invariant:** the rendered image goes onto the bus as an AttachmentStore SHA-256 ref, not inline base64. Vision-LLM call resolves via existing `_resolve_attachment_refs_for_openai` (BF-268 shape).

### AD-728 ordering note

AD-728 (vision-LLM mirror for digital-analog coherence) has NOT shipped as of Wave 162 (per DECISIONS.md it's recorded but build status pending). This AD provides the rate-limit infrastructure; AD-728 inherits it on its build. If AD-728 ships first, this AD's Section 3 (rate limit) becomes a no-op reuse — Builder reads which path applies at start of work.

### What this does NOT change

- AD-722a v1 rule-table detector (still runs; this AD adds a sibling).
- The renderer (this AD CONSUMES rendered output; does not produce it).
- The avatar DSL (AD-721d).
- AD-731 attachment-ref invariant — rendered image is content-addressed.
- Trust / Hebbian wiring shape (this AD records observations into the existing AD-722a wiring with a new path tag).

---

## Section 0 — New EventType + config

In `src/probos/events.py`:
```python
VISION_INTENT_DIVERGENCE_OBSERVED = "vision_intent_divergence_observed"  # AD-722a-1
```

In `src/probos/config.py` `AvatarsConfig` (or new `DivergenceConfig` sub-section if cleaner — Builder decides):
```python
# AD-722a-1: vision-LLM intent-divergence gating.
vision_intent_divergence_enabled: bool = False  # default-OFF transitional flag
vision_intent_divergence_max_per_hour_per_agent: int = 3  # AD-728 ceiling alignment
```

Default-OFF per Wave 10 convention #14.

---

## Section 1 — `VisionIntentDivergenceDetector` class

NEW FILE: `src/probos/avatars/vision_intent_divergence.py`

```python
"""AD-722a-1: vision-LLM intent-vs-render divergence detector.

Inputs:
  - agent self-tagged intent (string from the 8-emotion taxonomy + per-agent extensions)
  - rendered avatar image (AttachmentStore SHA-256 ref to backend-rendered PNG)
  - vision tier LLM client

Output: VisionIntentDivergenceResult dataclass.

AD-727 compliance:
  rule #1 (REASONING-vs-OUTPUT): OUTPUT here is the rendered image; signal is
    intent self-tag vs rendered pixels. Authorized.
  rule #5 (backend-server-side render only): the image MUST be a backend render.
    The detector REJECTS attachment refs that are not provenance-tagged backend.
  rule #8 (OUTPUT-as-subject phrasing): rendered observations describe the
    RENDER, not the agent.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisionIntentDivergenceResult:
    divergence_detected: bool
    intent: str
    rendered_attachment_ref: str
    confidence: float  # 0.0 - 1.0
    observation: str   # OUTPUT-as-subject phrasing, ≤200 chars
    skipped_reason: str | None = None  # "rate_limit" | "tier_unavailable" | "provenance_invalid" | None


class VisionIntentDivergenceDetector:
    _rate_limit_per_agent: dict[str, deque[float]] = {}  # class-level shared

    def __init__(self, llm_client, max_per_hour: int = 3):
        self._llm = llm_client
        self._max_per_hour = max_per_hour

    async def detect(
        self,
        agent_id: str,
        intent: str,
        rendered_attachment_ref: str,
        provenance_backend: bool,
    ) -> VisionIntentDivergenceResult:
        if not provenance_backend:
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="provenance_invalid",
            )
        if not self._under_rate_limit(agent_id):
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="rate_limit",
            )
        prompt = (
            f"Look at this rendered avatar. The intended emotion is '{intent}'. "
            "Respond with JSON: "
            "{conveys_intent: bool, confidence: number (0-1), "
            "observation: \"<≤200 char description of the rendered expression, "
            "phrased about the RENDER not the agent>\"}."
        )
        try:
            resp = await self._llm.call_with_attachments(
                tier="vision",
                prompt=prompt,
                attachment_refs=[rendered_attachment_ref],
            )
        except Exception:
            logger.warning(
                "AD-722a-1: vision tier call failed for agent_id=%s",
                agent_id, exc_info=True,
            )
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="tier_unavailable",
            )
        self._note_call(agent_id)
        return self._parse(resp, intent, rendered_attachment_ref)

    def _under_rate_limit(self, agent_id: str) -> bool:
        now = time.time()
        window = self._rate_limit_per_agent.setdefault(agent_id, deque())
        cutoff = now - 3600
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < self._max_per_hour

    def _note_call(self, agent_id: str) -> None:
        self._rate_limit_per_agent.setdefault(agent_id, deque()).append(time.time())

    def _parse(self, resp, intent, ref):
        # Builder: implement JSON parse + AD-727 #8 phrasing-regex enforcement.
        # If the LLM phrasing violates the regex, REWRITE to OUTPUT-as-subject
        # OR return divergence_detected=False with skipped_reason="phrasing_violation".
        ...
```

Builder: the `_llm.call_with_attachments` method signature must match what `OpenAICompatibleClient` exposes today. Read `src/probos/cognitive/llm_client.py:769-880` to find the existing vision call surface. If the existing API is `await self._llm.complete_with_messages(...)`, restructure to that — do NOT invent a new client method.

---

## Section 2 — Wire from `DivergenceDetector` callsite

Where AD-722a v1 fires today (DM path's `mark_reply_emitted`), add an OPTIONAL vision-LLM follow-up:

```python
# AD-722a-1: vision-LLM intent-divergence (cost-gated, default-OFF).
if (
    self._runtime is not None
    and self._runtime.config.avatars.vision_intent_divergence_enabled
):
    rendered_ref = self._get_latest_render_ref()  # AD-721i backend renderer ref
    if rendered_ref is not None:
        result = await self._runtime.vision_intent_divergence_detector.detect(
            agent_id=self.agent_id,
            intent=intent_self_tag,
            rendered_attachment_ref=rendered_ref,
            provenance_backend=True,  # by construction; AD-727 rule #5 audit
        )
        if result.divergence_detected and result.skipped_reason is None:
            self._emit_event(
                EventType.VISION_INTENT_DIVERGENCE_OBSERVED,
                {"agent_id": self.agent_id, "intent": result.intent,
                 "confidence": result.confidence, "observation": result.observation},
            )
```

Builder: the `_get_latest_render_ref` helper depends on AD-721i (backend renderer pipeline). If AD-721i hasn't shipped a stable ref-lookup surface, this section's gate stays `vision_intent_divergence_enabled=False` until AD-721i lands. The detector itself ships in this AD; the live wire-up stays default-OFF.

---

## Section 3 — Runtime wiring

In `src/probos/runtime.py`, construct the detector once at startup:

```python
from probos.avatars.vision_intent_divergence import VisionIntentDivergenceDetector

self.vision_intent_divergence_detector = VisionIntentDivergenceDetector(
    llm_client=self.llm_client,
    max_per_hour=self.config.avatars.vision_intent_divergence_max_per_hour_per_agent,
)
```

---

## Tests

`tests/test_ad722a_1_vision_intent_divergence.py` — 9 tests, real `SystemConfig()`:

1. `test_detect_match_returns_no_divergence` — fake LLM returns `{conveys_intent: true, confidence: 0.9}`.
2. `test_detect_mismatch_returns_divergence` — fake LLM returns `{conveys_intent: false, confidence: 0.7}`.
3. `test_rate_limit_enforces_3_per_hour_per_agent` — 4th call within an hour returns `skipped_reason="rate_limit"`.
4. `test_rate_limit_expires_after_3600s` — monkeypatch `time.time()` to advance past the window.
5. `test_provenance_invalid_skips_without_calling_llm` — non-backend ref short-circuits.
6. `test_tier_unavailable_returns_skipped` — fake LLM raises; detector returns `skipped_reason="tier_unavailable"`.
7. `test_phrasing_rule_regex_enforced` — LLM emits "Ezri looks sad" (agent-as-subject); detector rewrites OR rejects per AD-727 #8.
8. `test_default_off_flag_disables_wire_up` — when `vision_intent_divergence_enabled=False`, the AD-722a callsite never calls the detector (regression for cost discipline).
9. `test_attachment_ref_not_inline_bytes` — AD-731 invariant: the detector receives a SHA-256 ref, never a `bytes` payload.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-722a-1 row to SHIPPED Wave 162 (or partial-SHIPPED if AD-721i render-ref helper not yet available). File forward marker AD-722a-1a (HXI surface for vision-divergence events in SelfImageTab).
- `DECISIONS.md` — append entry noting cost-gating shared with AD-728.

---

## Acceptance criteria

- `VisionIntentDivergenceDetector` lands at `src/probos/avatars/vision_intent_divergence.py`.
- Rate limit shared class-level dict (matches HttpFetchAgent pattern, AD-270).
- AD-727 rule #5 enforced (backend-provenance check rejects non-backend refs).
- AD-727 rule #8 phrasing-regex enforced on LLM output.
- AD-731 invariant preserved (no inline base64; attachment refs only).
- Cost-gate aligns with AD-728's 3-per-hour ceiling.
- Default-OFF transitional flag.
- New `EventType.VISION_INTENT_DIVERGENCE_OBSERVED` registered.
- 9 new pytest tests green at `-n 0` and parallel.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/avatars/divergence_detector.py:1-9` — AD-722a v1 detector docstring confirms REASONING-vs-OUTPUT scope; this AD extends to REASONING-vs-RENDER which AD-727 rule #1 authorizes by inheritance.
- `src/probos/cognitive/llm_client.py:769` — `_resolve_attachment_refs_for_openai` confirmed (BF-268 shape).
- `src/probos/cognitive/llm_client.py:876` — `messages = await self._resolve_attachment_refs_for_openai(messages)` confirmed (this AD's calls inherit the same path).
- `src/probos/cognitive/vision_dispatch.py:227` — vision dispatch confirms ref-resolution comment.
- `src/probos/config.py:1266` — `vision_tier: str = "vision"` confirmed (AttachmentsConfig); this AD's flag lives under AvatarsConfig (sibling).
- `DECISIONS.md:1804-1823` — AD-728 record confirms 3-per-hour cost ceiling and backend-render-only constraint.
- `DECISIONS.md:1717` — AD-722a v1 record confirms vision-LLM extension is forward-marked as AD-722a-1.
