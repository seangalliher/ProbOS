"""AD-574b: DM listing endpoints expose target_agent_id for HXI sync chat path."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from probos.routers.wardroom import _resolve_dm_target_agent_id


class _FakeAgent:
    def __init__(self, agent_id: str, alive: bool = True):
        self.id = agent_id
        self.is_alive = alive


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]):
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return self._agents


@pytest.fixture
def runtime_with_agents():
    agents = [
        _FakeAgent("agentA001full"),
        _FakeAgent("agentB002full"),
        _FakeAgent("ghostagent", alive=False),
    ]
    return SimpleNamespace(registry=_FakeRegistry(agents))


class TestResolveDmTargetAgentId:
    """Direct unit tests of the resolver helper."""

    def test_captain_dm_resolves_other_participant(self, runtime_with_agents):
        # Hyphenated prefix produces > 3 parts after split → returns None.
        # This is expected per dispatch pre-flight (UI falls back gracefully).
        result = _resolve_dm_target_agent_id("dm-captain-agent-a-", runtime_with_agents)
        assert result is None

    def test_captain_dm_three_part_resolves(self, runtime_with_agents):
        # Real captain DM channel names use prefix[:8] of a hyphen-free agent_id,
        # so split yields exactly 3 parts.
        result = _resolve_dm_target_agent_id("dm-captain-agentA001", runtime_with_agents)
        assert result == "agentA001full"

    def test_agent_to_agent_dm_resolves_first_match(self, runtime_with_agents):
        # dm-{a8}-{b8} — non-captain prefix is parts[1] (or [2] if [1]=="captain").
        result = _resolve_dm_target_agent_id("dm-agentA001-agentB002", runtime_with_agents)
        # Helper takes first non-captain candidate → "agentA001" → resolves.
        # BF-721: this first-candidate rule is why the channel-level answer is only
        # a DEFAULT. An agent-to-agent channel has two participants but one answer,
        # so threads authored by the second participant would be misrouted. The
        # per-thread resolver (_resolve_thread_target_agent_id) is the correct
        # answer when thread context exists; this remains the no-context fallback.
        assert result == "agentA001full"

    def test_resting_agent_is_returned(self):
        # BF-721: this test was named ``test_dead_agent_not_returned`` and asserted
        # ``result is None`` for an agent with ``is_alive=False``. That pinned the
        # ``getattr(agent, "is_alive", False)`` gate as the contract — but a
        # proactive crew member is idle most of the time, so the gate made the
        # Captain's reply silently degrade to the async post-only path for a
        # perfectly healthy, registered agent. AD-1076 established the same rule
        # for group-chat membership: a *persistent* relationship must not depend on
        # momentary liveness. Registration, not wakefulness, is the test.
        agents = [_FakeAgent("ghostx", alive=False)]
        rt = SimpleNamespace(registry=_FakeRegistry(agents))
        result = _resolve_dm_target_agent_id("dm-captain-ghostx", rt)
        assert result == "ghostx"

    def test_unresolvable_prefix_returns_none(self, runtime_with_agents):
        result = _resolve_dm_target_agent_id("dm-captain-unknown", runtime_with_agents)
        assert result is None

    def test_non_dm_channel_returns_none(self, runtime_with_agents):
        result = _resolve_dm_target_agent_id("ship-general", runtime_with_agents)
        assert result is None

    def test_runtime_without_registry_returns_none(self):
        rt = SimpleNamespace()  # no registry attribute
        result = _resolve_dm_target_agent_id("dm-captain-anything", rt)
        assert result is None

    def test_resolver_swallows_registry_exception(self):
        class _Boom:
            def all(self):
                raise RuntimeError("registry unavailable")

        rt = SimpleNamespace(registry=_Boom())
        result = _resolve_dm_target_agent_id("dm-captain-prefix", rt)
        assert result is None  # tier-2 log-and-degrade
