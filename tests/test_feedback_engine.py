"""Tests for Phase 18 — FeedbackEngine."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from probos.cognitive.feedback import FeedbackEngine, FeedbackResult
from probos.cognitive.episodic import EpisodicMemory
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.substrate.event_log import EventLog
from probos.types import IntentResult, TaskDAG, TaskNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trust() -> MagicMock:
    """Create a mock TrustNetwork."""
    trust = MagicMock(spec=TrustNetwork)
    trust.record_outcome = MagicMock(return_value=0.5)
    return trust


def _make_hebbian(reward: float = 0.05) -> MagicMock:
    """Create a mock HebbianRouter."""
    router = MagicMock(spec=HebbianRouter)
    router.reward = reward
    router.record_interaction = MagicMock(return_value=0.1)
    return router


def _make_episodic() -> AsyncMock:
    """Create a mock EpisodicMemory."""
    mem = AsyncMock(spec=EpisodicMemory)
    mem.store = AsyncMock()
    return mem


def _make_event_log() -> AsyncMock:
    """Create a mock EventLog."""
    log = AsyncMock(spec=EventLog)
    log.log = AsyncMock()
    return log


def _make_dag(
    nodes: list[TaskNode] | None = None,
) -> TaskDAG:
    """Create a TaskDAG with given nodes."""
    if nodes is None:
        nodes = []
    return TaskDAG(nodes=nodes)


def _make_node(
    intent: str = "read_file",
    agent_id: str | None = "agent-1",
    status: str = "completed",
    result_type: str = "dict",
    node_id: str = "n1",
) -> TaskNode:
    """Create a TaskNode with a result."""
    result = None
    if agent_id and result_type == "dict":
        result = {"agent_id": agent_id, "output": "ok"}
    elif agent_id and result_type == "intent_result":
        result = IntentResult(
            intent_id="test-intent",
            agent_id=agent_id,
            success=True,
            result="ok",
        )
    node = TaskNode(id=node_id, intent=intent, status=status, result=result)
    return node


def _engine(
    trust: MagicMock | None = None,
    hebbian: MagicMock | None = None,
    episodic: AsyncMock | None = None,
    event_log: AsyncMock | None = None,
    feedback_hebbian_reward: float = 0.10,
) -> FeedbackEngine:
    return FeedbackEngine(
        trust_network=trust or _make_trust(),
        hebbian_router=hebbian or _make_hebbian(),
        episodic_memory=episodic,
        event_log=event_log,
        feedback_hebbian_reward=feedback_hebbian_reward,
    )


# ---------------------------------------------------------------------------
# TestApplyExecutionFeedback — Positive / Negative
# ---------------------------------------------------------------------------


class TestApplyExecutionPositive:
    """apply_execution_feedback() with positive=True."""

    @pytest.mark.asyncio
    async def test_strengthens_hebbian_weights(self):
        """Positive feedback calls record_interaction with success=True."""
        hebbian = _make_hebbian()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(hebbian=hebbian)

        await eng.apply_execution_feedback(dag, positive=True, original_text="read x")

        hebbian.record_interaction.assert_called_once_with(
            source="read_file",
            target="agent-1",
            success=True,
            rel_type="intent",
        )

    @pytest.mark.asyncio
    async def test_boosts_trust(self):
        """Positive feedback calls record_outcome with success=True."""
        trust = _make_trust()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(trust=trust)

        await eng.apply_execution_feedback(dag, positive=True, original_text="read x")

        trust.record_outcome.assert_called_once_with("agent-1", success=True)

    @pytest.mark.asyncio
    async def test_stores_feedback_episode(self):
        """Positive feedback stores episode with human_feedback tag."""
        episodic = _make_episodic()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(episodic=episodic)

        result = await eng.apply_execution_feedback(dag, positive=True, original_text="read x")

        assert result.episode_stored is True
        episodic.store.assert_called_once()
        episode = episodic.store.call_args[0][0]
        assert episode.user_input == "read x"
        assert any(
            o.get("human_feedback") == "positive" for o in episode.outcomes
        )

    @pytest.mark.asyncio
    async def test_returns_correct_agents_updated(self):
        """FeedbackResult.agents_updated contains unique agent IDs."""
        dag = _make_dag([
            _make_node("read_file", "agent-1", node_id="n1"),
            _make_node("write_file", "agent-2", node_id="n2"),
        ])
        eng = _engine()

        result = await eng.apply_execution_feedback(dag, positive=True, original_text="r")

        assert set(result.agents_updated) == {"agent-1", "agent-2"}
        assert result.feedback_type == "positive"

    @pytest.mark.asyncio
    async def test_uses_feedback_hebbian_reward(self):
        """Hebbian reward is temporarily set to 0.10 during feedback."""
        hebbian = _make_hebbian(reward=0.05)
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(hebbian=hebbian, feedback_hebbian_reward=0.10)

        # Track reward values during record_interaction calls
        rewards_during_call: list[float] = []
        original_record = hebbian.record_interaction

        def track_reward(*args, **kwargs):
            rewards_during_call.append(hebbian.reward)
            return original_record(*args, **kwargs)

        hebbian.record_interaction = track_reward

        await eng.apply_execution_feedback(dag, positive=True, original_text="r")

        # During the call, reward should have been 0.10
        assert rewards_during_call == [0.10]
        # After the call, reward should be restored to original
        assert hebbian.reward == 0.05


class TestApplyExecutionNegative:
    """apply_execution_feedback() with positive=False."""

    @pytest.mark.asyncio
    async def test_weakens_hebbian_weights(self):
        """Negative feedback calls record_interaction with success=False."""
        hebbian = _make_hebbian()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(hebbian=hebbian)

        await eng.apply_execution_feedback(dag, positive=False, original_text="r")

        hebbian.record_interaction.assert_called_once_with(
            source="read_file",
            target="agent-1",
            success=False,
            rel_type="intent",
        )

    @pytest.mark.asyncio
    async def test_penalizes_trust(self):
        """Negative feedback calls record_outcome with success=False."""
        trust = _make_trust()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(trust=trust)

        await eng.apply_execution_feedback(dag, positive=False, original_text="r")

        trust.record_outcome.assert_called_once_with("agent-1", success=False)

    @pytest.mark.asyncio
    async def test_negative_episode_tag(self):
        """Negative feedback episode has human_feedback='negative'."""
        episodic = _make_episodic()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(episodic=episodic)

        result = await eng.apply_execution_feedback(dag, positive=False, original_text="r")

        assert result.feedback_type == "negative"
        episode = episodic.store.call_args[0][0]
        assert any(
            o.get("human_feedback") == "negative" for o in episode.outcomes
        )


class TestApplyExecutionEdgeCases:
    """Edge cases for apply_execution_feedback()."""

    @pytest.mark.asyncio
    async def test_empty_dag_returns_empty_agents(self):
        """DAG with no nodes produces empty agents_updated."""
        dag = _make_dag([])
        eng = _engine()

        result = await eng.apply_execution_feedback(dag, positive=True, original_text="r")

        assert result.agents_updated == []

    @pytest.mark.asyncio
    async def test_failed_nodes_skipped(self):
        """Nodes with no result (failed/pending) are skipped."""
        failed_node = TaskNode(id="n-fail", intent="run_command", status="failed", result=None)
        ok_node = _make_node("read_file", "agent-1")
        dag = _make_dag([failed_node, ok_node])
        eng = _engine()

        result = await eng.apply_execution_feedback(dag, positive=True, original_text="r")

        assert result.agents_updated == ["agent-1"]

    @pytest.mark.asyncio
    async def test_deduplicates_agent_ids(self):
        """Same agent in multiple nodes only counted once."""
        dag = _make_dag([
            _make_node("read_file", "agent-1", node_id="n1"),
            _make_node("write_file", "agent-1", node_id="n2"),
        ])
        trust = _make_trust()
        eng = _engine(trust=trust)

        result = await eng.apply_execution_feedback(dag, positive=True, original_text="r")

        assert result.agents_updated == ["agent-1"]
        # Trust called once per unique agent
        trust.record_outcome.assert_called_once_with("agent-1", success=True)


# ---------------------------------------------------------------------------
# TestRejectionFeedback
# ---------------------------------------------------------------------------


class TestRejectionFeedback:
    """apply_rejection_feedback() tests."""

    @pytest.mark.asyncio
    async def test_stores_rejection_episode(self):
        """Rejection stores episode with rejected_plan tag."""
        episodic = _make_episodic()
        dag = _make_dag([_make_node("run_command", "agent-1")])
        eng = _engine(episodic=episodic)

        result = await eng.apply_rejection_feedback("delete all files", dag)

        assert result.feedback_type == "rejected_plan"
        assert result.episode_stored is True
        episode = episodic.store.call_args[0][0]
        assert episode.user_input == "delete all files"
        assert any(
            o.get("human_feedback") == "rejected_plan" for o in episode.outcomes
        )

    @pytest.mark.asyncio
    async def test_no_trust_updates(self):
        """Rejection does NOT update trust (no agents executed)."""
        trust = _make_trust()
        dag = _make_dag([_make_node("run_command", "agent-1")])
        eng = _engine(trust=trust)

        await eng.apply_rejection_feedback("delete all files", dag)

        trust.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_hebbian_updates(self):
        """Rejection does NOT update Hebbian weights."""
        hebbian = _make_hebbian()
        dag = _make_dag([_make_node("run_command", "agent-1")])
        eng = _engine(hebbian=hebbian)

        await eng.apply_rejection_feedback("delete all files", dag)

        hebbian.record_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_rejected_plan_type(self):
        dag = _make_dag([_make_node("x", "a1")])
        eng = _engine()

        result = await eng.apply_rejection_feedback("text", dag)

        assert result.feedback_type == "rejected_plan"
        assert result.agents_updated == []

    @pytest.mark.asyncio
    async def test_rejection_episode_metadata(self):
        """Rejection episode has correct dag_summary with human_feedback."""
        episodic = _make_episodic()
        dag = _make_dag([_make_node("run_command", "agent-1")])
        eng = _engine(episodic=episodic)

        await eng.apply_rejection_feedback("delete files", dag)

        episode = episodic.store.call_args[0][0]
        assert episode.dag_summary.get("human_feedback") == "rejected_plan"


# ---------------------------------------------------------------------------
# TestAgentIDExtraction
# ---------------------------------------------------------------------------


class TestAgentIDExtraction:
    """_extract_agent_ids() and _extract_intent_agent_pairs() tests."""

    def test_extracts_from_dict_results(self):
        """Extracts agent_id from dict results."""
        dag = _make_dag([_make_node("read_file", "agent-1", result_type="dict")])
        eng = _engine()

        ids = eng._extract_agent_ids(dag)

        assert ids == ["agent-1"]

    def test_extracts_from_intent_result_objects(self):
        """Extracts agent_id from IntentResult objects."""
        dag = _make_dag([_make_node("read_file", "agent-1", result_type="intent_result")])
        eng = _engine()

        ids = eng._extract_agent_ids(dag)

        assert ids == ["agent-1"]

    def test_handles_missing_results(self):
        """Nodes with no result (pending/failed) are skipped."""
        none_node = TaskNode(id="n-none", intent="x", status="pending", result=None)
        dag = _make_dag([none_node])
        eng = _engine()

        ids = eng._extract_agent_ids(dag)

        assert ids == []

    def test_deduplicates(self):
        """Same agent_id in multiple nodes appears only once."""
        dag = _make_dag([
            _make_node("read_file", "agent-1", node_id="n1"),
            _make_node("write_file", "agent-1", node_id="n2"),
        ])
        eng = _engine()

        ids = eng._extract_agent_ids(dag)

        assert ids == ["agent-1"]

    def test_intent_agent_pairs(self):
        """Returns correct (intent, agent_id) pairs."""
        dag = _make_dag([
            _make_node("read_file", "agent-1", node_id="n1"),
            _make_node("write_file", "agent-2", node_id="n2"),
        ])
        eng = _engine()

        pairs = eng._extract_intent_agent_pairs(dag)

        assert ("read_file", "agent-1") in pairs
        assert ("write_file", "agent-2") in pairs
        assert len(pairs) == 2

    def test_intent_agent_pairs_skips_no_agent(self):
        """Nodes without agent_id are skipped in pairs."""
        ok = _make_node("read_file", "agent-1")
        no_result = TaskNode(id="n-fail", intent="run_shell", status="failed", result=None)
        dag = _make_dag([ok, no_result])
        eng = _engine()

        pairs = eng._extract_intent_agent_pairs(dag)

        assert pairs == [("read_file", "agent-1")]


# ---------------------------------------------------------------------------
# TestEventLogIntegration
# ---------------------------------------------------------------------------


class TestEventLogIntegration:
    """Event log calls from FeedbackEngine (AD-222)."""

    @pytest.mark.asyncio
    async def test_positive_feedback_events(self):
        """Positive feedback logs feedback_positive, hebbian_update, trust_update."""
        event_log = _make_event_log()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(event_log=event_log)

        await eng.apply_execution_feedback(dag, positive=True, original_text="read x")

        event_names = [c.kwargs.get("event") or c.args[1] for c in event_log.log.call_args_list]
        assert "feedback_positive" in event_names
        assert "feedback_hebbian_update" in event_names
        assert "feedback_trust_update" in event_names

    @pytest.mark.asyncio
    async def test_negative_feedback_events(self):
        """Negative feedback logs feedback_negative."""
        event_log = _make_event_log()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(event_log=event_log)

        await eng.apply_execution_feedback(dag, positive=False, original_text="read x")

        event_names = [c.kwargs.get("event") or c.args[1] for c in event_log.log.call_args_list]
        assert "feedback_negative" in event_names

    @pytest.mark.asyncio
    async def test_rejection_event(self):
        """Rejection logs feedback_plan_rejected."""
        event_log = _make_event_log()
        dag = _make_dag([_make_node("run_command", "agent-1")])
        eng = _engine(event_log=event_log)

        await eng.apply_rejection_feedback("delete files", dag)

        event_names = [c.kwargs.get("event") or c.args[1] for c in event_log.log.call_args_list]
        assert "feedback_plan_rejected" in event_names

    @pytest.mark.asyncio
    async def test_event_log_category_is_cognitive(self):
        """All feedback events use category='cognitive'."""
        event_log = _make_event_log()
        dag = _make_dag([_make_node("read_file", "agent-1")])
        eng = _engine(event_log=event_log)

        await eng.apply_execution_feedback(dag, positive=True, original_text="x")

        for call_obj in event_log.log.call_args_list:
            cat = call_obj.kwargs.get("category") or call_obj.args[0]
            assert cat == "cognitive"


# ---------------------------------------------------------------------------
# TestFeedbackResult
# ---------------------------------------------------------------------------


class TestFeedbackResult:
    """FeedbackResult dataclass sanity."""

    def test_defaults(self):
        r = FeedbackResult(feedback_type="positive")
        assert r.agents_updated == []
        assert r.episode_stored is False
        assert r.original_text == ""

    def test_with_agents(self):
        r = FeedbackResult(
            feedback_type="negative",
            agents_updated=["a1", "a2"],
            episode_stored=True,
            original_text="hello",
        )
        assert r.feedback_type == "negative"
        assert len(r.agents_updated) == 2
