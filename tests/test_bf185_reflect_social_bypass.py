"""BF-185: Reflect Step Social Obligation Bypass — tests."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.reflect import ReflectHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(mode: str = "ward_room_quality") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect-test",
        prompt_template=mode,
        timeout_ms=15000,
    )


def _compose_result(output: str = "This is a draft response.") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-test",
        result={"output": output},
        tokens_used=50,
        success=True,
    )


def _evaluate_result(recommendation: str = "approve") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        result={"pass": True, "score": 1.0, "recommendation": recommendation},
        tokens_used=0,
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


def _mock_llm_client(response: str = "Revised output."):
    client = AsyncMock()
    resp = MagicMock()
    resp.content = response
    resp.tokens_used = 200
    resp.tier = "standard"
    client.complete.return_value = resp
    return client


def _prior_results(recommendation: str = "approve"):
    return [_compose_result(), _evaluate_result(recommendation)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCaptainBypass:
    """Captain messages auto-approved in reflect."""

    @pytest.mark.asyncio
    async def test_captain_message_auto_approved(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)

        result = await handler(_make_spec(), ctx, _prior_results())

        assert result.success
        assert result.result["output"] == "This is a draft response."
        assert result.result["revised"] is False
        assert result.result["suppressed"] is False
        assert result.result["bypass_reason"] == "captain_message"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()


class TestMentionBypass:
    """@mentioned messages auto-approved."""

    @pytest.mark.asyncio
    async def test_mentioned_auto_approved(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_was_mentioned=True)

        result = await handler(_make_spec(), ctx, _prior_results())

        assert result.success
        assert result.result["bypass_reason"] == "mentioned"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()


class TestBothFlags:
    """Both captain + mentioned → captain takes precedence."""

    @pytest.mark.asyncio
    async def test_captain_precedence(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True, _was_mentioned=True)

        result = await handler(_make_spec(), ctx, _prior_results())

        assert result.result["bypass_reason"] == "captain_message"


class TestNoBypass:
    """Neither flag set → normal LLM self-critique."""

    @pytest.mark.asyncio
    async def test_normal_reflection(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_from_captain=False, _was_mentioned=False)

        result = await handler(_make_spec(), ctx, _prior_results())

        assert result.success
        llm.complete.assert_awaited_once()
        assert result.tokens_used == 200


class TestMissingFlags:
    """Flags missing from context → normal path."""

    @pytest.mark.asyncio
    async def test_missing_flags_no_bypass(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = {"_callsign": "Test", "_department": "eng", "_agent_type": "test"}

        result = await handler(_make_spec(), ctx, _prior_results())

        llm.complete.assert_awaited_once()


class TestNoLlmCallOnBypass:
    """LLM not called when bypass active."""

    @pytest.mark.asyncio
    async def test_no_llm_call(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)

        await handler(_make_spec(), ctx, _prior_results())
        llm.complete.assert_not_awaited()


class TestComposeOutputPreserved:
    """Exact compose output returned unchanged on bypass."""

    @pytest.mark.asyncio
    async def test_output_preserved(self):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_from_captain=True)
        custom_output = "Specific draft with [REPLY] action and metrics: CPU 42%."

        prior = [_compose_result(custom_output), _evaluate_result()]
        result = await handler(_make_spec(), ctx, prior)

        assert result.result["output"] == custom_output
        assert result.result["revised"] is False


class TestLogging:
    """BF-185 log message emitted on bypass."""

    @pytest.mark.asyncio
    async def test_log_on_bypass(self, caplog):
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_was_mentioned=True)

        with caplog.at_level(logging.INFO):
            await handler(_make_spec(), ctx, _prior_results())

        assert any("BF-185" in r.message for r in caplog.records)
        assert any("mentioned" in r.message for r in caplog.records)
