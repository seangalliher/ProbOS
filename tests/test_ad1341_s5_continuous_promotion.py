"""AD-1341 S5 (#1569), M3: continuous promotion, a dream step behind a default-off flag.

Real Ship's Records, a real Ship's Archive, a real episodic memory and the real ``/forget`` route on ``tmp_path``. The
reports are written by M2's real service with scripted crew turns. The step has no model client, so a whole promotion
runs here with no model anywhere.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

import probos
from probos.after_action import run_after_action
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.oracle_service import OracleService
from probos.config import ArchivePromotionConfig, SystemConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.archive_promotion import is_settled, promote_settled
from probos.knowledge.archive_store import LABEL_THIS_CREW, ArchiveStore, PromotionRecord, SourceKind
from probos.knowledge.continuous_promotion import continuous_promotion_step, wire_continuous_promotion
from probos.stand_down import CrewMember
from probos.storage.sqlite_factory import default_factory
from probos.tools.oracle_query_tool import OracleQueryTool
from probos.types import EvictionDisposition
from tests.test_ad1340_s1_eviction import _memory
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _NEXT_SHIP, _SHIP, _data_dir, _records
from tests.test_ad1341_s4_exit_note_erasure import _CITED, _OTHER, _episodes, _live, _manager, _stored
from tests.test_ad1341_s4_stand_down import _reply

_SRC = Path(probos.__file__).resolve().parent
_AUTHOR = CrewMember(
    agent_id="slot-surgeon", agent_type="surgeon", sovereign_id="agent-a", did=f"did:probos:{_SHIP}:agent-a",
    callsign="Pulaski",
)
_CHIEF = CrewMember(
    agent_id="slot-diagnostician", agent_type="diagnostician", sovereign_id="agent-b",
    did=f"did:probos:{_SHIP}:bones", callsign="Bones",
)
_COUNSELOR = CrewMember(
    agent_id="slot-counselor", agent_type="counselor", sovereign_id="agent-c", did=f"did:probos:{_SHIP}:troi",
    callsign="Troi",
)


async def _report(records: Any) -> str:
    """A real report (M2's service) whose author was shown ``_CITED`` as e1 and cites it; the chain endorsed it."""

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply("e1") if member is _AUTHOR else "ENDORSE"

    async def recall(member: CrewMember) -> list[Any]:
        return [_episodes()[0]]

    report = await run_after_action(
        _AUTHOR, subject="Coolant drift alarm", flagged_at="20261027T015500Z",
        reviewers=lambda: (("superior", _CHIEF), ("counselor_or_xo", _COUNSELOR)), ask=ask, recall=recall,
        records=records, timeline_id=_SHIP,
    )
    assert report.endorsed  # premise
    return report.path


async def _published(records: Any, number: int) -> str:
    """A ship-wide published report: a source with no citations."""
    return await records.write_entry(
        author="Bones", path=f"reports/r{number:02d}.md", content=f"Report {number}.", message="test",
        classification="ship", status="published", topic=f"Report {number}",
    )


def _step(records: Any, store: Any, memory: Any, *, settle: float = 0.0, max_created: int = 8) -> Any:
    return continuous_promotion_step(
        records=lambda: records, archive=lambda: store, memory=lambda: memory, timeline_id=lambda: _SHIP,
        settle_seconds=settle, max_created=max_created, clock=lambda: time.time() + 5.0,
    )


def _archived(tmp_path: Path) -> list[tuple[Any, ...]]:
    return _rows(tmp_path / "archive.db", "SELECT id FROM archive")


async def test_a_reviewed_report_is_promoted_while_its_episode_lives_and_then_protects_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _report(records)
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            promoted = await _step(records, store, rig.em)()
            runtime = _runtime(tmp_path / "vessel", rig.em)
            runtime.records_store = records
            runtime.archive_store = store
            async with _client(runtime) as client:
                refused = await _post(client, "/api/security/forget", {"episode_id": _CITED})
            oracle = OracleService(archive_store=store)
            oracle.attach_current_timeline(_NEXT_SHIP)  # a later crew
            later = await OracleQueryTool(oracle=oracle).invoke({"query": "Pulaski", "kind": "archive"})
            oracle.attach_current_timeline(_SHIP)  # this crew
            same = await OracleQueryTool(oracle=oracle).invoke({"query": "Pulaski", "kind": "archive"})
        finally:
            await store.close()
        assert promoted.created == (path,)
        assert refused.status_code == 409 and refused.json()["error"] == "archive_entries_cite_erased_episodes"
        assert _live(rig.em) == [_CITED, _OTHER]  # S3's check now protects a live episode (register F-633)
    assert "[Inherited from " in later.output and "After-action report by Pulaski" in later.output
    assert LABEL_THIS_CREW in same.output  # S2 D5: this crew's own entry is a record, not an inheritance


async def test_an_episode_erased_before_the_step_keeps_the_report_waiting(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _report(records)
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            await _manager(rig.em, None, store).forget_episode(_CITED)  # F-631's window: no pending read counted it
            report = await _step(records, store, rig.em)()
        finally:
            await store.close()
    assert report.created == () and report.waiting == (path,)
    assert _archived(tmp_path) == []


async def test_the_step_waits_for_an_erasure_in_progress_and_never_archives_what_it_erased(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _report(records)
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        inside, release = asyncio.Event(), asyncio.Event()
        evict = rig.em.evict_by_ids

        async def paused_evict(*args: Any, **kwargs: Any) -> Any:
            inside.set()  # the real erasure is in its critical section: its archive check done, its evict not begun
            await release.wait()
            return await evict(*args, **kwargs)

        rig.em.evict_by_ids = paused_evict  # type: ignore[method-assign]  # Amendment A3 (C2): the manager's own lock
        try:
            erasure = asyncio.create_task(_manager(rig.em, None, store).forget_episode(_CITED))
            await asyncio.wait_for(inside.wait(), timeout=5.0)
            task = asyncio.create_task(_step(records, store, rig.em)())
            done, _pending = await asyncio.wait({task}, timeout=1.0)
            assert task not in done  # the step waits for the erasure ErasureManager is running
            release.set()
            await erasure
            report = await task
        finally:
            release.set()
            await store.close()
    assert report.created == () and report.waiting == (path,)
    assert _archived(tmp_path) == []


def _record(updated: str) -> PromotionRecord:
    return PromotionRecord(
        timeline_id=_SHIP, source_kind=SourceKind.PUBLISHED_REPORT, source_ref="reports/r.md", title="r",
        content="c", classification="ship", metadata={"record_updated": updated},
    )


@pytest.mark.parametrize(
    ("updated", "offset", "settled"),
    [
        ("2026-10-26T12:00:00+00:00", 0.0, True),
        ("2026-10-26T12:00:00+00:00", -0.001, False),
        ("2026-10-26T14:00:00+02:00", 0.0, True),
        ("2026-10-26T12:00:00", 86_400.0, False),
        ("not a time", 86_400.0, False),
        ("", 86_400.0, False),
    ],
    ids=["at-the-bound", "just-before", "another-offset", "no-offset", "garbage", "missing"],
)
def test_a_source_settles_at_its_last_update_plus_the_settle_time(updated: str, offset: float, settled: bool) -> None:
    base = datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp()
    assert is_settled(_record(updated), base + offset) is settled


def _log(ref: str, updated: str) -> PromotionRecord:
    return PromotionRecord(
        timeline_id=_SHIP, source_kind=SourceKind.CAPTAINS_LOG, source_ref=ref, title="Captain's log",
        content="c", classification="ship", metadata={"record_updated": updated},
    )


@pytest.mark.parametrize(
    ("ref", "updated", "offset", "settled"),
    [
        ("captains-log/2026-10-26.md", "", 0.0, True),
        ("captains-log/2026-10-26.md", "", -0.001, False),
        ("captains-log/2026-10-26.md", "2026-10-26T20:00:00+00:00", 0.0, True),
        ("captains-log/2026-10-26.md", "2026-10-27T06:00:00+00:00", 0.0, False),
        ("captains-log/20261026.md", "", 0.0, False),
        ("captains-log/notes.md", "", 0.0, False),
    ],
    ids=[
        "at-the-day-s-end", "just-before", "updated-within-the-day", "updated-after-the-day", "not-the-writer-s-name",
        "no-day",
    ],
)
def test_a_captain_s_log_settles_at_the_end_of_its_day_plus_the_settle_time(
    ref: str, updated: str, offset: float, settled: bool,
) -> None:
    ended = datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()  # 2026-10-26 ends here (Amendment A3, C1)
    assert is_settled(_log(ref, updated), ended + offset) is settled


class _WriterClock(datetime):
    """The Captain's log writer's clock (``records_store.datetime``), set by the test."""

    at = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        return cls.at if tz is None else cls.at.astimezone(tz)


async def test_the_captain_s_log_from_its_writer_settles_once_its_day_has_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _records(_data_dir(tmp_path))
    monkeypatch.setattr(records_store_module, "datetime", _WriterClock)
    monkeypatch.setattr(_WriterClock, "at", datetime(2026, 10, 26, 9, tzinfo=timezone.utc))
    created = await records.append_captains_log("Coolant drift at the start of the watch.")
    monkeypatch.setattr(_WriterClock, "at", datetime(2026, 10, 26, 23, 59, 59, tzinfo=timezone.utc))
    appended = await records.append_captains_log("The drift was a stuck sensor.")
    monkeypatch.setattr(_WriterClock, "at", datetime(2026, 10, 27, tzinfo=timezone.utc))
    next_day = await records.append_captains_log("A quiet watch.")
    assert created == appended == "captains-log/2026-10-26.md" and next_day == "captains-log/2026-10-27.md"  # premise
    assert "updated" not in (await records.read_entry(created, ""))["frontmatter"]  # premise: the writer stamps none
    ended = datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()
    store = _store(tmp_path)
    await store.initialize()
    try:

        def step(now: float) -> Any:
            return continuous_promotion_step(
                records=lambda: records, archive=lambda: store, memory=lambda: None, timeline_id=lambda: _SHIP,
                settle_seconds=86_400.0, max_created=8, clock=lambda: now,
            )

        early = await step(ended + 86_400.0 - 0.001)()
        settled = await step(ended + 86_400.0)()
    finally:
        await store.close()
    assert early.created == () and set(early.waiting) == {created, next_day}
    assert settled.created == (created,) and settled.waiting == (next_day,)  # Amendment A3 (C1): the whole day, once


async def test_the_step_promotes_a_source_only_once_it_has_settled(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _published(records, 0)
    store = _store(tmp_path)
    await store.initialize()
    try:
        early = await _step(records, store, None, settle=3600.0)()
        later = await _step(records, store, None, settle=0.0)()
    finally:
        await store.close()
    assert early.created == () and early.waiting == (path,)
    assert later.created == (path,)


class _CountingArchive(ArchiveStore):
    """A real archive that counts its writes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.writes = 0

    async def promote_entry(self, record: PromotionRecord) -> Any:
        self.writes += 1
        return await super().promote_entry(record)


async def test_each_cycle_creates_at_most_its_batch_and_rewrites_nothing(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    paths = [await _published(records, number) for number in range(9)]
    store = _CountingArchive(str(tmp_path / "archive.db"), connection_factory=default_factory)
    await store.initialize()
    try:
        first = await _step(records, store, None)()
        second = await _step(records, store, None)()
        third = await _step(records, store, None)()
    finally:
        await store.close()
    assert len(first.created) == 8 and set(first.created) < set(paths)
    assert len(second.created) == 1 and len(second.present) == 8
    assert third.created == () and len(third.present) == 9
    assert store.writes == 9  # an archived source is passed over without a write


async def test_a_veto_between_the_step_s_read_and_its_write_decides(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _report(records)
    store = _store(tmp_path)
    await store.initialize()
    try:

        async def vetoed_meanwhile(ids: tuple[str, ...]) -> bool:
            await store.veto_source(SourceKind.AFTER_ACTION_REPORT, path, "not canon")  # after source_state's read
            return True

        report = await promote_settled(
            records, store, timeline_id=_SHIP, settled_before=time.time() + 5.0, max_created=8,
            cited_live=vetoed_meanwhile, exclusive=contextlib.nullcontext,
        )
    finally:
        await store.close()
    assert report.vetoed == (path,) and report.created == ()
    assert _archived(tmp_path) == []


async def test_the_step_archives_nothing_the_reset_would_withhold(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    private = await records.write_entry(
        author="Bones", path="notebooks/bones/finding.md", content="A private finding.", message="test",
        classification="private", status="published", topic="finding",
    )
    department = await records.write_entry(
        author="Bones", path="reports/department.md", content="A department report.", message="test",
        classification="department", status="published", topic="department",
    )
    store = _store(tmp_path)
    await store.initialize()
    try:
        report = await _step(records, store, None)()
    finally:
        await store.close()
    assert report.created == () and set(report.withheld) == {private, department}


def _engine(step: Any) -> DreamingEngine:
    engine = DreamingEngine.__new__(DreamingEngine)  # the bypass pattern other dream-step tests use
    engine.micro_dream = AsyncMock(return_value={"episodes_replayed": 0, "weights_strengthened": 0})  # type: ignore[method-assign]
    engine.episodic_memory = MagicMock(recent=AsyncMock(return_value=[]))
    engine.config = MagicMock(replay_episode_count=5)
    engine.set_continuous_promotion(step)
    return engine


async def test_a_full_dream_cycle_runs_the_step_once_and_survives_its_failure(caplog: pytest.LogCaptureFixture) -> None:
    assert DreamingEngine.__new__(DreamingEngine)._continuous_promotion is None  # off unless wired
    ok = AsyncMock(return_value=None)
    await _engine(ok).dream_cycle()
    assert ok.await_count == 1
    broken = AsyncMock(side_effect=RuntimeError("archive locked"))
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dreaming"):
        report = await _engine(broken).dream_cycle()
    assert broken.await_count == 1 and report is not None
    assert "AD-1341 S5: continuous promotion failed" in caplog.text

    class PastTheStep(Exception):
        """Step 2 (the prune) raises it, so the cycle shows it got there."""

    later = _engine(AsyncMock(side_effect=RuntimeError("archive locked")))
    later.episodic_memory = MagicMock(recent=AsyncMock(return_value=[MagicMock()]))  # episodes to replay
    later._prune_weights = MagicMock(side_effect=PastTheStep())  # type: ignore[method-assign]
    with pytest.raises(PastTheStep):  # Amendment A3 (C3): the dream goes on past a failed step to its later steps
        await later.dream_cycle()


def test_continuous_promotion_is_off_by_default_with_bounded_settings() -> None:
    section = SystemConfig().archive_promotion
    assert (section.enabled, section.settle_hours, section.max_per_cycle) == (False, 24.0, 8)
    for bad in ({"settle_hours": -1.0}, {"settle_hours": 721.0}, {"max_per_cycle": 0}, {"max_per_cycle": 101}):
        with pytest.raises(ValidationError):
            ArchivePromotionConfig(**bad)


@pytest.mark.parametrize(
    ("enabled", "archive_enabled", "wired"),
    [(False, True, False), (True, False, False), (True, True, True)],
    ids=["off", "archive-disabled", "on"],
)
def test_the_step_is_wired_only_when_the_captain_enables_it(enabled: bool, archive_enabled: bool, wired: bool) -> None:
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.config.archive_promotion.enabled = enabled
    runtime.config.archive.enabled = archive_enabled
    engine = MagicMock()
    assert wire_continuous_promotion(runtime, engine) is wired
    assert engine.set_continuous_promotion.called is wired


@pytest.mark.parametrize("missing", ["archive", "records", "timeline"])
async def test_the_step_does_nothing_without_its_stores_or_a_timeline(tmp_path: Path, missing: str) -> None:
    records = _records(_data_dir(tmp_path))
    await _published(records, 0)
    store = _store(tmp_path)
    await store.initialize()
    try:
        step = continuous_promotion_step(
            records=lambda: None if missing == "records" else records,
            archive=lambda: None if missing == "archive" else store,
            memory=lambda: None,
            timeline_id=lambda: "unknown" if missing == "timeline" else _SHIP,
            settle_seconds=0.0, max_created=8, clock=lambda: time.time() + 5.0,
        )
        assert await step() is None
    finally:
        await store.close()
    assert _archived(tmp_path) == []


async def test_a_lesson_whose_citations_cannot_be_checked_waits(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _report(records)
    store = _store(tmp_path)
    await store.initialize()
    try:
        report = await _step(records, store, None)()  # no episodic memory
    finally:
        await store.close()
    assert report.waiting == (path,) and report.created == ()


def test_finalize_wires_the_step_through_the_one_function() -> None:
    """A source check (the live wiring is in Not verified): finalize calls ``wire_continuous_promotion(runtime,
    engine)`` once, and nothing else in ``src`` calls ``set_continuous_promotion`` but that function."""
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_text(encoding="utf-8-sig"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "wire_continuous_promotion"
    ]
    assert [[ast.unparse(arg) for arg in call.args] for call in calls] == [["runtime", "engine"]]
    setters = set()
    for source in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Attribute) and node.attr == "set_continuous_promotion":
                setters.add(source.relative_to(_SRC).as_posix())
    assert setters == {"knowledge/continuous_promotion.py"}
