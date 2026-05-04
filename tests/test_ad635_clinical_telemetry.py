"""AD-635 v1: Clinical Telemetry Query Facade — clearance-gated read-only access."""

from __future__ import annotations

import collections
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.clinical_telemetry import (
    CLINICAL_ROLES,
    QUALIFYING_TIERS,
    ClinicalTelemetryService,
)
from probos.cognitive.emergent_detector import EmergentDetector
from probos.config import ClinicalTelemetryConfig, SystemConfig
from probos.earned_agency import RecallTier
from probos.startup.finalize import _wire_clinical_telemetry


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_runtime(
    *,
    agents: dict[str, str] | None = None,    # agent_id -> agent_type
    journal_traces: list[dict] | None = None,
    journal_raises: bool = False,
    detector_dreams: list[dict] | None = None,
    has_detector: bool = True,
):
    """Build a minimal runtime stub for the service tests."""
    agents = agents or {}

    class _Reg:
        def get(self, aid):  # noqa: D401
            atype = agents.get(aid)
            if atype is None:
                return None
            return SimpleNamespace(agent_type=atype)

    class _Ont:
        # Map agent_type -> Post.clearance via the live mapping.
        _MAP = {"diagnostician": "FULL", "counselor": "ORACLE"}

        def get_post_for_agent(self, agent_type):
            cl = self._MAP.get(agent_type)
            if cl is None:
                return None
            return SimpleNamespace(clearance=cl)

    journal = AsyncMock()
    if journal_raises:
        journal.get_recent_chain_traces = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        journal.get_recent_chain_traces = AsyncMock(
            return_value=list(journal_traces or [])
        )

    runtime = SimpleNamespace(
        registry=_Reg(),
        ontology=_Ont(),
        cognitive_journal=journal,
        clearance_grant_store=None,
        acm=None,
    )
    if has_detector:
        det = SimpleNamespace(
            recent_dreams=lambda limit=20: list(detector_dreams or [])[-limit:],
        )
        runtime._emergent_detector = det
    return runtime


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_service_shape_and_module_constants():
    """Service exposes the two query methods + audit_log; constants are correct."""
    rt = _make_runtime()
    svc = ClinicalTelemetryService(rt, audit_max_entries=5)
    assert hasattr(svc, "query_dream_history")
    assert hasattr(svc, "query_agent_chain_traces")
    assert svc.audit_log == []
    # Audit ring is bounded.
    assert isinstance(svc._audit, collections.deque)
    assert svc._audit.maxlen == 5
    assert CLINICAL_ROLES == frozenset({"diagnostician", "counselor"})
    assert QUALIFYING_TIERS == frozenset({RecallTier.FULL, RecallTier.ORACLE})


@pytest.mark.asyncio
async def test_authorized_dream_query_returns_results():
    """Counselor (ORACLE) is authorized; query returns dream rows; audit granted=True."""
    dreams = [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]
    rt = _make_runtime(
        agents={"echo-1": "counselor"},
        detector_dreams=dreams,
    )
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_dream_history(requester_agent_id="echo-1", limit=20)
    assert out == dreams
    assert svc.audit_log[-1]["granted"] is True
    assert svc.audit_log[-1]["query_type"] == "dream_history"
    assert svc.audit_log[-1]["result_count"] == 3


@pytest.mark.asyncio
async def test_unauthorized_dream_query_returns_empty(caplog):
    """Non-clinical agent_type: returns []; logs warning; audit granted=False."""
    rt = _make_runtime(agents={"sci-1": "scientist"})
    svc = ClinicalTelemetryService(rt)
    with caplog.at_level("WARNING"):
        out = await svc.query_dream_history(requester_agent_id="sci-1")
    assert out == []
    assert svc.audit_log[-1]["granted"] is False
    assert any("AD-635" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_authorized_chain_traces_passes_target_agent_id():
    """Diagnostician (FULL) querying another agent passes target agent_id to journal."""
    traces = [{"chain_id": "c1", "agent_id": "engineer-7"}]
    rt = _make_runtime(
        agents={"chapel-1": "diagnostician"},
        journal_traces=traces,
    )
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_agent_chain_traces(
        requester_agent_id="chapel-1",
        target_agent_id="engineer-7",
        limit=10,
    )
    assert out == traces
    rt.cognitive_journal.get_recent_chain_traces.assert_awaited_once_with(
        limit=10, agent_id="engineer-7"
    )
    last = svc.audit_log[-1]
    assert last["granted"] is True
    assert last["target_agent_id"] == "engineer-7"
    assert last["result_count"] == 1


@pytest.mark.asyncio
async def test_unauthorized_chain_traces_returns_empty():
    """Unknown agent (no registry entry): returns []; audit granted=False."""
    rt = _make_runtime(agents={})  # registry returns None
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_agent_chain_traces(
        requester_agent_id="ghost",
        target_agent_id="engineer-7",
    )
    assert out == []
    assert svc.audit_log[-1]["granted"] is False
    # Journal is never called when authorization fails.
    rt.cognitive_journal.get_recent_chain_traces.assert_not_awaited()


@pytest.mark.asyncio
async def test_chain_traces_journal_failure_log_and_degrade(caplog):
    """Journal raises: returns []; warning logged; audit granted=True (gate passed)."""
    rt = _make_runtime(
        agents={"chapel-1": "diagnostician"},
        journal_raises=True,
    )
    svc = ClinicalTelemetryService(rt)
    with caplog.at_level("WARNING"):
        out = await svc.query_agent_chain_traces(
            requester_agent_id="chapel-1",
            target_agent_id="engineer-7",
        )
    assert out == []
    assert any("AD-635" in r.message for r in caplog.records)
    last = svc.audit_log[-1]
    assert last["granted"] is True
    assert last["result_count"] == 0


@pytest.mark.asyncio
async def test_audit_ring_is_bounded():
    """audit_max_entries caps the ring; oldest entries are evicted."""
    rt = _make_runtime(agents={"echo-1": "counselor"})
    svc = ClinicalTelemetryService(rt, audit_max_entries=3)
    for _ in range(5):
        await svc.query_dream_history(requester_agent_id="echo-1", limit=1)
    assert len(svc.audit_log) == 3


def test_emergent_detector_recent_dreams_accessor():
    """EmergentDetector.recent_dreams returns most-recent N (FIFO order)."""
    from unittest.mock import MagicMock

    det = EmergentDetector(
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        max_history=10,
    )
    for i in range(5):
        det._dream_history.append({"id": f"d{i}"})
    out = det.recent_dreams(limit=3)
    assert [d["id"] for d in out] == ["d2", "d3", "d4"]
    # limit larger than history returns full snapshot.
    assert det.recent_dreams(limit=99) == list(det._dream_history)
    # limit <= 0 returns [].
    assert det.recent_dreams(limit=0) == []
    # Returned list is a copy (mutation isolation).
    snap = det.recent_dreams(limit=10)
    snap.append({"id": "x"})
    assert "x" not in [d["id"] for d in det._dream_history]


def test_wirer_creates_runtime_attribute_when_enabled_and_no_op_when_disabled():
    """Wirer is a no-op when disabled; constructs runtime.clinical_telemetry when enabled."""
    rt_disabled = SimpleNamespace()
    cfg_disabled = SystemConfig()
    assert cfg_disabled.clinical_telemetry.enabled is False
    assert _wire_clinical_telemetry(runtime=rt_disabled, config=cfg_disabled) is False
    assert not hasattr(rt_disabled, "clinical_telemetry")

    rt_enabled = SimpleNamespace()
    cfg_enabled = SystemConfig(
        clinical_telemetry=ClinicalTelemetryConfig(
            enabled=True, audit_max_entries=42
        ),
    )
    assert _wire_clinical_telemetry(runtime=rt_enabled, config=cfg_enabled) is True
    assert isinstance(rt_enabled.clinical_telemetry, ClinicalTelemetryService)
    assert rt_enabled.clinical_telemetry._audit.maxlen == 42
