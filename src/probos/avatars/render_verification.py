"""AD-728: vision-LLM render-coherence mirror function.

Generalizes the AD-722e-2 self-render-verify pattern into a trigger-driven
mirror function with three trigger sources:

  1. ``captain_command``     — Captain runs ``/verify-render <agent_id>``.
  2. ``divergence_followup`` — Optional AD-722a-1 post-hook (gated by
     ``cfg.avatars.render_verification_followup_enabled``).
  3. ``agent_initiated_stub`` — Path exists but hard-rejected pending future
     AD that flips the config flag.

AD-727 hard rules:
  rule #1 — READ-ONLY on reputation + associative routing (digital-vs-render
            is OUTPUT-vs-OUTPUT, NOT REASONING-vs-OUTPUT).
  rule #5 — backend-server-side render only.
  rule #8 — OUTPUT-as-subject phrasing (verified via ``is_render_phrased``).

AD-731 invariant: image bytes flow through ``AttachmentStore`` SHA-256 refs;
this module never inlines base64.

Cost discipline: coherent observations are NOT logged (only divergent ones
emit ``EventType.RENDER_DIVERGENCE_OBSERVED``).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any, Mapping

from probos.avatars.vision_intent_divergence import (
    VisionLLMRateLimit,
    is_render_phrased,
)

logger = logging.getLogger(__name__)


_VALID_TRIGGERS = frozenset({
    "captain_command",
    "divergence_followup",
    "agent_initiated_stub",
})


@dataclasses.dataclass(frozen=True)
class RenderCoherenceResult:
    """AD-728: outcome of a single render-coherence mirror call.

    ``coherent`` is None when the call was skipped (honest-degrade); see
    ``skipped_reason`` for the reason.
    """

    agent_id: str
    trigger: str
    coherent: bool | None
    digital_description: str
    analog_description: str | None
    divergence_summary: str | None
    skipped_reason: str | None
    timestamp: float


async def verify_render_coherence(
    *,
    runtime: Any,
    agent_id: str,
    trigger: str,
    digital_state_summary: str = "",
    backend_render_ref: str | None = None,
) -> RenderCoherenceResult:
    """Mirror function: compare the digital model against the rendered image.

    All failure modes return a ``RenderCoherenceResult`` with
    ``skipped_reason`` set; this function NEVER raises.

    Args:
        runtime: The ProbOS runtime (provides config, llm_client,
            attachment_store, event emission).
        agent_id: Target agent.
        trigger: One of ``captain_command``, ``divergence_followup``,
            ``agent_initiated_stub``. Unknown triggers honest-degrade.
        digital_state_summary: Pre-computed digital description (e.g. from
            the AD-722e projection helper). When empty, the caller did
            not supply one — caller is responsible for projection.
        backend_render_ref: SHA-256 attachment ref to the backend-rendered
            PNG. When None or empty, honest-degrade with
            ``skipped_reason='backend_render_unavailable'``.
    """
    now = time.time()

    def _result(
        *,
        coherent: bool | None,
        analog: str | None = None,
        divergence: str | None = None,
        skipped: str | None,
    ) -> RenderCoherenceResult:
        return RenderCoherenceResult(
            agent_id=agent_id,
            trigger=trigger,
            coherent=coherent,
            digital_description=digital_state_summary,
            analog_description=analog,
            divergence_summary=divergence,
            skipped_reason=skipped,
            timestamp=now,
        )

    if trigger not in _VALID_TRIGGERS:
        logger.info(
            "AD-728: unknown trigger %r for agent_id=%s; honest-degrade",
            trigger, agent_id,
        )
        return _result(coherent=None, skipped="unknown_trigger")

    if trigger == "agent_initiated_stub":
        # Path exists so future AD flips the gate; currently hard-rejected.
        return _result(coherent=None, skipped="agent_initiated_disabled")

    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None) if cfg is not None else None
    if avatars_cfg is None or not getattr(avatars_cfg, "render_verification_enabled", False):
        return _result(coherent=None, skipped="disabled")

    if trigger == "divergence_followup" and not getattr(
        avatars_cfg, "render_verification_followup_enabled", False
    ):
        return _result(coherent=None, skipped="followup_disabled")

    if not backend_render_ref:
        return _result(coherent=None, skipped="backend_render_unavailable")

    max_per_hour = int(getattr(avatars_cfg, "render_verification_max_per_hour_per_agent", 0))
    if max_per_hour <= 0:
        return _result(coherent=None, skipped="disabled")

    rate = VisionLLMRateLimit(scope="render_verification", max_per_hour=max_per_hour)
    if not rate.under_limit(agent_id):
        return _result(coherent=None, skipped="rate_limited")

    llm = getattr(runtime, "llm_client", None)
    if llm is None:
        return _result(coherent=None, skipped="tier_unavailable")

    store = getattr(runtime, "attachment_store", None)

    prompt = (
        "Compare this rendered avatar against its digital description.\n\n"
        f"Digital description: {digital_state_summary}\n\n"
        "Respond with JSON only: "
        "{\"coherent\": bool, \"analog_description\": \"<<=200 char "
        "description, phrased about the RENDER OUTPUT (e.g. 'Render "
        "output for Ezri shows ...'). Do NOT use agent-as-subject "
        "phrasing like 'she looks...' or 'the agent appears...'.\", "
        "\"divergence_summary\": \"<<=200 char renderer-subject summary "
        "of the divergence, or empty string when coherent\"}."
    )

    try:
        raw = await _call_vision(llm, store, prompt, backend_render_ref)
    except Exception:
        logger.warning(
            "AD-728: vision tier call failed for agent_id=%s trigger=%s; honest-degrade",
            agent_id, trigger, exc_info=True,
        )
        return _result(coherent=None, skipped="tier_unavailable")

    rate.note_call(agent_id)

    parsed = _parse_vision_payload(raw)
    if parsed is None:
        return _result(coherent=None, skipped="parse_error")

    coherent, analog, divergence = parsed

    # AD-727 rule #8: re-prompt once if phrasing rejects the analog description.
    if analog and not is_render_phrased(analog):
        try:
            retry_prompt = (
                prompt
                + "\n\nIMPORTANT: phrase the analog_description with the "
                "RENDER as subject (e.g. 'Render output for "
                f"{agent_id} shows ...'). Do NOT say 'she/he/they "
                "looks/appears/is ...'."
            )
            raw_retry = await _call_vision(llm, store, retry_prompt, backend_render_ref)
            rate.note_call(agent_id)
            parsed_retry = _parse_vision_payload(raw_retry)
            if parsed_retry is not None:
                coherent_r, analog_r, divergence_r = parsed_retry
                if analog_r and is_render_phrased(analog_r):
                    coherent, analog, divergence = coherent_r, analog_r, divergence_r
                else:
                    return _result(
                        coherent=None,
                        skipped="phrasing_rejected",
                    )
            else:
                return _result(coherent=None, skipped="phrasing_rejected")
        except Exception:
            logger.warning(
                "AD-728: phrasing re-prompt failed for agent_id=%s; honest-degrade",
                agent_id, exc_info=True,
            )
            return _result(coherent=None, skipped="phrasing_rejected")

    # Cost discipline: only emit on divergence.
    if coherent is False:
        await _emit_render_divergence(
            runtime=runtime,
            agent_id=agent_id,
            trigger=trigger,
            digital=digital_state_summary,
            analog=analog or "",
            divergence_summary=divergence or "",
            timestamp=now,
        )

    return _result(
        coherent=coherent,
        analog=analog,
        divergence=divergence,
        skipped=None,
    )


async def _call_vision(
    llm: Any,
    store: Any,
    prompt: str,
    backend_render_ref: str,
) -> str:
    """Build the multimodal message and invoke the vision tier.

    AD-731 invariant: bytes flow through AttachmentStore SHA-256 refs; the
    IntentMessage / LLMRequest carries the ref, never inlined base64.
    """
    from probos.cognitive.llm_client import LLMRequest

    if store is not None:
        from probos.cognitive.vision_dispatch import build_multimodal_messages

        async def _mime(_aid: str) -> str | None:
            return "image/png"

        messages, _ids, _per = await build_multimodal_messages(
            prompt=prompt,
            attachment_ids=[backend_render_ref],
            store=store,
            mime_lookup=_mime,
            text_extraction_max_bytes=32768,
            pdf_extraction_enabled=False,
        )
        request = LLMRequest(
            prompt=prompt, tier="vision", max_tokens=300, messages=messages,
        )
    else:
        request = LLMRequest(prompt=prompt, tier="vision", max_tokens=300)

    response = await llm.complete(request)
    return getattr(response, "text", "") or ""


def _parse_vision_payload(
    raw: str,
) -> tuple[bool, str, str] | None:
    """Parse vision-LLM JSON response. Returns (coherent, analog, divergence)
    or None on parse failure.
    """
    text = raw.strip() if isinstance(raw, str) else ""
    if text.startswith("```"):
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("```")
        ).strip()
    try:
        payload = json.loads(text) if text else None
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    coherent = payload.get("coherent")
    if not isinstance(coherent, bool):
        return None
    analog = str(payload.get("analog_description", ""))[:200]
    divergence = str(payload.get("divergence_summary", ""))[:200]
    return coherent, analog, divergence


async def _emit_render_divergence(
    *,
    runtime: Any,
    agent_id: str,
    trigger: str,
    digital: str,
    analog: str,
    divergence_summary: str,
    timestamp: float,
) -> None:
    """Emit AD-728 RENDER_DIVERGENCE_OBSERVED event.

    Severity: payload field; computed from rough divergence length (short
    summary → 'low', long summary → 'high'). The renderer is the subject of
    every diagnostic phrase (Hard Rule 8).
    """
    from probos.events import EventType

    severity = "high" if len(divergence_summary) > 80 else "low"
    payload = {
        "agent_id": agent_id,
        "trigger": trigger,
        "digital_description": digital,
        "analog_description": analog,
        "divergence_summary": divergence_summary,
        "severity": severity,
        "timestamp": timestamp,
    }

    emit = getattr(runtime, "emit_event", None)
    if emit is None:
        logger.warning(
            "AD-728: runtime has no emit_event for agent_id=%s; observation lost",
            agent_id,
        )
        return
    try:
        result = emit(EventType.RENDER_DIVERGENCE_OBSERVED, payload)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.warning(
            "AD-728: emit_event failed for agent_id=%s; observation lost",
            agent_id, exc_info=True,
        )


__all__ = ["RenderCoherenceResult", "verify_render_coherence"]
