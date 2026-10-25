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

from probos.cognitive.output_grounding import (
    PATH_CHAIN,
    deterministic_rejection,
    intent_entity_ids,
    log_rejection,
    shown_hex_runs,
)
from probos.cognitive.sub_task import (
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
    resolve_chain_priority,
)
from probos.cognitive.sub_tasks.compose import composer_world_text
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
# AD-645b: Composition brief alignment helpers (Phase 4)
# ---------------------------------------------------------------------------

def _get_composition_brief(prior_results: list[SubTaskResult]) -> dict | None:
    """Extract the composition_brief from the most recent successful Analyze.

    AD-645 Phase 1 schema (analyze.py:184/:383/:462). Returns ``None`` when
    the brief is absent (legacy traces, SILENT contribution, or chains
    without AD-645 Phase 1). Returns ``None`` if the field is present but
    not a dict (defensive against malformed LLM output).
    """
    analysis = _get_analysis_result(prior_results)
    brief = analysis.get("composition_brief") if analysis else None
    if not brief or not isinstance(brief, dict):
        return None
    return brief


_BRIEF_FIELDS_RENDERED: tuple[str, ...] = (
    "situation",
    "key_evidence",
    "response_should_cover",
    "tone",
    "sources_to_draw_on",
)


def _render_brief_for_eval(brief: dict) -> str:
    """Render the composition brief as a Markdown block for the eval LLM.

    Intentionally renders only the five fields most directly assessable
    against the response (situation, key_evidence, response_should_cover,
    tone, sources_to_draw_on). ``analytical_reasoning`` is the agent's
    own narrative reasoning and is not graded against the response.
    """
    parts: list[str] = ["## Composition Brief", ""]
    for key in _BRIEF_FIELDS_RENDERED:
        value = brief.get(key)
        if value is None or value == "" or value == []:
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            parts.append(f"**{label}:**")
            for item in value:
                parts.append(f"- {item}")
            parts.append("")
        else:
            parts.append(f"**{label}:** {value}")
            parts.append("")
    return "\n".join(parts).rstrip()


_BRIEF_ALIGNMENT_CRITERION_TEXT: str = (
    "**Brief alignment** \u2014 Did the response cover what the brief said it "
    "should cover, use the brief's key_evidence, and match the brief's tone? "
    "Score along three sub-dimensions: covered_topics (response addresses each "
    "item in response_should_cover), used_evidence (response references at "
    "least one item from key_evidence), matched_tone (response register fits "
    "the brief's tone guidance). This criterion is informational; do NOT use "
    "it to gate pass/fail on its own.\n"
)


_BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT: str = (
    ', "brief_alignment": {"pass": true/false, "score": 0.0-1.0, '
    '"reason": "...", "dimensions": {"covered_topics": 0.0-1.0, '
    '"used_evidence": 0.0-1.0, "matched_tone": 0.0-1.0}}'
)


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

    # AD-645b: Brief alignment criterion (Phase 4) — appended only when a
    # composition brief is available. Numbering after voice (if present).
    brief = _get_composition_brief(prior_results)
    if brief is not None:
        idx = 7 if trust_band == "mid" else 6
        criteria += f"{idx}. " + _BRIEF_ALIGNMENT_CRITERION_TEXT

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
    if brief is not None:
        system_prompt += _BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )

    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_parts: list[str] = [
        "## Draft Response to Evaluate",
        "",
        compose_output,
        "",
    ]
    # AD-645b: Render the brief explicitly so the eval LLM can compare
    # response-against-plan when scoring brief_alignment.
    if brief is not None:
        user_parts.append(_render_brief_for_eval(brief))
        user_parts.append("")
    user_parts.extend([
        "## Analysis That Informed This Draft",
        "",
        json.dumps(analysis, indent=2),
        "",
        "## Original Content",
        "",
        original,
    ])
    user_prompt = "\n".join(user_parts)

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

    # AD-645b: Brief alignment criterion (Phase 4)
    brief = _get_composition_brief(prior_results)
    if brief is not None:
        idx = 7 if trust_band == "mid" else 6
        criteria += f"{idx}. " + _BRIEF_ALIGNMENT_CRITERION_TEXT

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
    if brief is not None:
        system_prompt += _BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT
    system_prompt += (
        '}, "recommendation": "approve"|"revise"|"suppress"}'
    )

    compose_output = _get_compose_output(prior_results)
    analysis = _get_analysis_result(prior_results)
    original = context.get("context", "")

    user_parts: list[str] = [
        "## Draft Response to Evaluate",
        "",
        compose_output,
        "",
    ]
    if brief is not None:
        user_parts.append(_render_brief_for_eval(brief))
        user_parts.append("")
    user_parts.extend([
        "## Analysis That Informed This Draft",
        "",
        json.dumps(analysis, indent=2),
        "",
        "## Original Content",
        "",
        original,
    ])
    user_prompt = "\n".join(user_parts)

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

        # AD-655 + AD-656: optional contrastive recall + department-specific
        # cognitive profile modulation. Both are best-effort and never raise
        # (Wave-5 tier-2 log-and-degrade).
        rt = self._runtime
        if rt is not None:
            try:
                # AD-656: department-specific recall depth override (if profile wired)
                _recall_depth = 2  # AD-655 default k
                _dept_profiles_cfg = None
                cfg_obj = getattr(rt, "config", None)
                if cfg_obj is not None:
                    _dept_profiles_cfg = getattr(cfg_obj, "dept_profiles", None)
                if _dept_profiles_cfg is not None and department:
                    _profile = _dept_profiles_cfg.profiles.get(department)
                    if _profile is not None:
                        _recall_depth = max(1, min(20, int(_profile.recall_depth)))
                        try:
                            from probos.events import EventType as _ET
                            _emit = getattr(rt, "emit_event", None)
                            if _emit is not None:
                                _emit(
                                    _ET.DEPT_PROFILE_APPLIED,
                                    {
                                        "department": department,
                                        "recall_depth": _recall_depth,
                                        "recall_threshold": _profile.recall_threshold,
                                    },
                                )
                        except Exception:
                            logger.debug(
                                "AD-656: DEPT_PROFILE_APPLIED emit failed",
                                exc_info=True,
                            )

                # AD-655: contrastive recall when episodic memory is wired
                em = getattr(rt, "episodic_memory", None)
                if em is not None and hasattr(em, "retrieve_contrastive_episodes"):
                    _query = context.get("context", "") or ""
                    if _query.strip():
                        _contrastive = await em.retrieve_contrastive_episodes(
                            _query, k=_recall_depth,
                        )
                        if _contrastive:
                            context["_contrastive_priors"] = [
                                {
                                    "id": getattr(ep, "id", ""),
                                    "user_input": getattr(ep, "user_input", ""),
                                }
                                for ep in _contrastive
                            ]
            except Exception:
                logger.debug(
                    "AD-655/AD-656: contrastive/profile hook failed",
                    exc_info=True,
                )

        # === SAFETY CHECKS (always run, 0 tokens) ===

        # BF-191 + BF-204, shared with the single-call fallback (BF-922, #1639).
        # Runs at ALL trust bands, even social obligation. Safety > obligation.
        # BF-204 grounds on what COMPOSE was given from outside the chain's model
        # calls (not the ANALYZE result: an id an earlier step invented is not
        # grounded by being repeated) and on the intent's own ids (BF-233).
        compose_output = _get_compose_output(prior_results)
        _shown = shown_hex_runs(composer_world_text(context, prior_results), *intent_entity_ids(context))
        rejection = deterministic_rejection(compose_output, _shown)
        if rejection is not None:
            log_rejection(
                rejection,
                compose_output,
                agent_type=context.get("_agent_type", "unknown"),
                agent_id=context.get("_agent_id", ""),
                callsign=context.get("_callsign", ""),
                path=PATH_CHAIN,
            )
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result=rejection.as_evaluate_result(),
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
            response = await self._llm_client.complete(
                request, priority=resolve_chain_priority(context),  # BF-688
            )
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

        # BF-901 (#1575): what this call is charged and the model that answered; both results below carry them.
        from probos.cognitive.token_accounting import (
            answered_model_name,
            charge_completion,
            request_messages,
        )

        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)
        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay

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
                tokens_used=charge.total_tokens,
                prompt_tokens=charge.prompt_tokens,
                completion_tokens=charge.completion_tokens,
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
                model=answered,
                token_source=charge.source,
                cached=replayed,  # BF-901: a replay whose verdict did not parse is still a replay
            )

        # Ensure required keys
        result = {
            "pass": parsed.get("pass", True),
            "score": float(parsed.get("score", 1.0)),
            "criteria": parsed.get("criteria", {}),
            "recommendation": parsed.get("recommendation", "approve"),
        }

        # AD-645b Phase 4: Ensure brief_alignment is always present in
        # criteria. When the brief was absent OR the LLM omitted the field
        # despite being asked, post-fill with neutral score 0.5 and an
        # explanatory rationale. Additive-only — never overrides an
        # LLM-supplied verdict.
        _criteria = result["criteria"] if isinstance(result["criteria"], dict) else {}
        if "brief_alignment" not in _criteria:
            _brief_for_fill = _get_composition_brief(prior_results)
            if _brief_for_fill is None:
                _criteria["brief_alignment"] = {
                    "pass": True,
                    "score": 0.5,
                    "reason": "brief absent",
                    "dimensions": {},
                }
            else:
                _criteria["brief_alignment"] = {
                    "pass": True,
                    "score": 0.5,
                    "reason": "verdict omitted criterion",
                    "dimensions": {},
                }
            result["criteria"] = _criteria

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
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
            cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend
        )
