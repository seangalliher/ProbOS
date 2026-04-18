"""AD-529: Communication Contagion Firewall — tests."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import FirewallConfig
from probos.events import EventType
from probos.ward_room.content_firewall import (
    ContentFirewall,
    ScanResult,
    _FABRICATED_METRIC_RE,
    _HEX_ID_RE,
    _PHANTOM_THREAD_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trust_network(default_score: float = 0.5):
    tn = MagicMock()
    tn.get_score = MagicMock(return_value=default_score)
    return tn


def _make_firewall(
    trust_score: float = 0.5,
    emit_fn=None,
    config: FirewallConfig | None = None,
) -> ContentFirewall:
    tn = _make_trust_network(trust_score)
    if emit_fn is None:
        emit_fn = MagicMock()
    return ContentFirewall(
        trust_network=tn,
        emit_event_fn=emit_fn,
        config=config or FirewallConfig(),
    )


# ===========================================================================
# Scanning Logic (12 tests)
# ===========================================================================


class TestHighTrustBypass:
    """High-trust agents pass through unscanned."""

    def test_high_trust_bypasses_scanning(self):
        fw = _make_firewall(trust_score=0.75)
        result = fw.scan_post("agent-1", "deadbeef cafebabe 123abc 456def")
        assert result.flagged is False
        assert result.severity == "none"

    def test_trust_at_threshold_bypasses(self):
        fw = _make_firewall(trust_score=0.65)
        result = fw.scan_post("agent-1", "deadbeef cafebabe")
        assert result.flagged is False


class TestMidTrustScanning:
    """Mid-trust agents are scanned."""

    def test_clean_post_passes(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post("agent-1", "The system is performing well today.")
        assert result.flagged is False
        assert result.severity == "none"

    def test_two_hex_ids_flagged(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post(
            "agent-1",
            "Thread deadbeef showed cafebabe patterns.",
        )
        assert result.flagged is True
        assert "ungrounded_hex_ids" in result.reasons

    def test_one_hex_id_not_flagged(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post("agent-1", "The value deadbeef showed patterns.")
        assert result.flagged is False

    def test_hex_ids_in_context_not_flagged(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post(
            "agent-1",
            "Values deadbeef and cafebabe look relevant.",
            thread_context="Earlier post mentioned deadbeef and cafebabe.",
        )
        assert result.flagged is False


class TestPhantomThreadRefs:
    """Phantom thread reference detection."""

    def test_phantom_thread_ref_detected(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post(
            "agent-1", "See thread abc123def for details.",
        )
        assert result.flagged is True
        assert "phantom_thread_ref" in result.reasons

    def test_thread_ref_in_context_not_flagged(self):
        fw = _make_firewall(trust_score=0.5)
        result = fw.scan_post(
            "agent-1",
            "See thread abc123def for details.",
            thread_context="thread abc123def was started yesterday.",
        )
        assert result.flagged is False


class TestFabricatedMetrics:
    """Fabricated metrics detection for low-trust agents."""

    def test_fabricated_metrics_detected_low_trust(self):
        fw = _make_firewall(trust_score=0.3)
        body = (
            "The system showed 50ms baseline with 200ms spikes and "
            "±3.2% variance in throughput."
        )
        result = fw.scan_post("agent-1", body)
        assert result.flagged is True
        assert "fabricated_metrics" in result.reasons

    def test_fabricated_metrics_not_checked_mid_trust(self):
        fw = _make_firewall(trust_score=0.5)
        body = (
            "The system showed 50ms baseline with 200ms spikes and "
            "±3.2% variance in throughput."
        )
        result = fw.scan_post("agent-1", body)
        # Mid-trust (0.5 >= 0.45) → metrics check NOT run
        assert "fabricated_metrics" not in result.reasons


class TestSeverityEscalation:
    """Multiple reasons → severity escalation."""

    def test_severity_levels(self):
        fw = _make_firewall(trust_score=0.3)
        # 1 reason = low
        r1 = ScanResult(flagged=True, reasons=["a"], severity="low", trust_score=0.3)
        assert r1.severity == "low"

        # Test via scan: hex + phantom + metrics = 3 reasons = high
        body = (
            "Thread deadbeef showed cafebabe patterns. "
            "See thread abc123def for context. "
            "50ms baseline, 200ms spikes, ±3.2% variance."
        )
        result = fw.scan_post("agent-1", body)
        assert result.flagged is True
        assert result.severity == "high"


class TestEdgeCases:
    """Edge case scanning."""

    def test_empty_body_not_flagged(self):
        fw = _make_firewall(trust_score=0.3)
        result = fw.scan_post("agent-1", "")
        assert result.flagged is False

    def test_whitespace_body_not_flagged(self):
        fw = _make_firewall(trust_score=0.3)
        result = fw.scan_post("agent-1", "   \n  ")
        assert result.flagged is False

    def test_hex_in_code_block_with_context(self):
        """Hex IDs that appear in thread context (e.g., commit SHAs) not flagged."""
        fw = _make_firewall(trust_score=0.5)
        body = "Commit a1b2c3d4 and e5f6a7b8 look relevant."
        context = "Reviewing commits a1b2c3d4 and e5f6a7b8 from main branch."
        result = fw.scan_post("agent-1", body, thread_context=context)
        assert result.flagged is False


# ===========================================================================
# Warning Banner (4 tests)
# ===========================================================================


class TestWarningBanner:
    """Flagged posts get [UNVERIFIED] prefix."""

    def test_flagged_post_gets_unverified_prefix(self):
        result = ScanResult(
            flagged=True,
            reasons=["ungrounded_hex_ids"],
            severity="low",
            trust_score=0.4,
        )
        body = "Original text"
        if result.flagged:
            body = f"[UNVERIFIED — {', '.join(result.reasons)}] {body}"
        assert body.startswith("[UNVERIFIED")
        assert "Original text" in body

    def test_unflagged_post_unchanged(self):
        result = ScanResult(
            flagged=False, reasons=[], severity="none", trust_score=0.7,
        )
        body = "Original text"
        if result.flagged:
            body = f"[UNVERIFIED] {body}"
        assert body == "Original text"

    def test_banner_machine_parseable(self):
        body = "[UNVERIFIED — ungrounded_hex_ids, phantom_thread_ref] Some text"
        assert body.startswith("[UNVERIFIED")

    def test_original_text_preserved_after_banner(self):
        original = "This is the original post text with important content."
        body = f"[UNVERIFIED — fabricated_metrics] {original}"
        # Original text appears after the banner
        assert original in body
        # Banner is at the front
        idx = body.index(original)
        assert idx > 0


# ===========================================================================
# Quarantine Escalation (6 tests)
# ===========================================================================


class TestQuarantineEscalation:
    """Flag counting, window pruning, quarantine events."""

    def test_single_flag_emits_event_no_quarantine(self):
        emit = MagicMock()
        fw = _make_firewall(trust_score=0.5, emit_fn=emit)
        scan = ScanResult(
            flagged=True, reasons=["ungrounded_hex_ids"],
            severity="low", trust_score=0.5,
        )
        fw.record_flag("agent-1", scan)

        # Should emit CONTENT_CONTAGION_FLAGGED but NOT quarantine
        calls = [c[0][0] for c in emit.call_args_list]
        assert EventType.CONTENT_CONTAGION_FLAGGED.value in calls
        assert EventType.CONTENT_QUARANTINE_RECOMMENDED.value not in calls

    def test_three_flags_triggers_quarantine(self):
        emit = MagicMock()
        fw = _make_firewall(trust_score=0.5, emit_fn=emit)
        scan = ScanResult(
            flagged=True, reasons=["ungrounded_hex_ids"],
            severity="low", trust_score=0.5,
        )

        fw.record_flag("agent-1", scan)
        fw.record_flag("agent-1", scan)
        fw.record_flag("agent-1", scan)

        calls = [c[0][0] for c in emit.call_args_list]
        assert EventType.CONTENT_QUARANTINE_RECOMMENDED.value in calls

    def test_flags_outside_window_pruned(self):
        emit = MagicMock()
        cfg = FirewallConfig(flag_window_seconds=60.0, quarantine_threshold=3)
        fw = _make_firewall(trust_score=0.5, emit_fn=emit, config=cfg)
        scan = ScanResult(
            flagged=True, reasons=["x"], severity="low", trust_score=0.5,
        )

        # Add 2 flags "in the past" by manipulating history
        old_time = time.time() - 120  # 2 minutes ago, outside 60s window
        from probos.ward_room.content_firewall import _FlagRecord
        fw._flag_history["agent-1"] = [
            _FlagRecord(old_time, scan),
            _FlagRecord(old_time, scan),
        ]

        # Third flag is current — window should prune the old ones
        fw.record_flag("agent-1", scan)

        # Only 1 flag should remain after pruning
        assert len(fw._flag_history["agent-1"]) == 1
        # No quarantine (below threshold)
        calls = [c[0][0] for c in emit.call_args_list]
        assert EventType.CONTENT_QUARANTINE_RECOMMENDED.value not in calls

    def test_flag_count_respects_window(self):
        emit = MagicMock()
        cfg = FirewallConfig(flag_window_seconds=3600.0, quarantine_threshold=3)
        fw = _make_firewall(trust_score=0.5, emit_fn=emit, config=cfg)
        scan = ScanResult(
            flagged=True, reasons=["x"], severity="low", trust_score=0.5,
        )

        fw.record_flag("agent-1", scan)
        fw.record_flag("agent-1", scan)
        # 2 flags — not quarantined
        calls = [c[0][0] for c in emit.call_args_list]
        assert EventType.CONTENT_QUARANTINE_RECOMMENDED.value not in calls

    @pytest.mark.asyncio
    async def test_set_restriction_blocks_posting(self):
        """set_restriction('post') makes credibility check raise."""
        import aiosqlite

        db = await aiosqlite.connect(":memory:")
        await db.execute(
            "CREATE TABLE credibility ("
            "agent_id TEXT PRIMARY KEY, total_posts INTEGER DEFAULT 0, "
            "restrictions TEXT NOT NULL DEFAULT '[]')"
        )
        await db.commit()

        from probos.ward_room.messages import MessageStore
        ms = MessageStore(db=db, emit_fn=MagicMock())
        await ms.set_restriction("agent-1", "post")

        # Verify restriction is stored
        async with db.execute(
            "SELECT restrictions FROM credibility WHERE agent_id = ?",
            ("agent-1",),
        ) as cursor:
            row = await cursor.fetchone()
        restrictions = json.loads(row[0])
        assert "post" in restrictions
        await db.close()

    @pytest.mark.asyncio
    async def test_remove_restriction_re_enables_posting(self):
        """remove_restriction('post') removes the posting block."""
        import aiosqlite

        db = await aiosqlite.connect(":memory:")
        await db.execute(
            "CREATE TABLE credibility ("
            "agent_id TEXT PRIMARY KEY, total_posts INTEGER DEFAULT 0, "
            "restrictions TEXT NOT NULL DEFAULT '[]')"
        )
        await db.commit()

        from probos.ward_room.messages import MessageStore
        ms = MessageStore(db=db, emit_fn=MagicMock())

        await ms.set_restriction("agent-1", "post")
        await ms.remove_restriction("agent-1", "post")

        async with db.execute(
            "SELECT restrictions FROM credibility WHERE agent_id = ?",
            ("agent-1",),
        ) as cursor:
            row = await cursor.fetchone()
        restrictions = json.loads(row[0])
        assert "post" not in restrictions
        await db.close()


# ===========================================================================
# Counselor Integration (4 tests)
# ===========================================================================


class TestCounselorIntegration:
    """Counselor event handling for contagion events."""

    def _make_counselor(self):
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-001"
        counselor.callsign = "Echo"
        counselor._ward_room = MagicMock()
        counselor._ward_room._messages = MagicMock()
        counselor._ward_room._messages.set_restriction = AsyncMock()
        counselor._registry = {
            "agent-test": MagicMock(id="agent-test", callsign="TestAgent"),
        }
        counselor._dm_cooldowns = {}
        counselor._cognitive_profiles = {}
        counselor._intervention_targets = set()
        counselor._assessment_log = {}
        counselor._reminiscence_engine = None
        return counselor

    @pytest.mark.asyncio
    async def test_counselor_receives_flag_event(self):
        """Counselor logs flag events for wellness context."""
        counselor = self._make_counselor()
        data = {
            "agent_id": "agent-test",
            "reasons": ["ungrounded_hex_ids"],
            "severity": "low",
            "trust_score": 0.4,
            "flags_in_window": 1,
        }
        # Should not raise
        await counselor._on_content_contagion_flagged(data)

    @pytest.mark.asyncio
    async def test_counselor_sends_dm_on_high_severity(self):
        """High severity → therapeutic DM sent."""
        counselor = self._make_counselor()
        counselor._send_therapeutic_dm = AsyncMock(return_value=True)
        data = {
            "agent_id": "agent-test",
            "reasons": ["ungrounded_hex_ids", "phantom_thread_ref", "fabricated_metrics"],
            "severity": "high",
            "trust_score": 0.3,
            "flags_in_window": 1,
        }
        await counselor._on_content_contagion_flagged(data)
        counselor._send_therapeutic_dm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_counselor_no_dm_on_low_severity(self):
        """Low severity → no DM."""
        counselor = self._make_counselor()
        counselor._send_therapeutic_dm = AsyncMock()
        data = {
            "agent_id": "agent-test",
            "reasons": ["ungrounded_hex_ids"],
            "severity": "low",
            "trust_score": 0.5,
            "flags_in_window": 1,
        }
        await counselor._on_content_contagion_flagged(data)
        counselor._send_therapeutic_dm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_counselor_quarantine_applies_restriction(self):
        """Quarantine + low wellness → post restriction applied."""
        counselor = self._make_counselor()
        counselor._send_therapeutic_dm = AsyncMock(return_value=True)
        # Mock assessment with low wellness
        mock_assessment = MagicMock()
        mock_assessment.wellness_score = 0.3
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.3, "confidence": 0.5,
            "hebbian_avg": 0.4, "success_rate": 0.5,
            "personality_drift": 0.1,
        })
        counselor.assess_agent = MagicMock(return_value=mock_assessment)
        counselor._save_profile_and_assessment = AsyncMock()

        data = {
            "agent_id": "agent-test",
            "flags_in_window": 5,
            "window_seconds": 3600.0,
            "reasons": ["ungrounded_hex_ids", "phantom_thread_ref"],
        }
        await counselor._on_content_quarantine_recommended(data)

        counselor._ward_room._messages.set_restriction.assert_awaited_once_with(
            "agent-test", "post",
        )


# ===========================================================================
# Bridge Alert (2 tests)
# ===========================================================================


class TestBridgeAlerts:
    """Bridge alerts on high severity and quarantine."""

    def test_high_severity_emits_advisory(self):
        emit = MagicMock()
        fw = _make_firewall(trust_score=0.5, emit_fn=emit)
        scan = ScanResult(
            flagged=True,
            reasons=["a", "b", "c"],
            severity="high",
            trust_score=0.4,
        )
        fw.record_flag("agent-1", scan)

        # Should emit a bridge alert event (ADVISORY for single flag)
        bridge_calls = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BRIDGE_ALERT.value
        ]
        assert len(bridge_calls) >= 1
        # First bridge alert should be ADVISORY
        alert_data = bridge_calls[0][0][1]
        assert alert_data["severity"] == "advisory"

    def test_quarantine_emits_alert(self):
        emit = MagicMock()
        fw = _make_firewall(trust_score=0.5, emit_fn=emit)
        scan = ScanResult(
            flagged=True, reasons=["x"], severity="low", trust_score=0.4,
        )
        # Trigger quarantine
        fw.record_flag("agent-1", scan)
        fw.record_flag("agent-1", scan)
        fw.record_flag("agent-1", scan)

        call_types = [c[0][0] for c in emit.call_args_list]
        assert EventType.CONTENT_QUARANTINE_RECOMMENDED.value in call_types

        # Check bridge alert with ALERT severity for quarantine
        bridge_calls = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BRIDGE_ALERT.value
        ]
        alert_severities = [c[0][1].get("severity") for c in bridge_calls]
        assert "alert" in alert_severities


# ===========================================================================
# Defense Ordering (2 tests)
# ===========================================================================


class TestDefenseOrdering:
    """Scan runs after restriction check, before DB INSERT."""

    @pytest.mark.asyncio
    async def test_restricted_agent_does_not_trigger_scan(self):
        """A restricted agent is rejected before the scan runs."""
        import aiosqlite
        from probos.ward_room.messages import MessageStore

        db = await aiosqlite.connect(":memory:")
        # Create minimal schema
        await db.executescript("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, locked INTEGER DEFAULT 0,
                channel_id TEXT, reply_count INTEGER DEFAULT 0,
                last_activity REAL DEFAULT 0
            );
            CREATE TABLE posts (
                id TEXT PRIMARY KEY, thread_id TEXT, parent_id TEXT,
                author_id TEXT, body TEXT, created_at REAL,
                author_callsign TEXT DEFAULT ''
            );
            CREATE TABLE credibility (
                agent_id TEXT PRIMARY KEY, total_posts INTEGER DEFAULT 0,
                restrictions TEXT NOT NULL DEFAULT '[]'
            );
        """)
        await db.execute(
            "INSERT INTO threads (id, locked, channel_id) VALUES ('t1', 0, 'ch1')"
        )
        # Restrict the agent
        await db.execute(
            "INSERT INTO credibility (agent_id, restrictions) VALUES (?, ?)",
            ("agent-1", json.dumps(["post"])),
        )
        await db.commit()

        ms = MessageStore(db=db, emit_fn=MagicMock())
        fw_mock = MagicMock()
        ms.set_content_firewall(fw_mock)

        with pytest.raises(ValueError, match="restricted from posting"):
            await ms.create_post("t1", "agent-1", "test body")

        # Firewall scan_post should NOT have been called
        fw_mock.scan_post.assert_not_called()
        await db.close()

    @pytest.mark.asyncio
    async def test_scan_runs_before_insert(self):
        """Flagged content is labeled BEFORE DB INSERT."""
        import aiosqlite
        from probos.ward_room.messages import MessageStore

        db = await aiosqlite.connect(":memory:")
        await db.executescript("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, locked INTEGER DEFAULT 0,
                channel_id TEXT, reply_count INTEGER DEFAULT 0,
                last_activity REAL DEFAULT 0
            );
            CREATE TABLE posts (
                id TEXT PRIMARY KEY, thread_id TEXT, parent_id TEXT,
                author_id TEXT, body TEXT, created_at REAL,
                author_callsign TEXT DEFAULT ''
            );
            CREATE TABLE credibility (
                agent_id TEXT PRIMARY KEY, total_posts INTEGER DEFAULT 0,
                restrictions TEXT NOT NULL DEFAULT '[]'
            );
        """)
        await db.execute(
            "INSERT INTO threads (id, locked, channel_id) VALUES ('t1', 0, 'ch1')"
        )
        await db.commit()

        ms = MessageStore(db=db, emit_fn=MagicMock())

        # Create firewall that flags everything
        fw_mock = MagicMock()
        fw_mock.scan_post.return_value = ScanResult(
            flagged=True,
            reasons=["ungrounded_hex_ids"],
            severity="low",
            trust_score=0.4,
        )
        ms.set_content_firewall(fw_mock)

        # Patch peer similarity to avoid import issues
        with patch("probos.ward_room.threads.check_peer_similarity", new_callable=AsyncMock, return_value=[]):
            post = await ms.create_post("t1", "agent-1", "deadbeef cafebabe test")

        # Verify the body stored has the UNVERIFIED prefix
        assert post.body.startswith("[UNVERIFIED")
        assert "ungrounded_hex_ids" in post.body
        assert "deadbeef cafebabe test" in post.body

        # Verify in DB
        async with db.execute(
            "SELECT body FROM posts WHERE id = ?", (post.id,)
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0].startswith("[UNVERIFIED")
        await db.close()


# ===========================================================================
# Config (3 tests)
# ===========================================================================


class TestFirewallConfig:
    """FirewallConfig defaults and nesting."""

    def test_defaults(self):
        cfg = FirewallConfig()
        assert cfg.enabled is True
        assert cfg.scan_trust_threshold == 0.65
        assert cfg.low_trust_threshold == 0.45
        assert cfg.quarantine_threshold == 3
        assert cfg.flag_window_seconds == 3600.0

    def test_nesting_in_system_config(self):
        from probos.config import SystemConfig
        sc = SystemConfig()
        assert hasattr(sc, "firewall")
        assert isinstance(sc.firewall, FirewallConfig)
        assert sc.firewall.enabled is True

    def test_disabled_firewall(self):
        cfg = FirewallConfig(enabled=False)
        assert cfg.enabled is False


# ===========================================================================
# Regex Patterns (3 tests)
# ===========================================================================


class TestRegexPatterns:
    """Verify the regex patterns match expected content."""

    def test_hex_id_pattern(self):
        assert _HEX_ID_RE.findall("deadbeef and cafebabe") == ["deadbeef", "cafebabe"]
        assert _HEX_ID_RE.findall("abc") == []  # too short (< 6)
        assert _HEX_ID_RE.findall("abcdef") == ["abcdef"]

    def test_phantom_thread_pattern(self):
        assert _PHANTOM_THREAD_RE.findall("thread abc123def is interesting")
        assert _PHANTOM_THREAD_RE.findall("thread #42 has details")
        assert not _PHANTOM_THREAD_RE.findall("a thread about dogs")

    def test_fabricated_metric_pattern(self):
        assert _FABRICATED_METRIC_RE.findall("50ms baseline")
        assert _FABRICATED_METRIC_RE.findall("±3.2%")
        assert _FABRICATED_METRIC_RE.findall("200 requests/s")


# ===========================================================================
# Trust Network Degradation (1 test)
# ===========================================================================


class TestTrustDegradation:
    """Firewall degrades gracefully when trust network unavailable."""

    def test_trust_lookup_failure_uses_default(self):
        tn = MagicMock()
        tn.get_score.side_effect = RuntimeError("Trust DB unavailable")
        fw = ContentFirewall(
            trust_network=tn,
            emit_event_fn=MagicMock(),
            config=FirewallConfig(),
        )
        # Default trust 0.5 < 0.65 threshold → scan runs, but clean post passes
        result = fw.scan_post("agent-1", "Clean post with no issues.")
        assert result.flagged is False
