"""AD-722e-2: vision-LLM verification of self-render (digital-vs-render coherence).

Consumes a backend-server-side render of the agent's avatar and asks a vision
LLM whether the render matches the digital state. Outputs surface as a
``self_perception`` observation block when the integration is enabled.

AD-727 hard rules enforced:
  rule #1 — READ-ONLY on trust + Hebbian (digital-vs-render is NOT
            REASONING-vs-OUTPUT). This module never wires into trust paths.
  rule #5 — backend-server-side render only; ``provenance_backend=False``
            short-circuits without an LLM call.
  rule #8 — phrasing: "Render output differs from digital state in
            <channel>" rather than "<agent> looks wrong." Enforced via the
            shared ``is_render_phrased`` regex from AD-722a-1.
  joint review — AD-722e inheritance; this AD's vision-LLM extension
            inherits the gate.

AD-731 invariant: refs only; raw bytes never reach this module.

Wave 162 coordination: REUSES the rate-limit primitive + phrasing-regex
helper from AD-722a-1 (`vision_intent_divergence` module). One budget per
agent across all vision-LLM observability uses (different ``scope`` per
detector keeps them keyed independently inside the shared store).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from probos.avatars.vision_intent_divergence import (
    VisionLLMRateLimit,
    is_render_phrased,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderCoherenceObservation:
    coherent: bool
    observation: str
    confidence: float
    screenshot_ref: str
    # "rate_limit" | "provenance_invalid" | "tier_unavailable"
    # | "phrasing_violation" | "parse_error" | None
    skipped_reason: str | None = None


class SelfRenderVerifier:
    """Vision-LLM digital-vs-render coherence checker.

    Tier-2 throughout (NEVER raises). READ-ONLY on trust + Hebbian (AD-727
    rule #1: digital-vs-render is OUTPUT-vs-OUTPUT, not REASONING-vs-OUTPUT,
    so the trust wiring is NOT authorized).
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
            scope="self_render_verify",
            max_per_hour=max_per_hour,
        )

    async def verify(
        self,
        *,
        agent_id: str,
        digital_state_summary: str,
        backend_render_ref: str,
        provenance_backend: bool,
    ) -> RenderCoherenceObservation:
        if not provenance_backend:
            return RenderCoherenceObservation(
                coherent=True, observation="", confidence=0.0,
                screenshot_ref=backend_render_ref,
                skipped_reason="provenance_invalid",
            )
        if not self._rate.under_limit(agent_id):
            return RenderCoherenceObservation(
                coherent=True, observation="", confidence=0.0,
                screenshot_ref=backend_render_ref,
                skipped_reason="rate_limit",
            )

        prompt = (
            "Compare this rendered avatar against its digital description.\n\n"
            f"Digital description: {digital_state_summary}\n\n"
            "Respond with JSON only: "
            "{\"coherent\": bool, \"confidence\": number 0..1, "
            "\"observation\": \"<<=200 char description, phrased about the "
            "RENDER OUTPUT (e.g. 'Render output differs from digital state in "
            "the lip-color channel'). Do NOT use agent-as-subject phrasing "
            "like 'she looks...' or 'the agent appears...'.\"}."
        )
        try:
            raw = await self._call_vision(prompt, backend_render_ref)
        except Exception:
            logger.warning(
                "AD-722e-2: vision tier call failed agent_id=%s; honest-degrade",
                agent_id, exc_info=True,
            )
            return RenderCoherenceObservation(
                coherent=True, observation="", confidence=0.0,
                screenshot_ref=backend_render_ref,
                skipped_reason="tier_unavailable",
            )

        self._rate.note_call(agent_id)
        return self._parse(raw, backend_render_ref)

    async def _call_vision(self, prompt: str, ref: str) -> str:
        from probos.cognitive.llm_client import LLMRequest
        if self._store is not None:
            from probos.cognitive.vision_dispatch import build_multimodal_messages

            async def _mime(_aid: str) -> str | None:
                return "image/png"

            messages, _ids, _per = await build_multimodal_messages(
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

    def _parse(self, raw: str, ref: str) -> RenderCoherenceObservation:
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
            return RenderCoherenceObservation(
                coherent=True, observation=text[:200] if text else "",
                confidence=0.0, screenshot_ref=ref,
                skipped_reason="parse_error",
            )
        coherent = payload.get("coherent")
        if not isinstance(coherent, bool):
            return RenderCoherenceObservation(
                coherent=True,
                observation=str(payload.get("observation", ""))[:200],
                confidence=0.0, screenshot_ref=ref,
                skipped_reason="parse_error",
            )
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        observation = str(payload.get("observation", ""))[:200]
        if not is_render_phrased(observation):
            logger.info(
                "AD-722e-2: agent-as-subject phrasing flagged; rejecting observation"
            )
            return RenderCoherenceObservation(
                coherent=True, observation="",
                confidence=confidence, screenshot_ref=ref,
                skipped_reason="phrasing_violation",
            )
        return RenderCoherenceObservation(
            coherent=coherent,
            observation=observation,
            confidence=confidence,
            screenshot_ref=ref,
        )
