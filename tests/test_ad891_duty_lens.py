"""AD-891: ACM consolidated profile — duties block (block 9).

Adds the configured duty schedule to ``ACM.get_consolidated_profile`` via the
public ``runtime.duty_schedule_tracker`` accessor and a non-mutating
``DutyScheduleTracker.list_duties_for_agent``.

BF-287 discipline: a real ``AgentCapitalService`` and a real
``DutyScheduleTracker`` (built from real ``DutyDefinition`` config objects) at
the substrate boundary — no MagicMock for the subsystems whose attribute shape
the lens depends on. The runtime container is a plain stub holding the real
tracker + a stub registry, so attribute lookups hit reality.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.config import DutyDefinition
from probos.duty_schedule import DutyScheduleTracker


# ---------------------------------------------------------------------------
# Helpers — real tracker, plain stub runtime container
# ---------------------------------------------------------------------------


class _StubAgent:
    """Minimal registry agent shape — block 9 reads ``agent_type``."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _StubRegistry:
    def __init__(self, agents: dict[str, _StubAgent]) -> None:
        self._agents = agents

    def get(self, agent_id: str) -> _StubAgent | None:
        return self._agents.get(agent_id)


class _LensRuntime:
    """Plain runtime container — only the attributes block 9 reads.

    Other blocks (profile_store, trust_network, skill_service, …) guard with
    hasattr(), so omitting them keeps those blocks dormant and isolates block 9.
    """

    def __init__(
        self,
        *,
        duty_schedule_tracker: DutyScheduleTracker | None = None,
        registry: _StubRegistry | None = None,
    ) -> None:
        if duty_schedule_tracker is not None:
            self.duty_schedule_tracker = duty_schedule_tracker
        if registry is not None:
            self.registry = registry


def _duty(duty_id: str, *, priority: int = 2, interval: float = 3600.0) -> DutyDefinition:
    return DutyDefinition(
        duty_id=duty_id,
        description=f"do {duty_id}",
        interval_seconds=interval,
        priority=priority,
    )


@pytest.fixture
async def acm(tmp_path):
    svc = AgentCapitalService(data_dir=str(tmp_path))
    await svc.start()
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# DutyScheduleTracker.list_duties_for_agent — unit
# ---------------------------------------------------------------------------


class TestListDutiesForAgent:
    def test_returns_configured_duties_sorted_by_priority(self) -> None:
        tracker = DutyScheduleTracker(
            {"scout": [_duty("low", priority=1), _duty("high", priority=5)]}
        )

        duties = tracker.list_duties_for_agent("scout")

        assert [d.duty_id for d in duties] == ["high", "low"]

    def test_unconfigured_agent_type_returns_empty(self) -> None:
        tracker = DutyScheduleTracker({"scout": [_duty("a")]})

        assert tracker.list_duties_for_agent("physician") == []

    def test_is_non_mutating(self) -> None:
        """Listing must not record execution or alter due-state (vs get_due_duties)."""
        tracker = DutyScheduleTracker({"scout": [_duty("a")]})

        # Fresh tracker: never executed → the duty is due.
        assert len(tracker.get_due_duties("scout")) == 1
        # Listing it should not flip it to "executed".
        tracker.list_duties_for_agent("scout")
        tracker.list_duties_for_agent("scout")
        assert len(tracker.get_due_duties("scout")) == 1
        # Internal status map untouched (no record_execution side effect).
        assert tracker._status == {}


# ---------------------------------------------------------------------------
# Block 9: duties in the consolidated profile
# ---------------------------------------------------------------------------


class TestDutyLensBlock:
    @pytest.mark.asyncio
    async def test_duties_present(self, acm) -> None:
        """Lens includes duties + duty_count from a real tracker."""
        await acm.onboard("a1", "scout", "pool", "science")
        tracker = DutyScheduleTracker(
            {"scout": [_duty("scout_report", priority=3), _duty("ping", priority=1)]}
        )
        rt = _LensRuntime(
            duty_schedule_tracker=tracker,
            registry=_StubRegistry({"a1": _StubAgent("scout")}),
        )

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["duty_count"] == 2
        assert [d["duty_id"] for d in profile["duties"]] == ["scout_report", "ping"]
        first = profile["duties"][0]
        assert {"duty_id", "description", "cron", "interval_seconds", "priority"} <= set(first)

    @pytest.mark.asyncio
    async def test_duties_absent_when_no_tracker(self, acm) -> None:
        """No tracker on the runtime → block omitted (graceful)."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = _LensRuntime(registry=_StubRegistry({"a1": _StubAgent("scout")}))

        profile = await acm.get_consolidated_profile("a1", rt)

        assert "duties" not in profile
        assert "duty_count" not in profile

    @pytest.mark.asyncio
    async def test_duties_empty_for_unconfigured_agent_type(self, acm) -> None:
        """Tracker present but agent_type has no schedule → empty list, count 0."""
        await acm.onboard("a1", "physician", "pool", "medical")
        tracker = DutyScheduleTracker({"scout": [_duty("scout_report")]})
        rt = _LensRuntime(
            duty_schedule_tracker=tracker,
            registry=_StubRegistry({"a1": _StubAgent("physician")}),
        )

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["duty_count"] == 0
        assert profile["duties"] == []

    @pytest.mark.asyncio
    async def test_duties_absent_when_agent_unknown(self, acm) -> None:
        """Registry returns no agent (no agent_type) → block omitted, no crash."""
        await acm.onboard("a1", "scout", "pool", "science")
        tracker = DutyScheduleTracker({"scout": [_duty("scout_report")]})
        rt = _LensRuntime(
            duty_schedule_tracker=tracker,
            registry=_StubRegistry({}),  # no agent → getattr(agent_type) is None
        )

        profile = await acm.get_consolidated_profile("a1", rt)

        assert "duties" not in profile
        assert "duty_count" not in profile
