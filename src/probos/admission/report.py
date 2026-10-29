"""AD-1346 M3b (#1604): the read-only queries over ``admission_shadow.db`` (#1601, evidence 2, 7 and 8).

``REPORT_QUERIES`` maps each frozen name to one SELECT. A later slice may add a name; none is
renamed or removed, so the queries the M4 ruling runs keep the names this slice gives them (#1604).
``run_query`` runs one on a connection its caller opened; ``open_read_only`` opens the file with
SQLite's ``mode=ro`` (BF-906), on which every write raises. ``p99_bucket`` reads a latency
histogram built from ``latency_by_work_kind``. No module in ``src`` imports this one.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from probos.storage.sqlite_factory import default_factory

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from probos.protocols import DatabaseConnection

#: AD-1346 M3b (D49): the frozen query names, in order, and their SQL. Append-only.
REPORT_QUERIES: Final[Mapping[str, str]] = MappingProxyType({
    "decisions_by_work_kind": (
        "SELECT work_kind, outcome, reason_code, SUM(decisions) FROM shadow_aggregates WHERE day >= ? "
        "GROUP BY work_kind, outcome, reason_code ORDER BY work_kind, outcome, reason_code"
    ),
    "latency_by_work_kind": (
        "SELECT work_kind, latency_bucket, SUM(decisions) FROM shadow_aggregates WHERE day >= ? "
        "GROUP BY work_kind, latency_bucket ORDER BY work_kind, latency_bucket"
    ),
    "would_refuse_samples": (
        "SELECT seq, boot_id, hour, work_kind, seam, reason_code, latency_ns, verdict_json FROM shadow_samples "
        "ORDER BY seq DESC LIMIT ?"
    ),
    "markers_by_boot": (
        "SELECT boot_id, MIN(hour), MAX(hour), SUM(offered), SUM(written), SUM(dropped), SUM(samples_dropped) "
        "FROM shadow_markers GROUP BY boot_id ORDER BY MIN(hour), boot_id"
    ),
    "days_recorded": "SELECT DISTINCT day FROM shadow_aggregates ORDER BY day",
    "schema_version": "SELECT version FROM schema_version",
})


async def run_query(db: DatabaseConnection, name: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    """The rows of the query ``name`` with ``params``, as tuples.

    Raises ``ValueError`` before ``db`` is used when ``name`` is not an exact ``str`` that
    ``REPORT_QUERIES`` holds. An error from ``params`` or from SQLite propagates.
    """
    if type(name) is not str:
        raise ValueError(f"AD-1346 M3b: a shadow report query name is a str, not {type(name).__name__}")
    if name not in REPORT_QUERIES:
        raise ValueError(f"AD-1346 M3b: no shadow report query named {name!r}")
    async with db.execute(REPORT_QUERIES[name], tuple(params)) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


async def open_read_only(db_path: str | Path) -> DatabaseConnection:
    """A ``mode=ro`` connection to ``db_path`` from the default factory; a missing file raises (BF-906)."""
    return await default_factory.connect(str(db_path), read_only=True)


def p99_bucket(counts: Sequence[int]) -> int | None:
    """The first bucket whose running count reaches 99% of the total, or None when the counts sum to zero or less.

    Bucket b below the last holds ``decide`` times t with ``t.bit_length() == b`` (bucket 0 holds
    0 ns), so 99% of the counted times are below 2**b ns; the last bucket also holds longer times.
    """
    total = sum(counts)
    if total <= 0:
        return None
    running = 0
    for bucket, count in enumerate(counts):
        running += count
        if running * 100 >= total * 99:
            return bucket
    return None
