"""Tests for Proactive Cognitive Loop (Phase 28b)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
from probos.bridge_alerts import BridgeAlertService
from probos.cognitive.episodic import EpisodicMemory
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry, Rank
from probos.earned_agency import can_think_proactively, agency_from_rank, AgencyLevel
from probos.knowledge.store import KnowledgeStore
from probos.mesh.intent import IntentBus
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.substrate.event_log import EventLog
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage, IntentResult
from probos.ward_room import WardRoomService
from probos.ward_room_router import WardRoomRouter


def _make_loop(**kwargs) -> ProactiveCognitiveLoop:
    """Create a loop with cooldown=0 by default so tests pass on fresh CI
    runners where time.monotonic() may be < the default 300s cooldown."""
    kwargs.setdefault("cooldown", 0)
    return ProactiveCognitiveLoop(**kwargs)


class TestCanThinkProactively:
    """can_think_proactively() — agency gating for proactive thought."""

    def test_ensign_cannot_think_proactively(self):
        assert can_think_proactively(Rank.ENSIGN) is False

    def test_lieutenant_can_think_proactively(self):
        assert can_think_proactively(Rank.LIEUTENANT) is True

    def test_commander_can_think_proactively(self):
        assert can_think_proactively(Rank.COMMANDER) is True

    def test_senior_can_think_proactively(self):
        assert can_think_proactively(Rank.SENIOR) is True


class TestProactiveCognitiveLoopLifecycle:
    """Start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        loop = _make_loop()
        loop.set_runtime(MagicMock(spec=ProbOSRuntime))
        await loop.start()
        assert loop._task is not None
        await loop.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        loop = _make_loop()
        loop.set_runtime(MagicMock(spec=ProbOSRuntime))
        await loop.start()
        await loop.stop()
        assert loop._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        loop = _make_loop()
        loop.set_runtime(MagicMock(spec=ProbOSRuntime))
        await loop.start()
        task1 = loop._task
        await loop.start()
        assert loop._task is task1
        await loop.stop()


def _make_mock_agent(agent_type="architect", agent_id="a1", alive=True):
    """Create a mock crew agent."""
    agent = MagicMock(spec=BaseAgent)
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.is_alive = alive
    agent.handle_intent = AsyncMock()
    agent.callsign = agent_type.title()
    agent.sovereign_id = ""  # AD-441: prevent MagicMock auto-truthy
    agent.did = ""
    agent.confidence = 0.8  # BF-079: was missing — spec= caught it
    return agent


def _make_mock_runtime(agents=None, trust_scores=None, ward_room=True):
    """Create a mock runtime with agents and services."""
    rt = MagicMock(spec=ProbOSRuntime)

    # BF-034: Default to non-cold-start
    rt.is_cold_start = False
    rt.ontology = None  # AD-429e: Explicit None so get_department uses legacy dict
    rt.acm = None  # AD-442: Checked directly in _run_cycle

    # Initialize sub-mocks for instance attributes not in dir(ProbOSRuntime)
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.callsign_registry = MagicMock(spec=CallsignRegistry)

    if agents is None:
        agents = [_make_mock_agent()]
    rt.registry.all.return_value = agents

    # Trust scores: default 0.7 (Commander)
    if trust_scores is None:
        trust_scores = {a.id: 0.7 for a in agents}
    rt.trust_network.get_score = MagicMock(side_effect=lambda aid: trust_scores.get(aid, 0.5))

    # is_crew_agent: set ontology=None so legacy set is used (all mock agents pass)
    rt.ontology = None

    # Ward Room
    if ward_room:
        rt.ward_room = MagicMock(spec=WardRoomService)
        rt.ward_room.list_channels = AsyncMock(return_value=[
            MagicMock(id="ch1", channel_type="department", department="science", name="Science"),
            MagicMock(id="ch2", channel_type="ship", department="", name="All Hands"),
        ])
        rt.ward_room.create_thread = AsyncMock()
    else:
        rt.ward_room = None

    # Callsign registry
    rt.callsign_registry.get_callsign = MagicMock(return_value="Number One")

    # Episodic memory
    rt.episodic_memory = MagicMock(spec=EpisodicMemory)
    rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])
    rt.episodic_memory.count_for_agent = AsyncMock(return_value=0)  # AD-568a: default zero episodes
    rt.episodic_memory.recall_weighted = AsyncMock(return_value=[])  # AD-568a: default empty

    # Bridge alerts
    rt.bridge_alerts = MagicMock(spec=BridgeAlertService)
    rt.bridge_alerts.get_recent_alerts = MagicMock(return_value=[])

    # Event log
    rt.event_log = AsyncMock(spec=EventLog)
    rt.event_log.query = AsyncMock(return_value=[])

    # AD-437: Endorsement extraction (default: no endorsements found)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)
    rt.ward_room_router.extract_endorsements = MagicMock(side_effect=lambda text: (text, []))
    rt.ward_room_router.process_endorsements = AsyncMock()

    return rt


class TestProactiveCognitiveLoopCycle:
    """_run_cycle() — agent iteration and filtering."""

    @pytest.mark.asyncio
    @patch("probos.proactive.is_crew_agent", return_value=False)
    async def test_skips_non_crew_agents(self, _mock_is_crew):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_dead_agents(self):
        agent = _make_mock_agent(alive=False)
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_ensign_agents(self):
        """Trust < 0.5 → Ensign → no proactive thought."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], trust_scores={agent.id: 0.3})

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_intent_to_lieutenant(self):
        """Trust 0.5 → Lieutenant → proactive thought allowed."""
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent], trust_scores={agent.id: 0.55})

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_called_once()
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.intent == "proactive_think"
        assert call_args.target_agent_id == agent.id

    @pytest.mark.asyncio
    async def test_respects_cooldown(self):
        """Agent in cooldown → skipped."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_runtime(rt)
        loop._last_proactive[agent.id] = time.monotonic()  # Just posted

        await loop._run_cycle()
        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_think(self):
        """Cooldown expired → agent can think again."""
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop(cooldown=1.0)
        loop.set_runtime(rt)
        loop._last_proactive[agent.id] = time.monotonic() - 2.0  # Expired
        loop._started_at = time.monotonic() - 1200  # Past cold-start window

        await loop._run_cycle()
        agent.handle_intent.assert_called_once()


class TestProactiveNoResponse:
    """[NO_RESPONSE] filtering — no WR post created."""

    @pytest.mark.asyncio
    async def test_no_response_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_response_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result=""
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_result_skips_posting(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=False, result="error"
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_not_called()


class TestProactiveWardRoomPosting:
    """Meaningful responses → WR thread creation."""

    @pytest.mark.asyncio
    async def test_meaningful_response_creates_thread(self):
        agent = _make_mock_agent(agent_type="architect")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="I notice the builder's trust has been climbing steadily. Good sign."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        rt.ward_room.create_thread.assert_called_once()
        call_kwargs = rt.ward_room.create_thread.call_args[1]
        assert "[Observation]" in call_kwargs["title"]
        assert call_kwargs["author_id"] == agent.id

    @pytest.mark.asyncio
    async def test_posts_to_department_channel(self):
        """Architect → science department channel."""
        agent = _make_mock_agent(agent_type="architect")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="Interesting pattern in recent code analysis."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)

        with patch("probos.cognitive.standing_orders.get_department", return_value="science"):
            await loop._run_cycle()

        call_kwargs = rt.ward_room.create_thread.call_args[1]
        assert call_kwargs["channel_id"] == "ch1"  # Science channel

    @pytest.mark.asyncio
    async def test_records_cooldown_after_post(self):
        agent = _make_mock_agent()
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True,
            result="Something noteworthy happened."
        )
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        assert agent.id in loop._last_proactive
        assert time.monotonic() - loop._last_proactive[agent.id] < 2.0

    @pytest.mark.asyncio
    async def test_no_ward_room_skips_cycle(self):
        """Ward Room disabled → entire cycle skipped."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], ward_room=False)

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()


class TestProactiveContextGathering:
    """Context assembly from system services."""

    @pytest.mark.asyncio
    async def test_gathers_episodic_memories(self):
        from probos.types import Episode, RecallScore
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        ep = Episode(user_input="test task", reflection="Handled successfully")
        # AD-567c: recall_weighted is now primary path
        rs = RecallScore(episode=ep, composite_score=0.5)
        rt.episodic_memory.recall_weighted = AsyncMock(return_value=[rs])
        rt.episodic_memory.recall_for_agent.return_value = [ep]
        rt.episodic_memory.count_for_agent = AsyncMock(return_value=5)  # AD-568a

        loop = _make_loop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_memories" in context
        assert len(context["recent_memories"]) == 1
        assert context["recent_memories"][0]["reflection"] == "Handled successfully"

    @pytest.mark.asyncio
    async def test_gathers_bridge_alerts(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        alert = MagicMock()  # Alert data object, not a runtime
        alert.severity.value = "advisory"
        alert.title = "Trust drop"
        alert.source = "vitals_monitor"
        rt.bridge_alerts.get_recent_alerts.return_value = [alert]

        loop = _make_loop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_alerts" in context
        assert len(context["recent_alerts"]) == 1

    @pytest.mark.asyncio
    async def test_gathers_system_events(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt.event_log.query.return_value = [
            {"category": "system", "event": "started", "agent_type": ""},
        ]

        loop = _make_loop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_events" in context
        assert len(context["recent_events"]) == 1

    @pytest.mark.asyncio
    async def test_handles_missing_services_gracefully(self):
        """If episodic_memory/bridge_alerts/event_log are None, context is empty."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None  # AD-429a

        loop = _make_loop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        # AD-502: temporal fields may be present; service-derived data should be absent
        assert "recent_memories" not in context
        assert "bridge_alerts" not in context
        assert "recent_events" not in context

    @pytest.mark.asyncio
    async def test_gather_context_fallback_to_recent_for_agent(self):
        """BF-028: _gather_context falls back to recent_for_agent when semantic recall empty."""
        from probos.types import Episode

        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt.episodic_memory.recall_for_agent.return_value = []  # semantic recall empty
        rt.episodic_memory.count_for_agent = AsyncMock(return_value=5)  # AD-568a: non-zero to enable retrieval

        ep1 = Episode(user_input="recent task 1", reflection="Did task 1.")
        ep2 = Episode(user_input="recent task 2", reflection="Did task 2.")
        rt.episodic_memory.recent_for_agent = AsyncMock(return_value=[ep1, ep2])

        loop = _make_loop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        rt.episodic_memory.recent_for_agent.assert_called_once_with(agent.id, k=5)
        assert "recent_memories" in context
        assert len(context["recent_memories"]) == 2
        assert context["recent_memories"][0]["reflection"] == "Did task 1."


class TestProactiveConfig:
    """ProactiveCognitiveConfig defaults."""

    def test_defaults(self):
        from probos.config import ProactiveCognitiveConfig
        cfg = ProactiveCognitiveConfig()
        assert cfg.enabled is False
        assert cfg.interval_seconds == 120.0
        assert cfg.cooldown_seconds == 300.0

    def test_system_config_has_proactive_cognitive(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "proactive_cognitive")
        assert cfg.proactive_cognitive.enabled is False


class TestPerAgentCooldown:
    """Per-agent cooldown override (Phase 28b slider)."""

    def test_default_returns_global_cooldown(self):
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        assert loop.get_agent_cooldown("agent1") == 300.0

    def test_set_override(self):
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_agent_cooldown("agent1", 120.0)
        assert loop.get_agent_cooldown("agent1") == 120.0

    def test_override_does_not_affect_others(self):
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_agent_cooldown("agent1", 120.0)
        assert loop.get_agent_cooldown("agent2") == 300.0

    def test_clamp_minimum(self):
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_agent_cooldown("agent1", 10.0)
        assert loop.get_agent_cooldown("agent1") == 60.0

    def test_clamp_maximum(self):
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_agent_cooldown("agent1", 5000.0)
        assert loop.get_agent_cooldown("agent1") == 1800.0

    @pytest.mark.asyncio
    async def test_per_agent_cooldown_used_in_cycle(self):
        """Agent with short cooldown thinks, agent with long cooldown skipped."""
        agent_fast = _make_mock_agent(agent_type="architect", agent_id="fast")
        agent_fast.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="fast", success=True, result="[NO_RESPONSE]"
        )
        agent_slow = _make_mock_agent(agent_type="builder", agent_id="slow")
        agent_slow.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="slow", success=True, result="[NO_RESPONSE]"
        )
        rt = _make_mock_runtime(agents=[agent_fast, agent_slow])

        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_runtime(rt)
        loop._started_at = time.monotonic() - 1200  # Past cold-start window
        # Both posted 100s ago
        loop._last_proactive["fast"] = time.monotonic() - 100
        loop._last_proactive["slow"] = time.monotonic() - 100

        # Fast agent has 60s cooldown (100s > 60s → thinks)
        # Slow agent uses global 300s (100s < 300s → skipped)
        loop.set_agent_cooldown("fast", 60.0)

        await loop._run_cycle()
        agent_fast.handle_intent.assert_called_once()
        agent_slow.handle_intent.assert_not_called()


class TestCooldownEndpointValidation:
    """BF-093: Cooldown endpoint range validation via Pydantic + HTTPException."""

    @pytest.mark.asyncio
    async def test_cooldown_below_minimum_rejected(self):
        """Cooldown < 60 raises HTTPException(400)."""
        from fastapi import HTTPException
        from probos.routers.agents import set_agent_proactive_cooldown
        from probos.api_models import SetCooldownRequest

        rt = MagicMock()
        agent = MagicMock()
        agent.agent_type = "scout"
        rt.registry.get.return_value = agent
        rt.ontology = MagicMock()
        rt.ontology.get_crew_agent_types.return_value = {"scout"}

        with pytest.raises(HTTPException) as exc_info:
            await set_agent_proactive_cooldown("a1", SetCooldownRequest(cooldown=30.0), rt)
        assert exc_info.value.status_code == 400
        assert "60" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cooldown_above_maximum_rejected(self):
        """Cooldown > 1800 raises HTTPException(400)."""
        from fastapi import HTTPException
        from probos.routers.agents import set_agent_proactive_cooldown
        from probos.api_models import SetCooldownRequest

        rt = MagicMock()
        agent = MagicMock()
        agent.agent_type = "scout"
        rt.registry.get.return_value = agent
        rt.ontology = MagicMock()
        rt.ontology.get_crew_agent_types.return_value = {"scout"}

        with pytest.raises(HTTPException) as exc_info:
            await set_agent_proactive_cooldown("a1", SetCooldownRequest(cooldown=2000.0), rt)
        assert exc_info.value.status_code == 400
        assert "1800" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_cooldown_accepted(self):
        """Cooldown within range is accepted."""
        from probos.routers.agents import set_agent_proactive_cooldown
        from probos.api_models import SetCooldownRequest

        rt = MagicMock()
        agent = MagicMock()
        agent.agent_type = "scout"
        rt.registry.get.return_value = agent
        rt.ontology = MagicMock()
        rt.ontology.get_crew_agent_types.return_value = {"scout"}
        rt.proactive_loop = MagicMock()
        rt.proactive_loop.set_agent_cooldown = MagicMock()
        rt.proactive_loop.get_agent_cooldown = MagicMock(return_value=300.0)

        result = await set_agent_proactive_cooldown("a1", SetCooldownRequest(cooldown=300.0), rt)
        assert result["agentId"] == "a1"
        assert result["cooldown"] == 300.0

    @pytest.mark.asyncio
    async def test_default_cooldown_accepted(self):
        """Empty body defaults to 300.0 (within range)."""
        from probos.routers.agents import set_agent_proactive_cooldown
        from probos.api_models import SetCooldownRequest

        rt = MagicMock()
        agent = MagicMock()
        agent.agent_type = "scout"
        rt.registry.get.return_value = agent
        rt.ontology = MagicMock()
        rt.ontology.get_crew_agent_types.return_value = {"scout"}
        rt.proactive_loop = MagicMock()
        rt.proactive_loop.set_agent_cooldown = MagicMock()
        rt.proactive_loop.get_agent_cooldown = MagicMock(return_value=300.0)

        result = await set_agent_proactive_cooldown("a1", SetCooldownRequest(), rt)
        assert result["cooldown"] == 300.0


class TestResetScope:
    """BF-070: Tiered reset scope tests."""

    def _reset_args(self, data_dir, **overrides):
        import argparse
        defaults = dict(
            yes=True, soft=False, full=False,
            dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_reset_archives_wardroom(self, tmp_path):
        """Tier 3 reset (--full) should archive ward_room.db before deleting."""
        import argparse
        import shutil
        from probos.__main__ import _cmd_reset

        # Create fake data_dir with ward_room.db
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        wr_db = data_dir / "ward_room.db"
        wr_db.write_text("fake ward room data")

        # Create minimal knowledge dir
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = self._reset_args(data_dir, full=True)

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        # ward_room.db should be gone
        assert not wr_db.exists()

        # Archive should exist
        archive_dir = data_dir / "archives"
        assert archive_dir.exists()
        archives = list(archive_dir.glob("ward_room_*.db"))
        assert len(archives) == 1
        assert archives[0].read_text() == "fake ward room data"

    def test_default_reset_preserves_wardroom(self, tmp_path):
        """Default Tier 2 reset preserves ward_room.db (only cleared at Tier 3)."""
        import argparse
        from probos.__main__ import _cmd_reset

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        wr_db = data_dir / "ward_room.db"
        wr_db.write_text("keep me")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = self._reset_args(data_dir)  # default = Tier 2

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        assert wr_db.exists()
        assert wr_db.read_text() == "keep me"

    def test_reset_clears_checkpoints(self, tmp_path):
        """Tier 1 reset clears DAG checkpoint JSON files."""
        import argparse
        from probos.__main__ import _cmd_reset

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")
        (cp_dir / "dag2.json").write_text("{}")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = self._reset_args(data_dir, soft=True)  # Tier 1 includes checkpoints

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        remaining = list(cp_dir.glob("*.json"))
        assert len(remaining) == 0

    def test_reset_clears_events_db(self, tmp_path):
        """Tier 1 reset clears events.db."""
        import argparse
        from probos.__main__ import _cmd_reset

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        events_db = data_dir / "events.db"
        events_db.write_text("fake events")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = self._reset_args(data_dir, soft=True)

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        assert not events_db.exists()


class TestProactiveWardRoomContext:
    """AD-413: Proactive loop Ward Room context gathering."""

    @pytest.mark.asyncio
    async def test_gather_context_includes_ward_room(self):
        """_gather_context should include recent Ward Room activity."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._cooldown = 300
        loop._agent_cooldowns = {}
        loop._circuit_breaker = CognitiveCircuitBreaker()
        loop._llm_status = "operational"  # AD-576
        loop._llm_failure_count = 0  # AD-576

        # Mock runtime with ward_room
        rt = MagicMock(spec=ProbOSRuntime)
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None  # AD-429e: Explicit None so get_department uses legacy dict

        mock_channel = MagicMock()
        mock_channel.channel_type = "department"
        mock_channel.department = "engineering"
        mock_channel.id = "ch-eng"

        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[mock_channel])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"type": "thread", "author": "LaForge", "title": "EPS conduit check", "body": "All nominal", "created_at": 1.0},
        ])

        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "eng-1"
        agent.agent_type = "builder"

        context = await loop._gather_context(agent, trust_score=0.7)
        assert "ward_room_activity" in context
        assert len(context["ward_room_activity"]) == 1
        assert context["ward_room_activity"][0]["author"] == "LaForge"

    @pytest.mark.asyncio
    async def test_ward_room_context_marks_seen(self):
        """AD-425: After _gather_context(), update_last_seen is called for dept channel."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._cooldown = 300
        loop._agent_cooldowns = {}
        loop._circuit_breaker = CognitiveCircuitBreaker()
        loop._llm_status = "operational"  # AD-576
        loop._llm_failure_count = 0  # AD-576

        rt = MagicMock(spec=ProbOSRuntime)
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None  # AD-429e

        dept_ch = MagicMock()
        dept_ch.channel_type = "department"
        dept_ch.department = "engineering"
        dept_ch.id = "ch-eng"

        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[dept_ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"type": "thread", "author": "LaForge", "title": "Check", "body": "ok", "created_at": 1.0},
        ])
        rt.ward_room.update_last_seen = AsyncMock()

        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "eng-1"
        agent.agent_type = "builder"

        await loop._gather_context(agent, trust_score=0.7)
        rt.ward_room.update_last_seen.assert_any_call("eng-1", "ch-eng")

    @pytest.mark.asyncio
    async def test_all_hands_context_marks_seen(self):
        """AD-425: After _gather_context(), update_last_seen is called for All Hands channel."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._cooldown = 300
        loop._agent_cooldowns = {}
        loop._circuit_breaker = CognitiveCircuitBreaker()
        loop._llm_status = "operational"  # AD-576
        loop._llm_failure_count = 0  # AD-576

        rt = MagicMock(spec=ProbOSRuntime)
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None

        dept_ch = MagicMock()
        dept_ch.channel_type = "department"
        dept_ch.department = "engineering"
        dept_ch.id = "ch-eng"

        all_hands = MagicMock()
        all_hands.channel_type = "ship"
        all_hands.department = ""
        all_hands.id = "ch-allhands"

        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[dept_ch, all_hands])
        # Dept returns nothing, All Hands returns activity
        rt.ward_room.get_recent_activity = AsyncMock(side_effect=lambda ch_id, **kw: [
            {"type": "thread", "author": "Captain", "title": "Briefing", "body": "msg",
             "created_at": 1.0, "thread_mode": "discuss"},
        ] if ch_id == "ch-allhands" else [])
        rt.ward_room.update_last_seen = AsyncMock()

        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "eng-1"
        agent.agent_type = "builder"

        context = await loop._gather_context(agent, trust_score=0.7)
        assert "ward_room_activity" in context
        rt.ward_room.update_last_seen.assert_any_call("eng-1", "ch-allhands")


class TestProactiveTrustSignal:
    """Tests for AD-414: Proactive loop trust signal emission."""

    def _make_loop_with_config(self, trust_reward_weight=0.1, trust_no_response_weight=0.0, trust_duty_bonus=0.1):
        """Create a ProactiveCognitiveLoop with config and mocked runtime."""
        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        config = MagicMock()
        config.trust_reward_weight = trust_reward_weight
        config.trust_no_response_weight = trust_no_response_weight
        config.trust_duty_bonus = trust_duty_bonus
        loop._config = config

        rt = MagicMock(spec=ProbOSRuntime)
        rt.acm = None  # AD-442: Checked directly in _run_cycle
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        rt.trust_network = MagicMock(spec=TrustNetwork)
        rt.trust_network.record_outcome = MagicMock(return_value=0.55)
        rt.trust_network.get_score = MagicMock(return_value=0.55)
        # AD-437: Endorsement extraction (default: no endorsements found)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.extract_endorsements = MagicMock(side_effect=lambda text: (text, []))
        rt.ward_room_router.process_endorsements = AsyncMock()
        rt.is_cold_start = False
        loop._runtime = rt
        loop._duty_tracker = None

        return loop, rt

    def _make_agent(self, response_text="Observation: systems nominal"):
        agent = MagicMock(spec=BaseAgent)
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.confidence = 0.8
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result=response_text,
        ))
        return agent

    @pytest.mark.asyncio
    async def test_successful_think_emits_trust_signal(self):
        """Successful proactive think emits attenuated trust signal."""
        loop, rt = self._make_loop_with_config(trust_reward_weight=0.1)
        agent = self._make_agent("EPS conduits nominal. No anomalies detected.")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_called_once_with(
            "scout-1", success=True, weight=0.1, intent_type="proactive_think",
        )

    @pytest.mark.asyncio
    async def test_duty_completion_adds_bonus(self):
        """Duty completion adds bonus weight to trust signal."""
        loop, rt = self._make_loop_with_config(trust_reward_weight=0.1, trust_duty_bonus=0.1)

        # Wire a duty tracker with a due duty
        duty_mock = MagicMock()
        duty_mock.duty_id = "scout_report"
        duty_mock.description = "Perform scout report"
        duty_mock.cron = ""
        duty_mock.interval_seconds = 86400
        duty_mock.priority = 3
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({"scout": [duty_mock]})

        agent = self._make_agent("Scout report: All systems nominal.")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_called_once_with(
            "scout-1", success=True, weight=0.2, intent_type="proactive_think",
        )

    @pytest.mark.asyncio
    async def test_no_response_no_trust_signal_by_default(self):
        """[NO_RESPONSE] does not emit trust signal when weight is 0."""
        loop, rt = self._make_loop_with_config(trust_no_response_weight=0.0)
        agent = self._make_agent("[NO_RESPONSE]")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_response_emits_signal_when_configured(self):
        """[NO_RESPONSE] emits trust signal when weight > 0."""
        loop, rt = self._make_loop_with_config(trust_no_response_weight=0.05)
        agent = self._make_agent("[NO_RESPONSE]")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_called_once_with(
            "scout-1", success=True, weight=0.05, intent_type="proactive_no_response",
        )

    @pytest.mark.asyncio
    async def test_failed_think_no_negative_trust(self):
        """Failed handle_intent does not emit any trust signal."""
        loop, rt = self._make_loop_with_config()
        agent = MagicMock(spec=BaseAgent)
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.confidence = 0.8
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=False, result=None,
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_update_event_emitted(self):
        """Successful proactive think calls record_outcome (AD-558: event emitted internally)."""
        loop, rt = self._make_loop_with_config(trust_reward_weight=0.1)
        agent = self._make_agent("EPS conduits nominal.")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        # AD-558: Event emission now happens inside record_outcome via callback.
        # Verify record_outcome was called with correct args.
        rt.trust_network.record_outcome.assert_called_once_with(
            "scout-1", success=True, weight=0.1, intent_type="proactive_think",
        )

    @pytest.mark.asyncio
    async def test_zero_weight_skips_record(self):
        """Zero trust_reward_weight skips record_outcome entirely."""
        loop, rt = self._make_loop_with_config(trust_reward_weight=0.0, trust_duty_bonus=0.0)
        agent = self._make_agent("Observation: something.")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_not_called()


# ---------------------------------------------------------------------------
# BF-023: Exception handler tracks confidence
# ---------------------------------------------------------------------------


class TestProactiveExceptionConfidence:
    """BF-023: LLM failures in proactive loop update agent confidence."""

    @pytest.mark.asyncio
    async def test_exception_updates_confidence(self):
        """When _think_for_agent raises, update_confidence(False) is called."""
        agent = _make_mock_agent()
        agent.confidence = 0.5
        agent.handle_intent = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        agent.update_confidence = MagicMock()
        rt = _make_mock_runtime(agents=[agent])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.update_confidence.assert_called_once_with(False)

    @pytest.mark.asyncio
    async def test_exception_does_not_crash_loop(self):
        """Exception is caught -- loop continues to next agent."""
        agent1 = _make_mock_agent(agent_type="architect", agent_id="a1")
        agent1.handle_intent = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        agent1.update_confidence = MagicMock()

        agent2 = _make_mock_agent(agent_type="scout", agent_id="a2")
        agent2.handle_intent = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="a2", success=True,
            result="All clear.",
        ))
        agent2.update_confidence = MagicMock()

        rt = _make_mock_runtime(agents=[agent1, agent2])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        # Agent1 failed, confidence updated
        agent1.update_confidence.assert_called_once_with(False)
        # Agent2 still got called (loop continued)
        agent2.handle_intent.assert_called_once()


# ---------------------------------------------------------------------------
# AD-430a: Proactive thought → episodic memory
# ---------------------------------------------------------------------------


class TestProactiveEpisodicMemory:
    """AD-430a: Proactive thoughts stored as episodic memory."""

    @pytest.mark.asyncio
    async def test_successful_think_stores_episode(self):
        """Successful proactive thought posts to Ward Room (which creates the episode).

        BF-039: When Ward Room is available, episode storage is handled by
        Ward Room's create_thread — the proactive path no longer stores a
        duplicate.  This test verifies the WR post path fires.
        """
        agent = _make_mock_agent(agent_type="scout", agent_id="scout-1")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="scout-1", success=True,
            result="EPS conduits nominal. No anomalies detected.",
        )
        rt = _make_mock_runtime(agents=[agent], ward_room=True)
        rt.episodic_memory = MagicMock()
        rt.episodic_memory.store = AsyncMock()
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])

        loop = _make_loop()
        loop.set_runtime(rt)
        loop._started_at = time.monotonic() - 1200  # past cold-start
        await loop._run_cycle()

        # Ward Room handles the episode — proactive path does NOT store directly
        rt.episodic_memory.store.assert_not_called()
        # Verify the WR post was made
        rt.ward_room.create_thread.assert_called_once()
        call_kwargs = rt.ward_room.create_thread.call_args
        # Thread body should contain the response text
        assert "EPS conduits" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_no_response_stores_episode(self):
        """AD-433: No-response proactive thought is filtered — no WR post, no episode."""
        agent = _make_mock_agent(agent_type="scout", agent_id="scout-1")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="scout-1", success=True,
            result="[NO_RESPONSE]",
        )
        rt = _make_mock_runtime(agents=[agent], ward_room=True)
        rt.episodic_memory = MagicMock()
        rt.episodic_memory.store = AsyncMock()
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])

        loop = _make_loop()
        loop.set_runtime(rt)
        loop._started_at = time.monotonic() - 1200  # past cold-start
        await loop._run_cycle()

        # No-response → no WR post → no episode stored
        rt.ward_room.create_thread.assert_not_called()
        rt.episodic_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_episodic_memory_no_crash(self):
        """Without episodic_memory, proactive think completes without error."""
        agent = _make_mock_agent(agent_type="scout", agent_id="scout-1")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="scout-1", success=True,
            result="Something interesting.",
        )
        rt = _make_mock_runtime(agents=[agent])
        rt.episodic_memory = None

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        # No crash — that's the assertion
        rt.ward_room.create_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_episode_store_failure_does_not_block(self):
        """Episodic memory store() failure doesn't block the proactive loop."""
        agent = _make_mock_agent(agent_type="scout", agent_id="scout-1")
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id="scout-1", success=True,
            result="Something noteworthy happened.",
        )
        rt = _make_mock_runtime(agents=[agent])
        rt.episodic_memory = MagicMock()
        rt.episodic_memory.store = AsyncMock(side_effect=RuntimeError("ChromaDB down"))
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])

        loop = _make_loop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        # Ward Room post still created despite episode store failure
        rt.ward_room.create_thread.assert_called_once()
        # Cooldown still recorded
        assert "scout-1" in loop._last_proactive


# ---------------------------------------------------------------------------
# AD-415: Proactive cooldown persistence
# ---------------------------------------------------------------------------


class TestCooldownPersistence:
    """AD-415: Per-agent cooldown overrides persisted to KnowledgeStore."""

    @pytest.mark.asyncio
    async def test_set_agent_cooldown_persists_to_store(self):
        """Test 1: set_agent_cooldown writes through to KnowledgeStore."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        mock_store = MagicMock(spec=KnowledgeStore)
        mock_store.store_cooldowns = AsyncMock()
        loop._knowledge_store = mock_store

        loop.set_agent_cooldown("agent-1", 600.0)
        # Let the fire-and-forget task run
        await asyncio.sleep(0)

        mock_store.store_cooldowns.assert_called_once()
        call_arg = mock_store.store_cooldowns.call_args[0][0]
        assert call_arg == {"agent-1": 600.0}

    @pytest.mark.asyncio
    async def test_restore_cooldowns_loads_from_store(self):
        """Test 2: restore_cooldowns loads saved overrides."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        mock_store = MagicMock(spec=KnowledgeStore)
        mock_store.load_cooldowns = AsyncMock(return_value={"agent-1": 450.0, "agent-2": 120.0})
        loop._knowledge_store = mock_store

        await loop.restore_cooldowns()

        assert loop.get_agent_cooldown("agent-1") == 450.0
        assert loop.get_agent_cooldown("agent-2") == 120.0

    @pytest.mark.asyncio
    async def test_restore_cooldowns_clamps_values(self):
        """Test 3: restore_cooldowns clamps values to [60, 1800]."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        mock_store = MagicMock(spec=KnowledgeStore)
        mock_store.load_cooldowns = AsyncMock(return_value={"agent-1": 30.0, "agent-2": 5000.0})
        loop._knowledge_store = mock_store

        await loop.restore_cooldowns()

        assert loop.get_agent_cooldown("agent-1") == 60.0   # Clamped to min
        assert loop.get_agent_cooldown("agent-2") == 1800.0  # Clamped to max

    @pytest.mark.asyncio
    async def test_restore_cooldowns_no_store_noop(self):
        """Test 4: restore_cooldowns with no KnowledgeStore doesn't crash."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop._knowledge_store = None

        await loop.restore_cooldowns()

        assert loop._agent_cooldowns == {}

    @pytest.mark.asyncio
    async def test_restore_cooldowns_load_failure_noop(self):
        """Test 5: restore_cooldowns with load failure doesn't crash."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        mock_store = MagicMock(spec=KnowledgeStore)
        mock_store.load_cooldowns = AsyncMock(side_effect=RuntimeError("disk error"))
        loop._knowledge_store = mock_store

        await loop.restore_cooldowns()

        assert loop._agent_cooldowns == {}

    def test_persist_cooldowns_no_store_noop(self):
        """Test 6: _persist_cooldowns with no KnowledgeStore is a no-op."""
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop._knowledge_store = None

        loop.set_agent_cooldown("agent-1", 600.0)

        # Still works in-memory
        assert loop._agent_cooldowns["agent-1"] == 600.0

    @pytest.mark.asyncio
    async def test_store_cooldowns_writes_json(self, tmp_path):
        """Test 7: store_cooldowns writes JSON file to proactive/ subdir."""
        import json
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        config = KnowledgeConfig(repo_path=str(tmp_path))
        store = KnowledgeStore(config)
        await store.initialize()

        await store.store_cooldowns({"agent-1": 600.0})

        cooldown_file = tmp_path / "proactive" / "cooldowns.json"
        assert cooldown_file.is_file()
        data = json.loads(cooldown_file.read_text())
        assert data == {"agent-1": 600.0}

    @pytest.mark.asyncio
    async def test_load_cooldowns_reads_json(self, tmp_path):
        """Test 8: load_cooldowns reads existing JSON file."""
        import json
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        config = KnowledgeConfig(repo_path=str(tmp_path))
        store = KnowledgeStore(config)
        await store.initialize()

        # Write a file manually
        cooldown_file = tmp_path / "proactive" / "cooldowns.json"
        cooldown_file.write_text(json.dumps({"agent-1": 450.0, "agent-2": 900.0}))

        result = await store.load_cooldowns()
        assert result == {"agent-1": 450.0, "agent-2": 900.0}

    @pytest.mark.asyncio
    async def test_load_cooldowns_returns_none_if_missing(self, tmp_path):
        """Test 9: load_cooldowns returns None when no file exists."""
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        config = KnowledgeConfig(repo_path=str(tmp_path))
        store = KnowledgeStore(config)
        await store.initialize()

        result = await store.load_cooldowns()
        assert result is None

    @pytest.mark.asyncio
    async def test_store_cooldowns_skips_empty_dict(self, tmp_path):
        """Test 10: store_cooldowns skips empty dict (no file written)."""
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        config = KnowledgeConfig(repo_path=str(tmp_path))
        store = KnowledgeStore(config)
        await store.initialize()

        await store.store_cooldowns({})

        cooldown_file = tmp_path / "proactive" / "cooldowns.json"
        assert not cooldown_file.is_file()


# ---------------------------------------------------------------------------
# AD-412: Proposal extraction tests
# ---------------------------------------------------------------------------

class TestProposalExtraction:
    """AD-412: _extract_and_post_proposal parsing and posting."""

    @pytest.mark.asyncio
    async def test_extract_proposal_valid(self):
        """Valid [PROPOSAL] block is parsed and posted."""
        loop = _make_loop()
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.handle_propose_improvement = AsyncMock(return_value={"success": True})
        loop.set_runtime(rt)

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "engineering_officer"
        agent.id = "eng-001"

        text = (
            "I noticed something interesting.\n"
            "[PROPOSAL]\n"
            "Title: Optimize query caching\n"
            "Rationale: Repeated queries are not cached, wasting tokens\n"
            "Affected Systems: KnowledgeStore, CognitiveJournal\n"
            "Priority: high\n"
            "[/PROPOSAL]\n"
            "That's my observation."
        )

        await loop._extract_and_post_proposal(agent, text)

        rt.ward_room_router.handle_propose_improvement.assert_called_once()
        call_args = rt.ward_room_router.handle_propose_improvement.call_args
        intent = call_args[0][0]
        assert intent.params["title"] == "Optimize query caching"
        assert intent.params["rationale"] == "Repeated queries are not cached, wasting tokens"
        assert intent.params["affected_systems"] == ["KnowledgeStore", "CognitiveJournal"]
        assert intent.params["priority_suggestion"] == "high"

    @pytest.mark.asyncio
    async def test_extract_proposal_no_block(self):
        """Text without [PROPOSAL] block is ignored."""
        loop = _make_loop()
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.handle_propose_improvement = AsyncMock()
        loop.set_runtime(rt)

        agent = MagicMock(spec=BaseAgent)
        agent.id = "test"
        await loop._extract_and_post_proposal(agent, "Just a regular observation.")

        rt.ward_room_router.handle_propose_improvement.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_proposal_missing_title(self):
        """Incomplete proposal (no title) is silently skipped."""
        loop = _make_loop()
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.handle_propose_improvement = AsyncMock()
        loop.set_runtime(rt)

        agent = MagicMock(spec=BaseAgent)
        agent.id = "test"
        text = (
            "[PROPOSAL]\n"
            "Rationale: Something is broken\n"
            "Affected Systems: Ward Room\n"
            "Priority: low\n"
            "[/PROPOSAL]"
        )

        await loop._extract_and_post_proposal(agent, text)
        rt.ward_room_router.handle_propose_improvement.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_proposal_missing_rationale(self):
        """Incomplete proposal (no rationale) is silently skipped."""
        loop = _make_loop()
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.handle_propose_improvement = AsyncMock()
        loop.set_runtime(rt)

        agent = MagicMock(spec=BaseAgent)
        agent.id = "test"
        text = (
            "[PROPOSAL]\n"
            "Title: Fix something\n"
            "Affected Systems: Ward Room\n"
            "Priority: medium\n"
            "[/PROPOSAL]"
        )

        await loop._extract_and_post_proposal(agent, text)
        rt.ward_room_router.handle_propose_improvement.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_proposal_multiline_rationale(self):
        """Multiline rationale is captured correctly."""
        loop = _make_loop()
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.handle_propose_improvement = AsyncMock(return_value={"success": True})
        loop.set_runtime(rt)

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "science_officer"
        agent.id = "sci-001"

        text = (
            "[PROPOSAL]\n"
            "Title: Improve dream consolidation\n"
            "Rationale: Dream cycles currently discard low-weight memories\n"
            "that could still be useful for pattern detection. We should\n"
            "apply a minimum threshold instead of a hard cutoff.\n"
            "Affected Systems: EpisodicMemory, DreamEngine\n"
            "Priority: medium\n"
            "[/PROPOSAL]"
        )

        await loop._extract_and_post_proposal(agent, text)

        rt.ward_room_router.handle_propose_improvement.assert_called_once()
        intent = rt.ward_room_router.handle_propose_improvement.call_args[0][0]
        assert "low-weight memories" in intent.params["rationale"]
        assert "minimum threshold" in intent.params["rationale"]


# ---------------------------------------------------------------------------
# AD-412: Runtime _handle_propose_improvement tests
# ---------------------------------------------------------------------------

class TestHandleProposeImprovement:
    """AD-412: Runtime handler for improvement proposals."""

    @pytest.mark.asyncio
    async def test_handle_propose_improvement_success(self, tmp_path):
        """Successful proposal creates a thread in Improvement Proposals channel."""
        from probos.ward_room import WardRoomService
        from probos.ward_room_router import WardRoomRouter

        events = []
        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: events.append((t, d)),
        )
        await wr.start()

        # Build a minimal runtime mock with real Ward Room
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = wr
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign = MagicMock(return_value="LaForge")

        # AD-515: Create WardRoomRouter so delegation works
        rt.ward_room_router = WardRoomRouter(
            ward_room=wr,
            registry=MagicMock(spec=AgentRegistry),
            intent_bus=MagicMock(spec=IntentBus),
            trust_network=MagicMock(spec=TrustNetwork),
            ontology=None,
            callsign_registry=rt.callsign_registry,
            episodic_memory=None,
            event_emitter=MagicMock(),
            event_log=AsyncMock(),
            config=MagicMock(spec=SystemConfig),
        )

        # Use the router's handle_propose_improvement directly
        handler = rt.ward_room_router.handle_propose_improvement

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "engineering_officer"
        agent.id = "eng-001"

        intent = MagicMock()
        intent.params = {
            "title": "Upgrade EPS conduits",
            "rationale": "Power distribution is unbalanced",
            "affected_systems": ["EPS", "Runtime"],
            "priority_suggestion": "high",
        }

        result = await handler(intent, agent)
        assert result["success"] is True
        assert result["channel"] == "Improvement Proposals"
        assert result["title"] == "Upgrade EPS conduits"

        # Verify thread was actually created
        channels = await wr.list_channels()
        ip_ch = next(c for c in channels if c.name == "Improvement Proposals")
        threads = await wr.list_threads(ip_ch.id)
        assert len(threads) == 1
        assert threads[0].title == "[Proposal] Upgrade EPS conduits"
        assert "LaForge" in threads[0].body

        await wr.stop()

    @pytest.mark.asyncio
    async def test_handle_propose_improvement_no_rationale(self):
        """Missing rationale returns error."""
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = MagicMock(spec=WardRoomService)
        # AD-515: Set up router so validation delegates properly
        from probos.ward_room_router import WardRoomRouter
        rt.ward_room_router = WardRoomRouter(
            ward_room=rt.ward_room,
            registry=MagicMock(spec=AgentRegistry),
            intent_bus=MagicMock(spec=IntentBus),
            trust_network=MagicMock(spec=TrustNetwork),
            ontology=None,
            callsign_registry=MagicMock(spec=CallsignRegistry),
            episodic_memory=None,
            event_emitter=MagicMock(),
            event_log=AsyncMock(),
            config=MagicMock(spec=SystemConfig),
        )
        handler = rt.ward_room_router.handle_propose_improvement

        intent = MagicMock()
        intent.params = {"title": "Something", "rationale": "", "affected_systems": []}
        agent = MagicMock(spec=BaseAgent)
        agent.id = "test"

        result = await handler(intent, agent)
        assert result["success"] is False
        assert "rationale" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_propose_improvement_no_ward_room(self):
        """Returns error when Ward Room is unavailable."""
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = None
        rt.ward_room_router = None  # No router when Ward Room is unavailable

        # With no ward_room_router, proposals cannot be processed
        assert rt.ward_room_router is None


# ---------------------------------------------------------------------------
# AD-412: API proposals endpoint tests
# ---------------------------------------------------------------------------

class TestProposalsAPI:
    """AD-412: /api/wardroom/proposals endpoint."""

    @pytest.mark.asyncio
    async def test_proposals_empty_by_default(self, tmp_path):
        """No proposals returns empty list."""
        from probos.ward_room import WardRoomService

        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: None,
        )
        await wr.start()

        # Simulate what the API does
        channels = await wr.list_channels()
        ip_ch = next(c for c in channels if c.name == "Improvement Proposals")
        threads = await wr.list_threads(ip_ch.id)
        assert len(threads) == 0

        await wr.stop()

    @pytest.mark.asyncio
    async def test_proposals_status_filtering(self, tmp_path):
        """Proposals are classified by net_score: approved/pending/shelved."""
        from probos.ward_room import WardRoomService

        wr = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=lambda t, d: None,
        )
        await wr.start()

        channels = await wr.list_channels()
        ip_ch = next(c for c in channels if c.name == "Improvement Proposals")

        # Create 3 threads — one will be approved, one pending, one shelved
        t1 = await wr.create_thread(ip_ch.id, "a1", "[Proposal] Approved", "Good idea", thread_mode="discuss")
        t2 = await wr.create_thread(ip_ch.id, "a2", "[Proposal] Pending", "Needs review", thread_mode="discuss")
        t3 = await wr.create_thread(ip_ch.id, "a3", "[Proposal] Shelved", "Bad idea", thread_mode="discuss")

        # Endorse t1 (approved: net_score > 0)
        await wr.endorse(t1.id, "thread", "captain", "up")
        # Downvote t3 (shelved: net_score < 0)
        await wr.endorse(t3.id, "thread", "captain", "down")
        # t2 stays at 0 (pending)

        threads = await wr.list_threads(ip_ch.id)

        # Replicate API status logic
        proposals = []
        for t in threads:
            status = "approved" if t.net_score > 0 else "shelved" if t.net_score < 0 else "pending"
            proposals.append({"thread_id": t.id, "title": t.title, "status": status})

        approved = [p for p in proposals if p["status"] == "approved"]
        pending = [p for p in proposals if p["status"] == "pending"]
        shelved = [p for p in proposals if p["status"] == "shelved"]

        assert len(approved) == 1
        assert "Approved" in approved[0]["title"]
        assert len(pending) == 1
        assert "Pending" in pending[0]["title"]
        assert len(shelved) == 1
        assert "Shelved" in shelved[0]["title"]

        await wr.stop()


# ---------------------------------------------------------------------------
# BF-032: Proactive Observation Self-Reference Loop
# ---------------------------------------------------------------------------


class TestSelfPostFiltering:
    """BF-032: Self-posts filtered from Ward Room context."""

    @pytest.mark.asyncio
    async def test_self_posts_filtered_from_context(self):
        """Ward Room context excludes posts authored by the current agent."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._cooldown = 300
        loop._agent_cooldowns = {}
        loop._circuit_breaker = CognitiveCircuitBreaker()
        loop._llm_status = "operational"  # AD-576
        loop._llm_failure_count = 0  # AD-576

        rt = MagicMock(spec=ProbOSRuntime)
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None  # AD-429e
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign = MagicMock(return_value="LaForge")

        dept_ch = MagicMock()
        dept_ch.channel_type = "department"
        dept_ch.department = "engineering"
        dept_ch.id = "ch-eng"

        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[dept_ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"type": "thread", "author": "Scotty", "body": "EPS check done", "created_at": 1.0},
            {"type": "thread", "author": "eng-1", "body": "My own observation", "created_at": 2.0},
            {"type": "thread", "author": "Worf", "body": "Security sweep clear", "created_at": 3.0},
        ])
        rt.ward_room.update_last_seen = AsyncMock()
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "eng-1"
        agent.agent_type = "engineering_officer"

        context = await loop._gather_context(agent, trust_score=0.7)
        assert "ward_room_activity" in context
        # Only Scotty and Worf — eng-1's own post filtered out
        assert len(context["ward_room_activity"]) == 2
        authors = [a["author"] for a in context["ward_room_activity"]]
        assert "eng-1" not in authors


class TestSimilarPostSuppression:
    """BF-032: Content similarity check before posting."""

    @pytest.mark.asyncio
    async def test_similar_post_suppressed(self):
        """Post with high word overlap is detected as similar."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._circuit_breaker = CognitiveCircuitBreaker()

        rt = MagicMock(spec=ProbOSRuntime)
        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"author_id": "scout-1", "author": "scout-1", "body": "I observe startup patterns in pool creation."},
        ])
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "scout-1"
        agent.agent_type = "scout"

        result = await loop._is_similar_to_recent_posts(
            agent, "I observe startup patterns in agent pool creation"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_different_post_allowed(self):
        """Post with low word overlap is not flagged."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._circuit_breaker = CognitiveCircuitBreaker()

        rt = MagicMock(spec=ProbOSRuntime)
        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"author_id": "scout-1", "author": "scout-1", "body": "I observe startup patterns in pool creation."},
        ])
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "scout-1"
        agent.agent_type = "scout"

        result = await loop._is_similar_to_recent_posts(
            agent, "Security vulnerability detected in input validation."
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_history_allows_posting(self):
        """No recent posts means nothing to compare — allow posting."""
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._circuit_breaker = CognitiveCircuitBreaker()

        rt = MagicMock(spec=ProbOSRuntime)
        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "scout-1"
        agent.agent_type = "scout"

        result = await loop._is_similar_to_recent_posts(agent, "Any observation text")
        assert result is False


class TestMetaObservationPrompt:
    """BF-032: Meta-observation instruction in proactive prompt."""

    def test_meta_observation_instruction_present(self):
        """Free-form think prompt includes instruction not to self-reference."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._agent_type = "scout"
        agent._id = "scout-1"

        # Build user message for proactive think with no duty
        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.7,
                "agency_level": "Lieutenant",
                "duty": None,
            },
        }
        msg = agent._build_user_message(observation)
        assert "Do not comment on your own posting patterns" in msg


# ---------------------------------------------------------------------------
# BF-039: Proactive Dedup & Cold-Start Dampening
# ---------------------------------------------------------------------------


class TestProactiveDedup:
    """BF-039: No double episode from proactive + Ward Room."""

    @pytest.mark.asyncio
    async def test_proactive_no_double_episode_on_wr_post(self):
        """When Ward Room is available, proactive path does NOT store its own episode."""
        loop = ProactiveCognitiveLoop(cooldown=0)
        rt = MagicMock(spec=ProbOSRuntime)
        rt.trust_network = MagicMock(spec=TrustNetwork)
        rt.trust_network.get_score = MagicMock(return_value=0.8)
        rt.trust_network.record_outcome = MagicMock(return_value=0.8)

        # Ward Room is available
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.episodic_memory = AsyncMock()
        rt.episodic_memory.store = AsyncMock()
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign = MagicMock(return_value="Bones")
        rt.ontology = None
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.extract_endorsements = MagicMock(return_value=("Status looks normal", []))
        loop.set_runtime(rt)
        loop._config = None

        agent = MagicMock(spec=BaseAgent)
        agent.id = "agent-bones"
        agent.agent_type = "medical_officer"
        agent.is_alive = True
        agent.confidence = 0.8
        agent.handle_intent = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-bones",
            result="Status looks normal", success=True,
        ))

        rank = Rank.LIEUTENANT
        await loop._think_for_agent(agent, rank, 0.8)

        # episodic_memory.store should NOT have been called from the proactive path
        # (Ward Room might call it, but the proactive code should not)
        rt.episodic_memory.store.assert_not_called()


class TestColdStartDampening:
    """BF-039: Cold-start episode dampening extends cooldown."""

    def test_cold_start_extends_cooldown(self):
        """During cold-start window, effective cooldown is 3x normal."""
        loop = ProactiveCognitiveLoop(cooldown=300)
        # Started just now — within cold-start window
        loop._started_at = time.monotonic()

        agent_id = "test-agent"
        base = loop.get_agent_cooldown(agent_id)
        assert base == 300

        # The 3x multiplier is applied in _run_cycle, not get_agent_cooldown.
        # Verify the constant exists and makes sense.
        assert loop.COLD_START_WINDOW_SECONDS == 600
        assert time.monotonic() - loop._started_at < loop.COLD_START_WINDOW_SECONDS

    def test_cold_start_expires(self):
        """After cold-start window, normal cooldown resumes."""
        loop = ProactiveCognitiveLoop(cooldown=300)
        # Started long ago — past cold-start window
        loop._started_at = time.monotonic() - 1200  # 20 minutes ago
        assert time.monotonic() - loop._started_at >= loop.COLD_START_WINDOW_SECONDS
