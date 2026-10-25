"""BF-924 (#1654) M2: trust history, /grant list and the Counselor's config read APIs that exist.

Each repair is driven through its production caller: the profile route and the avatar telemetry for
``TrustNetwork.get_history``, the real ``/grant`` command for the grant list, and real Counselors
(one on a booted runtime) for ``CounselorConfig``.
"""

from __future__ import annotations

import importlib
import inspect
import math
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.llm_client import BaseLLMClient
from probos.config import CounselorConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.substrate.registry import AgentRegistry
from tests.test_api_profile import mock_agent, mock_runtime  # noqa: F401  (fixtures)


# --- F04: TrustNetwork.get_history ----------------------------------------------------------------


def test_get_history_returns_the_agents_scores_oldest_first() -> None:
    trust = TrustNetwork()
    for success in (True, False, True):
        trust.record_outcome("agent-a", success=success, weight=1.0)
    trust.record_outcome("agent-b", success=True, weight=1.0)
    scores = [event.new_score for event in trust.get_events_for_agent("agent-a")]
    assert len(scores) == 3 and len(set(scores)) > 1  # premise: three readings, not all equal

    assert trust.get_history("agent-a", limit=2) == scores[-2:]
    assert trust.get_history("agent-a") == scores
    assert trust.get_history("agent-unknown") == []


def test_get_history_with_no_limit_is_empty() -> None:
    trust = TrustNetwork()
    trust.record_outcome("agent-a", success=True, weight=1.0)

    assert trust.get_history("agent-a", limit=0) == []


def test_the_profile_route_returns_the_trust_history(mock_runtime) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    from probos.api import create_app

    trust = TrustNetwork()
    trust.record_outcome("agent-123", success=True, weight=1.0)
    trust.record_outcome("agent-123", success=False, weight=1.0)
    # Replaces the fixture's MagicMock, which invented get_history (and so hid that it did not exist).
    mock_runtime.trust_network = trust
    expected = [event.new_score for event in trust.get_events_for_agent("agent-123")]
    assert len(expected) == 2

    data = TestClient(create_app(mock_runtime)).get("/api/agent/agent-123/profile").json()

    assert data["trustHistory"] == expected
    assert all(0.0 <= score <= 1.0 for score in data["trustHistory"])  # what useProfileResource.ts:54 admits


@pytest.mark.asyncio
async def test_the_avatar_trust_delta_is_the_last_trust_change() -> None:
    from probos.avatars.telemetry import build_telemetry_snapshot
    from tests.test_ad722_avatar_telemetry import _crew_with_full_dsl, _make_runtime

    runtime = _make_runtime(crew=_crew_with_full_dsl())
    trust = TrustNetwork()
    trust.record_outcome("agent-007", success=True, weight=1.0)
    trust.record_outcome("agent-007", success=False, weight=3.0)
    runtime.trust_network = trust  # the real network in place of the module's _FakeTrustNetwork
    events = trust.get_events_for_agent("agent-007")
    expected = events[-1].new_score - events[-2].new_score
    assert expected != 0.0  # premise

    snap = await build_telemetry_snapshot("agent-007", runtime)

    assert snap.current_signals.trust_delta == pytest.approx(expected)
    assert "insufficient_trust_history" not in snap.degraded_reasons


_TRUST_DOUBLES = (
    ("tests.test_ad722_avatar_telemetry", "_FakeTrustNetwork"),
    ("tests.test_ad722b4_fleet_telemetry", "_FakeTrustNetwork"),
    ("tests.test_ad722b_websocket_push", "_FakeTrustNetwork"),
    ("tests.test_ad1260_wellness_domain", "_FakeTrust"),
)


def _parameters(fn) -> list[tuple[str, object]]:
    return [(p.name, p.kind) for p in list(inspect.signature(fn).parameters.values())[1:]]


@pytest.mark.parametrize(("module_name", "class_name"), _TRUST_DOUBLES)
def test_the_trust_network_doubles_match_the_real_class(module_name: str, class_name: str) -> None:
    """The seam: a double that stands for TrustNetwork on these paths has only its methods, by name and kind."""
    double = getattr(importlib.import_module(module_name), class_name)
    methods = [name for name, value in vars(double).items() if callable(value) and not name.startswith("_")]
    assert methods

    for name in methods:
        real = getattr(TrustNetwork, name, None)
        assert real is not None, f"{name} is not a TrustNetwork method ({module_name}.{class_name})"
        assert _parameters(getattr(double, name)) == _parameters(real), name


# --- F05: /grant list -----------------------------------------------------------------------------


async def _grant_then_list(
    tmp_path, *, with_identity: bool, issue: str = "issue Crusher full", stored_expiry: float | None = None,
):
    """Issue a grant and list grants through the real command, on real stores and registries.

    ``issue`` is the issue command's arguments. ``stored_expiry`` adds a second grant to the same target
    through the store itself, standing for a row stored before BF-924's duration check (A2, D12).
    """
    from rich.console import Console

    from probos.clearance_grants import ClearanceGrantStore
    from probos.crew_profile import CallsignRegistry
    from probos.earned_agency import RecallTier
    from probos.experience.commands.commands_clearance import cmd_grant
    from probos.identity import AgentIdentityRegistry

    identity = AgentIdentityRegistry(data_dir=tmp_path)
    await identity.start()
    store = ClearanceGrantStore(db_path=str(tmp_path / "grants.db"))
    await store.start()
    try:
        slot = "scout_scout_0_bf924"
        cert = await identity.resolve_or_issue(
            slot_id=slot, agent_type="scout", callsign="Wesley", instance_id="bf924",
            vessel_name="ProbOS", department="science", post_id="scout", baseline_version="v0",
        )
        agents = AgentRegistry()
        # Stands in for the scout: resolve() and register() read only id, agent_type, pool and is_alive.
        await agents.register(SimpleNamespace(id=slot, agent_type="scout", pool="scout", is_alive=True))
        callsigns = CallsignRegistry()
        callsigns.set_callsign("scout", "Crusher")  # a naming ceremony replaced the birth callsign
        callsigns.bind_registry(agents)
        runtime = SimpleNamespace(
            clearance_grant_store=store, callsign_registry=callsigns,
            identity_registry=identity if with_identity else None,
        )
        out = StringIO()
        console = Console(file=out, width=240)
        await cmd_grant(runtime, console, issue)
        if stored_expiry is not None:
            await store.issue_grant(
                target_agent_id=cert.agent_uuid, recall_tier=RecallTier.BASIC, expires_at=stored_expiry,
            )
        grants = await store.list_grants()
        await cmd_grant(runtime, console, "list")
    finally:
        await store.stop()
        await identity.stop()
    return slot, cert, grants, out.getvalue()


def _listed_table(output: str) -> str:
    """The grant table ``/grant list`` printed after the issue command's output; it must have printed one.

    A3 (review round 2, M2 finding 2): A2 split at the title with ``[-1]`` so the refused-issue cases, which print
    no table, would not raise; with no table that returned the issue command's own confirmation, which names the
    target too, so the live-callsign test passed with the table's print removed.
    """
    _before, title, table = output.partition("Clearance Grants")
    assert title, "/grant list printed no grant table"
    return table


@pytest.mark.asyncio
async def test_grant_list_names_the_target_by_its_live_callsign(tmp_path) -> None:
    slot, cert, grants, output = await _grant_then_list(tmp_path, with_identity=True)
    table = _listed_table(output)

    assert [grant.target_agent_id for grant in grants] == [cert.agent_uuid]  # _grant_issue stores the sovereign id
    assert cert.agent_uuid != slot
    assert "Crusher" in table
    assert "Wesley" not in table


@pytest.mark.asyncio
async def test_grant_list_without_an_identity_registry_shows_the_target_id(tmp_path) -> None:
    slot, _cert, grants, output = await _grant_then_list(tmp_path, with_identity=False)
    table = _listed_table(output)

    assert [grant.target_agent_id for grant in grants] == [slot]
    assert slot[:12] in table


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_expiry", [math.inf, 3.6e13], ids=["inf", "past-time_t"])
async def test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown(tmp_path, stored_expiry) -> None:
    """G1 (review round 1): one expiry ``datetime.fromtimestamp`` cannot convert made ``/grant list`` raise and
    hide every grant. The status still reads the raw value, so an infinite expiry is Active."""
    _slot, _cert, grants, output = await _grant_then_list(tmp_path, with_identity=True, stored_expiry=stored_expiry)
    table = _listed_table(output)

    assert len(grants) == 2  # premise: the command's grant and the stored one are both active
    assert "Crusher" in table
    assert "out of range" in table
    assert table.count("Active") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", ["inf", "nan", "1e13"])
async def test_grant_issue_refuses_a_duration_that_cannot_be_an_expiry(tmp_path, duration) -> None:
    """G1 (review round 1): ``inf`` and ``1e13`` hours stored an expiry the list could not show; ``nan`` (``nan > 0``
    is False) stored a grant until revoked."""
    _slot, _cert, grants, output = await _grant_then_list(
        tmp_path, with_identity=True, issue=f"issue Crusher full general {duration}",
    )

    assert grants == []
    assert f"Invalid duration: {duration}" in output


# --- F10: CounselorConfig -------------------------------------------------------------------------


def _counselor(**config: object) -> CounselorAgent:
    return CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient), counselor_config=CounselorConfig(**config))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("threshold", "new_score", "assessments"),
    [(0.3, 0.7, 0), (0.1, 0.62, 1)],
    ids=["a-0.2-move-under-a-0.3-threshold", "a-0.12-move-over-a-0.1-threshold"],
)
async def test_the_trust_update_threshold_comes_from_the_config(threshold, new_score, assessments) -> None:
    """Through the Counselor's event listener; the move is measured from the default baseline (0.5)."""
    counselor = _counselor(trust_delta_threshold=threshold)
    await counselor.initialize(trust_network=TrustNetwork())
    counselor.get_or_create_profile("agent-1")  # _on_trust_update reassesses only a known agent

    await counselor._on_event_async({
        "type": EventType.TRUST_UPDATE.value, "data": {"agent_id": "agent-1", "new_score": new_score},
    })

    assert len(counselor.get_profile("agent-1").assessments) == assessments


@pytest.mark.asyncio
async def test_the_sweep_bound_comes_from_the_config() -> None:
    """Through act(), the wellness-report intent, which passes no bound."""
    counselor = _counselor(sweep_max_agents=2)
    registry = AgentRegistry()
    for i in range(3):
        # Crew stand-ins: the sweep reads id, tier, callsign and agent_type; the gather reads confidence.
        await registry.register(SimpleNamespace(
            id=f"agent-{i}", agent_type="crew", pool="crew", tier="crew", callsign=f"Crew{i}", confidence=0.8,
        ))
    await counselor.initialize(registry=registry)

    result = await counselor.act({"intent": "counselor_wellness_report"})

    assert result["result"]["total_assessed"] == 2


@pytest.mark.asyncio
async def test_the_booted_counselor_takes_the_operators_config(tmp_path) -> None:
    """The seam: startup gives the Counselor the operator's CounselorConfig."""
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(config=SystemConfig(counselor=CounselorConfig(sweep_max_agents=2)), data_dir=tmp_path)
    await rt.start()
    try:
        [counselor] = rt.registry.get_by_pool("counselor")
        assert isinstance(counselor, CounselorAgent)
        eligible = [
            agent for agent in rt.registry.all()
            if agent.id != counselor.id and getattr(agent, "tier", "") in ("", "domain", "crew")
        ]
        assert len(eligible) > 2  # premise: the bound, not the crew size, limits the sweep
        result = await counselor.act({"intent": "counselor_wellness_report"})
    finally:
        await rt.stop()

    assert result["result"]["total_assessed"] == 2


def test_the_removed_counselor_fields_are_gone_and_old_configs_still_load() -> None:
    assert set(CounselorConfig.model_fields) == {"trust_delta_threshold", "sweep_max_agents"}

    cfg = SystemConfig.model_validate({"counselor": {
        "enabled": False, "profile_retention_days": 7, "alert_on_red": False, "alert_on_yellow": True,
        "sweep_max_agents": 9,
    }})

    assert cfg.counselor.sweep_max_agents == 9
    assert cfg.counselor.trust_delta_threshold == 0.15
