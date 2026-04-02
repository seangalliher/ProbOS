"""AD-537: Level 5 dispatch and COMPILATION_MAX_LEVEL — 8 tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.procedures import Procedure


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_graduated_compilation.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeStep:
    step_number: int = 1
    action: str = "do something"
    expected_output: str = ""
    expected_input: str = ""
    fallback_action: str = ""
    invariants: list[str] = field(default_factory=list)
    agent_role: str = ""
    resolved_agent_type: str = ""


@dataclass
class _FakeProcedure:
    id: str = "proc-lvl5"
    name: str = "test-level5"
    description: str = "A Level 5 test procedure"
    compilation_level: int = 5
    steps: list = field(default_factory=lambda: [_FakeStep()])
    postconditions: list[str] = field(default_factory=list)
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
    preconditions: list[str] = field(default_factory=list)

    def to_dict(self):
        return {"id": self.id, "name": self.name}


def _make_procedure(**kwargs) -> Procedure:
    defaults = dict(
        id="proc-lvl5",
        name="test-level5",
        description="A Level 5 test procedure",
        compilation_level=5,
        is_active=True,
    )
    defaults.update(kwargs)
    return Procedure(**defaults)


def _make_cognitive_agent(**overrides):
    """Create a minimal CognitiveAgent for testing."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES
    from probos.types import AgentMeta, AgentState

    defaults = {
        "agent_type": "test-level5",
        "pool_name": "test-pool",
        "instructions": "Test instructions for Level 5 dispatch",
    }
    defaults.update(overrides)
    _DECISION_CACHES.pop(defaults["agent_type"], None)

    agent = object.__new__(CognitiveAgent)
    agent.agent_type = defaults["agent_type"]
    agent.pool_name = defaults["pool_name"]
    agent.instructions = defaults["instructions"]
    agent.id = defaults.get("id", "agent-001")
    agent.callsign = defaults.get("callsign", "")
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
    agent.trust_score = defaults.get("trust_score", 0.5)
    agent._trust_score = defaults.get("trust_score", 0.5)
    return agent


def _make_store_mock(promotion_status: str = "private") -> AsyncMock:
    """Build an AsyncMock procedure store with sane defaults."""
    store = AsyncMock()
    store.find_matching = AsyncMock(side_effect=[
        [],  # negative check
        [{"id": "proc-lvl5", "name": "test-level5", "score": 0.95}],
    ])
    store.get_quality_metrics = AsyncMock(return_value={
        "total_selections": 10, "effective_rate": 1.0,
    })
    store.record_selection = AsyncMock()
    store.record_applied = AsyncMock()
    store.get_promotion_status = AsyncMock(return_value=promotion_status)
    return store


# ===========================================================================
# Test 1: COMPILATION_MAX_LEVEL constant
# ===========================================================================
class TestCompilationMaxLevel:
    def test_compilation_max_level_is_5(self):
        from probos.config import COMPILATION_MAX_LEVEL

        assert COMPILATION_MAX_LEVEL == 5


# ===========================================================================
# Test 2-4: _max_compilation_level_for_promoted boundaries
# ===========================================================================
class TestLevel5PromotedAccess:
    def test_level_5_reachable_for_promoted_commander(self):
        """Approved procedure + Commander trust (0.95) → Level 5."""
        agent = _make_cognitive_agent(trust_score=0.95)
        result = agent._max_compilation_level_for_promoted(0.95, "approved")
        assert result == 5

    def test_level_5_unreachable_without_promotion(self):
        """Private (non-promoted) procedure → capped at 4 even with high trust."""
        agent = _make_cognitive_agent(trust_score=0.95)
        result = agent._max_compilation_level_for_promoted(0.95, "private")
        assert result <= 4

    def test_level_5_unreachable_without_commander_trust(self):
        """Approved procedure but trust 0.7 is exactly at TRUST_COMMANDER boundary.

        trust=0.6 (below Commander) + approved → still capped at 4.
        """
        agent = _make_cognitive_agent(trust_score=0.6)
        result = agent._max_compilation_level_for_promoted(0.6, "approved")
        assert result <= 4


# ===========================================================================
# Test 5: Level 5 dispatch falls through to same path as Level 4
# ===========================================================================
class TestLevel5Dispatch:
    @pytest.mark.asyncio
    async def test_level_5_dispatch_same_as_level_4(self):
        """Level 5 (Expert) uses the same zero-token replay path as Level 4."""
        proc = _FakeProcedure(compilation_level=5)
        store = _make_store_mock(promotion_status="approved")
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.get_service = MagicMock(return_value=None)

        agent = _make_cognitive_agent(
            trust_score=0.95,
            runtime=runtime,
        )

        result = await agent._check_procedural_memory({"intent": "do something"})

        # Level 5 should produce a result (zero-token replay), not None
        assert result is not None
        assert result.get("cached") is True
        assert result.get("procedure_id") == "proc-lvl5"

# ===========================================================================
class TestLevel5Promotion:
    @pytest.mark.asyncio
    async def test_level_5_promotion_from_4(self):
        """A procedure at Level 4 with approved promotion can reach Level 5.

        The promotion logic is inline in record_outcome. Here we verify
        the boundary conditions:
        - _max_compilation_level_for_promoted returns 5 for approved + Commander trust
        - COMPILATION_MAX_LEVEL is 5
        - So next_level (5) <= min(5, 5) = 5 is allowed.
        """
        from probos.config import COMPILATION_MAX_LEVEL

        agent = _make_cognitive_agent(trust_score=0.95)
        max_allowed = agent._max_compilation_level_for_promoted(0.95, "approved")
        next_level = 4 + 1  # Level 4 → 5

        # The promotion guard is: next_level <= min(max_allowed, COMPILATION_MAX_LEVEL)
        assert next_level <= min(max_allowed, COMPILATION_MAX_LEVEL)
        assert max_allowed == 5
        assert COMPILATION_MAX_LEVEL == 5


# ===========================================================================
# Test 7: Level 4 dispatch still works (regression guard)
# ===========================================================================
class TestLevel4Regression:
    @pytest.mark.asyncio
    async def test_existing_level_4_tests_still_pass(self):
        """Level 4 (Autonomous) dispatch returns cached/replay result."""
        proc = _FakeProcedure(compilation_level=4)
        store = _make_store_mock(promotion_status="private")
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.get_service = MagicMock(return_value=None)

        agent = _make_cognitive_agent(
            trust_score=0.7,
            runtime=runtime,
        )

        result = await agent._check_procedural_memory({"intent": "do something"})

        assert result is not None
        assert result.get("cached") is True
        assert result.get("procedure_id") == "proc-lvl5"


# ===========================================================================
# Test 8: Non-promoted max level is 4
# ===========================================================================
class TestNonPromotedCap:
    def test_non_promoted_max_level_4(self):
        """_max_compilation_level_for_trust() always caps at 4, never 5."""
        agent = _make_cognitive_agent(trust_score=0.99)
        result = agent._max_compilation_level_for_trust(0.99)
        assert result == 4

        # Also verify across multiple trust tiers
        for trust in [0.5, 0.7, 0.85, 0.95, 1.0]:
            assert agent._max_compilation_level_for_trust(trust) <= 4
