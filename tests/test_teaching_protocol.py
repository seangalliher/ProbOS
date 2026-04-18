"""AD-537: Teaching Protocol — 8 tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeStep:
    step_number: int = 1
    action: str = "run diagnostics"
    expected_output: str = ""
    expected_input: str = ""
    fallback_action: str = ""
    invariants: list[str] = field(default_factory=list)
    agent_role: str = ""
    resolved_agent_type: str = ""


@dataclass
class _FakeProcedure:
    id: str = "proc-teach-1"
    name: str = "warp-core-alignment"
    description: str = "Align the warp core"
    compilation_level: int = 5
    steps: list = field(default_factory=lambda: [_FakeStep(step_number=1, action="run diagnostics"),
                                                  _FakeStep(step_number=2, action="adjust alignment")])
    postconditions: list[str] = field(default_factory=lambda: ["warp core aligned"])
    preconditions: list[str] = field(default_factory=lambda: ["warp core online"])
    is_active: bool = True
    is_negative: bool = False
    origin_cluster_id: str = ""
    evolution_type: str = "CAPTURED"
    generation: int = 0
    superseded_by: str = ""
    intent_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    origin_agent_ids: list[str] = field(default_factory=list)
    parent_procedure_ids: list[str] = field(default_factory=list)
    extraction_date: float = 0.0

    def to_dict(self):
        return {"id": self.id, "name": self.name}


@dataclass
class _FakeDMChannel:
    id: str = "dm-channel-1"


def _make_cognitive_agent(**overrides):
    """Create a minimal CognitiveAgent wired for teaching protocol tests."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES
    from probos.types import AgentMeta, AgentState

    defaults = {
        "agent_type": "test-teacher",
        "pool_name": "test-pool",
        "instructions": "Test instructions for teaching protocol",
    }
    defaults.update(overrides)
    _DECISION_CACHES.pop(defaults["agent_type"], None)

    agent = object.__new__(CognitiveAgent)
    agent.agent_type = defaults["agent_type"]
    agent.pool_name = defaults["pool_name"]
    agent.instructions = defaults["instructions"]
    agent.id = defaults.get("id", "agent-teacher-001")
    agent.callsign = defaults.get("callsign", "LaForge")
    agent.confidence = 0.5
    agent._llm_client = defaults.get("llm_client")
    agent._runtime = defaults.get("runtime")
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    agent._handled_intents = set()
    agent.intent_descriptors = []
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.9)
    agent._trust_score = defaults.get("trust_score", 0.9)
    agent._callsign = defaults.get("callsign", "LaForge")
    agent._agent_id = defaults.get("id", "agent-teacher-001")
    return agent


def _make_runtime(trust: float = 0.9):
    """Build a mock runtime with ward_room and trust_network."""
    rt = MagicMock()
    # Trust network
    rt.trust_network = MagicMock()
    rt.trust_network.get_score = MagicMock(return_value=trust)
    # Ward Room
    rt.ward_room = AsyncMock()
    rt.ward_room.get_or_create_dm_channel = AsyncMock(return_value=_FakeDMChannel())
    rt.ward_room.create_thread = AsyncMock()
    # Procedure store
    store = AsyncMock()
    store.get = AsyncMock(return_value=_FakeProcedure())
    store.get_promotion_status = AsyncMock(return_value="approved")
    store.get_quality_metrics = AsyncMock(return_value={
        "total_completions": 12,
        "effective_rate": 0.95,
    })
    rt.procedure_store = store
    return rt


# ===========================================================================
# Tests
# ===========================================================================


class TestTeachingProtocol:
    """AD-537: Teaching protocol tests — 8 tests."""

    @pytest.mark.asyncio
    async def test_teach_procedure_success(self):
        """All preconditions met -> returns True, DM sent."""
        rt = _make_runtime(trust=0.9)
        agent = _make_cognitive_agent(runtime=rt)

        result = await agent._teach_procedure("proc-teach-1", "Wesley")

        assert result is True
        rt.ward_room.create_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teach_requires_level_5(self):
        """Level 4 procedure -> returns False."""
        rt = _make_runtime(trust=0.9)
        # Return a Level 4 procedure
        rt.procedure_store.get = AsyncMock(
            return_value=_FakeProcedure(compilation_level=4)
        )
        agent = _make_cognitive_agent(runtime=rt)

        result = await agent._teach_procedure("proc-teach-1", "Wesley")

        assert result is False
        rt.ward_room.create_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_teach_requires_approved(self):
        """Unapproved procedure (status 'private') -> returns False."""
        rt = _make_runtime(trust=0.9)
        rt.procedure_store.get_promotion_status = AsyncMock(return_value="private")
        agent = _make_cognitive_agent(runtime=rt)

        result = await agent._teach_procedure("proc-teach-1", "Wesley")

        assert result is False
        rt.ward_room.create_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_teach_requires_commander_trust(self):
        """Trust below 0.85 -> returns False."""
        rt = _make_runtime(trust=0.7)
        agent = _make_cognitive_agent(runtime=rt, trust_score=0.7)

        result = await agent._teach_procedure("proc-teach-1", "Wesley")

        assert result is False
        rt.ward_room.create_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_teach_dm_channel_failure_returns_false(self):
        """DM channel creation failure -> returns False."""
        rt = _make_runtime(trust=0.9)
        rt.ward_room.get_or_create_dm_channel = AsyncMock(
            side_effect=RuntimeError("Target agent not found")
        )
        agent = _make_cognitive_agent(runtime=rt)

        result = await agent._teach_procedure("proc-teach-1", "Wesley")

        assert result is False

    @pytest.mark.asyncio
    async def test_teach_sends_ward_room_dm(self):
        """Verify ward_room.create_thread called with '[TEACHING]' in title."""
        rt = _make_runtime(trust=0.9)
        agent = _make_cognitive_agent(runtime=rt)

        await agent._teach_procedure("proc-teach-1", "Wesley")

        rt.ward_room.create_thread.assert_awaited_once()
        call_kwargs = rt.ward_room.create_thread.call_args
        title = call_kwargs.kwargs.get("title", "") or call_kwargs[1].get("title", "")
        assert "[TEACHING]" in title

    @pytest.mark.asyncio
    async def test_teach_message_contains_steps(self):
        """DM body includes procedure steps."""
        rt = _make_runtime(trust=0.9)
        agent = _make_cognitive_agent(runtime=rt)

        await agent._teach_procedure("proc-teach-1", "Wesley")

        call_kwargs = rt.ward_room.create_thread.call_args
        body = call_kwargs.kwargs.get("body", "") or call_kwargs[1].get("body", "")
        assert "run diagnostics" in body
        assert "adjust alignment" in body

    @pytest.mark.asyncio
    async def test_taught_procedure_starts_at_level_2(self):
        """extract_procedure_from_observation with is_teaching=True -> compilation_level=2."""
        from probos.cognitive.procedures import extract_procedure_from_observation

        llm_client = AsyncMock()
        llm_response = MagicMock()
        llm_response.content = json.dumps({
            "name": "taught-proc",
            "description": "A taught procedure",
            "detail_score": 0.3,  # Below threshold, but teaching skips it
            "steps": [{"action": "step one"}],
            "preconditions": [],
            "postconditions": [],
        })
        llm_client.complete = AsyncMock(return_value=llm_response)

        procedure = await extract_procedure_from_observation(
            thread_content="[TEACHING] Procedure: warp-core-alignment\nSteps: ...",
            observer_agent_type="test-observer",
            author_callsign="LaForge",
            author_trust=0.9,
            llm_client=llm_client,
            is_teaching=True,
        )

        assert procedure is not None
        assert procedure.compilation_level == 2
        assert procedure.learned_via == "taught"
