"""Context Provenance Metadata (AD-677).

Tags each result the ``oracle_query`` tool hands an agent with its source tier,
its retrieval relevance and, where the tier's store records when the entry was
written, the entry's own age and a staleness flag.

BF-950: the age was measured from the retrieval, which happens in the same call
that renders the marker, so every marker read ``age:0s`` and ``STALE`` never
appeared. The age is now the content's, read from the write time its tier
records (:func:`entry_write_time`); a tier that records none shows no age.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

logger = logging.getLogger(__name__)

#: BF-950: content older than this is marked ``STALE``. Thirty days: the tiers
#: that record a write time hold standing reference material (records, the
#: archive, the semantic index, past episodes), so a threshold in minutes would
#: mark nearly every entry and the flag would say nothing. A module constant, as
#: the Oracle tool's tier list and bounds are; ``_ORACLE_DISPOSITION`` states it
#: to agents in words, and a test holds the two together.
STALE_AFTER_SECONDS: Final = 30 * 86400.0

#: BF-950: the metadata key under which each tier records its entry's write
#: time. ``records`` keeps it in the entry's frontmatter (:func:`record_write_time`).
#: ``graph`` and ``health`` record none in their results, so they show no age.
_TIER_WRITE_TIME_KEYS: Final[dict[str, str]] = {
    "episodic": "timestamp",
    "operational": "timestamp",
    "archive": "archived_at",
    "semantic": "indexed_at",
}

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=timezone.utc)
#: The last second of 9999-12-31 UTC: a later write time is not a date.
_MAX_POSIX_SECONDS: Final = 253402300799.0


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _posix_seconds(value: Any) -> float | None:
    """BF-950: ``value`` as positive, finite POSIX seconds no later than 9999, or ``None``.

    A number, a ``datetime``, a ``date`` (midnight UTC) or ISO-8601 text. A naive
    datetime, or text without an offset, is read as UTC: the store writes aware
    UTC times, and a hand-written entry names no zone. A bool, any other type,
    and text that is not ISO-8601 give ``None``. Nothing here raises, so one
    malformed entry cannot empty a result.
    """
    try:
        if type(value) is bool:
            return None
        if isinstance(value, (int, float)):
            seconds = float(value)
        elif isinstance(value, datetime):
            seconds = _as_utc(value).timestamp()
        elif isinstance(value, date):
            seconds = datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
        elif isinstance(value, str):
            seconds = _as_utc(datetime.fromisoformat(value.strip())).timestamp()
        else:
            return None
    except (OverflowError, ValueError, TypeError):
        return None
    if not math.isfinite(seconds) or seconds <= 0 or seconds > _MAX_POSIX_SECONDS:
        return None
    return seconds


def record_write_time(frontmatter: Any) -> float | None:
    """BF-950: when a Ship's Records entry was last written, as POSIX seconds, or ``None``.

    Its frontmatter's ``updated``, else its ``created``: ``RecordsStore.write_entry``
    sets both on a first write and ``updated`` on every revision.
    """
    if type(frontmatter) is not dict:
        return None
    updated = _posix_seconds(frontmatter.get("updated"))
    return updated if updated is not None else _posix_seconds(frontmatter.get("created"))


def entry_write_time(source_tier: str, metadata: Any) -> float | None:
    """BF-950: when an Oracle result's content was written to its tier, or ``None``.

    Read from the key :data:`_TIER_WRITE_TIME_KEYS` names, or for ``records``
    from the frontmatter. A tier not named there, and a value that does not
    parse, give ``None``.
    """
    if type(metadata) is not dict:
        return None
    if source_tier == "records":
        return record_write_time(metadata.get("frontmatter"))
    key = _TIER_WRITE_TIME_KEYS.get(source_tier)
    return None if key is None else _posix_seconds(metadata.get(key))


def iso_utc(seconds: float) -> str:
    """BF-950: POSIX ``seconds`` as ISO-8601 UTC to the second, e.g. ``2026-05-03T10:00:00+00:00``.

    By arithmetic from the epoch, so every value :func:`record_write_time`
    returns renders on every platform (``datetime.fromtimestamp`` is bounded by
    the C library, on Windows at the year 3000).
    """
    return (_EPOCH + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _is_stale(age: float | None) -> bool:
    return age is not None and age > STALE_AFTER_SECONDS


def _format_age(seconds: float) -> str:
    """``45s``, ``12m``, ``5h`` or ``184d``, each rounded down."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


@dataclass(frozen=True)
class ProvenanceTag:
    """Metadata tag for a single piece of injected context."""

    source_tier: str
    #: When the entry was retrieved. Not rendered (BF-950): the retrieval is the
    #: call that renders the marker, so its age says nothing about the entry.
    retrieval_timestamp: float
    #: AD-1294 (#1090): how well the entry MATCHED THE QUERY, not how strongly
    #: its author holds it. Named ``confidence`` until it was found rendering
    #: ``OracleResult.score`` under that label straight into agent context.
    relevance: float
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)
    #: BF-950: when the content was written to its tier, as POSIX seconds, or
    #: ``None`` when the tier records no write time (:func:`entry_write_time`).
    content_timestamp: float | None = None

    @property
    def age_seconds(self) -> float | None:
        """BF-950: how old the content is, or ``None`` with no recorded write time.

        A write time in the future (a skewed clock) reads as 0.
        """
        if self.content_timestamp is None:
            return None
        return max(0.0, time.time() - self.content_timestamp)

    @property
    def is_stale(self) -> bool:
        """BF-950: whether the content is older than :data:`STALE_AFTER_SECONDS`; False with no age."""
        return _is_stale(self.age_seconds)

    def format_inline(self) -> str:
        """Format as an inline provenance marker for prompt injection.

        Examples: ``[source:records relevance:0.82 age:184d STALE]``, and for a
        tier that records no write time ``[source:graph relevance:0.70]``.
        """
        marker = f"[source:{self.source_tier} relevance:{self.relevance:.2f}"
        age = self.age_seconds
        if age is not None:
            marker += f" age:{_format_age(age)}"
            if _is_stale(age):
                marker += " STALE"
        return marker + "]"


def compute_content_hash(content: str) -> str:
    """Compute a short hash of content for dedup detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:8]


@dataclass
class ProvenanceEnvelope:
    """Wraps content with its provenance tag (AD-677).

    Built by :func:`query_with_provenance`, whose one production caller is the
    ``oracle_query`` tool (``tools/oracle_query_tool.py``).
    """

    content: str
    tag: ProvenanceTag

    def render(self) -> str:
        """Render content with inline provenance marker."""
        return f"{self.tag.format_inline()}\n{self.content}"

    @classmethod
    def from_oracle_result(cls, result: Any) -> "ProvenanceEnvelope":
        """Create from an ``oracle_service.OracleResult``.

        BF-950: the tag carries the content's own write time, read from the
        result's tier metadata (:func:`entry_write_time`); the retrieval time is
        kept and not rendered.
        """
        return cls(
            content=result.content,
            tag=ProvenanceTag(
                source_tier=result.source_tier,
                retrieval_timestamp=time.time(),
                relevance=result.score,
                content_hash=compute_content_hash(result.content),
                metadata=result.metadata,
                content_timestamp=entry_write_time(result.source_tier, result.metadata),
            ),
        )


async def query_with_provenance(
    oracle: Any,
    *,
    query_text: str = "",
    agent_id: str = "",
    intent_type: str = "",
    k_per_tier: int = 5,
    tiers: list[str] | None = None,
) -> list[ProvenanceEnvelope]:
    """Query Oracle and wrap results with provenance metadata (AD-677)."""
    try:
        results = await oracle.query(
            query_text=query_text or intent_type or "ambient",
            agent_id=agent_id,
            intent_type=intent_type,
            k_per_tier=k_per_tier,
            tiers=tiers,
        )
        return [ProvenanceEnvelope.from_oracle_result(result) for result in results]
    except Exception:
        logger.debug(
            "AD-677: Provenance-tagged query failed; returning empty envelope list "
            "so context injection can continue without provenance metadata.",
            exc_info=True,
        )
        return []
