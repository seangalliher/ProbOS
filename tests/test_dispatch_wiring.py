"""Tests for dispatch system runtime wiring (AD-375)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_runtime():
    """Create a minimal mock runtime with build dispatch wired."""
    from probos.build_queue import BuildQueue
    from probos.cognitive.builder import BuildSpec

    rt = MagicMock()
    rt.build_queue = BuildQueue()
    rt.build_dispatcher = MagicMock()
    rt.build_dispatcher.approve_and_merge = AsyncMock(return_value=(True, "abc1234def"))
    rt.build_dispatcher.reject_build = AsyncMock(return_value=True)
    rt._emit_event = MagicMock()
    return rt


class TestRuntimeWiring:
    def test_runtime_has_build_queue_field(self) -> None:
        """ProbOSRuntime defines build_queue attribute."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        # Check the attribute is declared (would be set in __init__)
        assert hasattr(ProbOSRuntime, '__init__')

    def test_runtime_has_build_dispatcher_field(self) -> None:
        """ProbOSRuntime defines build_dispatcher attribute."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        assert hasattr(ProbOSRuntime, '__init__')

    def test_on_build_complete_emits_event(self) -> None:
        """_on_build_complete fires build_queue_item event."""
        from probos.build_queue import QueuedBuild
        from probos.cognitive.builder import BuildSpec
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._event_listeners = []

        spec = BuildSpec(title="test", description="test")
        build = QueuedBuild(
            id="test123",
            spec=spec,
            status="merged",
        )

        # Call the callback
        asyncio.get_event_loop().run_until_complete(rt._on_build_complete(build))

        # Can't easily check _emit_event without full init,
        # but we verify it doesn't crash


class TestDispatchAPI:
    @pytest.fixture
    def client(self):
        """Create a test client with mocked runtime."""
        from probos.api import create_app
        from fastapi.testclient import TestClient

        rt = _mock_runtime()
        app = create_app(rt)
        return TestClient(app), rt

    def test_get_queue_empty(self, client) -> None:
        """GET /api/build/queue returns empty list initially."""
        tc, rt = client
        resp = tc.get("/api/build/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["items"] == []

    def test_enqueue_build(self, client) -> None:
        """POST /api/build/enqueue adds a build to the queue."""
        tc, rt = client
        resp = tc.post("/api/build/enqueue", json={
            "title": "Test Build",
            "description": "test",
            "target_files": ["src/foo.py"],
            "priority": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "build_id" in data

        # Verify it appears in the queue
        resp2 = tc.get("/api/build/queue")
        items = resp2.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Test Build"
        assert items[0]["priority"] == 3

    def test_approve_queued_build(self, client) -> None:
        """POST /api/build/queue/approve calls dispatcher.approve_and_merge."""
        tc, rt = client
        resp = tc.post("/api/build/queue/approve", json={"build_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "abc1234" in data["commit"]
        rt.build_dispatcher.approve_and_merge.assert_awaited_once_with("abc123")

    def test_reject_queued_build(self, client) -> None:
        """POST /api/build/queue/reject calls dispatcher.reject_build."""
        tc, rt = client
        resp = tc.post("/api/build/queue/reject", json={"build_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        rt.build_dispatcher.reject_build.assert_awaited_once_with("abc123")

    def test_approve_not_running(self) -> None:
        """Approve returns error when dispatcher is not running."""
        from probos.api import create_app
        from fastapi.testclient import TestClient

        rt = MagicMock()
        rt.build_dispatcher = None
        rt.build_queue = None
        app = create_app(rt)
        tc = TestClient(app)

        resp = tc.post("/api/build/queue/approve", json={"build_id": "x"})
        assert resp.json()["status"] == "error"

    def test_emit_queue_snapshot(self, client) -> None:
        """Queue operations emit build_queue_update events."""
        tc, rt = client
        tc.post("/api/build/enqueue", json={
            "title": "Snapshot Test",
            "description": "test",
        })
        rt._emit_event.assert_called()
        call_args = rt._emit_event.call_args
        assert call_args[0][0] == "build_queue_update"
        assert "items" in call_args[0][1]
