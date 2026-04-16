"""AD-632e: Evaluate Sub-Task Handler — Criteria-based quality scoring.

Judges Compose output against explicit criteria (novelty, relevance,
opening quality, contribution value).  Returns a structured verdict:
pass/fail + score + per-criterion results.

Part of Level 3 cognitive escalation (Query → Analyze → Compose → **Evaluate** → Reflect).
"""

from __future__ import annotations

import json
import logging
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
    system_prompt = (
        f"You are evaluating a draft Ward Room response by {callsign} "
        f"({department} department).\n\n"
        "Score the draft against these criteria:\n"
        "1. **Novelty** — Contains at least one fact, metric, or conclusion "
        "not already present in the thread.\n"
        "2. **Opening quality** — First sentence states a conclusion, not a "
        "process description. No 'Looking at...', 'I notice...', "
        "'I can confirm...' openers.\n"
        "3. **Non-redundancy** — More than confirming what someone already said.\n"
        "4. **Relevance** — Addresses the thread topic from the agent's "
        "departmental perspective.\n\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"novelty": {"pass": true/false, "reason": "..."}, '
        '"opening_quality": {"pass": true/false, "reason": "..."}, '
        '"non_redundancy": {"pass": true/false, "reason": "..."}, '
        '"relevance": {"pass": true/false, "reason": "..."}}, '
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


def _build_proactive_eval_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for proactive observation quality evaluation."""
    system_prompt = (
        f"You are evaluating a draft proactive observation by {callsign} "
        f"({department} department).\n\n"
        "Score the draft against these criteria:\n"
        "1. **Observation value** — Contains actionable insight, not just "
        "restating known status.\n"
        "2. **Action appropriateness** — Action tags ([REPLY], [NOTEBOOK], "
        "[ENDORSE]) are well-targeted and warranted.\n"
        "3. **Departmental lens** — Reflects this agent's expertise.\n"
        "4. **Silence appropriateness** — Should this be [NO_RESPONSE] instead?\n\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"observation_value": {"pass": true/false, "reason": "..."}, '
        '"action_appropriateness": {"pass": true/false, "reason": "..."}, '
        '"departmental_lens": {"pass": true/false, "reason": "..."}, '
        '"silence_appropriateness": {"pass": true/false, "reason": "..."}}, '
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
        "the Ward Room thread.\n\n"
        "Respond with JSON only:\n"
        '{"pass": true/false, "score": 0.0-1.0, '
        '"criteria": {"conclusion_presence": {"pass": true/false, "reason": "..."}, '
        '"threading": {"pass": true/false, "reason": "..."}, '
        '"differentiation": {"pass": true/false, "reason": "..."}}, '
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

        # BF-184: Captain messages and @mentions bypass quality gate.
        # Social obligation outranks quality scoring — failing to respond
        # to the Captain is worse than a mediocre response.
        if context.get("_from_captain") or context.get("_was_mentioned"):
            reason = "captain_message" if context.get("_from_captain") else "mentioned"
            logger.info(
                "BF-184: Evaluate auto-approved for %s (social obligation: %s)",
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
