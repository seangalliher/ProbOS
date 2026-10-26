"""AD-1341 S4 M3 (#1569): an AD-754 erasure erases nothing while an exit note the next reset would archive cites its
episodes, and the Captain's veto of the note clears the way.

A real ``EpisodicMemory`` (``test_ad1340_s1_eviction``'s rig), the real ``ErasureManager``, notes written by the real
stand-down service (``run_stand_down``; its agent's turn is a stub), the real citation read, the real ``ArchiveStore``,
the real app's ``POST /api/security/forget`` (S2a's client), the Captain's real ``probos archive veto`` (S3's
``_veto``) and the real ``probos reset`` (S1's ``_reset``).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

import probos
from probos.api import create_app
from probos.knowledge.archive_promotion import exit_note_citations, plan_promotion
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, VetoOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager, ExitNotesBlockErasure
from probos.routers import security
from probos.stand_down import CrewMember, TurnOutcome, run_stand_down
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset
from tests.test_ad1341_s3_erasure_cascade import _traced, _traces
from tests.test_ad1341_s3_review_cli import _veto
from tests.test_ad1341_s4_lessons import _deny_entry_type, _deny_listing, _deny_reading
from tests.test_ad1341_s4_stand_down import _reply

_SRC = Path(probos.__file__).resolve().parent
_FORGET = "/api/security/forget"
_CITED, _OTHER = "ep-000", "ep-001"
_RESOURCE = "/srv/reactor.log"
_TARGETS: dict[str, dict[str, str]] = {
    "episode": {"episode_id": _CITED},
    "agent": {"agent_id": "agent-a"},
    "resource": {"resource_path": _RESOURCE},
}
_MATCHED = {"episode": [_CITED], "agent": [_CITED, _OTHER], "resource": [_CITED]}  # of the two stored episodes
_AGENT = CrewMember(
    agent_id="slot-surgeon", agent_type="surgeon", sovereign_id="agent-a", did=f"did:probos:{_SHIP}:agent-a",
    callsign="Chapel",
)
_SECOND = CrewMember(  # A2: a second billet, so two notes can cite one episode
    agent_id="slot-pathologist", agent_type="pathologist", sovereign_id="agent-a",
    did=f"did:probos:{_SHIP}:pathologist", callsign="Selar",
)


def _episodes() -> list[Any]:
    """Two episodes of agent-a; only the first names the resource."""
    cited = dataclasses.replace(_episode(0), user_input=f"alpha section filed the coolant readings under {_RESOURCE}")
    return [cited, _episode(1)]


async def _stored(em: Any) -> None:
    for episode in _episodes():
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    assert _live(em) == [_CITED, _OTHER]  # premise: both are live


def _live(em: Any) -> list[str]:
    return sorted(_raw(em, [_CITED, _OTHER])["ids"])


async def _stand_down(records: Any, *, cites: str = "e1", shown: int = 0, agent: CrewMember = _AGENT) -> str:
    """A real stand-down in which ``agent`` is shown one of agent-a's episodes (``_CITED`` by default) as e1."""

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply(cites)

    async def recall(member: CrewMember) -> list[Any]:
        return [_episodes()[shown]]

    report = await run_stand_down((agent,), ask=ask, recall=recall, records=records, timeline_id=_SHIP)
    assert [turn.outcome for turn in report.turns] == [TurnOutcome.WRITTEN]  # premise
    return report.turns[0].path


def _manager(
    memory: Any, citations: Any, archive: Any = None, attachments: Any = None, audit: Any = None,
) -> ErasureManager:
    options = {"exit_note_citations": citations, "archive_store": archive}  # the keywords, passed as a mapping
    return ErasureManager(memory, attachments, audit, **options)


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_CITED)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


# --- X1, X2: the refusal, and the Captain's way through it ---------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_a_pending_exit_note_cites_erases_nothing(tmp_path: Path, target: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            citations = await exit_note_citations(records, store)
            assert citations == {_CITED: (path,)}  # premise: the note cites the episode it was shown

            with pytest.raises(ExitNotesBlockErasure) as refused:
                await _forget(_manager(rig.em, citations, store), target)

            assert refused.value.paths == (path,)
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
        finally:
            await store.close()


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_a_refused_erasure_for_a_note_keeps_the_cited_episodes_attachment_and_audit_row(
    tmp_path: Path, target: str,
) -> None:
    """A1, S3's finding M3-F1 asked of this check: the refusal comes before every destructive consumer, the
    attachment's unlink and the audit marking included (S3's real attachment store and audit log, ``_traced``)."""
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    store = _store(tmp_path)
    await store.initialize()
    try:
        citations = await exit_note_citations(records, store)
        assert citations == {_CITED: (path,)}  # premise: the note cites the episode that holds the attachment
        async with _traced(tmp_path, store) as (rig, _archive_only, attachments, audit):
            with pytest.raises(ExitNotesBlockErasure) as refused:
                await _forget(_manager(rig.em, citations, store, attachments, audit), target)

            assert refused.value.paths == (path,)
            assert await _traces(rig.em, attachments, audit) == ([_CITED, _OTHER], True, [_CITED, _OTHER])
    finally:
        await store.close()


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_s3_s_archive_refusal_comes_before_this_slice_s_when_both_cite_the_episode(
    tmp_path: Path, target: str,
) -> None:
    """A2 (M3-F4): an archived note and a pending note both cite the target. S3's check runs first at every entry
    point, so the erasure is refused for the archive entry, and this slice's refusal is never reached."""
    records = _records(_data_dir(tmp_path))
    archived = await _stand_down(records)
    pending = await _stand_down(records, agent=_SECOND)
    store = _store(tmp_path)
    await store.initialize()
    try:
        plan = await plan_promotion(records, timeline_id=_SHIP)
        first = next(record for record in plan.records if record.source_ref == archived)
        assert await store.promote_entry(first) is PromotionOutcome.CREATED
        citations = await exit_note_citations(records, store)
        assert citations == {_CITED: (pending,)}  # premise: the archived note is S3's; the pending one is this slice's
        async with _memory(tmp_path / "vessel", "archive") as rig:
            await _stored(rig.em)
            with pytest.raises(ArchiveCitationsBlockErasure):
                await _forget(_manager(rig.em, citations, store), target)
            assert _live(rig.em) == [_CITED, _OTHER]
    finally:
        await store.close()


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_the_captain_vetoes_the_note_then_the_forget_route_erases_the_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, target: str,
) -> None:
    caplog.set_level(logging.WARNING)
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    records = _records(data_dir)
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        store = _store(tmp_path)
        await store.initialize()
        try:
            runtime = _runtime(root, rig.em)
            runtime.records_store = records  # the runtime's public accessor
            runtime.archive_store = store  # S3's public accessor
            async with _client(runtime) as client:
                refused = await _post(client, _FORGET, _TARGETS[target])

                assert refused.status_code == 409, refused.text
                assert refused.json()["error"] == "exit_notes_cite_erased_episodes"
                assert refused.json()["exit_note_paths"] == [path]
                assert _live(rig.em) == [_CITED, _OTHER]
                refusals = [
                    record.getMessage() for record in caplog.records if "exit note(s)" in record.getMessage()
                ]
                assert refusals == [  # A2 (M3-F5): logged once, as a count: no path, episode id or note text
                    "AD-1341 S4: an AD-754 erasure was refused: 1 exit note(s) awaiting promotion cite its episodes",
                ]

                # The Captain's veto, as the CLI runs it: its own event loop, so in a thread.
                assert await asyncio.to_thread(_veto, monkeypatch, config, data_dir, path, "cites an erased episode") == 0

                erased = await _post(client, _FORGET, _TARGETS[target])

                assert erased.status_code == 200, erased.text
                assert sorted(erased.json()["deleted_episode_ids"]) == _MATCHED[target]
                assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
        finally:
            await store.close()

    assert await asyncio.to_thread(_reset, monkeypatch, config, data_dir) == 0  # the real reset honours the veto
    assert _rows(tmp_path / "archive.db", "SELECT COUNT(*) FROM archive WHERE source_kind = 'exit_note'") == [(0,)]


# --- X3 to X5: what does not block, and what fails closed ----------------------------------------------------------


@pytest.mark.parametrize("state", ["vetoed", "erased", "present", "uncited", "another-episode"])
async def test_a_note_the_next_reset_would_not_archive_with_this_citation_blocks_nothing(
    tmp_path: Path, state: str,
) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(
        records, cites="" if state == "uncited" else "e1", shown=1 if state == "another-episode" else 0,
    )
    store = _store(tmp_path)
    await store.initialize()
    try:
        record = (await plan_promotion(records, timeline_id=_SHIP)).records[0]
        if state == "vetoed":
            outcome = await store.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP)
            assert outcome is VetoOutcome.RECORDED
        elif state in ("erased", "present"):
            assert await store.promote_entry(record) is PromotionOutcome.CREATED
            if state == "erased":
                entry_id = _rows(tmp_path / "archive.db", "SELECT id FROM archive")[0][0]
                assert await store.erase_entry(entry_id, "the Captain forgets it") is True
        citations = await exit_note_citations(records, store)
    finally:
        await store.close()
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        # Only this slice's check: an archived ("present") note is S3's check, its E1.
        result = await _manager(rig.em, citations).forget_episode(_CITED)

        assert result.deleted_episode_ids == [_CITED]
        assert _live(rig.em) == [_OTHER]


@pytest.mark.parametrize("archive", ["enabled-not-open", "disabled"])
async def test_the_check_fails_closed_while_the_archive_is_enabled_but_not_open(tmp_path: Path, archive: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None  # failed at boot, or closed at shutdown
        runtime.config.archive.enabled = archive != "disabled"
        async with _client(runtime) as client:
            answer = await _post(client, _FORGET, {"episode_id": _CITED})

        if archive == "disabled":  # a disabled archive promotes nothing, so nothing is checked
            assert answer.status_code == 200, answer.text
            assert answer.json()["deleted_episode_ids"] == [_CITED]
        else:
            assert answer.status_code == 409, answer.text
            assert answer.json()["exit_note_paths"] == [path]
            assert _live(rig.em) == [_CITED, _OTHER]


async def test_the_forget_route_reads_notes_only_from_a_real_records_store(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    assert await exit_note_citations(records, None) == {_CITED: (path,)}  # premise: a real store's read would refuse
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)  # its records_store is a MagicMock attribute, as in every route test
        async with _client(runtime) as client:
            erased = await _post(client, _FORGET, {"episode_id": _CITED})

        assert erased.status_code == 200, erased.text
        assert erased.json()["deleted_episode_ids"] == [_CITED]


# --- X6, X7: authority, and the read's bound -----------------------------------------------------------------------


def _importers(name: str) -> set[str]:
    """The ``src`` files that import ``name`` from a module."""
    found: set[str] = set()
    for source in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == name for alias in node.names):
                found.add(source.relative_to(_SRC).as_posix())
    return found


def test_only_the_forget_route_reads_exit_note_citations_and_only_the_manager_refuses_on_them() -> None:
    raisers: set[str] = set()
    for source in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id == "ExitNotesBlockErasure"
            ):
                raisers.add(source.relative_to(_SRC).as_posix())

    assert _importers("exit_note_citations") == {"routers/security.py"}
    assert _importers("ExitNotesBlockErasure") == {"routers/security.py"}
    assert raisers == {"knowledge/erasure.py"}


async def test_a_note_written_after_the_request_read_its_citations_does_not_stop_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D14's disclosed bound (register R2), through the real route (A2, M3-F3). The route reads the pending notes'
    citations once, before it builds the manager. A note citing the episode that lands right after that read does
    not stop the request; a second read would have counted it."""
    records = _records(_data_dir(tmp_path))
    root = tmp_path / "vessel"
    reads: list[dict[str, tuple[str, ...]]] = []
    late: list[str] = []
    real_read = security.exit_note_citations

    async def read_then_a_late_note(store: Any, archive: Any) -> dict[str, tuple[str, ...]]:
        reads.append(await real_read(store, archive))
        if not late:
            late.append(await _stand_down(records))  # lands after the read, before the manager is built
        return reads[-1]

    monkeypatch.setattr(security, "exit_note_citations", read_then_a_late_note)
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None
        runtime.config.archive.enabled = True
        async with _client(runtime) as client:
            answer = await _post(client, _FORGET, {"episode_id": _CITED})

        assert reads == [{}]  # one read per request, and it saw no note
        assert await real_read(records, None) == {_CITED: (late[0],)}  # premise: a second read would count it
        assert answer.status_code == 200, answer.text
        assert answer.json()["deleted_episode_ids"] == [_CITED]  # the disclosed bound: register R2


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
@pytest.mark.parametrize("fault", ["read", "listing", "entry-type"])
async def test_an_exit_note_the_route_cannot_read_now_refuses_the_erasure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, target: str,
) -> None:
    """A2 (M3-F1): a valid note citing the episode, which the OS refuses to read during the request. The route answers
    500 and erases nothing; once the note can be read, the refusal names it (the Captain's way through, unchanged).
    A5 (round 3 R3-M1-1, M3's coverage): the same through the route when the OS refuses to list the note's timeline
    directory (``[listing-*]``) or cannot report that directory's type (``[entry-type-*]``: the round-3 P1, in which
    the listing took the directory for a file, the read answered "no citations" and the erasure went ahead). The read
    runs before the manager is built (``routers/security.py``), so no attachment or audit row is touched (X1b).

    A3: the shared ``_client`` re-raises the app's exception (``raise_app_exceptions=True``), so this test builds a
    transport that answers as a served app does: Starlette's error middleware sends the 500, then re-raises, and the
    transport keeps the response. A wrapper records what the app raised, so the 500 is proved to be the denied read.
    """
    records = _records(_data_dir(tmp_path))
    path = await _stand_down(records)
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        runtime.records_store = records
        runtime.archive_store = None
        runtime.config.archive.enabled = True
        app = create_app(runtime)
        raised: list[Exception] = []

        async def served(scope: Any, receive: Any, send: Any) -> None:
            try:
                await app(scope, receive, send)
            except Exception as exc:
                raised.append(exc)
                raise

        transport = httpx.ASGITransport(app=served, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            note = records.repo_path / path
            if fault == "read":
                _deny_reading(monkeypatch, note)
            elif fault == "listing":
                _deny_listing(monkeypatch, note.parent)
            else:
                _deny_entry_type(monkeypatch, note.parent)
            failed = await _post(client, _FORGET, _TARGETS[target])
            assert failed.status_code == 500, failed.text
            assert failed.text == "Internal Server Error"  # what a served app sends: no path, no reason
            assert [type(exc) for exc in raised] == [PermissionError]  # the denied read, and nothing else
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
            monkeypatch.undo()
            refused = await _post(client, _FORGET, _TARGETS[target])

        assert len(raised) == 1  # the retry raised nothing
        assert refused.status_code == 409, refused.text
        assert refused.json()["exit_note_paths"] == [path]
