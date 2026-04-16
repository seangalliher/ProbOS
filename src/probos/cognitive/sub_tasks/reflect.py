"""AD-632e: Reflect Sub-Task Handler — Self-critique and revision.

Receives Compose output and optional Evaluate verdict, performs self-critique
from the agent's perspective, and returns either the original output (approved)
or a revised version.

Part of Level 3 cognitive escalation (Query → Analyze → Compose → Evaluate → **Reflect**).
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

_DEFAULT_MODE = "ward_room_reflection"
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


def _get_evaluate_result(prior_results: list[SubTaskResult]) -> dict | None:
    """Extract the most recent successful Evaluate result, or None."""
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.EVALUATE and pr.success and pr.result:
            return pr.result
    return None


# ---------------------------------------------------------------------------
# Suppress short-circuit
# ---------------------------------------------------------------------------

def _should_suppress(prior_results: list[SubTaskResult]) -> bool:
    """Return True if prior Evaluate recommended suppression."""
    eval_result = _get_evaluate_result(prior_results)
    if eval_result and eval_result.get("recommendation") == "suppress":
        return True
    return False


# ---------------------------------------------------------------------------
# Reflection mode prompt builders
# ---------------------------------------------------------------------------

def _build_ward_room_reflect_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for Ward Room post self-critique."""
    skill_instructions = context.get("_augmentation_skill_instructions", "")

    system_prompt = (
        f"You are {callsign} ({department} department), reviewing your own "
        "draft Ward Room response for quality.\n\n"
        "Check the draft against these criteria:\n"
        "- **Novelty**: Does it contain at least one new fact, metric, or "
        "conclusion not in the thread?\n"
        "- **Opening quality**: Does the first sentence state a conclusion? "
        "No 'Looking at...', 'I notice...', 'I can confirm...' openers.\n"
        "- **Non-redundancy**: Is this more than confirming what someone said?\n"
        "- **Relevance**: Does it address the topic from your department's "
        "perspective?\n\n"
    )
    if skill_instructions:
        system_prompt += (
            "## Active Skill Self-Verification Criteria\n\n"
            f"{skill_instructions}\n\n"
        )
    system_prompt += (
        "Either:\n"
        "(A) Approve: return the draft unchanged as \"output\"\n"
        "(B) Revise: return an improved version as \"output\" with \"revised\": true\n"
        "(C) Suppress: if the draft adds no value, return \"[NO_RESPONSE]\" as "
        "\"output\"\n\n"
        "Respond with JSON: {\"output\": \"...\", \"revised\": true/false, "
        "\"reflection\": \"brief explanation\"}"
    )

    compose_output = _get_compose_output(prior_results)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    user_prompt += (
        "\n## Self-Critique Instructions\n\n"
        "Review your draft against the criteria above. "
        "Return JSON with your decision."
    )

    return system_prompt, user_prompt


def _build_proactive_reflect_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for proactive observation self-critique."""
    skill_instructions = context.get("_augmentation_skill_instructions", "")

    system_prompt = (
        f"You are {callsign} ({department} department), reviewing your own "
        "draft proactive observation for quality.\n\n"
        "Check the draft against these criteria:\n"
        "- **Observation value**: Does it contain actionable insight?\n"
        "- **Action appropriateness**: Are action tags warranted?\n"
        "- **Departmental lens**: Does it reflect your expertise?\n"
        "- **Silence appropriateness**: Should this be [NO_RESPONSE]?\n\n"
    )
    if skill_instructions:
        system_prompt += (
            "## Active Skill Self-Verification Criteria\n\n"
            f"{skill_instructions}\n\n"
        )
    system_prompt += (
        "Either:\n"
        "(A) Approve: return the draft unchanged as \"output\"\n"
        "(B) Revise: return an improved version as \"output\" with \"revised\": true\n"
        "(C) Suppress: if the draft adds no value, return \"[NO_RESPONSE]\" as "
        "\"output\"\n\n"
        "Respond with JSON: {\"output\": \"...\", \"revised\": true/false, "
        "\"reflection\": \"brief explanation\"}"
    )

    compose_output = _get_compose_output(prior_results)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    user_prompt += (
        "\n## Self-Critique Instructions\n\n"
        "Review your draft against the criteria above. "
        "Return JSON with your decision."
    )

    return system_prompt, user_prompt


def _build_general_reflect_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build prompts for general standing orders compliance check."""
    skill_instructions = context.get("_augmentation_skill_instructions", "")

    system_prompt = (
        f"You are {callsign} ({department} department), reviewing your own "
        "draft response for standing orders compliance.\n\n"
        "Check the draft against general quality criteria:\n"
        "- Does it follow standing orders?\n"
        "- Is it concise and actionable?\n"
        "- Does it avoid redundancy?\n\n"
    )
    if skill_instructions:
        system_prompt += (
            "## Active Skill Self-Verification Criteria\n\n"
            f"{skill_instructions}\n\n"
        )
    system_prompt += (
        "Either:\n"
        "(A) Approve: return the draft unchanged as \"output\"\n"
        "(B) Revise: return an improved version as \"output\" with \"revised\": true\n"
        "(C) Suppress: if the draft adds no value, return \"[NO_RESPONSE]\" as "
        "\"output\"\n\n"
        "Respond with JSON: {\"output\": \"...\", \"revised\": true/false, "
        "\"reflection\": \"brief explanation\"}"
    )

    compose_output = _get_compose_output(prior_results)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    user_prompt += (
        "\n## Self-Critique Instructions\n\n"
        "Review your draft against the criteria above. "
        "Return JSON with your decision."
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

ReflectionModeBuilder = type(_build_ward_room_reflect_prompt)

_REFLECTION_MODES: dict[str, ReflectionModeBuilder] = {
    "ward_room_reflection": _build_ward_room_reflect_prompt,
    "proactive_reflection": _build_proactive_reflect_prompt,
    "general_reflection": _build_general_reflect_prompt,
}


# ---------------------------------------------------------------------------
# ReflectHandler
# ---------------------------------------------------------------------------

class ReflectHandler:
    """AD-632e: Self-critique and optional revision of Compose output."""

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
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={"error": "LLM client unavailable"},
                tokens_used=0,
                duration_ms=0,
                success=False,
                tier_used="",
            )

        # Suppress short-circuit: Evaluate recommended suppress
        if _should_suppress(prior_results):
            duration = int((time.monotonic() - start) * 1000)
            logger.info(
                "AD-632e: Reflect short-circuit for %s: Evaluate recommended suppress",
                context.get("_agent_type", "unknown"),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={"output": "[NO_RESPONSE]", "revised": False, "suppressed": True},
                tokens_used=0,
                duration_ms=duration,
                success=True,
                tier_used="",
            )

        # BF-185: Captain messages and @mentions bypass self-critique.
        # Social obligation outranks self-critique — the Captain expects a response.
        if context.get("_from_captain") or context.get("_was_mentioned"):
            compose_output = _get_compose_output(prior_results)
            reason = "captain_message" if context.get("_from_captain") else "mentioned"
            logger.info(
                "BF-185: Reflect auto-approved for %s (social obligation: %s)",
                context.get("_agent_type", "unknown"),
                reason,
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={
                    "output": compose_output,
                    "revised": False,
                    "suppressed": False,
                    "bypass_reason": reason,
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # Mode dispatch
        mode_key = spec.prompt_template or _DEFAULT_MODE
        builder = _REFLECTION_MODES.get(mode_key)
        if builder is None:
            logger.warning(
                "AD-632e: Unknown reflect mode '%s', falling back to %s",
                mode_key, _DEFAULT_MODE,
            )
            builder = _REFLECTION_MODES[_DEFAULT_MODE]

        callsign = context.get("_callsign", "agent")
        department = context.get("_department", "")

        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )

        # Preserve compose output for fail-open fallback
        compose_output = _get_compose_output(prior_results)

        # LLM call
        try:
            request = LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                tier=spec.tier,
                temperature=0.1,
                max_tokens=2048,
            )
            response = await self._llm_client.complete(request)
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.warning(
                "AD-632e: Reflect LLM call failed for %s: %s",
                context.get("_agent_type", "unknown"),
                str(exc)[:_MAX_ERROR_CONTENT],
            )
            # Fail-open: return original Compose output unchanged
            return SubTaskResult(
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={"output": compose_output, "revised": False},
                tokens_used=0,
                duration_ms=duration,
                success=False,
                tier_used="",
            )

        duration = int((time.monotonic() - start) * 1000)

        # Parse response
        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None

        if parsed is not None and "output" in parsed:
            result = {
                "output": parsed["output"],
                "revised": parsed.get("revised", False),
                "reflection": parsed.get("reflection", ""),
            }
        elif content.strip():
            # Plain text response treated as revision
            result = {
                "output": content.strip(),
                "revised": True,
                "reflection": "",
            }
        else:
            # Empty or unparseable — fail-open with original
            logger.warning(
                "AD-632e: Reflect parse failed, returning original: %s",
                content[:_MAX_ERROR_CONTENT],
            )
            result = {
                "output": compose_output,
                "revised": False,
            }

        logger.info(
            "AD-632e: Reflect for %s: revised=%s, suppressed=%s",
            context.get("_agent_type", "unknown"),
            result.get("revised", False),
            result.get("output") == "[NO_RESPONSE]",
        )

        return SubTaskResult(
            sub_task_type=SubTaskType.REFLECT,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
