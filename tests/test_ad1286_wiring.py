"""AD-1286 (#1333): default-off wiring of the elastic team store (Section 4).

The store is opened only inside the existing ``orchestrator_enabled`` crew-session path
(``startup/finalize.py``), bound to the ``CrewSessionService`` as its team-spec lookup, and closed
with the other SQLite sidecars (``startup/shutdown.py``). A default runtime (crew sessions
disabled) must import neither elastic-team module, create no ``elastic_teams.db`` and log no
AD-1286 line.

``tmp_path`` only: never the live vessel data directory (BF-883) and never ``config/system.yaml``.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.crew_session import CrewSessionService
from probos.cognitive.elastic_team_store import ElasticTeamStore, ElasticTeamStoreUnavailable
from probos.config import SystemConfig
from probos.startup.finalize import _wire_crew_session_service, _wire_elastic_team_store
from probos.startup.shutdown import _stop_runtime_sqlite_sidecars
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore
from tests.test_ad1127_crew_session_lifecycle_recovery import _new_session
from tests.test_ad1286_elastic_team_contract import _spec

_FINALIZE_LOGGER = "probos.startup.finalize"

_DISABLED_IMPORT_SCRIPT = (
    "import probos.runtime, probos.startup.finalize, probos.startup.shutdown, "
    "probos.cognitive.crew_session, sys\n"
    "print(sorted(m for m in sys.modules if 'elastic_team' in m))\n"
)


@pytest.fixture
async def work_store(tmp_path: Path) -> AsyncIterator[WorkItemStore]:
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


def _service(work_store: WorkItemStore, tmp_path: Path) -> CrewSessionService:
    return CrewSessionService(
        work_item_store=work_store,
        chat_thread_store=ChatThreadStore(tmp_path / "threads.db"),
    )


def _ad1286_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "AD-1286" in record.getMessage()
    ]


def _is_call_to(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


def _gate_census(tree: ast.AST) -> tuple[int, int]:
    """(gated, ungated) counts of ``_wire_elastic_team_store(...)`` calls.

    A call is gated when it sits lexically inside the BODY of an ``if`` whose test calls
    ``_wire_crew_session_service`` (the ``else`` branch and the test itself do not count).
    """
    counts = {"gated": 0, "ungated": 0}

    def visit(node: ast.AST, gated: bool) -> None:
        if isinstance(node, ast.If):
            opens_gate = any(_is_call_to(child, "_wire_crew_session_service") for child in ast.walk(node.test))
            visit(node.test, gated)
            for child in node.body:
                visit(child, gated or opens_gate)
            for child in node.orelse:
                visit(child, gated)
            return
        if _is_call_to(node, "_wire_elastic_team_store"):
            counts["gated" if gated else "ungated"] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, gated)

    visit(tree, False)
    return counts["gated"], counts["ungated"]


# --------------------------------------------------------------------------------------
# Default-off: nothing is imported, opened, wired or logged
# --------------------------------------------------------------------------------------


def test_disabled_runtime_never_imports_the_elastic_team_modules(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _DISABLED_IMPORT_SCRIPT],
        env={**os.environ, "PROBOS_DATA_DIR": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.stdout.strip() == "[]"


def test_default_config_does_not_wire_crew_sessions(tmp_path: Path) -> None:
    config = SystemConfig()
    runtime = SimpleNamespace(data_dir=tmp_path)

    wired = _wire_crew_session_service(runtime=runtime, config=config)

    assert config.agentic_dispatch.orchestrator_enabled is False
    assert wired is False
    assert vars(runtime) == {"data_dir": tmp_path}
    assert not (tmp_path / "elastic_teams.db").exists()
    assert list(tmp_path.iterdir()) == []


def test_store_wiring_sits_inside_the_crew_session_gate() -> None:
    """Structural placement test: it pins WHERE the call sits, not a defect.

    ``_wire_crew_session_service`` returns False unless ``orchestrator_enabled``, so a call to
    ``_wire_elastic_team_store`` inside the body of that ``if`` is what makes default-off true.
    Moving the call outside the gate (or into the ``else``) would open ``elastic_teams.db`` on
    every runtime without any other test noticing, which is why the placement is pinned here.
    """
    spec = importlib.util.find_spec("probos.startup.finalize")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))

    gated, ungated = _gate_census(tree)

    assert (gated, ungated) == (1, 0)


# --------------------------------------------------------------------------------------
# Enabled: the store opens, binds as the lookup, degrades and closes
# --------------------------------------------------------------------------------------


async def test_enabled_wiring_opens_store_and_binds_lookup(tmp_path: Path, work_store: WorkItemStore) -> None:
    service = _service(work_store, tmp_path)
    runtime = SimpleNamespace(crew_session_service=service, data_dir=tmp_path)
    try:
        wired = await _wire_elastic_team_store(runtime=runtime)

        store = runtime.elastic_team_store
        assert wired is True
        assert (tmp_path / "elastic_teams.db").exists()
        spec = _spec()
        ref = await store.put_team_spec(spec)  # a store that is not started refuses this
        assert await store.get_team_spec(ref) == spec
        assert await _wire_elastic_team_store(runtime=runtime) is True
        assert runtime.elastic_team_store is store
        with pytest.raises(ValueError, match="^crew_session_team_lookup_binding_invalid$"):
            service.bind_team_spec_lookup(store)
    finally:
        await _stop_runtime_sqlite_sidecars(runtime)


async def test_enabled_wiring_opens_store_in_a_data_directory_named_like_a_memory_uri(
    tmp_path: Path, work_store: WorkItemStore
) -> None:
    """R4-1: an ordinary data directory whose name contains ``mode=memory`` wires like any other; startup is not aborted."""
    data_dir = tmp_path / "mode=memory-data"
    data_dir.mkdir()
    runtime = SimpleNamespace(crew_session_service=_service(work_store, tmp_path), data_dir=data_dir)
    try:
        assert await _wire_elastic_team_store(runtime=runtime) is True

        assert (data_dir / "elastic_teams.db").exists()
        ref = await runtime.elastic_team_store.put_team_spec(_spec())
        assert await runtime.elastic_team_store.get_team_spec(ref) == _spec()
    finally:
        await _stop_runtime_sqlite_sidecars(runtime)


async def test_wired_store_is_the_lookup_the_session_binds_against(
    tmp_path: Path, work_store: WorkItemStore
) -> None:
    parent, service, session = await _new_session(work_store, tmp_path)
    runtime = SimpleNamespace(crew_session_service=service, data_dir=tmp_path)
    try:
        assert await _wire_elastic_team_store(runtime=runtime) is True
        ref = await runtime.elastic_team_store.put_team_spec(_spec())

        bound = await service.bind_team_spec(parent.id, ref, expected_session=session)

        assert bound.team_spec_ref == ref
        assert await service.get_team_binding(parent.id) == bound
    finally:
        await _stop_runtime_sqlite_sidecars(runtime)


async def test_start_failure_degrades_and_leaves_binding_unavailable(
    tmp_path: Path, work_store: WorkItemStore, caplog: pytest.LogCaptureFixture
) -> None:
    parent, service, session = await _new_session(work_store, tmp_path)
    (tmp_path / "elastic_teams.db").mkdir()
    runtime = SimpleNamespace(crew_session_service=service, data_dir=tmp_path)

    with caplog.at_level(logging.WARNING, logger=_FINALIZE_LOGGER):
        wired = await _wire_elastic_team_store(runtime=runtime)

    assert wired is False
    assert len(_ad1286_warnings(caplog)) == 1
    assert getattr(runtime, "elastic_team_store", None) is None
    with pytest.raises(ValueError, match="^crew_session_team_lookup_unavailable$"):
        await service.bind_team_spec(parent.id, "a" * 64, expected_session=session)
    assert await service.get_team_binding(parent.id) is None


async def test_shutdown_closes_the_elastic_team_store(tmp_path: Path) -> None:
    store = ElasticTeamStore(db_path=str(tmp_path / "elastic_teams.db"))
    await store.start()
    runtime = SimpleNamespace(elastic_team_store=store)
    failures: list[str] = []

    await _stop_runtime_sqlite_sidecars(runtime, lambda label, _service: failures.append(label))

    assert runtime.elastic_team_store is None
    assert failures == []
    with pytest.raises(ElasticTeamStoreUnavailable, match="^elastic_team_store_unavailable$"):
        await store.put_team_spec(_spec())


async def test_corrupt_store_file_propagates_as_data_integrity(
    tmp_path: Path, work_store: WorkItemStore, caplog: pytest.LogCaptureFixture
) -> None:
    """F9: a file that is not a database is data integrity -- ERROR and fail startup, never warn-and-degrade."""
    parent, service, session = await _new_session(work_store, tmp_path)
    (tmp_path / "elastic_teams.db").write_bytes(b"not a database" * 100)
    runtime = SimpleNamespace(crew_session_service=service, data_dir=tmp_path)

    with caplog.at_level(logging.ERROR, logger=_FINALIZE_LOGGER):
        with pytest.raises(sqlite3.DatabaseError) as refused:
            await _wire_elastic_team_store(runtime=runtime)

    assert not isinstance(refused.value, sqlite3.OperationalError)  # the file is corrupt, not merely unavailable
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and "AD-1286" in r.getMessage()]
    assert len(errors) == 1 and "move the file aside" in errors[0].getMessage()
    assert getattr(runtime, "elastic_team_store", None) is None
    with pytest.raises(ValueError, match="^crew_session_team_lookup_unavailable$"):  # the lookup was never bound
        await service.bind_team_spec(parent.id, "a" * 64, expected_session=session)


async def test_rewiring_after_shutdown_closes_the_new_store_and_publishes_nothing(
    tmp_path: Path,
    work_store: WorkItemStore,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2: the store is published only after the service accepted it as its lookup (no half-wired runtime)."""
    service = _service(work_store, tmp_path)
    runtime = SimpleNamespace(crew_session_service=service, data_dir=tmp_path)
    assert await _wire_elastic_team_store(runtime=runtime) is True
    await _stop_runtime_sqlite_sidecars(runtime)  # shutdown closes the store and clears the attribute
    assert runtime.elastic_team_store is None
    opened: list[ElasticTeamStore] = []

    class _RecordingStore(ElasticTeamStore):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

    monkeypatch.setattr("probos.cognitive.elastic_team_store.ElasticTeamStore", _RecordingStore)

    with caplog.at_level(logging.WARNING, logger=_FINALIZE_LOGGER):
        wired = await _wire_elastic_team_store(runtime=runtime)  # the service still holds the first lookup

    warnings = _ad1286_warnings(caplog)
    assert wired is False
    assert len(warnings) == 1 and "already has a team-spec lookup" in warnings[0]
    assert runtime.elastic_team_store is None  # nothing was published
    assert len(opened) == 1
    with pytest.raises(ElasticTeamStoreUnavailable, match="^elastic_team_store_unavailable$"):
        await opened[0].put_team_spec(_spec())  # the second store was closed, not leaked


async def test_missing_data_dir_degrades_with_warning(
    tmp_path: Path, work_store: WorkItemStore, caplog: pytest.LogCaptureFixture
) -> None:
    runtime = SimpleNamespace(crew_session_service=_service(work_store, tmp_path), data_dir=None)

    with caplog.at_level(logging.WARNING, logger=_FINALIZE_LOGGER):
        wired = await _wire_elastic_team_store(runtime=runtime)

    warnings = _ad1286_warnings(caplog)
    assert wired is False
    assert len(warnings) == 1 and "data directory" in warnings[0]
    assert getattr(runtime, "elastic_team_store", None) is None
    assert not (tmp_path / "elastic_teams.db").exists()


async def test_missing_crew_session_service_degrades_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runtime = SimpleNamespace(data_dir=tmp_path)

    with caplog.at_level(logging.WARNING, logger=_FINALIZE_LOGGER):
        wired = await _wire_elastic_team_store(runtime=runtime)

    warnings = _ad1286_warnings(caplog)
    assert wired is False
    assert len(warnings) == 1 and "crew session service" in warnings[0]
    assert getattr(runtime, "elastic_team_store", None) is None
    assert not (tmp_path / "elastic_teams.db").exists()
