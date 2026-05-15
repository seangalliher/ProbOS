# AD-722b-4 — Fleet-level avatar telemetry stream (single WS, fan-out by agent_id)

**AD:** AD-722b-4. **GH issue closed:** [#601](https://github.com/seangalliher/ProbOS/issues/601).
**Parent ADs:** AD-722b (per-agent WS, Wave 142), AD-722b-3 (snapshot-diff frames, Wave 159), AD-722c (history append), AD-722d (records writer).
**Wave:** 160. **Estimated tests:** +6 pytest + 2 vitest. **Estimated wall-time:** ~2h. **Risk:** LOW-MED — adds a new endpoint; existing per-agent endpoint stays functional for backward compat.

---

## Solution Overview

Today every avatar tile in the HXI opens its own WebSocket to `/api/agents/{agent_id}/avatar-telemetry-stream`. A Captain viewing 4 crew avatars = 4 WS connections, 4 publish loops, 4 `sampling_state.enter_popout` calls. AD-722b's `max_connections_per_agent=4` cap (per-agent) already bounds the worst case; the connection count never explodes. But the model is wasteful as the fleet grows.

AD-722b-4 adds a sibling endpoint `WS /api/agent/avatar-telemetry/stream` (fleet-scoped, NOT under `/{agent_id}/`). The `agents` router in `src/probos/routers/agents.py:30` mounts at prefix `/api/agent` (singular); the fleet endpoint is registered with relative path `/avatar-telemetry/stream` and resolves to `/api/agent/avatar-telemetry/stream`. The per-agent endpoint at `/api/agent/{agent_id}/avatar-telemetry-stream` is unaffected (path literals diverge cleanly: `/avatar-telemetry/stream` vs. `/{agent_id}/avatar-telemetry-stream`). On accept, the server iterates the crew registry and, for each crew agent, runs the SAME publish-loop logic the per-agent endpoint runs today — wrapped per-agent with the `agent_id` interleaved into every frame. Every frame the client receives is `{"type": "snapshot" | "diff" | "ping", "agent_id": "...", ...}` where the `agent_id` field is mandatory at the FLEET endpoint and absent at the per-agent endpoint (backward compat preserved).

**Concurrency design:**
- One WS connection holds N (= crew count) per-agent publish coroutines, each gated by its own sampling-state rate and event signal.
- Use `asyncio.TaskGroup` to fan out; the fleet endpoint waits on `FIRST_COMPLETED` of (all publish tasks, receive_loop). Disconnect on either side cancels the group cleanly.
- Per-agent diff state (`last_sent_snap_dict`) is tracked per-agent in a `dict[str, dict[str, Any] | None]` local to the handler.
- Sampling-state `enter_popout` / `exit_popout` are called per-agent on connect / disconnect.

**Backward compatibility:**
- Per-agent endpoint at `/{agent_id}/avatar-telemetry-stream` (line 669) stays functional with NO changes. Existing HXI components keep working.
- New endpoint is opt-in via a single `AvatarTelemetryConfig.fleet_stream_enabled: bool = True` flag — default-ON because no existing UI consumes it yet. The flag exists for operator override (e.g., to mute the fleet endpoint while debugging).
- The HXI side ships a single `useFleetAvatarTelemetry()` hook that subscribes once to `/api/agent/avatar-telemetry/stream` and dispatches per-agent frames into the existing per-agent telemetry stores (the consumer-side migration is a separate AD-722b-4a forward marker — v1 ships the server endpoint + a Vitest hook stub).

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | `AvatarTelemetryConfig` (~line 1025) | Add `fleet_stream_enabled: bool = True`. |
| `src/probos/routers/agents.py` | NEW endpoint (insert after the existing per-agent WS at line 720) | Fleet endpoint handler. |
| `tests/test_ad722b4_fleet_telemetry.py` | NEW | 6 pytest tests. |
| `ui/src/avatars/useFleetAvatarTelemetry.ts` | NEW (~80 lines) | Hook stub + Vitest fixture target. |
| `ui/tests/avatars/useFleetAvatarTelemetry.test.ts` | NEW | 2 Vitest tests (subscribes once, dispatches frames by agent_id). |

**Verified anchors:**
- Per-agent WS handler: `src/probos/routers/agents.py:669` (`@router.websocket("/{agent_id}/avatar-telemetry-stream")`, full path `/api/agent/{agent_id}/avatar-telemetry-stream`) through line ~920.
- Router prefix: `src/probos/routers/agents.py:30` (`router = APIRouter(prefix="/api/agent", tags=["agents"])`). Fleet endpoint inherits this prefix; full path resolves to `/api/agent/avatar-telemetry/stream`.
- Sampling state: `runtime.avatar_sampling_state` (`enter_popout(agent_id)`, `current_rate_ms(agent_id)`, `exit_popout(agent_id)`).
- Event bus: `runtime.avatar_event_bus` (`subscribe(agent_id) -> asyncio.Event`, `notify(agent_id)`, `unsubscribe(agent_id, event)`).
- Connection manager: `runtime.avatar_telemetry_connection_manager.register(agent_id, websocket) -> connection_id`.
- Snapshot builder: `from probos.avatars.telemetry import build_telemetry_snapshot`; returns object with `.to_dict()`.
- Diff: `from probos.avatars.snapshot_diff import compute_diff`.
- History writer: `runtime.avatar_telemetry_history.append(snap)`. Records writer: `runtime.avatar_telemetry_records_writer.observe(snap)`.
- Crew registry iteration: `is_crew_agent(agent, runtime.ontology)` (verified at line 1005). The fleet handler iterates `runtime.registry.agents.values()` and filters by `is_crew_agent`.

---

## Section 1 — Config flag

In `src/probos/config.py` `AvatarTelemetryConfig`, append AFTER the AD-722c history fields (existing) and BEFORE any AD-722d fields:

```python
    # AD-722b-4: fleet-level telemetry stream — one WS, fan-out by agent_id.
    # Default-ON: zero behavior change for operators because no UI consumer
    # ships in v1; setting False mutes the endpoint (returns 1008 close).
    fleet_stream_enabled: bool = True
```

## Section 2 — Fleet endpoint handler

In `src/probos/routers/agents.py`, insert a new endpoint AFTER the existing `agent_avatar_telemetry_stream` handler ends (Builder finds the end-of-function via the `finally:` block + `await websocket.close()` cleanup; the next handler currently starts with another `@router` decorator). Anchor: `# AD-722a-5: divergence history` block at line ~937 is the next thing after the per-agent WS handler.

Insert immediately before the next `@router.get(...)` decorator:

```python
# AD-722b-4: fleet-level avatar telemetry stream.
# Same feature gates as the per-agent endpoint. Adds an additional
# fleet_stream_enabled gate. Iterates all crew agents on accept and
# fans out per-agent publish loops over a single WS connection.
# Every frame carries an explicit "agent_id" field (the per-agent
# endpoint omits it; HXI hooks distinguish by endpoint URL).
@router.websocket("/avatar-telemetry/stream")
async def fleet_avatar_telemetry_stream(websocket: WebSocket) -> None:
    runtime = websocket.app.state.runtime
    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)

    if avatars_cfg is None or not avatars_cfg.enabled:
        await websocket.close(code=1008, reason="avatars_disabled")
        return
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        await websocket.close(code=1008, reason="avatar_telemetry_disabled")
        return
    if not getattr(telemetry_cfg, "fleet_stream_enabled", True):
        await websocket.close(code=1008, reason="fleet_stream_disabled")
        return

    await websocket.accept()

    sampling_state = getattr(runtime, "avatar_sampling_state", None)
    event_bus = getattr(runtime, "avatar_event_bus", None)
    if sampling_state is None or event_bus is None:
        await websocket.send_json(
            {"type": "error", "reason": "telemetry_runtime_unavailable"},
        )
        await websocket.close(code=1011, reason="runtime_unavailable")
        return

    # Build the per-agent task set on accept. Discovery is a snapshot;
    # newly-spawned crew during the connection lifetime are NOT picked
    # up until the client reconnects. v1 simplification — AD-722b-4-1
    # forward marker for dynamic membership.
    crew_agents: list[tuple[str, Any]] = []
    for agent in runtime.registry.agents.values():
        try:
            if is_crew_agent(agent, runtime.ontology):
                crew_agents.append((agent.agent_id, agent))
        except Exception:
            logger.debug(
                "AD-722b-4: crew discovery skipped agent during fleet accept",
                exc_info=True,
            )

    if not crew_agents:
        # Honest-degrade: no crew yet → close cleanly.
        await websocket.close(code=1008, reason="no_crew_agents")
        return

    # Per-agent state.
    events: dict[str, asyncio.Event] = {}
    last_sent: dict[str, dict[str, Any] | None] = {}
    tick_counts: dict[str, int] = {}

    from probos.avatars.telemetry import build_telemetry_snapshot

    # Enter popout for every crew agent.
    for agent_id, _agent in crew_agents:
        sampling_state.enter_popout(agent_id)
        events[agent_id] = event_bus.subscribe(agent_id)
        last_sent[agent_id] = None
        tick_counts[agent_id] = 0

    publish_tasks: list[asyncio.Task] = []
    receive_task: asyncio.Task | None = None
    try:
        # Initial snapshot per agent.
        for agent_id, agent in crew_agents:
            try:
                initial = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = initial
                initial_dict = initial.to_dict()
                await websocket.send_json(
                    {"type": "snapshot", "agent_id": agent_id, **initial_dict},
                )
                last_sent[agent_id] = initial_dict
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(initial)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: history append raised on initial for %s",
                            agent_id, exc_info=True,
                        )
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(initial)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: records writer raised on initial for %s",
                            agent_id, exc_info=True,
                        )
            except Exception:
                logger.warning(
                    "AD-722b-4: initial snapshot failed for agent=%s",
                    agent_id, exc_info=True,
                )

        async def _publish_one(agent_id: str, agent: Any) -> None:
            """Per-agent publish loop, mirroring the per-agent endpoint."""
            event = events[agent_id]
            while True:
                rate_ms = sampling_state.current_rate_ms(agent_id)
                interval_s = max(0.05, float(rate_ms) / 1000.0)
                event.clear()
                wait_event = asyncio.create_task(event.wait())
                wait_timer = asyncio.create_task(asyncio.sleep(interval_s))
                try:
                    await asyncio.wait(
                        {wait_event, wait_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (wait_event, wait_timer):
                        if not t.done():
                            t.cancel()
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                snap_dict = snap.to_dict()
                tick_counts[agent_id] += 1
                cfg_t = getattr(runtime.config, "avatar_telemetry", None)
                send_full = (
                    cfg_t is None
                    or not getattr(cfg_t, "ws_diff_enabled", False)
                    or (tick_counts[agent_id] % cfg_t.ws_full_snapshot_every_n) == 0
                )
                if send_full:
                    await websocket.send_json(
                        {"type": "snapshot", "agent_id": agent_id, **snap_dict},
                    )
                    last_sent[agent_id] = snap_dict
                else:
                    try:
                        from probos.avatars.snapshot_diff import compute_diff
                        diff = compute_diff(
                            last_sent[agent_id],
                            snap_dict,
                            threshold=cfg_t.ws_diff_threshold,
                        )
                    except Exception:
                        logger.warning(
                            "AD-722b-4: compute_diff raised; falling back to full snapshot for %s",
                            agent_id, exc_info=True,
                        )
                        await websocket.send_json(
                            {"type": "snapshot", "agent_id": agent_id, **snap_dict},
                        )
                        last_sent[agent_id] = snap_dict
                        diff = None
                    if diff:
                        await websocket.send_json({
                            "type": "diff",
                            "agent_id": agent_id,
                            "changed": diff,
                        })
                        last_sent[agent_id] = {
                            **(last_sent[agent_id] or {}), **diff,
                        }
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(snap)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: history append raised for %s",
                            agent_id, exc_info=True,
                        )
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(snap)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: records writer raised for %s",
                            agent_id, exc_info=True,
                        )

        async def _receive_loop() -> None:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {"type": "ping", "timestamp": time.time()},
                    )

        for agent_id, agent in crew_agents:
            publish_tasks.append(asyncio.create_task(_publish_one(agent_id, agent)))
        receive_task = asyncio.create_task(_receive_loop())

        done, pending = await asyncio.wait(
            {*publish_tasks, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "AD-722b-4: fleet WS task ended with %s",
                    type(exc).__name__, exc_info=exc,
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("AD-722b-4: fleet WS handler error", exc_info=True)
    finally:
        for t in publish_tasks:
            if not t.done():
                t.cancel()
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        for agent_id in events:
            try:
                event_bus.unsubscribe(agent_id, events[agent_id])
            except Exception:
                logger.debug(
                    "AD-722b-4: unsubscribe failed for %s", agent_id, exc_info=True,
                )
            try:
                sampling_state.exit_popout(agent_id)
            except Exception:
                logger.debug(
                    "AD-722b-4: exit_popout failed for %s", agent_id, exc_info=True,
                )
```

**Builder verification before insertion:**

1. Confirm `asyncio` is already imported at the top of `routers/agents.py`. (Verified — the per-agent WS uses `asyncio.create_task` extensively.)
2. Confirm `WebSocket`, `WebSocketDisconnect` are already imported. (Verified — same per-agent WS uses them.)
3. Confirm `time` module is imported. (Verified at line ~1330 — `import time as _time`. If the top-level import is missing, Builder adds `import time` at the module-top imports.)
4. Confirm `is_crew_agent` is imported at module top. (Verified — used at `routers/agents.py:1005`.)
5. Confirm `runtime.registry.agents` is the correct attribute name to iterate agent instances. Builder greps `runtime.registry` usages in `runtime.py` for the right shape; if it's `runtime.registry.list()` or `runtime.registry._agents.values()`, adjust accordingly. Pattern is established elsewhere in `routers/agents.py` — use whatever the per-agent endpoint uses for related lookups.
6. Insertion order does NOT affect routing for this pair. The literal segments `/avatar-telemetry/stream` (fleet endpoint, no path parameter) and `/{agent_id}/avatar-telemetry-stream` (per-agent endpoint, one path parameter with a literal suffix) cannot collide: a request for `/api/agent/avatar-telemetry/stream` cannot match the per-agent pattern because `/avatar-telemetry/stream` doesn't fit a single `{agent_id}` segment. Insert at line ~937 for code-layout proximity to the existing per-agent handler; insertion order is purely cosmetic.
7. Verify `cfg_t.ws_diff_enabled`, `cfg_t.ws_full_snapshot_every_n`, `cfg_t.ws_diff_threshold` are AD-722b-3 fields (verified via grep at the per-agent WS handler lines 791-810).

## Section 3 — HXI hook stub

Create `ui/src/avatars/useFleetAvatarTelemetry.ts` (~80 lines). The v1 hook subscribes once at `ws://{host}/api/agent/avatar-telemetry/stream`, parses every incoming frame, and dispatches `{agent_id, type, payload}` to a passed `onFrame` callback. No store-side migration in v1 — that's AD-722b-4a.

```typescript
// AD-722b-4: fleet-level avatar telemetry stream hook.
// v1 surface — subscribes once, dispatches frames by agent_id via callback.
// Per-agent hooks at /api/agents/{id}/avatar-telemetry-stream remain
// functional; this hook does NOT replace them yet (AD-722b-4a forward marker).
import { useEffect, useRef } from "react";

export interface FleetTelemetryFrame {
  type: "snapshot" | "diff" | "ping" | "error";
  agent_id: string;
  payload: Record<string, unknown>;
}

export interface UseFleetAvatarTelemetryOptions {
  onFrame: (frame: FleetTelemetryFrame) => void;
  enabled?: boolean;
  url?: string;
}

export function useFleetAvatarTelemetry({
  onFrame,
  enabled = true,
  url,
}: UseFleetAvatarTelemetryOptions): void {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const wsUrl = url ?? deriveFleetUrl();
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data as string);
        if (typeof data?.agent_id !== "string" || typeof data?.type !== "string") {
          // Frames without agent_id are out-of-contract for the fleet endpoint.
          return;
        }
        const { agent_id, type, ...payload } = data;
        onFrame({ type, agent_id, payload });
      } catch {
        // Malformed JSON — drop silently; the per-agent endpoint guarantees
        // the contract, the fleet endpoint only adds a fan-out wrapper.
      }
    };

    ws.onerror = () => {
      // Tier-2 silent — caller's onFrame contract is "best-effort."
    };

    return () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    };
  }, [enabled, url, onFrame]);
}

function deriveFleetUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  // AD-722b-4 (revised pass-2 2026-05-14): full path resolves under the
  // ``agents`` router prefix ``/api/agent`` (src/probos/routers/agents.py:30).
  return `${proto}//${window.location.host}/api/agent/avatar-telemetry/stream`;
}
```

## Section 4 — Tests

### pytest (`tests/test_ad722b4_fleet_telemetry.py`) — 6 tests

**All `TestClient.websocket_connect(...)` calls use the URL `/api/agent/avatar-telemetry/stream`** — the `agents` router prefix `/api/agent` applies (per `routers/agents.py:30`).

1. `test_fleet_stream_disabled_closes_1008` — `fleet_stream_enabled=False` ⇒ accept + close with reason `fleet_stream_disabled`.
2. `test_no_crew_closes_1008` — registry has zero crew agents ⇒ close `no_crew_agents`.
3. `test_initial_snapshot_per_agent` — 3 crew agents ⇒ exactly 3 initial frames received, each with distinct `agent_id`.
4. `test_frame_carries_agent_id` — every frame received MUST have `agent_id` field (contrast: per-agent endpoint frames do NOT).
5. `test_disconnect_unsubscribes_all` — close from client side ⇒ `event_bus.unsubscribe` called once per agent, `sampling_state.exit_popout` called once per agent.
6. `test_diff_frames_carry_agent_id_too` — after the first snapshot tick, diff frames also include `agent_id`.

Use FastAPI's `TestClient.websocket_connect(...)` pattern (see existing `tests/test_ad722b_telemetry_ws.py` for the per-agent precedent — Builder verifies the file exists; if not, mirror the AD-722b shape from the wave-159 prompt review).

### vitest (`ui/tests/avatars/useFleetAvatarTelemetry.test.ts`) — 3 tests

1. `dispatches frames by agent_id` — `MockWebSocket` injects 3 frames with distinct `agent_id` values; `onFrame` receives exactly 3 calls with the right `agent_id` each time.
2. `drops frames missing agent_id` — inject a frame without `agent_id`; `onFrame` is NOT called.
3. `closes WebSocket on unmount` — mount the hook; verify `MockWebSocket.close()` is called when the component unmounts (covers the `useEffect` cleanup path). Pass-2 add per Recommended #4.

Use the existing Vitest `MockWebSocket` pattern (greppable in `ui/tests/avatars/`); if absent, Builder writes a 20-line local stub.

---

## What This Does NOT Change

- Per-agent endpoint at `/{agent_id}/avatar-telemetry-stream` — frame shape, gates, max-connections behavior all preserved.
- `AvatarTelemetryConfig.max_connections_per_agent` — the fleet endpoint shares one connection across N agents, so this cap does NOT change.
- AD-722b-3 diff machinery — reused unchanged.
- AD-722c history append, AD-722d records writer — best-effort per-frame, same as per-agent.
- HXI per-agent telemetry stores — v1 fleet hook does NOT migrate them. AD-722b-4a forward marker for store consolidation.
- AD-731 invariant.

---

## Verification Commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722b4_fleet_telemetry.py -v -n 0 | Select-Object -Last 25
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722b_telemetry_ws.py tests/test_ad722b3_snapshot_diff.py -v -n 0 | Select-Object -Last 20
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3

# UI gate (AD-738b — vitest AND npm run build BOTH required).
cd ui ; npx vitest run ; npm run build ; cd ..
```

---

## Tracker Updates

- **PROGRESS.md:** `AD-722b-4 — Fleet avatar telemetry stream (+6 pytest +3 vitest tests; closes #601). New WS at /api/agent/avatar-telemetry/stream fans out per-agent publish loops over one connection. Every frame carries explicit agent_id field. Per-agent endpoint preserved. fleet_stream_enabled default-ON. HXI hook stub (useFleetAvatarTelemetry) ships; per-agent store migration deferred to AD-722b-4a.`
- **roadmap.md:** remove #601; add forward marker AD-722b-4a (consumer-side store consolidation), AD-722b-4-1 (dynamic crew membership during connection lifetime).
- **DECISIONS.md:** append `### AD-722b-4 — Fleet telemetry stream`.

---

## License Disposition

All-internal Apache 2.0. No new pip / npm deps.

---

## Forward markers (technical-trigger language)

- **AD-722b-4a — Consumer-side store consolidation.** Advances when HXI has 4+ avatar tiles open simultaneously AND profiling shows per-agent hook setup cost dominates initial paint, OR when a deployment renders >8 avatars per view (analytics-heavy workloads).
- **AD-722b-4-1 — Dynamic crew membership.** Advances when crew spawn/despawn during a fleet-stream lifetime is observed in production AND the disconnect-reconnect cost is measurable.

---

## Acceptance Criteria

- ✅ Config field added.
- ✅ New endpoint registered at `/avatar-telemetry/stream`.
- ✅ 6 pytest tests + 2 vitest tests pass.
- ✅ Existing per-agent tests (`test_ad722b_*.py`) stay green UNCHANGED.
- ✅ Full gate green.
- ✅ `npx vitest run` AND `npm run build` BOTH green (AD-738b).
- ✅ No emoji in `useFleetAvatarTelemetry.ts` (HXI principle #3 — pure logic file, no JSX).
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
Per-agent WS handler:
  src/probos/routers/agents.py:669: @router.websocket("/{agent_id}/avatar-telemetry-stream")
  src/probos/routers/agents.py:670: async def agent_avatar_telemetry_stream(

AD-722b-3 diff config fields (Wave 159):
  src/probos/routers/agents.py:794: cfg_t.ws_diff_enabled
  src/probos/routers/agents.py:795: cfg_t.ws_full_snapshot_every_n
  src/probos/routers/agents.py:804: cfg_t.ws_diff_threshold

AvatarTelemetryConfig:
  src/probos/config.py:1025: class AvatarTelemetryConfig(BaseModel):
  src/probos/config.py:1049: max_connections_per_agent: int = 4

is_crew_agent (in-scope import):
  src/probos/routers/agents.py:1005: if not is_crew_agent(agent, runtime.ontology):

snapshot_diff:
  src/probos/avatars/snapshot_diff.py (verified Wave 159).

Router prefix (pass-2 verification — URL prefix fix):
  src/probos/routers/agents.py:30: router = APIRouter(prefix="/api/agent", tags=["agents"])
  → Fleet endpoint full path: /api/agent/avatar-telemetry/stream (NOT /api/avatar-telemetry/stream).
```

---

## Revision (2026-05-14)

Pass-1 review (`prompts/Reviews/ad-722b-4-multi-agent-telemetry-stream-review.md`) raised 3 Required findings (1 critical URL bug + 2 test/wording) + 5 Recommended. Revision addresses all 3 Required and 1 of the 5 Recommended (#4 unmount-cleanup vitest test). Recommended 1, 2, 3, 5 absorbed inline or already correct per pass-1 Verified list.

| # | Finding | Resolution |
|---|---|---|
| Required 1 (CRITICAL) | Hook URL omits `/api/agent` router prefix \u2192 404 | `deriveFleetUrl()` in Section 3 now returns `/api/agent/avatar-telemetry/stream`. Solution Overview gains a sentence documenting the router-prefix mount and the resolved full path. Files-to-modify "Verified anchors" gains an explicit row pointing at `routers/agents.py:30` for the prefix. |
| Required 2 | pytest WS tests use unprefixed path | Section 4 pytest test plan now leads with an explicit bold reminder: *\"All `TestClient.websocket_connect(...)` calls use the URL `/api/agent/avatar-telemetry/stream`.\"* |
| Required 3 | Routing-precedence claim in verification step 6 is misleading | Section 2 Builder verification step 6 rewritten: insertion order does NOT affect routing for this pair (path literals diverge cleanly \u2014 `/avatar-telemetry/stream` cannot match `/{agent_id}/avatar-telemetry-stream` because the static segment doesn't fit a path parameter). Insertion at ~937 is cosmetic. |
| Recommended 4 | Missing Vitest unmount-cleanup test | Added test #3 `closes WebSocket on unmount` to the Vitest plan. Test count updated 2 \u2192 3 in tracker line. |

**Out-of-scope for this revision** (deferred per "no scope expansion" rule):

- Recommended 1 (`asyncio.create_task` ref-store discipline in `_publish_one`) \u2014 acknowledged as matching the existing per-agent pattern; the `asyncio.wait({wait_event, wait_timer}, ...)` holds refs on the stack for the duration of the await. Acceptable as-is; Builder may add a comment line at discretion.
- Recommended 2 (`event_bus.unsubscribe` arg validation) \u2014 the current `try/except` around the unsubscribe loop is already narrow per-agent; no change needed.
- Recommended 3 (`_last_self_avatar_snap` cross-handler race) \u2014 documented in Section 2 as benign (last-write-wins, atomic Python attr writes); Builder adds a comment line at discretion.
- Recommended 5 (silent-skip on empty diff) \u2014 matches AD-722b-3 semantics; Builder adds a comment line at discretion.
- Nits 1-3 \u2014 already correct or trivial.

**Cross-prompt coordination:** No collision with AD-726 or AD-722a-4 revisions. The router-prefix fix is internal to AD-722b-4; the only touchpoint with the rest of the wave is the standing AD-738b / BF-279 UI gate, which both verification commands honor (`vitest run` AND `npm run build`).
