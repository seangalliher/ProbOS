"""AD-538: Tests for lifecycle shell commands."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.experience.commands.commands_procedure import cmd_procedure


@pytest.fixture
def mock_runtime():
    """Minimal runtime mock with ProcedureStore."""
    runtime = MagicMock()
    store = AsyncMock()
    store.get_stale_procedures = AsyncMock(return_value=[])
    store.get_archived_procedures = AsyncMock(return_value=[])
    store.restore_procedure = AsyncMock(return_value=True)
    store.find_duplicate_candidates = AsyncMock(return_value=[])
    store.merge_procedures = AsyncMock(return_value=True)
    store.get = AsyncMock(return_value=None)
    store.get_quality_metrics = AsyncMock(return_value={"total_completions": 10})
    runtime.procedure_store = store
    return runtime


@pytest.fixture
def console():
    """Mock Rich console that captures output."""
    c = MagicMock()
    c.printed = []
    c.print = MagicMock(side_effect=lambda *a, **kw: c.printed.append(str(a[0]) if a else ""))
    return c


@pytest.mark.asyncio
async def test_procedure_stale_command(mock_runtime, console):
    """/procedure stale lists stale procedures."""
    mock_runtime.procedure_store.get_stale_procedures.return_value = [
        {"id": "abc12345", "name": "Old Proc", "compilation_level": 3,
         "days_unused": 35, "total_completions": 10, "total_selections": 12,
         "last_used_at": time.time() - 86400 * 35},
    ]
    await cmd_procedure(mock_runtime, console, "stale")
    mock_runtime.procedure_store.get_stale_procedures.assert_called_once_with(days=None)


@pytest.mark.asyncio
async def test_procedure_stale_custom_days(mock_runtime, console):
    """/procedure stale --days 60 passes custom days."""
    await cmd_procedure(mock_runtime, console, "stale --days 60")
    mock_runtime.procedure_store.get_stale_procedures.assert_called_once_with(days=60)


@pytest.mark.asyncio
async def test_procedure_archived_command(mock_runtime, console):
    """/procedure archived lists archived procedures."""
    mock_runtime.procedure_store.get_archived_procedures.return_value = [
        {"id": "arch123", "name": "Archived", "compilation_level": 1,
         "last_used_at": 0, "total_completions": 5, "archived_at": time.time()},
    ]
    await cmd_procedure(mock_runtime, console, "archived")
    mock_runtime.procedure_store.get_archived_procedures.assert_called_once_with(limit=20)


@pytest.mark.asyncio
async def test_procedure_restore_command(mock_runtime, console):
    """/procedure restore <id> restores procedure."""
    from probos.cognitive.procedures import Procedure, ProcedureStep
    mock_runtime.procedure_store.get.return_value = Procedure(
        id="rest123", name="Restored Proc", steps=[ProcedureStep(step_number=1, action="test")]
    )
    await cmd_procedure(mock_runtime, console, "restore rest123")
    mock_runtime.procedure_store.restore_procedure.assert_called_once_with("rest123")


@pytest.mark.asyncio
async def test_procedure_duplicates_command(mock_runtime, console):
    """/procedure duplicates lists candidates."""
    mock_runtime.procedure_store.find_duplicate_candidates.return_value = [
        {"primary_id": "p1", "primary_name": "A", "duplicate_id": "d1",
         "duplicate_name": "B", "similarity": 0.92},
    ]
    await cmd_procedure(mock_runtime, console, "duplicates")
    mock_runtime.procedure_store.find_duplicate_candidates.assert_called_once()


@pytest.mark.asyncio
async def test_procedure_merge_command(mock_runtime, console):
    """/procedure merge <p> <d> merges procedures."""
    from probos.cognitive.procedures import Procedure, ProcedureStep
    p = Procedure(id="p1", name="Primary", steps=[ProcedureStep(step_number=1, action="test")])
    d = Procedure(id="d1", name="Dup", steps=[ProcedureStep(step_number=1, action="test")])
    mock_runtime.procedure_store.get = AsyncMock(side_effect=lambda pid: p if pid == "p1" else d)
    await cmd_procedure(mock_runtime, console, "merge p1 d1")
    mock_runtime.procedure_store.merge_procedures.assert_called_once_with("p1", "d1")


@pytest.mark.asyncio
async def test_procedure_merge_invalid_ids(mock_runtime, console):
    """Bad IDs → error message."""
    mock_runtime.procedure_store.get = AsyncMock(return_value=None)
    await cmd_procedure(mock_runtime, console, "merge badid1 badid2")
    # Should print error about not found
    assert any("not found" in str(p).lower() for p in console.printed)
