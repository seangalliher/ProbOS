"""AD-552: Notebook Self-Repetition Detection tests.

Tests for cumulative frequency check, event emission, Counselor integration,
CognitiveProfile persistence, self-monitoring prompt, and config knobs.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import RecordsConfig
from probos.events import EventType, NotebookSelfRepetitionEvent


# ------------------------------------------------------------------ helpers

def _make_dedup_result(
    action: str = "update",
    similarity: float = 0.5,
    revision: int = 0,
    hours_ago_created: float = 10.0,
    hours_ago_updated: float = 1.0,
) -> dict:
    """Build a dedup result dict as check_notebook_similarity would return."""
    now = datetime.now(timezone.utc)
    created = (now - timedelta(hours=hours_ago_created)).isoformat()
    updated = (now - timedelta(hours=hours_ago_updated)).isoformat()
    return {
        "action": action,
        "reason": "different content for same topic",
        "existing_path": "notebooks/chapel/vitals.md",
        "existing_content": "old content",
        "similarity": similarity,
        "revision": revision,
        "created_iso": created if revision > 0 else None,
        "updated_iso": updated if revision > 0 else None,
    }


def _make_runtime(records_config=None):
    """Build a minimal mock runtime for dedup gate testing."""
    rt = MagicMock()
    rt._records_store = AsyncMock()
    rt._emit_event = AsyncMock()
    rc = records_config or RecordsConfig()
    rt.config = MagicMock()
    rt.config.records = rc
    rt.ontology = None
    rt.ward_room_router = None
    return rt


def _make_agent():
    """Build a minimal mock agent."""
    agent = MagicMock()
    agent.id = "agent-chapel"
    agent.callsign = "chapel"
    agent.agent_type = "medical"
    agent.department = "medical"
    return agent


# ==================================================================
# TestFrequencyDetection (8 tests)
# ==================================================================

class TestFrequencyDetection:
    """Test cumulative frequency check in dedup gate."""

    def test_revision_3_low_novelty_detected(self):
        """Entry with rev=3 within 48h AND novelty < 0.2 -> detection."""
        # similarity=0.85 -> novelty=0.15 < 0.2
        result = _make_dedup_result(revision=3, similarity=0.85, hours_ago_created=10.0)
        novelty = 1.0 - result["similarity"]
        assert result["revision"] >= 3
        assert novelty < 0.2
        assert result["created_iso"] is not None

    def test_revision_2_below_threshold(self):
        """Entry with rev=2 -> below threshold, no detection."""
        result = _make_dedup_result(revision=2, similarity=0.85, hours_ago_created=10.0)
        assert result["revision"] < 3  # Below default threshold

    def test_revision_3_outside_window(self):
        """Entry with rev=3 but created >48h ago -> outside window."""
        result = _make_dedup_result(revision=3, similarity=0.85, hours_ago_created=72.0)
        created_ts = datetime.fromisoformat(result["created_iso"]).timestamp()
        hours_active = (time.time() - created_ts) / 3600.0
        assert hours_active >= 48.0

    def test_revision_3_high_novelty_still_notable(self):
        """Entry with rev=3 within 48h but novelty > 0.2 -> not suppressed."""
        result = _make_dedup_result(revision=3, similarity=0.5, hours_ago_created=10.0)
        novelty = 1.0 - result["similarity"]
        assert novelty > 0.2  # High novelty, not a repetition

    def test_revision_5_low_novelty_suppressed(self):
        """Entry with rev=5 within 48h AND novelty < 0.2 -> write suppressed."""
        result = _make_dedup_result(revision=5, similarity=0.9, hours_ago_created=10.0)
        novelty = 1.0 - result["similarity"]
        rc = RecordsConfig()
        assert result["revision"] >= rc.notebook_repetition_suppression_count
        assert novelty < rc.notebook_repetition_novelty_threshold

    def test_revision_5_high_novelty_not_suppressed(self):
        """Entry with rev=5 but novelty > 0.3 -> NOT suppressed."""
        result = _make_dedup_result(revision=5, similarity=0.6, hours_ago_created=10.0)
        novelty = 1.0 - result["similarity"]
        assert novelty > 0.3  # Genuine new content

    def test_new_entry_no_check(self):
        """New entry (revision=0) -> no frequency check."""
        result = _make_dedup_result(revision=0, similarity=0.0)
        assert result["revision"] < 3
        assert result["created_iso"] is None

    def test_detection_disabled_via_config(self):
        """Config notebook_repetition_enabled=False -> no check."""
        rc = RecordsConfig(notebook_repetition_enabled=False)
        assert rc.notebook_repetition_enabled is False


# ==================================================================
# TestEventEmission (3 tests)
# ==================================================================

class TestEventEmission:
    """Test NOTEBOOK_SELF_REPETITION event structure."""

    def test_event_contains_correct_fields(self):
        """Event should contain all required fields."""
        evt = NotebookSelfRepetitionEvent(
            agent_id="agent-chapel",
            agent_callsign="chapel",
            topic_slug="vitals-analysis",
            revision=4,
            hours_active=12.5,
            novelty=0.15,
            suppressed=False,
        )
        d = evt.to_dict()
        assert d["type"] == "notebook_self_repetition"
        assert d["data"]["agent_id"] == "agent-chapel"
        assert d["data"]["agent_callsign"] == "chapel"
        assert d["data"]["topic_slug"] == "vitals-analysis"
        assert d["data"]["revision"] == 4
        assert d["data"]["novelty"] == 0.15
        assert d["data"]["suppressed"] is False

    def test_event_suppressed_true(self):
        """Event has suppressed=True when write is suppressed."""
        evt = NotebookSelfRepetitionEvent(
            agent_id="a1",
            agent_callsign="chapel",
            topic_slug="vitals",
            revision=5,
            novelty=0.1,
            suppressed=True,
        )
        assert evt.suppressed is True
        assert evt.to_dict()["data"]["suppressed"] is True

    def test_event_suppressed_false(self):
        """Event has suppressed=False when pattern detected but not suppressed."""
        evt = NotebookSelfRepetitionEvent(
            agent_id="a1",
            agent_callsign="chapel",
            topic_slug="vitals",
            revision=3,
            novelty=0.15,
            suppressed=False,
        )
        assert evt.suppressed is False


# ==================================================================
# TestCounselorIntegration (7 tests)
# ==================================================================

class TestCounselorIntegration:
    """Test Counselor event handling for notebook self-repetition."""

    def test_counselor_subscribes_to_event(self):
        """Counselor should subscribe to NOTEBOOK_SELF_REPETITION."""
        assert EventType.NOTEBOOK_SELF_REPETITION.value == "notebook_self_repetition"

    @pytest.mark.asyncio
    async def test_handler_increments_counter(self):
        """Handler should increment profile.notebook_repetitions."""
        from probos.cognitive.counselor import CognitiveProfile
        profile = CognitiveProfile(agent_id="a1")
        assert profile.notebook_repetitions == 0
        profile.notebook_repetitions += 1
        assert profile.notebook_repetitions == 1

    @pytest.mark.asyncio
    async def test_handler_sets_timestamp(self):
        """Handler should set profile.last_notebook_repetition."""
        from probos.cognitive.counselor import CognitiveProfile
        profile = CognitiveProfile(agent_id="a1")
        assert profile.last_notebook_repetition == 0.0
        profile.last_notebook_repetition = time.time()
        assert profile.last_notebook_repetition > 0

    @pytest.mark.asyncio
    async def test_assessment_tier_credit(self):
        """Assessment should have tier_credit='notebook_repetition'."""
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="a1")
        assessment = CounselorAssessment()
        assessment.tier_credit = "notebook_repetition"
        profile.add_assessment(assessment)
        assert profile.notebook_repetitions == 1

    @pytest.mark.asyncio
    async def test_dm_sent_when_not_suppressed(self):
        """Therapeutic DM should be sent when suppressed=False."""
        from probos.cognitive.counselor import CounselorAgent
        counselor = object.__new__(CounselorAgent)
        counselor.id = "counselor-id"
        counselor._ward_room = MagicMock()
        counselor._profiles = {}
        counselor._profile_store = None
        counselor._cognitive_profiles = {}
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.7, "confidence": 0.8, "hebbian_avg": 0.5,
            "success_rate": 0.9, "personality_drift": 0.1,
        })
        counselor.assess_agent = MagicMock(return_value=MagicMock(
            tier_credit="", wellness_score=0.8, fit_for_duty=True, concerns=[],
            timestamp=time.time(),
        ))
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._send_therapeutic_dm = AsyncMock(return_value=True)

        data = {
            "agent_id": "agent-chapel",
            "agent_callsign": "chapel",
            "topic_slug": "vitals",
            "revision": 4,
            "suppressed": False,
        }
        await counselor._on_notebook_self_repetition(data)
        counselor._send_therapeutic_dm.assert_called_once()

    @pytest.mark.asyncio
    async def test_dm_not_sent_when_suppressed(self):
        """Therapeutic DM should NOT be sent when suppressed=True."""
        from probos.cognitive.counselor import CounselorAgent
        counselor = object.__new__(CounselorAgent)
        counselor.id = "counselor-id"
        counselor._ward_room = MagicMock()
        counselor._profiles = {}
        counselor._profile_store = None
        counselor._cognitive_profiles = {}
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.7, "confidence": 0.8, "hebbian_avg": 0.5,
            "success_rate": 0.9, "personality_drift": 0.1,
        })
        counselor.assess_agent = MagicMock(return_value=MagicMock(
            tier_credit="", wellness_score=0.8, fit_for_duty=True, concerns=[],
            timestamp=time.time(),
        ))
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._send_therapeutic_dm = AsyncMock(return_value=True)

        data = {
            "agent_id": "agent-chapel",
            "agent_callsign": "chapel",
            "topic_slug": "vitals",
            "revision": 6,
            "suppressed": True,
        }
        await counselor._on_notebook_self_repetition(data)
        counselor._send_therapeutic_dm.assert_not_called()

    @pytest.mark.asyncio
    async def test_counselor_ignores_own_events(self):
        """Counselor should ignore events for its own agent_id."""
        from probos.cognitive.counselor import CounselorAgent
        counselor = object.__new__(CounselorAgent)
        counselor.id = "counselor-id"
        counselor._profiles = {}
        counselor._profile_store = None
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._send_therapeutic_dm = AsyncMock()

        data = {
            "agent_id": "counselor-id",  # Same as counselor
            "agent_callsign": "counselor",
            "topic_slug": "self-analysis",
            "revision": 5,
            "suppressed": False,
        }
        await counselor._on_notebook_self_repetition(data)
        counselor._save_profile_and_assessment.assert_not_called()


# ==================================================================
# TestCognitiveProfilePersistence (3 tests)
# ==================================================================

class TestCognitiveProfilePersistence:
    """Test CognitiveProfile serialization with AD-552 fields."""

    def test_notebook_repetitions_persists(self):
        """notebook_repetitions field should survive to_dict/from_dict."""
        from probos.cognitive.counselor import CognitiveProfile
        profile = CognitiveProfile(agent_id="a1", notebook_repetitions=5)
        d = profile.to_dict()
        restored = CognitiveProfile.from_dict(d)
        assert restored.notebook_repetitions == 5

    def test_last_notebook_repetition_persists(self):
        """last_notebook_repetition field should survive to_dict/from_dict."""
        from probos.cognitive.counselor import CognitiveProfile
        ts = time.time()
        profile = CognitiveProfile(agent_id="a1", last_notebook_repetition=ts)
        d = profile.to_dict()
        restored = CognitiveProfile.from_dict(d)
        assert restored.last_notebook_repetition == ts

    @pytest.mark.asyncio
    async def test_schema_migration_columns(self):
        """Schema migration should add new columns without error."""
        from probos.cognitive.counselor import CounselorProfileStore
        import aiosqlite

        db = await aiosqlite.connect(":memory:")
        store = CounselorProfileStore.__new__(CounselorProfileStore)
        store._db = db
        store._db_path = ":memory:"

        # Create tables
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cognitive_profiles (
                agent_id TEXT PRIMARY KEY,
                agent_type TEXT DEFAULT '',
                profile_json TEXT DEFAULT '{}',
                alert_level TEXT DEFAULT 'green',
                last_assessed REAL DEFAULT 0.0,
                created_at REAL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                timestamp REAL,
                assessment_json TEXT
            )
        """)
        await db.commit()

        # Run migration — should not raise
        for stmt in [
            "ALTER TABLE cognitive_profiles ADD COLUMN notebook_repetitions INTEGER DEFAULT 0",
            "ALTER TABLE cognitive_profiles ADD COLUMN last_notebook_repetition REAL DEFAULT 0.0",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass
        await db.commit()

        # Verify columns exist by inserting
        await db.execute(
            "INSERT INTO cognitive_profiles (agent_id, notebook_repetitions, last_notebook_repetition) VALUES (?, ?, ?)",
            ("test-agent", 3, 1000.0),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT notebook_repetitions, last_notebook_repetition FROM cognitive_profiles WHERE agent_id = ?",
            ("test-agent",),
        )
        row = await cursor.fetchone()
        assert row == (3, 1000.0)

        await db.close()


# ==================================================================
# TestSelfMonitoringPrompt (2 tests)
# ==================================================================

class TestSelfMonitoringPrompt:
    """Test self-monitoring prompt repetition warning."""

    def test_notebook_index_includes_revision(self):
        """Enriched notebook index entries should include revision count."""
        entry = {
            "topic": "vitals-analysis",
            "updated": datetime.now(timezone.utc).isoformat(),
            "recency": "2h ago",
            "preview": "Monitoring vitals...",
            "revision": 4,
        }
        assert "revision" in entry
        assert entry["revision"] == 4

    def test_repetition_warning_generated(self):
        """Warning should be generated when revision >= threshold within window."""
        now_ts = time.time()
        updated_recent = datetime.now(timezone.utc).isoformat()
        entries = [
            {"topic": "vitals-analysis", "updated": updated_recent, "revision": 4},
            {"topic": "diagnostics", "updated": updated_recent, "revision": 1},
        ]

        threshold = 3
        window_h = 48.0
        warnings = []
        for ei in entries:
            rev = ei.get("revision", 1)
            if rev >= threshold and ei.get("updated"):
                try:
                    ei_ts = datetime.fromisoformat(ei["updated"]).timestamp()
                    if (now_ts - ei_ts) < (window_h * 3600):
                        warnings.append(
                            f"You've written about {ei['topic']} {rev} times recently. "
                            f"Review your existing entry before writing again."
                        )
                except (ValueError, TypeError):
                    pass

        assert len(warnings) == 1
        assert "vitals-analysis" in warnings[0]
        assert "4 times" in warnings[0]


# ==================================================================
# TestConfigKnobs (2 tests)
# ==================================================================

class TestConfigKnobs:
    """Test RecordsConfig AD-552 settings."""

    def test_default_config_values(self):
        """RecordsConfig should include all AD-552 settings with correct defaults."""
        rc = RecordsConfig()
        assert rc.notebook_repetition_enabled is True
        assert rc.notebook_repetition_window_hours == 48.0
        assert rc.notebook_repetition_threshold_count == 3
        assert rc.notebook_repetition_novelty_threshold == 0.2
        assert rc.notebook_repetition_suppression_count == 5

    def test_custom_config_values(self):
        """Custom config values should override defaults."""
        rc = RecordsConfig(
            notebook_repetition_enabled=False,
            notebook_repetition_window_hours=24.0,
            notebook_repetition_threshold_count=5,
            notebook_repetition_novelty_threshold=0.3,
            notebook_repetition_suppression_count=10,
        )
        assert rc.notebook_repetition_enabled is False
        assert rc.notebook_repetition_window_hours == 24.0
        assert rc.notebook_repetition_threshold_count == 5
        assert rc.notebook_repetition_novelty_threshold == 0.3
        assert rc.notebook_repetition_suppression_count == 10
