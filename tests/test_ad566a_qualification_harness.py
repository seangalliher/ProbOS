"""AD-566a: Qualification Test Harness — 19 tests.

Tests cover D1 (core types), D2 (store), D3 (harness engine),
D4 (episode suppression), D5 (events), D6 (config).
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.qualification import (
    ComparisonResult,
    QualificationHarness,
    QualificationStore,
    QualificationTest,
    TestResult,
    _compute_direction,
)
from probos.config import QualificationConfig


# ---------------------------------------------------------------------------
# Mock test helper
# ---------------------------------------------------------------------------


class MockQualificationTest:
    """A test that always returns a configurable score."""

    def __init__(
        self,
        name: str = "mock_test",
        tier: int = 1,
        threshold: float = 0.5,
        score: float = 0.75,
    ):
        self._name = name
        self._tier = tier
        self._threshold = threshold
        self._score = score

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def description(self) -> str:
        return "Mock test for harness validation"

    @property
    def threshold(self) -> float:
        return self._threshold

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        return TestResult(
            agent_id=agent_id,
            test_name=self._name,
            tier=self._tier,
            score=self._score,
            passed=self._score >= self._threshold,
            timestamp=time.time(),
            duration_ms=1.0,
        )


class SlowTest(MockQualificationTest):
    """A test that takes too long."""

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        await asyncio.sleep(10)  # Will be timed out
        return await super().run(agent_id, runtime)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> QualificationStore:
    s = QualificationStore(data_dir=tmp_path)
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
async def harness(store: QualificationStore) -> QualificationHarness:
    return QualificationHarness(store=store)


@pytest.fixture
def sample_result() -> TestResult:
    return TestResult(
        agent_id="agent-1",
        test_name="mock_test",
        tier=1,
        score=0.8,
        passed=True,
        timestamp=time.time(),
        duration_ms=5.0,
    )


# =========================================================================
# D1 — Core Types (4 tests)
# =========================================================================


class TestCoreTypes:
    """Tests for TestResult and ComparisonResult."""

    def test_test_result_frozen(self, sample_result: TestResult):
        """TestResult is frozen — cannot mutate."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            sample_result.score = 0.5  # type: ignore[misc]

    def test_test_result_defaults(self):
        """Default values: is_baseline=False, details={}, error=None."""
        r = TestResult(
            agent_id="a",
            test_name="t",
            tier=1,
            score=0.5,
            passed=True,
            timestamp=1.0,
            duration_ms=1.0,
        )
        assert r.is_baseline is False
        assert r.details == {}
        assert r.error is None

    def test_comparison_result_improved(self):
        """delta > threshold → direction='improved'."""
        direction = _compute_direction(0.2, 0.15)
        assert direction == "improved"

        cr = ComparisonResult(
            agent_id="a",
            test_name="t",
            baseline_score=0.6,
            current_score=0.8,
            delta=0.2,
            percent_change=33.3,
            significant=True,
            direction="improved",
        )
        assert cr.direction == "improved"

    def test_comparison_result_declined(self):
        """delta < -threshold → direction='declined'."""
        direction = _compute_direction(-0.2, 0.15)
        assert direction == "declined"

        cr = ComparisonResult(
            agent_id="a",
            test_name="t",
            baseline_score=0.8,
            current_score=0.6,
            delta=-0.2,
            percent_change=-25.0,
            significant=True,
            direction="declined",
        )
        assert cr.direction == "declined"


# =========================================================================
# D2 — QualificationStore (5 tests)
# =========================================================================


class TestQualificationStore:
    """Tests for SQLite result persistence."""

    @pytest.mark.asyncio
    async def test_store_save_and_load(self, store: QualificationStore, sample_result: TestResult):
        """Save TestResult, get_latest returns it with matching fields."""
        await store.save_result(sample_result)
        loaded = await store.get_latest("agent-1", "mock_test")
        assert loaded is not None
        assert loaded.agent_id == "agent-1"
        assert loaded.test_name == "mock_test"
        assert loaded.score == 0.8
        assert loaded.passed is True
        assert loaded.tier == 1

    @pytest.mark.asyncio
    async def test_store_baseline_set_and_get(self, store: QualificationStore, sample_result: TestResult):
        """set_baseline marks result, get_baseline returns it."""
        await store.save_result(sample_result)
        latest = await store.get_latest("agent-1", "mock_test")
        assert latest is not None

        # Get the ID from the DB directly
        cursor = await store._db.execute(
            "SELECT id FROM qualification_results WHERE agent_id = ? AND test_name = ?",
            ("agent-1", "mock_test"),
        )
        row = await cursor.fetchone()
        result_id = row[0]

        await store.set_baseline("agent-1", "mock_test", result_id)
        baseline = await store.get_baseline("agent-1", "mock_test")
        assert baseline is not None
        assert baseline.is_baseline is True
        assert baseline.score == 0.8

    @pytest.mark.asyncio
    async def test_store_baseline_replaces_previous(self, store: QualificationStore):
        """Setting new baseline clears old one."""
        r1 = TestResult(
            agent_id="a", test_name="t", tier=1, score=0.5,
            passed=True, timestamp=1.0, duration_ms=1.0, is_baseline=True,
        )
        r2 = TestResult(
            agent_id="a", test_name="t", tier=1, score=0.9,
            passed=True, timestamp=2.0, duration_ms=1.0,
        )
        await store.save_result(r1)
        await store.save_result(r2)

        # Get IDs
        cursor = await store._db.execute(
            "SELECT id, timestamp FROM qualification_results "
            "WHERE agent_id = 'a' ORDER BY timestamp ASC",
        )
        rows = await cursor.fetchall()
        id1, id2 = rows[0][0], rows[1][0]

        # Set r2 as baseline
        await store.set_baseline("a", "t", id2)
        baseline = await store.get_baseline("a", "t")
        assert baseline is not None
        assert baseline.score == 0.9

        # Old baseline should be cleared
        cursor = await store._db.execute(
            "SELECT is_baseline FROM qualification_results WHERE id = ?",
            (id1,),
        )
        old_row = await cursor.fetchone()
        assert old_row[0] == 0

    @pytest.mark.asyncio
    async def test_store_history_chronological(self, store: QualificationStore):
        """Multiple results returned newest-first, respects limit."""
        for i in range(5):
            r = TestResult(
                agent_id="a", test_name="t", tier=1, score=0.1 * (i + 1),
                passed=True, timestamp=float(i + 1), duration_ms=1.0,
            )
            await store.save_result(r)

        history = await store.get_history("a", "t", limit=3)
        assert len(history) == 3
        # Newest first
        assert history[0].timestamp > history[1].timestamp
        assert history[1].timestamp > history[2].timestamp

    @pytest.mark.asyncio
    async def test_store_agent_summary(self, store: QualificationStore):
        """Summary aggregates across tests."""
        r1 = TestResult(
            agent_id="a", test_name="t1", tier=1, score=0.8,
            passed=True, timestamp=1.0, duration_ms=1.0,
        )
        r2 = TestResult(
            agent_id="a", test_name="t2", tier=1, score=0.3,
            passed=False, timestamp=2.0, duration_ms=1.0,
        )
        await store.save_result(r1)
        await store.save_result(r2)

        summary = await store.get_agent_summary("a")
        assert summary["agent_id"] == "a"
        assert summary["tests_run"] == 2
        assert summary["tests_passed"] == 1
        assert summary["pass_rate"] == 0.5
        assert "t1" in summary["latest_results"]
        assert "t2" in summary["latest_results"]


# =========================================================================
# D3 — QualificationHarness (7 tests)
# =========================================================================


class TestQualificationHarness:
    """Tests for the harness engine."""

    def test_harness_register_test(self, harness: QualificationHarness):
        """register_test → test appears in registered_tests."""
        test = MockQualificationTest()
        harness.register_test(test)
        assert "mock_test" in harness.registered_tests

    @pytest.mark.asyncio
    async def test_harness_run_test_basic(self, harness: QualificationHarness, store: QualificationStore):
        """Run mock test → TestResult stored in DB, returned."""
        test = MockQualificationTest()
        harness.register_test(test)

        result = await harness.run_test("agent-1", "mock_test", runtime=None)
        assert result.agent_id == "agent-1"
        assert result.score == 0.75
        assert result.passed is True

        # Verify stored
        loaded = await store.get_latest("agent-1", "mock_test")
        assert loaded is not None
        assert loaded.score == 0.75

    @pytest.mark.asyncio
    async def test_harness_auto_baseline(self, store: QualificationStore):
        """First run auto-captures baseline when baseline_auto_capture=True."""
        cfg = QualificationConfig(baseline_auto_capture=True)
        h = QualificationHarness(store=store, config=cfg)
        test = MockQualificationTest()
        h.register_test(test)

        result = await h.run_test("agent-1", "mock_test", runtime=None)
        assert result.is_baseline is True

        # Second run should NOT be baseline
        result2 = await h.run_test("agent-1", "mock_test", runtime=None)
        assert result2.is_baseline is False

    @pytest.mark.asyncio
    async def test_harness_no_auto_baseline(self, store: QualificationStore):
        """baseline_auto_capture=False → first run is NOT baseline."""
        cfg = QualificationConfig(baseline_auto_capture=False)
        h = QualificationHarness(store=store, config=cfg)
        test = MockQualificationTest()
        h.register_test(test)

        result = await h.run_test("agent-1", "mock_test", runtime=None)
        assert result.is_baseline is False

    @pytest.mark.asyncio
    async def test_harness_run_tier(self, harness: QualificationHarness):
        """Register 2 tier-1 tests + 1 tier-2 → run_tier(tier=1) runs only tier-1."""
        t1a = MockQualificationTest(name="t1a", tier=1)
        t1b = MockQualificationTest(name="t1b", tier=1)
        t2 = MockQualificationTest(name="t2", tier=2)
        harness.register_test(t1a)
        harness.register_test(t1b)
        harness.register_test(t2)

        results = await harness.run_tier("agent-1", 1, runtime=None)
        assert len(results) == 2
        assert all(r.tier == 1 for r in results)

    @pytest.mark.asyncio
    async def test_harness_compare(self, store: QualificationStore):
        """Baseline at 0.8, current at 0.6 → declined."""
        cfg = QualificationConfig(baseline_auto_capture=False, significance_threshold=0.15)
        h = QualificationHarness(store=store, config=cfg)

        # Save baseline
        baseline = TestResult(
            agent_id="a", test_name="t", tier=1, score=0.8,
            passed=True, timestamp=1.0, duration_ms=1.0, is_baseline=True,
        )
        await store.save_result(baseline)

        # Save current
        current = TestResult(
            agent_id="a", test_name="t", tier=1, score=0.6,
            passed=True, timestamp=2.0, duration_ms=1.0,
        )
        await store.save_result(current)

        # Register a test so compare can look it up
        mock = MockQualificationTest(name="t")
        h.register_test(mock)

        cr = await h.compare("a", "t")
        assert cr is not None
        assert cr.delta == pytest.approx(-0.2)
        assert cr.direction == "declined"
        assert cr.significant is True

    @pytest.mark.asyncio
    async def test_harness_timeout(self, store: QualificationStore):
        """Slow test exceeds timeout → error result."""
        cfg = QualificationConfig(test_timeout_seconds=0.1)
        h = QualificationHarness(store=store, config=cfg)
        slow = SlowTest(name="slow_test")
        h.register_test(slow)

        result = await h.run_test("agent-1", "slow_test", runtime=None)
        assert result.score == 0.0
        assert result.passed is False
        assert result.error == "Test timed out"


# =========================================================================
# D4 — Episode Suppression (1 test)
# =========================================================================


class TestEpisodeSuppression:
    """Tests for _qualification_test episode guard."""

    @pytest.mark.asyncio
    async def test_qualification_test_skips_episode_storage(self):
        """_store_action_episode with _qualification_test=True → no episode stored."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        # Minimal attributes needed by _store_action_episode
        agent._episodic_memory = AsyncMock()
        agent._runtime = MagicMock()
        agent._id = "test-agent"
        agent._name = "TestAgent"
        agent._callsign = "Test"
        agent._callsigns = ["Test"]

        # Create intent with _qualification_test flag
        intent = MagicMock()
        intent.intent = "test_probe"
        intent.params = {"_qualification_test": True, "query": "test"}

        observation = {"params": intent.params}
        report = {"success": True}

        await agent._store_action_episode(intent, observation, report)

        # Episodic memory should NOT have been called
        agent._episodic_memory.store.assert_not_called()


# =========================================================================
# D5 — Events (1 test)
# =========================================================================


class TestEvents:
    """Tests for event emission."""

    @pytest.mark.asyncio
    async def test_harness_emits_events(self, store: QualificationStore):
        """Run test → events emitted via emit_event_fn."""
        events: list[tuple[str, dict]] = []

        def capture_event(event_type: str, data: dict):
            events.append((event_type, data))

        cfg = QualificationConfig(baseline_auto_capture=True)
        h = QualificationHarness(store=store, emit_event_fn=capture_event, config=cfg)
        test = MockQualificationTest()
        h.register_test(test)

        await h.run_test("agent-1", "mock_test", runtime=None)

        # Should have baseline_set + test_complete events
        event_types = [e[0] for e in events]
        assert "qualification_baseline_set" in event_types
        assert "qualification_test_complete" in event_types

        # Verify test_complete data
        tc = next(e for e in events if e[0] == "qualification_test_complete")
        assert tc[1]["agent_id"] == "agent-1"
        assert tc[1]["score"] == 0.75
        assert tc[1]["is_baseline"] is True


# =========================================================================
# D6 — Config (1 test)
# =========================================================================


class TestConfig:
    """Tests for QualificationConfig defaults."""

    def test_qualification_config_defaults(self):
        """Default values match spec."""
        cfg = QualificationConfig()
        assert cfg.enabled is True
        assert cfg.baseline_auto_capture is True
        assert cfg.significance_threshold == 0.15
        assert cfg.test_timeout_seconds == 60.0


# =========================================================================
# Protocol compliance check
# =========================================================================


class TestProtocol:
    """Verify MockQualificationTest satisfies the Protocol."""

    def test_mock_implements_protocol(self):
        mock = MockQualificationTest()
        assert isinstance(mock, QualificationTest)
