"""AD-661 v1 — DiagnosticContextService tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.cognitive.diagnostic_context import (
    CHARS_PER_TOKEN,
    DiagnosticBundle,
    DiagnosticContextService,
    _estimate_tokens,
    _extract_keywords,
    _matches,
)


# --- Test 1: bundle frozen + to_dict round-trip ---
def test_bundle_frozen_and_to_dict_roundtrip() -> None:
    b = DiagnosticBundle(
        query="cpu",
        chain_traces=[{"chain_id": "c1", "step_name": "evaluate"}],
        procedures=[{"id": "p1", "name": "diagnose"}],
        episodes=[{"id": "e1", "text": "..."}],
        total_estimated_tokens=42,
        truncated=False,
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        b.query = "other"  # type: ignore[misc]
    d = b.to_dict()
    assert d["query"] == "cpu"
    assert d["chain_traces"][0]["step_name"] == "evaluate"
    assert d["total_estimated_tokens"] == 42
    assert d["truncated"] is False
    # to_dict returns a copy — mutating must not affect the bundle.
    d["chain_traces"].append({"chain_id": "c2"})
    assert len(b.chain_traces) == 1


# --- Test 2: keyword extractor + matcher ---
def test_keyword_extraction_and_matching() -> None:
    assert _extract_keywords("CPU usage spike") == ["cpu", "usage", "spike"]
    assert _extract_keywords("a b CPU") == ["cpu"]  # short tokens dropped
    assert _extract_keywords("") == []
    assert _matches("Step CPU evaluate", ["cpu"]) is True
    assert _matches("Step CPU evaluate", ["disk"]) is False
    assert _matches("anything", []) is True  # empty kw → include all
    assert _matches(None, ["cpu"]) is False
    assert _estimate_tokens("a" * 16) == 4
    assert _estimate_tokens("") == 0
    assert CHARS_PER_TOKEN == 4


# --- Test 3: chain_trace inclusion respects keyword + budget ---
@pytest.mark.asyncio
async def test_chain_trace_keyword_filter_and_budget() -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=[
        {"chain_id": "c1", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu_check", "intent": "diagnose",
         "error_truncated": "", "communication_context": ""},
        {"chain_id": "c2", "step_index": 0, "step_name": "REPORT",
         "sub_task_type": "ward_room_post", "intent": "compose",
         "error_truncated": "", "communication_context": ""},
        {"chain_id": "c3", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu_check", "intent": "diagnose",
         "error_truncated": "x" * 6000,  # forces budget overflow on its own
         "communication_context": ""},
    ])
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=2000)
    bundle = await svc.assemble(query="cpu", budget_tokens=2000)
    # "cpu" matches c1 and c3 (sub_task_type cpu_check); REPORT row excluded.
    assert all("cpu" in r["sub_task_type"] for r in bundle.chain_traces)
    # Budget should clip — c3's huge error_truncated > chain_budget (40% of 2000 = 800).
    assert bundle.truncated is True


# --- Test 4: procedure exemplar resolution via get_by_ids ---
@pytest.mark.asyncio
async def test_procedure_exemplar_resolution() -> None:
    proc = SimpleNamespace(
        id="p1", name="diagnose cpu",
        description="Investigate cpu spikes via memory check",
        intent_types=["diagnose"], compilation_level=2,
        trace_exemplars=["ep_a", "ep_b"],
    )
    store = MagicMock()
    store.list_active = AsyncMock(return_value=[
        {"id": "p1", "name": "diagnose cpu",
         "description": "Investigate cpu spikes via memory check",
         "intent_types": ["diagnose"], "compilation_level": 2},
    ])
    store.get = AsyncMock(return_value=proc)

    ep_a = SimpleNamespace(id="ep_a", text="cpu went to 100", agent_id="a1",
                           agent_type="science", timestamp=1.0,
                           importance=0.9, intent_type="diagnose")
    ep_b = SimpleNamespace(id="ep_b", text="cpu cooled down", agent_id="a1",
                           agent_type="science", timestamp=2.0,
                           importance=0.7, intent_type="diagnose")
    episodic = MagicMock()
    episodic.get_by_ids = AsyncMock(return_value=[ep_a, ep_b])

    runtime = SimpleNamespace(
        cognitive_journal=None, procedure_store=store, episodic_memory=episodic,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu")
    assert len(bundle.procedures) == 1
    assert bundle.procedures[0]["id"] == "p1"
    assert len(bundle.procedures[0]["exemplar_episodes"]) == 2
    episodic.get_by_ids.assert_awaited_once_with(["ep_a", "ep_b"])
    # Episodes flat list deduped — both exemplars appear once.
    ep_ids = [e["id"] for e in bundle.episodes]
    assert sorted(ep_ids) == ["ep_a", "ep_b"]


# --- Test 5: budget truncation sets truncated=True ---
@pytest.mark.asyncio
async def test_budget_truncation_sets_flag() -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=[
        {"chain_id": f"c{i}", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu", "intent": "diagnose",
         "error_truncated": "x" * 800, "communication_context": ""}
        for i in range(50)
    ])
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=1000)
    bundle = await svc.assemble(query="cpu", budget_tokens=1000)
    # 50 rows × ~200 tokens each >> 400-token chain budget.
    assert bundle.truncated is True
    assert len(bundle.chain_traces) < 50


# --- Test 6: episode dedup across multiple procedures ---
@pytest.mark.asyncio
async def test_episode_dedup_across_procedures() -> None:
    p1 = SimpleNamespace(
        id="p1", name="cpu", description="cpu check",
        intent_types=[], compilation_level=1,
        trace_exemplars=["ep_shared", "ep_a"],
    )
    p2 = SimpleNamespace(
        id="p2", name="cpu fallback", description="cpu fallback action",
        intent_types=[], compilation_level=1,
        trace_exemplars=["ep_shared", "ep_b"],
    )
    store = MagicMock()
    store.list_active = AsyncMock(return_value=[
        {"id": "p1", "name": "cpu", "description": "cpu check",
         "intent_types": [], "compilation_level": 1},
        {"id": "p2", "name": "cpu fallback",
         "description": "cpu fallback action",
         "intent_types": [], "compilation_level": 1},
    ])
    store.get = AsyncMock(side_effect=[p1, p2])

    eps = {
        "ep_shared": SimpleNamespace(
            id="ep_shared", text="cpu shared", agent_id="a", agent_type="x",
            timestamp=1.0, importance=0.5, intent_type=""),
        "ep_a": SimpleNamespace(
            id="ep_a", text="cpu A", agent_id="a", agent_type="x",
            timestamp=2.0, importance=0.4, intent_type=""),
        "ep_b": SimpleNamespace(
            id="ep_b", text="cpu B", agent_id="a", agent_type="x",
            timestamp=3.0, importance=0.4, intent_type=""),
    }
    episodic = MagicMock()
    episodic.get_by_ids = AsyncMock(side_effect=lambda ids: [eps[i] for i in ids if i in eps])

    runtime = SimpleNamespace(
        cognitive_journal=None, procedure_store=store, episodic_memory=episodic,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu")
    ep_ids = [e["id"] for e in bundle.episodes]
    assert ep_ids.count("ep_shared") == 1
    assert sorted(ep_ids) == ["ep_a", "ep_b", "ep_shared"]


# --- Test 7: collector failure degrades to empty section ---
@pytest.mark.asyncio
async def test_collector_failure_degrades_gracefully(caplog: pytest.LogCaptureFixture) -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(side_effect=RuntimeError("db down"))
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=2000)
    with caplog.at_level("WARNING"):
        bundle = await svc.assemble(query="cpu")
    assert bundle.chain_traces == []
    assert bundle.procedures == []
    assert bundle.episodes == []
    assert any("AD-661" in rec.message for rec in caplog.records)


# --- Test 8: API endpoint happy path + 503 when disabled ---
def test_api_endpoint_happy_path_and_503() -> None:
    from fastapi import FastAPI
    from probos.routers import diagnostic_context as dc_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(dc_router.router)

    # disabled runtime → 503
    disabled_runtime = SimpleNamespace(diagnostic_context_service=None)
    app.dependency_overrides[get_runtime] = lambda: disabled_runtime
    with TestClient(app) as client:
        resp = client.get("/api/diagnostic-context", params={"query": "cpu"})
        assert resp.status_code == 503

    # enabled runtime → 200 + bundle shape
    fake_bundle = DiagnosticBundle(
        query="cpu",
        chain_traces=[{"chain_id": "c1"}],
        procedures=[],
        episodes=[],
        total_estimated_tokens=10,
        truncated=False,
    )
    fake_service = MagicMock()
    fake_service.assemble = AsyncMock(return_value=fake_bundle)
    enabled_runtime = SimpleNamespace(diagnostic_context_service=fake_service)
    app.dependency_overrides[get_runtime] = lambda: enabled_runtime
    with TestClient(app) as client:
        resp = client.get(
            "/api/diagnostic-context",
            params={"query": "cpu", "budget": 4000, "agent_id": "a1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "cpu"
        assert body["chain_traces"][0]["chain_id"] == "c1"
    fake_service.assemble.assert_awaited_once()
    kwargs = fake_service.assemble.await_args.kwargs
    assert kwargs["query"] == "cpu"
    assert kwargs["budget_tokens"] == 4000
    assert kwargs["agent_id"] == "a1"
