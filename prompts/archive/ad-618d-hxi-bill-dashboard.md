# AD-618d: HXI Bill Dashboard

**Issue:** #204 (AD-618 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-618b (Bill Instance + Runtime — must be built first), AD-618c (Built-in Bills — must be built first)
**Files:** `src/probos/runtime.py` (EDIT — add `_bill_runtime` field), `src/probos/startup/structural_services.py` (EDIT — construct + load + register), `src/probos/startup/finalize.py` (EDIT — late-bind event callback + billet registry), `src/probos/sop/runtime.py` (EDIT — add definition registry), `src/probos/routers/bills.py` (NEW), `src/probos/routers/__init__.py` (EDIT — docstring only), `src/probos/api.py` (EDIT — register router), `ui/src/store/types.ts` (EDIT — add Bill types), `ui/src/store/useStore.ts` (EDIT — add Bill state + handlers), `ui/src/components/BillDashboard.tsx` (NEW), `ui/src/components/ViewSwitcher.tsx` (EDIT — add Bills tab), `tests/test_ad618d_hxi_bill_dashboard.py` (NEW), `ui/src/tests/BillDashboard.test.tsx` (NEW)

## Problem

AD-618b delivered BillRuntime — the service that activates bills, tracks step progression, and assigns roles. AD-618c delivered the built-in YAML bills. There is no way for the Captain to **see** active bills, **activate** a bill manually, or **monitor** step progression through the HXI.

AD-618d delivers the API routes and React components for bill visibility and control.

**Scope:**
- BillRuntime definition registry (addendum to AD-618b — 3 methods)
- FastAPI router: list bill definitions, list active instances, get instance detail, activate a bill, cancel an instance
- React dashboard: bill catalog view, active instance timeline, role assignment roster, step progression tracker
- WebSocket event handling for real-time bill lifecycle updates (refetch-on-event pattern)

**What this does NOT include:**
- Editing bill YAML in the HXI (future)
- Drag-and-drop role reassignment (future)
- Bill template wizard (future)

---

## Section 0a: Wire BillRuntime into Runtime

AD-618b built `BillRuntime` but added no startup wiring. AD-618c built the loaders but nothing calls them. This section wires it all together: the Runtime dataclass field, construction, bill loading, definition registration, and late-bound dependencies.

### Step 1: Add `_bill_runtime` field to the Runtime dataclass

**File:** `src/probos/runtime.py`

Add the type annotation in the dataclass field declarations (after `_records_store` at line 254):

```python
_bill_runtime: BillRuntime | None  # AD-618d
```

Add the initialization in `__init__` near the other structural service `None`-initializations (grep for `self._records_store = None`):

```python
# --- Bill System (AD-618d) ---
self._bill_runtime: BillRuntime | None = None
```

Add the import at the top of the file (TYPE_CHECKING block):

```python
from probos.sop.runtime import BillRuntime
```

### Step 2: Construct BillRuntime and load definitions in structural_services.py

**File:** `src/probos/startup/structural_services.py`

BillRuntime is structural infrastructure (no agent identity) — same category as SIF, TaskTracker, DirectiveStore. Add at the end of `init_structural_services()`, before the `logger.info("Startup [structural_services]: complete")` line and before constructing the result tuple.

```python
    # --- Bill System (AD-618d) ---
    from probos.sop.runtime import BillRuntime
    from probos.sop.loader import load_builtin_bills, load_custom_bills

    bill_runtime = BillRuntime(config=config.bill)
    logger.info("AD-618d: BillRuntime created")

    # Load and register built-in bills (AD-618c)
    builtin_bills = load_builtin_bills()
    for defn in builtin_bills.values():
        bill_runtime.register_definition(defn)

    # Load and register custom bills from Ship's Records
    # Custom bills dir lives alongside ship-records data.
    # RecordsStore may not be ready here (it's Phase 4, structural is Phase 6,
    # but the path is a well-known convention).
    _custom_bills_dir = data_dir / "ship-records" / "bills"
    custom_bills = load_custom_bills(_custom_bills_dir)
    for defn in custom_bills.values():
        bill_runtime.register_definition(defn)

    if builtin_bills or custom_bills:
        logger.info(
            "AD-618d: Registered %d bill definition(s) (%d built-in, %d custom)",
            len(builtin_bills) + len(custom_bills),
            len(builtin_bills),
            len(custom_bills),
        )
```

**Return the bill_runtime.** The function returns `(StructuralServicesResult, semantic_layer)`. Add `bill_runtime` to `StructuralServicesResult`:

**File:** `src/probos/startup/results.py` — add `bill_runtime: Any = None` to the `StructuralServicesResult` dataclass (grep for `class StructuralServicesResult`).

Then add `bill_runtime=bill_runtime` to the result construction:

```python
    result = StructuralServicesResult(
        sif=sif,
        initiative=initiative,
        build_queue=build_queue,
        build_dispatcher=build_dispatcher,
        task_tracker=task_tracker,
        service_profiles=service_profiles,
        directive_store=directive_store,
        bill_runtime=bill_runtime,  # AD-618d
    )
```

**In the caller** (the startup orchestrator that unpacks `StructuralServicesResult`), assign to runtime:

```python
runtime._bill_runtime = structural_result.bill_runtime
```

**Builder verification step:** Grep for `structural_result.sif` or `structural_result.task_tracker` to find the exact callsite where `StructuralServicesResult` is unpacked. Add the `_bill_runtime` assignment there.

### Step 3: Late-bind event callback and billet registry in finalize.py

**File:** `src/probos/startup/finalize.py`

Add after the BilletRegistry event callback wiring (after line 105: `logger.info("AD-595a: BilletRegistry wired")`):

```python
    # --- AD-618d: Wire BillRuntime event callback + billet registry ---
    if getattr(runtime, '_bill_runtime', None):
        runtime._bill_runtime.set_event_callback(
            lambda event_type, data: runtime._emit_event(event_type, data)
        )
        if runtime.ontology and runtime.ontology.billet_registry:
            runtime._bill_runtime.set_billet_registry(
                runtime.ontology.billet_registry
            )
        logger.info("AD-618d: BillRuntime wired (events + billet registry)")
```

**Why late-bind:** `BillRuntime.__init__` accepts `billet_registry=None` and `emit_event_fn=None` with explicit `set_billet_registry()` and `set_event_callback()` setters (sop/runtime.py lines 65-73). This matches the BilletRegistry pattern at finalize.py:101-104. Finalize runs after all services are constructed, so `runtime._emit_event` and `runtime.ontology.billet_registry` are guaranteed available.

**Startup ordering summary:**
1. Phase 4 (cognitive_services.py): RecordsStore created → `runtime._records_store` assigned
2. Phase 6 (structural_services.py): BillRuntime created → built-in bills loaded → custom bills loaded → definitions registered → `runtime._bill_runtime` assigned
3. Phase 8 (finalize.py): BillRuntime gets event callback + billet registry via late-binding setters

### Verified constructor args

| Parameter | Source | Type | Notes |
|-----------|--------|------|-------|
| `config` | `config.bill` | `BillConfig` | `SystemConfig.bill` at config.py:1111 |
| `billet_registry` | Late-bound in finalize.py | `Any` | `runtime.ontology.billet_registry` (property at runtime.py:930) |
| `emit_event_fn` | Late-bound in finalize.py | `Callable[[EventType, dict], None]` | `runtime._emit_event` (method at runtime.py:714, accepts `str | EventType`) |

---

## Section 0: Add Definition Registry to BillRuntime

**File:** `src/probos/sop/runtime.py` (EDIT)

BillRuntime (AD-618b) tracks instances but has no concept of loaded bill definitions — `load_builtin_bills()` and `load_custom_bills()` (AD-618c) return `dict[str, BillDefinition]` but nothing stores them on the runtime. The router needs to list and look up definitions.

Add a `_definitions` dict and three methods to `BillRuntime`. Place the dict in `__init__` after `self._instances`:

```python
        self._definitions: dict[str, BillDefinition] = {}  # bill_slug → BillDefinition
```

Add these methods in the "Queries" section (after `list_instances`, before `get_agent_assignments`):

```python
    def register_definition(self, defn: BillDefinition) -> None:
        """Register a loaded bill definition for lookup by the API layer."""
        self._definitions[defn.bill] = defn

    def list_definitions(self) -> list[BillDefinition]:
        """List all registered bill definitions."""
        return list(self._definitions.values())

    def get_definition(self, bill_id: str) -> BillDefinition | None:
        """Get a bill definition by slug."""
        return self._definitions.get(bill_id)
```

**Wiring point:** Section 0a handles BillRuntime construction, bill loading, and definition registration. The code above adds the methods that Section 0a's registration loop calls.

---

## Section 1: FastAPI Router — Bill System API

**File:** `src/probos/routers/bills.py` (NEW)

Follow the existing router pattern from `src/probos/routers/records.py`:
- `APIRouter(prefix="/api/bills", tags=["bills"])`
- `Depends(get_runtime)` from `probos.routers.deps`
- Return `JSONResponse` with error handling for missing services
- Access `runtime._bill_runtime` (same pattern as `runtime._records_store` in records.py)

### Endpoints

```python
"""ProbOS API — Bill System routes (AD-618d)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bills", tags=["bills"])


def _get_bill_runtime(runtime: Any) -> Any:
    """Extract BillRuntime, return None if unavailable."""
    return getattr(runtime, "_bill_runtime", None)


# ── Request models ───────────────────────────────────────────────

class ActivateBillRequest(BaseModel):
    """Request body for bill activation."""
    bill_id: str
    context: dict[str, Any] = {}


class CancelBillRequest(BaseModel):
    """Request body for bill cancellation."""
    reason: str = ""


# ── Bill Definitions (catalog) ───────────────────────────────────

@router.get("/definitions")
async def list_bill_definitions(runtime: Any = Depends(get_runtime)) -> Any:
    """List all loaded bill definitions (built-in + custom)."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    definitions = br.list_definitions()
    return {
        "definitions": [_serialize_definition(d) for d in definitions],
        "count": len(definitions),
    }


@router.get("/definitions/{bill_id}")
async def get_bill_definition(bill_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Get a specific bill definition by slug."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    defn = br.get_definition(bill_id)
    if not defn:
        return JSONResponse({"error": f"Bill '{bill_id}' not found"}, status_code=404)
    return _serialize_definition(defn)


# ── Bill Instances (active/completed) ────────────────────────────

@router.get("/instances")
async def list_bill_instances(
    status: str = "",
    bill_id: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """List bill instances, optionally filtered by status or bill_id."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    # list_instances takes status as InstanceStatus enum or None, and
    # bill_id as str or None. Convert empty strings to None.
    from probos.sop.instance import InstanceStatus
    _status = None
    if status:
        try:
            _status = InstanceStatus(status)
        except ValueError:
            return JSONResponse(
                {"error": f"Invalid status '{status}'"}, status_code=400,
            )
    instances = br.list_instances(
        status=_status,
        bill_id=bill_id or None,
    )
    return {
        "instances": [i.to_dict() for i in instances],
        "count": len(instances),
    }


@router.get("/instances/{instance_id}")
async def get_bill_instance(instance_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Get detailed state of a specific bill instance."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse({"error": f"Instance '{instance_id}' not found"}, status_code=404)
    return instance.to_dict()


@router.get("/instances/{instance_id}/assignments")
async def get_instance_assignments(instance_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Get role assignments for a bill instance (WQSB roster).

    Reads instance.role_assignments directly — NOT get_agent_assignments(),
    which takes an agent_id and returns "what bills is this agent in?"
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse({"error": f"Instance '{instance_id}' not found"}, status_code=404)
    # role_assignments is dict[str, RoleAssignment] — iterate values
    assignments = [
        {
            "role_id": ra.role_id,
            "agent_id": ra.agent_id,
            "agent_type": ra.agent_type,
            "callsign": ra.callsign,
            "department": ra.department,
        }
        for ra in instance.role_assignments.values()
    ]
    return {
        "instance_id": instance_id,
        "assignments": assignments,
        "count": len(assignments),
    }


# ── Bill Actions ─────────────────────────────────────────────────

@router.post("/activate")
async def activate_bill(body: ActivateBillRequest, runtime: Any = Depends(get_runtime)) -> Any:
    """Activate a bill — creates an instance with WQSB role assignments.

    activate() takes a BillDefinition (not a bill_id), so we look up
    the definition first from the registry.
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    defn = br.get_definition(body.bill_id)
    if not defn:
        return JSONResponse(
            {"error": f"Bill '{body.bill_id}' not found"}, status_code=404,
        )
    try:
        from probos.sop.runtime import BillActivationError
        instance = await br.activate(defn, activation_data=body.context)
    except BillActivationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Bill activation failed: %s", e, exc_info=True)
        return JSONResponse({"error": "Activation failed"}, status_code=500)
    return instance.to_dict()


@router.post("/instances/{instance_id}/cancel")
async def cancel_bill_instance(
    instance_id: str,
    body: CancelBillRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Cancel an active bill instance.

    cancel() returns bool, not BillInstance. Fetch instance after cancel
    for the response payload.
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    if not br.cancel(instance_id, reason=body.reason):
        return JSONResponse(
            {"error": "Instance not found or already terminal"}, status_code=404,
        )
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse({"error": "Instance not found"}, status_code=404)
    return instance.to_dict()


# ── Serializers ──────────────────────────────────────────────────

def _serialize_definition(defn: Any) -> dict[str, Any]:
    """Serialize a BillDefinition for the API response.

    Field names match schema.py (AD-618a):
    - BillDefinition: bill, title, description, version, activation
    - BillRole: id, department, count, qualifications
    - BillStep: id, name, role, action, gateway_type, timeout
    """
    return {
        "bill_id": defn.bill,       # slug identifier
        "title": defn.title,
        "description": defn.description,
        "version": defn.version,
        "activation": {
            "trigger": defn.activation.trigger,
            "authority": defn.activation.authority,
        } if defn.activation else None,
        "roles": [
            {
                "role_id": r.id,
                "department": r.department,
                "count": r.count,
                "qualifications": r.qualifications,
            }
            for r in (defn.roles.values() if isinstance(defn.roles, dict) else defn.roles or [])
        ],
        "steps": [
            {
                "step_id": s.id,
                "name": s.name,
                "role": s.role,
                "action": s.action,
                "gateway_type": s.gateway_type.value if hasattr(s.gateway_type, "value") else str(s.gateway_type),
                "timeout": s.timeout,
            }
            for s in (defn.steps or [])
        ],
        "step_count": len(defn.steps or []),
        "role_count": len(defn.roles) if defn.roles else 0,
    }
```

**Key design notes:**

- **Instance serialization uses `BillInstance.to_dict()`** (AD-618b Section 3, line 184). The dataclass owns its serialization shape — the router doesn't duplicate it.
- **Definition serialization uses a custom serializer** because `BillDefinition` has no `to_dict()` method. Field names match `schema.py` exactly: `bill` not `bill_id`, `title` not `name`, `gateway_type` not `gateway`, etc.
- **`activate()` takes `BillDefinition` not `bill_id`** (AD-618b Section 4, line 326). Router looks up the definition first.
- **`cancel()` returns `bool`** (AD-618b Section 4, line 602). Router checks return value, then fetches instance for the response.
- **`get_agent_assignments(agent_id)` returns "what bills is this agent in?"** — NOT "what assignments exist within this instance." For instance assignments, read `instance.role_assignments` directly.
- **`list_instances()` takes `status: InstanceStatus | None`** — an enum, not a string. Router converts the query param.
- **`role_assignments` and `step_states` are `dict[str, ...]`** — not lists. `to_dict()` handles the serialization. The assignments endpoint iterates `.values()`.

---

## Section 2: Register Router in API

**File:** `src/probos/api.py` (EDIT)

Add the bills router to both the import block and the iteration tuple. Builder must update **both** locations:

### Current code (lines 192–203):
```python
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph,
    ):
```

### New code:
```python
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph, bills,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph, bills,
    ):
```

---

## Section 3: TypeScript Types

**File:** `ui/src/store/types.ts` (EDIT)

Add Bill System view types after the existing `CrewManifestEntry` interface (end of file). Types match the serialized shapes from Section 1 — `_serialize_definition` for definitions, `BillInstance.to_dict()` for instances.

```typescript
// AD-618d: Bill System types

export interface BillDefinitionView {
  bill_id: string;    // BillDefinition.bill slug
  title: string;
  description: string;
  version: number;
  activation: {
    trigger: string;
    authority: string;
  } | null;
  roles: BillRoleView[];
  steps: BillStepView[];
  step_count: number;
  role_count: number;
}

export interface BillRoleView {
  role_id: string;   // BillRole.id
  department: string;
  count: string;     // "1" or "1-3"
  qualifications: string[];
}

export interface BillStepView {
  step_id: string;   // BillStep.id
  name: string;
  role: string;      // BillStep.role (role ID reference)
  action: string;    // StepAction value
  gateway_type: string;  // GatewayType value
  timeout: number;
}

export interface BillInstanceView {
  id: string;             // BillInstance.id (NOT instance_id)
  bill_id: string;
  bill_title: string;
  bill_version: number;
  status: 'pending' | 'active' | 'completed' | 'failed' | 'cancelled';
  activated_by: string;
  activated_at: number;
  completed_at: number | null;
  activation_data: Record<string, unknown>;
  role_assignments: Record<string, BillRoleAssignmentView>;  // dict keyed by role_id
  step_states: Record<string, BillStepStateView>;            // dict keyed by step_id
}

export interface BillRoleAssignmentView {
  agent_id: string;
  agent_type: string;
  callsign: string;
  department: string;
}

export interface BillStepStateView {
  status: 'pending' | 'active' | 'completed' | 'skipped' | 'failed' | 'blocked';
  assigned_agent_id: string | null;
  assigned_agent_callsign: string | null;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
}
```

**Key differences from prior draft:**
- `BillInstanceView.id` not `instance_id` — matches `BillInstance.to_dict()` which outputs `"id": self.id`
- `role_assignments` is `Record<string, ...>` (dict), not array — matches `to_dict()` output
- `step_states` is `Record<string, ...>` (dict), not array — matches `to_dict()` output
- `activation_data` not `context` — matches `BillInstance.activation_data`
- `BillRoleView` has `count` (string) not `min_trust` (doesn't exist) — matches `BillRole`
- `BillStepView` has `gateway_type` not `gateway`, `role` not `assigned_role`, `timeout` not `timeout_seconds` — matches `BillStep`
- No `category` field on definitions — not in schema
- No `title` on roles — not in schema
- No `required` on steps — not in schema

---

## Section 4: Zustand Store Slice

**File:** `ui/src/store/useStore.ts` (EDIT)

Add Bill System state and actions to the existing Zustand store. Follow the pattern used by the workforce slice (work items, bookings).

### State fields

Add to the store's state interface:

```typescript
// Bill System (AD-618d)
billDefinitions: BillDefinitionView[];
billInstances: BillInstanceView[];
billSelectedInstanceId: string | null;
```

### Initial values

```typescript
billDefinitions: [],
billInstances: [],
billSelectedInstanceId: null,
```

### Actions

Add these actions to the store:

```typescript
// Bill System (AD-618d)
fetchBillDefinitions: async () => {
  try {
    const res = await fetch('/api/bills/definitions');
    if (res.ok) {
      const data = await res.json();
      set({ billDefinitions: data.definitions ?? [] });
    }
  } catch { /* log-and-degrade */ }
},

fetchBillInstances: async (status?: string) => {
  try {
    const url = status ? `/api/bills/instances?status=${status}` : '/api/bills/instances';
    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      set({ billInstances: data.instances ?? [] });
    }
  } catch { /* log-and-degrade */ }
},

activateBill: async (billId: string, context?: Record<string, unknown>) => {
  try {
    const res = await fetch('/api/bills/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bill_id: billId, context: context ?? {} }),
    });
    if (res.ok) {
      // Refetch instead of optimistic append — the WS bill_activated
      // event would duplicate an optimistic entry.
      await get().fetchBillInstances();
      const instance = await res.json();
      return instance;
    }
  } catch { /* log-and-degrade */ }
  return null;
},

selectBillInstance: (instanceId: string | null) => {
  set({ billSelectedInstanceId: instanceId });
},
```

### WebSocket Event Handlers

In the existing WebSocket message handler (the `switch` block that processes `event.type` — search for `case 'trust_update'`), add handlers for bill events. **All bill events use the refetch-on-event pattern** — the event payloads (AD-618b) are lightweight summaries (e.g., `instance_id`, `step_id`, `duration_s`), NOT full instance snapshots. Refetching gets the authoritative state from `BillInstance.to_dict()`.

```typescript
// Bill System events (AD-618d) — refetch on any lifecycle event
case 'bill_activated':
case 'bill_step_started':
case 'bill_step_completed':
case 'bill_step_failed':
case 'bill_completed':
case 'bill_failed':
case 'bill_cancelled':
case 'bill_role_assigned': {
  get().fetchBillInstances();
  break;
}
```

**Why refetch-on-event:** AD-618b's event payloads contain summary fields (e.g., `BILL_STEP_COMPLETED` has `instance_id, bill_id, step_id, action, agent_id, agent_type, duration_s` — no `status` string, no `started_at`, no `completed_at`). Mapping these partial payloads onto the full `BillInstanceView` would require reconstructing state the backend already has. Refetch costs one extra HTTP roundtrip per event but stays in sync with backend truth. A future optimization (AD-618d+) can add richer event payloads to eliminate the roundtrip.

**Builder note:** Find the existing WebSocket handler by searching for `case 'trust_update'` in `useStore.ts`. Add the bill cases in the same switch block.

---

## Section 5: Bill Dashboard Component

**File:** `ui/src/components/BillDashboard.tsx` (NEW)

A full-page component with two panels:

1. **Left panel — Bill Catalog**: Lists all bill definitions. Each card shows bill title, role count, step count, trigger type. A "SET CONDITION" button activates the bill.
2. **Right panel — Active Instances**: Lists active bill instances. Clicking an instance expands to show step progression timeline and role assignments.

Follow the styling conventions from `WorkBoard.tsx` (CSS-in-JS inline styles, dark theme colors, monospace font for data). Use `useStore` hooks to access state.

**Key type adaptations for the component:**
- `instance.role_assignments` is `Record<string, BillRoleAssignmentView>` — use `Object.entries()` to iterate
- `instance.step_states` is `Record<string, BillStepStateView>` — use `Object.entries()` to iterate
- Instance ID field is `instance.id` not `instance.instance_id`
- Bill title on definitions is `defn.title` not `defn.name`

```tsx
/* Bill Dashboard — Bill System HXI (AD-618d) */

import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { BillDefinitionView, BillInstanceView } from '../store/types';

// ── Status colors ─────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  pending: '#8888a0',
  active: '#50b0d0',
  completed: '#50b080',
  failed: '#d05050',
  cancelled: '#a08040',
  skipped: '#888',
  blocked: '#665500',
};

// ── Bill Definition Card ──────────────────────────────────────────
function BillCard({ defn, onActivate }: {
  defn: BillDefinitionView;
  onActivate: (billId: string) => void;
}) {
  return (
    <div style={{
      background: '#1a1a2e', border: '1px solid #333', borderRadius: 6,
      padding: 12, marginBottom: 8, cursor: 'pointer',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{defn.title}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onActivate(defn.bill_id); }}
          style={{
            background: '#304060', border: '1px solid #5090d0', borderRadius: 4,
            color: '#5090d0', padding: '4px 12px', cursor: 'pointer', fontSize: 12,
          }}
        >
          SET CONDITION
        </button>
      </div>
      <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>{defn.description}</div>
      <div style={{ color: '#666', fontSize: 11, marginTop: 6 }}>
        {defn.role_count} roles · {defn.step_count} steps
        {defn.activation?.trigger ? ` · trigger: ${defn.activation.trigger}` : ''}
      </div>
    </div>
  );
}

// ── Step Progress Bar ─────────────────────────────────────────────
function StepProgress({ instance }: { instance: BillInstanceView }) {
  const steps = Object.entries(instance.step_states);
  if (steps.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: 2, marginTop: 8 }}>
      {steps.map(([stepId, ss]) => (
        <div
          key={stepId}
          title={`${stepId}: ${ss.status}${ss.assigned_agent_callsign ? ` (${ss.assigned_agent_callsign})` : ''}`}
          style={{
            flex: 1, height: 6, borderRadius: 2,
            background: STATUS_COLORS[ss.status] ?? '#444',
          }}
        />
      ))}
    </div>
  );
}

// ── Instance Detail ───────────────────────────────────────────────
function InstanceDetail({ instance }: { instance: BillInstanceView }) {
  const roles = Object.entries(instance.role_assignments);
  const steps = Object.entries(instance.step_states);

  return (
    <div style={{ padding: 12, background: '#12122a', borderRadius: 6, marginTop: 8 }}>
      <h4 style={{ margin: 0, color: '#e0e0e0' }}>{instance.bill_title}</h4>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
        {instance.id} · {instance.status}
      </div>

      {/* Role Assignments */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>ROLE ASSIGNMENTS</div>
        {roles.map(([roleId, ra]) => (
          <div key={roleId} style={{ fontSize: 12, color: '#ccc', padding: '2px 0' }}>
            <span style={{ color: '#5090d0' }}>{roleId}</span>
            {' → '}
            <span style={{ color: '#50b080' }}>{ra.callsign || ra.agent_type}</span>
          </div>
        ))}
        {roles.length === 0 && (
          <div style={{ fontSize: 12, color: '#666' }}>No assignments</div>
        )}
      </div>

      {/* Step Timeline */}
      <div>
        <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>STEP PROGRESSION</div>
        {steps.map(([stepId, ss]) => (
          <div key={stepId} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '4px 0', borderBottom: '1px solid #222',
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: STATUS_COLORS[ss.status] ?? '#444',
            }} />
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 12, color: '#ccc' }}>{stepId}</span>
              {ss.assigned_agent_callsign && (
                <span style={{ fontSize: 11, color: '#888', marginLeft: 6 }}>
                  ({ss.assigned_agent_callsign})
                </span>
              )}
            </div>
            <span style={{
              fontSize: 11, color: STATUS_COLORS[ss.status] ?? '#888',
            }}>{ss.status}</span>
            {ss.error && (
              <span style={{ fontSize: 11, color: '#d05050', marginLeft: 4 }}>
                {ss.error}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Instance Card ─────────────────────────────────────────────────
function InstanceCard({ instance, selected, onSelect }: {
  instance: BillInstanceView;
  selected: boolean;
  onSelect: () => void;
}) {
  const statusColor = STATUS_COLORS[instance.status] ?? '#888';
  const steps = Object.values(instance.step_states);
  return (
    <div>
      <div
        onClick={onSelect}
        style={{
          background: selected ? '#1a1a3e' : '#1a1a2e',
          border: `1px solid ${selected ? '#5090d0' : '#333'}`,
          borderRadius: 6, padding: 10, cursor: 'pointer', marginBottom: 4,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600, color: '#e0e0e0', fontSize: 13 }}>
            {instance.bill_title}
          </span>
          <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>
            {instance.status.toUpperCase()}
          </span>
        </div>
        <StepProgress instance={instance} />
        <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
          {Object.keys(instance.role_assignments).length} assigned ·{' '}
          {steps.filter(s => s.status === 'completed').length}/{steps.length} steps
        </div>
      </div>
      {selected && <InstanceDetail instance={instance} />}
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────
export default function BillDashboard() {
  const definitions = useStore(s => s.billDefinitions);
  const instances = useStore(s => s.billInstances);
  const selectedId = useStore(s => s.billSelectedInstanceId);
  const fetchDefs = useStore(s => s.fetchBillDefinitions);
  const fetchInstances = useStore(s => s.fetchBillInstances);
  const activate = useStore(s => s.activateBill);
  const selectInstance = useStore(s => s.selectBillInstance);

  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');

  useEffect(() => {
    fetchDefs();
    fetchInstances();
  }, [fetchDefs, fetchInstances]);

  const filteredInstances = filter === 'all'
    ? instances
    : instances.filter(i => filter === 'active'
        ? ['pending', 'active'].includes(i.status)
        : ['completed', 'failed', 'cancelled'].includes(i.status)
      );

  const handleActivate = async (billId: string) => {
    const inst = await activate(billId);
    if (inst) selectInstance(inst.id);
  };

  return (
    <div style={{ display: 'flex', height: '100%', gap: 16, padding: 16, color: '#e0e0e0' }}>
      {/* Left: Bill Catalog */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <h3 style={{ margin: '0 0 12px', color: '#aaa', fontSize: 14 }}>
          BILL CATALOG ({definitions.length})
        </h3>
        {definitions.map(d => (
          <BillCard key={d.bill_id} defn={d} onActivate={handleActivate} />
        ))}
        {definitions.length === 0 && (
          <div style={{ color: '#666', fontSize: 13 }}>No bills loaded</div>
        )}
      </div>

      {/* Right: Active Instances */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, color: '#aaa', fontSize: 14 }}>
            INSTANCES ({filteredInstances.length})
          </h3>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['all', 'active', 'completed'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  background: filter === f ? '#304060' : 'transparent',
                  border: `1px solid ${filter === f ? '#5090d0' : '#444'}`,
                  color: filter === f ? '#5090d0' : '#888',
                  borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 11,
                }}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {filteredInstances.map(i => (
          <InstanceCard
            key={i.id}
            instance={i}
            selected={selectedId === i.id}
            onSelect={() => selectInstance(
              selectedId === i.id ? null : i.id
            )}
          />
        ))}
        {filteredInstances.length === 0 && (
          <div style={{ color: '#666', fontSize: 13 }}>No instances</div>
        )}
      </div>
    </div>
  );
}
```

---

## Section 6: Add Bills Tab to ViewSwitcher

**File:** `ui/src/components/ViewSwitcher.tsx` (EDIT)

Add a "Bills" tab to the existing ViewSwitcher. The `mainViewer` type is a union literal — builder MUST add `'bills'` to **both** locations:

1. `ViewSwitcher.tsx` line 9: the `tabs` array type — change `'canvas' | 'kanban' | 'system' | 'work'` to `'canvas' | 'kanban' | 'system' | 'work' | 'bills'`
2. `useStore.ts` line 215: the `mainViewer` state type — change the same union

### Current code (ViewSwitcher.tsx, line 9):
```tsx
  const tabs: { key: 'canvas' | 'kanban' | 'system' | 'work'; label: string }[] = [
    { key: 'canvas', label: 'CANVAS' },
    { key: 'kanban', label: 'KANBAN' },
    { key: 'system', label: 'SYSTEM' },
    { key: 'work', label: 'WORK' },
  ];
```

### New code:
```tsx
  const tabs: { key: 'canvas' | 'kanban' | 'system' | 'work' | 'bills'; label: string }[] = [
    { key: 'canvas', label: 'CANVAS' },
    { key: 'kanban', label: 'KANBAN' },
    { key: 'system', label: 'SYSTEM' },
    { key: 'work', label: 'WORK' },
    { key: 'bills', label: 'BILLS' },
  ];
```

In the content rendering section (search for the conditional that renders based on `mainViewer`), add:

```tsx
import BillDashboard from './BillDashboard';

// In the content rendering:
{mainViewer === 'bills' && <BillDashboard />}
```

**Builder verification:** Grep `useStore.ts` for the `mainViewer` type definition (line ~215) and update it to include `'bills'`. Also check `useStore.ts` line ~423 for the initial value to ensure it's still `'canvas' as const`.

---

## Section 7: Backend Tests

**File:** `tests/test_ad618d_hxi_bill_dashboard.py` (NEW)

Test the FastAPI router endpoints. Use `httpx.AsyncClient` with a mocked runtime, following the pattern from existing router tests.

Create mock `BillDefinition` and `BillInstance` stubs using the **actual** imports from `probos.sop.schema` and `probos.sop.instance` — these are already built (AD-618a/b are dependencies).

### Test categories (15 tests):

**Definition endpoints (4 tests):**
1. `test_list_definitions_returns_catalog` — mock `br.list_definitions()` returning 2 `BillDefinition` objects, verify response shape matches `_serialize_definition` output
2. `test_get_definition_found` — mock `br.get_definition()` returning a definition, verify `bill_id` (= `.bill`), `title`, `version`, `activation.trigger`, `activation.authority`, role count, step count
3. `test_get_definition_not_found` — mock returning None, verify 404
4. `test_definitions_service_unavailable` — `runtime._bill_runtime` is None, verify 503

**Instance endpoints (5 tests):**
5. `test_list_instances_all` — mock `br.list_instances()`, verify response wraps `BillInstance.to_dict()` output
6. `test_list_instances_filtered_by_status` — verify `status` param converted to `InstanceStatus` enum and passed through
7. `test_get_instance_detail` — mock returning instance with `step_states` (dict) and `role_assignments` (dict), verify `to_dict()` output
8. `test_get_instance_not_found` — verify 404
9. `test_get_instance_assignments` — verify assignments endpoint reads `instance.role_assignments.values()` and returns `role_id`, `agent_id`, `callsign`, `department`. **Assert that `br.get_agent_assignments` is NOT called** — the endpoint uses `instance.role_assignments` directly, not `get_agent_assignments(agent_id)` which answers a different question.

**Action endpoints (4 tests):**
10. `test_activate_bill_success` — mock `br.get_definition()` and `br.activate()`, verify activate receives `BillDefinition` (not bill_id) and `activation_data=` (not `context=`). **Assert call shape:** `br.activate.assert_called_once()` and verify the first positional arg `is` the mocked `BillDefinition` instance (not a string). Verify `activation_data` keyword matches the request body's `context` dict.
11. `test_activate_bill_unknown_id` — `get_definition()` returns None, verify 404
12. `test_cancel_instance_success` — mock `br.cancel()` returning True, verify response is `instance.to_dict()`
13. `test_cancel_instance_not_found` — mock `br.cancel()` returning False, verify 404

**Serialization (2 tests):**
14. `test_serialize_definition_handles_none_activation` — definition with `activation=None`
15. `test_serialize_definition_roles_as_dict` — `BillDefinition.roles` is `dict[str, BillRole]`, verify serializer iterates `.values()` not the dict directly

---

## Section 8: Frontend Test

**File:** `ui/src/tests/BillDashboard.test.tsx` (NEW)

Per standing instructions: "Every UI change (TypeScript/React) must include a Vitest component test."

At minimum, write one Vitest test that verifies the WebSocket event handler integration:

```tsx
import { describe, it, expect } from 'vitest';
import { useStore } from '../store/useStore';

describe('BillDashboard store', () => {
  it('fetchBillDefinitions populates state', async () => {
    // Mock fetch to return test definitions
    const mockDef = {
      bill_id: 'general_quarters',
      title: 'General Quarters',
      description: 'test',
      version: 1,
      activation: { trigger: 'manual', authority: 'captain' },
      roles: [],
      steps: [],
      step_count: 0,
      role_count: 0,
    };
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ definitions: [mockDef] }),
    }) as Response;

    await useStore.getState().fetchBillDefinitions();
    expect(useStore.getState().billDefinitions).toHaveLength(1);
    expect(useStore.getState().billDefinitions[0].bill_id).toBe('general_quarters');
  });
});
```

Follow the existing Vitest patterns in `ui/src/tests/`. Builder should add at least 3 tests:
1. `fetchBillDefinitions` populates state
2. `fetchBillInstances` populates state
3. `selectBillInstance` toggles selection

---

## Engineering Principles Compliance

- **SOLID/S** — Router handles HTTP concerns only. Serialization separated into helpers. BillRuntime owns business logic.
- **SOLID/O** — Definition registry extends BillRuntime via new public methods (additive, not modifying existing behavior).
- **SOLID/D** — Router depends on `_get_bill_runtime()` abstraction, not direct construction. Zustand store decoupled from component rendering.
- **Law of Demeter** — `runtime._bill_runtime` follows established precedent (`runtime._records_store` in records.py). One level deep. Router doesn't reach through BillRuntime internals.
- **Fail Fast** — 503 for missing service, 404 for unknown bill/instance, 400 for invalid status enum. No silent degradation.
- **DRY** — Instance serialization delegates to `BillInstance.to_dict()`. Definition serializer is the only custom one (no `to_dict()` on schema dataclass). WebSocket handlers share a single refetch call.
- **Defense in Depth** — Router validates inputs (status enum conversion, bill_id lookup) before calling BillRuntime. BillRuntime validates internally (concurrency limits, terminal state guards).

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   AD-618d COMPLETE. HXI Bill Dashboard — definition registry on BillRuntime, FastAPI router (6 endpoints), React dashboard (catalog + instance timeline + role roster + step progression), WebSocket refetch-on-event, ViewSwitcher Bills tab. 15 backend + 3 frontend tests. Issue #204.
   ```

2. **docs/development/roadmap.md** — Update the AD-618d row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ### AD-618d — HXI Bill Dashboard (2026-04-25)
   **Context:** AD-618b delivered BillRuntime and AD-618c delivered built-in bills. No HXI surface existed for bill visibility or manual activation.
   **Decision:** Added definition registry to BillRuntime (3 methods: register_definition, list_definitions, get_definition). Router uses BillInstance.to_dict() for instance serialization — the dataclass owns its shape. WebSocket handlers use refetch-on-event pattern (re-fetch full instance list on any bill lifecycle event) rather than partial state patching from event payloads, because AD-618b event payloads are summary-only (no status strings, no timestamps). Activate endpoint looks up BillDefinition first then passes it to activate() — the runtime takes a BillDefinition, not a bill_id string. Cancel endpoint checks bool return from cancel(), then fetches instance for response. Instance assignments endpoint reads instance.role_assignments directly — get_agent_assignments(agent_id) answers a different question ("what bills is this agent in?").
   **Consequences:** Captain can view loaded bills, activate manually, monitor step progression, and cancel instances. Future: richer event payloads to eliminate refetch roundtrip, drag-and-drop role reassignment, bill template wizard.
   ```
