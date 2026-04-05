"""AD-566f: /qualify shell command tests."""
from __future__ import annotations

import time
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.cognitive.qualification import TestResult
from probos.experience.commands.commands_qualification import cmd_qualify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_console():
    buf = StringIO()
    return Console(file=buf, width=120, force_terminal=True), buf


def _make_test_result(
    agent_id: str = "agent-1",
    test_name: str = "personality_probe",
    tier: int = 1,
    score: float = 0.85,
    passed: bool = True,
    is_baseline: bool = False,
) -> TestResult:
    return TestResult(
        agent_id=agent_id,
        test_name=test_name,
        tier=tier,
        score=score,
        passed=passed,
        timestamp=time.time(),
        duration_ms=10.0,
        is_baseline=is_baseline,
    )


def _make_harness(tests: dict | None = None):
    harness = MagicMock()
    if tests is None:
        mock_t1 = MagicMock()
        mock_t1.name = "personality_probe"
        mock_t1.tier = 1
        mock_t2 = MagicMock()
        mock_t2.name = "theory_of_mind"
        mock_t2.tier = 2
        mock_t3 = MagicMock()
        mock_t3.name = "emergence_capacity"
        mock_t3.tier = 3
        tests = {
            "personality_probe": mock_t1,
            "theory_of_mind": mock_t2,
            "emergence_capacity": mock_t3,
        }
    harness.registered_tests = tests
    harness.run_all = AsyncMock(return_value=[
        _make_test_result(score=0.9, passed=True),
    ])
    harness.run_collective = AsyncMock(return_value=[])
    return harness


def _make_store(summary: dict | None = None, baseline: TestResult | None = None):
    store = AsyncMock()
    store.get_agent_summary = AsyncMock(return_value=summary or {
        "agent_id": "agent-1",
        "tests_run": 5,
        "tests_passed": 4,
        "pass_rate": 0.8,
        "baseline_set": True,
        "latest_results": {
            "personality_probe": {"score": 0.85, "passed": True, "timestamp": time.time()},
        },
    })
    store.get_baseline = AsyncMock(return_value=baseline)
    store.get_latest = AsyncMock(return_value=None)
    return store


def _make_scheduler(crew_ids: list[str] | None = None, running: bool = True):
    scheduler = MagicMock()
    scheduler._get_crew_agent_ids = MagicMock(return_value=crew_ids or ["agent-1"])
    scheduler._last_run_time = time.time() - 60
    scheduler._running = running
    scheduler.run_now = AsyncMock(return_value=[])
    return scheduler


def _make_agent(agent_id: str = "agent-1", callsign: str = "Echo", agent_type: str = "counselor"):
    agent = SimpleNamespace(id=agent_id, callsign=callsign, agent_type=agent_type)
    return agent


def _make_registry(agents: list | None = None):
    registry = MagicMock()
    agents = agents or [_make_agent()]
    registry.all = MagicMock(return_value=agents)
    return registry


def _make_runtime(**kwargs):
    rt = SimpleNamespace(
        _qualification_harness=kwargs.get("harness"),
        _qualification_store=kwargs.get("store"),
        _drift_scheduler=kwargs.get("scheduler"),
        registry=kwargs.get("registry", _make_registry()),
    )
    return rt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStatusNoHarness:
    @pytest.mark.asyncio
    async def test_status_no_harness(self):
        """No harness → error message."""
        con, buf = _make_console()
        rt = _make_runtime(harness=None, store=None)
        await cmd_qualify(rt, con, "")
        output = buf.getvalue()
        assert "not available" in output.lower()


class TestStatusWithHarness:
    @pytest.mark.asyncio
    async def test_status_with_harness(self):
        """Shows registered tests grouped by tier."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        scheduler = _make_scheduler()
        rt = _make_runtime(harness=harness, store=store, scheduler=scheduler)
        await cmd_qualify(rt, con, "status")
        output = buf.getvalue()
        assert "personality_probe" in output
        assert "theory_of_mind" in output
        assert "emergence_capacity" in output
        assert "1" in output  # tier counts


class TestRunTriggersTests:
    @pytest.mark.asyncio
    async def test_run_triggers_drift_scheduler(self):
        """run subcommand calls run_now()."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        scheduler = _make_scheduler()
        rt = _make_runtime(harness=harness, store=store, scheduler=scheduler)
        await cmd_qualify(rt, con, "run")
        scheduler.run_now.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_no_scheduler(self):
        """run without scheduler → error."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        rt = _make_runtime(harness=harness, store=store, scheduler=None)
        await cmd_qualify(rt, con, "run")
        output = buf.getvalue()
        assert "not available" in output.lower()


class TestRunSpecificAgent:
    @pytest.mark.asyncio
    async def test_run_specific_agent(self):
        """Resolves callsign, runs run_all for that agent."""
        con, buf = _make_console()
        agent = _make_agent(agent_id="abc-123", callsign="Echo")
        harness = _make_harness()
        store = _make_store()
        registry = _make_registry([agent])
        rt = _make_runtime(harness=harness, store=store, registry=registry)
        await cmd_qualify(rt, con, "run Echo")
        harness.run_all.assert_called_once_with("abc-123", rt)

    @pytest.mark.asyncio
    async def test_run_unknown_agent(self):
        """Unknown callsign → error."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        rt = _make_runtime(harness=harness, store=store)
        await cmd_qualify(rt, con, "run NoSuchAgent")
        output = buf.getvalue()
        assert "not found" in output.lower()


class TestAgentSummary:
    @pytest.mark.asyncio
    async def test_agent_summary(self):
        """Calls get_agent_summary and renders output."""
        con, buf = _make_console()
        agent = _make_agent()
        harness = _make_harness()
        store = _make_store()
        registry = _make_registry([agent])
        rt = _make_runtime(harness=harness, store=store, registry=registry)
        await cmd_qualify(rt, con, "agent Echo")
        store.get_agent_summary.assert_called_once_with("agent-1")
        output = buf.getvalue()
        assert "echo" in output.lower() or "Echo" in output

    @pytest.mark.asyncio
    async def test_agent_no_identifier(self):
        """agent without id → usage."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        rt = _make_runtime(harness=harness, store=store)
        await cmd_qualify(rt, con, "agent")
        output = buf.getvalue()
        assert "usage" in output.lower()


class TestBaselines:
    @pytest.mark.asyncio
    async def test_baselines_empty(self):
        """No baselines → helpful message."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store(baseline=None)
        scheduler = _make_scheduler()
        rt = _make_runtime(harness=harness, store=store, scheduler=scheduler)
        await cmd_qualify(rt, con, "baselines")
        output = buf.getvalue()
        assert "no baselines" in output.lower()

    @pytest.mark.asyncio
    async def test_baselines_with_data(self):
        """Baselines exist → table rendered."""
        con, buf = _make_console()
        harness = _make_harness()
        baseline = _make_test_result(is_baseline=True, score=0.88)
        store = _make_store(baseline=baseline)
        scheduler = _make_scheduler()
        rt = _make_runtime(harness=harness, store=store, scheduler=scheduler)
        await cmd_qualify(rt, con, "baselines")
        output = buf.getvalue()
        assert "0.880" in output


class TestUnknownSubcommand:
    @pytest.mark.asyncio
    async def test_unknown_subcommand(self):
        """Unknown subcommand → usage help."""
        con, buf = _make_console()
        harness = _make_harness()
        store = _make_store()
        rt = _make_runtime(harness=harness, store=store)
        await cmd_qualify(rt, con, "foobar")
        output = buf.getvalue()
        assert "usage" in output.lower()
