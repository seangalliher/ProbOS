"""AD-482f v1: QA Agent Pool with Shapley contribution scoring.

Wraps the existing `SystemQAAgent` template (single-instance utility agent)
into an N-instance pool. Each agent independently evaluates a candidate
designed-agent record; per-agent Shapley contribution is computed via
``compute_shapley_values`` over synthetic Vote records keyed on pass-count.

No new QA logic -- existing `SystemQAAgent` handles behavioral / regression /
performance testing. This module is the aggregator + Shapley layer only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from probos.consensus.shapley import compute_shapley_values
from probos.types import Vote

if TYPE_CHECKING:
    from probos.agents.system_qa import SystemQAAgent
    from probos.cognitive.self_mod import DesignedAgentRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QAEvaluation:
    """Aggregated QA outcome over a pool of QA agents."""

    proposal_id: str
    pass_count: int
    fail_count: int
    overall_pass: bool
    shapley_contributions: dict[str, float] = field(default_factory=dict)
    per_agent_outcomes: dict[str, bool] = field(default_factory=dict)


class QAAgentPool:
    """Pool of QA agents with Shapley contribution scoring.

    Args:
        qa_agents: List of ``SystemQAAgent`` instances. v1 caller (the wirer)
            requests N instances from the spawner; if only 1 is available the
            pool degrades gracefully and the Shapley contribution is
            ``{single_agent_id: 1.0}``.
        approval_threshold: Quorum threshold (0..1) for ``overall_pass``.
            Default 0.5 -- majority pass = overall pass.
        shapley_fn: Injectable Shapley computation. Default uses
            ``probos.consensus.shapley.compute_shapley_values``.
    """

    def __init__(
        self,
        *,
        qa_agents: list[Any],  # list[SystemQAAgent]
        approval_threshold: float = 0.5,
        shapley_fn: Callable[..., dict[str, float]] = compute_shapley_values,
    ) -> None:
        if not qa_agents:
            raise ValueError("AD-482f: QAAgentPool requires at least one QA agent")
        self._qa_agents = list(qa_agents)
        self._threshold = max(0.0, min(1.0, approval_threshold))
        self._shapley_fn = shapley_fn

    @property
    def size(self) -> int:
        return len(self._qa_agents)

    async def evaluate_proposal(
        self,
        *,
        proposal_id: str,
        candidate_record: Any,  # DesignedAgentRecord
    ) -> QAEvaluation:
        """Run all QA agents against the candidate record. Aggregate via Shapley.

        Each QA agent's ``smoke_test_record(candidate_record)`` returns a
        ``QAReport`` with a ``passed: bool`` field. Synthesize one ``Vote``
        per QA agent (yes when passed, no otherwise; confidence=1.0).
        Compute Shapley contributions across the votes.
        """
        per_agent_outcomes: dict[str, bool] = {}
        votes: list[Vote] = []
        for qa in self._qa_agents:
            agent_id = getattr(qa, "id", None) or f"qa_unknown_{id(qa)}"
            try:
                report = await qa.smoke_test_record(candidate_record)
                passed = bool(getattr(report, "passed", False))
            except Exception:
                logger.warning(
                    "AD-482f: QA agent %s smoke_test_record raised; counting as fail",
                    agent_id,
                    exc_info=True,
                )
                passed = False
            per_agent_outcomes[agent_id] = passed
            votes.append(
                Vote(agent_id=agent_id, approved=passed, confidence=1.0)
            )

        pass_count = sum(1 for v in per_agent_outcomes.values() if v)
        fail_count = len(per_agent_outcomes) - pass_count
        overall_pass = (pass_count / max(1, len(per_agent_outcomes))) >= self._threshold

        try:
            contributions = self._shapley_fn(
                votes,
                approval_threshold=self._threshold,
                use_confidence_weights=True,
            )
        except Exception:
            logger.warning(
                "AD-482f: shapley_fn failed; emitting equal contributions",
                exc_info=True,
            )
            n = max(1, len(per_agent_outcomes))
            contributions = {aid: 1.0 / n for aid in per_agent_outcomes}

        return QAEvaluation(
            proposal_id=proposal_id,
            pass_count=pass_count,
            fail_count=fail_count,
            overall_pass=overall_pass,
            shapley_contributions=contributions,
            per_agent_outcomes=per_agent_outcomes,
        )
