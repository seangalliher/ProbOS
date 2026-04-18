"""AD-632e: Evaluate Sub-Task Handler — Criteria-based quality scoring.

Judges Compose output against explicit criteria (novelty, relevance,
opening quality, contribution value).  Returns a structured verdict:
pass/fail + score + per-criterion results.

Part of Level 3 cognitive escalation (Query → Analyze → Compose → **Evaluate** → Reflect).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

_DEFAULT_MODE = "ward_room_quality"
_MAX_ERROR_CONTENT = 200


# ---------------------------------------------------------------------------
# Prior result extraction helpers
# ---------------------------------------------------------------------------

def _get_compose_output(prior_results: list[SubTaskResult]) -> str:
    """Extract the most recent successful Compose output."""
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.COMPOSE and pr.success and pr.result:
            return pr.result.get("output", "")
    return ""


def _get_analysis_result(prior_results: list[SubTaskResult]) -> dict:
    """Extract the most recent successful Analyze result."""
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.ANALYZE and pr.success and pr.result:
            return pr.result
    return {}


# ---------------------------------------------------------------------------
# Evaluation mode prompt builders
# ---------------------------------------------------------------------------

def _build_ward_room_eval_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for Ward Room post quality evaluation."""
    trust_band = context.get("_chain_trust_band", "high")

    criteria = (
        "1. **Novelty** — Contains at least one fact, metric, or conclusion "
        "not already present in the thread.\n"
        "2. **Opening quality** — First sentence states a conclusion, not a "
        "process description. No 'Looking at...', 'I notice...', "
        "'I can confirm...' openers.\n"
        "3. **Non-redundancy** — More than confirming what someone already said.\n"
        "4. **Relevance** — Addresses the thread topic from the agent's "
        "departmental perspective.\n"
        "5. **Grounding** — Claims reference observable data (events, logs, "
        "metrics, thread content) or are clearly marked as inference. "
        "Specific IDs, timestamps, or measurements that cannot be verified "
        "from the provided context are fabrication. Fail this criterion if "
        "the response presents unverifiable specifics as fact.\n"
    )

    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )

    system_prompt = (
        f"You are evaluating a draft Ward Room response by {callsign} "
        f"({department} department).\n\n"
        f"Score the draft against these criteria:\n{criteria}\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"novelty": {"pass": true/false, "reason": "..."}, '
        '"opening_quality": {"pass": true/false, "reason": "..."}, '
        '"non_redundancy": {"pass": true/false, "reason": "..."}, '
        '"relevance": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )

    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_prompt = (
        "## Draft Response to Evaluate\n\n"
        f"{compose_output}\n\n"
        "## Analysis That Informed This Draft\n\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        "## Original Content\n\n"
        f"{original}"
    )

    return system_prompt, user_prompt


def _build_proactive_eval_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for proactive observation quality evaluation."""
    trust_band = context.get("_chain_trust_band", "high")

    criteria = (
        "1. **Observation value** — Contains actionable insight, not just "
        "restating known status.\n"
        "2. **Action appropriateness** — Action tags ([REPLY], [NOTEBOOK], "
        "[ENDORSE]) are well-targeted and warranted.\n"
        "3. **Departmental lens** — Reflects this agent's expertise.\n"
        "4. **Silence appropriateness** — Should this be [NO_RESPONSE] instead?\n"
        "5. **Grounding** — Claims reference observable data (events, logs, "
        "metrics, thread content) or are clearly marked as inference. "
        "Specific IDs, timestamps, or measurements that cannot be verified "
        "from the provided context are fabrication. Fail this criterion if "
        "the response presents unverifiable specifics as fact.\n"
    )

    # AD-639: Mid trust — add personality preservation criterion
    if trust_band == "mid":
        criteria += (
            "6. **Voice** — Response has a distinct voice consistent with the "
            "agent's personality, not generic or clinical.\n"
        )

    system_prompt = (
        f"You are evaluating a draft proactive observation by {callsign} "
        f"({department} department).\n\n"
        f"Score the draft against these criteria:\n{criteria}\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"observation_value": {"pass": true/false, "reason": "..."}, '
        '"action_appropriateness": {"pass": true/false, "reason": "..."}, '
        '"departmental_lens": {"pass": true/false, "reason": "..."}, '
        '"silence_appropriateness": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}'
    )
    if trust_band == "mid":
        system_prompt += ', "voice": {"pass": true/false, "reason": "..."}'
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )

    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_prompt = (
        "## Draft Response to Evaluate\n\n"
        f"{compose_output}\n\n"
        "## Analysis That Informed This Draft\n\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        "## Original Content\n\n"
        f"{original}"
    )

    return system_prompt, user_prompt


def _build_notebook_eval_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for notebook entry quality evaluation."""
    system_prompt = (
        f"You are evaluating a draft notebook entry by {callsign} "
        f"({department} department).\n\n"
        "Score the draft against these criteria:\n"
        "1. **Conclusion presence** — Contains a conclusion, finding, or "
        "hypothesis (not just observations).\n"
        "2. **Threading** — Builds on prior notebook entries on this topic.\n"
        "3. **Differentiation** — Contains analysis beyond what was said in "
        "the Ward Room thread.\n"
        "4. **Grounding** — Claims reference observable data or are clearly "
        "marked as inference. No fabricated specifics.\n\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"conclusion_presence": {"pass": true/false, "reason": "..."}, '
        '"threading": {"pass": true/false, "reason": "..."}, '
        '"differentiation": {"pass": true/false, "reason": "..."}, '
        '"grounding": {"pass": true/false, "reason": "..."}}, '
        '"recommendation": "approve"|"revise"|"suppress"}'
    )

    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_prompt = (
        "## Draft Response to Evaluate\n\n"
        f"{compose_output}\n\n"
        "## Analysis That Informed This Draft\n\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        "## Original Content\n\n"
        f"{original}"
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

EvaluationModeBuilder = type(_build_ward_room_eval_prompt)

_EVALUATION_MODES: dict[str, EvaluationModeBuilder] = {
    "ward_room_quality": _build_ward_room_eval_prompt,
    "proactive_quality": _build_proactive_eval_prompt,
    "notebook_quality": _build_notebook_eval_prompt,
}

_PASS_BY_DEFAULT: dict[str, Any] = {
    "pass": True,
    "score": 1.0,
    "criteria": {},
    "recommendation": "approve",
}


# ---------------------------------------------------------------------------
# EvaluateHandler
# ---------------------------------------------------------------------------

class EvaluateHandler:
    """AD-632e: Criteria-based quality scoring of Compose output."""

    def __init__(self, *, llm_client: Any = None, runtime: Any = None) -> None:
        self._llm_client = llm_client
        self._runtime = runtime

    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        start = time.monotonic()

        # Guard: no LLM client
        if self._llm_client is None:
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={"error": "LLM client unavailable"},
                tokens_used=0,
                duration_ms=0,
                success=False,
                tier_used="",
            )

        # Mode dispatch
        mode_key = spec.prompt_template or _DEFAULT_MODE
        builder = _EVALUATION_MODES.get(mode_key)
        if builder is None:
            logger.warning(
                "AD-632e: Unknown evaluate mode '%s', falling back to %s",
                mode_key, _DEFAULT_MODE,
            )
            builder = _EVALUATION_MODES[_DEFAULT_MODE]

        callsign = context.get("_callsign", "agent")
        department = context.get("_department", "")

        # === SAFETY CHECKS (always run, 0 tokens) ===

        # BF-191: Deterministic JSON rejection — compose output must be natural language
        compose_output = _get_compose_output(prior_results)
        stripped = compose_output.strip()
        if stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200]):
            logger.warning(
                "BF-191: Evaluate rejected raw intent JSON from %s (%d chars)",
                context.get("_agent_type", "unknown"),
                len(compose_output),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": False,
                    "score": 0.0,
                    "criteria": {"format": {"pass": False, "reason": "Raw JSON instead of natural language"}},
                    "recommendation": "suppress",
                    "rejection_reason": "raw_json_output",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # BF-204: Deterministic grounding pre-check — catch fabricated identifiers
        # Runs at ALL trust bands, even social obligation. Safety > obligation.
        _grounding_source = (context.get("context", "") + " "
                             + json.dumps(_get_analysis_result(prior_results)))
        # Hex IDs (6+ chars) in compose output that don't appear in source material
        _hex_ids = re.findall(r'\b[0-9a-f]{6,}\b', compose_output.lower())
        _ungrounded_ids = [h for h in _hex_ids if h not in _grounding_source.lower()]
        if len(_ungrounded_ids) >= 2:
            logger.warning(
                "BF-204: Grounding check failed for %s — %d ungrounded hex IDs: %s",
                context.get("_agent_type", "unknown"),
                len(_ungrounded_ids),
                _ungrounded_ids[:3],
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": False,
                    "score": 0.0,
                    "criteria": {
                        "grounding": {
                            "pass": False,
                            "reason": f"Ungrounded identifiers: {_ungrounded_ids[:3]}",
                        },
                    },
                    "recommendation": "suppress",
                    "rejection_reason": "confabulation_detected",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # === OBLIGATION/TRUST BYPASSES ===

        # BF-184/187: Captain, @mention, and DM bypass quality gate.
        # Social obligation outranks quality scoring — failing to respond
        # to the Captain or a DM is worse than a mediocre response.
        if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
            if context.get("_from_captain"):
                reason = "captain_message"
            elif context.get("_was_mentioned"):
                reason = "mentioned"
            else:
                reason = "dm_recipient"
            logger.info(
                "BF-184/187: Evaluate auto-approved for %s (social obligation: %s)",
                context.get("_agent_type", "unknown"),
                reason,
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": True,
                    "score": 1.0,
                    "criteria": {},
                    "recommendation": "approve",
                    "bypass_reason": reason,
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # AD-638: Boot camp quality gate relaxation
        if context.get("_boot_camp_active"):
            logger.info(
                "AD-638: Evaluate auto-approved for %s (boot camp)",
                context.get("_agent_type", "unknown"),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": True,
                    "score": 0.8,
                    "criteria": {},
                    "recommendation": "approve",
                    "bypass_reason": "boot_camp",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # AD-639: Low trust band — skip evaluation, let personality through
        if context.get("_chain_trust_band") == "low":
            logger.info(
                "AD-639: Evaluate skipped for %s (low trust band, trust=%.2f)",
                context.get("_agent_type", "unknown"),
                context.get("_trust_score", 0.0),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={
                    "pass": True,
                    "score": 0.0,  # 0.0 signals "not evaluated", not "bad"
                    "criteria": {},
                    "recommendation": "approve",
                    "bypass_reason": "low_trust_band",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # === LLM EVALUATION ===

        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )

        # LLM call
        try:
            request = LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                tier=spec.tier,
                temperature=0.0,
                max_tokens=512,
            )
            response = await self._llm_client.complete(request)
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.warning(
                "AD-632e: Evaluate LLM call failed for %s: %s",
                context.get("_agent_type", "unknown"),
                str(exc)[:_MAX_ERROR_CONTENT],
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result={"error": str(exc)[:_MAX_ERROR_CONTENT]},
                tokens_used=0,
                duration_ms=duration,
                success=False,
                tier_used="",
            )

        duration = int((time.monotonic() - start) * 1000)

        # Parse structured verdict
        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None

        if parsed is None:
            logger.warning(
                "AD-632e: Evaluate JSON parse failed, passing by default: %s",
                content[:_MAX_ERROR_CONTENT],
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=getattr(response, "tokens_used", 0),
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
            )

        # Ensure required keys
        result = {
            "pass": parsed.get("pass", True),
            "score": float(parsed.get("score", 1.0)),
            "criteria": parsed.get("criteria", {}),
            "recommendation": parsed.get("recommendation", "approve"),
        }

        logger.info(
            "AD-632e: Evaluate verdict for %s: pass=%s, score=%.2f, recommendation=%s",
            context.get("_agent_type", "unknown"),
            result["pass"],
            result["score"],
            result["recommendation"],
        )

        return SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
