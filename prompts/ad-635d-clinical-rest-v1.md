# AD-635d — Clinical Telemetry v4: REST Endpoints

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-635 v1 (`ClinicalTelemetryService.query_dream_history`, `query_agent_chain_traces`, `audit_log` property; COMPLETE), AD-635b (audit persistence; COMPLETE), AD-635c (`query_circuit_breaker_history`; COMPLETE), AD-516 (router registration pattern in `api.py`; COMPLETE).
**Estimated tests:** +14 (ceiling +18)
**Closes:** GH issue #393

## Problem

`src/probos/cognitive/clinical_telemetry.py:65+` ships a complete in-process clinical query facade — three clearance-gated query methods plus an audit-ring snapshot — but no HTTP surface. Every operator-facing tool that needs clinical visibility (HXI panels, the `/clinical` shell command in AD-635e, the proactive context bundle in AD-635f, external monitoring scripts) is blocked on a REST surface.

The roadmap entry at `docs/development/roadmap.md:5962` defines the scope literally: four GET endpoints under `/api/clinical/`, each a thin pass-through to the existing service.

## Solution

One new router module + two SEARCH/REPLACE additions to the existing router-include block in `api.py`, plus 14 tests.

1. **`src/probos/routers/clinical.py` (NEW)** — `APIRouter(prefix="/api/clinical", tags=["clinical"])` with four GET endpoints. Each endpoint returns 503 when `runtime.clinical_telemetry` is unavailable; otherwise it shape-converts query parameters, calls the service, and envelopes the result.
2. **`src/probos/api.py`** — extend the existing router-import tuple and the include-router loop to register `clinical.router`.
3. **`tests/test_ad635d_clinical_rest_endpoints.py` (NEW)** — 14 tests minimum, using `FastAPI` + `TestClient` + `dependency_overrides[get_runtime]` (mirrors `tests/test_ad561_intervention_classification.py`).

No EventTypes added. No mutation of `ClinicalTelemetryService`, `CircuitBreakerHistoryStore`, `ClinicalAuditStore`, `CognitiveCircuitBreaker`, `ClinicalTelemetryConfig`, `ProactiveCognitiveLoop`, `_authorize_clinical_query`, or any startup wiring. No changes outside the three named files (plus tracking files at sweep-end).

---

## Section 0 — `src/probos/routers/clinical.py` (NEW file)

**File:** `src/probos/routers/clinical.py`

Create the file with this exact content:

```python
"""ProbOS API — Clinical Telemetry routes (AD-635d).

Thin REST pass-through over ``ClinicalTelemetryService`` (AD-635 v1, AD-635b,
AD-635c). Four GET endpoints:

  * ``GET /api/clinical/dreams``
  * ``GET /api/clinical/chain-traces/{agent_id}``
  * ``GET /api/clinical/circuit-breakers/{agent_id}``
  * ``GET /api/clinical/audit``

The clearance gate lives inside the service (``_authorize_clinical_query``);
the REST layer is shape-conversion only. Every successful call is recorded
on the in-memory audit ring by the service itself, so the REST layer adds
no separate audit hook.

Service-unavailable (``runtime.clinical_telemetry`` is None or missing,
which is the default when ``ClinicalTelemetryConfig.enabled=False``)
returns HTTP 503. Clearance-denied calls return HTTP 200 with an empty
list (mirrors the underlying service contract — denial is logged on the
audit ring, not surfaced to the caller).

REST authentication is deferred to AD-635d-1 (matches every other
unauthenticated router in the current codebase).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clinical", tags=["clinical"])


def _service(runtime: Any) -> Any:
    """Return ``runtime.clinical_telemetry`` or None when unavailable."""
    return getattr(runtime, "clinical_telemetry", None)


def _service_unavailable() -> JSONResponse:
    """Construct a fresh 503 response per call (Response objects are not reused)."""
    return JSONResponse(
        {"error": "Clinical telemetry not available"},
        status_code=503,
    )


@router.get("/dreams")
async def get_dreams(
    requester_agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent dream-cycle reports, most recent first.

    Args:
        requester_agent_id: REQUIRED. Caller-asserted agent identity.
            The clearance gate inside ``query_dream_history`` validates it.
        limit: Max rows (default 20, hard-capped at 100).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_dream_history(
        requester_agent_id=requester_agent_id,
        limit=min(max(limit, 1), 100),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "dreams": rows,
    }


@router.get("/chain-traces/{agent_id}")
async def get_chain_traces(
    agent_id: str,
    requester_agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent cognitive-chain traces for one agent, most recent first.

    Args:
        agent_id: Path param — the target agent whose traces are queried.
        requester_agent_id: REQUIRED query param. Clearance-gated by service.
        limit: Max rows (default 20, hard-capped at 500).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_agent_chain_traces(
        requester_agent_id=requester_agent_id,
        target_agent_id=agent_id,
        limit=min(max(limit, 1), 500),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "target_agent_id": agent_id,
        "traces": rows,
    }


@router.get("/circuit-breakers/{agent_id}")
async def get_circuit_breaker_history(
    agent_id: str,
    requester_agent_id: str,
    limit: int = 50,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent circuit-breaker state + zone transitions for one agent.

    Args:
        agent_id: Path param — the target agent whose breaker history is queried.
        requester_agent_id: REQUIRED query param. Clearance-gated by service.
        limit: Max rows (default 50, hard-capped at 500).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_circuit_breaker_history(
        requester_agent_id=requester_agent_id,
        target_agent_id=agent_id,
        limit=min(max(limit, 1), 500),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "target_agent_id": agent_id,
        "transitions": rows,
    }


@router.get("/audit")
async def get_audit(
    limit: int = 200,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Snapshot of the in-memory clinical audit ring.

    Returns the most-recent ``limit`` entries (the ring is append-most-
    recent-last, so the slice is ``[-limit:]``). Hard-capped at 1000
    (matches the default ring capacity).

    NOT clearance-gated at the REST layer — same contract as the
    in-process ``audit_log`` property. AD-635d-1 covers REST-layer auth.
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    snapshot = service.audit_log
    capped = min(max(limit, 1), 1000)
    return {"audit": snapshot[-capped:]}
```

---

## Section 1 — `src/probos/api.py` (extend router registration)

**File:** `src/probos/api.py`

### Section 1a — extend the import tuple

**SEARCH** (locks the existing import tuple verbatim — verified at HEAD lines 191-198):

```python
    # ── Router registrations (AD-516) ─────────────────────────────────
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    )
```

**REPLACE** (adds `clinical` to the import group, preserving alphabetical-ish grouping by AD family — clinical lives next to counselor since both are AD-635 / clinical-adjacent):

```python
    # ── Router registrations (AD-516) ─────────────────────────────────
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    )
```

### Section 1b — extend the include-router loop

**SEARCH** (locks the existing include-router loop verbatim — verified at HEAD lines 199-208):

```python
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    ):
        app.include_router(r.router)
```

**REPLACE** (adds `clinical` to the iteration tuple in the same position as the import tuple — order matters for include consistency, NOT for routing precedence):

```python
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    ):
        app.include_router(r.router)
```

---

## Section 2 — `tests/test_ad635d_clinical_rest_endpoints.py` (NEW file)

**File:** `tests/test_ad635d_clinical_rest_endpoints.py`

Create the file with exactly this content:

```python
"""AD-635d v1: REST endpoints for clinical telemetry."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.clinical import router
from probos.routers.deps import get_runtime


# ---- Test harness (mirrors tests/test_ad561_intervention_classification.py) ----


class _FakeClinicalTelemetryService:
    """In-test stub for ClinicalTelemetryService — only the four surfaces
    the REST router consumes are stubbed out."""

    def __init__(
        self,
        *,
        dreams: list[dict[str, Any]] | None = None,
        traces: list[dict[str, Any]] | None = None,
        transitions: list[dict[str, Any]] | None = None,
        audit: list[dict[str, Any]] | None = None,
    ) -> None:
        self.query_dream_history = AsyncMock(return_value=list(dreams or []))
        self.query_agent_chain_traces = AsyncMock(return_value=list(traces or []))
        self.query_circuit_breaker_history = AsyncMock(
            return_value=list(transitions or [])
        )
        self._audit = list(audit or [])

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit)


class _FakeRuntime:
    def __init__(self, service: _FakeClinicalTelemetryService | None) -> None:
        self.clinical_telemetry = service


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ---- Dreams ----


def test_dreams_happy_path_returns_envelope_with_rows() -> None:
    rows = [{"ts": 1.0, "summary": "dream-a"}]
    service = _FakeClinicalTelemetryService(dreams=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/dreams", params={"requester_agent_id": "med-1"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {"requester_agent_id": "med-1", "dreams": rows}
    service.query_dream_history.assert_awaited_once_with(
        requester_agent_id="med-1", limit=20
    )


def test_dreams_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/dreams")

    assert resp.status_code == 422
    service.query_dream_history.assert_not_awaited()


def test_dreams_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/clinical/dreams", params={"requester_agent_id": "med-1"})

    assert resp.status_code == 503
    assert resp.json() == {"error": "Clinical telemetry not available"}


def test_dreams_clearance_denied_returns_200_with_empty_list() -> None:
    # Service-side denial → query_dream_history returns []. REST passes through.
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/dreams",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "no-clearance-agent",
        "dreams": [],
    }


def test_dreams_limit_query_param_is_clamped_to_cap() -> None:
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/dreams",
        params={"requester_agent_id": "med-1", "limit": 9999},
    )

    assert resp.status_code == 200
    service.query_dream_history.assert_awaited_once_with(
        requester_agent_id="med-1", limit=100
    )


# ---- Chain traces ----


def test_chain_traces_happy_path_returns_envelope_with_rows() -> None:
    rows = [{"chain_id": "c1", "agent_id": "khan-1"}]
    service = _FakeClinicalTelemetryService(traces=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "med-1",
        "target_agent_id": "khan-1",
        "traces": rows,
    }
    service.query_agent_chain_traces.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=20
    )


def test_chain_traces_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService()
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/chain-traces/khan-1")

    assert resp.status_code == 422
    service.query_agent_chain_traces.assert_not_awaited()


def test_chain_traces_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 503


def test_chain_traces_clearance_denied_returns_200_with_empty_list() -> None:
    service = _FakeClinicalTelemetryService(traces=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json()["traces"] == []


# ---- Circuit-breaker history ----


def test_circuit_breakers_happy_path_returns_envelope_with_transitions() -> None:
    rows = [
        {"ts": 100.0, "agent_id": "khan-1", "transition_kind": "state",
         "old_value": "closed", "new_value": "open", "trip_count": 1},
    ]
    service = _FakeClinicalTelemetryService(transitions=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "med-1",
        "target_agent_id": "khan-1",
        "transitions": rows,
    }
    service.query_circuit_breaker_history.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=50
    )


def test_circuit_breakers_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService()
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/circuit-breakers/khan-1")

    assert resp.status_code == 422


def test_circuit_breakers_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 503


def test_circuit_breakers_clearance_denied_returns_200_with_empty_list() -> None:
    service = _FakeClinicalTelemetryService(transitions=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json()["transitions"] == []


def test_circuit_breakers_limit_query_param_is_clamped_to_cap() -> None:
    service = _FakeClinicalTelemetryService(transitions=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1", "limit": 9999},
    )

    assert resp.status_code == 200
    service.query_circuit_breaker_history.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=500
    )


# ---- Audit ----


def test_audit_returns_audit_log_snapshot_envelope() -> None:
    audit = [
        {"ts": 1.0, "requester_agent_id": "a", "query_type": "dream_history",
         "granted": True, "result_count": 0},
        {"ts": 2.0, "requester_agent_id": "b", "query_type": "chain_traces",
         "granted": False, "result_count": 0},
    ]
    service = _FakeClinicalTelemetryService(audit=audit)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/audit")

    assert resp.status_code == 200
    assert resp.json() == {"audit": audit}


def test_audit_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/clinical/audit")

    assert resp.status_code == 503


def test_audit_limit_returns_most_recent_slice() -> None:
    audit = [
        {"ts": float(i), "requester_agent_id": f"a{i}",
         "query_type": "dream_history", "granted": True, "result_count": 0}
        for i in range(10)
    ]
    service = _FakeClinicalTelemetryService(audit=audit)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/audit", params={"limit": 3})

    assert resp.status_code == 200
    payload = resp.json()
    # Most-recent slice = audit[-3:] — entries ts=7,8,9.
    assert [row["ts"] for row in payload["audit"]] == [7.0, 8.0, 9.0]


```

**Test count:** 17 tests (4 dreams + 4 chain-traces + 5 circuit-breakers + 4 audit minus the redundant audit-clamp). Comfortable within the [+14, +18] window.

---

## What this AD does NOT change

- `src/probos/cognitive/clinical_telemetry.py` — untouched. No new methods, no new audit columns, no clearance-gate changes.
- `src/probos/cognitive/circuit_breaker_history_store.py` — untouched.
- `src/probos/cognitive/clinical_audit_store.py` — untouched.
- `src/probos/cognitive/circuit_breaker.py` — untouched.
- `src/probos/config.py` — untouched. No new config fields. The router activates whenever `runtime.clinical_telemetry` is non-None, which is already gated by `ClinicalTelemetryConfig.enabled`.
- `src/probos/startup/finalize.py` — untouched. Router is registered statically at app construction in `api.py`.
- `src/probos/runtime.py` — untouched.
- HXI / TypeScript / `ui/` — untouched. The HXI consumer of these endpoints is a follow-up AD when the panel work is scheduled.
- `src/probos/experience/shell.py` — untouched. The `/clinical` shell command is AD-635e (next wave).

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635d v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635c). |
| `docs/development/roadmap.md:5962` | Flip `*(Scoped, OSS, Issue #393)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook router-extension sibling pattern). |
| `prompts/wave-plan.yaml` (id: 64) | Set `status: done` post-archive. |
| GH issue #393 | Closed by Captain post-merge with commit hash. |

## Acceptance Criteria

1. New router file `src/probos/routers/clinical.py` exists with exactly four GET endpoints under `prefix="/api/clinical"`, `tags=["clinical"]`.
2. `src/probos/api.py` SEARCH/REPLACE blocks apply cleanly. `clinical` is added to BOTH the import tuple AND the include-router loop, in the same relative position (next to `counselor`).
3. New test file `tests/test_ad635d_clinical_rest_endpoints.py` exists with 17 tests covering: happy-path-with-envelope (×4 endpoints), service-unavailable-503 (×4), missing-requester-422 (×3 clearance-gated endpoints; audit has no requester param), clearance-denied-empty (×3 — audit endpoint is not clearance-gated per DLog #4), limit-clamp (×2 — dreams and circuit-breakers), audit-slice-direction (×1).
4. Pre-flight gate: `pytest tests/ -q -n 4 --dist=loadfile` passes at HEAD `27fd14f` with 11351 collected.
5. Post-build gate: `pytest tests/ -q -n 4 --dist=loadfile` passes with 11365 (+14) to 11369 (+18) collected. Outside that range → hard-stop and triage.
6. Existing `tests/test_ad635_*.py`, `tests/test_ad635b_*.py`, `tests/test_ad635c_*.py`, `tests/test_ad561_*.py` tests continue to pass unchanged.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-05, HEAD `27fd14f`)

```
src/probos/cognitive/clinical_telemetry.py:65    class ClinicalTelemetryService:
src/probos/cognitive/clinical_telemetry.py:93        async def query_dream_history(
src/probos/cognitive/clinical_telemetry.py:96            requester_agent_id: str,
src/probos/cognitive/clinical_telemetry.py:97            limit: int = 20,
src/probos/cognitive/clinical_telemetry.py:139       async def query_agent_chain_traces(
src/probos/cognitive/clinical_telemetry.py:142           requester_agent_id: str,
src/probos/cognitive/clinical_telemetry.py:143           target_agent_id: str,
src/probos/cognitive/clinical_telemetry.py:144           limit: int = 20,
src/probos/cognitive/clinical_telemetry.py:206       @property def audit_log(self) -> list[dict[str, Any]]:
src/probos/cognitive/clinical_telemetry.py:211       async def query_circuit_breaker_history(
src/probos/cognitive/clinical_telemetry.py:214           requester_agent_id: str,
src/probos/cognitive/clinical_telemetry.py:215           target_agent_id: str | None = None,
src/probos/cognitive/clinical_telemetry.py:216           limit: int = 50,
src/probos/cognitive/clinical_telemetry.py:284       def _authorize_clinical_query(self, agent_id: str) -> bool:
src/probos/startup/finalize.py:598               runtime.clinical_telemetry = service  (only assigned when cfg.enabled)
src/probos/api.py:191-198                        from probos.routers import (...) — verbatim SEARCH target for Section 1a
src/probos/api.py:199-208                        for r in (...): app.include_router(r.router) — verbatim SEARCH target for Section 1b
src/probos/routers/deps.py:13                    def get_runtime(request: Request) -> ProbOSRuntime
src/probos/routers/counselor.py:15               router = APIRouter(prefix="/api/counselor", tags=["counselor"]) — shape reference
src/probos/routers/counselor.py:23               JSONResponse({"error": "..."}, status_code=503) — 503 envelope reference
src/probos/routers/chain_traces.py:14            router = APIRouter(prefix="/api/chain-traces", tags=["chain-traces"]) — shape reference
src/probos/routers/chain_traces.py:30            min(max(limit, 1), 500) — clamp idiom reference
src/probos/routers/diagnostic_context.py:18      @router.get("") — shape reference
tests/test_ad561_intervention_classification.py:60  app.dependency_overrides[get_runtime] = lambda: runtime — harness reference
docs/development/roadmap.md:5962                 AD-635d *(Scoped, OSS, Issue #393)* — 4 endpoint paths verbatim
DECISIONS.md (highest AD)                         AD-695 — AD-635d unique
PROGRESS.md baseline                              11351 tests collected (post-Wave-63)
```
