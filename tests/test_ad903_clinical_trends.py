"""AD-903: tests for the gated clinical trend surface + indicator primitives (#866).

Endpoint tests use a REAL ``TestClient`` over the real counselor router with a
real-attribute ``_Runtime`` stub (BF-287 — no MagicMock at the store/auth
boundary; real ``SystemConfig()`` so ``require_crew_scope`` is pass-through, real
``ClearanceGrantStore(db_path="")``, real ``deque`` audit ring). Indicator
primitives (``get_zone_history`` / ``SelfSimilarityHistory`` / duty
``success_rate``) are unit-tested directly.

asyncio_mode="auto": grant seeding uses ``asyncio.run`` inside sync tests.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad903_clinical_trends.py -q -n 0
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.clearance_grants import ClearanceGrantStore
from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
from probos.cognitive.self_similarity_history import SelfSimilarityHistory
from probos.config import SystemConfig
from probos.duty_schedule import DutyScheduleTracker, DutyStatus
from probos.earned_agency import RecallTier


# --------------------------------------------------------------------------- #
# Real-attribute runtime stub
# --------------------------------------------------------------------------- #


class _Agent:
    def __init__(self, agent_id: str, agent_type: str) -> None:
        self.id = agent_id
        self.agent_type = agent_type


class _Registry:
    def __init__(self, agent_types: dict[str, str]) -> None:
        self._agent_types = agent_types

    def get(self, agent_id: str) -> _Agent | None:
        agent_type = self._agent_types.get(agent_id)
        if agent_type is None:
            return None
        return _Agent(agent_id, agent_type)

    def get_by_pool(self, pool: str) -> list[Any]:
        return []


class _Runtime:
    """Real-attribute stub exposing exactly what the counselor router reads."""

    def __init__(
        self,
        *,
        agent_types: dict[str, str] | None = None,
        grant_store: Any = None,
        profile_store: Any = None,
        self_similarity_history: Any = None,
        duty_schedule_tracker: Any = None,
    ) -> None:
        self.config = SystemConfig()
        self.registry = _Registry(agent_types or {})
        self.pools: dict[str, Any] = {}
        self.clearance_grant_store = grant_store
        self.clinical_access_audit: deque[dict[str, Any]] = deque(maxlen=1000)
        self._counselor_profile_store = profile_store
        # Indicator stores — None ⇒ that stream honest-degrades to []/null.
        self.trust_network = None
        self.proactive_loop = None
        self.self_similarity_history = self_similarity_history
        self.duty_schedule_tracker = duty_schedule_tracker


_AGENT_TYPES = {
    "crewman": "science",
    "counselor-1": "counselor",
    "chief": "engineering",
    "officer": "operations",
}


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.counselor import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _seed_grant(store: ClearanceGrantStore, grantee: str, scope: str) -> None:
    asyncio.run(store.issue_grant(grantee, RecallTier.BASIC, scope=scope))


# --------------------------------------------------------------------------- #
# Trend endpoint — gate behavior
# --------------------------------------------------------------------------- #


def test_trend_captain_no_as_agent_id_allows() -> None:
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get("/api/counselor/clinical/crewman")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "crewman"
    # All five indicator streams present (honest-degraded when stores absent).
    assert set(body["streams"]) == {
        "trust",
        "zones",
        "self_similarity",
        "hebbian_drift",
        "duty",
    }


def test_trend_counselor_as_agent_allows() -> None:
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get(
        "/api/counselor/clinical/crewman?as_agent_id=counselor-1"
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "crewman"


def test_trend_non_counselor_as_agent_denied() -> None:
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get(
        "/api/counselor/clinical/crewman?as_agent_id=officer"
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "clinical_access_denied"


def test_trend_subject_reading_own_denied() -> None:
    # The crewman (science) asserting their own id is the subject → denied.
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get(
        "/api/counselor/clinical/crewman?as_agent_id=crewman"
    )
    assert resp.status_code == 403


def test_trend_grantee_chief_allows() -> None:
    store = ClearanceGrantStore(db_path="")
    _seed_grant(store, "chief", "clinical:crewman")
    resp = _client(_Runtime(agent_types=_AGENT_TYPES, grant_store=store)).get(
        "/api/counselor/clinical/crewman?as_agent_id=chief"
    )
    assert resp.status_code == 200
    # The same chief is NOT unlocked for a different crewman (per-target grant).
    other = _client(_Runtime(agent_types=_AGENT_TYPES, grant_store=store)).get(
        "/api/counselor/clinical/crewman-2?as_agent_id=chief"
    )
    assert other.status_code == 403


# --------------------------------------------------------------------------- #
# Crew-wide endpoint — gate behavior
# --------------------------------------------------------------------------- #


def test_crew_wide_profiles_non_counselor_denied() -> None:
    # A per-target grant cannot unlock a crew-wide endpoint; officer has none.
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get(
        "/api/counselor/profiles?as_agent_id=officer"
    )
    assert resp.status_code == 403


def test_crew_wide_profiles_captain_passes_to_503_when_no_store() -> None:
    # Captain (no as_agent_id) passes the gate; existing 503 honest-degrade is
    # byte-identical (store absent).
    resp = _client(_Runtime(agent_types=_AGENT_TYPES)).get("/api/counselor/profiles")
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# Audit — a row on every allow AND deny
# --------------------------------------------------------------------------- #


def test_audit_row_on_every_allow_and_deny() -> None:
    runtime = _Runtime(agent_types=_AGENT_TYPES)
    client = _client(runtime)

    allow = client.get("/api/counselor/clinical/crewman")  # captain → allow
    deny = client.get("/api/counselor/clinical/crewman?as_agent_id=officer")  # → deny
    assert allow.status_code == 200
    assert deny.status_code == 403

    rows = list(runtime.clinical_access_audit)
    assert len(rows) == 2
    assert {r["query_type"] for r in rows} == {"clinical_trend"}
    granted = sorted(r["granted"] for r in rows)
    assert granted == [False, True]
    # Every row stamps the target and a requester id.
    assert all(r["target_agent_id"] == "crewman" for r in rows)
    assert all(r["requester_agent_id"] for r in rows)


# --------------------------------------------------------------------------- #
# Streams assembled from indicator stores (indicators only)
# --------------------------------------------------------------------------- #


def test_streams_populated_from_indicator_stores() -> None:
    sim_hist = SelfSimilarityHistory()
    sim_hist.record("crewman", 0.42, ts=1000.0)

    duty = DutyScheduleTracker(schedules={})
    duty.record_outcome("science", "wellness_sweep", success=True)

    runtime = _Runtime(
        agent_types=_AGENT_TYPES,
        self_similarity_history=sim_hist,
        duty_schedule_tracker=duty,
    )
    resp = _client(runtime).get("/api/counselor/clinical/crewman")
    assert resp.status_code == 200
    streams = resp.json()["streams"]

    assert streams["self_similarity"] == [{"timestamp": 1000.0, "similarity": 0.42}]
    # crewman is agent_type "science"; the recorded outcome → success_rate 1.0.
    assert streams["duty"]["success_rate"] == 1.0
    # Absent stores honest-degrade rather than erroring.
    assert streams["trust"] == {"events": [], "raw": None}
    assert streams["zones"] == []


# --------------------------------------------------------------------------- #
# Indicator primitive units
# --------------------------------------------------------------------------- #


def test_get_zone_history_returns_bounded_ring() -> None:
    breaker = CognitiveCircuitBreaker()
    state = breaker._get_state("crewman")  # documented internal accessor
    state.zone_history.extend([("green", 1.0), ("amber", 2.0), ("red", 3.0)])

    assert breaker.get_zone_history("crewman") == [
        ("green", 1.0),
        ("amber", 2.0),
        ("red", 3.0),
    ]
    # n slices to the last n.
    assert breaker.get_zone_history("crewman", n=2) == [("amber", 2.0), ("red", 3.0)]
    # n <= 0 and unknown agent degrade to [].
    assert breaker.get_zone_history("crewman", n=0) == []
    assert breaker.get_zone_history("nobody") == []


def test_self_similarity_history_record_and_recent() -> None:
    hist = SelfSimilarityHistory(cap=3)
    assert hist.recent("a") == []  # empty agent
    hist.record("a", 0.1, ts=1.0)
    hist.record("a", 0.2, ts=2.0)
    assert hist.recent("a") == [(1.0, 0.1), (2.0, 0.2)]
    # Bounded ring: cap=3, a 4th sample drops the oldest.
    hist.record("a", 0.3, ts=3.0)
    hist.record("a", 0.4, ts=4.0)
    assert hist.recent("a") == [(2.0, 0.2), (3.0, 0.3), (4.0, 0.4)]
    # n slicing and n <= 0.
    assert hist.recent("a", n=1) == [(4.0, 0.4)]
    assert hist.recent("a", n=0) == []


def test_duty_status_has_outcome_counters() -> None:
    status = DutyStatus(duty_id="d", agent_type="science")
    assert status.success_count == 0
    assert status.failure_count == 0


def test_duty_success_rate_none_then_value() -> None:
    tracker = DutyScheduleTracker(schedules={})
    # No outcomes recorded → None (distinguishes "no data" from "0%").
    assert tracker.success_rate("science") is None

    tracker.record_outcome("science", "d1", success=True)
    tracker.record_outcome("science", "d1", success=True)
    tracker.record_outcome("science", "d2", success=False)
    # 2 success / 3 total across the agent type's duties.
    assert tracker.success_rate("science") == 2 / 3

    # A different agent type is unaffected.
    assert tracker.success_rate("engineering") is None


def test_duty_record_outcome_does_not_touch_execution_count() -> None:
    tracker = DutyScheduleTracker(schedules={})
    tracker.record_outcome("science", "d1", success=True)
    status = tracker._status["science:d1"]  # documented internal map
    assert status.success_count == 1
    assert status.execution_count == 0  # owned by record_execution, untouched
