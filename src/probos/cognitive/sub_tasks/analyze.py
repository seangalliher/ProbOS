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

from probos.cognitive.standing_orders import get_step_instructions
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# AD-646b: Import from parent package — constant is defined before handler imports
# to avoid circular dependency.
from probos.cognitive.sub_tasks import AD646B_DEDICATED_KEYS

# ---------------------------------------------------------------------------
# Analysis mode prompt builders
# ---------------------------------------------------------------------------

_MAX_ERROR_CONTENT = 200  # Truncate LLM content in error messages


def _format_trigger_awareness(context: dict) -> str:
    """AD-643b: Format eligible triggers for ANALYZE prompt injection."""
    eligible = context.get("_eligible_triggers")
    if not eligible:
        return ""
    lines = []
    for tag, skills in sorted(eligible.items()):
        skill_names = ", ".join(skills)
        lines.append(f"   - {tag} \u2192 loads: {skill_names}")
    return (
        "   Declare ALL actions you plan to take so quality skills load:\n"
        + "\n".join(lines) + "\n"
    )


def _build_thread_analysis_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
    """Build system + user prompts for Ward Room thread comprehension."""
    # BF-186: Full standing orders context for better SILENT/RESPOND decisions
    system_prompt = get_step_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        step_name="analyze",
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
                if k not in AD646B_DEDICATED_KEYS:
                    lines.append(f"- {k}: {v}")
            if lines:
                context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
            break  # Use first successful prior result

    # BF-189: Use pre-formatted memory text (AD-567b/568c/592 compliant)
    formatted_memories = context.get("_formatted_memories", "")
    memory_section = ""
    if formatted_memories:
        memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"

    # AD-646: Universal baseline keys — agent self-knowledge
    agent_state_parts = []

    _temporal = context.get("_temporal_context", "")
    if _temporal:
        agent_state_parts.append(f"**Temporal:** {_temporal}")

    _wm = context.get("_working_memory_context", "")
    if _wm:
        agent_state_parts.append(f"**Working Memory:**\n{_wm}")

    _metrics = context.get("_agent_metrics", "")
    if _metrics:
        agent_state_parts.append(f"**Status:** {_metrics}")

    _ontology = context.get("_ontology_context", "")
    if _ontology:
        agent_state_parts.append(f"**Identity:** {_ontology}")

    _source_attr = context.get("_source_attribution_text", "")
    if _source_attr:
        agent_state_parts.append(_source_attr)

    _confab = context.get("_confabulation_guard", "")
    if _confab:
        agent_state_parts.append(_confab)

    agent_state_section = ""
    if agent_state_parts:
        agent_state_section = "## Your Current State\n\n" + "\n\n".join(agent_state_parts) + "\n\n"

    # AD-646b: Oracle context — cross-tier knowledge grounding
    oracle_section = ""
    _oracle = context.get("_oracle_context", "")
    if _oracle:
        oracle_section = (
            "## Cross-Tier Knowledge (Ship's Records)\n\n"
            "These are NOT your personal experiences. They are from the ship's shared "
            "knowledge stores. Treat as reference material, not memory.\n\n"
            f"{_oracle}\n\n"
        )

    # AD-646b: Self-recognition cue
    _self_cue = context.get("_self_recognition_cue", "")

    # AD-646b: Self-monitoring and telemetry from QUERY results
    self_monitoring_section = ""
    for pr in prior_results:
        if pr.success and pr.result:
            _sm = pr.result.get("self_monitoring", "")
            if _sm:
                self_monitoring_section = f"## Self-Monitoring\n\n{_sm}\n\n"
            _telemetry = pr.result.get("introspective_telemetry", "")
            if _telemetry:
                self_monitoring_section += f"{_telemetry}\n\n"
            break

    user_prompt = (
        f"## Thread Content\n\n{thread_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        f"{agent_state_section}"
        f"{oracle_section}"
        f"{self_monitoring_section}"
        + (f"{_self_cue}\n\n" if _self_cue else "")
        + f"## Analysis Required\n\n"
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
        f"   \"SILENT\" (topic outside your scope or fully covered).\n"
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent, speak_freely.\n"
        f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
        f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
        f"   Add \"speak_freely\" if you have something important to communicate\n"
        f"   that the expected format would constrain or dilute — a candid\n"
        f"   assessment, a concern that formal structure would flatten, or a\n"
        f"   personal insight that matters more than protocol compliance.\n"
        f"   speak_freely is additive: [\"ward_room_reply\", \"speak_freely\"].\n"
        f"7. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"
        f"   - **situation**: What is being discussed? (1-2 sentences)\n"
        f"   - **key_evidence**: Specific findings, metrics, or conclusions — not just\n"
        f"     activities. Not 'I talked to Wesley' but 'Wesley showed X pattern that\n"
        f"     resolved after Y'. Cite numbers, trajectories, and causal chains.\n"
        f"   - **response_should_cover**: What your reply needs to address.\n"
        f"   - **tone**: How should the reply be framed? Consider the communication\n"
        f"     context: {context.get('_communication_context', 'department_discussion')}.\n"
        f"     Private conversations are warm and exploratory. Bridge briefings are\n"
        f"     concise and strategic. Department discussions are collegial and\n"
        f"     technically specific. Recreation is casual and playful. Ship-wide\n"
        f"     posts are measured and broadly relevant.\n"
        f"     Include your reasoning process, not just conclusions.\n"
        f"   - **sources_to_draw_on**: Which knowledge sources are relevant.\n"
        f"   - **analytical_reasoning**: Your thinking about this situation in 2-3\n"
        f"     sentences. What does this mean beyond the surface? What's the\n"
        f"     counterargument or alternative perspective? What would a thoughtful\n"
        f"     colleague notice that a summary would miss? Write as narrative prose,\n"
        f"     not bullets.\n"
        f"   If contribution_assessment is \"SILENT\", composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 7 keys. No other text."
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
    system_prompt = get_step_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        step_name="analyze",
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

    # AD-644 Phase 3: Build situation content from environmental perception keys.
    # For proactive_think, context.get("context") is empty — all dynamic data
    # arrives via observation dict keys populated from context_parts.
    situation_parts: list[str] = []

    # Original context (non-empty for ward_room_notification, empty for proactive_think)
    _raw_context = context.get("context", "")
    if _raw_context:
        situation_parts.append(_raw_context)

    # Cold-start note (BF-034)
    _cold_start = context.get("_cold_start_note", "")
    if _cold_start:
        situation_parts.append(_cold_start)

    # Infrastructure status (AD-576)
    _infra = context.get("_infrastructure_status", "")
    if _infra:
        situation_parts.append(_infra)

    # Ward Room activity (AD-413)
    _wr_activity = context.get("_ward_room_activity", "")
    if _wr_activity:
        situation_parts.append(_wr_activity)

    # Recent alerts
    _alerts = context.get("_recent_alerts", "")
    if _alerts:
        situation_parts.append(_alerts)

    # Recent events
    _events = context.get("_recent_events", "")
    if _events:
        situation_parts.append(_events)

    # Subordinate stats (AD-630) — Chiefs
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        situation_parts.append(_sub_stats)

    # Active game (BF-110)
    _game = context.get("_active_game", "")
    if _game:
        situation_parts.append(f"--- Active Game ---\n{_game}")

    situation_content = "\n\n".join(situation_parts) if situation_parts else ""

    context_section = ""
    for pr in prior_results:
        if pr.success and pr.result:
            lines = [f"- {k}: {v}" for k, v in pr.result.items()]
            if lines:
                context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
            break

    # BF-189: Situation review needs memory for context
    formatted_memories = context.get("_formatted_memories", "")
    memory_section = ""
    if formatted_memories:
        memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"

    # AD-644 Phase 1: Duty context + agent metrics
    _active_duty = context.get("_active_duty")
    _agent_metrics = context.get("_agent_metrics", "")

    duty_section = ""
    if _active_duty:
        _duty_desc = _active_duty.get("description", _active_duty.get("duty_id", "unknown"))
        duty_section = (
            f"## Active Duty\n\n"
            f"[Duty Cycle: {_duty_desc}]\n"
            f"{_agent_metrics}\n\n"
            f"This is a scheduled duty. Assess your area of responsibility and "
            f"report your findings.\n\n"
        )
    else:
        duty_section = (
            f"## Proactive Review — No Scheduled Duty\n\n"
            f"{_agent_metrics}\n\n"
            f"You have no scheduled duty at this time. Assess the situation and "
            f"decide what action, if any, is warranted. Options include posting an "
            f"observation, filing a proposal, replying to a thread, sending a DM, "
            f"challenging a crewmate to a game, or staying silent. "
            f"Do not post vague observations — if you act, be specific and actionable. "
            f"If nothing warrants action, [NO_RESPONSE] is appropriate.\n\n"
        )

    # AD-644 Phase 2: Innate faculties section
    innate_parts: list[str] = []

    # Temporal awareness
    _temporal = context.get("_temporal_context", "")
    if _temporal:
        innate_parts.append(f"## Temporal Awareness\n\n{_temporal}")

    # Working memory
    _wm = context.get("_working_memory_context", "")
    if _wm:
        innate_parts.append(f"## Working Memory\n\n{_wm}")

    # Ontology identity
    _ontology = context.get("_ontology_context", "")
    if _ontology:
        innate_parts.append(f"## Your Identity\n\n{_ontology}")

    # Orientation supplement
    _orient = context.get("_orientation_supplement", "")
    if _orient:
        innate_parts.append(f"## Orientation\n\n{_orient}")

    # Self-monitoring
    _self_mon = context.get("_self_monitoring", "")
    if _self_mon:
        innate_parts.append(f"## Self-Monitoring\n\n<recent_activity>\n{_self_mon}\n</recent_activity>")

    # Introspective telemetry
    _telemetry = context.get("_introspective_telemetry", "")
    if _telemetry:
        innate_parts.append(f"## Telemetry\n\n{_telemetry}")

    # Source attribution
    _source_attr = context.get("_source_attribution_text", "")
    if _source_attr:
        innate_parts.append(_source_attr)

    innate_section = "\n\n".join(innate_parts) + "\n\n" if innate_parts else ""

    user_prompt = (
        f"{duty_section}"
        f"{innate_section}"
        f"## Current Situation\n\n{situation_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        "## Assessment Required\n\n"
        f"From your department's perspective ({department}), assess:\n\n"
        "1. **active_threads**: List active discussion threads requiring attention.\n"
        "2. **pending_actions**: Actions you need to take or respond to.\n"
        "3. **priority_topics**: Topics ranked by departmental relevance.\n"
        "4. **department_relevance**: How relevant is the current situation to your "
        f"department ({department})? One of: \"HIGH\", \"MEDIUM\", \"LOW\".\n"
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent, speak_freely. Include ALL that apply.\n"
        "   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
        "   Add \"speak_freely\" if you have something important to communicate\n"
        "   that the expected format would constrain or dilute — a candid\n"
        "   assessment, a concern that formal structure would flatten, or a\n"
        "   personal insight that matters more than protocol compliance.\n"
        "   speak_freely is additive: [\"ward_room_post\", \"speak_freely\"].\n"
        "6. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"
        "   - **situation**: What is happening? (1-2 sentences)\n"
        "   - **key_evidence**: Specific findings, metrics, or diagnostic conclusions\n"
        "     from the situation data — not activity summaries. Cite numbers (counts,\n"
        "     scores, percentages), temporal changes (improving/declining/stable), and\n"
        "     causal chains (X happened because Y). 'Talked to crew' is useless;\n"
        "     '3 agents in AMBER zone, trust trending down 0.72→0.65' is evidence.\n"
        "   - **response_should_cover**: What your response needs to address (bullet list).\n"
        f"   - **tone**: How should the response be framed? Consider the communication\n"
        f"     context: {context.get('_communication_context', 'department_discussion')}.\n"
        f"     Private conversations are warm and exploratory. Bridge briefings are\n"
        f"     concise and strategic. Department discussions are collegial and\n"
        f"     technically specific. Recreation is casual and playful. Ship-wide\n"
        f"     posts are measured and broadly relevant.\n"
        f"     Include your reasoning process, not just conclusions.\n"
        "   - **sources_to_draw_on**: Which knowledge sources are relevant (episodic\n"
        "     memories, Ward Room observations, duty data, training knowledge).\n"
        "   - **analytical_reasoning**: Your thinking about this situation in 2-3\n"
        "     sentences. What does this mean beyond the surface? What's the\n"
        "     counterargument or alternative perspective? What would a thoughtful\n"
        "     colleague notice that a summary would miss? Write as narrative prose,\n"
        "     not bullets.\n"
        "   If intended_actions is [\"silent\"], composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 6 keys. No other text."
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
    system_prompt = get_step_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        step_name="analyze",
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

    # BF-189: DM analysis needs memory for grounding (prevents confabulation)
    formatted_memories = context.get("_formatted_memories", "")
    memory_section = ""
    if formatted_memories:
        memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"

    user_prompt = (
        f"## Direct Message\n\n{dm_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        "## Comprehension Required\n\n"
        "Analyze this direct message:\n\n"
        "1. **sender_intent**: What is the sender trying to accomplish?\n"
        "2. **key_questions**: List specific questions being asked.\n"
        "3. **required_actions**: What actions are expected of you?\n"
        "4. **emotional_tone**: The sender's emotional tone (neutral, urgent, "
        "appreciative, concerned, etc.).\n"
        "5. **composition_brief**: Your analytical reasoning and composition plan. Include:\n"
        "   - **situation**: What is the sender asking/discussing? (1-2 sentences)\n"
        "   - **key_evidence**: Specific findings or conclusions you should reference —\n"
        "     not 'I have memories of X' but what those memories revealed. Cite metrics,\n"
        "     behavioral patterns, and diagnostic conclusions.\n"
        "   - **response_should_cover**: What your reply needs to address.\n"
        "   - **tone**: How should you respond given the emotional_tone and your\n"
        "     relationship with the sender?\n"
        f"   - **register**: This is a {context.get('_communication_context', 'private_conversation')}.\n"
        f"     Be warm, conversational, and exploratory. Share reasoning, not just\n"
        f"     conclusions. Engage as a trusted colleague, not a reporting system.\n"
        "   - **sources_to_draw_on**: Which knowledge sources are relevant.\n"
        "   - **analytical_reasoning**: Your thinking about this situation in 2-3\n"
        "     sentences. What does this mean beyond the surface? What's the\n"
        "     counterargument or alternative perspective? What would a thoughtful\n"
        "     colleague notice that a summary would miss? Write as narrative prose,\n"
        "     not bullets.\n\n"
        "Return a JSON object with these 5 keys. No other text."
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
            max_tokens=1536,
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
