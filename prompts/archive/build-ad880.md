# Build AD-880 — Reactive reclaim on agent removal (event-driven safety net)

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-880**. One AD = one commit.
**Depends on:** AD-877 (reuses classify→act + attempt guard). **Ship as a minimal, config-gated, default-off first cut.**

---

## Problem

Reclaim is poll-only — up to `interval_seconds` (default 300s) latency between an agent dying and its items
being reclaimed. Mature schedulers pair the sweep with a **reactive** reclaim triggered the moment an agent
deregisters.

## Verify-first findings (confirmed)

- **No `AGENT_REMOVED` EventType exists.** events.py has an `# Agent lifecycle` cluster
  (events.py:86-89: `AGENT_STATE`, `AGENT_WIRED` (AD-490), `AGENT_CAPACITY_APPROACHING`). `runtime.py` ~l.4408
  logs an `event_log(category="qa", event="agent_removed", ...)` string in the QA auto-remove path only —
  that is an event-log category, **not** a bus `EventType`.
- **Canonical removal chokepoint = `AgentRegistry.unregister`** (substrate/registry.py:39): pops the agent
  under `self._lock`, debug-logs, returns the popped agent. `AgentPool.remove_agent` (pool.py:200) calls
  `await self.registry.unregister(...)`, so QA auto-remove and pool removal both funnel through it. There is
  **one** chokepoint to instrument.
- `AgentRegistry` has **no** `_emit_event_fn` set in `__init__`; finalize.py:140 late-binds it
  (`registry._emit_event_fn = emit_fn`). Use `getattr(self, "_emit_event_fn", None)` and no-op if absent.
- `runtime.emit_event` (runtime.py:1257) is **sync**.

## Build (minimal, config-gated)

### 0. EventType (events.py:86-89, `# Agent lifecycle` cluster)

Add, immediately after `AGENT_CAPACITY_APPROACHING`:

```python
AGENT_REMOVED = "agent_removed"  # AD-880: reactive reclaim trigger
```

### 1. Emit at the chokepoint — `AgentRegistry.unregister` (substrate/registry.py:39)

- Capture the popped agent (and its `agent_id`/`agent_type`) **inside** the `self._lock` block (you already
  hold the reference there).
- After the `async with self._lock:` block exits (so the emit is **outside** the lock — re-entrancy safety,
  per the BF-598 idempotency lesson), if a non-`None` agent was popped, emit:

```python
emit = getattr(self, "_emit_event_fn", None)
if emit is not None:
    emit(EventType.AGENT_REMOVED, {"agent_id": agent_id, "agent_type": agent_type})
```

- `emit` is the late-bound sync callable — **do not await**. Guard with `getattr`; honest-degrade to no-op if
  unbound (tests that construct a bare registry).
- Import `EventType` at module top if not already imported (verify-first before adding a duplicate import).

### 2. Scoped reclaim — `QuartermasterAgent.reconcile_for_agent(agent_id)`

New async method that reclaims **only** the dead agent's items, reusing the existing classify→act path:

- Fetch open + in_progress items (each `limit=self._scan_limit`), filter to `item.assigned_to == agent_id`.
- For each, run the same per-item logic as `reconcile()` (including AD-877 quarantine/backoff/attempt guard
  and AD-878 too-fresh skip, and AD-879 oldest-first sort of the filtered set). **Extract the shared per-item
  routine** into a private helper (e.g. `async def _process_item(self, item, counts)`) that both
  `reconcile()` and `reconcile_for_agent()` call — DRY; do not duplicate the body.
- Emit `WORK_ITEM_RECONCILED` with the counts dict plus `{"trigger": "reactive", "agent_id": agent_id}`.
- Store an episode as `reconcile()` does (reuse `resolve_sovereign_id(self)`).

### 3. Subscription wiring (gated) — `_wire_board_reconciler` (startup/finalize.py:1866)

- Add `reactive_reclaim: bool = Field(default=False)` to `WorkBoardReconcilerConfig` (config.py:4543).
- When `cfg.reactive_reclaim` is True (and the reconciler is otherwise wired), subscribe the quartermaster to
  `EventType.AGENT_REMOVED` on the runtime's intent/event bus using the same subscription mechanism the
  runtime already uses for `EventType` subscriptions (verify-first the exact bus API in finalize.py /
  runtime — reuse an existing `subscribe` pattern; do **not** invent a new bus).
- The handler calls `await agent.reconcile_for_agent(event_data["agent_id"])` inside a Tier-2 try/except
  (honest-degrade; never let a reclaim failure crash the bus). Hold the subscription/task reference.
- When `cfg.reactive_reclaim` is False (default): **no subscription** — the sweep is unchanged.

## Tests (≥8) — `tests/test_ad880_reactive_reclaim.py`

**BF-287:** real `AgentRegistry` + real `WorkItemStore`. `_Fake` only for router/dispatch.

1. `registry.unregister` of a present agent emits `AGENT_REMOVED` once (real registry with a captured
   `_emit_event_fn`).
2. `unregister` of an absent agent (pop returns None) emits **nothing**.
3. Registry with no `_emit_event_fn` bound → no crash, no emit.
4. `AGENT_REMOVED` carries `agent_id` + `agent_type`.
5. `reconcile_for_agent(x)` reclaims only items assigned to `x`, leaves others untouched.
6. `reconcile_for_agent` honours the AD-877 attempt guard (a thrashing item quarantines, not loops).
7. `reactive_reclaim=False` → no subscription created (assert the bus has no quartermaster subscriber).
8. `reactive_reclaim=True` → handler invocation reclaims the dead agent's items (drive an `AGENT_REMOVED`
   through the handler).

## Do not

- Change the sweep's semantics — reactive reclaim is **additive**. The periodic sweep stays the safety net.
- Emit `AGENT_REMOVED` from `pool.remove_agent_by_id` (pool.py:261) — that path only removes pool tracking,
  not the registry; the single chokepoint is `registry.unregister`.
- Emit inside the `_lock`.

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-880 newest-first under `## Era V — Civilization`
  (record: reactive reclaim default-off; AGENT_REMOVED added; emitted at registry.unregister chokepoint).

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad880_reactive_reclaim.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- events.py:86-89 `# Agent lifecycle` cluster (`AGENT_STATE`/`AGENT_WIRED`/`AGENT_CAPACITY_APPROACHING`); no `AGENT_REMOVED`.
- substrate/registry.py:39 `async def unregister` — pops under `_lock`, debug-log only, no emit; no `_emit_event_fn` in `__init__`.
- substrate/pool.py:200 `remove_agent` → `await registry.unregister`; pool.py:261 `remove_agent_by_id` pool-only.
- startup/finalize.py:140 `registry._emit_event_fn = emit_fn` (late-bind); runtime.py:1257 `emit_event` sync.
- runtime.py:~4408 QA path uses `event_log(category="qa", event="agent_removed")` (not an EventType).
