# Build Prompt — AD-876: warm-boot + periodic trigger, config gate, pool + finalize wiring

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-874-board-reconciler-quartermaster.md`. **GitHub issue:** #846.
**Depends on:** AD-874 + AD-875. Build them first.

> Verified against live HEAD. Mirror `_wire_hybrid_dispatch` (`startup/finalize.py:1792`) +
> `AttachmentReaper` (`src/probos/attachments/reaper.py`) for the ticker pattern. Ships **disabled**.

---

## Goal

Run the Quartermaster once at warm boot and on an interval, behind a config gate, and create its pool.
The agent stays intent-driven; the cadence is a tiny ticker holding its own task ref. Zero behavior change
out of the box (default disabled).

## 1 — Config (`src/probos/config.py`)

Add near `HybridDispatchConfig` (config.py:4493):
```python
class WorkBoardReconcilerConfig(BaseModel):
    """AD-876: periodic + warm-boot work-board reconciliation (Quartermaster)."""
    enabled: bool = False                                   # transitional flag — default False (conv #14)
    interval_seconds: int = Field(default=300, ge=30, le=3600)
    warm_boot: bool = True
    scan_limit: int = Field(default=200, ge=1, le=2000)
```
(Use `Field(ge=, le=)` for the numeric bounds — out-of-range values surface as `pydantic.ValidationError`,
which the tests assert. Default `enabled=False` is load-bearing: unlike `HybridDispatchConfig.enabled`
(which defaults True for a read-only boot path), this gate guards a **side-effecting** ticker that
unassigns/re-dispatches work items, so it must ship off.)
Add to `SystemConfig` (sibling of `hybrid_dispatch`, config.py:5246):
```python
work_board_reconciler: WorkBoardReconcilerConfig = Field(default_factory=WorkBoardReconcilerConfig)
```

## 2 — Spawner template + pool (`src/probos/runtime.py` + `src/probos/startup/agent_fleet.py`)

**REQUIRED first (crash risk if omitted):** register the agent-type → class template. The spawner does
`if type_name not in self._templates: raise ValueError(...)` (`substrate/spawner.py:40`), and templates are
registered explicitly in `runtime.py` (~line 1011) next to `introspect`/`system_qa`:
```python
from probos.agents.quartermaster import QuartermasterAgent  # with the other agent imports
self.spawner.register_template("quartermaster", QuartermasterAgent)  # beside register_template("introspect", ...)
```
Without this, `create_pool_fn("quartermaster", ...)` raises `ValueError: Unknown agent template` and the
wiring test (`registry.get_by_pool("quartermaster")`) is empty.

Then create the pool in `agent_fleet.py`, mirror the introspect block (agent_fleet.py:58-60), gated on the config:
```python
if getattr(config, "work_board_reconciler", None) and config.work_board_reconciler.enabled:
    ids = generate_pool_ids("quartermaster", "quartermaster", 1)
    await create_pool_fn("quartermaster", "quartermaster", target_size=1, agent_ids=ids, runtime=runtime)
```
(Confirm how `create_pool_fn` maps `agent_type="quartermaster"` to the `QuartermasterAgent` class — follow
the same registration the introspect/system_qa pools use, e.g. the agent-class registry/factory. Wire the
constructor kwargs — `reconciler`, `work_item_store`, `work_item_router`, `emit_fn`, `episodic`,
`scan_limit` — at creation **or** inject post-create in finalize (step 3). Pick the path the existing
utility pools use; inject in finalize if the factory signature can't carry them.)

## 3 — Wiring (`src/probos/startup/finalize.py`)

New `_wire_board_reconciler(*, runtime, config) -> bool` mirroring `_wire_hybrid_dispatch`:
1. `cfg = getattr(config, "work_board_reconciler", None)`; if not `cfg` or not `cfg.enabled` → return False.
2. Require `runtime.work_item_router`, `runtime.work_item_store`, `runtime.registry` — any missing → INFO log + return False. (`runtime.work_item_router` only exists when `hybrid_dispatch.enabled` is true, so this also enforces the hard `hybrid_dispatch` dependency — the `WorkBoardReconcilerConfig` docstring must say "requires hybrid_dispatch enabled".)
3. Build `reconciler = WorkItemReconciler(registry=runtime.registry, identity_registry=getattr(runtime,"identity_registry",None))`.
4. Resolve the live quartermaster agent (`runtime.registry.get_by_pool("quartermaster")[0]` if present); inject by setting the **exact private attrs** the constructor uses — `agent._reconciler = reconciler`, `agent._store = runtime.work_item_store`, `agent._router = runtime.work_item_router`, `agent._emit = getattr(runtime,"emit_event",None)`, `agent._episodic = getattr(runtime,"episodic_memory",None)`, `agent._scan_limit = cfg.scan_limit` (NOT the public kwarg names).
5. Start a ticker (new small class `BoardReconcilerTicker` — put it in `src/probos/mesh/board_reconciler_ticker.py` or inline in finalize; prefer a named module for testability):
   ```python
   class BoardReconcilerTicker:
       def __init__(self, *, agent, interval_seconds, warm_boot, startup_delay=10.0): ...
       def start(self) -> None:    # holds self._task = asyncio.create_task(self._loop(), name="ad876-board-reconciler")
       async def stop(self) -> None:  # cancel + await, swallow CancelledError
       async def _loop(self) -> None:
           if self._warm_boot:
               await asyncio.sleep(self._startup_delay)
               await self._safe_reconcile()
           while True:
               await asyncio.sleep(self._interval)
               await self._safe_reconcile()
       async def _safe_reconcile(self):  # try: await self._agent.reconcile() except CancelledError: raise except Exception: logger.warning(..., exc_info=True)
   ```
   Store `runtime.board_reconciler_ticker = ticker` (public attr) and `ticker.start()`.
6. Call `_wire_board_reconciler(runtime=runtime, config=config)` in the finalize sequence next to the
   `_wire_hybrid_dispatch` call.
7. Shutdown: wire `await runtime.board_reconciler_ticker.stop()` alongside the existing reaper/ward-room
   stops in `startup/shutdown.py` (honest-degrade if the attr is absent).

## Tests — `tests/test_ad876_reconciler_wiring.py` (≥9)

Use a **real** `SystemConfig` (BF-287 — no MagicMock at the config boundary).
1. `WorkBoardReconcilerConfig()` defaults: `enabled is False`, `interval_seconds == 300`, `warm_boot is True`, `scan_limit == 200`.
2. Pydantic bounds: `interval_seconds=10` and `=99999` raise `ValidationError`; `scan_limit=0` and `=99999` raise.
3. `_wire_board_reconciler` returns False + no-ops when `enabled is False`.
4. returns False + INFO (no raise) when a dependency (`work_item_router`) is missing though enabled.
5. enabled + deps present → injects reconciler onto the agent + returns True + sets `runtime.board_reconciler_ticker`.
6. ticker holds its task ref after `start()` (`ticker._task is not None`); source-scan assertion that `create_task` result is stored (no fire-and-forget).
7. warm-boot path calls `agent.reconcile()` once (use a fake agent recording calls + a tiny `startup_delay`).
8. `ticker.stop()` cancels cleanly — no unretrieved-task-exception (await stop, assert task cancelled).
9. integration: real `WorkItemStore` with one stranded item + a `_FakeRouter`; one warm-boot `reconcile()` → router saw `dispatch_work_item`.
10. (regression) `tests/test_runtime.py` startup path stays green with the feature disabled — assert default boot does NOT create a quartermaster pool / ticker.

## Do NOT
- Default `enabled` True (flip stays a future grandchild AD / operator config).
- Change `WorkItemRouter` create-path behavior.
- Add a loop inside the agent (the ticker owns the cadence).
- Use `asyncio.ensure_future`/`get_event_loop` — `create_task` + `get_running_loop` only.

## Gate
`d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad876_reconciler_wiring.py tests/test_ad875_quartermaster.py tests/test_ad874_work_reconciler.py tests/test_runtime.py -q -n 0 -p no:cacheprovider`
Then a broader serial blast radius (`tests/test_workforce.py tests/test_ad839_work_item_dispatch.py` + startup tests).
Update PROGRESS.md banner + DECISIONS.md (Era V) — note the epic closes. One commit.
Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
