"""AD-537: Tests for learned_via / learned_from fields on Procedure."""

from __future__ import annotations

import asyncio
import json

import pytest

from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep


@pytest.fixture
def store(tmp_path):
    s = ProcedureStore(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(s.start())
    yield s
    asyncio.get_event_loop().run_until_complete(s.stop())


def _make_procedure(proc_id: str = "test1", name: str = "Test Proc",
                    learned_via: str = "direct", learned_from: str = "") -> Procedure:
    """Create a minimal Procedure suitable for learned_via tests."""
    return Procedure(
        id=proc_id,
        name=name,
        steps=[ProcedureStep(step_number=1, action="test action")],
        learned_via=learned_via,
        learned_from=learned_from,
    )


@pytest.mark.asyncio
async def test_learned_via_default_direct() -> None:
    """New procedures should default learned_via to 'direct'."""
    proc = Procedure(
        id="default1",
        name="Default Proc",
        steps=[ProcedureStep(step_number=1, action="do something")],
    )
    assert proc.learned_via == "direct"
    assert proc.learned_from == ""


@pytest.mark.asyncio
async def test_learned_via_persists_save_load(store: ProcedureStore) -> None:
    """save() + get() should preserve the learned_via field."""
    proc = _make_procedure("via1", learned_via="observational", learned_from="data")
    await store.save(proc)

    loaded = await store.get("via1")
    assert loaded is not None
    assert loaded.learned_via == "observational"


@pytest.mark.asyncio
async def test_learned_from_persists(store: ProcedureStore) -> None:
    """save() + get() should preserve the learned_from field."""
    proc = _make_procedure("from1", learned_via="taught", learned_from="laforge")
    await store.save(proc)

    loaded = await store.get("from1")
    assert loaded is not None
    assert loaded.learned_from == "laforge"
    assert loaded.learned_via == "taught"


@pytest.mark.asyncio
async def test_migration_adds_columns(store: ProcedureStore) -> None:
    """_ensure_learned_via_columns() should add learned_via and learned_from columns."""
    cursor = await store._db.execute("PRAGMA table_info(procedure_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    expected_cols = {"learned_via", "learned_from"}
    assert expected_cols.issubset(columns), f"Missing columns: {expected_cols - columns}"


@pytest.mark.asyncio
async def test_to_dict_includes_learned_via() -> None:
    """to_dict() serialization should include learned_via and learned_from."""
    proc = _make_procedure("dict1", learned_via="observational", learned_from="worf")
    d = proc.to_dict()
    assert d["learned_via"] == "observational"
    assert d["learned_from"] == "worf"


@pytest.mark.asyncio
async def test_from_dict_includes_learned_via() -> None:
    """from_dict() deserialization should restore learned_via and learned_from."""
    data = {
        "id": "fromdict1",
        "name": "From Dict Proc",
        "steps": [{"step_number": 1, "action": "test"}],
        "learned_via": "taught",
        "learned_from": "bones",
    }
    proc = Procedure.from_dict(data)
    assert proc.learned_via == "taught"
    assert proc.learned_from == "bones"

    # Also verify defaults when keys are absent
    sparse = {"id": "fromdict2", "name": "Sparse", "steps": []}
    proc2 = Procedure.from_dict(sparse)
    assert proc2.learned_via == "direct"
    assert proc2.learned_from == ""
