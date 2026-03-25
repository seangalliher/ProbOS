"""Tests for Proactive Cognitive Loop (Phase 28b)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.crew_profile import Rank
from probos.earned_agency import can_think_proactively, agency_from_rank, AgencyLevel
from probos.proactive import ProactiveCognitiveLoop
from probos.types import IntentMessage, IntentResult


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
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        assert loop._task is not None
        await loop.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        await loop.stop()
        assert loop._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        loop = ProactiveCognitiveLoop()
        loop.set_runtime(MagicMock())
        await loop.start()
        task1 = loop._task
        await loop.start()
        assert loop._task is task1
        await loop.stop()


def _make_mock_agent(agent_type="architect", agent_id="a1", alive=True):
    """Create a mock crew agent."""
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.is_alive = alive
    agent.handle_intent = AsyncMock()
    agent.callsign = agent_type.title()
    return agent


def _make_mock_runtime(agents=None, trust_scores=None, ward_room=True):
    """Create a mock runtime with agents and services."""
    rt = MagicMock()

    if agents is None:
        agents = [_make_mock_agent()]
    rt.registry.all.return_value = agents

    # Trust scores: default 0.7 (Commander)
    if trust_scores is None:
        trust_scores = {a.id: 0.7 for a in agents}
    rt.trust_network.get_score = MagicMock(side_effect=lambda aid: trust_scores.get(aid, 0.5))

    # _is_crew_agent: True for all
    rt._is_crew_agent = MagicMock(return_value=True)

    # Ward Room
    if ward_room:
        rt.ward_room = MagicMock()
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
    rt.episodic_memory = MagicMock()
    rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])

    # Bridge alerts
    rt.bridge_alerts = MagicMock()
    rt.bridge_alerts.get_recent_alerts = MagicMock(return_value=[])

    # Event log
    rt.event_log = MagicMock()
    rt.event_log.query = AsyncMock(return_value=[])

    return rt


class TestProactiveCognitiveLoopCycle:
    """_run_cycle() — agent iteration and filtering."""

    @pytest.mark.asyncio
    async def test_skips_non_crew_agents(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        rt._is_crew_agent.return_value = False

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_dead_agents(self):
        agent = _make_mock_agent(alive=False)
        rt = _make_mock_runtime(agents=[agent])

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_ensign_agents(self):
        """Trust < 0.5 → Ensign → no proactive thought."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], trust_scores={agent.id: 0.3})

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        assert agent.id in loop._last_proactive
        assert time.monotonic() - loop._last_proactive[agent.id] < 2.0

    @pytest.mark.asyncio
    async def test_no_ward_room_skips_cycle(self):
        """Ward Room disabled → entire cycle skipped."""
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent], ward_room=False)

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        agent.handle_intent.assert_not_called()


class TestProactiveContextGathering:
    """Context assembly from system services."""

    @pytest.mark.asyncio
    async def test_gathers_episodic_memories(self):
        from probos.types import Episode
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        ep = Episode(user_input="test task", reflection="Handled successfully")
        rt.episodic_memory.recall_for_agent.return_value = [ep]

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "recent_memories" in context
        assert len(context["recent_memories"]) == 1
        assert context["recent_memories"][0]["reflection"] == "Handled successfully"

    @pytest.mark.asyncio
    async def test_gathers_bridge_alerts(self):
        agent = _make_mock_agent()
        rt = _make_mock_runtime(agents=[agent])
        alert = MagicMock()
        alert.severity.value = "advisory"
        alert.title = "Trust drop"
        alert.source = "vitals_monitor"
        rt.bridge_alerts.get_recent_alerts.return_value = [alert]

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert context == {}


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
        # Both posted 100s ago
        loop._last_proactive["fast"] = time.monotonic() - 100
        loop._last_proactive["slow"] = time.monotonic() - 100

        # Fast agent has 60s cooldown (100s > 60s → thinks)
        # Slow agent uses global 300s (100s < 300s → skipped)
        loop.set_agent_cooldown("fast", 60.0)

        await loop._run_cycle()
        agent_fast.handle_intent.assert_called_once()
        agent_slow.handle_intent.assert_not_called()


class TestResetScope:
    """AD-413: Fine-grained reset scope tests."""

    def test_reset_archives_wardroom(self, tmp_path):
        """probos reset should archive ward_room.db before deleting."""
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

        # Mock args
        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

        # Patch _load_config_with_fallback and _default_data_dir
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

    def test_reset_keeps_wardroom_with_flag(self, tmp_path):
        """--keep-wardroom should preserve ward_room.db."""
        import argparse
        from probos.__main__ import _cmd_reset

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        wr_db = data_dir / "ward_room.db"
        wr_db.write_text("keep me")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=True,
            config=None,
            data_dir=data_dir,
        )

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        assert wr_db.exists()
        assert wr_db.read_text() == "keep me"

    def test_reset_clears_checkpoints(self, tmp_path):
        """probos reset should clear DAG checkpoint JSON files."""
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

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

        from unittest.mock import patch as mock_patch
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with mock_patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with mock_patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        remaining = list(cp_dir.glob("*.json"))
        assert len(remaining) == 0

    def test_reset_clears_events_db(self, tmp_path):
        """probos reset should clear events.db."""
        import argparse
        from probos.__main__ import _cmd_reset

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        events_db = data_dir / "events.db"
        events_db.write_text("fake events")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

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

        # Mock runtime with ward_room
        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None

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

        agent = MagicMock()
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

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None

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

        agent = MagicMock()
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

        rt = MagicMock()
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

        agent = MagicMock()
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

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        rt.trust_network = MagicMock()
        rt.trust_network.record_outcome = MagicMock(return_value=0.55)
        loop._runtime = rt
        loop._duty_tracker = None

        return loop, rt

    def _make_agent(self, response_text="Observation: systems nominal"):
        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
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
        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=False, result=None,
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        rt.trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_trust_update_event_emitted(self):
        """Successful proactive think emits trust_update event."""
        events = []
        loop, rt = self._make_loop_with_config(trust_reward_weight=0.1)
        loop._on_event = lambda evt: events.append(evt)
        agent = self._make_agent("EPS conduits nominal.")

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        trust_events = [e for e in events if e["type"] == "trust_update"]
        assert len(trust_events) == 1
        assert trust_events[0]["data"]["source"] == "proactive"
        assert trust_events[0]["data"]["agent_id"] == "scout-1"
        assert trust_events[0]["data"]["weight"] == 0.1

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

        loop = ProactiveCognitiveLoop()
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

        loop = ProactiveCognitiveLoop()
        loop.set_runtime(rt)
        await loop._run_cycle()

        # Agent1 failed, confidence updated
        agent1.update_confidence.assert_called_once_with(False)
        # Agent2 still got called (loop continued)
        agent2.handle_intent.assert_called_once()
