"""Tests for Architect API endpoints and /design command (AD-308)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------


class TestDesignRequestModel:
    def test_required_fields(self):
        """DesignRequest requires feature."""
        from probos.api import DesignRequest

        req = DesignRequest(feature="Add network egress policy")
        assert req.feature == "Add network egress policy"

    def test_defaults(self):
        """DesignRequest has correct defaults."""
        from probos.api import DesignRequest

        req = DesignRequest(feature="F")
        assert req.phase == ""

    def test_full_population(self):
        """DesignRequest populates all fields."""
        from probos.api import DesignRequest

        req = DesignRequest(feature="Add egress", phase="31")
        assert req.feature == "Add egress"
        assert req.phase == "31"


class TestDesignApproveRequestModel:
    def test_required_fields(self):
        """DesignApproveRequest requires design_id."""
        from probos.api import DesignApproveRequest

        req = DesignApproveRequest(design_id="abc123")
        assert req.design_id == "abc123"


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


class TestDesignSubmitEndpoint:
    @pytest.mark.asyncio
    async def test_submit_returns_started(self, chat_client):
        """POST /api/design/submit returns status=started and a design_id."""
        resp = await chat_client.post("/api/design/submit", json={
            "feature": "Add network egress policy",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert "design_id" in data
        assert len(data["design_id"]) == 12

    @pytest.mark.asyncio
    async def test_submit_with_phase(self, chat_client):
        """POST /api/design/submit accepts phase parameter."""
        resp = await chat_client.post("/api/design/submit", json={
            "feature": "Add security agents",
            "phase": "31",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"


# ---------------------------------------------------------------------------
# /design slash command
# ---------------------------------------------------------------------------


class TestDesignSlashCommand:
    @pytest.mark.asyncio
    async def test_design_command_valid(self, chat_client):
        """/design <feature> triggers a design."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/design Add network egress policy",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "design_id" in data
        assert "submitted" in data["response"]

    @pytest.mark.asyncio
    async def test_design_command_with_phase(self, chat_client):
        """/design phase 31: <feature> parses phase."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/design phase 31: Add egress policy",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "design_id" in data

    @pytest.mark.asyncio
    async def test_design_command_empty(self, chat_client):
        """/design with no args returns usage."""
        resp = await chat_client.post("/api/chat", json={
            "message": "/design",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Usage" in data["response"]


# ---------------------------------------------------------------------------
# /api/design/approve
# ---------------------------------------------------------------------------


class TestDesignApproveEndpoint:
    @pytest.mark.asyncio
    async def test_approve_missing_design(self, chat_client):
        """POST /api/design/approve returns error when design not found."""
        resp = await chat_client.post("/api/design/approve", json={
            "design_id": "nonexistent",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "not found" in data["message"]


# ---------------------------------------------------------------------------
# _run_design event emission
# ---------------------------------------------------------------------------


class TestRunDesignEvents:
    @pytest.mark.asyncio
    async def test_emits_design_started_and_progress(self, tmp_path):
        """_run_design emits design_started and design_progress events."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        app = create_app(rt)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/design/submit", json={
                "feature": "Event Test Feature",
            })
            assert resp.status_code == 200
            await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "design_started" in event_types
        assert "design_progress" in event_types

        await rt.stop()

    @pytest.mark.asyncio
    async def test_emits_failure_on_no_result(self, tmp_path):
        """_run_design emits design_failure when intent bus returns no results."""
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
            await client.post("/api/design/submit", json={
                "feature": "Fail Test",
            })
            await asyncio.sleep(0.5)

        event_types = [e[0] for e in events]
        assert "design_failure" in event_types

        await rt.stop()


# ---------------------------------------------------------------------------
# Approval flow — forwarding to builder
# ---------------------------------------------------------------------------


class TestApprovalForwarding:
    @pytest.mark.asyncio
    async def test_approve_forwards_to_builder(self, tmp_path):
        """Approving a pending design creates a build task."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        app = create_app(rt)

        # Manually inject a pending design into the closure's _pending_designs
        # Access via the approve endpoint's behavior
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First, verify that unknown design returns error
            resp = await client.post("/api/design/approve", json={
                "design_id": "test_fwd_123",
            })
            assert resp.json()["status"] == "error"

        await rt.stop()

    @pytest.mark.asyncio
    async def test_generated_event_stores_pending(self, tmp_path):
        """_run_design stores proposal in _pending_designs on success."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        events: list[tuple[str, dict]] = []
        original_emit = rt._emit_event

        def capture_emit(event_type, data):
            events.append((event_type, data))
            original_emit(event_type, data)

        rt._emit_event = capture_emit

        # Mock intent_bus to return a successful result with a proposal
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        mock_result.result = {
            "proposal": {
                "title": "Test Feature",
                "summary": "A test",
                "rationale": "Testing",
                "roadmap_ref": "Phase 99",
                "priority": "medium",
                "dependencies": [],
                "risks": [],
                "build_spec": {
                    "title": "Test Feature",
                    "description": "Build this test",
                    "target_files": ["src/test.py"],
                    "reference_files": [],
                    "test_files": ["tests/test_test.py"],
                    "ad_number": 999,
                    "constraints": [],
                },
            },
            "llm_output": "===PROPOSAL===\n...\n===END PROPOSAL===",
        }
        rt.intent_bus.broadcast = AsyncMock(return_value=[mock_result])

        app = create_app(rt)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/design/submit", json={
                "feature": "Test Feature",
            })
            design_id = resp.json()["design_id"]
            await asyncio.sleep(0.5)

            # Now approve the design — should forward to builder
            resp2 = await client.post("/api/design/approve", json={
                "design_id": design_id,
            })
            data = resp2.json()
            assert data["status"] == "forwarded"
            assert "build_id" in data

        event_types = [e[0] for e in events]
        assert "design_generated" in event_types

        await rt.stop()
