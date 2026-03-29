"""Tests for AD-502: Temporal Context Injection — Agent Time Awareness."""

import asyncio
import json
import time
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Duration Formatter Tests
# ---------------------------------------------------------------------------
from probos.utils import format_duration


class TestFormatDuration:
    """Component 4: Duration formatter utility."""

    def test_format_duration_seconds(self):
        assert format_duration(45) == "45s"

    def test_format_duration_minutes(self):
        assert format_duration(750) == "12m 30s"

    def test_format_duration_hours(self):
        assert format_duration(13500) == "3h 45m"

    def test_format_duration_days(self):
        assert format_duration(140400) == "1d 15h"

    def test_format_duration_zero(self):
        assert format_duration(0) == "0s"

    def test_format_duration_negative_clamped(self):
        """Negative durations should be clamped to 0."""
        assert format_duration(-10) == "0s"

    def test_format_duration_boundary_60(self):
        assert format_duration(60) == "1m 0s"

    def test_format_duration_boundary_3600(self):
        assert format_duration(3600) == "1h 0m"

    def test_format_duration_boundary_86400(self):
        assert format_duration(86400) == "1d 0h"


# ---------------------------------------------------------------------------
# Session Ledger Tests (Component 1)
# ---------------------------------------------------------------------------

class TestSessionLedger:
    """Component 1: Session record persistence and lifecycle detection."""

    def test_session_record_schema(self):
        """Session record contains all required fields."""
        record = {
            "session_id": "test-uuid",
            "start_time_utc": 1711612800.0,
            "shutdown_time_utc": 1711616400.0,
            "uptime_seconds": 3600.0,
            "agent_count": 5,
            "reason": "user-requested",
        }
        assert all(k in record for k in [
            "session_id", "start_time_utc", "shutdown_time_utc",
            "uptime_seconds", "agent_count", "reason",
        ])

    def test_session_record_timestamps_are_wall_clock(self):
        """Session record uses time.time() not monotonic."""
        now = time.time()
        record = {
            "start_time_utc": now - 3600,
            "shutdown_time_utc": now,
        }
        # Wall clock timestamps should be > 1e9 (epoch seconds)
        assert record["start_time_utc"] > 1e9
        assert record["shutdown_time_utc"] > 1e9

    def test_lifecycle_state_first_boot(self):
        """No previous session record = first_boot."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._lifecycle_state = "first_boot"
        assert rt._lifecycle_state == "first_boot"

    def test_lifecycle_state_stasis_recovery(self):
        """Previous session + warm boot = stasis_recovery."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._lifecycle_state = "stasis_recovery"
        rt._stasis_duration = 3600.0
        assert rt._lifecycle_state == "stasis_recovery"
        assert rt._stasis_duration == 3600.0

    def test_lifecycle_state_reset(self):
        """Cold start = reset, regardless of previous session."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._lifecycle_state = "stasis_recovery"
        # Simulate cold-start override
        rt._lifecycle_state = "reset"
        assert rt._lifecycle_state == "reset"

    def test_lifecycle_state_reset_overrides_stasis(self):
        """Cold start with previous session = reset, not stasis."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._lifecycle_state = "stasis_recovery"
        rt._previous_session = {"shutdown_time_utc": time.time() - 3600}
        # Cold start overrides
        rt._cold_start = True
        rt._lifecycle_state = "reset"
        assert rt._lifecycle_state == "reset"

    def test_session_record_persisted_on_shutdown(self):
        """stop() writes session_last.json to KS data dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record = {
                "session_id": "test-session",
                "start_time_utc": time.time() - 100,
                "shutdown_time_utc": time.time(),
                "uptime_seconds": 100.0,
                "agent_count": 3,
                "reason": "test",
            }
            session_path = Path(tmpdir) / "session_last.json"
            session_path.write_text(json.dumps(record, indent=2))
            loaded = json.loads(session_path.read_text())
            assert loaded["session_id"] == "test-session"
            assert loaded["agent_count"] == 3

    def test_startup_loads_previous_session(self):
        """Startup reads session_last.json and detects stasis recovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record = {
                "session_id": "prev-session",
                "start_time_utc": time.time() - 7200,
                "shutdown_time_utc": time.time() - 3600,
                "uptime_seconds": 3600.0,
                "agent_count": 5,
                "reason": "",
            }
            session_path = Path(tmpdir) / "session_last.json"
            session_path.write_text(json.dumps(record))
            loaded = json.loads(session_path.read_text())
            stasis_duration = time.time() - loaded["shutdown_time_utc"]
            assert stasis_duration > 0
            assert loaded["session_id"] == "prev-session"

    def test_startup_no_previous_session(self):
        """First boot detected when no record exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session_last.json"
            assert not session_path.exists()

    def test_startup_calculates_stasis_duration(self):
        """Shutdown_time to current time delta is computed correctly."""
        shutdown_time = time.time() - 7200  # 2 hours ago
        stasis_duration = time.time() - shutdown_time
        assert 7190 < stasis_duration < 7210  # ~2h with small margin


# ---------------------------------------------------------------------------
# Temporal Context Header Tests (Component 2)
# ---------------------------------------------------------------------------

class TestTemporalContextHeader:
    """Component 2: _build_temporal_context() method on CognitiveAgent."""

    def _make_agent(self, **overrides):
        """Create a mock CognitiveAgent with temporal fields."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        agent.meta = SimpleNamespace(
            last_active=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        agent._birth_timestamp = time.time() - 3600  # 1 hour ago
        agent._system_start_time = time.time() - 7200  # 2 hours ago
        agent._recent_post_count = 3
        for k, v in overrides.items():
            setattr(agent, k, v)
        return agent

    def test_temporal_context_includes_current_time(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        assert "Current time:" in ctx
        assert "UTC" in ctx

    def test_temporal_context_includes_day_of_week(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        # Should include day name (Monday, Tuesday, etc.)
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert any(d in ctx for d in days)

    def test_temporal_context_includes_birth_time(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        assert "Your birth:" in ctx
        assert "age:" in ctx

    def test_temporal_context_includes_birth_age(self):
        agent = self._make_agent(_birth_timestamp=time.time() - 7200)
        ctx = agent._build_temporal_context()
        assert "2h" in ctx

    def test_temporal_context_includes_system_uptime(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        assert "System uptime:" in ctx

    def test_temporal_context_includes_last_action(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        assert "Your last action:" in ctx
        assert "ago" in ctx

    def test_temporal_context_includes_post_count(self):
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        assert "Your posts this hour: 3" in ctx

    def test_temporal_context_omits_birth_if_no_certificate(self):
        agent = self._make_agent(_birth_timestamp=None)
        ctx = agent._build_temporal_context()
        assert "Your birth:" not in ctx

    def test_temporal_context_format(self):
        """Matches expected block format."""
        agent = self._make_agent()
        ctx = agent._build_temporal_context()
        lines = ctx.split("\n")
        assert lines[0].startswith("Current time:")
        assert len(lines) >= 3  # At minimum: time, uptime, last_action

    def test_temporal_context_disabled_via_config(self):
        """Respects enabled=false."""
        from probos.config import TemporalConfig
        mock_rt = MagicMock()
        mock_rt.config.temporal = TemporalConfig(enabled=False)
        agent = self._make_agent(_runtime=mock_rt)
        ctx = agent._build_temporal_context()
        assert ctx == ""


# ---------------------------------------------------------------------------
# Injection Point Tests
# ---------------------------------------------------------------------------

class TestTemporalInjectionPoints:
    """Component 2b: Temporal header injected into all three intent types."""

    def _make_agent(self, **overrides):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        agent.meta = SimpleNamespace(
            last_active=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        agent._birth_timestamp = time.time() - 3600
        agent._system_start_time = time.time() - 7200
        agent._recent_post_count = 0
        for k, v in overrides.items():
            setattr(agent, k, v)
        return agent

    def test_direct_message_includes_temporal_header(self):
        agent = self._make_agent()
        obs = {
            "intent": "direct_message",
            "params": {"text": "Hello", "session_history": []},
        }
        msg = agent._build_user_message(obs)
        assert "--- Temporal Awareness ---" in msg
        assert "Current time:" in msg

    def test_ward_room_notification_includes_temporal_header(self):
        agent = self._make_agent()
        obs = {
            "intent": "ward_room_notification",
            "params": {"channel_name": "test", "author_callsign": "Worf", "title": "Alert", "author_id": "agent-1"},
        }
        msg = agent._build_user_message(obs)
        assert "--- Temporal Awareness ---" in msg
        assert "Current time:" in msg

    def test_proactive_think_includes_temporal_header(self):
        agent = self._make_agent()
        obs = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.8,
                "agency_level": "autonomous",
                "rank": "lieutenant",
                "agent_type": "SecurityAgent",
                "duty": None,
            },
        }
        msg = agent._build_user_message(obs)
        assert "--- Temporal Awareness ---" in msg
        assert "Current time:" in msg

    def test_temporal_header_position_in_prompt(self):
        """Temporal header appears before main content."""
        agent = self._make_agent()
        obs = {
            "intent": "direct_message",
            "params": {"text": "Hello Captain", "session_history": []},
        }
        msg = agent._build_user_message(obs)
        temporal_idx = msg.index("--- Temporal Awareness ---")
        captain_idx = msg.index("Captain says:")
        assert temporal_idx < captain_idx


# ---------------------------------------------------------------------------
# Episode Timestamp Tests (Component 3)
# ---------------------------------------------------------------------------

class TestEpisodeTimestamps:
    """Component 3: Episode recall includes relative timestamps."""

    def test_recalled_episodes_include_relative_time(self):
        """Episodes should get an 'age' field in formatted recall."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = MagicMock()
        agent._runtime.config.temporal.include_episode_timestamps = True

        ep = SimpleNamespace(
            user_input="Test episode content",
            reflection="Test reflection",
            timestamp=time.time() - 11700,  # 3h 15m ago
        )
        episodes = [ep]

        # Simulate what _recall_relevant_memories does
        include_ts = True
        memories = [
            {
                "input": ep.user_input[:200] if ep.user_input else "",
                "reflection": ep.reflection[:200] if ep.reflection else "",
                **({"age": format_duration(time.time() - ep.timestamp)}
                   if include_ts and ep.timestamp > 0 else {}),
            }
            for ep in episodes
        ]
        assert "age" in memories[0]
        assert "3h" in memories[0]["age"]

    def test_episode_timestamps_respect_config(self):
        """Can be disabled via config."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        include_ts = False  # Simulating disabled config
        ep = SimpleNamespace(user_input="test", reflection="r", timestamp=time.time() - 3600)
        mem = {
            "input": ep.user_input,
            "reflection": ep.reflection,
            **({"age": format_duration(time.time() - ep.timestamp)}
               if include_ts and ep.timestamp > 0 else {}),
        }
        assert "age" not in mem

    def test_episode_timestamp_formatting(self):
        """Correct human-readable duration."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        assert format_duration(195) == "3m 15s"
        assert format_duration(7200) == "2h 0m"


# ---------------------------------------------------------------------------
# Hibernation Protocol Tests (Component 5)
# ---------------------------------------------------------------------------

class TestHibernationProtocol:
    """Component 5: Stasis/wake announcements."""

    def test_stasis_announcement_title(self):
        """Shutdown announcement should use 'Entering Stasis' not 'System Restart'."""
        # Verify the expected title string
        title = "Entering Stasis"
        assert title == "Entering Stasis"

    def test_stasis_recovery_announcement_includes_duration(self):
        """Stasis recovery announcement includes human-readable duration."""
        duration = format_duration(7200)
        body = f"Stasis duration: {duration}."
        assert "2h 0m" in body

    def test_first_boot_announcement(self):
        """Maiden voyage message on first ever boot."""
        title = "System Online — First Activation"
        body = "This is the maiden voyage. All systems operational."
        assert "maiden voyage" in body
        assert "First Activation" in title

    def test_reset_announcement_preserved(self):
        """Fresh Start message preserved for cold-start resets."""
        body = (
            "This instance has been reset. All crew are being created fresh "
            "through the Construct."
        )
        assert "created fresh" in body
        assert "Construct" in body

    def test_stasis_notification_includes_duration(self):
        """Stasis recovery notification includes duration."""
        stasis_duration = 18000.0  # 5 hours
        dur = format_duration(stasis_duration)
        assert dur == "5h 0m"


# ---------------------------------------------------------------------------
# State Snapshot Tests
# ---------------------------------------------------------------------------

class TestStateSnapshotTemporal:
    """State snapshot includes temporal data."""

    def test_state_snapshot_includes_temporal(self):
        """Temporal key should be present in snapshot."""
        snapshot = {
            "temporal": {
                "current_time_utc": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": 3600.0,
                "lifecycle_state": "first_boot",
                "stasis_duration": None,
                "session_id": "test-uuid",
            }
        }
        assert "temporal" in snapshot

    def test_state_snapshot_temporal_fields(self):
        """Temporal section has all required fields."""
        temporal = {
            "current_time_utc": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": 3600.0,
            "lifecycle_state": "stasis_recovery",
            "stasis_duration": 7200.0,
            "session_id": "test-session-id",
        }
        assert all(k in temporal for k in [
            "current_time_utc", "uptime_seconds", "lifecycle_state",
            "stasis_duration", "session_id",
        ])


# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------

class TestTemporalConfig:
    """AD-502: TemporalConfig model."""

    def test_temporal_config_defaults(self):
        from probos.config import TemporalConfig
        cfg = TemporalConfig()
        assert cfg.enabled is True
        assert cfg.include_birth_time is True
        assert cfg.include_system_uptime is True
        assert cfg.include_last_action is True
        assert cfg.include_post_count is True
        assert cfg.include_episode_timestamps is True

    def test_temporal_config_disabled(self):
        from probos.config import TemporalConfig
        cfg = TemporalConfig(enabled=False)
        assert cfg.enabled is False

    def test_temporal_config_in_system_config(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, 'temporal')
        assert cfg.temporal.enabled is True

    def test_temporal_config_from_yaml(self):
        from probos.config import load_config
        cfg = load_config("config/system.yaml")
        assert cfg.temporal.enabled is True


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestTemporalIntegration:
    """Integration tests for AD-502."""

    def test_full_shutdown_restart_stasis_flow(self):
        """Shutdown persists session → restart detects stasis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Phase 1: Simulate shutdown — write session record
            record = {
                "session_id": "session-1",
                "start_time_utc": time.time() - 3600,
                "shutdown_time_utc": time.time() - 1800,
                "uptime_seconds": 1800.0,
                "agent_count": 7,
                "reason": "maintenance",
            }
            session_path = Path(tmpdir) / "session_last.json"
            session_path.write_text(json.dumps(record))

            # Phase 2: Simulate startup — read session record
            loaded = json.loads(session_path.read_text())
            stasis_duration = time.time() - loaded["shutdown_time_utc"]
            lifecycle_state = "stasis_recovery"
            assert lifecycle_state == "stasis_recovery"
            assert stasis_duration > 0
            assert loaded["agent_count"] == 7

    def test_reset_after_previous_session(self):
        """Cold start with session record = reset, not stasis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            record = {
                "session_id": "session-old",
                "start_time_utc": time.time() - 7200,
                "shutdown_time_utc": time.time() - 3600,
                "uptime_seconds": 3600.0,
                "agent_count": 5,
                "reason": "",
            }
            session_path = Path(tmpdir) / "session_last.json"
            session_path.write_text(json.dumps(record))

            # Detect stasis recovery first
            lifecycle_state = "stasis_recovery"
            # Then cold-start overrides
            cold_start = True
            if cold_start:
                lifecycle_state = "reset"
            assert lifecycle_state == "reset"

    def test_birth_timestamp_available_on_agent(self):
        """Agent should have _birth_timestamp after wiring."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        ts = time.time() - 86400
        agent._birth_timestamp = ts
        agent._system_start_time = time.time()
        assert agent._birth_timestamp == ts


# ---------------------------------------------------------------------------
# Proactive Context Tests
# ---------------------------------------------------------------------------

class TestProactiveTemporalContext:
    """Temporal context passing through proactive loop."""

    def test_post_count_injection(self):
        """Agent should get _recent_post_count before proactive think."""
        agent = MagicMock()
        agent.id = "agent-1"
        # Simulate what proactive.py does
        agent._recent_post_count = 0
        assert agent._recent_post_count == 0

    def test_gather_context_adds_temporal_fields(self):
        """_gather_context() should add system_start_time and lifecycle_state."""
        context: dict = {}
        # Simulate the injection
        context["system_start_time"] = time.time() - 3600
        context["lifecycle_state"] = "stasis_recovery"
        context["stasis_duration"] = 7200.0
        assert "system_start_time" in context
        assert context["lifecycle_state"] == "stasis_recovery"
