"""AD-532: Procedure data model — deterministic step sequences extracted from experience.

A Procedure is the "how" — the specific ordered steps an agent used to solve
a class of problem successfully. Extracted from success-dominant EpisodeClusters
during dream consolidation (AD-531 → AD-532).

Consumed by:
- AD-533: Procedure Store (persistence)
- AD-534: Replay-First Dispatch (execution)
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcedureStep:
    """A single step in a deterministic procedure.

    Each step represents one action the agent took, with pre/postconditions
    that must hold for safe execution.
    """

    step_number: int  # 1-based ordinal
    action: str  # what to do (natural language description)
    expected_input: str = ""  # what state should look like before this step
    expected_output: str = ""  # what state should look like after this step
    fallback_action: str = ""  # what to do if this step fails
    invariants: list[str] = field(default_factory=list)  # must remain true during step
    agent_role: str = ""  # AD-532d: functional role (e.g. "security_analysis"), "" = any agent
    resolved_agent_type: str = ""  # AD-534c: concrete agent_type for dispatch, "" = unresolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "expected_input": self.expected_input,
            "expected_output": self.expected_output,
            "fallback_action": self.fallback_action,
            "invariants": self.invariants,
            "agent_role": self.agent_role,
            "resolved_agent_type": self.resolved_agent_type,
        }


@dataclass
class Procedure:
    """A deterministic procedure extracted from a success-dominant episode cluster.

    Represents the "compiled" solution to a recurring task type. Can be
    replayed without LLM involvement once validated (AD-534).
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""  # human-readable label (e.g., "Handle code review request")
    description: str = ""  # what this procedure accomplishes
    steps: list[ProcedureStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)  # must be true before execution
    postconditions: list[str] = field(default_factory=list)  # must be true after execution
    intent_types: list[str] = field(default_factory=list)  # intent types this handles
    origin_cluster_id: str = ""  # EpisodeCluster.cluster_id that spawned this
    origin_agent_ids: list[str] = field(default_factory=list)  # agents in the cluster
    provenance: list[str] = field(default_factory=list)  # episode IDs this was derived from
    extraction_date: float = 0.0  # timestamp of extraction
    evolution_type: str = "CAPTURED"  # CAPTURED | FIX | DERIVED (only CAPTURED in AD-532)
    compilation_level: int = 1  # Dreyfus level (AD-535): 1=Novice
    success_count: int = 0  # incremented by AD-534 replay
    failure_count: int = 0  # incremented by AD-534 replay failure
    # AD-533: Store and evolution support
    is_active: bool = True  # False when superseded by FIX (AD-532b)
    generation: int = 0  # distance from root in version DAG (AD-532b)
    parent_procedure_ids: list[str] = field(default_factory=list)  # FIX/DERIVED parents (AD-532b)
    is_negative: bool = False  # anti-pattern flag (AD-532c)
    superseded_by: str = ""  # ID of procedure that replaced this one (AD-532b)
    tags: list[str] = field(default_factory=list)  # domain, agent_type, etc.
    learned_via: str = "direct"  # "direct" | "observational" | "taught" (AD-537)
    learned_from: str = ""  # callsign of the agent observed/taught from (AD-537)
    last_used_at: float = 0.0    # timestamp of last replay selection (AD-538)
    is_archived: bool = False     # archived (removed from active index) (AD-538)
    # AD-567d: Anchor provenance from source episodes
    source_anchors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "intent_types": self.intent_types,
            "origin_cluster_id": self.origin_cluster_id,
            "origin_agent_ids": self.origin_agent_ids,
            "provenance": self.provenance,
            "extraction_date": self.extraction_date,
            "evolution_type": self.evolution_type,
            "compilation_level": self.compilation_level,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "is_active": self.is_active,
            "generation": self.generation,
            "parent_procedure_ids": self.parent_procedure_ids,
            "is_negative": self.is_negative,
            "superseded_by": self.superseded_by,
            "tags": self.tags,
            "learned_via": self.learned_via,
            "learned_from": self.learned_from,
            "last_used_at": self.last_used_at,
            "is_archived": self.is_archived,
            "source_anchors": self.source_anchors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Procedure":
        """Reconstruct a Procedure from a serialized dict."""
        steps = [ProcedureStep(**s) for s in data.get("steps", [])]
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=steps,
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=data.get("intent_types", []),
            origin_cluster_id=data.get("origin_cluster_id", ""),
            origin_agent_ids=data.get("origin_agent_ids", []),
            provenance=data.get("provenance", []),
            extraction_date=data.get("extraction_date", 0.0),
            evolution_type=data.get("evolution_type", "CAPTURED"),
            compilation_level=data.get("compilation_level", 1),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            is_active=data.get("is_active", True),
            generation=data.get("generation", 0),
            parent_procedure_ids=data.get("parent_procedure_ids", []),
            is_negative=data.get("is_negative", False),
            superseded_by=data.get("superseded_by", ""),
            tags=data.get("tags", []),
            learned_via=data.get("learned_via", "direct"),
            learned_from=data.get("learned_from", ""),
            last_used_at=data.get("last_used_at", 0.0),
            is_archived=data.get("is_archived", False),
            source_anchors=data.get("source_anchors", []),
        )


@dataclass
class EvolutionResult:
    """Result of a FIX or DERIVED evolution (AD-532b)."""
    procedure: Procedure
    content_diff: str
    change_summary: str


# ------------------------------------------------------------------
# AD-532e: LLM confirmation gate & apply-retry
# ------------------------------------------------------------------

_CONFIRMATION_GATE_PROMPT = (
    "You are a procedure evolution gate. Given a procedure's health diagnosis "
    "and supporting evidence, determine whether evolution should be triggered. "
    "Answer with exactly YES or NO on the first line, followed by a brief reason."
)


async def confirm_evolution_with_llm(
    procedure_name: str,
    diagnosis: str,
    evidence: str,
    llm_client: Any,
) -> bool:
    """Gate evolution behind LLM confirmation. Returns True only on explicit YES."""
    try:
        from probos.types import LLMRequest

        user_prompt = (
            f"Procedure: {procedure_name}\n"
            f"Diagnosis: {diagnosis}\n"
            f"Evidence: {evidence}\n\n"
            "Should this procedure be evolved? Answer YES or NO on the first line."
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_CONFIRMATION_GATE_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=256,
        )
        response = await llm_client.complete(request)

        text = response.content.strip()
        first_line = text.split("\n")[0].strip().upper() if text else ""
        decision = first_line == "YES"

        logger.debug(
            "Evolution gate: procedure=%s diagnosis=%s decision=%s",
            procedure_name, diagnosis, decision,
        )
        return decision

    except Exception as e:
        logger.debug("Evolution gate failed (conservative deny): %s", e)
        return False


async def evolve_with_retry(
    evolve_fn: Any,
    *args: Any,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """Call an evolution function with retries on None/failure results."""
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                kwargs["retry_hint"] = (
                    "Previous attempt returned no usable result. "
                    "Please ensure valid JSON output."
                )
                logger.debug(
                    "Evolution retry %d/%d for %s",
                    attempt + 1, max_retries, evolve_fn.__name__,
                )
            result = await evolve_fn(*args, **kwargs)
            if result is not None:
                return result
        except Exception as e:
            logger.debug(
                "Evolution attempt %d/%d failed: %s",
                attempt + 1, max_retries, e,
            )
    return None


# ------------------------------------------------------------------
# Shared diagnosis function (AD-532b / AD-534)
# ------------------------------------------------------------------

def diagnose_procedure_health(metrics: dict[str, Any], min_selections: int = 5) -> str | None:
    """Rule-based health diagnosis. Returns diagnosis string or None.

    Rules (first match wins, from OpenSpace):
    - fallback_rate > threshold -> "FIX:high_fallback_rate"
    - applied_rate > threshold AND completion_rate < threshold -> "FIX:low_completion"
    - effective_rate < threshold AND applied_rate > threshold -> "DERIVED:low_effective_rate"
    """
    from probos.config import (
        PROCEDURE_HEALTH_FALLBACK_RATE,
        PROCEDURE_HEALTH_COMPLETION_RATE,
        PROCEDURE_HEALTH_APPLIED_RATE,
        PROCEDURE_HEALTH_EFFECTIVE_RATE,
        PROCEDURE_HEALTH_DERIVED_APPLIED,
    )

    selections = metrics.get("total_selections", 0)
    if selections < min_selections:
        return None

    fallback_rate = metrics.get("fallback_rate", 0.0)
    applied_rate = metrics.get("applied_rate", 0.0)
    completion_rate = metrics.get("completion_rate", 0.0)
    effective_rate = metrics.get("effective_rate", 0.0)

    if fallback_rate > PROCEDURE_HEALTH_FALLBACK_RATE:
        return "FIX:high_fallback_rate"
    if applied_rate > PROCEDURE_HEALTH_APPLIED_RATE and completion_rate < PROCEDURE_HEALTH_COMPLETION_RATE:
        return "FIX:low_completion"
    if effective_rate < PROCEDURE_HEALTH_EFFECTIVE_RATE and applied_rate > PROCEDURE_HEALTH_DERIVED_APPLIED:
        return "DERIVED:low_effective_rate"
    return None


# ------------------------------------------------------------------
# LLM-assisted extraction (Part 2)
# ------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a procedure extraction engine. You analyze successful execution episodes
and extract the common deterministic procedure — the specific steps that were
taken, in order, to achieve the outcome.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label",
  "description": "what this procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"]
}

Rules:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON pattern across episodes, not any single episode's exact steps
- Steps should be deterministic and replayable without LLM assistance
- ABSTRACT over specific instances: replace specific channel names, thread IDs, agent names, \
timestamps, and quoted phrases with generic placeholders (e.g., "{channel}", "{thread_id}", \
"{colleague}", "{timestamp}"). The procedure must be generalizable to future scenarios, not \
a verbatim replay of one conversation.
- Focus on the SKILL being demonstrated (e.g., "provide departmental analysis referencing \
others' observations"), not the CONTENT of a specific exchange.
- Do NOT hardcode specific data values, metric numbers, or scenario details from the source \
episodes into procedure steps.
- If no common procedure can be extracted, return {"error": "no_common_pattern"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)

_FIX_SYSTEM_PROMPT = """\
You are a procedure repair engine. A previously extracted procedure has degraded
in quality (high fallback rate, low completion rate, or low effectiveness).
You are given the original procedure, its quality metrics, the specific diagnosis,
and fresh successful episodes that represent how the task is NOW being accomplished.

Your job: produce a REPAIRED version of the procedure that reflects current reality.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label",
  "description": "what this procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"],
  "change_summary": "one-sentence summary of what changed and why"
}

Rules:
- Keep the same logical intent — this is a REPAIR, not a new procedure
- Reference episode IDs from the fresh episodes, do not reconstruct narratives
- Steps should be deterministic and replayable without LLM assistance
- The change_summary must explain what was wrong and what you fixed
- If no repair can be determined, return {"error": "no_repair_possible"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""

_DERIVED_SYSTEM_PROMPT = """\
You are a procedure specialization engine. You are given one or more parent
procedures and episodes showing contexts where the parent(s) don't fully succeed.
Your job: create a SPECIALIZED variant that handles the failing cases better.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label (should reflect the specialization)",
  "description": "what this specialized procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting (should be MORE specific than parent)"],
  "postconditions": ["what must be true when done"],
  "change_summary": "one-sentence summary of how this specializes the parent(s)"
}

Rules:
- The preconditions should be NARROWER than the parent — this handles a specific subset
- Reference episode IDs, do not reconstruct narratives
- Steps should be deterministic and replayable without LLM assistance
- If no useful specialization can be determined, return {"error": "no_specialization_possible"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""


_NEGATIVE_SYSTEM_PROMPT = """\
You are an anti-pattern extraction engine. You analyze FAILED execution episodes
and extract the common mistake — the specific steps that were taken that led to
failure. This becomes a "negative procedure" — a warning of what NOT to do.

Output ONLY valid JSON matching this schema:
{
  "name": "short label describing the anti-pattern",
  "description": "what goes wrong when this pattern is followed",
  "steps": [
    {
      "step_number": 1,
      "action": "the BAD action that was taken",
      "expected_input": "state before this step",
      "expected_output": "what the agent EXPECTED (but did not get)",
      "fallback_action": "what SHOULD be done instead",
      "invariants": ["what was violated"]
    }
  ],
  "preconditions": ["conditions under which this anti-pattern is dangerous"],
  "postconditions": ["the negative outcomes that result from following this pattern"]
}

Rules:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON failure pattern across episodes, not any single episode's exact steps
- The "fallback_action" for each step should describe the CORRECT approach to take instead
- Preconditions should describe WHEN this anti-pattern is tempting but dangerous
- Postconditions should describe the BAD outcomes (errors, failures, user dissatisfaction)
- If no common anti-pattern can be extracted, return {"error": "no_common_antipattern"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""


def _format_procedure_block(procedure: Any, label: str = "PROCEDURE") -> str:
    """Format a procedure as an AD-541b READ-ONLY block."""
    proc_json = json.dumps(procedure.to_dict(), indent=2, default=str)
    return (
        f"=== READ-ONLY {label} (do not modify source — generate new artifact) ===\n"
        f"{proc_json}\n"
        f"=== END READ-ONLY {label} ==="
    )


def _format_episode_blocks(episodes: list[Any]) -> str:
    """Format episodes as AD-541b READ-ONLY blocks. AD-567d: includes anchor context."""
    blocks = []
    for ep in episodes:
        # AD-567d: Include anchor context if present
        anchor_lines = ""
        anchors = getattr(ep, "anchors", None)
        if anchors is not None:
            ch = getattr(anchors, "channel", "") or ""
            dept = getattr(anchors, "department", "") or ""
            trigger = getattr(anchors, "trigger_type", "") or ""
            parts = getattr(anchors, "participants", []) or []
            if ch or dept or trigger or parts:
                anchor_lines = (
                    f"Channel: {ch}\n"
                    f"Department: {dept}\n"
                    f"Trigger: {trigger}\n"
                    f"Participants: {parts}\n"
                )
        block = (
            "=== READ-ONLY EPISODE (do not modify, summarize, or reinterpret) ===\n"
            f"Episode ID: {ep.id}\n"
            f"User Input: {ep.user_input}\n"
            f"Outcomes: {json.dumps(ep.outcomes, default=str)}\n"
            f"DAG Summary: {json.dumps(ep.dag_summary, default=str)}\n"
            f"Reflection: {ep.reflection or 'none'}\n"
            f"Agents: {ep.agent_ids}\n"
            + anchor_lines
            + "=== END READ-ONLY EPISODE ==="
        )
        blocks.append(block)
    return "\n\n".join(blocks)


async def extract_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
) -> Procedure | None:
    """Extract a deterministic procedure from a success-dominant episode cluster.

    Uses AD-541b READ-ONLY episode framing to prevent the LLM from
    modifying or fabricating episode content.

    Returns None if extraction fails (log-and-degrade).
    """
    try:
        from probos.types import LLMRequest

        # Build user prompt with AD-541b READ-ONLY framing
        user_prompt = (
            f"Extract the common procedure from these {len(episodes)} successful episodes "
            f"(cluster {cluster.cluster_id}, {cluster.success_rate:.0%} success rate, "
            f"intent types: {cluster.intent_types}).\n\n"
            + _format_episode_blocks(episodes)
            + "\n\nAnalyze the PATTERN across these episodes. Do not alter, embellish, "
            "or reinterpret individual episodes. Your output should reference "
            "episode IDs, not reconstructed narratives."
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        # Parse response — strip markdown fences if present
        text = response.content.strip()
        match = _FENCE_RE.search(text)
        if match:
            text = match.group(1).strip()

        data = json.loads(text)

        # Check for explicit error response
        if "error" in data:
            logger.debug("LLM declined extraction: %s", data["error"])
            return None

        # Build Procedure from parsed JSON
        steps = []
        for s in data.get("steps", []):
            steps.append(ProcedureStep(
                step_number=s.get("step_number", 0),
                action=s.get("action", ""),
                expected_input=s.get("expected_input", ""),
                expected_output=s.get("expected_output", ""),
                fallback_action=s.get("fallback_action", ""),
                invariants=s.get("invariants", []),
            ))

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=steps,
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=cluster.intent_types,
            origin_cluster_id=cluster.cluster_id,
            origin_agent_ids=cluster.participating_agents,
            provenance=cluster.episode_ids,
            extraction_date=time.time(),
            evolution_type="CAPTURED",
            compilation_level=1,
        )
        return procedure

    except Exception as e:
        logger.debug("Procedure extraction failed (non-critical): %s", e)
        return None


# ------------------------------------------------------------------
# Observational extraction (AD-537)
# ------------------------------------------------------------------

_OBSERVATION_SYSTEM_PROMPT = """\
You are an observational learning engine. You analyze a Ward Room discussion
between agents and determine if it contains actionable procedural knowledge
that an observer could learn from.

Your task has TWO parts:

**Part 1 — Detail Assessment:**
Score the discussion's actionability from 0.0 to 1.0:
- 0.0: Pure opinion, no actionable steps
- 0.3: Mentions a solution but lacks specifics
- 0.6: Clear problem → solution with some reproducible steps
- 0.8: Detailed, step-by-step walkthrough that someone could follow
- 1.0: Complete procedure with inputs, outputs, and edge cases

**Part 2 — Procedure Extraction (only if detail_score >= 0.6):**
Extract the procedure from the observer's perspective — what *I* learned
from watching this discussion.

Output ONLY valid JSON matching this schema:
{
  "detail_score": 0.8,
  "name": "short human-readable label",
  "description": "what this procedure accomplishes. Include: Observed from {author}'s discussion about {topic}.",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"]
}

If detail_score < 0.6, return ONLY: {"detail_score": 0.3, "error": "insufficient_detail"}

Rules:
- This is READ-ONLY observation. Do not modify, summarize, or reinterpret the discussion.
- The observer is learning from another agent's account [observed], not from direct experience.
- Steps should be deterministic and replayable without LLM assistance.
- Frame the procedure from the observer's perspective.
"""


async def extract_procedure_from_observation(
    thread_content: str,
    observer_agent_type: str,
    author_callsign: str,
    author_trust: float,
    llm_client: Any,
    is_teaching: bool = False,
) -> Procedure | None:
    """Extract a procedure from a Ward Room thread observation.

    AD-537: Observational learning — agents learn from Ward Room discussions.
    When is_teaching=True (Level 5 teaching DM), sets learned_via="taught"
    and compilation_level=2, skipping detail_score threshold.

    Returns None if extraction fails or detail is insufficient.
    """
    from probos.config import OBSERVATION_MIN_DETAIL_SCORE

    try:
        from probos.types import LLMRequest

        user_prompt = (
            "=== READ-ONLY WARD ROOM DISCUSSION (do not modify or reinterpret) ===\n"
            f"{thread_content}\n"
            "=== END READ-ONLY DISCUSSION ===\n\n"
            f"Observer: {observer_agent_type}\n"
            f"Author: {author_callsign} (trust: {author_trust:.2f})\n\n"
            "Analyze this discussion for actionable procedural knowledge. "
            "Score the detail level, and if sufficient, extract a procedure "
            "from the observer's perspective."
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_OBSERVATION_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        text = response.content.strip()
        match = _FENCE_RE.search(text)
        if match:
            text = match.group(1).strip()

        data = json.loads(text)

        if "error" in data:
            logger.debug("Observation extraction declined: %s", data["error"])
            return None

        detail_score = data.get("detail_score", 0.0)
        min_detail = OBSERVATION_MIN_DETAIL_SCORE

        # Teaching DMs skip detail threshold — always detailed enough
        if not is_teaching and detail_score < min_detail:
            logger.debug(
                "Observation detail too low (%.2f < %.2f), skipping",
                detail_score, min_detail,
            )
            return None

        steps = _build_steps_from_data(data)

        learned_via = "taught" if is_teaching else "observational"
        comp_level = 2 if is_teaching else 1

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=steps,
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=[],
            origin_cluster_id="",
            origin_agent_ids=[observer_agent_type],
            provenance=[],
            extraction_date=time.time(),
            evolution_type="CAPTURED",
            compilation_level=comp_level,
            learned_via=learned_via,
            learned_from=author_callsign,
        )
        return procedure

    except Exception as e:
        logger.debug("Observation extraction failed (non-critical): %s", e)
        return None


# ------------------------------------------------------------------
# Evolution functions (AD-532b)
# ------------------------------------------------------------------

def _parse_procedure_json(text: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    text = text.strip()
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()
    data = json.loads(text)
    if "error" in data:
        logger.debug("LLM declined evolution: %s", data["error"])
        return None
    return data


def _build_steps_from_data(data: dict[str, Any]) -> list[ProcedureStep]:
    """Build ProcedureStep list from parsed JSON data."""
    steps = []
    for s in data.get("steps", []):
        steps.append(ProcedureStep(
            step_number=s.get("step_number", 0),
            action=s.get("action", ""),
            expected_input=s.get("expected_input", ""),
            expected_output=s.get("expected_output", ""),
            fallback_action=s.get("fallback_action", ""),
            invariants=s.get("invariants", []),
            agent_role=s.get("agent_role", ""),
            resolved_agent_type=s.get("resolved_agent_type", ""),
        ))
    return steps


def _generate_content_diff(parent: Procedure, child: Procedure) -> str:
    """Generate unified diff between parent and child procedure JSON."""
    parent_lines = json.dumps(parent.to_dict(), indent=2).splitlines(keepends=True)
    child_lines = json.dumps(child.to_dict(), indent=2).splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        parent_lines, child_lines,
        fromfile=f"parent:{parent.id}", tofile=f"child:{child.id}",
    ))


async def evolve_fix_procedure(
    parent: Procedure,
    diagnosis: str,
    metrics: dict[str, Any],
    fresh_episodes: list[Any],
    llm_client: Any,
    retry_hint: str = "",  # AD-532e: retry guidance from evolve_with_retry
) -> EvolutionResult | None:
    """Evolve a FIX replacement for a degraded procedure.

    The parent is deactivated by the caller after successful evolution.
    Returns None if the LLM cannot produce a repair.
    """
    try:
        from probos.types import LLMRequest

        user_prompt = (
            _format_procedure_block(parent, "DEGRADED PROCEDURE")
            + "\n\n"
            f"Diagnosis: {diagnosis}\n"
            f"Quality metrics: {json.dumps(metrics)}\n\n"
            f"Fresh successful episodes ({len(fresh_episodes)}):\n\n"
            + _format_episode_blocks(fresh_episodes)
            + "\n\nRepair this procedure based on the fresh episodes. "
            "Do not alter, embellish, or reinterpret individual episodes. "
            "The diagnosis explains what degraded."
        )
        if retry_hint:
            user_prompt += f"\n\n[RETRY HINT: {retry_hint}]"

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_FIX_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        data = _parse_procedure_json(response.content)
        if data is None:
            return None

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=_build_steps_from_data(data),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=parent.intent_types,
            origin_cluster_id=parent.origin_cluster_id,
            origin_agent_ids=parent.origin_agent_ids,
            extraction_date=time.time(),
            evolution_type="FIX",
            generation=parent.generation + 1,
            parent_procedure_ids=[parent.id],
            compilation_level=parent.compilation_level,
            tags=list(parent.tags),
        )

        content_diff = _generate_content_diff(parent, procedure)
        change_summary = data.get("change_summary", "")

        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("FIX evolution failed (non-critical): %s", e)
        return None


async def evolve_derived_procedure(
    parents: list[Procedure],
    fresh_episodes: list[Any],
    llm_client: Any,
    retry_hint: str = "",  # AD-532e: retry guidance from evolve_with_retry
) -> EvolutionResult | None:
    """Create a specialized DERIVED variant from 1+ parent procedures.

    Parents stay active (DERIVED branches, does not replace).
    Returns None if the LLM cannot produce a specialization.
    """
    try:
        from probos.types import LLMRequest

        # Build parent blocks with AD-541b READ-ONLY framing
        parent_blocks = []
        for i, p in enumerate(parents, 1):
            parent_blocks.append(
                _format_procedure_block(p, f"PARENT PROCEDURE {i}")
            )

        if len(parents) == 1:
            instruction = (
                "Create a specialized variant that handles the cases "
                "where the parent procedure fails."
            )
        else:
            instruction = (
                "Create a specialized procedure that combines the strengths "
                "of these parent procedures for the specific context shown "
                "in the episodes."
            )

        user_prompt = (
            "\n\n".join(parent_blocks)
            + f"\n\nFresh episodes ({len(fresh_episodes)}):\n\n"
            + _format_episode_blocks(fresh_episodes)
            + f"\n\n{instruction}"
            + "\nDo not alter, embellish, or reinterpret individual episodes."
        )
        if retry_hint:
            user_prompt += f"\n\n[RETRY HINT: {retry_hint}]"

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_DERIVED_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        data = _parse_procedure_json(response.content)
        if data is None:
            return None

        # Union of all parents' fields
        all_intent_types = list({t for p in parents for t in p.intent_types})
        all_agent_ids = list({a for p in parents for a in p.origin_agent_ids})
        all_tags = list({t for p in parents for t in p.tags})
        max_gen = max(p.generation for p in parents)
        max_level = max(p.compilation_level for p in parents)

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=_build_steps_from_data(data),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=all_intent_types,
            origin_cluster_id="",  # DERIVED has no single origin cluster
            origin_agent_ids=all_agent_ids,
            extraction_date=time.time(),
            evolution_type="DERIVED",
            generation=max_gen + 1,
            parent_procedure_ids=[p.id for p in parents],
            compilation_level=max(max_level - 1, 1),
            tags=all_tags,
        )

        # Diff against first parent (convention for multi-parent)
        content_diff = _generate_content_diff(parents[0], procedure)
        change_summary = data.get("change_summary", "")

        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("DERIVED evolution failed (non-critical): %s", e)
        return None


# ------------------------------------------------------------------
# Negative procedure extraction (AD-532c)
# ------------------------------------------------------------------

_COMPOUND_SYSTEM_PROMPT = """\
You are a multi-agent compound procedure extraction engine. You analyze successful
execution episodes that involve MULTIPLE agents collaborating on a task, and extract
the common collaborative workflow — which agent roles contributed what, in what order.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label for this collaborative workflow",
  "description": "what this compound procedure accomplishes through collaboration",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"],
      "agent_role": "functional_role_descriptor"
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"]
}

Rules:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON collaborative pattern across episodes, not any single episode's exact steps
- Assign a functional agent_role per step — generalize from specific agent names/IDs to \
descriptive roles (e.g. "security_analysis", "engineering_diagnostics", "code_generation"). \
Do NOT use specific callsigns or agent IDs as roles.
- Capture handoff points: step N's expected_output should match step N+1's expected_input \
when the role changes between steps (cross-agent handoff)
- Preserve sequential ordering — steps should reflect the temporal order agents took
- Steps should be deterministic and replayable without LLM assistance
- If no common multi-agent pattern can be extracted, return {"error": "no_compound_pattern"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""


async def extract_negative_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster (failure-dominant)
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
    contradictions: list[Any] | None = None,  # Contradiction objects (AD-403)
) -> Procedure | None:
    """Extract a negative procedure (anti-pattern) from a failure-dominant cluster.

    Uses AD-541b READ-ONLY episode framing. Optionally enriched with
    contradiction context from AD-403.

    Returns None if extraction fails (log-and-degrade).
    """
    try:
        from probos.types import LLMRequest

        failure_rate = 1.0 - cluster.success_rate
        user_prompt = (
            f"Extract the common anti-pattern from these {len(episodes)} failed episodes "
            f"(cluster {cluster.cluster_id}, {failure_rate:.0%} failure rate, "
            f"intent types: {cluster.intent_types}).\n\n"
            + _format_episode_blocks(episodes)
        )

        # Optionally enrich with contradiction context (AD-403)
        if contradictions:
            # Filter to contradictions matching cluster intent types
            relevant = [
                c for c in contradictions
                if c.intent in cluster.intent_types
            ]
            # Limit to 5 most relevant (highest similarity)
            relevant.sort(key=lambda c: c.similarity, reverse=True)
            relevant = relevant[:5]
            if relevant:
                lines = [
                    "\n=== READ-ONLY CONTRADICTION CONTEXT (do not modify — reference only) ===",
                    "The following contradictions were detected — episodes with similar inputs",
                    "but opposite outcomes. The failure outcomes may explain WHY this pattern is bad:\n",
                ]
                for i, c in enumerate(relevant, 1):
                    lines.append(
                        f"Contradiction {i}: Episode {c.older_episode_id} ({c.older_outcome}) "
                        f"vs Episode {c.newer_episode_id} ({c.newer_outcome})"
                    )
                    lines.append(
                        f"  Intent: {c.intent}, Agent: {c.agent_id}, "
                        f"Similarity: {c.similarity:.2f}"
                    )
                    if c.description:
                        lines.append(f"  {c.description}")
                lines.append("=== END READ-ONLY CONTRADICTION CONTEXT ===")
                user_prompt += "\n".join(lines)

        user_prompt += (
            "\n\nAnalyze the PATTERN across these episodes. Do not alter, embellish, "
            "or reinterpret individual episodes. Your output should reference "
            "episode IDs, not reconstructed narratives."
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_NEGATIVE_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        data = _parse_procedure_json(response.content)
        if data is None:
            return None

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=_build_steps_from_data(data),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            is_negative=True,
            intent_types=cluster.intent_types,
            origin_cluster_id=cluster.cluster_id,
            origin_agent_ids=cluster.participating_agents,
            provenance=cluster.episode_ids,
            extraction_date=time.time(),
            evolution_type="CAPTURED",
            compilation_level=1,
        )
        return procedure

    except Exception as e:
        logger.debug("Negative procedure extraction failed (non-critical): %s", e)
        return None


# ------------------------------------------------------------------
# Compound (multi-agent) procedure extraction (AD-532d)
# ------------------------------------------------------------------


def _resolve_agent_roles(
    steps: list[ProcedureStep],
    participating_agent_ids: list[str],
) -> list[ProcedureStep]:
    """AD-534c: Map agent_role strings to concrete agent_types using cluster participant info.

    Agent IDs encode their type: 'security_officer-abc123' → agent_type='security_officer'.
    Builds a {agent_type: token_set} map from participating_agent_ids,
    then uses fuzzy token matching to map each step's agent_role to the best
    matching agent_type.

    Steps with empty agent_role or no match get resolved_agent_type = "".
    """
    if not participating_agent_ids:
        return steps

    # Extract agent_types from IDs: 'security_officer-abc123' → 'security_officer'
    # Agent IDs follow pattern: {agent_type}-{uuid_hex}
    agent_types: list[str] = []
    for aid in participating_agent_ids:
        # Split on last hyphen-followed-by-hex to separate type from UUID
        # Most reliable: find the last segment that looks like hex
        parts = aid.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) >= 6:
            agent_types.append(parts[0])
        else:
            agent_types.append(aid)  # Fallback: use full ID as type

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_types: list[str] = []
    for at in agent_types:
        if at not in seen:
            seen.add(at)
            unique_types.append(at)

    # Build token sets for each agent_type
    type_tokens: dict[str, set[str]] = {}
    for at in unique_types:
        type_tokens[at] = set(at.replace("-", "_").split("_"))

    for step in steps:
        if not step.agent_role:
            continue

        role_tokens = set(step.agent_role.replace("-", "_").split("_"))
        best_type = ""
        best_overlap = 0

        for at, tokens in type_tokens.items():
            overlap = len(role_tokens & tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_type = at

        step.resolved_agent_type = best_type

    return steps


async def extract_compound_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster (success-dominant, multi-agent)
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
) -> Procedure | None:
    """Extract a compound procedure from a multi-agent success-dominant cluster.

    Uses AD-541b READ-ONLY episode framing. Steps include agent_role
    assignments for collaborative workflow replay.

    Returns None if extraction fails (log-and-degrade).
    """
    try:
        from probos.types import LLMRequest

        user_prompt = (
            f"Extract the common collaborative procedure from these {len(episodes)} "
            f"successful multi-agent episodes "
            f"(cluster {cluster.cluster_id}, {cluster.success_rate:.0%} success rate, "
            f"intent types: {cluster.intent_types}, "
            f"participating agents: {cluster.participating_agents}).\n\n"
            + _format_episode_blocks(episodes)
            + "\n\nAnalyze the COLLABORATIVE PATTERN across these episodes. "
            "Identify which agent roles contributed which steps and in what order. "
            "Do not alter, embellish, or reinterpret individual episodes. "
            "Your output should reference episode IDs, not reconstructed narratives."
        )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_COMPOUND_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        data = _parse_procedure_json(response.content)
        if data is None:
            return None

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=_build_steps_from_data(data),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=cluster.intent_types,
            origin_cluster_id=cluster.cluster_id,
            origin_agent_ids=cluster.participating_agents,
            provenance=cluster.episode_ids,
            extraction_date=time.time(),
            evolution_type="CAPTURED",
            compilation_level=1,
        )

        # AD-534c: Resolve agent_role → concrete agent_type for dispatch
        _resolve_agent_roles(procedure.steps, cluster.participating_agents)

        return procedure

    except Exception as e:
        logger.debug("Compound procedure extraction failed (non-critical): %s", e)
        return None


# ------------------------------------------------------------------
# Fallback learning evolution (AD-534b)
# ------------------------------------------------------------------

_FALLBACK_FIX_SYSTEM_PROMPT = """\
You are a targeted procedure repair engine. You are given:
1. A procedure that was relevant to a task but either failed during execution or was \
rejected by quality gates
2. What the LLM actually did to succeed at the same task

Your job is to compare the procedure's steps with the LLM's successful approach, \
identify where they diverge, and produce a repaired procedure.

Analysis steps:
- Compare each step of the procedure against what the LLM did
- Identify the divergence_point: the step number where procedure and LLM first diverged \
(0 if the entire approach changed)
- Diagnose the root cause: did requirements shift? Did a precondition change? Is a step \
outdated? Is the procedure too narrow?
- Produce a repaired procedure incorporating the LLM's successful approach while \
maintaining the procedure's structure and intent

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label",
  "description": "what this procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"],
      "agent_role": ""
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"],
  "change_summary": "one-sentence summary explaining what was wrong and what you fixed, \
referencing specific step numbers",
  "divergence_point": 0
}

Rules:
- Reference episode IDs when available, do not reconstruct narratives
- The repaired procedure must be deterministic and replayable without LLM assistance
- Include a clear change_summary explaining what diverged and why
- Set divergence_point to the first step number where the procedure and LLM approach diverged
- If the procedure is fundamentally wrong, return {"error": "no_repair_possible"}
All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source.
"""


async def evolve_fix_from_fallback(
    parent: Procedure,
    fallback_type: str,
    llm_response: str,
    rejection_reason: str,
    fresh_episodes: list[Any],
    llm_client: Any,
    retry_hint: str = "",
) -> EvolutionResult | None:
    """AD-534b: Targeted FIX evolution using fallback evidence.

    Unlike evolve_fix_procedure() which uses generic health diagnosis,
    this function receives the LLM's successful response as direct evidence
    of what works, enabling more targeted repair.

    Returns None if the LLM cannot produce a repair.
    """
    try:
        from probos.types import LLMRequest

        user_prompt = (
            _format_procedure_block(parent, "PROCEDURE TO REPAIR")
            + "\n\n"
            f"Fallback type: {fallback_type}\n"
            f"Rejection reason: {rejection_reason}\n\n"
            "=== READ-ONLY LLM RESPONSE (do not modify — reference only) ===\n"
            f"{llm_response}\n"
            "=== END READ-ONLY LLM RESPONSE ===\n\n"
        )

        if fresh_episodes:
            user_prompt += (
                f"Fresh episodes ({len(fresh_episodes)}):\n\n"
                + _format_episode_blocks(fresh_episodes)
                + "\n\n"
            )

        user_prompt += (
            "Compare the procedure's steps with what the LLM did. "
            "Identify where they diverge and repair the procedure accordingly. "
            "Do not alter, embellish, or reinterpret individual episodes."
        )
        if retry_hint:
            user_prompt += f"\n\n[RETRY HINT: {retry_hint}]"

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_FALLBACK_FIX_SYSTEM_PROMPT,
            tier="standard",
            temperature=0.0,
            max_tokens=2048,
        )
        response = await llm_client.complete(request)

        data = _parse_procedure_json(response.content)
        if data is None:
            return None

        procedure = Procedure(
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=_build_steps_from_data(data),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=parent.intent_types,
            origin_cluster_id=parent.origin_cluster_id,
            origin_agent_ids=parent.origin_agent_ids,
            extraction_date=time.time(),
            evolution_type="FIX",
            generation=parent.generation + 1,
            parent_procedure_ids=[parent.id],
            compilation_level=parent.compilation_level,
            tags=list(parent.tags),
        )

        content_diff = _generate_content_diff(parent, procedure)
        change_summary = data.get("change_summary", "")

        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("Fallback FIX evolution failed (non-critical): %s", e)
        return None
