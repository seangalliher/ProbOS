"""AD-1208 (#1154): the cost budget of one conversational agentic turn.

A 1:1 DM agentic turn can be bounded by what it spends, not only by how many
steps it takes. This module owns that per-turn policy for the DM path:

* The ceiling is ``dm_agentic.token_budget`` (``None`` = off, the shipped
  default). Parsing rejects a value below 1024 (the field's ``ge``); only a
  value that bypassed validation (``model_construct``, a non-config double)
  reaches the check here, where it degrades to "off" -- the
  ``crew_executor._normalize_token_budget`` precedent.
* The agent's trust scales it, within [0.5, 2]. The raw
  Beta(alpha, beta) is read once, at arming, through the trust network's public
  ``get_record``; nothing derived is persisted. Trust moves the budget only: which
  tools a turn may call, and which calls need approval, do not depend on it.
* It is SHARED by the turn's AD-1164 passes: each pass runs with what is left
  (the AD-1155 DD-3 shape), so a continuation cannot multiply the ceiling.
* While it is armed the loop does not count an iteration whose every call is
  tier 1 (``agentic_loop.is_tier_1_tool_call``) toward ``max_iterations``;
  ``dm_agentic.max_total_iterations`` bounds those iterations instead, and
  trust does not move that backstop.
* A turn it stops says so, in front of any partial work.

Tier-3 gating lives in the tool layer and is not touched.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Protocol

from probos.config import TRUST_DEFAULT, TRUST_SENIOR
from probos.crew_execution_usage import (
    TOKEN_SOURCE_ESTIMATED,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_MIXED,
    merge_token_sources,
)

logger = logging.getLogger(__name__)

# Mirrors ``DmAgenticConfig.token_budget``'s ``ge`` and the crew's
# ``_MIN_CREW_TOKEN_BUDGET`` for the same loop: the budget is checked after each
# model call, so any budget admits one call, and one smaller than a typical call
# would end every turn at its first. A drift test keeps it equal to the bound.
MIN_TURN_TOKEN_BUDGET: int = 1024
# Mirrors ``DmAgenticConfig.max_total_iterations`` (default and ``le``). The
# ceiling is ten times the task path's 25 steps: tier-1 steps are bounded by
# tokens first, and this stops a run whose steps stay cheap.
DEFAULT_MAX_TOTAL_ITERATIONS: int = 100
MAX_TOTAL_ITERATIONS_CEILING: int = 250
# How far trust may move the budget. Constants, not config: they bound the
# worst case (2 x token_budget), the PARALLEL_SAFE_TOOL_IDS stance.
TRUST_BUDGET_MULTIPLIER_MIN: float = 0.5
TRUST_BUDGET_MULTIPLIER_MAX: float = 2.0

_KNOWN_TOKEN_SOURCES = frozenset(
    {TOKEN_SOURCE_MEASURED, TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MIXED}
)

# The statement leads (BF-717) and never says "step limit": that phrase belongs
# to the continue-or-ask notice, and the two stops must read differently.
_COST_STOP_LEAD_WITH_WORK: str = (
    "I stopped here: this turn reached its cost budget with the task still "
    "open. Partial work is below."
)
_COST_STOP_LEAD_NO_WORK: str = (
    "I stopped here: this turn reached its cost budget before I had anything "
    "to report back. The task is still open."
)
_COST_STOP_SPEND: str = (
    " It used about {spent:,} tokens against a budget of {budget:,}"
    "{adjusted}{estimated}."
)
_COST_STOP_ADJUSTED: str = " (the configured {configured:,}, adjusted by my trust record)"
_COST_STOP_ESTIMATED: str = " (usage estimated, not measured)"
_COST_STOP_TAIL: str = " A new message starts a new turn with a fresh budget."


class TrustRecordSource(Protocol):
    """The one trust-network method this module reads (``TrustNetwork.get_record``)."""

    def get_record(self, agent_id: str) -> Any: ...


def trust_budget_multiplier(record: object) -> float:
    """AD-1208: how far one agent's trust moves its turn budget, within [0.5, 2].

    1.0 at TRUST_DEFAULT (a new agent's trust), 2.0 from TRUST_SENIOR up, and the
    same slope below, so the floor is reached at a mean of 0.325. Anything that
    is not a valid Beta record -- None, a missing, non-finite or non-positive
    parameter -- is 1.0.
    """
    alpha = getattr(record, "alpha", None)
    beta = getattr(record, "beta", None)
    if not (_positive_finite(alpha) and _positive_finite(beta)):
        return 1.0
    mean = alpha / (alpha + beta)
    raw = 1.0 + (mean - TRUST_DEFAULT) / (TRUST_SENIOR - TRUST_DEFAULT)
    return min(TRUST_BUDGET_MULTIPLIER_MAX, max(TRUST_BUDGET_MULTIPLIER_MIN, raw))


def _positive_finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _read_trust_multiplier(source: object, agent_id: str) -> float:
    if source is None or not agent_id:
        return 1.0
    try:
        record = source.get_record(agent_id)  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "AD-1208: the trust record of agent %s could not be read; its turn "
            "budget stays at the configured value", agent_id[:12], exc_info=True,
        )
        return 1.0
    return trust_budget_multiplier(record)


class TurnCostBudget:
    """The spend ledger of one conversational agentic turn (AD-1208)."""

    def __init__(
        self,
        *,
        budget: int,
        max_total_iterations: int,
        configured_budget: int | None = None,
        trust_multiplier: float = 1.0,
        agent_id: str = "",
    ) -> None:
        self._budget = budget
        self._configured_budget = budget if configured_budget is None else configured_budget
        self._trust_multiplier = trust_multiplier
        self._max_total_iterations = max_total_iterations
        self._agent_id = agent_id
        self._spent = 0
        self._sources: list[str] = []

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        *,
        max_iterations: Any,
        agent_id: str = "",
        trust_source: TrustRecordSource | None = None,
    ) -> TurnCostBudget | None:
        """Arm from ``dm_agentic``; ``None`` means the turn runs exactly as before."""
        budget = getattr(cfg, "token_budget", None)
        if type(budget) is not int or budget < MIN_TURN_TOKEN_BUDGET:
            return None
        if type(max_iterations) is not int or max_iterations < 1:
            return None
        total = getattr(cfg, "max_total_iterations", None)
        if type(total) is not int or total < 1:
            total = DEFAULT_MAX_TOTAL_ITERATIONS
        total = max(min(total, MAX_TOTAL_ITERATIONS_CEILING), max_iterations)
        multiplier = _read_trust_multiplier(trust_source, agent_id)
        # Neutral is the configured value exactly, never a float round-trip of it.
        effective = budget if multiplier == 1.0 else max(MIN_TURN_TOKEN_BUDGET, int(budget * multiplier))
        logger.info(
            "AD-1208: agent %s armed with a %d-token turn budget (configured %d, "
            "trust multiplier %.3f) and max_total_iterations=%d",
            agent_id[:12], effective, budget, multiplier, total,
        )
        return cls(
            budget=effective,
            configured_budget=budget,
            trust_multiplier=multiplier,
            max_total_iterations=total,
            agent_id=agent_id,
        )

    @property
    def budget(self) -> int:
        return self._budget

    @property
    def configured_budget(self) -> int:
        return self._configured_budget

    @property
    def trust_multiplier(self) -> float:
        return self._trust_multiplier

    @property
    def spent(self) -> int:
        return self._spent

    def loop_kwargs(self) -> dict[str, int]:
        """What the next pass passes to ``WorkItemAgenticExecutor.run``.

        The remainder, never below 1. A further pass starts only after a
        ``max_iterations`` stop, which the budget check did not end, so the floor
        is a guard rather than a path.
        """
        return {
            "token_budget": max(self._budget - self._spent, 1),
            "max_total_iterations": self._max_total_iterations,
        }

    def record(self, outcome: Any) -> None:
        """Fold one pass's spend in. A malformed count or source adds nothing."""
        tokens = getattr(outcome, "total_tokens", 0)
        if type(tokens) is int and tokens > 0:
            self._spent += tokens
        source = getattr(outcome, "token_source", None)
        if type(source) is str and source in _KNOWN_TOKEN_SOURCES:
            self._sources.append(source)
        logger.info(
            "AD-1208: agent %s pass stopped_reason=%s; this turn has spent %d of "
            "its %d-token budget (%s)",
            self._agent_id[:12],
            str(getattr(outcome, "stopped_reason", "") or ""),
            self._spent,
            self._budget,
            self._source_label(),
        )

    def render_stop(self, partial: str) -> str:
        """The reply for a turn whose last pass stopped at ``token_budget``."""
        from probos.cognitive.continue_or_ask import _CUT_OFF_SEPARATOR

        body = (partial or "").rstrip()
        lead = _COST_STOP_LEAD_WITH_WORK if body.strip() else _COST_STOP_LEAD_NO_WORK
        estimated = (
            "" if self._source_label() == TOKEN_SOURCE_MEASURED else _COST_STOP_ESTIMATED
        )
        adjusted = (
            _COST_STOP_ADJUSTED.format(configured=self._configured_budget)
            if self._budget != self._configured_budget
            else ""
        )
        note = (
            lead
            + _COST_STOP_SPEND.format(
                spent=self._spent,
                budget=self._budget,
                adjusted=adjusted,
                estimated=estimated,
            )
            + _COST_STOP_TAIL
        )
        return note + _CUT_OFF_SEPARATOR + body if body.strip() else note

    def _source_label(self) -> str:
        # No recorded source is treated as an estimate: "about" is the claim.
        if not self._sources:
            return TOKEN_SOURCE_ESTIMATED
        return merge_token_sources(self._sources)
