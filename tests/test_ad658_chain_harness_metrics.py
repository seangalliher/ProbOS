"""AD-658: Cognitive Chain Harness Metrics — tests."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.chain_trace import ChainExecutionTrace
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)


# ---------------------------------------------------------------------------
# Section 1 — dataclass
# ---------------------------------------------------------------------------

def test_chain_execution_trace_dataclass_defaults() -> None:
    trace = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
    )
    assert trace.agent_id == ""
    assert trace.success is True
    assert trace.tokens_used == 0
    assert trace.context_filter_applied is False
    assert trace.communication_context is None
    assert trace.chain_trust_band is None
    assert trace.trust_score is None
    assert trace.boot_camp_active is False
    assert trace.from_captain is False
    assert trace.is_dm is False

    d = trace.to_dict()
    assert d["chain_id"] == "c"
    assert d["step_index"] == 0
    assert d["sub_task_type"] == "analyze"
    assert d["context_keys_declared"] == 0
    # Round-trip: reconstruct from dict
    trace2 = ChainExecutionTrace(**d)
    assert trace2 == trace


def test_chain_execution_trace_is_frozen() -> None:
    trace = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
    )
    assert dataclasses.is_dataclass(trace)
    with pytest.raises(dataclasses.FrozenInstanceError):
        trace.duration_ms = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 2 — Journal record_chain_trace / get_recent_chain_traces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_record_and_get_recent_chain_traces_round_trip(tmp_path) -> None:
    db_path = str(tmp_path / "j.db")
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        trace = ChainExecutionTrace(
            chain_id="abc", step_index=0, step_name="analyze-thread",
            sub_task_type="analyze", tier="fast", chain_source="skill",
            agent_id="agent-1", agent_type="counselor", intent="reply",
            intent_id="int-9", started_at=1000.0, duration_ms=42.5,
            tokens_used=128, success=True, error_truncated="",
            context_keys_declared=2, context_keys_passed=3,
            context_filter_applied=True,
            communication_context="bridge_briefing",
            chain_trust_band="high", trust_score=0.82,
            boot_camp_active=False, from_captain=True, is_dm=False,
        )
        await journal.record_chain_trace(trace)
        rows = await journal.get_recent_chain_traces(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["chain_id"] == "abc"
        assert row["step_index"] == 0
        assert row["step_name"] == "analyze-thread"
        assert row["sub_task_type"] == "analyze"
        assert row["tier"] == "fast"
        assert row["chain_source"] == "skill"
        assert row["agent_id"] == "agent-1"
        assert row["duration_ms"] == 42.5
        assert row["tokens_used"] == 128
        assert row["success"] == 1
        assert row["context_keys_declared"] == 2
        assert row["context_keys_passed"] == 3
        assert row["context_filter_applied"] == 1
        assert row["communication_context"] == "bridge_briefing"
        assert row["chain_trust_band"] == "high"
        assert row["trust_score"] == 0.82
        assert row["from_captain"] == 1
        assert row["is_dm"] == 0
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_journal_get_recent_chain_traces_filters_and_ordering(tmp_path) -> None:
    db_path = str(tmp_path / "j.db")
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        for idx, (agent, ts) in enumerate([("a", 1.0), ("a", 2.0), ("b", 3.0)]):
            trace = ChainExecutionTrace(
                chain_id=f"chain-{idx}", step_index=0, step_name="s",
                sub_task_type="analyze", tier="standard",
                agent_id=agent, started_at=ts,
            )
            await journal.record_chain_trace(trace)

        all_rows = await journal.get_recent_chain_traces(limit=10)
        assert len(all_rows) == 3
        assert [r["started_at"] for r in all_rows] == [3.0, 2.0, 1.0]

        a_rows = await journal.get_recent_chain_traces(agent_id="a")
        assert len(a_rows) == 2
        assert all(r["agent_id"] == "a" for r in a_rows)

        recent = await journal.get_recent_chain_traces(since=2.5)
        assert len(recent) == 1
        assert recent[0]["agent_id"] == "b"

        capped = await journal.get_recent_chain_traces(limit=2)
        assert len(capped) == 2
        assert [r["started_at"] for r in capped] == [3.0, 2.0]
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_journal_record_chain_trace_no_db_short_circuits() -> None:
    journal = CognitiveJournal(db_path=None)
    trace = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
    )
    result = await journal.record_chain_trace(trace)
    assert result is None
    rows = await journal.get_recent_chain_traces()
    assert rows == []


# ---------------------------------------------------------------------------
# Section 3 — executor emission hook
# ---------------------------------------------------------------------------

def _make_executor_with_handler(handler) -> SubTaskExecutor:
    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.ANALYZE, handler)
    return executor


@pytest.mark.asyncio
async def test_executor_emits_trace_per_step_with_modulation_snapshot() -> None:
    async def handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name,
            tokens_used=42, duration_ms=15.0, success=True, tier_used="fast",
        )

    executor = _make_executor_with_handler(handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="step-0", prompt_template="t",
            context_keys=("query",),
        )],
        source="skill",
    )

    journal = MagicMock()
    journal.record = AsyncMock()
    journal.record_chain_trace = AsyncMock()

    observation = {
        "query": "X",
        "_communication_context": "bridge_briefing",
        "_chain_trust_band": "high",
        "_trust_score": 0.82,
        "_boot_camp_active": False,
        "_from_captain": True,
        "_is_dm": False,
    }

    await executor.execute(
        chain, observation,
        agent_id="agent-1", agent_type="counselor",
        intent="reply", intent_id="int-9",
        journal=journal,
    )

    journal.record_chain_trace.assert_awaited_once()
    trace = journal.record_chain_trace.await_args.args[0]
    assert isinstance(trace, ChainExecutionTrace)
    assert trace.communication_context == "bridge_briefing"
    assert trace.chain_trust_band == "high"
    assert trace.trust_score == 0.82
    assert trace.from_captain is True
    assert trace.is_dm is False
    assert trace.boot_camp_active is False
    assert trace.tokens_used == 42
    assert trace.duration_ms == 15.0
    assert trace.success is True
    assert trace.tier == "fast"
    assert trace.chain_source == "skill"
    assert trace.step_name == "step-0"
    assert trace.step_index == 0


@pytest.mark.asyncio
async def test_executor_context_composition_breakdown_records_filter() -> None:
    async def handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name,
            success=True, tier_used="standard",
        )

    # ANALYZE — filter applied
    executor = _make_executor_with_handler(handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="a", prompt_template="t",
            context_keys=("query", "history"),
        )],
        source="test",
    )
    journal = MagicMock()
    journal.record = AsyncMock()
    journal.record_chain_trace = AsyncMock()

    observation = {
        "query": "X", "history": [], "noise": "Y", "_internal": "Z",
    }

    await executor.execute(
        chain, observation,
        agent_id="a-1", agent_type="t", intent="i", intent_id="ii",
        journal=journal,
    )
    trace = journal.record_chain_trace.await_args.args[0]
    assert trace.context_keys_declared == 2
    assert trace.context_keys_passed == 3
    assert trace.context_filter_applied is True

    # QUERY — no filter
    async def query_handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name, success=True,
        )

    executor2 = SubTaskExecutor()
    executor2.register_handler(SubTaskType.QUERY, query_handler)
    chain2 = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="q", context_keys=("query", "history"),
        )],
        source="test",
    )
    journal2 = MagicMock()
    journal2.record = AsyncMock()
    journal2.record_chain_trace = AsyncMock()

    await executor2.execute(
        chain2, observation,
        agent_id="a-1", agent_type="t", intent="i", intent_id="ii",
        journal=journal2,
    )
    trace2 = journal2.record_chain_trace.await_args.args[0]
    assert trace2.context_filter_applied is False
    assert trace2.context_keys_passed == 4


@pytest.mark.asyncio
async def test_executor_trace_emission_failure_does_not_break_chain() -> None:
    async def handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name,
            success=True, tokens_used=5, tier_used="standard",
        )

    executor = _make_executor_with_handler(handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="step-0", prompt_template="t",
        )],
        source="test",
    )

    journal = MagicMock()
    journal.record = AsyncMock()
    journal.record_chain_trace = AsyncMock(side_effect=Exception("boom"))

    results = await executor.execute(
        chain, {"query": "X"},
        agent_id="a-1", agent_type="t", intent="i", intent_id="ii",
        journal=journal,
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].tokens_used == 5
    journal.record_chain_trace.assert_awaited_once()
