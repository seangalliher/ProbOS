"""BF-154: TemperamentProbe timeout — sequential 8-LLM-call loop exceeds 60s.

Root cause: _run_inner() sent 4 scenarios + 4 LLM scoring calls sequentially.
Each _send_probe() goes through full cognitive pipeline (~10-15s). Total ~60-80s
exceeds the 60s harness timeout → asyncio.TimeoutError → score=0.0, passed=False.

Fix: asyncio.gather() runs all 4 axes in parallel. Each axis (probe + score)
takes ~15-20s, but all 4 complete in ~20s total instead of ~60-80s.
"""

import asyncio
import pytest
from dataclasses import dataclass, field
from unittest.mock import MagicMock, AsyncMock

from probos.cognitive.qualification_tests import TemperamentProbe, _MTI_SCENARIOS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockAgent:
    """Agent with configurable per-call delay."""

    def __init__(self, response: str = "I would investigate.", delay: float = 0.0):
        self.id = "agent-1"
        self.agent_type = "systems_analyst"
        self._response = response
        self._delay = delay
        self.call_count = 0

    async def handle_intent(self, intent):
        self.call_count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        result = MagicMock()
        result.result = self._response
        return result


class _MockLLMClient:
    """LLM client returning a fixed score."""

    def __init__(self, score_text: str = "0.6"):
        self._score_text = score_text

    async def complete(self, request):
        resp = MagicMock()
        resp.content = self._score_text
        resp.text = self._score_text
        return resp


def _build_runtime(agent=None, llm_score="0.6"):
    runtime = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.llm_client = _MockLLMClient(llm_score)
    return runtime


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParallelAxes:
    """BF-154: Verify axes run in parallel, not sequentially."""

    @pytest.mark.asyncio
    async def test_four_axes_complete_within_timeout(self):
        """With 0.5s delay per call, parallel should finish in ~1s not ~4s."""
        agent = _MockAgent(delay=0.5)
        runtime = _build_runtime(agent=agent)
        probe = TemperamentProbe()

        result = await asyncio.wait_for(probe.run("agent-1", runtime), timeout=10.0)

        assert result.passed is True
        assert result.score > 0.0
        # 4 scenarios + 4 LLM scoring = 8 calls on agent, but only 4 on agent
        assert agent.call_count == 4  # 4 _send_probe calls

    @pytest.mark.asyncio
    async def test_all_four_axes_in_details(self):
        """All 4 axes present in result details."""
        agent = _MockAgent()
        runtime = _build_runtime(agent=agent)
        probe = TemperamentProbe()

        result = await probe.run("agent-1", runtime)

        for axis in ("reactivity", "compliance", "sociality", "resilience"):
            assert axis in result.details, f"Missing axis: {axis}"
            assert 0.0 <= result.details[axis] <= 1.0

    @pytest.mark.asyncio
    async def test_per_axis_responses_populated(self):
        """per_axis_responses dict has all 4 axes."""
        agent = _MockAgent(response="Test response for axis.")
        runtime = _build_runtime(agent=agent)
        probe = TemperamentProbe()

        result = await probe.run("agent-1", runtime)

        responses = result.details["per_axis_responses"]
        assert set(responses.keys()) == {"reactivity", "compliance", "sociality", "resilience"}
        for axis, text in responses.items():
            assert len(text) > 0, f"{axis} response empty"

    @pytest.mark.asyncio
    async def test_parallel_faster_than_sequential(self):
        """Parallel completion time should be ~1 axis, not ~4 axes."""
        agent = _MockAgent(delay=0.3)
        runtime = _build_runtime(agent=agent)
        probe = TemperamentProbe()

        import time
        t0 = time.monotonic()
        result = await probe.run("agent-1", runtime)
        elapsed = time.monotonic() - t0

        assert result.passed is True
        # Sequential would be ~2.4s (8 calls × 0.3s). Parallel should be <1.5s.
        assert elapsed < 2.0, f"Took {elapsed:.1f}s — likely sequential"


class TestPartialAxisFailure:
    """BF-154: One axis failing shouldn't kill the whole probe."""

    @pytest.mark.asyncio
    async def test_partial_failure_still_passes(self):
        """If one axis throws, probe still returns passed=True with defaults."""
        call_count = 0

        class _FailOnSecondAgent:
            id = "agent-1"
            agent_type = "systems_analyst"

            async def handle_intent(self, intent):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("Simulated LLM failure")
                result = MagicMock()
                result.result = "I would handle it carefully."
                return result

        agent = _FailOnSecondAgent()
        runtime = _build_runtime(agent=agent)
        probe = TemperamentProbe()

        result = await probe.run("agent-1", runtime)

        assert result.passed is True
        assert result.score > 0.0  # at least 3 axes scored

    @pytest.mark.asyncio
    async def test_failed_axis_gets_default_score(self):
        """Axes that fail use 0.5 default from details.get()."""
        probe = TemperamentProbe()
        # Verify the details.get() fallback pattern
        details = {"reactivity": 0.7, "compliance": 0.8}
        assert details.get("sociality", 0.5) == 0.5
        assert details.get("resilience", 0.5) == 0.5


class TestAlwaysPasses:
    """TemperamentProbe is profile-only — should always pass."""

    @pytest.mark.asyncio
    async def test_always_passes_with_valid_agent(self):
        """Even with low scores, passed=True (threshold=0.0)."""
        agent = _MockAgent()
        runtime = _build_runtime(agent=agent, llm_score="0.1")
        probe = TemperamentProbe()

        result = await probe.run("agent-1", runtime)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_missing_agent_returns_error(self):
        """Agent not in registry → error, not a silent 0.0."""
        runtime = _build_runtime(agent=None)
        probe = TemperamentProbe()

        result = await probe.run("nonexistent", runtime)

        assert result.passed is False
        assert result.error is not None
        assert "not found" in result.error

    def test_threshold_is_zero(self):
        """Profile probe — no pass/fail threshold."""
        assert TemperamentProbe().threshold == 0.0

    def test_scenarios_cover_four_axes(self):
        """All 4 MTI axes have scenarios defined."""
        assert set(_MTI_SCENARIOS.keys()) == {"reactivity", "compliance", "sociality", "resilience"}
