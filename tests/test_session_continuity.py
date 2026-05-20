import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import asyncio
from probos.cognitive.session_manager import SessionManager, Session

@pytest.mark.asyncio
async def test_session_restored_after_restart():
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        manager = SessionManager(sessions_dir=sessions_dir, user_id="captain")
        session = await manager.create_session(agent_type="Yeo", platform="desktop")
        # Simulate activity 1 hour ago
        session.last_activity = datetime.now(timezone.utc) - timedelta(hours=1)
        await manager._write(session)
        restored = await manager.restore_active_session("captain")
        assert restored is not None
        assert restored.id == session.id

@pytest.mark.asyncio
async def test_active_tasks_recoverable():
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        manager = SessionManager(sessions_dir=sessions_dir, user_id="captain")
        session = await manager.create_session(agent_type="Yeo", platform="desktop")
        session.active_tasks = ["task-1", "task-2"]
        await manager._write(session)
        tasks = await manager.resume_delegated_tasks(session)
        assert tasks == ["task-1", "task-2"]
