"""AD-752 proactive scan agent policy gating tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.proactive import ProactiveScanAgent


@pytest.mark.asyncio
async def test_perceive_inbox_scan_only_during_work_hours() -> None:
    agent = ProactiveScanAgent(agent_id="proactive-scan-1")

    class _Schedule:
        def should_scan(self, scan_type: str, dt):
            return scan_type == "inbox"

        def reason_code(self, scan_type: str, dt):
            if scan_type == "inbox":
                return "allowed"
            return "outside_work_hours"

    agent._runtime = SimpleNamespace(duty_schedule=_Schedule())

    msg = await agent.perceive()

    assert msg.intent == "proactive_scan"
    assert msg.params["scan_types"] == ["inbox"]
    assert msg.params["suppressed_reasons"]["calendar"] == "outside_work_hours"
    assert msg.params["suppressed_reasons"]["teams"] == "outside_work_hours"


@pytest.mark.asyncio
async def test_perceive_calendar_and_teams_suppressed_during_quiet_hours() -> None:
    agent = ProactiveScanAgent(agent_id="proactive-scan-2")

    class _Schedule:
        def should_scan(self, scan_type: str, dt):
            return scan_type == "inbox"

        def reason_code(self, scan_type: str, dt):
            if scan_type == "inbox":
                return "allowed"
            return "quiet_hours_active"

    agent._runtime = SimpleNamespace(duty_schedule=_Schedule())

    msg = await agent.perceive()

    assert msg.params["scan_types"] == ["inbox"]
    assert msg.params["suppressed_reasons"]["calendar"] == "quiet_hours_active"
    assert msg.params["suppressed_reasons"]["teams"] == "quiet_hours_active"


@pytest.mark.asyncio
async def test_perceive_uses_heartbeat_tagging_for_scan_intents() -> None:
    agent = ProactiveScanAgent(agent_id="proactive-scan-3")

    class _Schedule:
        def should_scan(self, scan_type: str, dt):
            return True

        def reason_code(self, scan_type: str, dt):
            return "allowed"

    agent._runtime = SimpleNamespace(duty_schedule=_Schedule())

    msg = await agent.perceive()

    assert msg.params["tagged_as"] == "heartbeat"
    assert msg.params["scan_types"] == ["inbox", "calendar", "teams"]
