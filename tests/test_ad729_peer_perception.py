"""AD-729: peer avatar perception governance contract tests."""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

import pytest

from probos.avatars import peer_perception as pp
from probos.avatars.peer_perception import (
    ObservationRegister,
    PeerObservation,
    composite_impressions_for,
    observe_peer,
    register_permission_listener,
    request_permission,
    reset_state,
)
from probos.config import SystemConfig
from probos.crew_profile import CrewProfile, PeerPerceptionProfile
from probos.events import EventType


class _FakeAgent:
    def __init__(self, *, agent_id: str, enabled: bool, certified: bool) -> None:
        self.profile = CrewProfile(
            agent_id=agent_id,
            peer_perception=PeerPerceptionProfile(
                enabled=enabled, certified=certified
            ),
        )


class _FakeRegistry:
    """Real-shape registry: ``get(agent_id) -> agent | None``. BF-287 — no
    MagicMock at the substrate boundary."""

    def __init__(self) -> None:
        self._agents: dict[str, _FakeAgent] = {}

    def add(self, agent_id: str, *, enabled: bool = True, certified: bool = False) -> None:
        self._agents[agent_id] = _FakeAgent(
            agent_id=agent_id, enabled=enabled, certified=certified
        )

    def get(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


class _FakeRecordsStore:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write_entry(self, **kwargs: Any) -> str:
        self.writes.append(dict(kwargs))
        return kwargs["path"]


class _FakeRuntime:
    def __init__(
        self,
        *,
        config: SystemConfig,
        registry: _FakeRegistry,
        records_store: _FakeRecordsStore | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.records_store = records_store
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    async def emit_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, dict(payload)))


def _config_enabled() -> SystemConfig:
    cfg = SystemConfig()
    cfg.avatars.peer_perception_enabled = True
    cfg.avatars.peer_observation_max_per_pair_per_thread = 1
    cfg.avatars.peer_observation_decay_seconds = 3600
    return cfg


def _standard_runtime(records_store: _FakeRecordsStore | None = None) -> _FakeRuntime:
    registry = _FakeRegistry()
    registry.add("alpha", enabled=True, certified=True)   # observer (certified)
    registry.add("bravo", enabled=True, certified=False)  # observed (opted-in)
    return _FakeRuntime(config=_config_enabled(), registry=registry, records_store=records_store)


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()


# 1. operational register happy path.
@pytest.mark.asyncio
async def test_operational_register_happy_path() -> None:
    rt = _standard_runtime()
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="works precisely",
    )
    assert isinstance(result, PeerObservation)
    assert result.register == ObservationRegister.OPERATIONAL
    types = [et for et, _ in rt.emitted]
    assert EventType.PEER_OBSERVATION_RECORDED in types


# 2. personal register without permission_grant_id → declined.
@pytest.mark.asyncio
async def test_personal_without_grant_declined() -> None:
    rt = _standard_runtime()
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.PERSONAL,
        content="warm presence",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads
    assert decline_payloads[-1]["reason"] == "permission_required"


# 3. personal register with valid permission_grant_id → recorded.
@pytest.mark.asyncio
async def test_personal_with_valid_grant_recorded() -> None:
    rt = _standard_runtime()
    register_permission_listener("bravo", lambda obs, obsd: True)
    grant_id = await request_permission(
        runtime=rt, observer_id="alpha", observed_id="bravo",
    )
    assert grant_id is not None
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.PERSONAL,
        content="warm presence",
        permission_grant_id=grant_id,
    )
    assert result is not None
    assert result.permission_grant_id == grant_id


# 4. expired permission_grant_id → declined.
@pytest.mark.asyncio
async def test_expired_grant_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _standard_runtime()
    register_permission_listener("bravo", lambda obs, obsd: True)
    grant_id = await request_permission(
        runtime=rt, observer_id="alpha", observed_id="bravo",
    )
    assert grant_id is not None
    # Advance time past TTL.
    real_time = time.time
    monkeypatch.setattr(
        "probos.avatars.peer_perception.time.time",
        lambda: real_time() + pp._PERMISSION_TTL_SECONDS + 1,
    )
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.PERSONAL,
        content="warm presence",
        permission_grant_id=grant_id,
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "permission_invalid"


# 5. observed opt-out → declined.
@pytest.mark.asyncio
async def test_observed_opted_out_declined() -> None:
    registry = _FakeRegistry()
    registry.add("alpha", enabled=True, certified=True)
    registry.add("bravo", enabled=False, certified=False)  # opted-out
    rt = _FakeRuntime(config=_config_enabled(), registry=registry)
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "observed_opted_out"


# 6. observer uncertified → declined.
@pytest.mark.asyncio
async def test_observer_uncertified_declined() -> None:
    registry = _FakeRegistry()
    registry.add("alpha", enabled=True, certified=False)  # uncertified
    registry.add("bravo", enabled=True, certified=False)
    rt = _FakeRuntime(config=_config_enabled(), registry=registry)
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "observer_uncertified"


# 7. peer_perception_enabled=False → declined.
@pytest.mark.asyncio
async def test_capability_disabled_globally() -> None:
    cfg = SystemConfig()  # default peer_perception_enabled=False
    registry = _FakeRegistry()
    registry.add("alpha", enabled=True, certified=True)
    registry.add("bravo", enabled=True, certified=False)
    rt = _FakeRuntime(config=cfg, registry=registry)
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "capability_disabled"


# 8. utility-tier observer (enabled=False) → declined.
@pytest.mark.asyncio
async def test_utility_observer_disabled_declined() -> None:
    registry = _FakeRegistry()
    registry.add("util", enabled=False, certified=True)  # utility-tier
    registry.add("bravo", enabled=True, certified=False)
    rt = _FakeRuntime(config=_config_enabled(), registry=registry)
    result = await observe_peer(
        runtime=rt, observer_id="util", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "observer_disabled"


# 9. cross-federation observed (unknown registry entry) → declined.
@pytest.mark.asyncio
async def test_cross_federation_observed_declined() -> None:
    registry = _FakeRegistry()
    registry.add("alpha", enabled=True, certified=True)
    # bravo NOT in registry (treated as peer-mesh).
    rt = _FakeRuntime(config=_config_enabled(), registry=registry)
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "federation_review_required"


# 10. backend render unavailable → declined.
@pytest.mark.asyncio
async def test_backend_render_unavailable_declined() -> None:
    rt = _standard_runtime()
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
        backend_render_available=False,
    )
    assert result is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "backend_render_unavailable"


# 11. per-pair-per-thread cap (1) → second call declined.
@pytest.mark.asyncio
async def test_pair_thread_rate_limit() -> None:
    rt = _standard_runtime()
    first = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="x",
    )
    assert first is not None
    second = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="y",
    )
    assert second is None
    decline_payloads = [p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED]
    assert decline_payloads[-1]["reason"] == "pair_thread_rate_limited"


# 12. trust isolation source-scan.
def test_trust_isolation_source_scan() -> None:
    source = inspect.getsource(pp)
    lower = source.lower()
    assert "trust_network" not in lower
    assert "hebbian" not in lower
    assert "import probos.mesh.routing" not in lower


# 13. observation persists to RecordsStore.
@pytest.mark.asyncio
async def test_observation_persists_to_records_store() -> None:
    records = _FakeRecordsStore()
    rt = _standard_runtime(records_store=records)
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="works precisely",
    )
    assert result is not None
    assert len(records.writes) == 1
    write = records.writes[0]
    assert write["author"] == "alpha"
    assert "peer_observations/" in write["path"]
    assert "works precisely" in write["content"]
    assert "peer_observation" in write["tags"]


# 14. composite impression rendered when undecayed observations exist.
@pytest.mark.asyncio
async def test_composite_impressions_renders_when_active() -> None:
    rt = _standard_runtime()
    await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="precise work",
    )
    impressions = composite_impressions_for(runtime=rt, observed_id="bravo")
    assert impressions is not None
    assert "alpha" in impressions
    assert "precise work" in impressions


# 15. impression decay: observation older than decay window filtered.
@pytest.mark.asyncio
async def test_impressions_decay(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _standard_runtime()
    rt.config.avatars.peer_observation_decay_seconds = 3600
    await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="precise",
    )
    # Advance > decay window.
    real_time = time.time
    monkeypatch.setattr(
        "probos.avatars.peer_perception.time.time",
        lambda: real_time() + 4000,
    )
    impressions = composite_impressions_for(runtime=rt, observed_id="bravo")
    assert impressions is None


# 16. permission flow REQUESTED → GRANTED → recorded.
@pytest.mark.asyncio
async def test_permission_flow_requested_granted_recorded() -> None:
    rt = _standard_runtime()
    register_permission_listener("bravo", lambda obs, obsd: True)
    grant_id = await request_permission(
        runtime=rt, observer_id="alpha", observed_id="bravo",
    )
    assert grant_id is not None
    types = [et for et, _ in rt.emitted]
    assert EventType.PEER_OBSERVATION_PERMISSION_REQUESTED in types
    assert EventType.PEER_OBSERVATION_PERMISSION_GRANTED in types
    result = await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.PERSONAL,
        content="warm",
        permission_grant_id=grant_id,
    )
    assert result is not None


# 17. permission flow REQUESTED → DENIED (default deny-silent).
@pytest.mark.asyncio
async def test_permission_default_deny_silent() -> None:
    rt = _standard_runtime()
    # No listener registered → default deny-silent.
    grant_id = await request_permission(
        runtime=rt, observer_id="alpha", observed_id="bravo",
    )
    assert grant_id is None
    types = [et for et, _ in rt.emitted]
    assert EventType.PEER_OBSERVATION_PERMISSION_REQUESTED in types
    assert EventType.PEER_OBSERVATION_PERMISSION_DENIED in types


# 18. AD-731 invariant: peer-observation event payloads carry no image bytes.
@pytest.mark.asyncio
async def test_ad731_no_inline_image_bytes() -> None:
    """Peer observations are textual; assert the module's path never inlines
    image bytes via base64 or otherwise."""
    source = inspect.getsource(pp)
    assert "b64encode" not in source
    assert "base64.b64" not in source
    # Verify event payloads at runtime: no "image_url"/"source.base64" keys.
    rt = _standard_runtime()
    await observe_peer(
        runtime=rt, observer_id="alpha", observed_id="bravo",
        register=ObservationRegister.OPERATIONAL,
        content="works",
    )
    for _, payload in rt.emitted:
        assert "image_url" not in payload
        assert "source" not in payload
