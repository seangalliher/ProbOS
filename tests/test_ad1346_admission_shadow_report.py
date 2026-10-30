"""AD-1346 M3b (#1604): the frozen, read-only report queries over a written ``admission_shadow.db``.

- Q1 the query names are frozen, in order, each one SELECT, and the mapping is read-only.
- Q2 each query answers on a ``mode=ro`` connection to a written store, and a ``DELETE`` from one of the store's tables on it raises.
- Q3 a query name that is not an exact ``str`` the mapping holds is a ``ValueError``, before the connection is used.
- Q4 ``p99_bucket`` is the first bucket whose running count reaches 99% of the total.
- Q5 the module holds no write or schema statement.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.admission.report import REPORT_QUERIES, open_read_only, p99_bucket, run_query
from probos.admission.store import STORE_FILENAME, AdmissionShadowStore, ShadowBatch, ShadowSample, utc_hour
from probos.admission.taxonomy import LATENCY_BUCKETS
from tests.fixtures.ad1346_shadow import HOUR, T0, refuse


class _Str(str):
    """A ``str`` subclass, which is not an exact ``str``."""


def test_the_query_names_are_frozen_and_each_is_one_select() -> None:
    """Q1."""
    assert tuple(REPORT_QUERIES) == (
        "decisions_by_work_kind", "latency_by_work_kind", "would_refuse_samples", "markers_by_boot",
        "days_recorded", "schema_version", "parity_by_work_kind", "disagreement_samples",
        "ticket_findings_by_operation", "ticket_samples", "ticket_missing_samples", "ticket_markers_by_boot",
        "ticket_days_recorded",
    )
    for name, sql in REPORT_QUERIES.items():
        assert sql.startswith("SELECT ") and ";" not in sql, name
    with pytest.raises(TypeError):
        REPORT_QUERIES["another"] = "SELECT 1"  # type: ignore[index]


async def test_every_query_runs_on_a_read_only_connection_to_a_written_store(tmp_path: Path) -> None:
    """Q2 (kills RP-4, RP-5)."""
    first, second = utc_hour(T0), utc_hour(T0 + HOUR)
    store = AdmissionShadowStore(data_dir=tmp_path / "data")
    await store.start()
    try:
        await store.write_batch("boot-a", ShadowBatch(
            aggregates={
                (first, "intent", "intent", "would_refuse", "identity_unresolved", 10): 3,
                (first, "intent", "intent", "admit", "admitted", 3): 1,
                (second, "tool_call", "tool", "admit", "admitted", 0): 2,
            },
            samples=[ShadowSample(first, T0, refuse(), 1000), ShadowSample(first, T0 + 1, refuse(), 900)],
            offered={first: 4, second: 3},
            dropped={second: 1},
            samples_dropped={first: 1},
        ))
    finally:
        await store.stop()
    db = await open_read_only(tmp_path / "data" / STORE_FILENAME)
    try:
        assert await run_query(db, "decisions_by_work_kind", ("2026-10-28",)) == [
            ("intent", "admit", "admitted", 1),
            ("intent", "would_refuse", "identity_unresolved", 3),
            ("tool_call", "admit", "admitted", 2),
        ]
        assert await run_query(db, "decisions_by_work_kind", ("2026-10-29",)) == []
        latency = await run_query(db, "latency_by_work_kind", ("2026-10-28",))
        assert latency == [("intent", 3, 1), ("intent", 10, 3), ("tool_call", 0, 2)]
        histogram = [0] * LATENCY_BUCKETS
        for work_kind, bucket, count in latency:
            if work_kind == "intent":
                histogram[bucket] += count
        assert p99_bucket(histogram) == 10
        samples = await run_query(db, "would_refuse_samples", (1,))
        assert [row[6] for row in samples] == [900], "the newest sample first"
        assert await run_query(db, "markers_by_boot") == [("boot-a", first, second, 7, 6, 1, 1)]
        assert await run_query(db, "days_recorded") == [("2026-10-28",)]
        assert await run_query(db, "schema_version") == [(1,)]
        with pytest.raises(sqlite3.OperationalError):
            await db.execute("DELETE FROM shadow_markers")
    finally:
        await db.close()


@pytest.mark.parametrize(
    "name",
    ["nope", ["decisions_by_work_kind"], {"days_recorded": 1}, None, _Str("days_recorded")],
    ids=["unknown", "list", "mapping", "none", "str-subclass"],
)
async def test_a_query_name_that_is_not_a_known_exact_str_is_a_value_error(name: Any) -> None:
    """Q3: refused before the connection is used (kills RP-1)."""
    with pytest.raises(ValueError, match="shadow report query"):
        await run_query(None, name)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("counts", "expected"),
    [([], None), ([0, 0], None), ([7], 0), ([99, 1], 0), ([98, 0, 2], 2), ([0] * 39 + [5], 39)],
    ids=["empty", "zeros", "one-bucket", "exactly-99", "tail", "last-bucket"],
)
def test_p99_bucket_is_the_first_bucket_reaching_99_percent(counts: list[int], expected: int | None) -> None:
    """Q4 (kills RP-2, RP-3)."""
    assert p99_bucket(counts) == expected


def test_the_report_module_holds_no_write_or_schema_statement() -> None:
    """Q5: no string constant in the module begins with a write or schema keyword."""
    source = (Path(probos.__file__).resolve().parent / "admission" / "report.py").read_text(encoding="utf-8")
    words = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE", "PRAGMA", "ATTACH", "VACUUM")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.lstrip().upper().startswith(words), node.value[:40]
