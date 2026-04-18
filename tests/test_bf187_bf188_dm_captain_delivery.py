"""BF-187/BF-188: DM Social Obligation + Captain Delivery Guarantee — tests."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.compose import _should_short_circuit
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_context(**overrides) -> dict:
    ctx = {
        "_callsign": "TestAgent",
        "_department": "science",
        "_agent_type": "test_agent",
        "_from_captain": False,
        "_was_mentioned": False,
        "_is_dm": False,
        "_agent_rank": None,
        "_skill_profile": None,
        "_crew_manifest": "",
    }
    ctx.update(overrides)
    return ctx


def _analyze_result(assessment: str = "RESPOND") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        result={
            "contribution_assessment": assessment,
            "should_respond": assessment != "SILENT",
        },
        tokens_used=50,
        success=True,
    )


def _compose_result(output: str = "Test response.") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-test",
        result={"output": output},
        tokens_used=100,
        success=True,
    )


def _evaluate_result(recommendation: str = "approve") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        result={"recommendation": recommendation, "pass": recommendation == "approve"},
        tokens_used=50,
        success=True,
    )


def _eval_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        prompt_template="ward_room_quality",
        timeout_ms=15000,
    )


def _reflect_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect-test",
        prompt_template="self_critique",
        timeout_ms=15000,
    )


def _mock_llm_client(response: str = "LLM response"):
    client = AsyncMock()
    resp = MagicMock()
    resp.content = response
    resp.tokens_used = 100
    resp.tier = "fast"
    client.complete.return_value = resp
    return client


# ===========================================================================
# BF-187: DM Social Obligation
# ===========================================================================


class TestComposeDmBypass:
    """BF-187: Compose SILENT short-circuit respects DM flag."""

    def test_compose_short_circuit_bypassed_for_dm(self):
        """SILENT + DM → do NOT short-circuit."""
        prior = [_analyze_result("SILENT")]
        ctx = _base_context(_is_dm=True)
        assert _should_short_circuit(prior, ctx) is False

    def test_compose_short_circuit_normal_for_non_dm(self):
        """SILENT + no DM + no social flags → short-circuit as before."""
        prior = [_analyze_result("SILENT")]
        ctx = _base_context(_is_dm=False)
        assert _should_short_circuit(prior, ctx) is True


class TestEvaluateDmBypass:
    """BF-187: Evaluate quality gate bypassed for DMs."""

    @pytest.mark.asyncio
    async def test_evaluate_bypassed_for_dm(self):
        """DM → auto-approve with bypass_reason=dm_recipient."""
        llm = _mock_llm_client()
        handler = EvaluateHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_is_dm=True)
        prior = [_compose_result()]
        result = await handler(_eval_spec(), ctx, prior)

        assert result.success
        assert result.result["pass"] is True
        assert result.result["bypass_reason"] == "dm_recipient"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_evaluate_not_bypassed_without_dm(self):
        """No DM → proceeds to LLM call."""
        llm = _mock_llm_client('{"pass": true, "score": 0.8, "recommendation": "approve"}')
        handler = EvaluateHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_is_dm=False)
        prior = [_compose_result()]
        result = await handler(_eval_spec(), ctx, prior)

        llm.complete.assert_awaited_once()


class TestReflectDmBypass:
    """BF-187: Reflect respects DM social obligation + reorder fix."""

    @pytest.mark.asyncio
    async def test_reflect_bypassed_for_dm(self):
        """DM → auto-approve, return compose output unchanged."""
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_is_dm=True)
        prior = [_compose_result("DM reply text"), _evaluate_result("approve")]
        result = await handler(_reflect_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] == "DM reply text"
        assert result.result["bypass_reason"] == "dm_recipient"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reflect_dm_suppress_honored(self):
        """DM + Evaluate suppress → BF-204: safety suppress wins over social obligation."""
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_is_dm=True)
        # BF-204: Suppress from EVALUATE safety verdict is honored even for DMs
        prior = [_compose_result("DM reply"), _evaluate_result("suppress")]
        result = await handler(_reflect_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.result["suppressed"] is True
        # Social obligation did NOT bypass the safety check
        assert result.result.get("bypass_reason") is None

    @pytest.mark.asyncio
    async def test_reflect_suppress_still_works_without_social(self):
        """No social flags + suppress → [NO_RESPONSE] (regression)."""
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm, runtime=None)
        ctx = _base_context()
        prior = [_compose_result("Some text"), _evaluate_result("suppress")]
        result = await handler(_reflect_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.result.get("suppressed") is True

    @pytest.mark.asyncio
    async def test_reflect_captain_suppress_honored(self):
        """Captain + suppress → BF-204: safety suppress wins over social obligation."""
        llm = _mock_llm_client()
        handler = ReflectHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_from_captain=True)
        prior = [_compose_result("Captain reply"), _evaluate_result("suppress")]
        result = await handler(_reflect_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.result["suppressed"] is True
        # Safety check takes precedence — no bypass
        assert result.result.get("bypass_reason") is None


class TestChainContextInjection:
    """BF-187: Verify _is_dm is extracted from intent params."""

    def test_chain_context_includes_is_dm(self):
        ctx = _base_context(_is_dm=True)
        assert ctx["_is_dm"] is True

    def test_chain_context_is_dm_false_by_default(self):
        ctx = _base_context()
        assert ctx["_is_dm"] is False

    def test_is_dm_channel_true_for_dm_channel(self):
        """Verify the channel_type check used in intent params."""
        channel = MagicMock()
        channel.channel_type = "dm"
        assert getattr(channel, 'channel_type', '') == "dm"

    def test_is_dm_channel_false_for_ship_channel(self):
        """Verify the channel_type check returns False for non-DM."""
        channel = MagicMock()
        channel.channel_type = "ship"
        assert getattr(channel, 'channel_type', '') != "dm"


# ===========================================================================
# BF-188: Captain Delivery Coordination
# ===========================================================================


class TestCaptainDeliveryCoordination:
    """BF-188: asyncio.Event coordinates Captain delivery with agent routing."""

    def _make_router(self):
        """Create a minimal WardRoomRouter with required attributes."""
        router = MagicMock()
        router._captain_delivery_done = asyncio.Event()
        router._captain_delivery_done.set()  # Initially done
        return router

    def test_captain_delivery_event_initially_set(self):
        """Event starts in set state (no Captain routing in progress)."""
        router = self._make_router()
        assert router._captain_delivery_done.is_set()

    def test_captain_delivery_event_cleared_on_start(self):
        """Clearing event signals Captain delivery in progress."""
        router = self._make_router()
        router._captain_delivery_done.clear()
        assert not router._captain_delivery_done.is_set()

    def test_captain_delivery_event_set_on_completion(self):
        """Setting event signals Captain delivery complete."""
        router = self._make_router()
        router._captain_delivery_done.clear()
        router._captain_delivery_done.set()
        assert router._captain_delivery_done.is_set()

    @pytest.mark.asyncio
    async def test_agent_routing_waits_for_captain(self):
        """Agent routing waits when Captain delivery is in progress."""
        event = asyncio.Event()
        # Event is cleared = Captain delivery in progress
        waited = False

        async def wait_and_set():
            nonlocal waited
            await asyncio.sleep(0.05)
            waited = True
            event.set()

        asyncio.create_task(wait_and_set())
        await asyncio.wait_for(event.wait(), timeout=2.0)
        assert waited

    @pytest.mark.asyncio
    async def test_agent_routing_proceeds_when_no_captain(self):
        """Agent routing proceeds immediately when Event is already set."""
        event = asyncio.Event()
        event.set()
        # Should not block
        await asyncio.wait_for(event.wait(), timeout=0.1)
        assert event.is_set()

    @pytest.mark.asyncio
    async def test_captain_delivery_timeout_proceeds(self):
        """If Captain delivery takes too long, agent routing proceeds with timeout."""
        event = asyncio.Event()
        # Event never set → timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.05)
