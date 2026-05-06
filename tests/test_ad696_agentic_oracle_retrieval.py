"""AD-696 v1: Agentic Oracle Retrieval — On-Demand Ship's Records Query.

Covers:
- EventType.ORACLE_LOOKUP_DISPATCHED registration (Section 0)
- _query_oracle_lookup QUERY op + dispatch table entry (Section 1)
- _maybe_dispatch_oracle_lookup chain helper (Section 3)
- ToolRegistry registration of oracle_lookup with READ permission (Section 4)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.query import (
    _QUERY_OPERATIONS,
    _query_oracle_lookup,
)
from probos.earned_agency import RecallTier
from probos.events import EventType


# ---------------------------------------------------------------------------
# Section 0 — EventType
# ---------------------------------------------------------------------------


def test_event_type_oracle_lookup_dispatched_exists():
    assert EventType.ORACLE_LOOKUP_DISPATCHED.value == "oracle_lookup_dispatched"


# ---------------------------------------------------------------------------
# Section 1 — QUERY op + dispatch table
# ---------------------------------------------------------------------------


def test_oracle_lookup_op_registered_in_query_operations_dispatch_table():
    assert "oracle_lookup" in _QUERY_OPERATIONS
    assert _QUERY_OPERATIONS["oracle_lookup"] is _query_oracle_lookup


def _make_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.QUERY,
        name="oracle-agentic-lookup",
        context_keys=("oracle_lookup",),
    )


def _make_runtime_with_oracle(formatted: str = "=== ORACLE ===\n[graph: bob -> alice]\n") -> MagicMock:
    runtime = MagicMock()
    runtime.oracle = MagicMock()
    runtime.oracle.query_formatted = AsyncMock(return_value=formatted)
    return runtime


def test_oracle_lookup_returns_formatted_text_when_oracle_present():
    runtime = _make_runtime_with_oracle("=== ORACLE ===\nrecord-x\n")
    context = {
        "oracle_query_text": "who reports to bob",
        "_recall_tier": RecallTier.ORACLE,
        "_emit_event_fn": MagicMock(),
        "_agent_id": "agent-1",
        "_agent_type": "ScienceOfficer",
    }
    result = asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    assert result == {"oracle_lookup": "=== ORACLE ===\nrecord-x\n"}
    runtime.oracle.query_formatted.assert_awaited_once()


def test_oracle_lookup_returns_empty_when_oracle_query_text_missing():
    runtime = _make_runtime_with_oracle()
    context = {
        "_recall_tier": RecallTier.ORACLE,
        "_agent_id": "agent-1",
    }
    result = asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    assert result == {"oracle_lookup": ""}
    runtime.oracle.query_formatted.assert_not_called()


def test_oracle_lookup_returns_empty_when_runtime_oracle_absent():
    runtime = MagicMock()
    runtime.oracle = None
    context = {
        "oracle_query_text": "query",
        "_recall_tier": RecallTier.ORACLE,
        "_agent_id": "agent-1",
    }
    result = asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    assert result == {"oracle_lookup": ""}


def test_oracle_lookup_returns_empty_when_recall_tier_below_oracle():
    runtime = _make_runtime_with_oracle()
    context = {
        "oracle_query_text": "query",
        "_recall_tier": RecallTier.FULL,  # below ORACLE
        "_agent_id": "agent-1",
    }
    result = asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    assert result == {"oracle_lookup": ""}
    runtime.oracle.query_formatted.assert_not_called()


def test_oracle_lookup_swallows_oracle_exception_and_returns_empty(caplog):
    runtime = MagicMock()
    runtime.oracle = MagicMock()
    runtime.oracle.query_formatted = AsyncMock(side_effect=RuntimeError("boom"))
    context = {
        "oracle_query_text": "query",
        "_recall_tier": RecallTier.ORACLE,
        "_agent_id": "agent-1",
    }
    import logging
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    assert result == {"oracle_lookup": ""}
    assert any("oracle_lookup query failed" in rec.message for rec in caplog.records)


def test_oracle_lookup_passes_optional_oracle_tiers_filter():
    runtime = _make_runtime_with_oracle("formatted")
    context = {
        "oracle_query_text": "query",
        "oracle_tiers": ["semantic", "graph"],
        "_recall_tier": RecallTier.ORACLE,
        "_agent_id": "agent-1",
    }
    asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    call_kwargs = runtime.oracle.query_formatted.await_args.kwargs
    assert call_kwargs["tiers"] == ["semantic", "graph"]


def test_oracle_lookup_emits_oracle_lookup_dispatched_event_on_dispatch():
    runtime = _make_runtime_with_oracle("hello world")
    emit_fn = MagicMock()
    context = {
        "oracle_query_text": "query",
        "_recall_tier": RecallTier.ORACLE,
        "_emit_event_fn": emit_fn,
        "_agent_id": "agent-1",
        "_agent_type": "ScienceOfficer",
    }
    asyncio.run(_query_oracle_lookup(runtime, _make_spec(), context))
    emit_fn.assert_called_once()
    args, _ = emit_fn.call_args
    assert args[0] == EventType.ORACLE_LOOKUP_DISPATCHED
    payload = args[1]
    assert payload["agent_id"] == "agent-1"
    assert payload["agent_type"] == "ScienceOfficer"
    assert payload["query_text"] == "query"
    assert payload["tiers"] == []
    assert payload["result_chars"] == len("hello world")


# ---------------------------------------------------------------------------
# Section 3 — _maybe_dispatch_oracle_lookup chain helper
# ---------------------------------------------------------------------------


def _make_chain_helper_fixture(
    oracle_lookup_result: str | None = "[graph: ...]",
    analyze_query_text: str | None = "incident 47",
):
    """Build a CognitiveAgent-like object exposing _maybe_dispatch_oracle_lookup."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = MagicMock(spec=CognitiveAgent)
    agent.id = "agent-1"
    agent.agent_type = "ScienceOfficer"
    agent._cognitive_journal = MagicMock()
    agent._sub_task_executor = MagicMock()

    if oracle_lookup_result is None:
        execute_results: list = []
    else:
        execute_results = [
            SubTaskResult(
                sub_task_type=SubTaskType.QUERY,
                name="oracle-agentic-lookup",
                result={"oracle_lookup": oracle_lookup_result},
                success=True,
            )
        ]
    agent._sub_task_executor.execute = AsyncMock(return_value=execute_results)

    triage_results = []
    if analyze_query_text is not None:
        triage_results.append(
            SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name="analyze",
                result={
                    "intended_actions": ["ward_room_reply", "oracle_query"],
                    "oracle_query_text": analyze_query_text,
                },
                success=True,
            )
        )

    # Bind the real method so behavior under test is the unmocked implementation.
    agent._maybe_dispatch_oracle_lookup = (
        CognitiveAgent._maybe_dispatch_oracle_lookup.__get__(agent)
    )
    return agent, triage_results


def test_chain_helper_dispatches_oracle_lookup_when_intended_action_present():
    agent, triage_results = _make_chain_helper_fixture(
        oracle_lookup_result="[graph: bob -> alice]",
        analyze_query_text="incident 47",
    )
    observation: dict = {"_oracle_lookup_fired": False}

    asyncio.run(agent._maybe_dispatch_oracle_lookup(triage_results, observation))

    assert observation["_oracle_context"] == "[graph: bob -> alice]"
    assert observation["_oracle_lookup_fired"] is True
    agent._sub_task_executor.execute.assert_awaited_once()


def test_chain_helper_skips_oracle_lookup_when_intended_action_absent():
    # No ANALYZE result with oracle_query_text — helper short-circuits
    agent, triage_results = _make_chain_helper_fixture(
        oracle_lookup_result=None,
        analyze_query_text=None,
    )
    observation: dict = {"_oracle_lookup_fired": False, "_oracle_context": "PRE_RAG"}

    asyncio.run(agent._maybe_dispatch_oracle_lookup(triage_results, observation))

    agent._sub_task_executor.execute.assert_not_called()
    assert observation["_oracle_context"] == "PRE_RAG"  # unchanged


def test_chain_helper_dispatches_oracle_lookup_at_most_once_per_chain():
    agent, triage_results = _make_chain_helper_fixture(
        oracle_lookup_result="[result]",
        analyze_query_text="x",
    )
    observation: dict = {"_oracle_lookup_fired": True}  # already fired

    asyncio.run(agent._maybe_dispatch_oracle_lookup(triage_results, observation))

    agent._sub_task_executor.execute.assert_not_called()


def test_chain_helper_writes_result_to_observation_oracle_context_key():
    agent, triage_results = _make_chain_helper_fixture(
        oracle_lookup_result="THE_PAYLOAD",
        analyze_query_text="x",
    )
    observation: dict = {"_oracle_lookup_fired": False}

    asyncio.run(agent._maybe_dispatch_oracle_lookup(triage_results, observation))

    assert observation.get("_oracle_context") == "THE_PAYLOAD"
    assert "_oracle_lookup" not in observation  # NOT this key


# ---------------------------------------------------------------------------
# Section 4 — ToolRegistry registration
# ---------------------------------------------------------------------------


def test_oracle_tool_registered_in_tool_registry_with_read_permission():
    """Replays the AD-696 wiring block from startup/communication.py."""
    from probos.tools.adapters import DirectServiceAdapter
    from probos.tools.protocol import ToolType
    from probos.tools.registry import ToolRegistry

    runtime = MagicMock()
    runtime.oracle = MagicMock()
    runtime.oracle.query_formatted = AsyncMock(return_value="formatted")

    tool_registry = ToolRegistry()

    # Mirror the wiring block in communication.py (Section 4)
    assert getattr(runtime, "oracle", None) is not None
    oracle_adapter = DirectServiceAdapter(
        tool_id="oracle_lookup",
        name="Oracle (Ship's Records Query)",
        description="Query Ship's Records.",
        input_schema={
            "type": "object",
            "properties": {"query_text": {"type": "string"}},
            "required": ["query_text"],
        },
        output_schema={"type": "string"},
        handler=runtime.oracle.query_formatted,
        tool_type=ToolType.INFRA_SERVICE,
    )
    tool_registry.register(
        oracle_adapter,
        provider="oracle_service",
        tags=["oracle", "memory", "rag", "ad696"],
        default_permissions={"*": "read"},
    )

    reg = tool_registry.get("oracle_lookup")
    assert reg is not None
    assert reg.default_permissions == {"*": "read"}
    assert "oracle" in reg.tags
    assert reg.tool.tool_type == ToolType.INFRA_SERVICE
