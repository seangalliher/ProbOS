"""AD-632a: Sub-Task Foundation — Protocol, Executor, Journal, Config.

Tests for SubTaskType, SubTaskSpec, SubTaskResult, SubTaskChain,
SubTaskHandler protocol, SubTaskExecutor, journal recording,
event emission, CognitiveAgent integration, and SubTaskConfig.

41 tests across 9 classes.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskChainError,
    SubTaskError,
    SubTaskExecutor,
    SubTaskHandler,
    SubTaskResult,
    SubTaskSpec,
    SubTaskStepError,
    SubTaskType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_handler(
    result_dict: dict | None = None,
    tokens: int = 10,
    success: bool = True,
    error: str = "",
    delay: float = 0.0,
    tier_used: str = "standard",
):
    """Create a mock handler that returns a SubTaskResult."""
    async def handler(
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        if delay:
            await asyncio.sleep(delay)
        return SubTaskResult(
            sub_task_type=spec.sub_task_type,
            name=spec.name,
            result=result_dict or {"output": f"result-{spec.name}"},
            tokens_used=tokens,
            duration_ms=delay * 1000,
            success=success,
            error=error,
            tier_used=tier_used,
        )
    return handler


def _sync_make_handler(**kwargs):
    """Synchronous wrapper to create handler without await."""
    async def handler(
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        delay = kwargs.get("delay", 0.0)
        if delay:
            await asyncio.sleep(delay)
        return SubTaskResult(
            sub_task_type=spec.sub_task_type,
            name=spec.name,
            result=kwargs.get("result_dict") or {"output": f"result-{spec.name}"},
            tokens_used=kwargs.get("tokens", 10),
            duration_ms=delay * 1000,
            success=kwargs.get("success", True),
            error=kwargs.get("error", ""),
            tier_used=kwargs.get("tier_used", "standard"),
        )
    return handler


# ---------------------------------------------------------------------------
# 1. TestSubTaskType
# ---------------------------------------------------------------------------


class TestSubTaskType:
    """SubTaskType enum has 5 members with correct string values."""

    def test_enum_values(self):
        assert SubTaskType.QUERY.value == "query"
        assert SubTaskType.ANALYZE.value == "analyze"
        assert SubTaskType.COMPOSE.value == "compose"
        assert SubTaskType.EVALUATE.value == "evaluate"
        assert SubTaskType.REFLECT.value == "reflect"

    def test_enum_is_str(self):
        for member in SubTaskType:
            assert isinstance(member.value, str)
            # JSON-serializable
            import json
            json.dumps(member.value)

    def test_enum_members(self):
        names = {m.name for m in SubTaskType}
        assert names == {"QUERY", "ANALYZE", "COMPOSE", "EVALUATE", "REFLECT"}


# ---------------------------------------------------------------------------
# 2. TestSubTaskSpec
# ---------------------------------------------------------------------------


class TestSubTaskSpec:
    """SubTaskSpec is a frozen dataclass with correct defaults."""

    def test_construction(self):
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-thread",
            prompt_template="Analyze: {context}",
        )
        assert spec.sub_task_type == SubTaskType.ANALYZE
        assert spec.name == "analyze-thread"
        assert spec.prompt_template == "Analyze: {context}"

    def test_frozen(self):
        spec = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q")
        with pytest.raises(FrozenInstanceError):
            spec.name = "changed"  # type: ignore[misc]

    def test_defaults(self):
        spec = SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c")
        assert spec.timeout_ms == 60000
        assert spec.tier == "standard"
        assert spec.required is True
        assert spec.prompt_template == ""
        assert spec.context_keys == ()

    def test_context_keys_tuple(self):
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="a",
            context_keys=("intent", "threads"),
        )
        assert isinstance(spec.context_keys, tuple)
        # Hashable — can be used in sets/dicts
        hash(spec.context_keys)


# ---------------------------------------------------------------------------
# 3. TestSubTaskResult
# ---------------------------------------------------------------------------


class TestSubTaskResult:
    """SubTaskResult is a frozen dataclass with correct defaults."""

    def test_construction(self):
        result = SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name="compose-reply",
            result={"output": "Hello"},
            tokens_used=42,
            duration_ms=150.0,
            tier_used="deep",
        )
        assert result.tokens_used == 42
        assert result.result["output"] == "Hello"

    def test_frozen(self):
        result = SubTaskResult(sub_task_type=SubTaskType.QUERY, name="q")
        with pytest.raises(FrozenInstanceError):
            result.name = "changed"  # type: ignore[misc]

    def test_success_default(self):
        result = SubTaskResult(sub_task_type=SubTaskType.EVALUATE, name="e")
        assert result.success is True
        assert result.error == ""

    def test_error_field(self):
        result = SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="a",
            success=False,
            error="LLM timeout",
        )
        assert not result.success
        assert result.error == "LLM timeout"


# ---------------------------------------------------------------------------
# 4. TestSubTaskChain
# ---------------------------------------------------------------------------


class TestSubTaskChain:
    """SubTaskChain has step list, timeouts, and fallback."""

    def test_construction(self):
        steps = [
            SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q1"),
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a1"),
        ]
        chain = SubTaskChain(steps=steps, source="test")
        assert len(chain.steps) == 2
        assert chain.source == "test"

    def test_defaults(self):
        chain = SubTaskChain()
        assert chain.chain_timeout_ms == 240000
        assert chain.fallback == "single_call"
        assert chain.source == ""
        assert chain.steps == []

    def test_empty_chain(self):
        chain = SubTaskChain(steps=[])
        assert len(chain.steps) == 0


# ---------------------------------------------------------------------------
# 5. TestSubTaskExecutor
# ---------------------------------------------------------------------------


class TestSubTaskExecutor:
    """SubTaskExecutor registers handlers, validates, and executes chains."""

    def test_register_handler(self):
        executor = SubTaskExecutor()
        handler = _sync_make_handler()
        executor.register_handler(SubTaskType.ANALYZE, handler)
        assert executor.has_handler(SubTaskType.ANALYZE)

    def test_register_duplicate_raises(self):
        executor = SubTaskExecutor()
        handler = _sync_make_handler()
        executor.register_handler(SubTaskType.QUERY, handler)
        with pytest.raises(ValueError, match="already registered"):
            executor.register_handler(SubTaskType.QUERY, handler)

    def test_has_handler(self):
        executor = SubTaskExecutor()
        assert not executor.has_handler(SubTaskType.REFLECT)
        executor.register_handler(SubTaskType.REFLECT, _sync_make_handler())
        assert executor.has_handler(SubTaskType.REFLECT)

    def test_can_execute_all_required_registered(self):
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        executor.register_handler(SubTaskType.COMPOSE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
        ])
        assert executor.can_execute(chain)

    def test_can_execute_missing_required(self):
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c", required=True),
        ])
        assert not executor.can_execute(chain)

    def test_can_execute_optional_missing(self):
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
            SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="r", required=False),
        ])
        assert executor.can_execute(chain)

    @pytest.mark.asyncio
    async def test_execute_single_step(self):
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler(tokens=20))
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a1"),
        ])
        results = await executor.execute(
            chain, {"intent": "test"}, agent_id="agent-1",
        )
        assert len(results) == 1
        assert results[0].name == "a1"
        assert results[0].tokens_used == 20
        assert results[0].success

    @pytest.mark.asyncio
    async def test_execute_multi_step(self):
        call_log = []

        async def handler_with_log(spec, context, prior_results):
            call_log.append((spec.name, len(prior_results)))
            return SubTaskResult(
                sub_task_type=spec.sub_task_type,
                name=spec.name,
                result={"output": f"out-{spec.name}"},
                tokens_used=5,
            )

        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, handler_with_log)
        executor.register_handler(SubTaskType.COMPOSE, handler_with_log)
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="step1"),
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="step2"),
        ])
        results = await executor.execute(
            chain, {}, agent_id="agent-1",
        )
        assert len(results) == 2
        # Second handler received prior_results from first
        assert call_log[0] == ("step1", 0)
        assert call_log[1] == ("step2", 1)

    @pytest.mark.asyncio
    async def test_execute_step_timeout(self):
        async def slow_handler(spec, context, prior_results):
            await asyncio.sleep(5)  # Much longer than timeout
            return SubTaskResult(sub_task_type=spec.sub_task_type, name=spec.name)

        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, slow_handler)
        chain = SubTaskChain(steps=[
            SubTaskSpec(
                sub_task_type=SubTaskType.ANALYZE, name="slow",
                timeout_ms=50,  # 50ms timeout
            ),
        ])
        with pytest.raises(SubTaskStepError, match="timed out"):
            await executor.execute(chain, {}, agent_id="agent-1")

    @pytest.mark.asyncio
    async def test_execute_chain_timeout(self):
        async def medium_handler(spec, context, prior_results):
            await asyncio.sleep(0.2)  # 200ms each
            return SubTaskResult(sub_task_type=spec.sub_task_type, name=spec.name)

        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, medium_handler)
        chain = SubTaskChain(
            steps=[
                SubTaskSpec(
                    sub_task_type=SubTaskType.ANALYZE, name=f"s{i}",
                    timeout_ms=5000,  # Individual step timeout is generous
                )
                for i in range(5)  # 5 steps × 200ms = 1000ms > chain timeout
            ],
            chain_timeout_ms=100,  # But chain timeout is tight (100ms)
        )
        with pytest.raises(SubTaskChainError, match="timed out"):
            await executor.execute(chain, {}, agent_id="agent-1")

    @pytest.mark.asyncio
    async def test_execute_required_step_failure(self):
        executor = SubTaskExecutor()
        executor.register_handler(
            SubTaskType.ANALYZE,
            _sync_make_handler(success=False, error="bad input"),
        )
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="fail", required=True),
        ])
        with pytest.raises(SubTaskStepError, match="bad input"):
            await executor.execute(chain, {}, agent_id="agent-1")

    @pytest.mark.asyncio
    async def test_execute_optional_step_failure(self):
        executor = SubTaskExecutor()
        executor.register_handler(
            SubTaskType.ANALYZE,
            _sync_make_handler(success=True, tokens=10),
        )

        async def failing_handler(spec, context, prior_results):
            raise ValueError("optional boom")

        executor.register_handler(SubTaskType.REFLECT, failing_handler)
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="ok", required=True),
            SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="opt", required=False),
        ])
        results = await executor.execute(chain, {}, agent_id="agent-1")
        assert len(results) == 2
        assert results[0].success
        assert not results[1].success


# ---------------------------------------------------------------------------
# 6. TestSubTaskJournalRecording
# ---------------------------------------------------------------------------


class TestSubTaskJournalRecording:
    """Journal recording with dag_node_id population."""

    @pytest.mark.asyncio
    async def test_journal_record_called_per_step(self):
        journal = AsyncMock()
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        executor.register_handler(SubTaskType.COMPOSE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
        ])
        await executor.execute(
            chain, {}, agent_id="agent-1", journal=journal,
        )
        # Both ANALYZE and COMPOSE are LLM sub-tasks → 2 journal records
        assert journal.record.call_count == 2

    @pytest.mark.asyncio
    async def test_dag_node_id_format(self):
        journal = AsyncMock()
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
        ])
        await executor.execute(
            chain, {}, agent_id="agent-1", journal=journal,
        )
        call_kwargs = journal.record.call_args_list[0][1]
        dag_node_id = call_kwargs["dag_node_id"]
        # Format: "st:{chain_id}:{index}:{type}"
        assert re.match(r"^st:[a-f0-9]{8}:0:analyze$", dag_node_id), \
            f"dag_node_id format mismatch: {dag_node_id}"

    @pytest.mark.asyncio
    async def test_agent_id_attributed_to_parent(self):
        journal = AsyncMock()
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.COMPOSE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
        ])
        await executor.execute(
            chain, {}, agent_id="parent-agent-99", journal=journal,
        )
        call_kwargs = journal.record.call_args_list[0][1]
        assert call_kwargs["agent_id"] == "parent-agent-99"

    @pytest.mark.asyncio
    async def test_no_journal_on_query_step(self):
        journal = AsyncMock()
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.QUERY, _sync_make_handler(tokens=0))
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q"),
        ])
        await executor.execute(
            chain, {}, agent_id="agent-1", journal=journal,
        )
        # QUERY steps have 0 LLM calls → no journal entry
        journal.record.assert_not_called()


# ---------------------------------------------------------------------------
# 7. TestSubTaskEventEmission
# ---------------------------------------------------------------------------


class TestSubTaskEventEmission:
    """SUB_TASK_CHAIN_COMPLETED event emission."""

    @pytest.mark.asyncio
    async def test_chain_completed_event(self):
        emitter = MagicMock()
        executor = SubTaskExecutor(emit_event_fn=emitter)
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a")],
            source="test-trigger",
        )
        await executor.execute(chain, {}, agent_id="agent-1")
        emitter.assert_called_once()
        call_args = emitter.call_args
        from probos.events import EventType
        assert call_args[0][0] == EventType.SUB_TASK_CHAIN_COMPLETED
        event_data = call_args[0][1]
        assert event_data["data"]["success"] is True
        assert event_data["data"]["source"] == "test-trigger"

    @pytest.mark.asyncio
    async def test_chain_completed_event_on_failure(self):
        emitter = MagicMock()
        executor = SubTaskExecutor(emit_event_fn=emitter)
        executor.register_handler(
            SubTaskType.ANALYZE,
            _sync_make_handler(success=False, error="fail"),
        )
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a", required=True),
        ])
        with pytest.raises(SubTaskStepError):
            await executor.execute(chain, {}, agent_id="agent-1")
        emitter.assert_called_once()
        event_data = emitter.call_args[0][1]
        assert event_data["data"]["success"] is False

    @pytest.mark.asyncio
    async def test_no_event_without_emitter(self):
        executor = SubTaskExecutor()  # No emit_event_fn
        executor.register_handler(SubTaskType.ANALYZE, _sync_make_handler())
        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
        ])
        # Should not raise — just no event
        results = await executor.execute(chain, {}, agent_id="agent-1")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# 8. TestCognitiveAgentIntegration
# ---------------------------------------------------------------------------


class TestCognitiveAgentIntegration:
    """CognitiveAgent sub-task executor wiring and decide() integration."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent(
            agent_id="test-agent",
            instructions="Test instructions",
            llm_client=AsyncMock(),
        )
        return agent

    def test_set_sub_task_executor(self):
        agent = self._make_agent()
        assert agent._sub_task_executor is None
        executor = SubTaskExecutor()
        agent.set_sub_task_executor(executor)
        assert agent._sub_task_executor is executor

    @pytest.mark.asyncio
    async def test_execute_chain_returns_decision(self):
        agent = self._make_agent()
        executor = SubTaskExecutor()
        executor.register_handler(
            SubTaskType.COMPOSE,
            _sync_make_handler(result_dict={"output": "composed text"}, tier_used="deep"),
        )
        agent.set_sub_task_executor(executor)

        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
        ])
        result = await agent._execute_sub_task_chain(chain, {"intent": "test"})
        assert result is not None
        assert result["sub_task_chain"] is True
        assert result["action"] == "execute"
        assert result["llm_output"] == "composed text"

    @pytest.mark.asyncio
    async def test_execute_chain_fallback_on_error(self):
        agent = self._make_agent()
        executor = SubTaskExecutor()
        # No handlers registered — can_execute returns False
        agent.set_sub_task_executor(executor)

        chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="a"),
        ])
        result = await agent._execute_sub_task_chain(chain, {})
        assert result is None  # Fallback signal

    @pytest.mark.asyncio
    async def test_decide_with_pending_chain(self):
        agent = self._make_agent()
        executor = SubTaskExecutor()
        executor.register_handler(
            SubTaskType.COMPOSE,
            _sync_make_handler(result_dict={"output": "sub-task output"}, tier_used="standard"),
        )
        agent.set_sub_task_executor(executor)
        agent._pending_sub_task_chain = SubTaskChain(steps=[
            SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
        ])

        # Mock _decide_via_llm to ensure it's NOT called
        agent._decide_via_llm = AsyncMock(return_value={"action": "execute", "llm_output": "direct"})

        result = await agent.decide({"intent": "test", "intent_id": "id-1"})
        assert result["sub_task_chain"] is True
        assert result["llm_output"] == "sub-task output"
        # _decide_via_llm should NOT have been called
        agent._decide_via_llm.assert_not_called()
        # Pending chain consumed
        assert agent._pending_sub_task_chain is None

    @pytest.mark.asyncio
    async def test_decide_without_chain_unchanged(self):
        agent = self._make_agent()
        # No executor, no pending chain — normal flow
        llm_response = MagicMock()
        llm_response.content = "normal output"
        llm_response.tier = "standard"
        llm_response.model = "test-model"
        llm_response.prompt_tokens = 10
        llm_response.completion_tokens = 20
        llm_response.tokens_used = 30
        llm_response.error = None
        llm_response.id = "req-1"
        agent._llm_client.complete = AsyncMock(return_value=llm_response)

        result = await agent.decide({"intent": "test", "intent_id": "id-2"})
        assert result["action"] == "execute"
        assert result["llm_output"] == "normal output"
        assert "sub_task_chain" not in result


# ---------------------------------------------------------------------------
# 9. TestSubTaskConfig
# ---------------------------------------------------------------------------


class TestSubTaskConfig:
    """SubTaskConfig defaults and SystemConfig integration."""

    def test_defaults(self):
        from probos.config import SubTaskConfig
        config = SubTaskConfig()
        assert config.enabled is True  # AD-632f: flipped to True
        assert config.chain_timeout_ms == 30000
        assert config.step_timeout_ms == 15000
        assert config.fallback_on_timeout == "single_call"

    def test_system_config_integration(self):
        from probos.config import SystemConfig
        config = SystemConfig()
        assert hasattr(config, "sub_task")
        assert config.sub_task.enabled is True  # AD-632f: flipped to True

    def test_max_chain_steps(self):
        from probos.config import SubTaskConfig
        config = SubTaskConfig()
        assert config.max_chain_steps == 6
