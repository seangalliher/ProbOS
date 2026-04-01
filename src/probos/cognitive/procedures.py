"""AD-532: Procedure data model — deterministic step sequences extracted from experience.

A Procedure is the "how" — the specific ordered steps an agent used to solve
a class of problem successfully. Extracted from success-dominant EpisodeClusters
during dream consolidation (AD-531 → AD-532).

Consumed by:
- AD-533: Procedure Store (persistence)
- AD-534: Replay-First Dispatch (execution)
"""

from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "expected_input": self.expected_input,
            "expected_output": self.expected_output,
            "fallback_action": self.fallback_action,
            "invariants": self.invariants,
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
        }


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
- If no common procedure can be extracted, return {"error": "no_common_pattern"}
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


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
        episode_blocks = []
        for ep in episodes:
            block = (
                "=== READ-ONLY EPISODE (do not modify, summarize, or reinterpret) ===\n"
                f"Episode ID: {ep.id}\n"
                f"User Input: {ep.user_input}\n"
                f"Outcomes: {json.dumps(ep.outcomes, default=str)}\n"
                f"DAG Summary: {json.dumps(ep.dag_summary, default=str)}\n"
                f"Reflection: {ep.reflection or 'none'}\n"
                f"Agents: {ep.agent_ids}\n"
                "=== END READ-ONLY EPISODE ==="
            )
            episode_blocks.append(block)

        user_prompt = (
            f"Extract the common procedure from these {len(episodes)} successful episodes "
            f"(cluster {cluster.cluster_id}, {cluster.success_rate:.0%} success rate, "
            f"intent types: {cluster.intent_types}).\n\n"
            + "\n\n".join(episode_blocks)
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
