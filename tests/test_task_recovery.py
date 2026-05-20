import pytest
import asyncio
from probos.cognitive.task_recovery import TaskRecoveryManager

@pytest.mark.asyncio
async def test_pending_tasks_listed():
    mgr = TaskRecoveryManager()
    pending = await mgr.list_pending_delegations("session-123")
    assert isinstance(pending, list)

@pytest.mark.asyncio
async def test_task_status_polling():
    mgr = TaskRecoveryManager()
    status = await mgr.check_delegation_status("task-xyz")
    assert isinstance(status, dict)
    assert status["task_id"] == "task-xyz"
    assert "status" in status
