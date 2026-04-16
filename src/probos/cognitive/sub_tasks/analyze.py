"""AD-632c: Analyze Sub-Task Handler — Focused LLM comprehension.

Performs narrow, structured analysis of content (thread, situation, DM)
via a single LLM call.  Part of Level 3 cognitive escalation
(Query → **Analyze** → Compose).

The handler does NOT compose responses, emit actions, or enforce skill
instructions — that's the Compose handler (AD-632d).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.cognitive.standing_orders import compose_instructions
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Analysis mode prompt builders
# ---------------------------------------------------------------------------

_MAX_ERROR_CONTENT = 200  # Truncate LLM content in error messages


def _build_thread_analysis_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for Ward Room thread comprehension."""
    # BF-186: Full standing orders context for better SILENT/RESPOND decisions
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )
    system_prompt += (
        "\n\nYour task is to ANALYZE the following content. Do NOT compose a response.\n"
        "Do NOT suggest what to say. Only analyze what has been said and identify\n"
        "what is relevant to your department's expertise.\n\n"
        "Respond with a JSON object containing your structured analysis. No\n"
        "conversational text outside the JSON block."
    )

    # Thread content
    thread_content = context.get("context", "")

    # Build context section from prior QUERY results
    context_section = ""
    for pr in prior_results:
        if pr.success and pr.result:
            lines = []
            for k, v in pr.result.items():
                lines.append(f"- {k}: {v}")
            if lines:
                context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
            break  # Use first successful prior result

    # Episodic memories if present
    memories = context.get("recent_memories", "")
    memory_section = ""
    if memories:
        memory_section = f"## Relevant Memories\n\n{memories}\n\n"

    user_prompt = (
        f"## Thread Content\n\n{thread_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        f"## Analysis Required\n\n"
        f"Analyze this thread from your department's perspective ({department}):\n\n"
        f"1. **topics_covered**: List each post's core claim or contribution (one\n"
        f"   sentence per post). Include the author callsign.\n"
        f"2. **novel_posts**: Which posts contain genuinely NEW information vs\n"
        f"   restating what others said? List post indices or author callsigns.\n"
        f"3. **gaps**: What has NOT been addressed that your department ({department})\n"
        f"   could contribute? Be specific — what analysis, data, or perspective\n"
        f"   is missing?\n"
        f"4. **endorsement_candidates**: Which posts are strong, novel contributions\n"
        f"   worth endorsing? List callsigns. Empty list if none qualify.\n"
        f"5. **contribution_assessment**: One of: \"RESPOND\" (you have something new\n"
        f"   to add), \"ENDORSE\" (agree with existing analysis, nothing new), or\n"
        f"   \"SILENT\" (topic outside your scope or fully covered).\n\n"
        f"Return a JSON object with these 5 keys. No other text."
    )
    return system_prompt, user_prompt


def _build_situation_review_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for proactive situation assessment."""
    # BF-186: Full standing orders context
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )
    system_prompt += (
        "\n\nYour task is to ASSESS the current situation. Do NOT compose a response.\n"
        "Do NOT suggest what to say. Only analyze what is happening and identify\n"
        "priorities relevant to your department.\n\n"
        "Respond with a JSON object containing your structured analysis. No\n"
        "conversational text outside the JSON block."
    )

    situation_content = context.get("context", "")

    context_section = ""
    for pr in prior_results:
        if pr.success and pr.result:
            lines = [f"- {k}: {v}" for k, v in pr.result.items()]
            if lines:
                context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
            break

    user_prompt = (
        f"## Current Situation\n\n{situation_content}\n\n"
        f"{context_section}"
        "## Assessment Required\n\n"
        f"From your department's perspective ({department}), assess:\n\n"
        "1. **active_threads**: List active discussion threads requiring attention.\n"
        "2. **pending_actions**: Actions you need to take or respond to.\n"
        "3. **priority_topics**: Topics ranked by departmental relevance.\n"
        "4. **department_relevance**: How relevant is the current situation to your "
        f"department ({department})? One of: \"HIGH\", \"MEDIUM\", \"LOW\".\n\n"
        "Return a JSON object with these 4 keys. No other text."
    )
    return system_prompt, user_prompt


def _build_dm_comprehension_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for direct message understanding."""
    # BF-186: Full standing orders context
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )
    system_prompt += (
        "\n\nYour task is to UNDERSTAND the following direct message. Do NOT compose\n"
        "a reply. Only analyze the sender's intent and identify what is being asked.\n\n"
        "Respond with a JSON object containing your structured analysis. No\n"
        "conversational text outside the JSON block."
    )

    dm_content = context.get("context", "")

    context_section = ""
    for pr in prior_results:
        if pr.success and pr.result:
            lines = [f"- {k}: {v}" for k, v in pr.result.items()]
            if lines:
                context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
            break

    user_prompt = (
        f"## Direct Message\n\n{dm_content}\n\n"
        f"{context_section}"
        "## Comprehension Required\n\n"
        "Analyze this direct message:\n\n"
        "1. **sender_intent**: What is the sender trying to accomplish?\n"
        "2. **key_questions**: List specific questions being asked.\n"
        "3. **required_actions**: What actions are expected of you?\n"
        "4. **emotional_tone**: The sender's emotional tone (neutral, urgent, "
        "appreciative, concerned, etc.).\n\n"
        "Return a JSON object with these 4 keys. No other text."
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Mode dispatch table (Open/Closed)
# ---------------------------------------------------------------------------

PromptBuilder = type(_build_thread_analysis_prompt)

_ANALYSIS_MODES: dict[str, Any] = {
    "thread_analysis": _build_thread_analysis_prompt,
    "situation_review": _build_situation_review_prompt,
    "dm_comprehension": _build_dm_comprehension_prompt,
}

_DEFAULT_MODE = "thread_analysis"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class AnalyzeHandler:
    """AD-632c: Focused LLM comprehension — analysis without response composition.

    Implements ``SubTaskHandler`` protocol.  Makes exactly one LLM call per
    invocation, produces structured JSON analysis.
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
                sub_task_type=SubTaskType.ANALYZE,
                name=spec.name,
                result={},
                duration_ms=(time.monotonic() - start) * 1000,
                success=False,
                error="LLM client not available",
            )

        # Resolve analysis mode
        mode_key = spec.prompt_template or _DEFAULT_MODE
        builder = _ANALYSIS_MODES.get(mode_key)
        if builder is None:
            logger.warning(
                "AD-632c: Unknown analysis mode '%s', falling back to '%s'",
                mode_key,
                _DEFAULT_MODE,
            )
            builder = _ANALYSIS_MODES[_DEFAULT_MODE]

        # Resolve agent identity from context (injected by _execute_sub_task_chain)
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
            temperature=0.0,
            max_tokens=1024,
        )

        try:
            response = await self._llm_client.complete(request)
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.warning("AD-632c: LLM call failed: %s", exc)
            return SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name=spec.name,
                result={},
                tokens_used=0,
                duration_ms=duration,
                success=False,
                error=f"LLM call failed: {exc}",
            )

        # Parse structured JSON from response
        try:
            analysis = extract_json(response.content)
        except (ValueError, TypeError):
            duration = (time.monotonic() - start) * 1000
            truncated = (response.content or "")[:_MAX_ERROR_CONTENT]
            logger.warning(
                "AD-632c: JSON parse failure, content: %s", truncated,
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name=spec.name,
                result={},
                tokens_used=response.tokens_used,
                duration_ms=duration,
                success=False,
                error=f"Failed to parse analysis JSON from LLM response: {truncated}",
                tier_used=response.tier,
            )

        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name=spec.name,
            result=analysis,
            tokens_used=response.tokens_used,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
