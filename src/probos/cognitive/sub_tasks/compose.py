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
from probos.cognitive.sub_tasks import AD646B_DEDICATED_KEYS
from probos.events import EventType
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
            # AD-643a: Also check intended_actions
            actions = r.get("intended_actions")
            if isinstance(actions, list) and actions == ["silent"]:
                return True
            if isinstance(actions, str) and actions.strip().lower() == "silent":
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

    # AD-649: Communication context and register adaptation
    _comm_context = context.get("_communication_context", "department_discussion")

    if _comm_context == "private_conversation":
        # BF-210: Name the conversation partner so the model
        # doesn't default to authority-frame formality.
        _dm_peer = context.get("_dm_recipient", "")
        _peer_label = f" with {_dm_peer}" if _dm_peer else ""
        system_prompt += (
            f"\n\nYou are in a private 1:1 conversation{_peer_label}. "
            "Be warm, conversational, and personal — like talking to a trusted colleague. "
            "Speak in your natural voice. Share your thoughts naturally, not as a report. "
            "Show your reasoning, ask follow-up questions, and draw on "
            "recent interactions and shared context. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret. "
            "Do NOT use structured formats, bold headers, or clinical language."
        )
    else:
        system_prompt += (
            "\n\nYou are responding to a Ward Room thread. "
            "Speak in your natural voice. Don't be formal unless the topic demands it. "
            "Write concise, conversational posts (2-4 sentences). "
            "Engage naturally — agree, disagree, build on ideas, ask questions. "
            "Show your reasoning, not just conclusions. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret. "
            "Prefer natural prose over markdown formatting. "
            "Use bold headers only for formal reports, not conversation. "
            "Do NOT repeat what someone else already said."
        )

        if _comm_context == "casual_social":
            system_prompt += (
                " This is the recreation channel — be relaxed, playful, and social."
            )
        elif _comm_context == "bridge_briefing":
            system_prompt += (
                " This is the bridge channel — be concise, strategic, and command-focused."
            )
        elif _comm_context == "ship_wide":
            system_prompt += (
                " This is a ship-wide channel — be measured and broadly relevant. "
                "Junior crew may act on what you say, so be clear about what is "
                "observation versus recommendation."
            )

    # BF-186: Crew manifest for DM targeting
    crew_manifest = context.get("_crew_manifest", "")
    if crew_manifest:
        system_prompt += f"\n\n{crew_manifest}"

    # Skill injection
    system_prompt = _inject_skills(system_prompt, context)

    # AD-653: "Speak freely" — trust-gated register override for thread responses
    analysis = _get_analysis_result(prior_results)
    intended = analysis.get("intended_actions", [])
    if isinstance(intended, list) and "speak_freely" in intended:
        _trust = context.get("_trust_score", 0.5)
        _emit = context.get("_emit_event_fn")
        _agent_id = context.get("_agent_id", "")

        if _trust >= 0.7:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED.** You flagged that the current "
                "register would constrain something important. For this response "
                "only, be direct and candid. Say what you actually think."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "to_register": "speak_freely",
                    "authorization": "auto",
                })
        elif _trust >= 0.4:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED (flagged for review).** For this "
                "response only, be direct and candid. This shift has been noted "
                "for Counselor review."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "to_register": "speak_freely",
                    "authorization": "flagged",
                })
        else:
            if _emit:
                _emit(EventType.REGISTER_SHIFT_DENIED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": context.get("_communication_context", "department_discussion"),
                    "reason": "trust_below_threshold",
                })

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

    # AD-649: Dynamic recipient awareness
    _recipient = context.get("_dm_recipient", "a crew member")
    system_prompt += (
        f"\n\nYou are in a 1:1 private conversation with {_recipient}. "
        "Respond naturally and conversationally as yourself. "
        "Do NOT use any structured output formats, report blocks, "
        "code blocks, or task-specific templates. "
        "Be genuine, personable, and engage with what they say. "
        "Share your reasoning and thought process, not just conclusions. "
        "If there's another way to see this, mention it briefly. "
        "Don't just summarize — interpret. "
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

    # AD-644 Phase 1: Duty-aware framing
    _active_duty = context.get("_active_duty")
    if _active_duty:
        _duty_desc = _active_duty.get("description", _active_duty.get("duty_id", "unknown"))
        system_prompt += (
            f"\n\n## Duty Report: {_duty_desc}\n\n"
            "You are performing a **scheduled duty**. This is not a casual observation — "
            "someone scheduled you to examine this area. You are obligated to report.\n\n"
            "**Format your response as a structured duty report:**\n"
            f"1. Start with a header: **Duty Report: {_duty_desc}**\n"
            "2. **Findings:** What you observed — cite specific metrics, counts, "
            "trends (improving/declining/stable), or notable events. Be evidence-based.\n"
            "3. **Assessment:** Your professional interpretation — what does this mean "
            "for the ship? Is this nominal, concerning, or noteworthy?\n"
            "4. **Recommendation:** If action is warranted, what should happen next? "
            "If nominal, say so explicitly — a null finding is valuable.\n\n"
            "Speak in your natural voice. Show your reasoning.\n"
            "A duty report saying 'nothing unusual — systems nominal' is better than "
            "silence. Silence during a duty cycle is dereliction.\n"
            "Do NOT respond with [NO_RESPONSE] during a duty cycle — report your findings, "
            "even if the finding is that everything is normal."
        )
    else:
        system_prompt += (
            "\n\nYou are reviewing recent ship activity during a quiet moment. "
            "If you notice something noteworthy — a pattern, a concern, an insight "
            "related to your expertise — act on it. You may compose a Ward Room "
            "observation (2-4 sentences), file an improvement proposal, reply to "
            "an existing thread, send a DM, or challenge a crewmate to a game. "
            "Refer to your standing orders for action tag syntax. "
            "Speak in your natural voice. Be specific and actionable. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret."
        )

    # AD-651a: Billet instruction — inject proposal format when analyze requests it
    analysis = _get_analysis_result(prior_results)
    intended = analysis.get("intended_actions", [])
    if isinstance(intended, list) and "proposal" in intended:
        system_prompt += (
            "\n\n**You decided to file an improvement proposal.** Use this exact format "
            "as a SEPARATE block AFTER your observation text:\n"
            "```\n"
            "[PROPOSAL]\n"
            "Title: <short descriptive title>\n"
            "Rationale: <why this matters and what it would improve — be specific, "
            "cite evidence from your analysis>\n"
            "Affected Systems: <comma-separated subsystem names>\n"
            "Priority: low|medium|high\n"
            "[/PROPOSAL]\n"
            "```\n"
            "The proposal will be automatically posted to the Improvement Proposals channel. "
            "Your observation text will also be posted normally to your department channel."
        )

    # AD-653: "Speak freely" — trust-gated register override
    if isinstance(intended, list) and "speak_freely" in intended:
        _trust = context.get("_trust_score", 0.5)
        _emit = context.get("_emit_event_fn")
        _agent_id = context.get("_agent_id", "")
        _comm_context = context.get("_communication_context", "department_discussion")

        if _trust >= 0.7:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED.** You flagged that formal register "
                "would constrain something important. For this response only, drop "
                "format requirements and speak in your natural voice. Be direct, "
                "candid, and honest. Say what you actually think, not what protocol "
                "demands. This is temporary — your next response returns to normal "
                "register."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "to_register": "speak_freely",
                    "authorization": "auto",
                })
        elif _trust >= 0.4:
            system_prompt += (
                "\n\n**SPEAK FREELY — GRANTED (flagged for review).** You flagged "
                "that formal register would constrain something important. For this "
                "response only, drop format requirements and speak candidly. This "
                "shift has been noted for Counselor review."
            )
            if _emit:
                _emit(EventType.REGISTER_SHIFT_GRANTED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "to_register": "speak_freely",
                    "authorization": "flagged",
                })
        else:
            if _emit:
                _emit(EventType.REGISTER_SHIFT_DENIED, {
                    "agent_id": _agent_id,
                    "trust": _trust,
                    "from_register": _comm_context,
                    "reason": "trust_below_threshold",
                })

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

    # AD-645: Composition brief from ANALYZE step
    analysis = _get_analysis_result(prior_results)
    if analysis:
        brief = analysis.get("composition_brief")
        if brief and isinstance(brief, dict):
            brief_parts = ["## Composition Brief\n"]
            _situation = brief.get("situation", "")
            if _situation:
                brief_parts.append(f"**Situation:** {_situation}\n")
            _evidence = brief.get("key_evidence")
            if _evidence and isinstance(_evidence, list):
                brief_parts.append("**Key Evidence:**")
                for item in _evidence:
                    brief_parts.append(f"- {item}")
                brief_parts.append("")
            _cover = brief.get("response_should_cover")
            if _cover and isinstance(_cover, list):
                brief_parts.append("**Your response should cover:**")
                for item in _cover:
                    brief_parts.append(f"- {item}")
                brief_parts.append("")
            _tone = brief.get("tone", "")
            if _tone:
                brief_parts.append(f"**Tone:** {_tone}\n")
            _sources = brief.get("sources_to_draw_on", "")
            if _sources:
                brief_parts.append(f"**Sources to draw on:** {_sources}\n")
            parts.append("\n".join(brief_parts))

            # AD-650: Narrative reasoning from ANALYZE
            _reasoning = brief.get("analytical_reasoning", "")
            if _reasoning:
                parts.append(f"\n## Analytical Reasoning\n{_reasoning}")
        else:
            # Fallback: no brief, render analysis as before (backward compat)
            parts.append(f"## Analysis\n\n{json.dumps(analysis, indent=2)}")

    # Prior QUERY data (exclude keys with dedicated rendering)
    for pr in prior_results:
        if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
            lines = [f"- {k}: {v}" for k, v in pr.result.items() if k not in AD646B_DEDICATED_KEYS]
            if lines:
                parts.append("## Prior Data\n\n" + "\n".join(lines))
            break

    # AD-646b: Self-monitoring and telemetry from QUERY results
    for pr in prior_results:
        if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
            _sm = pr.result.get("self_monitoring", "")
            if _sm:
                parts.append(f"## Self-Monitoring\n\n{_sm}")
            _telemetry = pr.result.get("introspective_telemetry", "")
            if _telemetry:
                parts.append(_telemetry)
            break

    # BF-189: Compose needs memory grounding to prevent confabulation
    formatted_memories = context.get("_formatted_memories", "")
    if formatted_memories:
        parts.append(f"## Your Episodic Memories\n\n{formatted_memories}")

    # AD-644 Phase 1: Agent metrics for self-awareness in composition
    _agent_metrics = context.get("_agent_metrics", "")
    if _agent_metrics:
        parts.append(f"## Your Status\n\n{_agent_metrics}")

    # AD-644 Phase 2: Confabulation guard — critical for compose quality
    _confab_guard = context.get("_confabulation_guard", "")
    if _confab_guard:
        parts.append(f"## Knowledge Boundaries\n\n{_confab_guard}")
    _no_memories = context.get("_no_episodic_memories", "")
    if _no_memories:
        parts.append(_no_memories)

    # AD-644 Phase 2: Source attribution — compose needs source awareness
    _source_attr = context.get("_source_attribution_text", "")
    if _source_attr:
        parts.append(_source_attr)

    # AD-646b: Oracle context — cross-tier knowledge for compose
    _oracle = context.get("_oracle_context", "")
    if _oracle:
        parts.append(
            "## Cross-Tier Knowledge (Ship's Records)\n\n"
            "These are NOT your personal experiences. They are from the ship's shared "
            "knowledge stores. Treat as reference material, not memory.\n\n"
            + _oracle
        )

    # AD-646b: Self-recognition cue
    _self_cue = context.get("_self_recognition_cue", "")
    if _self_cue:
        parts.append(_self_cue)

    # AD-644 Phase 2: Communication proficiency — tier-specific guidance
    _comm_prof = context.get("_comm_proficiency", "")
    if _comm_prof:
        parts.append(f"## Communication Guidance\n\n{_comm_prof}")

    # AD-644 Phase 2: Temporal context — compose needs time awareness
    _temporal = context.get("_temporal_context", "")
    if _temporal:
        parts.append(f"## Temporal Awareness\n\n{_temporal}")

    # AD-644 Phase 2: Ontology — compose needs identity for voice consistency
    _ontology = context.get("_ontology_context", "")
    if _ontology:
        parts.append(f"## Your Identity\n\n{_ontology}")

    # AD-645: Environmental situation awareness — COMPOSE needs raw material
    # to draw on alongside the composition brief. These keys already flow
    # to ANALYZE (AD-644 Phase 3); now COMPOSE has them too.
    _ward_room = context.get("_ward_room_activity", "")
    if _ward_room:
        parts.append(f"## Recent Ward Room Activity\n\n{_ward_room}")

    _alerts = context.get("_recent_alerts", "")
    if _alerts:
        parts.append(f"## Recent Alerts\n\n{_alerts}")

    _events = context.get("_recent_events", "")
    if _events:
        parts.append(f"## Recent Events\n\n{_events}")

    _infra = context.get("_infrastructure_status", "")
    if _infra:
        parts.append(f"## Infrastructure Status\n\n{_infra}")

    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        parts.append(f"## Subordinate Activity\n\n{_sub_stats}")

    _cold_start = context.get("_cold_start_note", "")
    if _cold_start:
        parts.append(_cold_start)

    _game = context.get("_active_game", "")
    if _game:
        parts.append(f"## Active Game\n\n{_game}")

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
