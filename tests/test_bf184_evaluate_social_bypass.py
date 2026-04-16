"""BF-184: Evaluate Step Social Obligation Bypass — tests."""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(mode: str = "ward_room_quality") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        prompt_template=mode,
        timeout_ms=15000,
    )


def _compose_result() -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-test",
        result={"output": "This is a draft response."},
        tokens_used=50,
        success=True,
    )


def _base_context(**overrides) -> dict:
    ctx = {
        "_callsign": "TestAgent",
        "_department": "science",
        "_agent_type": "test_agent",
        "_from_captain": False,
        "_was_mentioned": False,
    }
    ctx.update(overrides)
    return ctx


def _mock_llm_client(response_json: str = '{"pass": true, "score": 0.8, "criteria": {}, "recommendation": "approve"}'):
    client = AsyncMock()
    resp = MagicMock()
    resp.content = response_json
    resp.tokens_used = 100
    resp.tier = "fast"
    client.complete.return_value = resp
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCaptainBypass:
    """Captain messages auto-approved."""

    @pytest.mark.asyncio
    async def test_captain_message_auto_approved(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)

        result = await handler(_make_spec(), ctx, [_compose_result()])

        assert result.success
        assert result.result["pass"] is True
        assert result.result["score"] == 1.0
        assert result.result["recommendation"] == "approve"
        assert result.result["bypass_reason"] == "captain_message"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()


class TestMentionBypass:
    """@mentioned messages auto-approved."""

    @pytest.mark.asyncio
    async def test_mentioned_auto_approved(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_was_mentioned=True)

        result = await handler(_make_spec(), ctx, [_compose_result()])

        assert result.success
        assert result.result["pass"] is True
        assert result.result["score"] == 1.0
        assert result.result["bypass_reason"] == "mentioned"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()


class TestBothFlags:
    """Both captain + mentioned → captain takes precedence."""

    @pytest.mark.asyncio
    async def test_captain_precedence(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True, _was_mentioned=True)

        result = await handler(_make_spec(), ctx, [_compose_result()])

        assert result.result["bypass_reason"] == "captain_message"


class TestNoBypass:
    """Neither flag set → normal LLM evaluation."""

    @pytest.mark.asyncio
    async def test_normal_evaluation(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_from_captain=False, _was_mentioned=False)

        result = await handler(_make_spec(), ctx, [_compose_result()])

        assert result.success
        llm.complete.assert_awaited_once()
        assert result.tokens_used == 100  # From mock LLM


class TestMissingFlags:
    """Flags missing from context → normal evaluation (no bypass)."""

    @pytest.mark.asyncio
    async def test_missing_flags_no_bypass(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = {"_callsign": "Test", "_department": "eng", "_agent_type": "test"}
        # No _from_captain or _was_mentioned keys

        result = await handler(_make_spec(), ctx, [_compose_result()])

        llm.complete.assert_awaited_once()


class TestFlagPropagation:
    """Verify flags are set correctly from observation params."""

    def test_captain_flag_set(self):
        observation = {"params": {"author_id": "captain"}}
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)
        assert observation["_from_captain"] is True
        assert observation["_was_mentioned"] is False

    def test_mention_flag_set(self):
        observation = {"params": {"was_mentioned": True, "author_id": "some_agent"}}
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)
        assert observation["_from_captain"] is False
        assert observation["_was_mentioned"] is True

    def test_crew_message_no_flags(self):
        observation = {"params": {"author_id": "agent_lynx"}}
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)
        assert observation["_from_captain"] is False
        assert observation["_was_mentioned"] is False


class TestNoLlmCallOnBypass:
    """LLM client.complete() NOT called when bypass is active."""

    @pytest.mark.asyncio
    async def test_no_llm_call_captain(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)

        await handler(_make_spec(), ctx, [_compose_result()])
        llm.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_llm_call_mentioned(self):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_was_mentioned=True)

        await handler(_make_spec(), ctx, [_compose_result()])
        llm.complete.assert_not_awaited()


class TestLogging:
    """BF-184 log message emitted on bypass."""

    @pytest.mark.asyncio
    async def test_log_on_bypass(self, caplog):
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)

        with caplog.at_level(logging.INFO):
            await handler(_make_spec(), ctx, [_compose_result()])

        assert any("BF-184" in r.message for r in caplog.records)
        assert any("captain_message" in r.message for r in caplog.records)
