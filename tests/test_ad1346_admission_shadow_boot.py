"""AD-1346 M3b (#1604) - real-boot tests: the shadow store and recorder are wired, persist across a restart, and fail open on an ``Exception``.

These boot a real ``ProbOSRuntime`` with the mock LLM, as ``tests/test_ad1346_admission_service_boot.py`` does
(``SystemConfig()`` with the naming ceremony, the proactive loop and QA off, or ``lifecycle_config`` for the
rollback). Every data directory is under ``tmp_path``:

- B1 a boot opens the store and builds the service with its recorder; the shadow verdicts of two boots on one data
     directory are in the store after the second stop, each boot's marker rows sum to offered equal to written, and
     the trust scores and the Captain's stop's refusal counts are unchanged across the shadow calls.
- B2 a store file with another schema version is logged once, the service is built with no recorder, the boot
     completes and the file's bytes are unchanged.
- B3 at ``create_agent_fleet`` the store is open and the flusher runs; the rollback of a start that fails there
     closes the store, ends the flusher and releases both attributes.
- B4 the store's declaration names ``ProbOSRuntime.start`` as its lifecycle owner.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from probos.admission import AdmissionService
from probos.admission.recorder import FLUSHER_TASK_NAME, ShadowRecorder
from probos.admission.report import open_read_only, run_query
from probos.admission.store import STORE_FILENAME, AdmissionShadowStore
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import InjectedStartFailure, inject_start_failure, lifecycle_config

CANARY = "CANARY-ad1346-m3b-boot: the Captain's private reason"


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _shadow(gate: Any, presented_id: str, **fields: str) -> None:
    values = {"work_kind": "intent", "seam": "intent", "origin": "captain", "origin_id": "captain", **fields}
    gate.shadow(presented_id=presented_id, **values)


def _flushers() -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if task.get_name() == FLUSHER_TASK_NAME and not task.done()]


async def test_shadow_verdicts_persist_across_a_restart_and_change_no_trust_or_stop_count(tmp_path: Path) -> None:
    """B1 (kills RT-1, RT-4)."""
    data_dir = tmp_path / "data"
    rt = await _boot(data_dir)
    try:
        store, recorder, gate = rt.admission_shadow_store, rt.admission_shadow_recorder, rt.admission_service
        assert isinstance(store, AdmissionShadowStore) and store.is_open and store.path == data_dir / STORE_FILENAME
        assert isinstance(recorder, ShadowRecorder) and isinstance(gate, AdmissionService)
        assert vars(gate)["_recorder"] is recorder, "the service must be built with the boot's recorder"
        crew = next(
            (
                a for a in rt.registry.all()
                if a.did and is_crew_agent(a, rt.ontology) and getattr(rt.identity_service.resolve(a.did), "slot_id", None) == a.id
            ),
            None,
        )
        assert crew is not None, "premise: a certified crew agent whose DID resolves to its own slot"
        issued = await rt.agent_stops.issue_stop(crew.id, reason=CANARY)
        try:
            counts = rt.agent_stops.refused_counts(issued.record.stop_id)
            trust = rt.trust_network.raw_scores()
            _shadow(gate, crew.did)
            _shadow(gate, "nobody-ad1346-m3b")
            _shadow(gate, "system:ship_computer", origin="system", origin_id="system:ship_computer")
            # no await between the reads above and the reads below
            assert rt.agent_stops.refused_counts(issued.record.stop_id) == counts, "shadow counted a refusal"
            assert rt.trust_network.raw_scores() == trust, "shadow changed a trust score"
        finally:
            await rt.agent_stops.lift_stop(crew.id, reason="lifted by the test")
        assert gate.failures == 0 and recorder.counters()["offered"] == 3
        first_boot = recorder.boot_id
    finally:
        await rt.stop()
    assert rt.admission_shadow_recorder is None and rt.admission_shadow_store is None and not store.is_open

    rt = await _boot(data_dir)
    try:
        assert rt.admission_shadow_recorder is not None
        _shadow(rt.admission_service, "system:ship_computer", origin="system", origin_id="system:ship_computer")
        second_boot = rt.admission_shadow_recorder.boot_id
    finally:
        await rt.stop()

    db = await open_read_only(data_dir / STORE_FILENAME)
    try:
        markers = {row[0]: row[3:] for row in await run_query(db, "markers_by_boot")}
        decisions = await run_query(db, "decisions_by_work_kind", ("0000-00-00",))
        samples = await run_query(db, "would_refuse_samples", (10,))
    finally:
        await db.close()
    assert markers == {first_boot: (3, 3, 0, 0), second_boot: (1, 1, 0, 0)}
    assert sorted((row[1], row[2], row[3]) for row in decisions) == [
        ("admit", "admitted", 2), ("would_refuse", "agent_stopped", 1), ("would_refuse", "identity_unresolved", 1),
    ]
    assert sorted(row[5] for row in samples) == ["agent_stopped", "identity_unresolved"]
    assert "CANARY" not in json.dumps(samples)


async def test_a_store_with_another_schema_version_is_logged_and_the_boot_continues_without_a_recorder(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """B2: #1604 property 11 for the store (D47)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / STORE_FILENAME
    db = await default_factory.connect(str(path))
    try:
        await db.executescript(
            "CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version (version) VALUES (2);"
        )
        await db.commit()
    finally:
        await db.close()
    before = path.read_bytes()
    caplog.set_level(logging.WARNING, logger="probos.runtime")
    rt = await _boot(data_dir)
    try:
        assert rt.admission_shadow_store is None and rt.admission_shadow_recorder is None
        assert isinstance(rt.admission_service, AdmissionService) and vars(rt.admission_service)["_recorder"] is None
        assert rt.registry.count > 0, "premise: the boot went on to create the fleet"
        warned = [r for r in caplog.records if r.name == "probos.runtime" and "shadow admission store" in r.getMessage()]
        assert len(warned) == 1 and warned[0].levelno == logging.WARNING
        assert warned[0].exc_info is not None and "schema_version" in str(warned[0].exc_info[1])
    finally:
        await rt.stop()
    assert path.read_bytes() == before


async def test_the_store_and_flusher_exist_at_fleet_entry_and_a_failed_start_releases_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3 (kills RT-2, RT-3)."""
    monkeypatch.chdir(tmp_path)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    seen: list[tuple[Any, bool, Any, list[asyncio.Task[Any]]]] = []

    def at_fleet_entry(rt: ProbOSRuntime) -> None:
        store = rt.admission_shadow_store
        seen.append((store, store is not None and store.is_open, rt.admission_shadow_recorder, _flushers()))

    failure = inject_start_failure(monkeypatch, runtime, "fleet_entry", on_fire=at_fleet_entry)
    with pytest.raises(InjectedStartFailure) as raised:
        await runtime.start()

    assert raised.value is failure.error
    assert len(seen) == 1, "premise: the start reached create_agent_fleet"
    store, was_open, recorder, flushers = seen[0]
    assert isinstance(store, AdmissionShadowStore) and was_open, "the store must be open when the fleet is created"
    assert isinstance(recorder, ShadowRecorder) and len(flushers) == 1, "the flusher must run when the fleet is created"
    assert runtime.admission_shadow_store is None and runtime.admission_shadow_recorder is None
    assert not store.is_open and all(task.done() for task in flushers)


def test_the_declaration_names_the_runtime_start_as_lifecycle_owner() -> None:
    """B4."""
    declaration = load_default_store_registry().get("admission.shadow-decisions")
    assert declaration is not None and declaration.lifecycle_owner == "probos.runtime.ProbOSRuntime.start"
