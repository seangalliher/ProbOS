"""AD-661 v1: Diagnostic Context Service — pull-based, token-budgeted assembly
of raw diagnostic artifacts (chain traces, procedure exemplars, episodes).

v1 hard limits: no automatic invocation, no continuous stream, no semantic
search, no summary fallback, no LLM calls. Read-only aggregator over
already-shipped surfaces (AD-658, AD-657).

Builds on:
- AD-658 chain_traces (CognitiveJournal.get_recent_chain_traces)
- AD-657 trace_exemplars (Procedure.trace_exemplars + EpisodicMemory.get_by_ids)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4  # Same precedent as agent_working_memory.py:35


def _estimate_tokens(text: str, *, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    """Heuristic token estimator — len(text) // chars_per_token, min 1.

    v1 deliberately does NOT depend on tiktoken or any tokenizer library.
    """
    if not text:
        return 0
    return max(1, len(text) // chars_per_token)


def _extract_keywords(query: str, *, min_len: int = 3) -> list[str]:
    """Split on whitespace, lowercase, drop tokens shorter than min_len."""
    if not query:
        return []
    return [tok.lower() for tok in query.split() if len(tok) >= min_len]


def _matches(text: str | None, keywords: list[str]) -> bool:
    """Case-insensitive substring match. Empty keywords → always True."""
    if not keywords:
        return True
    if not text:
        return False
    haystack = text.lower()
    return any(kw in haystack for kw in keywords)


@dataclass(frozen=True)
class DiagnosticBundle:
    """Token-budgeted bundle of raw diagnostic artifacts.

    Field types are intentionally `list[dict]` (not typed dataclasses) — v1
    is a thin pass-through over journal rows and episode metadata; consumers
    should treat the bundle as a read-only snapshot, not a typed model.

    `total_estimated_tokens` uses the `len(text) // 4` heuristic — see
    `_estimate_tokens()`.
    """

    query: str
    chain_traces: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_tokens: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chain_traces": list(self.chain_traces),
            "procedures": list(self.procedures),
            "episodes": list(self.episodes),
            "total_estimated_tokens": self.total_estimated_tokens,
            "truncated": self.truncated,
        }


class DiagnosticContextService:
    """Pull-based diagnostic-context assembler.

    Construction mirrors AD-659 ChainOptimizer / AD-660 CausalReasoner sibling
    shape: `__init__(runtime, *, default_budget_tokens=..., chain_trace_ratio=...,
    procedure_ratio=..., episode_ratio=..., chars_per_token=...)`.

    `assemble()` never raises — every collector is wrapped in try/except →
    log-and-degrade. A failure in one section yields an empty section, not a
    failed bundle.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        default_budget_tokens: int = 8000,
        chain_trace_ratio: float = 0.4,
        procedure_ratio: float = 0.3,
        episode_ratio: float = 0.3,
        chars_per_token: int = CHARS_PER_TOKEN,
    ) -> None:
        self._runtime = runtime
        self._default_budget_tokens = default_budget_tokens
        self._chain_trace_ratio = chain_trace_ratio
        self._procedure_ratio = procedure_ratio
        self._episode_ratio = episode_ratio
        self._chars_per_token = chars_per_token

    async def assemble(
        self,
        *,
        query: str,
        budget_tokens: int | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
    ) -> DiagnosticBundle:
        """Assemble a token-budgeted diagnostic bundle.

        Args:
            query: Natural-language query for keyword filtering.
            budget_tokens: Max total tokens; falls back to default_budget_tokens.
            agent_id: Optional filter for chain_traces (passed to AD-658 surface).
            since: Optional Unix-time lower bound for chain_traces.

        Returns:
            DiagnosticBundle. Never raises.
        """
        budget = max(1, budget_tokens if budget_tokens is not None else self._default_budget_tokens)
        keywords = _extract_keywords(query)

        chain_budget = int(budget * self._chain_trace_ratio)
        procedure_budget = int(budget * self._procedure_ratio)
        episode_budget = budget - chain_budget - procedure_budget  # absorb int-trunc remainder

        truncated = False

        # --- chain traces ----------------------------------------------------
        try:
            since_ts = since.timestamp() if since is not None else None
            chain_rows, chain_truncated = await self._collect_chain_traces(
                keywords=keywords,
                budget_tokens=chain_budget,
                agent_id=agent_id,
                since=since_ts,
            )
        except Exception:
            logger.warning("AD-661: chain_traces collection failed", exc_info=True)
            chain_rows, chain_truncated = [], False
        truncated = truncated or chain_truncated

        # --- procedures + inline exemplars ----------------------------------
        try:
            procedures, exemplar_episode_index, proc_truncated = await self._collect_procedures(
                keywords=keywords,
                budget_tokens=procedure_budget,
            )
        except Exception:
            logger.warning("AD-661: procedure collection failed", exc_info=True)
            procedures, exemplar_episode_index, proc_truncated = [], {}, False
        truncated = truncated or proc_truncated

        # --- episodes (deduped exemplars, keyword-filtered) ------------------
        try:
            episodes, ep_truncated = self._collect_episodes(
                keywords=keywords,
                budget_tokens=episode_budget,
                exemplar_episode_index=exemplar_episode_index,
            )
        except Exception:
            logger.warning("AD-661: episode collection failed", exc_info=True)
            episodes, ep_truncated = [], False
        truncated = truncated or ep_truncated

        # --- total tokens ---------------------------------------------------
        total = sum(self._row_tokens(r) for r in chain_rows) \
              + sum(self._row_tokens(p) for p in procedures) \
              + sum(self._row_tokens(e) for e in episodes)

        return DiagnosticBundle(
            query=query,
            chain_traces=chain_rows,
            procedures=procedures,
            episodes=episodes,
            total_estimated_tokens=total,
            truncated=truncated,
        )

    # --- collectors -----------------------------------------------------------

    async def _collect_chain_traces(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
        agent_id: str | None,
        since: float | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            return [], False
        # Pull a generous slice; budget-clip after filter.
        raw = await journal.get_recent_chain_traces(
            limit=200, agent_id=agent_id, since=since,
        )
        accepted: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for row in raw:
            haystack = " ".join(str(row.get(k) or "") for k in (
                "step_name", "sub_task_type", "intent",
                "error_truncated", "communication_context",
            ))
            if not _matches(haystack, keywords):
                continue
            cost = self._row_tokens(row)
            if used + cost > budget_tokens:
                truncated = True
                break
            accepted.append(row)
            used += cost
        return accepted, truncated

    async def _collect_procedures(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
        store = getattr(self._runtime, "procedure_store", None)
        episodic = getattr(self._runtime, "episodic_memory", None)
        if store is None or not hasattr(store, "list_active"):
            return [], {}, False
        try:
            summaries = await store.list_active()
        except Exception:
            logger.debug("AD-661: list_active failed", exc_info=True)
            return [], {}, False

        procedures: list[dict[str, Any]] = []
        exemplar_index: dict[str, dict[str, Any]] = {}
        used = 0
        truncated = False

        for summary in summaries:
            haystack = " ".join(str(summary.get(k) or "") for k in (
                "name", "description",
            )) + " " + ",".join(summary.get("intent_types", []) or [])
            if not _matches(haystack, keywords):
                continue

            full = None
            try:
                full = await store.get(summary["id"])
            except Exception:
                logger.debug("AD-661: procedure get failed", exc_info=True)
            if full is None:
                continue

            exemplar_dicts: list[dict[str, Any]] = []
            if episodic is not None and getattr(full, "trace_exemplars", None):
                try:
                    eps = await episodic.get_by_ids(list(full.trace_exemplars))
                except Exception:
                    logger.debug("AD-661: get_by_ids failed", exc_info=True)
                    eps = []
                for ep in eps:
                    ep_dict = self._episode_to_dict(ep)
                    if ep_dict["id"] in exemplar_index:
                        continue
                    exemplar_index[ep_dict["id"]] = ep_dict
                    exemplar_dicts.append(ep_dict)

            entry = {
                "id": getattr(full, "id", summary.get("id", "")),
                "name": getattr(full, "name", summary.get("name", "")),
                "description": getattr(full, "description", ""),
                "intent_types": list(getattr(full, "intent_types", []) or []),
                "compilation_level": getattr(full, "compilation_level", 1),
                "exemplar_episodes": exemplar_dicts,
            }
            cost = self._row_tokens(entry)
            if used + cost > budget_tokens:
                truncated = True
                break
            procedures.append(entry)
            used += cost

        return procedures, exemplar_index, truncated

    def _collect_episodes(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
        exemplar_episode_index: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        # v1 source: deduped exemplars across all in-bundle procedures.
        # NO call into EpisodicMemory.recall() — that is semantic search.
        accepted: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for ep_id, ep_dict in exemplar_episode_index.items():
            if not _matches(ep_dict.get("text", ""), keywords):
                continue
            cost = self._row_tokens(ep_dict)
            if used + cost > budget_tokens:
                truncated = True
                break
            accepted.append(ep_dict)
            used += cost
        return accepted, truncated

    # --- helpers ---------------------------------------------------------------

    def _row_tokens(self, row: dict[str, Any]) -> int:
        # Estimate tokens by serializing values to a single string.
        return _estimate_tokens(
            " ".join(str(v) for v in row.values()),
            chars_per_token=self._chars_per_token,
        )

    @staticmethod
    def _episode_to_dict(ep: Any) -> dict[str, Any]:
        return {
            "id": getattr(ep, "id", ""),
            "text": getattr(ep, "text", "") or "",
            "agent_id": getattr(ep, "agent_id", ""),
            "agent_type": getattr(ep, "agent_type", ""),
            "timestamp": getattr(ep, "timestamp", 0.0),
            "importance": getattr(ep, "importance", 0.0),
            "intent_type": getattr(ep, "intent_type", ""),
        }
