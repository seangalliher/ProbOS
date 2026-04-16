"""BF-190/BF-191: Route `now` NameError + Evaluate Raw JSON Pass-Through — tests."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType


# ===========================================================================
# BF-190: _route_to_agents() has `now` defined
# ===========================================================================


class TestBF190RouteToAgentsNow:
    """BF-190: `now` must be defined inside _route_to_agents()."""

    def test_route_to_agents_now_defined(self):
        """_route_to_agents uses time.time(), no NameError."""
        from probos.ward_room_router import WardRoomRouter

        source = __import__("inspect").getsource(WardRoomRouter._route_to_agents)
        # Must contain 'now = time.time()' (using module-level import)
        assert "now = time.time()" in source

    def test_route_event_no_dead_now(self):
        """route_event() no longer has dead `now = time.time()` assignment."""
        from probos.ward_room_router import WardRoomRouter

        source = __import__("inspect").getsource(WardRoomRouter.route_event)
        # Should NOT have `now = time.time()` — it was dead code
        assert "now = time.time()" not in source

    def test_route_to_agents_no_local_time_import(self):
        """_route_to_agents uses module-level time, not `import time as _time`."""
        from probos.ward_room_router import WardRoomRouter

        source = __import__("inspect").getsource(WardRoomRouter._route_to_agents)
        assert "import time as _time" not in source


# ===========================================================================
# BF-191: Evaluate deterministic JSON rejection
# ===========================================================================


def _make_compose_result(output: str) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-test",
        result={"output": output},
        tokens_used=50,
        success=True,
    )


def _make_analyze_result() -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        result={"contribution_assessment": "RESPOND"},
        tokens_used=30,
        success=True,
    )


def _base_context(**overrides) -> dict:
    ctx = {
        "_callsign": "TestAgent",
        "_department": "science",
        "_agent_type": "test_agent",
        "_from_captain": False,
        "_was_mentioned": False,
        "_is_dm": False,
        "context": "Some content",
    }
    ctx.update(overrides)
    return ctx


def _make_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        tier="tier1",
    )


class TestBF191EvaluateJsonRejection:
    """BF-191: Evaluate must reject raw intent JSON deterministically."""

    @pytest.fixture
    def handler(self):
        from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
        return EvaluateHandler(llm_client=AsyncMock())

    @pytest.mark.asyncio
    async def test_evaluate_rejects_raw_intent_json(self, handler):
        """Compose output = raw intent JSON → pass=False, suppress."""
        compose = _make_compose_result('{"intents": []}')
        ctx = _base_context()
        spec = _make_spec()
        result = await handler(spec, ctx, [_make_analyze_result(), compose])
        assert result.success is True
        assert result.result["pass"] is False
        assert result.result["score"] == 0.0
        assert result.result["recommendation"] == "suppress"
        assert result.result["rejection_reason"] == "raw_json_output"

    @pytest.mark.asyncio
    async def test_evaluate_rejects_intent_json_with_content(self, handler):
        """Compose output with full intent structure → rejected."""
        json_output = '{"intents": [{"intent": "ward_room_notification", "body": "test"}]}'
        compose = _make_compose_result(json_output)
        ctx = _base_context()
        spec = _make_spec()
        result = await handler(spec, ctx, [_make_analyze_result(), compose])
        assert result.result["pass"] is False
        assert result.result["rejection_reason"] == "raw_json_output"

    @pytest.mark.asyncio
    async def test_evaluate_passes_normal_text(self, handler):
        """Normal natural language → NOT rejected by format check (reaches LLM)."""
        compose = _make_compose_result("I've observed unusual latency in the EPS conduits.")
        ctx = _base_context()
        spec = _make_spec()
        # Mock LLM to return a valid evaluate response
        handler._llm_client.complete = AsyncMock(return_value=MagicMock(
            content='{"pass": true, "score": 0.85, "criteria": {}, "recommendation": "approve"}'
        ))
        result = await handler(spec, ctx, [_make_analyze_result(), compose])
        # Should have called LLM (not short-circuited by JSON check)
        handler._llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_passes_json_in_prose(self, handler):
        """JSON embedded in prose → NOT rejected (doesn't start with '{')."""
        compose = _make_compose_result('The analysis shows {"status": "ok"} in the logs.')
        ctx = _base_context()
        spec = _make_spec()
        handler._llm_client.complete = AsyncMock(return_value=MagicMock(
            content='{"pass": true, "score": 0.80, "criteria": {}, "recommendation": "approve"}'
        ))
        result = await handler(spec, ctx, [_make_analyze_result(), compose])
        handler._llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_json_rejection_zero_tokens(self, handler):
        """JSON rejection uses 0 tokens — no LLM call."""
        compose = _make_compose_result('{"intents": [{"intent": "test"}]}')
        ctx = _base_context()
        spec = _make_spec()
        result = await handler(spec, ctx, [_make_analyze_result(), compose])
        assert result.tokens_used == 0
        handler._llm_client.complete.assert_not_called()
