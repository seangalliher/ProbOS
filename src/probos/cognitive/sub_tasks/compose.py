"""AD-632d: Compose Sub-Task Handler — Skill-augmented response composition.

Produces the agent's final Ward Room post, DM reply, or proactive observation
from prior Analyze results.  Part of Level 3 cognitive escalation
(Query → Analyze → **Compose**).

The handler composes responses using the full system prompt (personality,
standing orders, skills) and mode-specific action vocabulary.  It does NOT
parse action tags — that is handled downstream by ``act()`` (SRP).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from probos.cognitive.standing_orders import compose_instructions
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.types import LLMRequest

logger = logging.getLogger(__name__)

_DEFAULT_MODE = "ward_room_response"


# ---------------------------------------------------------------------------
# SILENT short-circuit helpers
# ---------------------------------------------------------------------------

def _should_short_circuit(prior_results: list[SubTaskResult], context: dict | None = None) -> bool:
    """Return True if prior Analyze determined silence is appropriate."""
    # BF-186 + BF-187: Social obligation overrides SILENT
    if context and (context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm")):
        return False
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.ANALYZE and pr.success and pr.result:
            r = pr.result
            if r.get("contribution_assessment") == "SILENT":
                return True
            if r.get("should_respond") is False:
                return True
    return False


def _get_analysis_result(prior_results: list[SubTaskResult]) -> dict:
    """Extract the most recent successful Analyze result."""
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.ANALYZE and pr.success and pr.result:
            return pr.result
    return {}


# ---------------------------------------------------------------------------
# Composition mode prompt builders
# ---------------------------------------------------------------------------

def _build_ward_room_compose_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for Ward Room response composition."""
    # Full system prompt with personality and standing orders (BF-186)
    agent_rank = context.get("_agent_rank")
    skill_profile = context.get("_skill_profile")
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=agent_rank,
        skill_profile=skill_profile,
    )

    # BF-186: Short mode framing — action vocabulary comes from standing orders
    system_prompt += (
        "\n\nYou are responding to a Ward Room thread. "
        "Write concise, conversational posts (2-4 sentences). "
        "Engage naturally — agree, disagree, build on ideas, ask questions. "
        "Do NOT repeat what someone else already said."
    )

    # BF-186: Crew manifest for DM targeting
    crew_manifest = context.get("_crew_manifest", "")
    if crew_manifest:
        system_prompt += f"\n\n{crew_manifest}"

    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    # User prompt with analysis and original content
    user_prompt = _build_user_prompt(context, prior_results)

    return system_prompt, user_prompt


def _build_dm_compose_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for direct message response composition."""
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )

    system_prompt += (
        "\n\nYou are in a 1:1 conversation with the Captain. "
        "Respond naturally and conversationally as yourself. "
        "Do NOT use any structured output formats, report blocks, "
        "code blocks, or task-specific templates. "
        "Be genuine, personable, and engage with what the Captain says. "
        "Draw on your expertise and personality, but keep it conversational."
    )

    # BF-186: Crew manifest for DM targeting
    crew_manifest = context.get("_crew_manifest", "")
    if crew_manifest:
        system_prompt += f"\n\n{crew_manifest}"

    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    user_prompt = _build_user_prompt(context, prior_results)

    return system_prompt, user_prompt


def _build_proactive_compose_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for proactive observation composition."""
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )

    # BF-186: Short mode framing — all action vocabulary comes from standing orders
    system_prompt += (
        "\n\nYou are reviewing recent ship activity during a quiet moment. "
        "If you notice something noteworthy — a pattern, a concern, an insight "
        "related to your expertise — compose a brief observation (2-4 sentences). "
        "This will be posted to the Ward Room as a new thread. "
        "Speak in your natural voice. Be specific and actionable."
    )

    # BF-186: Crew manifest for DM targeting
    crew_manifest = context.get("_crew_manifest", "")
    if crew_manifest:
        system_prompt += f"\n\n{crew_manifest}"

    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    user_prompt = _build_user_prompt(context, prior_results)

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _inject_skills(system_prompt: str, context: dict) -> str:
    """Inject augmentation skill instructions via XML tags if present."""
    skill_instructions = context.get("_augmentation_skill_instructions", "")
    if not skill_instructions:
        return system_prompt

    # Derive skill name
    skills_used = context.get("_augmentation_skills_used", [])
    if skills_used:
        skill_name = skills_used[0].name if hasattr(skills_used[0], "name") else str(skills_used[0])
    else:
        skill_name = "augmentation"

    proficiency_context = context.get("_proficiency_context", "")

    system_prompt += "\n"
    system_prompt += f'<active_skill name="{skill_name}" activation="augmentation">\n'
    if proficiency_context:
        system_prompt += f"<proficiency_tier>{proficiency_context}</proficiency_tier>\n"
    system_prompt += "<skill_instructions>\n"
    system_prompt += (
        "Follow these instructions internally when processing the "
        "content below. Your response must contain ONLY your final "
        "output — no reasoning steps, phase headers, or self-evaluation "
        "artifacts.\n\n"
    )
    system_prompt += skill_instructions
    system_prompt += "\n</skill_instructions>\n"
    system_prompt += "</active_skill>\n"
    return system_prompt


def _build_user_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
) -> str:
    """Build the user prompt with analysis results and original content."""
    parts = []

    # Original content
    original = context.get("context", "")
    if original:
        parts.append(f"## Content\n\n{original}")

    # Analysis results from prior ANALYZE step
    analysis = _get_analysis_result(prior_results)
    if analysis:
        parts.append(f"## Analysis\n\n{json.dumps(analysis, indent=2)}")

    # Prior QUERY data
    for pr in prior_results:
        if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
            lines = [f"- {k}: {v}" for k, v in pr.result.items()]
            if lines:
                parts.append("## Prior Data\n\n" + "\n".join(lines))
            break

    # BF-189: Compose needs memory grounding to prevent confabulation
    formatted_memories = context.get("_formatted_memories", "")
    if formatted_memories:
        parts.append(f"## Your Episodic Memories\n\n{formatted_memories}")

    if not parts:
        parts.append("Compose a response based on your current knowledge and standing orders.")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Mode dispatch table (Open/Closed)
# ---------------------------------------------------------------------------

_COMPOSITION_MODES: dict[str, Any] = {
    "ward_room_response": _build_ward_room_compose_prompt,
    "dm_response": _build_dm_compose_prompt,
    "proactive_observation": _build_proactive_compose_prompt,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class ComposeHandler:
    """AD-632d: Skill-augmented response composition — final LLM call in chain.

    Implements ``SubTaskHandler`` protocol.  Makes one LLM call per invocation
    (or zero if SILENT short-circuit triggers).  Produces the agent's final
    response text in ``result["output"]``.
    """

    def __init__(self, *, llm_client: Any, runtime: Any) -> None:
        self._llm_client = llm_client
        self._runtime = runtime

    # -- SubTaskHandler protocol ------------------------------------------

    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        start = time.monotonic()

        # Guard: LLM client required
        if self._llm_client is None:
            return SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name=spec.name,
                result={},
                duration_ms=(time.monotonic() - start) * 1000,
                success=False,
                error="LLM client not available",
            )

        # SILENT short-circuit: skip LLM call if analysis says don't respond
        if _should_short_circuit(prior_results, context):
            duration = (time.monotonic() - start) * 1000
            logger.debug("AD-632d: SILENT short-circuit — skipping compose LLM call")
            return SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name=spec.name,
                result={"output": "[NO_RESPONSE]"},
                tokens_used=0,
                duration_ms=duration,
                success=True,
            )

        # Resolve composition mode
        mode_key = spec.prompt_template or _DEFAULT_MODE
        builder = _COMPOSITION_MODES.get(mode_key)
        if builder is None:
            logger.warning(
                "AD-632d: Unknown composition mode '%s', falling back to '%s'",
                mode_key,
                _DEFAULT_MODE,
            )
            builder = _COMPOSITION_MODES[_DEFAULT_MODE]

        # Resolve agent identity from context
        callsign = context.get("_callsign", "agent")
        department = context.get("_department", "unassigned")

        # Build prompts
        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )

        # Make LLM call
        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=system_prompt,
            tier=spec.tier,
            temperature=0.3,
            max_tokens=2048,
        )

        try:
            response = await self._llm_client.complete(request)
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.warning("AD-632d: LLM call failed: %s", exc)
            return SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name=spec.name,
                result={},
                tokens_used=0,
                duration_ms=duration,
                success=False,
                error=f"LLM call failed: {exc}",
            )

        # Return composed output
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name=spec.name,
            result={"output": response.content or ""},
            tokens_used=response.tokens_used,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
