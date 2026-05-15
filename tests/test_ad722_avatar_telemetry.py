"""AD-722: Avatar telemetry — read-side channel boundary tests.

Tier-2 log-and-degrade contract: every failure path returns the snapshot with
``degraded_reasons`` populated; the builder NEVER raises. The HTTP endpoint
NEVER returns 422 (malformed persisted DSL is a degraded field, not an
endpoint failure).

Read-only contract: zero state mutations, zero LLM calls, zero writes.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.dsl import AvatarDSL
from probos.avatars.telemetry import (
    BLOCKED_PITCH_FACTOR,
    BLOCKED_RATE_FACTOR,
    DEFAULT_PITCH,
    DEFAULT_RATE,
    DEFAULT_VOLUME,
    HIGH_TRUST_PITCH_FACTOR,
    LOW_TRUST_PITCH_FACTOR,
    MODULATION_DIVERGENCE_THRESHOLD,
    PITCH_BOUNDS,
    RATE_BOUNDS,
    RESPONDING_RATE_FACTOR,
    TIER3_RATE_FACTOR,
    TIER3_VOLUME_FACTOR,
    TRUST_DELTA_HIGH,
    TRUST_DELTA_LOW,
    VOLUME_BOUNDS,
    AgentSignalsSnapshot,
    AvatarTelemetrySnapshot,
    apply_voice_modulation,
    build_telemetry_snapshot,
)
from probos.bridge_alerts import AlertSeverity
from probos.crew_profile import AppearanceProfile, CrewProfile, VoiceProfile
from probos.types import AgentState


# ── Fakes ───────────────────────────────────────────────────────────────


class _FakeProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id: str):
        return self.profiles.get(agent_id)

    def get_or_create(self, agent_id: str, agent_type: str = "", pool: str = "", **_):
        if agent_id in self.profiles:
            return self.profiles[agent_id]
        crew = CrewProfile(agent_id=agent_id, agent_type=agent_type, pool=pool)
        self.profiles[agent_id] = crew
        return crew

    def update(self, profile: CrewProfile) -> None:
        self.profiles[profile.agent_id] = profile


class _FakeTrustNetwork:
    def __init__(self, history: list[float] | None = None) -> None:
        self._history = list(history) if history is not None else []

    def get_history(self, agent_id: str, limit: int = 20) -> list[float]:
        return list(self._history[-limit:])

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _FakeTrustNetworkNoHistoryMethod:
    """Mirrors a trust-network shape that lacks ``get_history`` (hasattr → False)."""

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _FakeAlert:
    def __init__(self, severity: AlertSeverity, related_agent_id: str | None) -> None:
        self.severity = severity
        self.related_agent_id = related_agent_id


class _FakeBridgeAlerts:
    def __init__(self, alerts: list[_FakeAlert] | None = None) -> None:
        self._alerts = list(alerts) if alerts is not None else []

    def get_recent_alerts(self, limit: int = 50) -> list[_FakeAlert]:
        return list(self._alerts[-limit:])


def _make_runtime(
    *,
    agent_id: str = "agent-007",
    agent_present: bool = True,
    crew: CrewProfile | None = None,
    trust_history: list[float] | None = None,
    trust_method_present: bool = True,
    bridge_alerts: _FakeBridgeAlerts | None | object = ...,  # sentinel for "default empty"
    last_reply_ts: float = 0.0,
    state: AgentState = AgentState.ACTIVE,
    telemetry_enabled: bool = True,
    avatars_enabled: bool = True,
) -> MagicMock:
    runtime = MagicMock()
    if agent_present:
        agent = MagicMock()
        agent.id = agent_id
        agent.agent_type = "counselor"
        agent.state = state
        agent.last_reply_emitted_at = last_reply_ts
    else:
        agent = None

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent

    runtime.profile_store = _FakeProfileStore()
    if crew is not None:
        runtime.profile_store.profiles[agent_id] = crew

    if trust_method_present:
        runtime.trust_network = _FakeTrustNetwork(history=trust_history)
    else:
        runtime.trust_network = _FakeTrustNetworkNoHistoryMethod()

    if bridge_alerts is ...:
        runtime.bridge_alerts = _FakeBridgeAlerts()
    else:
        runtime.bridge_alerts = bridge_alerts  # may be None

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = avatars_enabled
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatar_telemetry = MagicMock()
    cfg.avatar_telemetry.enabled = telemetry_enabled
    cfg.avatar_telemetry.inject_into_agent_context = False
    cfg.avatar_telemetry.mouth_active_window_seconds = 3.0
    cfg.avatar_telemetry.polling_interval_ms = 2000
    runtime.config = cfg

    return runtime


def _crew_with_full_dsl(agent_id: str = "agent-007") -> CrewProfile:
    crew = CrewProfile(agent_id=agent_id, agent_type="counselor")
    crew.appearance = AppearanceProfile(
        vrm_url="",
        color_palette_hint="warm",
        dsl=AvatarDSL().model_dump(),
    )
    crew.voice = VoiceProfile(pitch=0.9, rate=0.95, volume=0.8)
    return crew


# ── Snapshot tests ──────────────────────────────────────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_snapshot_happy_path():
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        last_reply_ts=time.time() - 0.1,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert isinstance(snap, AvatarTelemetrySnapshot)
    assert snap.agent_id == "agent-007"
    assert snap.expression_resting == "neutral"
    assert snap.dsl_summary is not None
    assert snap.applied_modulation is not None
    assert snap.mouth_active is True
    assert snap.degraded_reasons == ()
    assert pytest.approx(snap.current_signals.trust_delta, abs=1e-9) == 0.1


@pytest.mark.asyncio
async def test_snapshot_no_dsl_persisted():
    crew = CrewProfile(agent_id="agent-007", agent_type="counselor")
    crew.appearance = AppearanceProfile(vrm_url="", dsl=None)
    crew.voice = VoiceProfile()
    runtime = _make_runtime(crew=crew, trust_history=[0.4, 0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.dsl_summary is None
    assert "dsl_not_persisted" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_dsl_invalid():
    crew = CrewProfile(agent_id="agent-007", agent_type="counselor")
    # body.type must be a valid BodyType literal — "invalid_value" fails validation.
    crew.appearance = AppearanceProfile(
        vrm_url="", dsl={"body": {"type": "invalid_value"}},
    )
    crew.voice = VoiceProfile()
    runtime = _make_runtime(crew=crew, trust_history=[0.4, 0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.dsl_summary is None
    assert "dsl_invalid" in snap.degraded_reasons
    # Endpoint contract: 200-shape snapshot, never raises.
    assert isinstance(snap, AvatarTelemetrySnapshot)


@pytest.mark.asyncio
async def test_snapshot_no_appearance_profile():
    crew = CrewProfile(agent_id="agent-007", agent_type="counselor")
    crew.appearance = None  # type: ignore[assignment]
    crew.voice = VoiceProfile()
    runtime = _make_runtime(crew=crew, trust_history=[0.4, 0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert "appearance_profile_missing" in snap.degraded_reasons
    assert snap.dsl_summary is None
    # Voice + signals still populate.
    assert snap.applied_modulation is not None


@pytest.mark.asyncio
async def test_snapshot_trust_history_too_short():
    runtime = _make_runtime(crew=_crew_with_full_dsl(), trust_history=[0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.current_signals.trust_delta == 0.0
    assert "insufficient_trust_history" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_trust_network_no_method():
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        trust_method_present=False,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.current_signals.trust_delta == 0.0
    assert "insufficient_trust_history" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_bridge_alerts_unavailable():
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        bridge_alerts=None,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.current_signals.tier3_alert is False
    assert "bridge_alerts_unavailable" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_tier3_alert_for_agent():
    alerts = _FakeBridgeAlerts(alerts=[
        _FakeAlert(severity=AlertSeverity.ALERT, related_agent_id="agent-007"),
        _FakeAlert(severity=AlertSeverity.ADVISORY, related_agent_id="agent-007"),
        _FakeAlert(severity=AlertSeverity.ALERT, related_agent_id="other-agent"),
    ])
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        bridge_alerts=alerts,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.current_signals.tier3_alert is True


@pytest.mark.asyncio
async def test_snapshot_voice_profile_missing():
    crew = CrewProfile(agent_id="agent-007", agent_type="counselor")
    crew.appearance = AppearanceProfile(dsl=AvatarDSL().model_dump())
    crew.voice = None  # type: ignore[assignment]
    runtime = _make_runtime(crew=crew, trust_history=[0.4, 0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.applied_modulation is None
    assert "voice_profile_missing" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_no_persisted_profile_falls_back_to_defaults():
    """BF-2026-05-10: most crew never have a persisted CrewProfile until the
    Captain modifies their voice or appearance. Telemetry must fall through
    to typed defaults gracefully (mirrors routers/agents.py 3-tier fallback)
    rather than emitting scary "missing" warnings for normal startup state."""
    runtime = _make_runtime(crew=None, trust_history=[0.4, 0.5])
    snap = await build_telemetry_snapshot("agent-007", runtime)
    # Voice modulation IS computed using default_voice_for("counselor") seed.
    assert snap.applied_modulation is not None
    # Reason set distinguishes "fell back to defaults" from "data corrupt".
    fallback_reasons = {"crew_profile_default", "crew_profile_seeded"}
    assert any(r in fallback_reasons for r in snap.degraded_reasons), (
        f"expected one of {fallback_reasons} in {snap.degraded_reasons}"
    )
    # The OLD scary flags should NOT fire on this normal-startup path.
    assert "crew_profile_missing" not in snap.degraded_reasons
    assert "voice_profile_missing" not in snap.degraded_reasons


@pytest.mark.asyncio
async def test_snapshot_agent_not_found():
    runtime = _make_runtime(agent_present=False)
    snap = await build_telemetry_snapshot("agent-missing", runtime)
    assert snap.agent_id == "agent-missing"
    assert snap.degraded_reasons == ("agent_not_found",)
    assert snap.expression_resting is None
    assert snap.dsl_summary is None
    assert snap.applied_modulation is None
    assert snap.mouth_active is False


# ── Modulation tests ────────────────────────────────────────────────────


def test_modulation_manifest_loads_from_canonical_path():
    """AD-722-1: the manifest must be at the canonical repo location and
    parseable as JSON. This is the structural replacement for the old
    regex-based byte-parity test — drift is now impossible because both
    Python and TS read from this single file."""
    import json
    manifest_path = Path("ui/src/audio/modulation_manifest.json")
    assert manifest_path.is_file(), (
        f"AD-722-1 manifest missing at {manifest_path}"
    )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # Schema: every documented key present, no extras.
    expected_scalar = {
        "modulation_divergence_threshold", "trust_delta_high",
        "trust_delta_low", "responding_rate_factor", "blocked_rate_factor",
        "blocked_pitch_factor", "high_trust_pitch_factor",
        "low_trust_pitch_factor", "tier3_rate_factor", "tier3_volume_factor",
        "default_pitch", "default_rate", "default_volume",
    }
    expected_bounds = {"pitch_bounds", "rate_bounds", "volume_bounds"}
    # AD-722a-7: intent_rules nested-object key carries the v1 emotion taxonomy.
    expected_objects = {"intent_rules"}
    assert set(data.keys()) == expected_scalar | expected_bounds | expected_objects, (
        f"manifest schema drift: keys = {sorted(data.keys())}"
    )
    for k in expected_scalar:
        assert isinstance(data[k], (int, float)) and not isinstance(data[k], bool)
    for k in expected_bounds:
        assert isinstance(data[k], list) and len(data[k]) == 2
    # AD-722a-7: intent_rules schema check.
    intent_rules = data["intent_rules"]
    assert isinstance(intent_rules, dict)
    assert set(intent_rules.keys()) == {
        "warm", "concerned", "excited", "apologetic",
        "formal", "playful", "reassuring", "neutral",
    }
    for entry in intent_rules.values():
        assert set(entry.keys()) == {"pitch", "rate", "volume", "rule_name"}


def test_python_constants_reflect_manifest_values():
    """AD-722-1: every Python module-level constant must equal the manifest
    value at import. This is the structural drift detector: if either side
    changes without the other, the value mismatches."""
    import json
    data = json.loads(
        Path("ui/src/audio/modulation_manifest.json").read_text(encoding="utf-8")
    )
    assert MODULATION_DIVERGENCE_THRESHOLD == pytest.approx(data["modulation_divergence_threshold"])
    assert TRUST_DELTA_HIGH == pytest.approx(data["trust_delta_high"])
    assert TRUST_DELTA_LOW == pytest.approx(data["trust_delta_low"])
    assert RESPONDING_RATE_FACTOR == pytest.approx(data["responding_rate_factor"])
    assert BLOCKED_RATE_FACTOR == pytest.approx(data["blocked_rate_factor"])
    assert BLOCKED_PITCH_FACTOR == pytest.approx(data["blocked_pitch_factor"])
    assert HIGH_TRUST_PITCH_FACTOR == pytest.approx(data["high_trust_pitch_factor"])
    assert LOW_TRUST_PITCH_FACTOR == pytest.approx(data["low_trust_pitch_factor"])
    assert TIER3_RATE_FACTOR == pytest.approx(data["tier3_rate_factor"])
    assert TIER3_VOLUME_FACTOR == pytest.approx(data["tier3_volume_factor"])
    assert DEFAULT_PITCH == pytest.approx(data["default_pitch"])
    assert DEFAULT_RATE == pytest.approx(data["default_rate"])
    assert DEFAULT_VOLUME == pytest.approx(data["default_volume"])
    assert PITCH_BOUNDS == (pytest.approx(data["pitch_bounds"][0]),
                            pytest.approx(data["pitch_bounds"][1]))
    assert RATE_BOUNDS == (pytest.approx(data["rate_bounds"][0]),
                           pytest.approx(data["rate_bounds"][1]))
    assert VOLUME_BOUNDS == (pytest.approx(data["volume_bounds"][0]),
                             pytest.approx(data["volume_bounds"][1]))


def test_typescript_imports_manifest_not_inline_literals():
    """AD-722-1: voiceModulation.ts must read its constants from the
    manifest (via ``import manifest from './modulation_manifest.json'``)
    rather than inline literals. Regex-checks the TS source for the
    import statement and asserts no inline numeric literal is assigned
    to a known rule-table constant."""
    ts_path = Path("ui/src/audio/voiceModulation.ts")
    text = ts_path.read_text(encoding="utf-8")
    assert "from './modulation_manifest.json'" in text, (
        "TS file must import the manifest"
    )
    # Spot-check: no inline numeric literal for the divergence threshold.
    inline_pattern = re.compile(
        r"MODULATION_DIVERGENCE_THRESHOLD\s*[:=]\s*(?:number\s*=\s*)?-?\d+\.\d+",
    )
    assert not inline_pattern.search(text), (
        "TS file still contains inline literal for MODULATION_DIVERGENCE_THRESHOLD"
    )


def test_modulation_rule_composition_responding_plus_tier3():
    """Responding + tier3 rules compose multiplicatively (matches TS)."""
    profile = VoiceProfile(pitch=0.9, rate=1.0, volume=0.8)
    signals = AgentSignalsSnapshot(
        trust_delta=0.0, load=1.0, working_state="responding", tier3_alert=True,
    )
    mod = apply_voice_modulation(profile, signals)
    assert "responding_rate" in mod.fired_rules
    assert "tier3_rate_volume" in mod.fired_rules
    expected_rate = max(
        RATE_BOUNDS[0],
        min(RATE_BOUNDS[1], 1.0 * RESPONDING_RATE_FACTOR * TIER3_RATE_FACTOR),
    )
    assert mod.rate_factor == pytest.approx(expected_rate)


@pytest.mark.asyncio
async def test_mouth_active_within_window():
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        last_reply_ts=time.time() - 1.0,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.mouth_active is True


@pytest.mark.asyncio
async def test_mouth_active_outside_window():
    runtime = _make_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        last_reply_ts=time.time() - 10.0,
    )
    snap = await build_telemetry_snapshot("agent-007", runtime)
    assert snap.mouth_active is False


# ── Endpoint tests ──────────────────────────────────────────────────────


def _endpoint_runtime(**overrides) -> MagicMock:
    """Endpoint tests need extra runtime surface that ``probos.api.create_app``
    pokes during construction. We extend ``_make_runtime`` with the minimal
    additional members the FastAPI app touches at import/wire time.
    """
    runtime = _make_runtime(**overrides)
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi", "agent_type": "counselor",
        "agent_id": "agent-007",
        "display_name": "Counselor", "department": "bridge",
    }
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    return runtime


def test_endpoint_200_happy_path():
    from probos.api import create_app
    runtime = _endpoint_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        last_reply_ts=time.time() - 0.1,
    )
    client = TestClient(create_app(runtime))
    resp = client.get("/api/agent/agent-007/avatar-telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert body["dsl_summary"] is not None
    assert body["applied_modulation"] is not None
    assert "current_signals" in body
    assert "degraded_reasons" in body


def test_endpoint_404_unknown_agent():
    from probos.api import create_app
    runtime = _endpoint_runtime(agent_present=False)
    client = TestClient(create_app(runtime))
    resp = client.get("/api/agent/missing-007/avatar-telemetry")
    assert resp.status_code == 404


def test_endpoint_503_telemetry_disabled():
    from probos.api import create_app
    runtime = _endpoint_runtime(
        crew=_crew_with_full_dsl(),
        trust_history=[0.4, 0.5],
        telemetry_enabled=False,
    )
    client = TestClient(create_app(runtime))
    resp = client.get("/api/agent/agent-007/avatar-telemetry")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "avatar_telemetry_disabled"


# ── Static-grep contract test (singular call site) ─────────────────────


def test_mark_reply_emitted_singular_call_site():
    """``mark_reply_emitted()`` MUST have exactly one call site in production source.

    Multiple call sites are a Demeter / single-source-of-truth smell. The
    contract is that the DM reply pipeline at
    ``src/probos/cognitive/dm/reply_pipeline.py`` (AD-726, extracted from
    ``routers/agents.py``) is the SINGLE place that stamps the reply emission
    timestamp.
    """
    src_root = Path("src/probos")
    pattern = re.compile(r"\bmark_reply_emitted\s*\(\s*\)")
    call_sites: list[Path] = []
    for py_file in src_root.rglob("*.py"):
        # Skip the definition file itself.
        if py_file.name == "cognitive_agent.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        if pattern.search(text):
            call_sites.append(py_file)
    assert len(call_sites) == 1, (
        f"Expected exactly 1 call site, found {len(call_sites)}: {call_sites}"
    )
    assert call_sites[0].name == "reply_pipeline.py"
