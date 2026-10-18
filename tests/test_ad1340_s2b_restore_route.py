"""AD-1340 S2b (M5): the restore route, through the real app.

``POST /api/security/archive/restore`` on the REAL app (``create_app``), called through ``httpx.ASGITransport`` in the
test's own event loop, over S2a's rig: the real ``EpisodicMemory`` on ``tmp_path`` with every sidecar and the archive
wired. Raw ``sqlite3`` connections of the tests' own are the independent witness for the archive, its access rows and
the sidecars, and the live store is read straight from ChromaDB. Every test archives its subject through Step 12's
call and states its premise first (archived, not live, in no sidecar, no access row), so a pass cannot be vacuous.
No test sleeps and every wait is bounded. No assertion orders rows by time (back-to-back ``time.time()`` calls can
return one value on Windows): the access rows come back ordered by id.
"""

from __future__ import annotations

import ast
import asyncio
import gc
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.cognitive.episode_archive import (
    ArchiveRecord,
    EpisodeArchive,
    EpisodeArchiveError,
    EpisodeArchiveUnavailable,
    decode_payload,
)
from probos.routers.security import _holds_unpaired_surrogate
from probos.security.pii_redaction import LogRedactionFormatter
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_erasure import _GONE, _traces
from tests.test_ad1340_s1_eviction import _archive_rows, _sidecar_counts
from tests.test_ad1340_s1_restore_reset import _canonical
from tests.test_ad1340_s2a_archive_lookup import _write
from tests.test_ad1340_s2a_lookup_route import (
    _access_rows,
    _ACCESSOR,
    _archive_path,
    _AUTH,
    _client,
    _count,
    _episode,
    _episode_ids,
    _FORGET,
    _LOOKUP,
    _memory,
    _memory_without_archive,
    _post,
    _query,
    _raw,
    _Rig,
    _runtime,
    _store_and_evict,
    _TOKEN,
    _UNAVAILABLE,
)
from tests.test_ad1340_s2b_restore import (
    _archive_one,
    _CAPTAIN,
    _fail_insert,
    _LIVE_SIDECARS,
    _NO_SIDECARS,
    _pause_in,
    _STORED_VALUE_MARKER,
    _two_crafted_versions,
)

_RESTORE = "/api/security/archive/restore"
_SRC = Path(__file__).resolve().parent.parent / "src" / "probos"


# --- RR-a ----------------------------------------------------------------------------------------------------


async def test_restore_route_refuses_without_a_configured_token_before_anything(tmp_path: Path) -> None:
    refusal = (403, {"detail": "episode_archive_restore_requires_token"})
    async with _memory(tmp_path / "open", "archive") as rig:
        root = rig.root
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        runtime = _runtime(root, rig.em, token="")
        assert runtime.config.auth.crew_scope_token == ""  # premise: no token is configured

        async with _client(runtime) as client:
            response = await _post(client, _RESTORE, {"episode_id": eid})
            assert (response.status_code, response.json()) == refusal
            response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)  # a presented token changes nothing
            assert (response.status_code, response.json()) == refusal

        assert _raw(rig.em, [eid])["ids"] == []  # not live
        assert _sidecar_counts(root, eid) == _NO_SIDECARS  # and in no sidecar
        assert _access_rows(root, eid) == []  # nothing was restored, so nothing was audited
        assert _count(root, "episode_archive", eid) == 1  # the archive row is as it was

    # With the archive in the "failed" state the answer is still 403, not 503: the token check comes first.
    async with _memory_without_archive(tmp_path / "failed", "failed") as em:
        with pytest.raises(EpisodeArchiveUnavailable, match=r"^episode_archive_unavailable$"):
            await asyncio.wait_for(em.restore_from_archive("ep-000", accessor="premise"), 5)  # premise: a restore would answer 503
        async with _client(_runtime(tmp_path / "failed", em, token="")) as client:
            response = await _post(client, _RESTORE, {"episode_id": "ep-000"})
            assert (response.status_code, response.json()) == refusal


# --- RR-b ----------------------------------------------------------------------------------------------------


async def test_restore_route_rejects_a_missing_or_wrong_token(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        runtime = _runtime(tmp_path, rig.em, token=_TOKEN)
        assert runtime.config.auth.crew_scope_token == _TOKEN  # premise: a token is configured
        body = {"episode_id": eid}
        nan_body = f'{{"episode_id": "{eid}", "extra": NaN}}'.encode()
        json_headers = {"Content-Type": "application/json"}
        missing = (401, {"detail": "missing_or_malformed_authorization"})

        async with _client(runtime) as client:
            # Premise: the non-finite-number guard is live for this body once the caller is authenticated.
            response = await _post(client, _RESTORE, content=nan_body, headers={**json_headers, **_AUTH})
            assert (response.status_code, response.json()) == (422, {"detail": "non_finite_number_in_body"})

            response = await _post(client, _RESTORE, body)  # no Authorization header
            assert (response.status_code, response.json()) == missing
            response = await _post(client, _RESTORE, body, headers={"Authorization": f"Basic {_TOKEN}"})
            assert (response.status_code, response.json()) == missing
            response = await _post(client, _RESTORE, body, headers={"Authorization": f"Bearer wrong-{_TOKEN}"})
            assert (response.status_code, response.json()) == (401, {"detail": "invalid_token"})
            # Authentication is checked before the non-finite-number guard (A2): a NaN body without a token is 401.
            response = await _post(client, _RESTORE, content=nan_body, headers=json_headers)
            assert (response.status_code, response.json()) == missing

        assert _raw(rig.em, [eid])["ids"] == []  # not live
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # and in no sidecar
        assert _access_rows(tmp_path, eid) == []  # nothing was restored, so nothing was audited


# --- RR-c ----------------------------------------------------------------------------------------------------


async def test_restore_route_restores_and_records_one_access(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        snapshot = await _store_and_evict(rig.em, [0])  # the raw record is taken before the eviction
        eid = "ep-000"
        document, metadata = snapshot[eid]
        assert _count(tmp_path, "episode_archive", eid) == 1  # premise: archived
        assert _raw(rig.em, [eid])["ids"] == []  # premise: not live
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # premise: in no sidecar
        assert _access_rows(tmp_path, eid) == []  # premise: nothing has read or restored it yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)

        assert response.status_code == 200, response.text
        assert response.json() == {"episode_id": eid, "restored": True}
        assert response.json()["restored"] is True
        live = _raw(rig.em, [eid])
        assert live["ids"] == [eid]
        assert live["documents"] == [document]  # the raw record, as the live store held it before the eviction
        assert _canonical(live["metadatas"][0]) == _canonical(metadata)  # canonical bytes: 1, 1.0 and True differ
        assert _sidecar_counts(tmp_path, eid) == _LIVE_SIDECARS  # one FTS row, one activation access, two participants
        assert _access_rows(tmp_path, eid) == [(_CAPTAIN, "restore")]  # exactly one raw row, written by the route
        assert _count(tmp_path, "episode_archive", eid) == 1  # a restore never deletes the archive row


# --- RR-d ----------------------------------------------------------------------------------------------------


async def _arrange_never_archived(rig: _Rig, client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    """A live episode that was never archived (so the live check cannot be what answers) and an id never stored.

    Returns the ids to ask for and the ids that are live.
    """
    live = _episode(1)
    assert await rig.em.store(live) is EpisodeStoreOutcome.STORED
    assert _raw(rig.em, [live.id])["ids"] == [live.id]  # premise: it is live
    for episode_id in (live.id, "ep-unknown"):
        assert _count(rig.root, "episode_archive", episode_id) == 0  # premise: the archive has no row for it
    return [live.id, "ep-unknown"], [live.id]


async def _arrange_already_live(rig: _Rig, client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    """Archive ``ep-000`` and restore it once through the route: it is live, and its archive row is kept."""
    eid = await _archive_one(rig, 0)
    response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)
    assert (response.status_code, response.json()) == (200, {"episode_id": eid, "restored": True})  # premise: restored
    assert _raw(rig.em, [eid])["ids"] == [eid]  # premise: it is live
    assert _count(rig.root, "episode_archive", eid) == 1  # premise: the archive still holds it
    assert _access_rows(rig.root, eid) == [(_CAPTAIN, "restore")]  # premise: exactly one access row, from that restore
    return [eid], [eid]


async def _arrange_at_capacity(rig: _Rig, client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    """S2b R-1's setup exactly (``max_episodes=2``): ``ep-000`` archived by Step 12's call, ``ep-001``/``ep-002`` live."""
    em = rig.em
    for index in (0, 1):
        assert await em.store(_episode(index)) is EpisodeStoreOutcome.STORED
    assert await em.evict_by_ids(["ep-000"], reason="activation_decay") == 1  # Step 12's call
    assert await em.store(_episode(2)) is EpisodeStoreOutcome.STORED  # never past the budget: store() would evict
    assert em._collection.count() == em.max_episodes == 2  # premise: the live store is exactly at its budget
    assert _raw(em, ["ep-000"])["ids"] == []  # premise: ep-000 is not live
    assert _count(rig.root, "episode_archive", "ep-000") == 1  # premise: it is archived
    assert _access_rows(rig.root, "ep-000") == []  # premise: nothing has restored it yet
    return ["ep-000"], ["ep-001", "ep-002"]


def _snapshot(rig: _Rig, episode_ids: Sequence[str]) -> dict[str, Any]:
    """What a refused restore must leave alone: the live count and, per id, the raw live record, sidecar and access rows."""
    live = _raw(rig.em, episode_ids)
    return {
        "live_count": rig.em._collection.count(),
        "live_records": {
            episode_id: (document, _canonical(metadata))
            for episode_id, document, metadata in zip(live["ids"], live["documents"], live["metadatas"])
        },
        "sidecars": {episode_id: _sidecar_counts(rig.root, episode_id) for episode_id in episode_ids},
        "access_rows": {episode_id: _access_rows(rig.root, episode_id) for episode_id in episode_ids},
    }


@pytest.mark.parametrize(
    ("arrange", "max_episodes", "status", "detail"),
    [
        pytest.param(_arrange_never_archived, 100, 404, "episode_archive_not_found", id="never_archived"),
        pytest.param(_arrange_already_live, 100, 409, "episode_archive_restore_live_id", id="already_live"),
        pytest.param(_arrange_at_capacity, 2, 409, "episode_archive_restore_over_capacity", id="at_capacity"),
    ],
)
async def test_restore_route_maps_each_refusal(
    tmp_path: Path,
    arrange: Callable[[_Rig, httpx.AsyncClient], Awaitable[tuple[list[str], list[str]]]],
    max_episodes: int,
    status: int,
    detail: str,
) -> None:
    async with _memory(tmp_path, "archive", max_episodes=max_episodes) as rig:
        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            asked, live = await arrange(rig, client)  # each arrangement asserts its own premise
            watched = list(dict.fromkeys([*asked, *live]))
            before = _snapshot(rig, watched)

            for episode_id in asked:
                response = await _post(client, _RESTORE, {"episode_id": episode_id}, headers=_AUTH)
                assert (response.status_code, response.json()) == (status, {"detail": detail}), episode_id

        # No further access row, no live record changed, no sidecar row touched, and the live count is as it was.
        assert _snapshot(rig, watched) == before


# --- RR-e ----------------------------------------------------------------------------------------------------


async def test_restore_route_maps_unavailability_to_503(tmp_path: Path) -> None:
    body = {"episode_id": "ep-000"}
    runtime = _runtime(tmp_path / "none", None, token=_TOKEN)
    assert runtime.episodic_memory is None  # premise: no episodic memory at all
    async with _client(runtime) as client:
        response = await _post(client, _RESTORE, body, headers=_AUTH)
    assert (response.status_code, response.json()) == (503, {"detail": "episodic_memory_unavailable"})

    # The second element of each ``_UNAVAILABLE`` tuple is the LOOKUP's code; restore's own state check gives one code.
    states = [state for state, _ in _UNAVAILABLE]
    assert states == ["absent", "failed", "stopped"]  # premise: every way the archive can be unavailable
    for state in states:
        async with _memory_without_archive(tmp_path / state, state) as em:  # premise: no open archive, in this way
            with pytest.raises(EpisodeArchiveUnavailable, match=r"^episode_archive_unavailable$"):
                await asyncio.wait_for(em.restore_from_archive("ep-000", accessor="premise"), 5)  # premise: a restore refuses
            async with _client(_runtime(tmp_path / state, em, token=_TOKEN)) as client:
                response = await _post(client, _RESTORE, body, headers=_AUTH)
            assert (response.status_code, response.json()) == (503, {"detail": "episode_archive_unavailable"}), state


# --- RR-f ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("point", "detail"),
    [
        pytest.param("archive_read", "episode_archive_not_open", id="archive_read"),
        pytest.param("participant_insert", "episode_restore_interrupted_by_stop", id="participant_insert"),
    ],
)
async def test_restore_route_maps_a_stop_during_the_restore_to_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, detail: str,
) -> None:
    before_the_access = point == "archive_read"  # this stop comes before the restore's audit row is written
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        entered, release = _pause_in(rig, monkeypatch, point)

        async with _client(_runtime(tmp_path, em, token=_TOKEN)) as client:
            task = asyncio.create_task(_post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)  # premise: the restore is paused inside this await
                assert not task.done()
                await asyncio.wait_for(em.stop(), timeout=5)
                assert em._collection is None  # premise: the stop completed (test-only private access) ...
                assert not task.done()  # ... while the request was still pending
                release.set()
                response = await asyncio.wait_for(task, timeout=5)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert (response.status_code, response.json()) == (503, {"detail": detail})
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # read from the files: no row survived the stop
        assert _count(tmp_path, "episode_archive", eid) == 1  # the archive still holds it
        assert _access_rows(tmp_path, eid) == ([] if before_the_access else [(_CAPTAIN, "restore")])

    # The failed read's exception chain keeps the paused SQLite cursor alive, and an unfinished cursor holds the
    # file's read lock (S2b R-4). These references belong to the test, not to the product (in production they are
    # dropped once the error is handled): release them so the reopen below sees the files as a restart would.
    task = response = entered = release = None
    gc.collect()

    async with _memory(tmp_path, "archive") as again:  # leave the rig, reopen the same files
        assert _raw(again.em, [eid])["ids"] == []  # not live
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # and in no sidecar
        assert _count(tmp_path, "episode_archive", eid) == 1  # the archive row survived the stop


# --- RR-g ----------------------------------------------------------------------------------------------------


async def test_restore_route_reports_a_failed_index_insert_as_500_with_nothing_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        hits, _ = _fail_insert(rig, monkeypatch, "participant_index")
        assert hits == []  # premise: the fault is armed and has not fired

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)

        assert hits == ["participant_index"]  # premise: the injected failure is what the route answered
        assert (response.status_code, response.json()) == (
            500, {"detail": "episode_archive_restore_incomplete:participant_index"},
        )
        assert _raw(rig.em, [eid])["ids"] == []  # not live
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # and in no sidecar: the FTS row the attempt wrote is undone
        assert _count(tmp_path, "episode_archive", eid) == 1  # the archive still holds it
        assert _access_rows(tmp_path, eid) == [(_CAPTAIN, "restore")]  # the audit row was written before the failure


# --- RR-h ----------------------------------------------------------------------------------------------------

_JSON_HEADERS = {"Content-Type": "application/json", **_AUTH}


@pytest.mark.parametrize(
    ("body", "content", "status", "reason"),
    [
        pytest.param({}, None, 422, "missing", id="empty_object"),
        pytest.param({"episode_id": ""}, None, 422, "string_too_short", id="empty_episode_id"),
        pytest.param({"episode_id": "e" * 257}, None, 422, "string_too_long", id="episode_id_of_257_characters"),
        pytest.param({"episode_id": "ep-000", "extra": 1}, None, 422, "extra_forbidden", id="unknown_field"),
        # The JSON parser accepts NaN; the route-local guard must refuse it. Sent raw: ``json=`` cannot encode it. The
        # framework alone would answer 500 here (its 422 handler cannot encode NaN); the guard gives a typed 422.
        pytest.param(
            None, b'{"episode_id": "ep-000", "extra": NaN}', 422, "non_finite_number_in_body", id="unknown_field_with_nan",
        ),
        pytest.param(["ep-000"], None, 422, "model_attributes_type", id="array_body"),
        pytest.param(None, b'"ep-000"', 422, "model_attributes_type", id="string_body"),
        pytest.param(None, b"42", 422, "model_attributes_type", id="number_body"),
        # The boundary of the length rule: 256 characters pass validation, and name nothing that was archived.
        pytest.param({"episode_id": "e" * 256}, None, 404, "episode_archive_not_found", id="episode_id_of_256_characters"),
    ],
)
async def test_restore_route_validates_the_request(
    tmp_path: Path, body: Any, content: bytes | None, status: int, reason: str,
) -> None:
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        assert eid == "ep-000"  # premise: the bodies above name this subject, so a wrongly accepted one would restore it

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, body, headers=_JSON_HEADERS, content=content)

        assert response.status_code == status, f"{response.status_code} {response.text}"
        detail = response.json()["detail"]
        if isinstance(detail, str):  # the route's own answer: its non-finite-number guard, or the archive's refusal
            assert detail == reason
        else:  # the framework's own validation error: a list of errors that names the rule that refused the body
            assert reason in response.text
        assert _raw(rig.em, [eid])["ids"] == []  # nothing was restored
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # nothing was indexed
        assert _access_rows(tmp_path, eid) == []  # and nothing was audited
        assert _count(tmp_path, "episode_archive", eid) == 1  # the archive row is as it was


# --- RR-i ----------------------------------------------------------------------------------------------------


async def _arm_marked_access_failure(archive: EpisodeArchive, episode_id: str) -> None:
    """S2a's ``_arm_failing_access``, with a stored value in the failure's text as a driver error can carry one.

    A real SQLite failure on the archive's own connection, so both ``record_access`` and the lookups' access INSERT hit it.
    """
    await archive._db.execute(  # test-only private access
        "CREATE TEMP TRIGGER fail_access BEFORE INSERT ON main.archive_access "
        f"WHEN NEW.episode_id = '{episode_id}' "
        f"BEGIN SELECT RAISE(ABORT, 'injected access failure on {_STORED_VALUE_MARKER}'); END"
    )
    await archive._db.commit()


async def _marked_driver_error_premise(archive: EpisodeArchive, episode_id: str) -> str:
    """Prove the armed failure is a real driver error carrying the marker; return its type name, which the log may show."""
    with pytest.raises(sqlite3.Error, match=_STORED_VALUE_MARKER) as raised:
        await archive.record_access(episode_id, accessor="premise", purpose="restore")
    access_rows = _query(  # test-only private access to the archive's path; a raw read-only witness of its own
        Path(archive._db_path), "SELECT count(*) FROM archive_access WHERE episode_id = ?", (episode_id,),
    )
    assert access_rows == [(0,)]  # premise: the failed INSERT left no access row
    return type(raised.value).__name__


def _probos_texts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every INFO-or-higher record the product logged, rendered as the PRODUCTION formatter renders it.

    ``Formatter.format`` appends the whole traceback chain whenever ``record.exc_info`` is set, whatever the format
    string says, so a record that carries ``exc_info`` shows its exception text here. Call ``caplog.set_level(logging.INFO)``
    before the request.
    """
    formatter = LogRedactionFormatter("%(message)s")
    return [
        formatter.format(record)
        for record in caplog.records
        if record.name.startswith("probos") and record.levelno >= logging.INFO
    ]


def _route_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if record.name == "probos.routers.security" and record.levelno == logging.ERROR
    ]


async def test_restore_route_maps_an_unexpected_failure_to_a_typed_500_and_logs_no_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        archive = rig.em._episode_archive  # test-only private access
        await _arm_marked_access_failure(archive, eid)
        name = await _marked_driver_error_premise(archive, eid)  # premise: a real driver error carrying the marker
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)

        assert (response.status_code, response.json()) == (500, {"detail": "episode_archive_restore_failed"})
        [record] = _route_errors(caplog)  # exactly one ERROR record from the route
        message = record.getMessage()
        # A3 (F3): the id is shown as its repr, and the unexpected branch now carries its error code too.
        assert (
            repr(eid[:8]) in message and "failed unexpectedly" in message
            and "episode_archive_restore_failed" in message and name in message
        )
        assert record.exc_info is None
        texts = _probos_texts(caplog)
        assert any("failed unexpectedly" in text for text in texts)  # premise: the route's record is among those searched
        assert [text for text in texts if _STORED_VALUE_MARKER in text] == []
        assert _raw(rig.em, [eid])["ids"] == []  # not live
        assert _sidecar_counts(tmp_path, eid) == _NO_SIDECARS  # and in no sidecar
        assert _access_rows(tmp_path, eid) == []  # the audit row never committed


# --- RR-j ----------------------------------------------------------------------------------------------------


async def test_restore_route_returns_the_version_the_lookup_route_showed(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        # Two versions with one forced ``archived_at``: no assertion depends on the clock (as R-6 forces its tie).
        versions = await _two_crafted_versions(rig, eid, {"0" * 64: 7000.0, "f" * 64: 7000.0})
        assert sorted(versions) == ["0" * 64, "f" * 64]  # premise: two versions of the one id are archived

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            looked_up = await _post(client, _LOOKUP, {"episode_id": eid}, headers=_AUTH)
            assert looked_up.status_code == 200, looked_up.text
            [shown] = looked_up.json()["episodes"]  # one version is shown
            assert shown["metadata"]["content_hash"] == "0" * 64  # the tie is broken as R-6 pins it
            assert _canonical(shown["metadata"]) == _canonical(versions["0" * 64])  # canonical bytes: 1.0 and 2.0 differ

            restored = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)
            assert (restored.status_code, restored.json()) == (200, {"episode_id": eid, "restored": True})

        live = _raw(rig.em, [eid])
        assert live["ids"] == [eid]
        assert live["metadatas"][0]["content_hash"] == "0" * 64  # the version the lookup route showed ...
        assert _canonical(live["metadatas"][0]) == _canonical(shown["metadata"])  # ... and exactly its metadata


# --- RR-k ----------------------------------------------------------------------------------------------------


async def test_seam_step12_lookup_restore_recall_forget(tmp_path: Path) -> None:
    eid, other = "ep-000", "ep-001"
    archived_only = {**_GONE, "episode_archive": 1}  # in the archive and in no other store, and nothing has read it
    recall_query = "alpha coolant loop"
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        snapshot = await _store_and_evict(em, [0, 1])  # Step 12's own call archives both; each raw record is taken first
        document, metadata = snapshot[eid]
        for episode_id in (eid, other):  # premise: both archived, in no other store, and unread
            assert await _traces(em, tmp_path, episode_id) == archived_only, episode_id
            assert _access_rows(tmp_path, episode_id) == []
        assert eid not in [hit for hit, _ in await em.keyword_search("alpha")]  # premise: nothing live to find yet
        assert eid not in [episode.id for episode in await em.recall_for_agent("agent-a", recall_query, k=6)]

        async with _client(_runtime(tmp_path, em, token=_TOKEN)) as client:
            looked_up = await _post(client, _LOOKUP, {"episode_id": eid}, headers=_AUTH)
            assert looked_up.status_code == 200, looked_up.text
            assert _episode_ids(looked_up.json()) == [eid]
            [shown] = looked_up.json()["episodes"]
            assert shown["document"] == document  # the lookup route returns the record, as the live store held it
            assert _canonical(shown["metadata"]) == _canonical(metadata)

            restored = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)
            assert (restored.status_code, restored.json()) == (200, {"episode_id": eid, "restored": True})

            live = _raw(em, [eid])
            assert (live["ids"], live["documents"]) == ([eid], [document])
            assert _canonical(live["metadatas"][0]) == _canonical(metadata)
            assert _sidecar_counts(tmp_path, eid) == _LIVE_SIDECARS
            assert eid in [hit for hit, _ in await em.keyword_search("alpha")]  # the FTS channel finds it again
            assert eid in [episode.id for episode in await em.recall_for_agent("agent-a", recall_query, k=6)]
            assert _access_rows(tmp_path, eid) == [(_ACCESSOR, "lookup"), (_CAPTAIN, "restore")]  # in id order, not time

            forgotten = await _post(client, _FORGET, {"episode_id": eid})  # the AD-754 route
            assert forgotten.status_code == 200, forgotten.text
            assert forgotten.json()["deleted_count"] == 1
            assert forgotten.json()["deleted_episode_ids"] == [eid]

        # live store, FTS, activation, participants, archive and access rows: none is left for the erased id
        assert await _traces(em, tmp_path, eid) == _GONE
        assert await _traces(em, tmp_path, other) == archived_only  # the other episode stays archived, unread
        assert _access_rows(tmp_path, other) == []


# --- RR-l ----------------------------------------------------------------------------------------------------


class _CallSites(ast.NodeVisitor):
    """Every call whose callee is an attribute named in ``attributes``, with the name of the function that holds it."""

    def __init__(self, attributes: frozenset[str]) -> None:
        self._attributes = attributes
        self._enclosing: list[str] = []
        self.sites: list[tuple[str, str]] = []  # (attribute, enclosing function)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enclosing.append(node.name)
        self.generic_visit(node)
        self._enclosing.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in self._attributes:
            self.sites.append((node.func.attr, self._enclosing[-1] if self._enclosing else "<module>"))
        self.generic_visit(node)


def test_only_the_route_restores_and_only_restore_reads_get_records() -> None:
    sites: dict[str, list[tuple[str, str]]] = {"restore_from_archive": [], "get_records": []}
    parsed = 0
    for path in sorted(_SRC.rglob("*.py")):
        visitor = _CallSites(frozenset(sites))
        visitor.visit(ast.parse(path.read_bytes(), filename=str(path)))
        parsed += 1
        for attribute, function in visitor.sites:
            sites[attribute].append((path.relative_to(_SRC).as_posix(), function))

    assert parsed > 500  # premise: the whole product tree was parsed, not a corner of it
    assert sites["restore_from_archive"] == [("routers/security.py", "restore_archived_episode")]
    assert sites["get_records"] == [("cognitive/episodic.py", "restore_from_archive")]


# --- RR-m ----------------------------------------------------------------------------------------------------


async def test_restore_route_reports_a_real_chroma_rejection_without_copying_stored_metadata_into_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The reviewer's case through the real app, with no injection: Chroma's own rejection quotes a stored value."""
    caplog.set_level(logging.INFO)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        [row] = [candidate for candidate in _archive_rows(rig.root) if candidate["episode_id"] == subject]
        archived = decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
        # A different content_hash matters: the same key would upsert onto the original row.
        crafted = {**archived.metadata, "content_hash": "f" * 64, _STORED_VALUE_MARKER: {_STORED_VALUE_MARKER: "x"}}
        await em._episode_archive.archive(  # test-only private access
            [ArchiveRecord(episode_id=subject, document=archived.document, metadata=crafted)], reason="activation_decay",
        )
        _write(
            _archive_path(rig.root),
            "DELETE FROM episode_archive WHERE episode_id = ? AND content_hash = ?",
            (subject, row["content_hash"]),
        )
        [only] = [candidate for candidate in _archive_rows(rig.root) if candidate["episode_id"] == subject]
        assert only["content_hash"] != row["content_hash"]  # premise: only the crafted version remains
        assert only["content_hash"] == "f" * 64

        # Premise probe (test-only): the REAL live collection rejects this metadata, and its text quotes the stored value.
        with pytest.raises(Exception) as rejected:
            em._collection.add(ids=["rr-m-probe"], documents=[archived.document], metadatas=[crafted])
        assert _STORED_VALUE_MARKER in str(rejected.value)
        assert _raw(em, ["rr-m-probe"])["ids"] == []  # the probe itself left nothing live
        name = type(rejected.value).__name__
        del rejected
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": subject}, headers=_AUTH)

        assert (response.status_code, response.json()) == (500, {"detail": "episode_archive_restore_incomplete:live_add"})
        [record] = _route_errors(caplog)  # exactly one ERROR record from the route
        message = record.getMessage()
        # A3: the id prefix is logged as its repr (it used to be interpolated with %s).
        assert repr(subject[:8]) in message and "episode_archive_restore_incomplete:live_add" in message and name in message
        assert record.exc_info is None
        texts = _probos_texts(caplog)
        assert any("could not write its live_add row" in text for text in texts)  # premise: the episodic WARNING is searched
        assert [text for text in texts if _STORED_VALUE_MARKER in text] == []
        assert _raw(em, [subject])["ids"] == []  # not live
        assert _sidecar_counts(rig.root, subject) == _NO_SIDECARS  # and in no sidecar
        assert _access_rows(rig.root, subject) == [(_CAPTAIN, "restore")]  # the audit row was written before the add


# --- RR-n ----------------------------------------------------------------------------------------------------


async def test_restore_route_never_answers_or_logs_free_text_as_a_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The route's own guard (A2): every real raise site passes a code, so a free-text ``EpisodeArchiveError`` is injected."""
    caplog.set_level(logging.INFO)
    free_text = f"restore failed on {_STORED_VALUE_MARKER}: {{'k': 'v'}}"
    asked: list[str] = []

    async def raiser(episode_id: str, **kwargs: Any) -> Any:
        asked.append(episode_id)
        raise EpisodeArchiveError(free_text)

    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        monkeypatch.setattr(rig.em, "restore_from_archive", raiser)  # test-only: no real raise site gives free text
        with pytest.raises(EpisodeArchiveError, match=_STORED_VALUE_MARKER):
            await rig.em.restore_from_archive(eid)  # premise: the patched restore raises free text carrying the marker
        assert asked == [eid]
        asked.clear()
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": eid}, headers=_AUTH)

        assert asked == [eid]  # the route reached the patched restore
        assert (response.status_code, response.json()) == (500, {"detail": "episode_archive_restore_failed"})
        assert _STORED_VALUE_MARKER not in response.text
        [record] = _route_errors(caplog)  # exactly one ERROR record from the route
        message = record.getMessage()
        assert repr(eid[:8]) in message  # A3: the id prefix is logged as its repr
        assert "episode_archive_restore_failed" in message and "EpisodeArchiveError" in message
        assert record.exc_info is None
        texts = _probos_texts(caplog)
        assert any("archive restore of" in text for text in texts)  # premise: the route's record is among those searched
        assert [text for text in texts if _STORED_VALUE_MARKER in text] == []
        assert _raw(rig.em, [eid])["ids"] == []  # nothing was restored
        assert _access_rows(tmp_path, eid) == []  # and nothing was audited


# --- RR-o ----------------------------------------------------------------------------------------------------


async def test_lookup_route_logs_no_exception_text(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        archive = rig.em._episode_archive  # test-only private access
        await _arm_marked_access_failure(archive, eid)
        name = await _marked_driver_error_premise(archive, eid)  # premise: a real driver error carrying the marker
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _LOOKUP, {"episode_id": eid}, headers=_AUTH)

        assert (response.status_code, response.json()) == (500, {"detail": "episode_archive_access_not_recorded"})
        [record] = _route_errors(caplog)  # exactly one ERROR record from the route
        message = record.getMessage()
        assert "episode_archive_access_not_recorded" in message and name in message
        assert record.exc_info is None
        texts = _probos_texts(caplog)
        assert any("archive lookup failed" in text for text in texts)  # premise: the route's record is among those searched
        assert [text for text in texts if _STORED_VALUE_MARKER in text] == []
        assert _access_rows(tmp_path, eid) == []  # the lookup returned nothing, so it audited nothing


# --- RR-p ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "code", "type_name"),
    [
        pytest.param(
            EpisodeArchiveError("episode_archive_restore_incomplete:live_add"),
            "episode_archive_restore_incomplete:live_add",
            "EpisodeArchiveError",
            id="archive_error",
        ),
        pytest.param(RuntimeError("boom"), "episode_archive_restore_failed", "RuntimeError", id="unexpected_error"),
    ],
)
async def test_restore_route_logs_only_an_escaped_prefix_of_the_requested_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    raised: Exception, code: str, type_name: str,
) -> None:
    """A3 (F2): the 8-character cut bounds the id in the log and ``%r`` escapes it; neither alone is enough."""
    caplog.set_level(logging.INFO)
    requested = "ab\ncd\x1bf\r" + "ijklmnop" * 4  # 40 characters; the first 8 hold a line feed, an ESC and a carriage return
    asked: list[str] = []

    async def raiser(episode_id: str, **kwargs: Any) -> Any:
        asked.append(episode_id)
        raise raised

    async with _memory(tmp_path, "archive") as rig:
        monkeypatch.setattr(rig.em, "restore_from_archive", raiser)  # test-only: the raise is the premise
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _RESTORE, {"episode_id": requested}, headers=_AUTH)

        assert asked == [requested]  # validation passed the whole id through
        assert (response.status_code, response.json()) == (500, {"detail": code})
        [record] = _route_errors(caplog)  # exactly one ERROR record from the route
        message = record.getMessage()
        assert repr(requested[:8]) in message and code in message and type_name in message
        assert "ijklmnop" not in message  # only the first 8 characters
        assert record.exc_info is None
        rendered = LogRedactionFormatter("%(message)s").format(record)
        assert "\n" not in rendered and "\r" not in rendered and "\x1b" not in rendered
        assert repr(requested[:8]) in rendered
        assert [text for text in _probos_texts(caplog) if "ijklmnop" in text] == []


# --- RR-q ----------------------------------------------------------------------------------------------------

_UNPAIRED = "unpaired_surrogate_in_body"
_NON_FINITE = "non_finite_number_in_body"
_SURROGATE_BODIES = [
    pytest.param(b'{"episode_id": "\\ud800"}', _UNPAIRED, id="value"),
    pytest.param(b'{"episode_id": "ep-\\ud800-000"}', _UNPAIRED, id="inside_a_longer_value"),
    pytest.param(b'{"episode_id": "\\udc00"}', _UNPAIRED, id="low_surrogate_alone"),
    pytest.param(b'{"episode_id": "\\ude00\\ud83d"}', _UNPAIRED, id="reversed_pair"),
    pytest.param(b'{"episode_id": "ep-000", "\\ud800": 1}', _UNPAIRED, id="object_key"),
    pytest.param(b'{"episode_id": "ep-000", "extra": [["\\ud800"]]}', _UNPAIRED, id="nested_list"),
    pytest.param(b'"\\ud800"', _UNPAIRED, id="top_level_string"),
    # Raw CESU-8 bytes: json.loads decodes bytes with ``surrogatepass`` (CPython ``json/__init__.py``).
    pytest.param(b'{"episode_id": "\xed\xa0\x80"}', _UNPAIRED, id="raw_cesu_bytes"),
    pytest.param(b'{"episode_id": "\\ud800", "extra": NaN}', _NON_FINITE, id="nan_first"),
    # Premises: valid Unicode, including escaped control characters, still reaches the handler.
    pytest.param(b'{"episode_id": "\\ud83d\\ude00"}', None, id="paired_surrogates"),
    pytest.param(b'{"episode_id": "ep\\n000\\u001b"}', None, id="control_characters"),
]


@pytest.mark.parametrize("path", [_RESTORE, _LOOKUP], ids=["restore", "lookup"])
@pytest.mark.parametrize(("content", "code"), _SURROGATE_BODIES)
async def test_archive_routes_refuse_an_unpaired_surrogate_without_echoing_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, path: str, content: bytes, code: str | None,
) -> None:
    """A3 (F1): the framework's 422 renderer cannot encode an unpaired surrogate and answered a 500 with nothing logged."""
    caplog.set_level(logging.INFO)
    async with _memory(tmp_path, "archive") as rig:
        eid = await _archive_one(rig, 0)  # premise: archived, not live, in no sidecar, no access row
        assert eid == "ep-000"
        assert _route_errors(caplog) == []  # premise: the route has logged nothing yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, path, content=content, headers=_JSON_HEADERS)

        if code is not None:
            assert (response.status_code, response.json()) == (422, {"detail": code}), f"{response.status_code} {response.text}"
            assert response.headers["content-type"].startswith("application/json")
        elif path == _RESTORE:  # valid Unicode: the handler ran and found nothing archived under that id
            assert (response.status_code, response.json()) == (404, {"detail": "episode_archive_not_found"})
        else:
            assert response.status_code == 200, f"{response.status_code} {response.text}"
            assert response.json()["episodes"] == []
        assert _raw(rig.em, [eid])["ids"] == []  # nothing was restored
        assert _access_rows(tmp_path, eid) == []  # and nothing was audited
        assert _count(tmp_path, "episode_archive", eid) == 1  # the archive row is as it was
        assert _route_errors(caplog) == []  # the guard answers before the handler, so no route ERROR


# --- RR-r ----------------------------------------------------------------------------------------------------


def test_unpaired_surrogate_walk_is_exact_and_iterative() -> None:
    """A3: the walk finds exactly what strict UTF-8 cannot encode, in keys and values, at any depth, without recursion.

    A Python literal ``"\\ud83d\\ude00"`` is two unpaired code points; a joined pair is written ``"\\U0001f600"``.
    """
    for holds in ("\ud800", "\udc00", "\ud83d\ude00", {"k\ud800": 1}, {"k": ["a", {"b": "\udfff"}]}):
        assert _holds_unpaired_surrogate(holds) is True, repr(holds)
    for clean in ("\U0001f600", "ep\n000\x1b", [1, 2.5, None, True, "ok", {"a": "é"}], {}, []):
        assert _holds_unpaired_surrogate(clean) is False, repr(clean)

    deep: Any = "\ud800"
    clean_deep: Any = "ok"
    deep_key: Any = {"\ud800": 0}
    for _ in range(10_000):  # a recursive walk raises RecursionError here
        deep = [deep]
        clean_deep = [clean_deep]
        deep_key = {"k": deep_key}
    assert _holds_unpaired_surrogate(deep) is True
    assert _holds_unpaired_surrogate(clean_deep) is False
    assert _holds_unpaired_surrogate(deep_key) is True
