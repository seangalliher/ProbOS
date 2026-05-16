"""AD-729c: Counselor pattern-monitoring tests."""
from __future__ import annotations

import inspect
import time
from typing import Any

import pytest

from probos.avatars.peer_perception import ObservationRegister, PeerObservation
from probos.cognitive import peer_observation_monitor as pom
from probos.cognitive.peer_observation_monitor import (
    CascadeSignalDetector,
    FrequencyDriftDetector,
    PatternFinding,
    PeerObservationMonitor,
    PermissionDenialPatternDetector,
    PrivilegedTierLeakageDetector,
    RegisterDriftDetector,
    StaticImpressionDetector,
    SycophancyPatternDetector,
    aggregate_health_metrics,
    default_detectors,
)
from probos.events import EventType


def _obs(
    observer_id: str,
    observed_id: str,
    *,
    content: str = "neutral",
    register: ObservationRegister = ObservationRegister.OPERATIONAL,
    age_seconds: float = 10.0,
) -> PeerObservation:
    now = time.time()
    return PeerObservation(
        observer_id=observer_id,
        observed_id=observed_id,
        register=register,
        content=content,
        timestamp=now - age_seconds,
        decay_after=now + 3600,
        permission_grant_id=None,
    )


# 1. FrequencyDriftDetector positive.
def test_frequency_drift_positive() -> None:
    det = FrequencyDriftDetector()
    obs = [_obs("a", "b") for _ in range(4)] + [_obs("a", "c") for _ in range(0)]
    finding = det.evaluate(obs, observer_id="a", observed_id="b", now=time.time())
    assert finding is not None
    assert finding.detector == "frequency_drift"


# 2. FrequencyDriftDetector negative (balanced distribution).
def test_frequency_drift_negative() -> None:
    det = FrequencyDriftDetector()
    obs = [_obs("a", "b")] + [_obs("a", "c") for _ in range(4)]
    finding = det.evaluate(obs, observer_id="a", observed_id="b", now=time.time())
    assert finding is None


# 3. RegisterDriftDetector positive (PERSONAL vocab in OPERATIONAL).
def test_register_drift_positive() -> None:
    det = RegisterDriftDetector()
    obs = [_obs("a", "b", content="She seems stressed today")]
    finding = det.evaluate(obs, observer_id="a", now=time.time())
    assert finding is not None
    assert finding.severity == "warn"


# 4. RegisterDriftDetector negative.
def test_register_drift_negative() -> None:
    det = RegisterDriftDetector()
    obs = [_obs("a", "b", content="Render output shows reduced amber luminance")]
    finding = det.evaluate(obs, observer_id="a", now=time.time())
    assert finding is None


# 5. CascadeSignalDetector positive.
def test_cascade_signal_positive() -> None:
    det = CascadeSignalDetector(min_observers=3, window_seconds=600.0)
    obs = [
        _obs("a", "x"),
        _obs("b", "x"),
        _obs("c", "x"),
    ]
    finding = det.evaluate(obs, observed_id="x", now=time.time())
    assert finding is not None


# 6. CascadeSignalDetector negative (single observer).
def test_cascade_signal_negative() -> None:
    det = CascadeSignalDetector(min_observers=3, window_seconds=600.0)
    obs = [_obs("a", "x"), _obs("a", "x"), _obs("a", "x")]
    finding = det.evaluate(obs, observed_id="x", now=time.time())
    assert finding is None


# 7. StaticImpressionDetector positive.
def test_static_impression_positive() -> None:
    det = StaticImpressionDetector(minimum_observations=3, max_distinct_content=1)
    obs = [_obs("a", "b", content="quiet"), _obs("a", "b", content="quiet"), _obs("a", "b", content="quiet")]
    finding = det.evaluate(obs, observer_id="a", observed_id="b", now=time.time())
    assert finding is not None


# 8. StaticImpressionDetector negative (varied content).
def test_static_impression_negative() -> None:
    det = StaticImpressionDetector(minimum_observations=3, max_distinct_content=1)
    obs = [_obs("a", "b", content="quiet"), _obs("a", "b", content="alert"), _obs("a", "b", content="focused")]
    finding = det.evaluate(obs, observer_id="a", observed_id="b", now=time.time())
    assert finding is None


# 9. PermissionDenialPatternDetector positive.
def test_permission_denial_positive() -> None:
    denials = {("a", "b"): 5}
    det = PermissionDenialPatternDetector(
        denial_threshold=3,
        denials_lookup=lambda o, p: denials.get((o, p), 0),
    )
    finding = det.evaluate([], observer_id="a", observed_id="b", now=time.time())
    assert finding is not None
    assert finding.evidence["denial_count"] == 5


# 10. PermissionDenialPatternDetector negative.
def test_permission_denial_negative() -> None:
    denials = {("a", "b"): 1}
    det = PermissionDenialPatternDetector(
        denial_threshold=3,
        denials_lookup=lambda o, p: denials.get((o, p), 0),
    )
    finding = det.evaluate([], observer_id="a", observed_id="b", now=time.time())
    assert finding is None


# 11. SycophancyPatternDetector positive (low-trust -> high-trust positive obs).
def test_sycophancy_positive() -> None:
    det = SycophancyPatternDetector(
        observer_trust_lookup=lambda _: 0.2,
        observed_trust_lookup=lambda _: 0.9,
    )
    obs = [
        _obs("low", "high", content="outstanding work today"),
        _obs("low", "high", content="impeccable performance"),
    ]
    finding = det.evaluate(obs, observer_id="low", observed_id="high", now=time.time())
    assert finding is not None
    assert finding.detector == "sycophancy_pattern"


# 12. SycophancyPatternDetector negative (peer trust gradient absent).
def test_sycophancy_negative_trust_balanced() -> None:
    det = SycophancyPatternDetector(
        observer_trust_lookup=lambda _: 0.6,
        observed_trust_lookup=lambda _: 0.6,
    )
    obs = [_obs("a", "b", content="outstanding work today")]
    finding = det.evaluate(obs, observer_id="a", observed_id="b", now=time.time())
    assert finding is None


# 13. PrivilegedTierLeakageDetector positive.
def test_privileged_tier_leakage_positive() -> None:
    det = PrivilegedTierLeakageDetector()
    obs = [_obs("a", "b", content="diagnosis indicates fatigue")]
    finding = det.evaluate(obs, observer_id="a", now=time.time())
    assert finding is not None
    assert finding.severity == "critical"


# 14. PrivilegedTierLeakageDetector negative.
def test_privileged_tier_leakage_negative() -> None:
    det = PrivilegedTierLeakageDetector()
    obs = [_obs("a", "b", content="produced report on time")]
    finding = det.evaluate(obs, observer_id="a", now=time.time())
    assert finding is None


# 15. Tier 1 escalation: first finding emits TIER_1 event.
@pytest.mark.asyncio
async def test_tier_1_escalation(tmp_path: Any) -> None:
    emitted: list[tuple[Any, Any]] = []

    async def emit(event_type: Any, payload: Any) -> None:
        emitted.append((event_type, dict(payload)))

    monitor = PeerObservationMonitor(
        detectors=[RegisterDriftDetector()],
        state_path=tmp_path / "state.json",
        emit_event=emit,
    )
    obs = [_obs("a", "b", content="She seems stressed today")]
    findings = await monitor.tick(obs, observer_id="a")
    assert len(findings) == 1
    event_types = [et for et, _ in emitted]
    assert EventType.PEER_OBSERVATION_PATTERN_FLAGGED in event_types
    assert EventType.PEER_OBSERVATION_INTERVENTION_TIER_1 in event_types


# 16. Tier 2 escalation: persistence -> certification revoked.
@pytest.mark.asyncio
async def test_tier_2_escalation_revokes_certification(tmp_path: Any) -> None:
    revoke_calls: list[tuple[str, str]] = []

    async def revoke(agent_id: str, reason: str) -> None:
        revoke_calls.append((agent_id, reason))

    emitted: list[Any] = []

    async def emit(event_type: Any, payload: Any) -> None:
        emitted.append(event_type)

    monitor = PeerObservationMonitor(
        detectors=[RegisterDriftDetector()],
        state_path=tmp_path / "state.json",
        emit_event=emit,
        revoke_certification=revoke,
    )
    obs = [_obs("a", "b", content="She seems stressed")]
    await monitor.tick(obs, observer_id="a")
    await monitor.tick(obs, observer_id="a")
    assert EventType.PEER_OBSERVATION_INTERVENTION_TIER_2 in emitted
    assert len(revoke_calls) == 1
    assert revoke_calls[0][0] == "a"


# 17. Tier 3 escalation: third persistence -> bridge-alert event.
@pytest.mark.asyncio
async def test_tier_3_escalation_emits_bridge_event(tmp_path: Any) -> None:
    emitted: list[Any] = []

    async def emit(event_type: Any, payload: Any) -> None:
        emitted.append(event_type)

    monitor = PeerObservationMonitor(
        detectors=[RegisterDriftDetector()],
        state_path=tmp_path / "state.json",
        emit_event=emit,
    )
    obs = [_obs("a", "b", content="She seems stressed")]
    await monitor.tick(obs, observer_id="a")
    await monitor.tick(obs, observer_id="a")
    await monitor.tick(obs, observer_id="a")
    assert EventType.PEER_OBSERVATION_INTERVENTION_TIER_3 in emitted


# 18. Aggregate metrics correctness.
def test_aggregate_metrics() -> None:
    obs = [
        _obs("a", "x"),
        _obs("a", "y"),
        _obs("b", "x", register=ObservationRegister.PERSONAL),
    ]
    metrics = aggregate_health_metrics(
        obs, permission_request_count=4, permission_grant_count=1,
    )
    assert metrics["total_observations"] == 3
    assert metrics["by_register"]["operational"] == 2
    assert metrics["by_register"]["personal"] == 1
    assert metrics["permission_grant_ratio"] == 0.25
    assert metrics["unique_observed_count"] == 2


# 19. Sampling cadence is the fixed 60s constant.
def test_monitor_interval_pinned_at_60s(tmp_path: Any) -> None:
    monitor = PeerObservationMonitor(
        detectors=[], state_path=tmp_path / "state.json",
    )
    assert monitor.interval_seconds == 60
    assert pom._MONITOR_INTERVAL_SECONDS == 60


# 20. Trust read-only source-scan: monitor module does not call
#     trust_network.record_outcome.
def test_trust_read_only_source_scan() -> None:
    source = inspect.getsource(pom)
    assert "trust_network.record_outcome" not in source
    assert "trust_network.update" not in source


# 21. Counselor-own-conduct: monitor module does NOT call observe_peer().
def test_counselor_own_conduct_no_observe_peer() -> None:
    source = inspect.getsource(pom)
    assert "observe_peer(" not in source


# 22. Intervention state survives restart (sidecar reload).
@pytest.mark.asyncio
async def test_state_persists_across_restart(tmp_path: Any) -> None:
    state_path = tmp_path / "state.json"

    async def emit(event_type: Any, payload: Any) -> None:
        return None

    monitor = PeerObservationMonitor(
        detectors=[RegisterDriftDetector()],
        state_path=state_path,
        emit_event=emit,
    )
    obs = [_obs("a", "b", content="She seems stressed")]
    await monitor.tick(obs, observer_id="a")
    # Sidecar should now exist.
    assert state_path.exists()
    # New monitor reads previous state.
    monitor2 = PeerObservationMonitor(
        detectors=[RegisterDriftDetector()],
        state_path=state_path,
        emit_event=emit,
    )
    # State key reconstructed.
    state_keys = list(monitor2._state.keys())
    assert ("register_drift", "a") in state_keys


# 23. Default detectors returns canonical seven.
def test_default_detectors_returns_seven() -> None:
    dets = default_detectors()
    assert len(dets) == 7
    names = {d.name for d in dets}
    assert names == {
        "frequency_drift", "register_drift", "cascade_signal",
        "static_impression", "permission_denial_pattern",
        "sycophancy_pattern", "privileged_tier_leakage",
    }
