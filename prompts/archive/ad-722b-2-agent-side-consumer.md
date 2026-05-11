# AD-722b-2 — Agent-Side Consumption of Avatar Telemetry Push

**Status:** Ready
**Parent:** AD-722b (Wave 142, shipped commit 7e08110)
**Closes:** GH #599
**Estimated tests:** +3 (backend, in `tests/test_ad722b_websocket_push.py`)

## Problem

The WebSocket push channel (`WS /api/agent/{id}/avatar-telemetry-stream`) currently serves UI consumers only. The agent's own cached snapshot (`_last_self_avatar_snap`, consumed by `_build_avatar_self_observation()` for INTEROCEPTION prompt injection and by `divergence_detector` for modulation lookup) is populated only when `observe_self_avatar()` is invoked from the DM chat handler.

Result: during chain reasoning, multi-turn workflows, or any path that does NOT re-enter the DM handler, the agent's self-observation is stale — even though the push channel is broadcasting fresh snapshots to UI subscribers in the same process. The agent is the only consumer of its own state that doesn't get the push.

## Solution (Option 1: piggyback on existing broadcast)

The WS publish loop in `routers/agents.py` already:
1. Resolves the agent (line 666: `agent = runtime.registry.get(agent_id)`).
2. Builds a snapshot every publish tick (lines 705 initial, 732 loop).
3. Has `agent` in closure scope inside `_publish_loop`.

Add a single side-effect line after each `build_telemetry_snapshot()` call inside the WS handler: `agent._last_self_avatar_snap = snap`.

**Why not put it in `build_telemetry_snapshot()` itself:** That function is also called from the HTTP GET endpoint at line 630 (idempotent read). Mutating agent state from a GET handler is a read-side-effect regression.

**Why not Option 2 (agent opens self-WS):** One persistent connection per agent scales poorly (N agents × idle WS), adds a new failure mode (self-connection churn), and provides no fidelity gain over the in-process write.

## Implementation

### Section 1 — Cache-write on initial snapshot

`src/probos/routers/agents.py` (~line 705 inside `agent_avatar_telemetry_stream`):

**SEARCH:**
```python
        # Send an initial snapshot immediately on connect (UI populates fast).
        try:
            initial = await build_telemetry_snapshot(agent_id, runtime)
            await websocket.send_json(initial.to_dict())
        except Exception:
            logger.warning(
                "AD-722b: initial snapshot send failed for agent=%s",
                agent_id, exc_info=True,
            )
```

**REPLACE:**
```python
        # Send an initial snapshot immediately on connect (UI populates fast).
        # AD-722b-2: also write to agent._last_self_avatar_snap so the agent's
        # own sensorium (INTEROCEPTION) stays fresh without re-polling.
        try:
            initial = await build_telemetry_snapshot(agent_id, runtime)
            agent._last_self_avatar_snap = initial
            await websocket.send_json(initial.to_dict())
        except Exception:
            logger.warning(
                "AD-722b: initial snapshot send failed for agent=%s",
                agent_id, exc_info=True,
            )
```

### Section 2 — Cache-write on each publish tick

`src/probos/routers/agents.py` (~line 732 inside `_publish_loop`):

**SEARCH:**
```python
                # Build + send.
                snap = await build_telemetry_snapshot(agent_id, runtime)
                await websocket.send_json(snap.to_dict())
```

**REPLACE:**
```python
                # Build + send.
                # AD-722b-2: same side-effect as initial — keep agent cache fresh.
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                await websocket.send_json(snap.to_dict())
```

**Builder verification before applying:** Line numbers may have shifted; grep for the exact SEARCH text before each replacement.

### Section 3 — Tests

Append to `tests/test_ad722b_websocket_push.py`:

```python
@pytest.mark.asyncio
async def test_ad722b_2_ws_push_populates_agent_self_snap(runtime_with_avatar_telemetry):
    """AD-722b-2: agent's _last_self_avatar_snap is written on initial WS send."""
    runtime = runtime_with_avatar_telemetry
    agent = runtime.registry.get("agent-007")
    agent._last_self_avatar_snap = None  # explicit stale baseline

    client = TestClient(runtime.app)
    with client.websocket_connect("/api/agent/agent-007/avatar-telemetry-stream") as ws:
        _ = ws.receive_json()  # initial snapshot
        assert agent._last_self_avatar_snap is not None
        assert agent._last_self_avatar_snap.agent_id == "agent-007"


@pytest.mark.asyncio
async def test_ad722b_2_ws_push_refreshes_agent_self_snap_on_tick(runtime_with_avatar_telemetry):
    """AD-722b-2: subsequent ticks overwrite the cached snapshot."""
    runtime = runtime_with_avatar_telemetry
    agent = runtime.registry.get("agent-007")

    client = TestClient(runtime.app)
    with client.websocket_connect("/api/agent/agent-007/avatar-telemetry-stream") as ws:
        _ = ws.receive_json()
        first = agent._last_self_avatar_snap
        # Trigger an event-driven publish via the event bus.
        runtime.avatar_event_bus.notify("agent-007")
        _ = ws.receive_json()
        second = agent._last_self_avatar_snap
        # Same agent, but a distinct object instance (new build).
        assert second is not first
        assert second.agent_id == "agent-007"


@pytest.mark.asyncio
async def test_ad722b_2_http_get_does_not_mutate_agent_self_snap(runtime_with_avatar_telemetry):
    """AD-722b-2: idempotent-read invariant — HTTP GET must not write the cache."""
    runtime = runtime_with_avatar_telemetry
    agent = runtime.registry.get("agent-007")
    agent._last_self_avatar_snap = None

    client = TestClient(runtime.app)
    resp = client.get("/api/agent/agent-007/avatar-telemetry")
    assert resp.status_code == 200
    assert agent._last_self_avatar_snap is None  # HTTP path remains side-effect-free
```

Reuse the existing `runtime_with_avatar_telemetry` fixture and `agent-007` test agent from the existing test file.

## What this does NOT change

- `build_telemetry_snapshot()` signature, behavior, or call sites outside the WS handler.
- HTTP GET `/avatar-telemetry` endpoint behavior (verified by Section 3 test #3).
- `observe_self_avatar()` — still callable, still writes the cache; this AD makes it redundant when a WS subscriber is connected but does not remove it.
- WS frame protocol (UI sees identical JSON).

## Acceptance criteria

- [ ] Both SEARCH/REPLACE blocks apply cleanly at HEAD.
- [ ] Three new tests green; existing AD-722b tests unchanged.
- [ ] HTTP GET idempotency test asserts the read-side-effect-free invariant.
- [ ] No new imports required.
- [ ] Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-11, HEAD e066c0b)

```
grep -n "agent = runtime.registry.get" src/probos/routers/agents.py
  666: agent = runtime.registry.get(agent_id)
grep -n "initial = await build_telemetry_snapshot" src/probos/routers/agents.py
  705: initial = await build_telemetry_snapshot(agent_id, runtime)
grep -n "snap = await build_telemetry_snapshot" src/probos/routers/agents.py
  732: snap = await build_telemetry_snapshot(agent_id, runtime)
grep -n "_last_self_avatar_snap" src/probos/cognitive/cognitive_agent.py
  486: self._last_self_avatar_snap: Any = None
  2950: self._last_self_avatar_snap = snap
  2965: snap = self._last_self_avatar_snap
grep -n "_last_self_avatar_snap" src/probos/avatars/divergence_detector.py
  361: snap = getattr(agent, "_last_self_avatar_snap", None)
```
