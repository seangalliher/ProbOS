# Build Prompt — AD-875: `QuartermasterAgent` (Utility-tier board reconciler, deterministic)

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-874-board-reconciler-quartermaster.md`. **GitHub issue:** #846.
**Depends on:** AD-874 (`WorkItemReconciler` + `WorkItemRouter.dispatch_work_item`). Build AD-874 first.

> Verified against live HEAD. Mirror `IntrospectionAgent` (`src/probos/agents/introspect.py`). No LLM.

---

## Goal

A Utility-tier `BaseAgent` that reviews the board and acts on AD-874 decisions — re-dispatching live work
and clearing/re-routing stale bindings — through the existing router. Deterministic; honest-degrade.

## New module `src/probos/agents/quartermaster.py`

```python
from __future__ import annotations
import logging
from typing import Any
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)

class QuartermasterAgent(BaseAgent):
    agent_type = "quartermaster"
    tier = "utility"
    default_capabilities = [CapabilityDescriptor(can="reconcile_board", detail="Review the work board; re-dispatch / re-bind stranded work items")]
    initial_confidence = 0.9
    intent_descriptors = [IntentDescriptor(name="reconcile_board", params={}, description="Review the work board and re-dispatch or re-bind stranded work items", requires_reflect=False)]
    _handled_intents = {"reconcile_board"}

    def __init__(self, *, reconciler: Any = None, work_item_store: Any = None,
                 work_item_router: Any = None, emit_fn: Any = None,
                 episodic: Any = None, scan_limit: int = 200, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._reconciler = reconciler
        self._store = work_item_store
        self._router = work_item_router
        self._emit = emit_fn
        self._episodic = episodic
        self._scan_limit = scan_limit

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None: ...
    async def perceive(self, intent: dict[str, Any]) -> Any: ...
    async def decide(self, observation: Any) -> Any: ...
    async def act(self, plan: Any) -> Any: ...
    async def report(self, result: Any) -> dict[str, Any]: ...
    async def reconcile(self) -> dict[str, Any]: ...   # the core sweep (also called by the AD-876 ticker)
```

### `reconcile()` — honest-degrade sweep
1. If `self._store`/`self._router`/`self._reconciler` is None → `logger.info("AD-875: Quartermaster missing collaborators; reconcile skipped")` and return `{"scanned":0,"redispatched":0,"cleared":0,"skipped":0,"degraded":True}`.
2. Gather non-terminal items:
   `open_items = await self._store.list_work_items(status="open", limit=self._scan_limit)`
   `inprog = await self._store.list_work_items(status="in_progress", limit=self._scan_limit)`
   merge (dedupe by `id`).
3. counts `= {"scanned":0,"redispatched":0,"cleared":0,"skipped":0,"degraded":False}`.
4. Per item, in a `try/except Exception` (Tier-2 log-and-continue; on except `counts["degraded"]=True`):
   - `counts["scanned"] += 1`
   - `wi = item.to_dict()`; `is_disp = self._router.is_dispatchable(wi)`
   - `d = self._reconciler.classify(wi, is_dispatchable=is_disp)`
   - `action == "live_redispatch"`: `await self._router.dispatch_work_item(wi)`; `counts["redispatched"] += 1`
   - `action == "clear_and_reroute"`: `await self._store.unassign_work_item(item.id, reason="quartermaster: assignee not live")` (note: this also resets `status` to `'open'` as a side effect — do **not** add a separate transition); `fresh = await self._store.get_work_item(item.id)`; if `fresh`: `await self._router.dispatch_work_item(fresh.to_dict())`; `counts["cleared"] += 1`
   - else: `counts["skipped"] += 1`
5. Emit summary (best-effort, **sync** — `runtime.emit_event` is not a coroutine, do NOT `await`): add a real
   enum member `WORK_ITEM_RECONCILED` to `EventType` in `src/probos/events.py` in the existing `WORK_ITEM_*`
   cluster (after `WORK_ITEM_STATUS_CHANGED`, `# AD-875` tag — mirror how `WORK_ITEM_QUARANTINED` was
   appended). Then `if self._emit is not None: self._emit(EventType.WORK_ITEM_RECONCILED, {...counts})`
   wrapped in try/except. **No raw-string fallback** (the codebase always emits an `EventType`).
6. Episode (best-effort): if `self._episodic`, store a one-line reconcile episode; honest-degrade if not.
7. `logger.info("AD-875: reconcile pass scanned=%d redispatched=%d cleared=%d skipped=%d", ...)`; return counts.

### Lifecycle
- `handle_intent`: if `intent.intent != "reconcile_board"` → `None`. Else run `perceive→decide→act→report`, `update_confidence(True)`, return `IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result=<counts>, confidence=self.confidence)`.
- `perceive`: return None unless `intent.get("intent")=="reconcile_board"`.
- `decide`: `{"action":"reconcile"}`. `act`: `await self.reconcile()`. `report`: `{"success":True,"data":<counts>}`.

## Tests — `tests/test_ad875_quartermaster.py` (≥12)

**BF-287 (HARD):** real `WorkItemStore` (`tmp_path`, `await store.start()`), real `AgentRegistry`, real
`WorkItemReconciler`. A `_FakeRouter` with a real-ish `is_dispatchable(wi)` (reads `metadata["dispatchable"]`)
and a `dispatch_work_item` async that records calls. Concrete `BaseAgent` subclass for live agents.

1. stranded dispatchable open item, live assignee → `dispatch_work_item` called, `redispatched==1`.
2. dead-assignee dispatchable open item → `unassign_work_item` called then re-dispatched, `cleared==1`.
3. live in_progress owner → untouched, `skipped` counts it, no dispatch/unassign.
4. terminal item present → never scanned (status filter), counts unaffected.
5. non-dispatchable open item → `skipped`, no dispatch.
6. empty board → all-zero counts, `degraded False`.
7. one item raising mid-sweep → `degraded True`, other items still processed/counted.
8. missing collaborators (`store=None`) → degraded summary, no raise.
9. `reconcile_board` intent → `IntentResult.success True`, `result` is the counts dict.
10. non-`reconcile_board` intent → `None`.
11. `QuartermasterAgent.tier == "utility"`.
12. gap-regex clean: assert no descriptor/return string matches `_CAPABILITY_GAP_RE`
    (`from probos.cognitive.decomposer import _CAPABILITY_GAP_RE` — its literal home; `is_capability_gap`
    is the helper at `decomposer.py:51`).

## Do NOT
- Build the ticker / startup wiring / pool creation (AD-876).
- Add an internal `while`/`create_task` loop — the cadence is AD-876's ticker.
- Call the LLM. Scan terminal statuses. Touch `done`/`failed`/`cancelled` items.

## Gate
`d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad875_quartermaster.py tests/test_ad874_work_reconciler.py -q -n 0 -p no:cacheprovider`
Then PROGRESS.md banner + DECISIONS.md (Era V). One commit.
Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
