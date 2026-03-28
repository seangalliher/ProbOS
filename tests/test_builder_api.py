"""Tests for Builder API endpoints and /build command (AD-304)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------


class TestBuildRequestModel:
    def test_required_fields(self):
        """BuildRequest requires title and description."""
        from probos.api import BuildRequest

        req = BuildRequest(title="Test", description="A test build")
        assert req.title == "Test"
        assert req.description == "A test build"

    def test_defaults(self):
        """BuildRequest has correct defaults for optional fields."""
        from probos.api import BuildRequest

        req = BuildRequest(title="T", description="D")
        assert req.target_files == []
        assert req.reference_files == []
        assert req.test_files == []
        assert req.ad_number == 0
        assert req.constraints == []

    def test_full_population(self):
        """BuildRequest populates all fields."""
        from probos.api import BuildRequest

        req = BuildRequest(
            title="Add Vec",
            description="Vector store",
            target_files=["src/vec.py"],
            reference_files=["src/ref.py"],
            test_files=["tests/test_vec.py"],
            ad_number=400,
            constraints=["No new deps"],
        )
        assert req.ad_number == 400
        assert req.target_files == ["src/vec.py"]
        assert req.constraints == ["No new deps"]


class TestBuildApproveRequestModel:
    def test_required_fields(self):
        """BuildApproveRequest requires build_id."""
        from probos.api import BuildApproveRequest

        req = BuildApproveRequest(build_id="abc123")
        assert req.build_id == "abc123"

    def test_defaults(self):
        """BuildApproveRequest has correct defaults."""
        from probos.api import BuildApproveRequest

        req = BuildApproveRequest(build_id="abc")
        assert req.file_changes == []
        assert req.title == ""
        assert req.description == ""
        assert req.ad_number == 0
        assert req.branch_name == ""


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def chat_client(tmp_path):
    """Create a test client with a running ProbOS runtime."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    app = create_app(rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await rt.stop()


class TestBuildSubmitEndpoint:
    @pytest.mark.asyncio
    async def test_submit_returns_started(self, chat_client):
        """POST /api/build/submit returns status=started and a build_id."""
        resp = await chat_client.post("/api/build/submit", json={
            "title": "Test Build",
            "description": "A test build",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert "build_id" in data
        assert len(data["build_id"]) == 12

    @pytest.mark.asyncio
    async def test_submit_with_full_params(self, chat_client):
        """POST /api/build/submit accepts all optional params."""
        resp = await chat_client.post("/api/build/submit", json={
            "title": "Full Build",
            "description": "With all params",
            "target_files": ["src/foo.py"],
            "reference_files": ["src/ref.py"],
            "test_files": ["tests/test_foo.py"],
            "ad_number": 999,
            "constraints": ["No new deps"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"


class TestBuildApproveEndpoint:
    @pytest.mark.asyncio
    async def test_approve_returns_started(self, chat_client):
        """POST /api/build/approve returns status=started."""
        # Mock execute_approved_build to prevent background task from running
        # real git subprocesses (which hang in CI).
        mock_result = MagicMock(success=True, error=None, test_output="ok")
        with patch(
            "probos.cognitive.builder.execute_approved_build",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await chat_client.post("/api/build/approve", json={
                "build_id": "test123",
                "file_changes": [
                    {"path": "src/foo.py", "content": "print('hi')\n", "mode": "create"},
                ],
                "title": "Test Build",
                "description": "A test",
                "ad_number": 999,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["build_id"] == "test123"


# ---------------------------------------------------------------------------
# /build slash command
# ---------------------------------------------------------------------------


class TestBuildSlashCommand:
    @pytest.mark.asyncio
    async def test_build_command_valid(self, chat_client):
        """/build <title>: <description> triggers a build."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/build My Feature: do the thing",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "build_id" in data
        assert "My Feature" in data["response"]

    @pytest.mark.asyncio
    async def test_build_command_no_title(self, chat_client):
        """/build with no title returns usage."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/build",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Usage" in data["response"]

    @pytest.mark.asyncio
    async def test_build_command_title_only(self, chat_client):
        """/build with title but no colon still works."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/build Simple Task",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "build_id" in data
        assert "Simple Task" in data["response"]


# ---------------------------------------------------------------------------
# _run_build event emission
# ---------------------------------------------------------------------------


class TestRunBuildEvents:
    @pytest.mark.asyncio
    async def test_emits_build_started_and_progress(self, tmp_path):
        """_run_build emits build_started and build_progress events."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        app = create_app(rt)

        # Access _run_build from the app closure
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/build/submit", json={
                "title": "Event Test",
                "description": "Test event emission",
            })
            assert resp.status_code == 200

            # Give the background task time to emit events
            await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "build_started" in event_types
        assert "build_progress" in event_types

        await rt.stop()

    @pytest.mark.asyncio
    async def test_emits_failure_on_no_result(self, tmp_path):
        """_run_build emits build_failure when intent bus returns no results."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        # Mock intent_bus to return empty results
        rt.intent_bus.broadcast = AsyncMock(return_value=[])

        app = create_app(rt)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/build/submit", json={
                "title": "Fail Test",
                "description": "Should fail",
            })
            await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "build_failure" in event_types

        await rt.stop()


# ---------------------------------------------------------------------------
# _execute_build event emission
# ---------------------------------------------------------------------------


class TestExecuteBuildEvents:
    @pytest.mark.asyncio
    async def test_emits_build_success(self, tmp_path):
        """_execute_build emits build_success on successful execution."""
        from probos.cognitive.builder import BuildResult, BuildSpec

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        mock_result = BuildResult(
            success=True,
            spec=BuildSpec(title="T", description="D"),
            branch_name="builder/test",
            commit_hash="abc123",
            files_written=["src/foo.py"],
            tests_passed=True,
        )

        app = create_app(rt)
        transport = ASGITransport(app=app)

        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=mock_result):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/build/approve", json={
                    "build_id": "test123",
                    "file_changes": [
                        {"path": "src/foo.py", "content": "pass\n", "mode": "create"},
                    ],
                    "title": "T",
                    "description": "D",
                })
                await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "build_success" in event_types

        await rt.stop()

    @pytest.mark.asyncio
    async def test_emits_build_failure(self, tmp_path):
        """_execute_build emits build_failure on failed execution."""
        from probos.cognitive.builder import BuildResult, BuildSpec

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        mock_result = BuildResult(
            success=False,
            spec=BuildSpec(title="T", description="D"),
            error="Test failure",
        )

        app = create_app(rt)
        transport = ASGITransport(app=app)

        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=mock_result):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/build/approve", json={
                    "build_id": "test456",
                    "file_changes": [],
                    "title": "T",
                    "description": "D",
                })
                await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "build_failure" in event_types

        await rt.stop()


class TestTaskTracking:
    """Tests for background task lifecycle (AD-326)."""

    @pytest.mark.asyncio
    async def test_build_submit_tracks_task(self, tmp_path):
        """submit_build creates a tracked background task visible in /api/tasks."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        app = create_app(rt)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/build/submit", json={
                "title": "Track test",
                "description": "Testing task tracking",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "started"

            # /api/tasks endpoint should be functional
            tasks_resp = await ac.get("/api/tasks")
            assert tasks_resp.status_code == 200
            tasks_data = tasks_resp.json()
            assert "active_count" in tasks_data
            assert "total_tracked" in tasks_data

    @pytest.mark.asyncio
    async def test_tasks_endpoint_returns_status(self, tmp_path):
        """GET /api/tasks returns active task information."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        app = create_app(rt)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/tasks")
            assert resp.status_code == 200
            data = resp.json()
            assert "active_count" in data
            assert "total_tracked" in data
            assert "pending_designs" in data
            assert "tasks" in data
            assert isinstance(data["tasks"], list)

    @pytest.mark.asyncio
    async def test_task_done_callback_removes_from_set(self, tmp_path):
        """Completed tasks are cleaned up — /api/tasks shows 0 after completion."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        app = create_app(rt)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Initially no tasks
            resp = await ac.get("/api/tasks")
            assert resp.json()["total_tracked"] == 0

            # Submit a build (completes quickly with MockLLM)
            await ac.post("/api/build/submit", json={
                "title": "Quick build",
                "description": "Finishes fast",
            })

            # Let the task complete
            await asyncio.sleep(0.5)

            # Done callback should have removed it
            resp2 = await ac.get("/api/tasks")
            assert resp2.json()["total_tracked"] == 0
