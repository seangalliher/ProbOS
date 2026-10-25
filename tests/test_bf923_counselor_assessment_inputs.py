"""BF-923 (#1652) M2: the Counselor reads real trust and records it; its assessment stays held (BF-921 D3).

Every trust network here is a real ``TrustNetwork`` unless a test is about a failing read, where the double
is ``create_autospec(TrustNetwork, instance=True)``.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from probos.cognitive.llm_client import BaseLLMClient
from probos.config import TRUST_DEFAULT
from probos.consensus.trust import TrustNetwork


def _counselor(trust: Any = None) -> Any:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = trust
    return counselor


class _OneCounselorPool:
    """Stands in for ``AgentRegistry.get_by_pool`` (``self_telemetry_domains.CounselorRegistry``)."""

    def __init__(self, counselor: Any) -> None:
        self._counselor = counselor

    def get_by_pool(self, pool_name: str) -> list[Any]:
        return [self._counselor] if pool_name == "counselor" else []


def test_the_trust_reading_uses_get_score_and_is_recorded_not_assessed() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)

    metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["trust_score"] == TRUST_DEFAULT  # held: the assessment input is unchanged (BF-921 D3)
    profile = counselor.get_profile("agent-a")
    assert profile.observed_baseline is not None
    assert profile.observed_baseline.trust_score == pytest.approx(0.8)
    assert [score for _, score in profile.trust_observations] == [pytest.approx(0.8)]


def test_the_baseline_is_captured_at_the_first_reading_only() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)

    counselor._gather_agent_metrics("agent-a")
    trust.record_outcome("agent-a", success=False, weight=5.0)
    later = trust.get_score("agent-a")
    counselor._gather_agent_metrics("agent-a")

    assert later < 0.8
    profile = counselor.get_profile("agent-a")
    assert profile.observed_baseline.trust_score == pytest.approx(0.8)
    assert [score for _, score in profile.trust_observations] == [pytest.approx(0.8), pytest.approx(later)]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["trust_update", "qualification_drift"])
async def test_a_real_trust_drop_moves_no_assessment_dm_alert_or_wellness_view(path: str, monkeypatch) -> None:
    """BF-921 D3's hold. A trust of 0.02 against TRUST_DEFAULT would be a -0.48 drift (wellness 0.28: unfit,
    a DM, and on the trust-update path a Bridge alert) if it were assessed. Held, the Counselor that reads it
    assesses exactly as one with no trust network, and the agent's own wellness view is the same."""
    from probos.cognitive.self_telemetry_domains import collect_wellness_state

    trust = TrustNetwork()
    trust.create_with_prior("agent-low", alpha=1.0, beta=49.0)
    held, control = _counselor(trust), _counselor(None)
    sent: dict[str, AsyncMock] = {}
    alerts: dict[str, MagicMock] = {}
    for name, counselor in (("held", held), ("control", control)):
        counselor.get_or_create_profile("agent-low")  # the trust-update handler skips an agent with no profile
        sent[name] = AsyncMock(return_value=True)
        alerts[name] = MagicMock()
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", sent[name])
        monkeypatch.setattr(counselor, "_alert_bridge", alerts[name])
        if path == "trust_update":
            await counselor._on_trust_update({"agent_id": "agent-low", "new_score": trust.get_score("agent-low")})
        else:
            await counselor._on_qualification_drift({
                "agent_id": "agent-low", "severity": "critical", "test_name": "bf923_probe",
                "drift_type": "unclassified", "z_score": 3.5,
            })

    held_profile = held.get_profile("agent-low")
    control_profile = control.get_profile("agent-low")
    assert len(held_profile.assessments) == len(control_profile.assessments) == 1

    def without_time(assessment: Any) -> dict[str, Any]:
        return {k: v for k, v in assessment.to_dict().items() if k != "timestamp"}

    assert without_time(held_profile.assessments[0]) == without_time(control_profile.assessments[0])
    assert held_profile.assessments[0].trust_drift == 0.0
    for name in ("held", "control"):
        sent[name].assert_not_called()
        alerts[name].assert_not_called()

    def wellness_view(counselor: Any) -> dict[str, Any]:
        view = collect_wellness_state("agent-low", registry=_OneCounselorPool(counselor))
        view.pop("assessed_at", None)
        return view

    assert wellness_view(held)
    assert wellness_view(held) == wellness_view(control)
    # The reading is real and on record.
    assert held_profile.trust_observations[-1][1] == pytest.approx(0.02)
    assert held_profile.observed_baseline.trust_score == pytest.approx(0.02)


def test_a_failing_trust_read_is_logged_at_warning_and_records_nothing(caplog) -> None:
    trust = create_autospec(TrustNetwork, instance=True)
    trust.get_score.side_effect = RuntimeError("trust store offline")
    counselor = _counselor(trust)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["trust_score"] == TRUST_DEFAULT
    assert counselor.get_profile("agent-a") is None
    assert any(
        record.levelno == logging.WARNING and "BF-923: trust read failed for agent-a" in record.getMessage()
        for record in caplog.records
    )


def test_the_hebbian_router_is_not_read() -> None:
    from probos.mesh.routing import HebbianRouter

    counselor = _counselor(None)
    router = create_autospec(HebbianRouter, instance=True)
    counselor._hebbian_router = router

    metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["hebbian_avg"] == 0.0
    assert router.mock_calls == []


def test_the_assessment_list_keeps_the_latest_entries() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT, CognitiveProfile, CounselorAssessment

    profile = CognitiveProfile(agent_id="agent-a")
    for i in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 5):
        profile.add_assessment(CounselorAssessment(timestamp=float(i), agent_id="agent-a"))

    assert len(profile.assessments) == COUNSELOR_PROFILE_HISTORY_LIMIT
    assert profile.assessments[0].timestamp == 5.0
    assert profile.assessments[-1].timestamp == float(COUNSELOR_PROFILE_HISTORY_LIMIT + 4)
    assert profile.last_assessed == float(COUNSELOR_PROFILE_HISTORY_LIMIT + 4)


def test_a_profile_saved_before_the_bound_loads_its_latest_assessments() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT, CognitiveProfile, CounselorAssessment

    data = CognitiveProfile(agent_id="agent-a").to_dict()
    data["assessments"] = [
        CounselorAssessment(timestamp=float(i), agent_id="agent-a").to_dict()
        for i in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 10)
    ]

    loaded = CognitiveProfile.from_dict(data)

    assert [a.timestamp for a in loaded.assessments] == [
        float(i) for i in range(10, COUNSELOR_PROFILE_HISTORY_LIMIT + 10)
    ]


def test_trust_observations_keep_the_latest_readings() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT

    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)
    for _ in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 3):
        counselor._gather_agent_metrics("agent-a")

    profile = counselor.get_profile("agent-a")
    assert len(profile.trust_observations) == COUNSELOR_PROFILE_HISTORY_LIMIT
    times = [when for when, _ in profile.trust_observations]
    assert times == sorted(times)


@pytest.mark.asyncio
async def test_the_readings_survive_the_profile_store(tmp_path) -> None:
    from probos.cognitive.counselor import CounselorProfileStore

    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)
    counselor._gather_agent_metrics("agent-a")
    counselor._gather_agent_metrics("agent-a")
    profile = counselor.get_profile("agent-a")

    store = CounselorProfileStore(data_dir=tmp_path)
    await store.start()
    try:
        await store.save_profile(profile)
        loaded = await store.load_profile("agent-a")
    finally:
        await store.stop()

    assert loaded is not None
    assert loaded.observed_baseline is not None
    assert loaded.observed_baseline.to_dict() == profile.observed_baseline.to_dict()
    assert loaded.trust_observations == profile.trust_observations
