"""AD-1347 S1 (#1627) M2: the runtime builds the agent-work service only when enabled, over its own collaborators.

Real boots of ``ProbOSRuntime`` with the mock LLM, as ``tests/test_ad1346_admission_service_boot.py`` does, with the
workforce store on. W1 is the boot half of the byte-identical-when-off golden (the store half is
``tests/test_ad1347_s1_agent_work.py`` tests 13 and 28; the default-config half is ``tests/test_ad1152_agentic_correlation.py``).
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

import probos.agent_work as agent_work_module
import probos.config as probos_config
import probos.knowledge.embeddings as embeddings_module
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkRefusal, AgentWorkService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AgentWorkConfig, ArchiveConfig, SystemConfig, WorkforceConfig
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from tests.test_ad1346_admission_service_boot import _config as _admission_boot_config

AGENT_WORK_TABLES = {"agent_work_watchers", "agent_work_notices"}


def _boot_config(*, enabled: bool) -> SystemConfig:
    """AD-1346's boot shape with the workforce store on and the Ship's Archive off (A3, F1).

    An empty ``archive.db_path`` resolves to the live vessel's archive outside ``tmp_path``, and an enabled archive
    opens and migrates that file at boot. These boots need no archive, so it is off (``lifecycle_config`` redirects it
    instead).
    """
    return _admission_boot_config().model_copy(update={
        "workforce": WorkforceConfig(enabled=True), "agent_work": AgentWorkConfig(enabled=enabled),
        "archive": ArchiveConfig(enabled=False),
    })


@pytest.fixture
def archive_resolutions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every call a boot makes to resolve the Ship's Archive path; each test asserts there is none (A3, F1).

    The boot imports ``resolve_archive_db_path`` inside its archive block, so replacing the module attribute is what
    it calls. The spy answers with a path under ``tmp_path``, so even a boot that regresses never opens the live file.
    """
    calls: list[object] = []

    def _resolve_under_tmp(archive: object) -> Path:
        calls.append(archive)
        return tmp_path / "archive-pin" / "archive.db"

    monkeypatch.setattr(probos_config, "resolve_archive_db_path", _resolve_under_tmp)
    return calls


@pytest.fixture
def local_embeddings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """BF-657's local embedding backend for the boots, as CI selects it, and where a downloaded model would land (A4).

    Unless ``PROBOS_EMBEDDINGS`` is ``local``, the boot's collection setup asks ``get_embedding_function``, which loads
    a downloaded model; Chroma's ONNX model lands under the home directory, outside ``tmp_path``. The variable is set
    here, not left to the invoking shell. The toggle overwrites the module's memo, so both memo attributes are set
    through ``monkeypatch``, which restores them after the test. The ONNX class reads its download directory from a
    class attribute at each use, so it is redirected under ``tmp_path``: a boot that regresses fails the test, and
    Chroma's model lands under ``tmp_path`` instead of the home directory.
    """
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)
    download_dir = tmp_path / "onnx-pin"
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", download_dir)
    return download_dir


def _assert_no_embedding_model_loaded(download_dir: Path) -> None:
    """No boot downloaded Chroma's ONNX model or loaded any downloaded model (A4, R2-1)."""
    assert not download_dir.exists(), "a boot downloaded Chroma's ONNX model"
    assert embeddings_module._embedding_available is not True, "a boot loaded a downloaded embedding model"


def _tables(path: Path) -> set[str]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return {name for (name,) in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# W1
async def test_the_flag_decides_whether_the_service_and_its_two_tables_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_resolutions: list[object], local_embeddings: Path,
) -> None:
    """Acceptance 7: off never calls the opener and adds no table; on calls it once, adds exactly the two tables, and a
    clean stop releases the service.

    The call count pins the runtime's own guard (mutation row R1): the opener also returns None while off, so the
    outcomes alone cannot tell a runtime that skips its block from one that runs it. The runtime imports the opener
    inside that block, so replacing the module attribute is what the boot calls; the spy delegates to the real opener.
    """
    real_opener = agent_work_module.open_agent_work_service
    opened: list[dict[str, Any]] = []

    async def _counted_opener(**kwargs: Any) -> AgentWorkService | None:
        opened.append(kwargs)
        return await real_opener(**kwargs)

    monkeypatch.setattr(agent_work_module, "open_agent_work_service", _counted_opener)
    off = ProbOSRuntime(config=_boot_config(enabled=False), data_dir=tmp_path / "off", llm_client=MockLLMClient())
    await off.start()
    try:
        assert off.work_item_store is not None, "premise: the workforce store is on"
        assert off.agent_work is None
        assert opened == [], "while off the runtime never calls the opener"
    finally:
        await off.stop()
    on = ProbOSRuntime(config=_boot_config(enabled=True), data_dir=tmp_path / "on", llm_client=MockLLMClient())
    await on.start()
    try:
        assert isinstance(on.agent_work, AgentWorkService)
        assert len(opened) == 1 and opened[0]["config"].enabled is True, opened
    finally:
        await on.stop()
    assert on.agent_work is None, "a clean stop releases the service"
    off_tables = _tables(tmp_path / "off" / "workforce.db")
    on_tables = _tables(tmp_path / "on" / "workforce.db")
    assert not off_tables & AGENT_WORK_TABLES
    assert on_tables - off_tables == AGENT_WORK_TABLES
    assert archive_resolutions == [], "neither boot resolves the Ship's Archive path (A3, F1)"
    _assert_no_embedding_model_loaded(local_embeddings)


# W2
async def test_an_enabled_boot_creates_a_self_task_under_the_agents_slot_through_the_real_identity_facade(
    tmp_path: Path, archive_resolutions: list[object], local_embeddings: Path,
) -> None:
    """Acceptance 6 and premise 8 on the real IdentityService: a DID becomes its slot; an unknown DID is refused."""
    rt = ProbOSRuntime(config=_boot_config(enabled=True), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    try:
        service = rt.agent_work
        assert isinstance(service, AgentWorkService)
        crew = next(
            (
                a for a in rt.registry.all()
                if a.did and is_crew_agent(a, rt.ontology)
                and getattr(rt.identity_service.resolve(a.did), "slot_id", None) == a.id
            ),
            None,
        )
        assert crew is not None, "premise: a certified crew agent whose DID resolves to its own slot"
        origin = AgentWorkOrigin("dm")
        created = await service.create_self_task(
            crew.did, title="Verify the boot", description="", reason="AD-1347 wiring", origin=origin,
        )
        assert isinstance(created, AgentWorkCreated), created
        assert (created.work_item.created_by, created.work_item.assigned_to) == (crew.id, crew.id)
        stored = await rt.work_item_store.get_work_item(created.work_item.id)
        assert stored is not None and stored.created_by == crew.id
        unknown = await service.create_self_task(
            "did:probos:agent:unknown", title="Nobody", description="", reason="AD-1347 wiring", origin=origin,
        )
        assert isinstance(unknown, AgentWorkRefusal) and unknown.code == "requester_unresolved"
    finally:
        await rt.stop()
    assert archive_resolutions == [], "the boot never resolves the Ship's Archive path (A3, F1)"
    _assert_no_embedding_model_loaded(local_embeddings)
