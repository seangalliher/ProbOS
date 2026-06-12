# Build Prompt — AD-874: `WorkItemReconciler` (deterministic stranded-item classifier + reusable re-dispatch)

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first:
`git diff --numstat | sort -k2nr | head`).
**Parent epic:** `prompts/ad-874-board-reconciler-quartermaster.md`. **GitHub issue:** #846.
**Depends on:** nothing — build this first.

> Verified against live HEAD. Signatures below are confirmed. Grep before quoting if anything drifted.

---

## Goal

A pure, side-effect-free service that resolves an item's `assigned_to` to a **live** agent and classifies a
board item into a reconcile action. Plus an Open/Closed refactor so re-dispatch reuses the create path.
No LLM. No board mutation. Honest-degrade — never raise.

## Part 1 — Open/Closed refactor of `WorkItemRouter`

`src/probos/mesh/work_item_router.py`: extract the body of `on_work_item_created` (everything after the
envelope unwrap `data = event.get("data"); wi = data.get("work_item") or {}`) into a new public coroutine:

```python
async def dispatch_work_item(self, wi: dict[str, Any]) -> None:
    """Route + dispatch a single work-item dict (AD-874: reused by create-listener and Quartermaster)."""
    # (existing is_dispatchable gate → intent build → DepartmentDispatcher.route → TaskEvent → dispatcher.dispatch)

async def on_work_item_created(self, event: dict[str, Any]) -> None:
    try:
        data = event.get("data") or {}
        wi = data.get("work_item") or {}
        await self.dispatch_work_item(wi)
    except Exception:
        logger.warning("AD-581a: WorkItemRouter.on_work_item_created failed; dispatch skipped", exc_info=True)
```

**Behavior-preserving:** the create path must dispatch byte-for-byte as before. Keep the
`is_dispatchable` early-return and all emit/log lines inside `dispatch_work_item`.

## Part 2 — new module `src/probos/cognitive/work_reconciler.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import logging

logger = logging.getLogger(__name__)

_TERMINAL = {"done", "failed", "cancelled"}

@dataclass(frozen=True)
class ReconcileDecision:
    work_item_id: str
    action: str                    # "live_redispatch" | "clear_and_reroute" | "skip"
    assignee: str | None
    resolved_agent_id: str | None
    reason: str

class WorkItemReconciler:
    def __init__(self, *, registry: Any, identity_registry: Any | None = None) -> None: ...
    def resolve_live_agent(self, assigned_to: str | None) -> str | None: ...
    def classify(self, wi: dict[str, Any], *, is_dispatchable: bool) -> ReconcileDecision: ...
```

### `resolve_live_agent(assigned_to)` (pure)
1. falsy → `None`.
2. `self._registry.get(assigned_to) is not None` → return `assigned_to`.
3. elif `self._identity_registry` is not None:
   - `cert = self._identity_registry.get_by_slot(assigned_to)`; falsy → `None`.
   - scan `self._registry.all()`: for each live `agent`, `peer = self._identity_registry.get_by_slot(agent.id)`; if `peer and peer.agent_uuid == cert.agent_uuid` → return `agent.id`.
   - no match → `None`.
4. else `None`.
Wrap the whole body in `try/except Exception` → `logger.warning(..., exc_info=True); return None`.

> **Forward-proofing note:** step 2 resolves the common case — the slot ID is restart-stable (AD-177
> `generate_agent_id` excludes `instance_id`), so a re-spawned same-role agent keeps the same id. Step 3
> (sovereign-DID scan) is the **AD-441 migration seam**, only load-bearing once `sovereign_id` can move to a
> new slot. Keep it, labelled as such; it is O(N) only on the dead-assignee branch.

### `classify(wi, *, is_dispatchable)` (pure)
Read `wid = wi.get("id","")`, `status = wi.get("status","")`, `assignee = wi.get("assigned_to") or None`.
- `status in _TERMINAL` → `skip` / `"terminal"`.
- `not is_dispatchable` → `skip` / `"not_dispatchable"`.
- `assignee is None and status == "open"` → `live_redispatch` / `"unassigned_dispatchable"` (`resolved=None`).
- `assignee is not None`: `resolved = self.resolve_live_agent(assignee)`:
  - `resolved is not None and status == "in_progress"` → `skip` / `"in_progress_live_owner"`.
  - `resolved is not None and status == "open"` → `live_redispatch` / `"assignee_live"`.
  - `resolved is None` → `clear_and_reroute` / `"assignee_not_live"`.
- else → `skip` / `"no_action"`.
Always carry `assignee` and `resolved_agent_id` on the returned `ReconcileDecision`.

## Tests — `tests/test_ad874_work_reconciler.py` (≥12)

**BF-287 (HARD):** real `AgentRegistry`, real `AgentIdentityRegistry` (tmp DB via its `start()`), concrete
`BaseAgent` subclass for live agents. No MagicMock at these boundaries.

1. live slot assignee → `resolve_live_agent` returns it.
2. dead assignee, sovereign DID maps to a re-spawned live slot → returns the new id.
3. dead assignee, no cert → `None`.
4. `identity_registry=None` + dead assignee → `None` (step-2 only).
5. unassigned open dispatchable → `live_redispatch` / `unassigned_dispatchable`.
6. live owner + in_progress → `skip` / `in_progress_live_owner`.
7. live assignee + open → `live_redispatch` / `assignee_live`.
8. dead assignee → `clear_and_reroute` / `assignee_not_live`.
9. terminal status → `skip` / `terminal` (even if assignee dead).
10. not dispatchable → `skip` / `not_dispatchable`.
11. collaborator raising inside `resolve_live_agent` → degrades to `None`, no raise.
12. `ReconcileDecision` carries correct `assignee`/`resolved_agent_id`.

Also add to `tests/test_ad839_work_item_dispatch.py`: assert `dispatch_work_item(wi_dict)` routes
(direct/broadcast) identically and `on_work_item_created` still works (refactor is behavior-preserving).

## Do NOT
- Build the Quartermaster agent (AD-875) or ticker/wiring (AD-876).
- Call `update_work_item`/`unassign_work_item` here — pure decision only.
- Change what `assigned_to` stores.

## Gate
Focused serial blast radius:
`d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad874_work_reconciler.py tests/test_ad839_work_item_dispatch.py tests/test_workforce.py -q -n 0 -p no:cacheprovider`
Then update PROGRESS.md (top banner, next Wave) + DECISIONS.md (Era V, above the BF-608 entry). One commit.
Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
