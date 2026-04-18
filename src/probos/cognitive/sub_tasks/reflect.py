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
# AD-643b: Trigger feedback formatting
# ---------------------------------------------------------------------------

def _format_trigger_feedback(feedback: dict) -> str:
    """AD-643b: Format undeclared action feedback for REFLECT prompt."""
    undeclared = feedback.get("undeclared_actions", [])
    missed = feedback.get("missed_skills", [])
    if not undeclared:
        return ""
    actions_str = ", ".join(undeclared)
    skills_str = ", ".join(missed) if missed else "none"
    return (
        "\n## Skill Trigger Feedback\n\n"
        "You took actions without declaring them in your intended_actions "
        "during triage:\n"
        f"- Undeclared actions: {actions_str}\n"
        f"- Quality skills that did NOT load: {skills_str}\n\n"
        "In future triage, include these action tags in your intended_actions "
        "so the relevant quality skills load and improve your output.\n"
    )


# ---------------------------------------------------------------------------
# Prior result extraction helpers
# ---------------------------------------------------------------------------

def _get_compose_output(
    prior_results: list[SubTaskResult],
    context: dict | None = None,
) -> str:
    """Extract the most recent successful Compose output.

    Falls back to observation key for AD-643b re-reflect chains where
    prior_results may not contain compose output.
    """
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.COMPOSE and pr.success and pr.result:
            return pr.result.get("output", "")
    # AD-643b: Fallback for re-reflect partial chains
    if context:
        return context.get("_re_reflect_compose_output", "")
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
    trust_band = context.get("_chain_trust_band", "high")

    # AD-639: Mid trust — inject personality block for voice preservation
    if trust_band == "mid":
        from probos.cognitive.standing_orders import _build_personality_block
        personality_section = _build_personality_block(
            agent_type=context.get("_agent_type", "agent"),
            department=department,
            callsign_override=callsign,
        )
        system_prompt = (
            f"{personality_section}\n\n"
            "You are reviewing your own draft Ward Room response.\n\n"
            "**IMPORTANT: Preserve your personality and voice when revising.** "
            "Revisions should improve substance, not flatten personality. "
            "If the draft sounds like you, keep that voice.\n\n"
            "Check the draft against these criteria:\n"
            "- **Novelty**: Does it contain at least one new fact, metric, or "
            "conclusion not in the thread?\n"
            "- **Opening quality**: Does the first sentence state a conclusion? "
            "No 'Looking at...', 'I notice...', 'I can confirm...' openers.\n"
            "- **Non-redundancy**: Is this more than confirming what someone said?\n"
            "- **Relevance**: Does it address the topic from your department's "
            "perspective?\n"
            "- **Voice consistency**: Does the revision preserve your personality?\n"
            "- **Grounding**: Are your claims based on data you actually have? "
            "If you cited specific IDs, timestamps, or metrics, can you trace "
            "them to your episodic memory or the thread content? Remove or "
            "qualify any unverifiable specifics.\n\n"
        )
    else:
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

    compose_output = _get_compose_output(prior_results, context)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
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
    trust_band = context.get("_chain_trust_band", "high")

    # AD-639: Mid trust — inject personality block for voice preservation
    if trust_band == "mid":
        from probos.cognitive.standing_orders import _build_personality_block
        personality_section = _build_personality_block(
            agent_type=context.get("_agent_type", "agent"),
            department=department,
            callsign_override=callsign,
        )
        system_prompt = (
            f"{personality_section}\n\n"
            "You are reviewing your own draft proactive observation.\n\n"
            "**IMPORTANT: Preserve your personality and voice when revising.** "
            "Revisions should improve substance, not flatten personality. "
            "If the draft sounds like you, keep that voice.\n\n"
            "Check the draft against these criteria:\n"
            "- **Observation value**: Does it contain actionable insight?\n"
            "- **Action appropriateness**: Are action tags warranted?\n"
            "- **Departmental lens**: Does it reflect your expertise?\n"
            "- **Silence appropriateness**: Should this be [NO_RESPONSE]?\n"
            "- **Voice consistency**: Does the revision preserve your personality?\n"
            "- **Grounding**: Are your claims based on data you actually have? "
            "If you cited specific IDs, timestamps, or metrics, can you trace "
            "them to your episodic memory or the thread content? Remove or "
            "qualify any unverifiable specifics.\n\n"
        )
    else:
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

    compose_output = _get_compose_output(prior_results, context)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
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
    trust_band = context.get("_chain_trust_band", "high")

    # AD-639: Mid trust — inject personality block for voice preservation
    if trust_band == "mid":
        from probos.cognitive.standing_orders import _build_personality_block
        personality_section = _build_personality_block(
            agent_type=context.get("_agent_type", "agent"),
            department=department,
            callsign_override=callsign,
        )
        system_prompt = (
            f"{personality_section}\n\n"
            "You are reviewing your own draft response for standing orders compliance.\n\n"
            "**IMPORTANT: Preserve your personality and voice when revising.** "
            "Revisions should improve substance, not flatten personality. "
            "If the draft sounds like you, keep that voice.\n\n"
            "Check the draft against general quality criteria:\n"
            "- Does it follow standing orders?\n"
            "- Is it concise and actionable?\n"
            "- Does it avoid redundancy?\n"
            "- **Voice consistency**: Does the revision preserve your personality?\n"
            "- **Grounding**: Are your claims based on data you actually have? "
            "If you cited specific IDs, timestamps, or metrics, can you trace "
            "them to your episodic memory or the thread content? Remove or "
            "qualify any unverifiable specifics.\n\n"
        )
    else:
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

    compose_output = _get_compose_output(prior_results, context)
    eval_result = _get_evaluate_result(prior_results)

    user_prompt = "## Your Draft Response\n\n" + compose_output + "\n"
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
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

        # === SAFETY CHECKS (honor EVALUATE safety verdicts) ===

        # BF-204: Suppress short-circuit — if EVALUATE said suppress, honor it.
        # Runs BEFORE social obligation because suppression from BF-191/BF-204
        # safety checks must not be overridden. Silence > fabrication.
        if _should_suppress(prior_results):
            duration = int((time.monotonic() - start) * 1000)
            logger.info(
                "BF-204: Reflect honoring suppress for %s: Evaluate recommended suppress",
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

        # === OBLIGATION/TRUST BYPASSES ===

        # BF-185/187: Social obligation bypass
        # Social obligation outranks quality self-critique but not safety.
        if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
            compose_output = _get_compose_output(prior_results, context)
            if context.get("_from_captain"):
                reason = "captain_message"
            elif context.get("_was_mentioned"):
                reason = "mentioned"
            else:
                reason = "dm_recipient"
            logger.info(
                "BF-185/187: Reflect auto-approved for %s (social obligation: %s)",
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

        # AD-638: Boot camp quality gate relaxation
        if context.get("_boot_camp_active"):
            compose_output = _get_compose_output(prior_results, context)
            logger.info(
                "AD-638: Reflect auto-approved for %s (boot camp)",
                context.get("_agent_type", "unknown"),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={
                    "output": compose_output,
                    "revised": False,
                    "suppressed": False,
                    "bypass_reason": "boot_camp",
                },
                tokens_used=0,
                duration_ms=int((time.monotonic() - start) * 1000),
                success=True,
                tier_used="",
            )

        # AD-639: Low trust band — skip self-critique, preserve personality
        if context.get("_chain_trust_band") == "low":
            compose_output = _get_compose_output(prior_results, context)
            logger.info(
                "AD-639: Reflect skipped for %s (low trust band, trust=%.2f)",
                context.get("_agent_type", "unknown"),
                context.get("_trust_score", 0.0),
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.REFLECT,
                name=spec.name,
                result={
                    "output": compose_output,
                    "revised": False,
                    "reflection": "low_trust_band_bypass",
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
        compose_output = _get_compose_output(prior_results, context)

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
