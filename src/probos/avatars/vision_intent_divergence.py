"""AD-722a-1: vision-LLM intent-vs-render divergence detector.

Inputs:
  - agent self-tagged intent (e.g. "warm", "calm", "alert")
  - rendered avatar image (AttachmentStore SHA-256 ref to a backend-rendered PNG)
  - vision tier LLM client

Output: VisionIntentDivergenceResult dataclass.

AD-727 compliance:
  rule #1 (REASONING-vs-OUTPUT): OUTPUT here is the rendered image; signal
    is intent self-tag vs rendered pixels. Authorized by inheritance from
    AD-722a v1.
  rule #5 (backend-server-side render only): the image MUST be a backend
    render; the detector rejects non-backend refs.
  rule #8 (OUTPUT-as-subject phrasing): rendered observations describe the
    RENDER, not the agent.

AD-731 invariant: this module never sees raw bytes; only sha256 refs flow.

Wave 162 coordination: the rate-limit helper + phrasing-regex enforcer
are exposed for reuse by AD-722e-2 (self-render verify, also vision-LLM).
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# -- Shared helpers exposed for AD-722e-2 reuse -------------------------


# AD-727 rule #8: observation phrasing must describe the RENDER, not the agent.
# This regex flags agent-as-subject patterns; the detector rewrites or rejects.
_AGENT_AS_SUBJECT_RE = re.compile(
    r"\b(she|he|they|the\s+(?:agent|counselor|officer|crew))\b\s+"
    r"(?:looks?|appears?|seems?|feels?|is|are)\b",
    re.IGNORECASE,
)


def is_render_phrased(observation: str) -> bool:
    """AD-727 rule #8: return True iff the observation does NOT use
    agent-as-subject phrasing. Empty observations are vacuously render-phrased.
    """
    if not observation:
        return True
    return _AGENT_AS_SUBJECT_RE.search(observation) is None


class VisionLLMRateLimit:
    """Per-agent hourly call cap (AD-728 ceiling alignment).

    Wave 162: shared by AD-722a-1 (intent divergence) and AD-722e-2
    (self-render verify). Class-level shared store keyed by ``(scope, agent_id)``
    so the two detectors compete for the same budget per agent (the cost
    ceiling is the agent's, not the detector's).
    """

    # (scope, agent_id) -> deque[timestamps]
    _windows: dict[tuple[str, str], deque[float]] = {}

    def __init__(self, *, scope: str, max_per_hour: int) -> None:
        self._scope = scope
        self._max = int(max_per_hour)

    def under_limit(self, agent_id: str) -> bool:
        now = time.time()
        key = (self._scope, agent_id)
        window = self._windows.setdefault(key, deque())
        cutoff = now - 3600.0
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) < self._max

    def note_call(self, agent_id: str) -> None:
        self._windows.setdefault((self._scope, agent_id), deque()).append(time.time())

    @classmethod
    def reset_all(cls) -> None:
        """Test helper: clear all rate-limit state."""
        cls._windows.clear()


# -- Detector ------------------------------------------------------------


@dataclass(frozen=True)
class VisionIntentDivergenceResult:
    divergence_detected: bool
    intent: str
    rendered_attachment_ref: str
    confidence: float
    observation: str
    # "rate_limit" | "tier_unavailable" | "provenance_invalid"
    # | "phrasing_violation" | "parse_error" | None
    skipped_reason: str | None = None


class VisionIntentDivergenceDetector:
    """Compares agent intent against rendered facial expression via vision LLM.

    Tier-2 throughout: every failure mode returns a result with
    ``skipped_reason`` set. NEVER raises.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        max_per_hour: int = 3,
        attachment_store: Any | None = None,
    ) -> None:
        self._llm = llm_client
        self._store = attachment_store
        self._rate = VisionLLMRateLimit(
            scope="vision_intent_divergence",
            max_per_hour=max_per_hour,
        )

    async def detect(
        self,
        *,
        agent_id: str,
        intent: str,
        rendered_attachment_ref: str,
        provenance_backend: bool,
    ) -> VisionIntentDivergenceResult:
        """Run a single intent-vs-render check.

        AD-727 rule #5: ``provenance_backend`` must be True (caller asserts
        the ref points to a backend render). Browser-side captures are
        prohibited and short-circuit to ``skipped_reason='provenance_invalid'``.
        """
        if not provenance_backend:
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="provenance_invalid",
            )
        if not self._rate.under_limit(agent_id):
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="rate_limit",
            )

        prompt = (
            f"Look at this rendered avatar. The intended emotion is "
            f"'{intent}'. Respond with JSON only: "
            "{\"conveys_intent\": bool, \"confidence\": number 0..1, "
            "\"observation\": \"<<=200 char description of the rendered "
            "EXPRESSION (subject must be the render or the expression, NOT "
            "the agent or the person)>\"}."
        )
        try:
            raw = await self._call_vision(prompt, rendered_attachment_ref)
        except Exception:
            logger.warning(
                "AD-722a-1: vision tier call failed for agent_id=%s; honest-degrade",
                agent_id, exc_info=True,
            )
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=rendered_attachment_ref,
                confidence=0.0, observation="",
                skipped_reason="tier_unavailable",
            )

        self._rate.note_call(agent_id)
        return self._parse(raw, intent, rendered_attachment_ref)

    async def _call_vision(self, prompt: str, ref: str) -> str:
        """Invoke the vision tier with a single attachment ref.

        Reuses ``build_multimodal_messages`` (BF-268 OpenAI shape) when an
        AttachmentStore is bound; otherwise calls the client with the prompt
        directly (test path).
        """
        from probos.cognitive.llm_client import LLMRequest
        if self._store is not None:
            from probos.cognitive.vision_dispatch import build_multimodal_messages

            async def _mime(_aid: str) -> str | None:
                return "image/png"

            messages, _image_ids, _per = await build_multimodal_messages(
                prompt=prompt,
                attachment_ids=[ref],
                store=self._store,
                mime_lookup=_mime,
                text_extraction_max_bytes=32768,
                pdf_extraction_enabled=False,
            )
            request = LLMRequest(
                prompt=prompt, tier="vision", max_tokens=300, messages=messages,
            )
        else:
            request = LLMRequest(prompt=prompt, tier="vision", max_tokens=300)
        response = await self._llm.complete(request)
        return getattr(response, "text", "") or ""

    def _parse(
        self, raw: str, intent: str, ref: str,
    ) -> VisionIntentDivergenceResult:
        import json as _json
        text = raw.strip() if isinstance(raw, str) else ""
        if text.startswith("```"):
            text = "\n".join(
                ln for ln in text.splitlines() if not ln.startswith("```")
            ).strip()
        try:
            payload = _json.loads(text) if text else None
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, Mapping):
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=ref, confidence=0.0,
                observation=text[:200] if text else "",
                skipped_reason="parse_error",
            )
        conveys = payload.get("conveys_intent")
        if not isinstance(conveys, bool):
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=ref, confidence=0.0,
                observation=str(payload.get("observation", ""))[:200],
                skipped_reason="parse_error",
            )
        confidence_raw = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        observation = str(payload.get("observation", ""))[:200]
        # AD-727 rule #8: enforce render-as-subject phrasing.
        if not is_render_phrased(observation):
            logger.info(
                "AD-722a-1: agent-as-subject phrasing flagged for intent=%s; "
                "rejecting observation",
                intent,
            )
            return VisionIntentDivergenceResult(
                divergence_detected=False, intent=intent,
                rendered_attachment_ref=ref, confidence=confidence,
                observation="", skipped_reason="phrasing_violation",
            )
        return VisionIntentDivergenceResult(
            divergence_detected=(not conveys),
            intent=intent,
            rendered_attachment_ref=ref,
            confidence=confidence,
            observation=observation,
        )
