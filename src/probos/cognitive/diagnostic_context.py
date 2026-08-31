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

# AD-661b: Ship's Records collection caps
_MAX_RECORDS_CANDIDATES = 30  # absolute cap on records pulled from records_store before token-trim
_RECORDS_READER_ID = "_diagnostic_context_system"  # synthetic privileged reader (sees ship/fleet only)
_RECORDS_CONTENT_EXCERPT_CHARS = 1200  # truncate raw record content before inclusion in bundle dict


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
    is a thin pass-through over journal rows, episode metadata, and record
    excerpts; consumers should treat the bundle as a read-only snapshot.

    `total_estimated_tokens` uses the `len(text) // 4` heuristic — see
    `_estimate_tokens()`.

    AD-661b adds `records` (Ship's Records — AD-434). Empty when
    `runtime.records_store` is None or no records match the query.
    """

    query: str
    chain_traces: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_tokens: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chain_traces": list(self.chain_traces),
            "procedures": list(self.procedures),
            "episodes": list(self.episodes),
            "records": list(self.records),
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
        chain_trace_ratio: float = 0.30,
        procedure_ratio: float = 0.25,
        episode_ratio: float = 0.25,
        records_ratio: float = 0.20,
        chars_per_token: int = CHARS_PER_TOKEN,
        redistribute_remainder: bool = True,
    ) -> None:
        self._runtime = runtime
        self._default_budget_tokens = default_budget_tokens
        self._chain_trace_ratio = chain_trace_ratio
        self._procedure_ratio = procedure_ratio
        self._episode_ratio = episode_ratio
        self._records_ratio = records_ratio
        self._chars_per_token = chars_per_token
        self._redistribute_remainder = redistribute_remainder

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

        AD-661b: 4th tier `records` (Ship's Records). Empty when records_store
        unavailable or no matches.

        AD-661c: When ``redistribute_remainder=True`` (default), unused budget
        from any under-filled tier is redistributed to other tiers in priority
        order (chain_traces > procedures > episodes > records) while
        candidates remain.
        """
        budget = max(
            1,
            budget_tokens if budget_tokens is not None else self._default_budget_tokens,
        )
        keywords = _extract_keywords(query)

        # Per-tier base allocations — episodes absorbs int-trunc remainder of the
        # initial split (mirrors v1 behavior); records is computed last.
        chain_budget = int(budget * self._chain_trace_ratio)
        procedure_budget = int(budget * self._procedure_ratio)
        records_budget = int(budget * self._records_ratio)
        episode_budget = max(
            0, budget - chain_budget - procedure_budget - records_budget,
        )

        # --- gather candidates per tier (all candidates, no per-tier budget clip) ---
        try:
            since_ts = since.timestamp() if since is not None else None
            chain_candidates = await self._gather_chain_trace_candidates(
                keywords=keywords, agent_id=agent_id, since=since_ts,
            )
        except Exception:
            logger.warning("AD-661: chain_traces collection failed", exc_info=True)
            chain_candidates = []

        try:
            proc_entries, exemplar_episode_index = (
                await self._gather_procedure_candidates(keywords=keywords)
            )
        except Exception:
            logger.warning("AD-661: procedure collection failed", exc_info=True)
            proc_entries, exemplar_episode_index = [], {}

        try:
            episode_candidates = self._gather_episode_candidates(
                keywords=keywords,
                exemplar_episode_index=exemplar_episode_index,
            )
        except Exception:
            logger.warning("AD-661: episode collection failed", exc_info=True)
            episode_candidates = []

        try:
            record_candidates = await self._gather_record_candidates(
                keywords=keywords,
            )
        except Exception:
            logger.warning("AD-661: records collection failed", exc_info=True)
            record_candidates = []

        # --- two-pass fill: per-tier allocation, then optional redistribution ---
        candidates_by_tier: dict[str, list[dict[str, Any]]] = {
            "chain_traces": chain_candidates,
            "procedures": proc_entries,
            "episodes": episode_candidates,
            "records": record_candidates,
        }
        allocations: dict[str, int] = {
            "chain_traces": chain_budget,
            "procedures": procedure_budget,
            "episodes": episode_budget,
            "records": records_budget,
        }
        filled, truncated = self._fill_with_redistribution(
            candidates_by_tier=candidates_by_tier,
            allocations=allocations,
            total_budget=budget,
            redistribute=self._redistribute_remainder,
        )

        chain_rows = filled["chain_traces"]
        procedures = filled["procedures"]
        episodes = filled["episodes"]
        records = filled["records"]

        total = (
            sum(self._row_tokens(r) for r in chain_rows)
            + sum(self._row_tokens(p) for p in procedures)
            + sum(self._row_tokens(e) for e in episodes)
            + sum(self._row_tokens(r) for r in records)
        )

        return DiagnosticBundle(
            query=query,
            chain_traces=chain_rows,
            procedures=procedures,
            episodes=episodes,
            records=records,
            total_estimated_tokens=total,
            truncated=truncated,
        )

    # --- collectors -----------------------------------------------------------

    async def _gather_chain_trace_candidates(
        self,
        *,
        keywords: list[str],
        agent_id: str | None,
        since: float | None,
    ) -> list[dict[str, Any]]:
        """AD-661b/c: gather all keyword-matching chain trace rows (no budget clip)."""
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            return []
        raw = await journal.get_recent_chain_traces(
            limit=200, agent_id=agent_id, since=since,
        )
        accepted: list[dict[str, Any]] = []
        for row in raw:
            haystack = " ".join(str(row.get(k) or "") for k in (
                "step_name", "sub_task_type", "intent",
                "error_truncated", "communication_context",
            ))
            if not _matches(haystack, keywords):
                continue
            accepted.append(row)
        return accepted

    async def _gather_procedure_candidates(
        self,
        *,
        keywords: list[str],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """AD-661b/c: gather procedure entries + cross-procedure exemplar index (no budget clip)."""
        store = getattr(self._runtime, "procedure_store", None)
        episodic = getattr(self._runtime, "episodic_memory", None)
        if store is None or not hasattr(store, "list_active"):
            return [], {}
        try:
            summaries = await store.list_active()
        except Exception:
            logger.debug("AD-661: list_active failed", exc_info=True)
            return [], {}

        procedures: list[dict[str, Any]] = []
        exemplar_index: dict[str, dict[str, Any]] = {}

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
                    # AD-1293 (#1200): these exemplars are rendered into the
                    # diagnostic bundle an agent reads, so this rehydration is
                    # EVIDENCE, not history.
                    eps = await episodic.get_by_ids(
                        list(full.trace_exemplars), for_evidence=True,
                    )
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
            procedures.append(entry)

        return procedures, exemplar_index

    def _gather_episode_candidates(
        self,
        *,
        keywords: list[str],
        exemplar_episode_index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """AD-661b/c: deduped exemplars, keyword-filtered (no budget clip).

        Source: deduped exemplars across all in-bundle procedures.
        Explicitly NOT calling ``EpisodicMemory.recall()`` (that is semantic
        search and is out of scope for v1 / AD-661b).
        """
        accepted: list[dict[str, Any]] = []
        for ep_dict in exemplar_episode_index.values():
            if not _matches(ep_dict.get("text", ""), keywords):
                continue
            accepted.append(ep_dict)
        return accepted

    async def _gather_record_candidates(
        self,
        *,
        keywords: list[str],
    ) -> list[dict[str, Any]]:
        """AD-661b: keyword-filter Ship's Records and normalize to flat dicts.

        Reader identity is the synthetic ``_RECORDS_READER_ID`` with empty
        department; this naturally surfaces only ``ship``/``fleet`` records via
        ``RecordsStore.read_entry()``'s built-in classification gate. Per-agent
        record authorization is deferred (AD-661f).

        Hard-caps the candidate list at ``_MAX_RECORDS_CANDIDATES`` before
        token-trim; truncates raw record content to
        ``_RECORDS_CONTENT_EXCERPT_CHARS`` to keep individual records bounded.
        """
        store = getattr(self._runtime, "records_store", None)
        if store is None or not hasattr(store, "list_entries"):
            return []
        try:
            entries = await store.list_entries()
        except Exception:
            logger.debug("AD-661b: list_entries failed", exc_info=True)
            return []

        accepted: list[dict[str, Any]] = []
        for entry in entries:
            fm = entry.get("frontmatter") or {}
            path = entry.get("path") or ""
            title = str(fm.get("title") or path)
            # Keyword phase 1: title — cheap.
            if _matches(title, keywords):
                content_excerpt = await self._read_record_excerpt(store, path)
            else:
                # Keyword phase 2: full content — only if title missed.
                content_excerpt = await self._read_record_excerpt(store, path)
                if not _matches(content_excerpt, keywords):
                    continue
            accepted.append({
                "path": path,
                "title": title,
                "summary_excerpt": content_excerpt,
                "classification": str(fm.get("classification") or "ship"),
                "author": str(fm.get("author") or ""),
                "status": str(fm.get("status") or ""),
                "tags": list(fm.get("tags") or []),
            })
            if len(accepted) >= _MAX_RECORDS_CANDIDATES:
                break
        return accepted

    async def _read_record_excerpt(self, store: Any, path: str) -> str:
        """Read record content via ``read_entry``, truncate to excerpt length.

        Returns empty string on any failure or denial (denied records simply
        do not surface in diagnostic context — same v1 graceful-degradation
        contract).
        """
        try:
            doc = await store.read_entry(
                path,
                reader_id=_RECORDS_READER_ID,
                reader_department="",
            )
        except Exception:
            logger.debug("AD-661b: read_entry failed for %s", path, exc_info=True)
            return ""
        if not doc:
            return ""
        content = str(doc.get("content") or "")
        if len(content) > _RECORDS_CONTENT_EXCERPT_CHARS:
            content = content[:_RECORDS_CONTENT_EXCERPT_CHARS]
        return content

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

    # --- AD-661c: budget allocation + redistribution -------------------------

    # Priority order for redistribution: chain traces are richest diagnostic
    # signal; records the broadest. Order is deliberately stable — used by both
    # tests and the redistribution loop.
    _TIER_PRIORITY: tuple[str, ...] = (
        "chain_traces", "procedures", "episodes", "records",
    )

    def _fill_with_redistribution(
        self,
        *,
        candidates_by_tier: dict[str, list[dict[str, Any]]],
        allocations: dict[str, int],
        total_budget: int,
        redistribute: bool,
    ) -> tuple[dict[str, list[dict[str, Any]]], bool]:
        """Two-pass fill across tiers, optional remainder redistribution.

        Pass 1: each tier fills up to its allocated budget in priority order.
        Pass 2 (only when ``redistribute`` is True): walk tiers in priority
        order again, topping up tiers that have remaining candidates while the
        global budget still has room.

        Returns ``(filled_by_tier, truncated)``. ``truncated`` is True iff the
        global budget is exhausted AND at least one tier still has unconsumed
        candidates.
        """
        filled: dict[str, list[dict[str, Any]]] = {
            tier: [] for tier in self._TIER_PRIORITY
        }
        consumed_index: dict[str, int] = {tier: 0 for tier in self._TIER_PRIORITY}
        used_total = 0

        # Pass 1 — per-tier hard allocation.
        for tier in self._TIER_PRIORITY:
            tier_budget = max(0, int(allocations.get(tier, 0)))
            candidates = candidates_by_tier.get(tier, [])
            tier_used = 0
            idx = 0
            while idx < len(candidates):
                cost = self._row_tokens(candidates[idx])
                if tier_used + cost > tier_budget:
                    break
                filled[tier].append(candidates[idx])
                tier_used += cost
                used_total += cost
                idx += 1
            consumed_index[tier] = idx

        # Pass 2 — optional redistribution of the unused remainder.
        if redistribute and used_total < total_budget:
            for tier in self._TIER_PRIORITY:
                candidates = candidates_by_tier.get(tier, [])
                idx = consumed_index[tier]
                while idx < len(candidates) and used_total < total_budget:
                    cost = self._row_tokens(candidates[idx])
                    if used_total + cost > total_budget:
                        break
                    filled[tier].append(candidates[idx])
                    used_total += cost
                    idx += 1
                consumed_index[tier] = idx
                if used_total >= total_budget:
                    break

        # Truncated iff budget exhausted AND at least one tier still has
        # candidates left over.
        truncated = any(
            consumed_index[tier] < len(candidates_by_tier.get(tier, []))
            for tier in self._TIER_PRIORITY
        )
        return filled, truncated
