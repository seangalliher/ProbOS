"""AD-1346 M3d3b1 (#1604): the work ticket's persisted record, four tables in ``admission_shadow.db``, over real
SQLite in ``tmp_path``.

``AdmissionShadowStore.write_batch`` writes a batch's work-ticket part (``TicketBatch``) in the transaction of its
verdicts: finding counts per (UTC day, operation, code, work kind, ``off_loop``), two sample rings (the batch's
``missing`` samples in ``ticket_missing_samples``, its other samples in ``ticket_samples``) and marker rows per (boot,
UTC hour); ``prune`` bounds the counts and the markers. In ``src`` the recorder, the one caller of ``write_batch``,
builds each batch without a work-ticket part, so that part is the empty default until AD-1346 M3d3b2 adds the
recorder's offers. The tests that write the part build it directly, with findings from a real ``TicketRegistry``
over a real ``AgentStopService`` under ``tmp_path`` or built as ``TicketFinding`` values, and read it back with SQL
or with the report's queries.

- TR1 a new file gets the four ticket tables beside the six earlier ones, each with its columns, NOT NULL and key.
- TR2 a batch adds finding counts by UTC day and writes each ring's sample as ``persisted_finding`` JSON, with the raw
      ticket id in no ring row; its marker rows hold the batch's offered, dropped and samples-dropped counts and the
      findings it wrote; it adds no verdict marker and returns 0, and a second write adds to each count and marker row.
- TR3 each ring keeps at most its own size of its newest rows, and a write to the missing ring alone leaves the other.
- TR4 a batch whose write fails on a NULL boot id is rolled back: a later commit lands none of its ticket rows.
- TR5 ``prune`` deletes the finding days and marker hours before the window and then the oldest markers beyond
      ``MARKER_ROW_LIMIT``; it leaves the rings, and the counts it returns leave the work-ticket rows out.
- TR6 the ring sizes and the digest length are named constants, and 35 days of the ticket key space stay below
      ``AGGREGATE_ROW_LIMIT``.
- TR7 on a version-1 file without the ticket tables each ``ticket_`` report query raises ``sqlite3.OperationalError``
      on a read-only connection; ``start`` then keeps the file's rows and adds the tables.
- TR8 the five ``ticket_`` report queries answer on a ``mode=ro`` connection to a store two boots wrote, each ring's
      newest sample first and one marker row per boot, with the marker rows of hours that have only a dropped or only
      a samples-dropped count; a delete on it raises.
- TR9 ``persisted_finding`` shows the ticket and parent ids as ``ticket_digest`` in their fields and, where they have
      the registry's form (32 lowercase hex characters), in the cause; an id of another alphabet, length or case stays
      in the cause as it is, and every other value, the stop's id included, is the finding's.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from probos.admission import store as store_module
from probos.admission.report import REPORT_QUERIES, open_read_only, run_query
from probos.admission.store import (
    AGGREGATE_RETENTION_DAYS,
    AGGREGATE_ROW_LIMIT,
    DAY_SECONDS,
    SCHEMA_VERSION,
    TICKET_DIGEST_CHARS,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    TicketBatch,
    TicketSample,
    persisted_finding,
    ticket_digest,
    utc_hour,
)
from probos.admission.taxonomy import SEAM_MODEL_CALL, TICKET_REASON_CODES, WORK_KINDS
from probos.admission.tickets import (
    TICKET_EFFECTS,
    TICKET_FINDING_KEYS,
    TICKET_OPERATIONS,
    TicketBudget,
    TicketFinding,
    TicketRegistry,
    TicketScope,
)
from probos.agent_stop import AgentStopService
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.ad1346_shadow import HOUR, T0, rows

BOOT = "boot-a"
AGENT = "ad1346-m3d3b1-agent"
DAY = "2026-10-28"
TABLES = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
SHADOW_TABLES = [
    ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",), ("shadow_parity",),
    ("shadow_samples",),
]
TICKET_TABLE_NAMES = [("ticket_findings",), ("ticket_markers",), ("ticket_missing_samples",), ("ticket_samples",)]
SAMPLE_COLUMNS = ["seq", "boot_id", "hour", "recorded_at", "operation", "code", "work_kind", "off_loop", "finding_json"]
#: (table, its columns in order, its primary key's columns in key order).
TICKET_TABLES = (
    (
        "ticket_findings",
        ["day", "operation", "code", "work_kind", "off_loop", "findings"],
        ["day", "operation", "code", "work_kind", "off_loop"],
    ),
    ("ticket_samples", SAMPLE_COLUMNS, ["seq"]),
    ("ticket_missing_samples", SAMPLE_COLUMNS, ["seq"]),
    ("ticket_markers", ["boot_id", "hour", "offered", "written", "dropped", "samples_dropped"], ["boot_id", "hour"]),
)
FINDINGS = (
    "SELECT day, operation, code, work_kind, off_loop, findings FROM ticket_findings "
    "ORDER BY operation, code, work_kind, off_loop"
)
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM ticket_markers ORDER BY hour"
SAMPLE_READ = "boot_id, hour, recorded_at, operation, code, work_kind, off_loop, finding_json"
#: The ``ticket_`` report queries and the parameters each takes.
TICKET_QUERIES = {
    "ticket_findings_by_operation": (DAY,), "ticket_samples": (1,), "ticket_missing_samples": (1,),
    "ticket_markers_by_boot": (), "ticket_days_recorded": (),
}
_SCOPE = TicketScope(frozenset(TICKET_EFFECTS))


def _with_tickets(tickets: TicketBatch) -> ShadowBatch:
    """A batch whose verdict part is empty."""
    return ShadowBatch({}, [], {}, {}, {}, tickets=tickets)


def _missing() -> TicketFinding:
    return TicketFinding(SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT)


def _unknown() -> TicketFinding:
    return TicketFinding("tool", "ticket_unknown", "The presented object is not a ticket the registry holds.")


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


async def test_a_new_file_gets_the_four_ticket_tables_with_their_columns_and_keys(store: AdmissionShadowStore) -> None:
    """TR1 (kills TRX-1)."""
    assert await rows(store.path, TABLES) == sorted(SHADOW_TABLES + TICKET_TABLE_NAMES)
    for table, columns, key in TICKET_TABLES:
        info = await rows(store.path, f"PRAGMA table_info({table})")
        assert [column[1] for column in info] == columns, table
        assert [column[1] for column in sorted(info, key=lambda column: column[5]) if column[5]] == key, table
        assert all(column[3] == 1 for column in info if column[1] != "seq"), table
    assert await rows(store.path, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]


async def test_a_batch_writes_ticket_findings_by_day_their_samples_and_their_markers(
    store: AdmissionShadowStore, stops: AgentStopService,
) -> None:
    """TR2 (kills TRX-2, TRX-3, TRX-5, TRX-8, TRX-17): findings from a real registry under a real Captain's stop."""
    registry = TicketRegistry(stops, max_depth=1, clock=lambda: 1_000.0)
    issued = registry.issue(
        principal_key=AGENT, work_kind="agentic_run", seam="agentic_run", scope=_SCOPE, budget=TicketBudget(),
    )
    assert issued.ticket is not None, "premise: the registry issued the ticket"
    raw = issued.ticket.ticket_id
    missing = registry.check(None, effect=SEAM_MODEL_CALL, presented_key=AGENT)
    stop = await stops.issue_stop(AGENT, reason="ad1346-m3d3b1: a stop whose finding a ring keeps")
    revoked = registry.check(issued.ticket, effect=SEAM_MODEL_CALL, presented_key=AGENT)
    assert (missing.code, revoked.code, revoked.stop_id) == ("ticket_missing", "ticket_revoked", stop.record.stop_id)
    assert raw in revoked.cause, "premise: the registry's cause names the ticket's id"
    first, second = utc_hour(T0), utc_hour(T0 + HOUR)
    batch = _with_tickets(TicketBatch(
        findings={
            (first, "issue", "ticket_issued", "agentic_run", False): 1,
            (first, "tool", "ticket_live", "agentic_run", False): 2,
            (first, "model_call", "ticket_missing", "", True): 3,
            (second, "model_call", "ticket_revoked", "agentic_run", False): 1,
        },
        samples=[TicketSample(second, T0 + HOUR, revoked, False)],
        missing=[TicketSample(first, T0, missing, True)],
        offered={first: 6, second: 2},
        dropped={second: 1},
        samples_dropped={first: 1},
    ))
    assert await store.write_batch(BOOT, batch) == 0, "the number returned counts verdicts only"
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "agentic_run", 0, 1),
        (DAY, "model_call", "ticket_missing", "", 1, 3),
        (DAY, "model_call", "ticket_revoked", "agentic_run", 0, 1),
        (DAY, "tool", "ticket_live", "agentic_run", 0, 2),
    ]
    assert await rows(store.path, MARKERS) == [(BOOT, first, 6, 6, 0, 1), (BOOT, second, 2, 1, 1, 0)]
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_markers") == [(0,)], "no verdict marker is added"
    kept = await rows(store.path, f"SELECT {SAMPLE_READ} FROM ticket_samples")
    assert [row[:7] for row in kept] == [(BOOT, second, T0 + HOUR, "model_call", "ticket_revoked", "agentic_run", 0)]
    body = json.loads(kept[0][7])
    assert list(body) == list(TICKET_FINDING_KEYS) and body == persisted_finding(revoked)
    assert kept[0][7] == json.dumps(body, separators=(",", ":")), "the ring keeps compact JSON"
    assert (body["ticket_id"], body["stop_id"], body["principal_key"]) == (ticket_digest(raw), stop.record.stop_id, AGENT)
    noted = await rows(store.path, f"SELECT {SAMPLE_READ} FROM ticket_missing_samples")
    assert [row[:7] for row in noted] == [(BOOT, first, T0, "model_call", "ticket_missing", "", 1)]
    assert json.loads(noted[0][7]) == missing.to_dict(), "a finding with no ticket id is kept as it is"
    assert all(raw not in row[7] for row in kept + noted), "the raw ticket id is in no ring row"
    assert await store.write_batch(BOOT, batch) == 0
    assert [row[-1] for row in await rows(store.path, FINDINGS)] == [2, 6, 2, 4], "a second write adds to each row"
    assert await rows(store.path, MARKERS) == [(BOOT, first, 12, 12, 0, 2), (BOOT, second, 4, 2, 2, 0)]


async def test_the_two_ticket_rings_each_keep_their_newest_rows(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TR3 (kills TRX-4, TRX-6, TRX-7)."""
    monkeypatch.setattr(store_module, "TICKET_SAMPLE_RING_SIZE", 2)
    monkeypatch.setattr(store_module, "TICKET_MISSING_RING_SIZE", 3)
    others_read = "SELECT recorded_at FROM ticket_samples ORDER BY seq"
    missing_read = "SELECT recorded_at FROM ticket_missing_samples ORDER BY seq"
    hour = utc_hour(T0)
    others = [TicketSample(hour, T0 + n, _unknown(), False) for n in range(3)]
    missing = [TicketSample(hour, T0 + n, _missing(), False) for n in range(8)]
    await store.write_batch(BOOT, _with_tickets(TicketBatch(samples=others[:1], missing=missing[:4])))
    await store.write_batch(BOOT, _with_tickets(TicketBatch(samples=others[1:], missing=missing[4:5])))
    assert await rows(store.path, others_read) == [(T0 + 1,), (T0 + 2,)]
    assert await rows(store.path, missing_read) == [(T0 + 2,), (T0 + 3,), (T0 + 4,)]
    await store.write_batch(BOOT, _with_tickets(TicketBatch(missing=missing[5:])))
    assert await rows(store.path, others_read) == [(T0 + 1,), (T0 + 2,)], "a write to one ring leaves the other"
    assert await rows(store.path, missing_read) == [(T0 + 5,), (T0 + 6,), (T0 + 7,)]


async def test_a_failed_batch_rolls_back_its_ticket_rows_and_a_later_commit_does_not_land_them(
    store: AdmissionShadowStore,
) -> None:
    """TR4: a NULL boot id fails the batch's write (the shape of S4)."""
    hour = utc_hour(T0)
    failing = TicketBatch(
        findings={(hour, "tool", "ticket_live", "agentic_run", False): 5},
        missing=[TicketSample(hour, T0, _missing(), False)],
        offered={hour: 5},
    )
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        await store.write_batch(None, _with_tickets(failing))  # type: ignore[arg-type]
    later = TicketBatch(findings={(hour, "tool", "ticket_live", "agentic_run", False): 1}, offered={hour: 1})
    assert await store.write_batch(BOOT, _with_tickets(later)) == 0
    assert await rows(store.path, "SELECT findings FROM ticket_findings") == [(1,)]
    assert await rows(store.path, "SELECT COUNT(*) FROM ticket_missing_samples") == [(0,)]
    assert await rows(store.path, "SELECT boot_id, offered, written FROM ticket_markers") == [(BOOT, 1, 1)]


async def test_prune_deletes_old_ticket_days_and_markers_and_leaves_the_rings(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TR5 (kills TRX-9, TRX-10, TRX-11)."""
    old, kept, today = utc_hour(T0 - 35 * DAY_SECONDS), utc_hour(T0 - 34 * DAY_SECONDS), utc_hour(T0)
    assert (old, kept) == ("2026-09-23T12", "2026-09-24T12")  # premise
    findings = {(hour, "tool", "ticket_live", "agentic_run", False): 1 for hour in (old, kept, today)}
    at = T0 - 35 * DAY_SECONDS
    stale = TicketBatch(
        findings=findings,
        samples=[TicketSample(old, at, _unknown(), False)],
        missing=[TicketSample(old, at, _missing(), False)],
    )
    await store.write_batch(BOOT, _with_tickets(stale))
    assert await store.prune(T0) == (0, 0), "the counts prune returns leave the work-ticket rows out"
    assert await rows(store.path, "SELECT day FROM ticket_findings ORDER BY day") == [("2026-09-24",), (DAY,)]
    assert await rows(store.path, "SELECT hour FROM ticket_markers ORDER BY hour") == [(kept,), (today,)]
    rings = "SELECT (SELECT COUNT(*) FROM ticket_samples), (SELECT COUNT(*) FROM ticket_missing_samples)"
    assert await rows(store.path, rings) == [(1, 1)], "neither ring is pruned by day"
    monkeypatch.setattr(store_module, "MARKER_ROW_LIMIT", 1)
    assert await store.prune(T0) == (0, 0)
    assert await rows(store.path, "SELECT hour FROM ticket_markers ORDER BY hour") == [(today,)]


def test_the_ticket_key_space_and_the_rings_are_bounded_by_named_constants() -> None:
    """TR6: D139's bounds."""
    assert (TICKET_SAMPLE_RING_SIZE, TICKET_MISSING_RING_SIZE, TICKET_DIGEST_CHARS, SCHEMA_VERSION) == (5_000, 1_000, 16, 1)
    one_day = len(TICKET_OPERATIONS) * len(TICKET_REASON_CODES) * (len(WORK_KINDS) + 1) * 2
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT, one_day


async def test_a_file_without_the_ticket_tables_keeps_its_rows_and_gains_them_at_start(tmp_path: Path) -> None:
    """TR7: D143. The file is this build's with its four ticket tables dropped, which leaves the tables a build
    without them creates."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        verdicts = {(utc_hour(T0), "intent", "intent", "admit", "admitted", 3): 9}
        await shadow.write_batch(BOOT, ShadowBatch(verdicts, [], {}, {}, {}))
    finally:
        await shadow.stop()
    db = await default_factory.connect(str(shadow.path))
    try:
        await db.executescript("".join(f"DROP TABLE {name};" for (name,) in TICKET_TABLE_NAMES))
        await db.commit()
    finally:
        await db.close()
    assert await rows(shadow.path, TABLES) == SHADOW_TABLES, "premise: the tables of a build without the ticket tables"
    assert tuple(name for name in REPORT_QUERIES if name.startswith("ticket_")) == tuple(TICKET_QUERIES)
    reader = await open_read_only(shadow.path)
    try:
        for name, params in TICKET_QUERIES.items():
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                await run_query(reader, name, params)
        assert await run_query(reader, "days_recorded") == [(DAY,)]
    finally:
        await reader.close()
    again = AdmissionShadowStore(data_dir=tmp_path / "data")
    await again.start()
    await again.stop()
    assert await rows(shadow.path, TABLES) == sorted(SHADOW_TABLES + TICKET_TABLE_NAMES)
    assert await rows(shadow.path, "SELECT * FROM shadow_aggregates") == [(DAY, "intent", "intent", "admit", "admitted", 3, 9)]
    assert await rows(shadow.path, "SELECT version FROM schema_version") == [(1,)]


async def test_the_ticket_queries_answer_on_a_read_only_connection(tmp_path: Path) -> None:
    """TR8 (kills TRX-18, TRX-19): a second boot, ``boot-0``, writes only a dropped and a samples-dropped count, each at
    an hour of its own. Its id sorts before ``boot-a`` and its hours after, so only the order by hour puts ``boot-a`` first."""
    first, second, third = utc_hour(T0), utc_hour(T0 + DAY_SECONDS), utc_hour(T0 + DAY_SECONDS + HOUR)
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        await shadow.write_batch(BOOT, _with_tickets(TicketBatch(
            findings={
                (first, "tool", "ticket_live", "agentic_run", False): 2,
                (second, "tool", "ticket_live", "agentic_run", False): 1,
                (second, "model_call", "ticket_missing", "", True): 1,
            },
            samples=[TicketSample(first, T0, _unknown(), False), TicketSample(first, T0 + 1, _unknown(), True)],
            missing=[
                TicketSample(second, T0 + DAY_SECONDS, _missing(), True),
                TicketSample(second, T0 + DAY_SECONDS + 1, _missing(), False),
            ],
            offered={first: 2, second: 3},
            dropped={second: 1},
        )))
        await shadow.write_batch("boot-0", _with_tickets(TicketBatch(dropped={second: 1}, samples_dropped={third: 1})))
    finally:
        await shadow.stop()
    reader = await open_read_only(shadow.path)
    try:
        assert await run_query(reader, "ticket_findings_by_operation", (DAY,)) == [
            ("model_call", "ticket_missing", "", 1, 1), ("tool", "ticket_live", "agentic_run", 0, 3),
        ]
        assert await run_query(reader, "ticket_findings_by_operation", ("2026-10-29",)) == [
            ("model_call", "ticket_missing", "", 1, 1), ("tool", "ticket_live", "agentic_run", 0, 1),
        ]
        assert await run_query(reader, "ticket_findings_by_operation", ("2026-10-30",)) == []
        newest = await run_query(reader, "ticket_samples", (1,))
        assert [row[3:7] for row in newest] == [("tool", "ticket_unknown", "", 1)], "the newest sample first"
        noted = await run_query(reader, "ticket_missing_samples", (1,))
        assert [row[3:7] for row in noted] == [("model_call", "ticket_missing", "", 0)], "the newest sample first"
        assert await run_query(reader, "ticket_markers_by_boot") == [
            (BOOT, first, second, 5, 4, 1, 0), ("boot-0", second, third, 0, 0, 1, 1),
        ]
        assert await run_query(reader, "ticket_days_recorded") == [(DAY,), ("2026-10-29",)]
        with pytest.raises(sqlite3.OperationalError):
            await reader.execute("DELETE FROM ticket_findings")
    finally:
        await reader.close()


def test_a_persisted_finding_shows_ticket_ids_only_as_digests() -> None:
    """TR9 (kills TRX-12, TRX-13, TRX-14, TRX-15, TRX-16)."""
    ticket, parent, stop = "ab" * 16, "cd" * 16, "ef" * 16
    finding = TicketFinding(
        "model_call", "ticket_revoked", f"Ticket {ticket} of a child of {parent} is under the Captain's stop {stop}.",
        ticket_id=ticket, principal_key="agent", presented_key="agent", parent_id=parent, depth=1,
        work_kind="delegated_task", stop_id=stop,
    )
    body = persisted_finding(finding)
    assert list(body) == list(TICKET_FINDING_KEYS)
    assert (body["ticket_id"], body["parent_id"], body["stop_id"]) == (ticket_digest(ticket), ticket_digest(parent), stop)
    assert body["cause"] == (
        f"Ticket {ticket_digest(ticket)} of a child of {ticket_digest(parent)} is under the Captain's stop {stop}."
    )
    same = ("operation", "code", "principal_key", "presented_key", "depth", "work_kind", "stop_id")
    assert {name: body[name] for name in same} == {name: finding.to_dict()[name] for name in same}
    short = TicketFinding("tool", "ticket_unknown", "The presented object is not a ticket the registry holds.", ticket_id="T")
    assert persisted_finding(short)["cause"] == short.cause, "an id not of the issued form is not looked for in the cause"
    for odd in ("ab" * 8, "AB" * 16):
        other = TicketFinding("tool", "ticket_unknown", f"The presented id {odd} is unknown.", ticket_id=odd)
        assert persisted_finding(other)["cause"] == other.cause, f"{odd} is not of the issued form"
    assert persisted_finding(short)["ticket_id"] == ticket_digest("T")
    assert ticket_digest("") == "" and ticket_digest(ticket) == hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]
    assert len(ticket_digest("T")) == TICKET_DIGEST_CHARS == 16
