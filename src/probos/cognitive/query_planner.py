"""Memvid pattern 1: route relational queries to structured anchor lookup
before falling back to semantic similarity.

Classification rules (deterministic, regex-driven, no LLM):

  WHO    : "who works at X" / "who belongs to X" / "who is on/in X" / "who reports to X"
           → anchor.department or anchor.participants
  WHERE  : "where is X" / "where did X" / "where was X"
           → anchor.channel
  WHEN   : "when did X" / "when happened X" / "when was X"
           → anchor.watch_section / time_range (semantic carry-through)

A relational match emits a ``QueryPlan`` with the ``relational`` flag set
and the resolved anchor kwargs. The caller (recall pipeline) hands those
kwargs to ``EpisodicMemory.recall_by_anchor``. If the structured lookup
returns nothing, the caller falls back to ``recall(query, k)``.

Out of scope (memvid follow-ups):
  - VersionRelation enum (memvid pattern 2 — file as memvid-versionrelation-v1)
  - per-engine-version enrichment (memvid pattern 3 — file as memvid-engineversion-v1)

Wave 130. Issue #490.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

QueryShape = str
"""One of: ``RELATIONAL_WHO`` | ``RELATIONAL_WHERE`` | ``RELATIONAL_WHEN`` | ``SEMANTIC``."""


@dataclass(frozen=True)
class QueryPlan:
    """The classifier's verdict + the structured anchor kwargs to apply."""

    shape: QueryShape
    relational: bool
    anchor_kwargs: dict[str, Any] = field(default_factory=dict)


_WHO_RE = re.compile(
    r"\bwho\b.*?\b(works at|belongs to|is (?:on|in)|reports to)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(
    r"\bwhere\b.*?\b(?:is|did|was)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)
_WHEN_RE = re.compile(
    r"\bwhen\b.*?\b(?:did|happened|was)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)

_TRIM_TRAILING = " ?.!,;"


def _clean_target(raw: str) -> str:
    """Strip whitespace + trailing punctuation/courtesy words from a captured target."""
    s = raw.strip().rstrip(_TRIM_TRAILING).strip()
    # Drop trailing courtesy fragments ("please", "now").
    for tail in (" please", " now"):
        if s.lower().endswith(tail):
            s = s[: -len(tail)]
    return s.rstrip(_TRIM_TRAILING).strip()


class QueryPlanner:
    """Classify a query and produce a recall plan.

    Public API:
      - classify(query) -> QueryPlan
      - async recall_with_fallback(episodic, query, k) -> list
    """

    def classify(self, query: str) -> QueryPlan:
        text = query.strip()
        if not text:
            return QueryPlan(shape="SEMANTIC", relational=False)

        m = _WHO_RE.search(text)
        if m:
            target = _clean_target(m.group(2))
            if not target:
                return QueryPlan(shape="SEMANTIC", relational=False)
            # Heuristic: short single-token target = department; multi-word = participant callsign
            if " " in target:
                return QueryPlan(
                    shape="RELATIONAL_WHO",
                    relational=True,
                    anchor_kwargs={"participants": [target], "semantic_query": text},
                )
            return QueryPlan(
                shape="RELATIONAL_WHO",
                relational=True,
                anchor_kwargs={"department": target.lower(), "semantic_query": text},
            )

        m = _WHERE_RE.search(text)
        if m:
            target = _clean_target(m.group(1))
            if not target:
                return QueryPlan(shape="SEMANTIC", relational=False)
            return QueryPlan(
                shape="RELATIONAL_WHERE",
                relational=True,
                anchor_kwargs={"channel": target.lower(), "semantic_query": text},
            )

        m = _WHEN_RE.search(text)
        if m:
            return QueryPlan(
                shape="RELATIONAL_WHEN",
                relational=True,
                anchor_kwargs={"semantic_query": text},
            )

        return QueryPlan(shape="SEMANTIC", relational=False)

    async def recall_with_fallback(
        self,
        episodic: Any,
        query: str,
        k: int = 5,
    ) -> list[Any]:
        """Run the planned lookup; fall back to semantic on empty.

        Always returns a list (possibly empty). Never raises on classification.
        Anchor-lookup failure is logged at warning level (degraded operation)
        and the call falls through to the semantic path.
        """
        plan = self.classify(query)
        if plan.relational:
            try:
                results = await episodic.recall_by_anchor(
                    limit=k, **plan.anchor_kwargs
                )
                if results:
                    logger.debug(
                        "Memvid: %s -> %d episodes via anchor lookup",
                        plan.shape,
                        len(results),
                    )
                    return list(results)
            except Exception:
                logger.warning(
                    "Memvid: anchor lookup raised, falling back to semantic recall",
                    exc_info=True,
                )
        return list(await episodic.recall(query, k=k))
