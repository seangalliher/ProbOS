# AD-722b — WebSocket push channel for avatar telemetry (single-agent stream)

**Status:** READY FOR BUILDER
**Wave:** 142 (single-prompt wave, single commit)
**Dispatch:** [prompts/WAVE-142-DISPATCH.md](WAVE-142-DISPATCH.md)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**Depends on:** AD-722 v1 (SHIPPED Wave 140), AD-722-1 (SHIPPED Wave 141), AD-722f (SHIPPED Wave 141 — sampling state machine + `runtime.avatar_sampling_state`)
**Issue:** [#568](https://github.com/seangalliher/seangalliher/ProbOS/issues/568) — *use the canonical owner/repo at file time; #568 is the AD-722b tracking issue per BUILDER-EXECUTION-PLAN-avatar-cluster.md*
**Risk:** **MEDIUM** — new WS endpoint + new connection-manager module + new event-bus module + 6 trigger sites. The read-only contract on the snapshot side is preserved (the WS surface is pure projection of `runtime.avatar_sampling_state` + `build_telemetry_snapshot`).
**Estimated tests:** ≥ 24 Python boundary cases (connection lifecycle, publish-on-event, fan-out, max-connections, sampling-tier flip on subscribe/disconnect, feature gates, AD-722f trigger notifies). ≥ 4 Vitest UI cases (WS-first, poll fallback on `onerror`/`onclose`, frame render, no-double-poll after WS open).

> **Builder:** read [prompts/WAVE-142-DISPATCH.md](WAVE-142-DISPATCH.md) for cross-AD context, license posture, and the engineering-principles checklist. Read [prompts/BUILDER-EXECUTION-PLAN.md](BUILDER-EXECUTION-PLAN.md) for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal (TL;DR)

Today the avatar-telemetry channel is poll-only: HXI's `<SelfImageTab>` calls `GET /api/agent/{id}/avatar-telemetry` every 2000 ms (`POLL_MS` at `ui/src/components/profile/SelfImageTab.tsx:42`). At HIGH-tier sampling (AD-722f, 250 ms) this would be 4 polls/sec/tab — wasteful, and even at NORMAL the latency floor is 2 s. AD-722b replaces that poll surface (for the popout / SelfImageTab context only) with an event-driven push channel:

- New endpoint **`WS /api/agent/{agent_id}/avatar-telemetry-stream`** (registered on the existing `agents` `APIRouter`).
- Server publishes `AvatarTelemetrySnapshot.to_dict()` JSON frames at the rate dictated by `runtime.avatar_sampling_state.current_rate_ms(agent_id)`. State-changing triggers (DM in/out, chain in/out, reply emitted) wake the publish loop *early* via a per-agent `asyncio.Event`, surfacing the change well below the timer interval.
- WS subscribe flips the agent's sampling tier to **HIGH** via a new `enter_popout(agent_id, connection_id)` method on the state machine; disconnect flips it back via `exit_popout(...)`. This is the trigger surface AD-722f deliberately left as a forward marker.
- HXI: `SelfImageTab` upgrades to **WS-first with poll fallback**. On `onerror` or `onclose` within 5 s of opening, falls back to the existing 2 s poll. The poll code path stays intact as the safety net.

Captain ruling 2026-05-10 (Ezri's request, [DECISIONS.md AD-722 addendum (i)](../DECISIONS.md)):

> *"A push model where I receive a signal when something shifts would start to feel more like proprioception than inventory."*

This is the architectural delta from "inventory" to "proprioception": a shifting state-channel rather than a periodic snapshot.

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# Existing GET endpoint + feature gate (parallel target for the WS endpoint)
grep -n "avatar-telemetry\|_avatars_feature_check\|@router\." src/probos/routers/agents.py
   377: def _avatars_feature_check(runtime: Any) -> None:
   388: @router.post("/{agent_id}/appearance/propose"...)
   398:     _avatars_feature_check(runtime)
   427: @router.put("/{agent_id}/appearance")
   438:     _avatars_feature_check(runtime)
   493: @router.get("/{agent_id}/avatar-telemetry")
   502:     _avatars_feature_check(runtime)
   518: @router.post("/{agent_id}/chat")

# AD-722 GET endpoint — full body (lines 493-515) — feature gate is the model AD-722b mirrors
grep -n "avatar_telemetry_disabled" src/probos/routers/agents.py
   505: detail="avatar_telemetry_disabled"

# build_telemetry_snapshot — payload contract; .to_dict() is JSON-serialisable
grep -n "def build_telemetry_snapshot\|def to_dict\|sampling_rate_ms\|sampling_tier" src/probos/avatars/telemetry.py
   227: class AvatarTelemetrySnapshot:
   246: sampling_rate_ms: int                # AD-722f
   247: sampling_tier: str                   # AD-722f
   249: def to_dict(self) -> dict[str, Any]:
   415: async def build_telemetry_snapshot(

# AvatarSamplingStateMachine — public methods at HEAD (Wave 141)
grep -n "def enter_dm\|def exit_dm\|def enter_chain\|def exit_chain\|def current_tier\|def current_rate_ms\|def snapshot_counts" src/probos/avatars/sampling_state.py
   64: def enter_dm(self, agent_id: str) -> None:
   68: def exit_dm(self, agent_id: str) -> None:
   83: def enter_chain(self, agent_id: str) -> None:
   87: def exit_chain(self, agent_id: str) -> None:
  103: def current_tier(self, agent_id: str) -> str:
  115: def current_rate_ms(self, agent_id: str) -> int:
  123: def snapshot_counts(self, agent_id: str) -> dict[str, int]:
# enter_popout / exit_popout — DO NOT EXIST AT HEAD (greenfield in this AD).
# enter_subscriber / exit_subscriber — referenced as forward markers in
# sampling_state.py module docstring; this AD adopts the name `enter_popout`
# (per the user-prompt and the cluster plan) and the docstring forward-marker
# is updated accordingly.

# CognitiveAgent.mark_reply_emitted — single call site at routers/agents.py
grep -n "mark_reply_emitted\b" src/probos/
   src/probos/cognitive/cognitive_agent.py:215: def mark_reply_emitted(self) -> None:
   src/probos/cognitive/cognitive_agent.py:221: self._last_reply_emit_ts = time.time()
   src/probos/routers/agents.py:721: if hasattr(agent, 'mark_reply_emitted'):
   src/probos/routers/agents.py:722: agent.mark_reply_emitted()
# AD-722f exit_dm sits immediately below this block (lines 724-727 region).

# FastAPI WebSocket scaffolding — there IS an existing pattern at app level
grep -n "@app.websocket\|@router.websocket\|WebSocketDisconnect\|WebSocket" src/probos/api.py
    18: from fastapi import FastAPI, WebSocket, WebSocketDisconnect
   134: _ws_clients: list[WebSocket] = []
   214: @app.websocket("/ws/events")
   215: async def ws_events(websocket: WebSocket) -> None:
   235: except WebSocketDisconnect:
# Existing WS pattern is APP-level (`@app.websocket`) and ALL-CLIENTS broadcast
# (the _ws_clients list is global). AD-722b's WS endpoint is PER-AGENT and
# lives on the `agents` ROUTER, not at app-level — APIRouter supports
# @router.websocket() since FastAPI 0.39+ (we run >=0.115 per pyproject.toml:34).

# ws/events test pattern — none exists yet; TestClient.websocket_connect is
# the standard FastAPI pattern for boundary tests
grep -rn "websocket_connect" tests/
# (no matches — AD-722b introduces the first WS-test fixture pattern in this codebase)

# AvatarTelemetryConfig — surface AD-722b extends with max_connections_per_agent
grep -n "class AvatarTelemetryConfig\|polling_interval_ms\|sampling_rates\|max_connections" src/probos/config.py
   973: class AvatarTelemetryConfig(BaseModel):
   990: enabled: bool = True
   991: inject_into_agent_context: bool = False
   992: mouth_active_window_seconds: float = 3.0
   993: polling_interval_ms: int = 2000
   994: sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)
# max_connections_per_agent — DOES NOT EXIST AT HEAD (greenfield).

# UI — SelfImageTab polling effect
grep -n "POLL_MS\|setInterval\|useEffect" ui/src/components/profile/SelfImageTab.tsx
   42: const POLL_MS = 2000;
   53: useEffect(() => {
   54: if (!isActive || !agentId) return;
   72: const id = setInterval(fetchOnce, POLL_MS);
# Lines 53-76 are the polling effect; AD-722b wraps this logic in a WS-first
# branch with the existing fetch as the fallback path.

# UI — existing WebSocket reconnection pattern (template, not extension target)
grep -n "new WebSocket\|onclose\|MAX_BACKOFF" ui/src/hooks/useWebSocket.ts
    6: const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/events`;
    7: const MAX_BACKOFF = 30_000;
   22: const ws = new WebSocket(WS_URL);
   40: ws.onclose = () => {
# AD-722b does NOT reuse this hook — it's app-level and singular. The new
# per-agent WS connection lives inside SelfImageTab's useEffect, lifecycle
# scoped to the tab's `isActive` state.

# fastapi version — confirms @router.websocket support
grep -n "fastapi" pyproject.toml
   34:     "fastapi>=0.115",
```

> **Pre-flight findings (informational; do not block build):**
>
> 1. There is no FastAPI **per-router** WebSocket pattern in the codebase yet. AD-722b establishes it. Verified: `APIRouter.websocket(...)` is supported in FastAPI ≥ 0.39 (we run ≥ 0.115). The endpoint registers via the existing `app.include_router(agents.router)` call at `api.py:194-211` — no app-level changes required.
> 2. `AvatarSamplingStateMachine`'s docstring (`src/probos/avatars/sampling_state.py:15-19`) calls the forward-marker methods `enter_subscriber`/`exit_subscriber`. The user-prompt and the cluster plan adopt the name **`enter_popout`/`exit_popout`** for clarity (the WS subscriber IS the popout for v1). The docstring updates accordingly; no code under that name exists yet — both names are greenfield.
> 3. The existing AD-722f phantom-API test (`tests/test_ad722f_adaptive_sampling.py::test_state_machine_does_not_expose_wr_methods`) asserts the absence of `enter_wr`/`exit_wr` only — no test asserts the absence of popout methods. AD-722b adds them; no existing test breaks.

---

## 3. License posture

Apache 2.0 stays Apache 2.0. **Zero new Python deps.** **Zero new JS deps.** The vitest mock for `WebSocket` is a small in-tree class (≤ 30 lines) that records calls and surfaces `onopen`/`onmessage`/`onerror`/`onclose` — `mock-socket` (MIT) is NOT absorbed (in-tree mock is simpler than adding a dep). `pyproject.toml` and `ui/package.json` are bit-for-bit identical pre/post commit — Reviewer fails on any diff.

---

## 4. Architectural decisions (resolved by architect; do NOT re-litigate)

| # | Decision | Resolution | Rationale |
|---|---|---|---|
| 1 | WS endpoint path | **`WS /api/agent/{agent_id}/avatar-telemetry-stream`** | Parallel to the existing `GET /{agent_id}/avatar-telemetry`; same `agents` router prefix `/api/agent`. No path collision (verified: no existing `/avatar-telemetry-stream` route at HEAD). |
| 2 | Payload protocol | **Full JSON snapshots matching `AvatarTelemetrySnapshot.to_dict()`** | Polling-fallback shape-compatible (UI parsers stay identical). Small payload (~500 bytes typical). Delta encoding rejected for v1 — premature optimization, complicates fallback parity, and the diff would itself need a state-tracking surface. |
| 3 | Authentication | **Same feature-gate-only model as the existing GET endpoint.** No new auth. | The GET endpoint is behind `_avatars_feature_check` + `avatar_telemetry.enabled` — no crew-auth, no token. AD-722b mirrors that exactly. **Documented gap:** when federation lands (cross-mesh visibility) auth comes in with that AD; AD-722b does not pre-build infra for it. The gap is logged in §11 forward-markers as **AD-722b-1 (auth on avatar telemetry surfaces)**. |
| 4 | Backpressure / fan-out | **WS subscribe → `enter_popout(agent_id, connection_id)` → tier flip to HIGH; disconnect → `exit_popout(...)` → flip back.** | Reuses AD-722f's per-agent state machine. Refcount semantics match the existing `enter_dm`/`enter_chain` design — multiple HXI tabs subscribing to the same agent each enter; tier stays HIGH while ≥ 1 connection is open. |
| 5 | Connection lifecycle | **Per-connection WS-level keepalive: server sends a `{"type":"ping"}` frame every 30 s when no other frame has been sent. Client may send pongs; server does not require them. Stale connections (`WebSocketDisconnect` raised by `receive`) trigger immediate `exit_popout` + connection cleanup.** | Mirrors the `/ws/events` 30 s pattern (`api.py:230-234`). Pong-not-required keeps the client minimal — `WebSocketDisconnect` from a dead TCP socket fires server-side regardless. |
| 6 | Max connections per agent | **Default 4. Configurable via new `max_connections_per_agent` field on `AvatarTelemetryConfig`. Over-limit connection accepted-then-immediately-closed with code `1008` (policy violation) and a `{"type":"error","reason":"max_connections_exceeded"}` frame.** | Reasonable for one Captain on multiple HXI tabs/devices. WebSocket spec requires accept-before-close to send a structured close frame; raising in the handshake is allowed but loses the reason payload. |
| 7 | UI upgrade strategy | **WS-first with poll fallback.** SelfImageTab opens WS on mount (when `isActive=true`); if `onopen` fires within 5 s, polling is suppressed. If `onerror` or `onclose` fires before `onopen`, OR `onopen` never fires within 5 s, the existing poll fallback (`setInterval(fetchOnce, POLL_MS)`) starts. WS reconnect on `onclose` after `onopen` had succeeded: capped 1-5-30 s backoff (matches `useWebSocket.ts` shape). | Feature-detected and graceful. The poll path stays intact as the safety net. Test coverage: 4 vitest cases (WS-success, WS-error fallback, WS-timeout fallback, frame render parity). |
| 8 | Server-side publish loop | **Per-connection `asyncio.Task` running a `while True:` loop that does `await asyncio.wait({timer_task, event_task}, return_when=FIRST_COMPLETED)`.** Timer fires at `runtime.avatar_sampling_state.current_rate_ms(agent_id)` per iteration; event_task is `runtime.avatar_event_bus.subscribe(agent_id).wait()` (per-agent `asyncio.Event` cleared after each wake). On either wake, build snapshot + send. Loop exits on `WebSocketDisconnect` from any branch (the send raises, propagates, terminates the task). | Clean cancellation semantics. The event surface is the AD-722f trigger surfaces (DM in/out, chain in/out) and the existing `mark_reply_emitted` site (no new cross-cutting wiring). |
| 9 | Test infrastructure (Python) | **`fastapi.testclient.TestClient.websocket_connect()`** — Starlette's bundled WS client. Used inside synchronous test bodies via the context-manager form (`with client.websocket_connect(...) as ws: ws.receive_json()`). No new test deps. | Identical to FastAPI's documented test pattern. Tests run synchronously even though the server side is async. |
| 10 | State-change event detection | **No fine-grained snapshot diffing.** The `runtime.avatar_event_bus.notify(agent_id)` call is added at the EXISTING AD-722f trigger sites (`enter_dm`/`exit_dm` in `routers/agents.py`, `enter_chain`/`exit_chain` in `cognitive/cognitive_agent.py`) PLUS one new site at `mark_reply_emitted()` itself. The publish loop's wake event is "state-changing trigger fired"; the loop builds + sends a fresh snapshot each wake. Working_state and mouth_active flips are second-order — `mark_reply_emitted` notifies (mouth_active true→false next refresh), and DM/chain enter/exit flips working_state. Sufficient coverage in v1; full delta detection is forward-marker AD-722b-3. | Simpler than diff detection. The trigger surfaces ARE the state-change surfaces in practice. Documented limitation: a tier3 alert appearing mid-call is surfaced on the next *timer* iteration only (HIGH=250 ms in popout — acceptable). |

---

## 5. Scope (this AD only)

Single commit. Six surfaces touched + two new files:

1. **Add** `src/probos/avatars/events.py` — `AvatarEventBus` (per-agent `asyncio.Event` registry).
2. **Add** `src/probos/avatars/ws_connection_manager.py` — `AvatarTelemetryConnectionManager` (per-agent connection set + max enforcement).
3. **Modify** `src/probos/avatars/sampling_state.py` — add `enter_popout(agent_id)` / `exit_popout(agent_id)` methods. Update module docstring to reflect that the popout trigger is now wired (no longer a forward marker).
4. **Modify** `src/probos/config.py` — add `max_connections_per_agent: int = 4` to `AvatarTelemetryConfig` with floor validator.
5. **Modify** `src/probos/runtime.py` — initialize `self.avatar_event_bus` and `self.avatar_telemetry_connection_manager` in `__init__()` adjacent to `self.avatar_sampling_state` (around line 417).
6. **Modify** `src/probos/cognitive/cognitive_agent.py` — `mark_reply_emitted()` calls `self._runtime.avatar_event_bus.notify(self.id)` (tier-2 degrade if missing).
7. **Modify** `src/probos/routers/agents.py` — add `enter_popout`/`exit_popout` and `avatar_event_bus.notify()` calls at the existing AD-722f trigger sites (`enter_dm`/`exit_dm`); add the new `@router.websocket("/{agent_id}/avatar-telemetry-stream")` endpoint.
8. **Modify** `src/probos/cognitive/cognitive_agent.py` — `avatar_event_bus.notify(self.id)` at the existing AD-722f chain wiring (`enter_chain`/`exit_chain`).
9. **Modify** `ui/src/components/profile/SelfImageTab.tsx` — WS-first with poll fallback inside the existing `useEffect`.
10. **Add** `tests/test_ad722b_websocket_push.py` — boundary tests.
11. **Modify** `ui/src/__tests__/SelfImageTab.test.tsx` — add 4 new cases for the WS upgrade. Existing 7 cases stay green (poll fallback path is what they exercise; the WS branch is new).

---

## 6. Non-goals (deferred forward markers)

| Marker | Deferred to | Why not v1 |
|---|---|---|
| **AD-722b-1** | Crew-scope auth on avatar-telemetry surfaces (HTTP + WS) | Federation-paired AD; not built independently. |
| **AD-722b-2** | Agent-side WS push to populate `_last_self_avatar_snap` cache | Read-side stays poll-driven for the in-process `observe_self_avatar()` call. Agent-loop integration is its own AD. |
| **AD-722b-3** | Fine-grained state-diff detection at snapshot-build time | v1 publishes at trigger surfaces + timer. AD-722b-3 would add a per-agent last-snapshot cache + field-diff to surface tier3 alerts / load changes between trigger fires. |
| **AD-722b-4** | Multi-agent telemetry stream (one connection, fan-out by `agent_id`) | v1 is per-agent (1 connection = 1 agent). Multi-agent stream is a separate concurrency surface. |
| **AD-722b-5** | Federation cross-mesh push | Pairs with AD-722b-1 auth. |

Reviewer fails the prompt if any deliverable touches `voice.ts`, any VRM file, `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `pyproject.toml`, `ui/package.json`, or **the existing GET `/avatar-telemetry` HTTP endpoint** (it stays as the polling fallback target — modifying it is out of scope).

---

## 7. Deliverables

### D1 — `AvatarEventBus` (`src/probos/avatars/events.py`, new file)

```python
"""AD-722b: per-agent avatar-telemetry event bus.

Lightweight ``asyncio.Event`` registry keyed by agent_id. Trigger sites
(``enter_dm``, ``exit_dm``, ``enter_chain``, ``exit_chain``,
``enter_popout``, ``exit_popout``, ``mark_reply_emitted``) call
``notify(agent_id)`` to wake any subscribers (the WS publish loop).
Subscribers obtain a fresh ``asyncio.Event`` via ``subscribe(agent_id)``
and ``await event.wait()`` inside their loop, ``event.clear()`` after
processing.

Thread-safety: ``asyncio.Event.set()`` is safe to call from synchronous
code IF the event was created on a running loop; we create on first
``subscribe`` (which always runs from the WS handler coroutine, i.e.
on the loop). ``notify`` may be called from sync code (e.g. the DM
trigger site in routers/agents.py — FastAPI sync handler section).
That is also safe — ``Event.set()`` is documented as thread-safe-in-
practice for the CPython implementation when the event was bound
to the running loop.

State is volatile by design — restart resets all events.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Iterator

logger = logging.getLogger(__name__)


class AvatarEventBus:
    """Per-agent ``asyncio.Event`` registry.

    Multiple subscribers per agent are supported: each ``subscribe()``
    returns a distinct ``asyncio.Event``; ``notify(agent_id)`` sets all
    events bound to that agent. Subscribers ``clear()`` their own event
    after handling a wake.
    """

    def __init__(self) -> None:
        # agent_id -> set of asyncio.Event instances.
        self._subscribers: dict[str, set[asyncio.Event]] = defaultdict(set)

    def subscribe(self, agent_id: str) -> asyncio.Event:
        """Create + register a fresh event for an agent. Caller owns
        the lifecycle and MUST call ``unsubscribe`` (or use the context
        manager helper below) on close.
        """
        event = asyncio.Event()
        self._subscribers[agent_id].add(event)
        return event

    def unsubscribe(self, agent_id: str, event: asyncio.Event) -> None:
        """Remove a subscriber. Tier-2 — silent on missing key."""
        bucket = self._subscribers.get(agent_id)
        if bucket is None:
            return
        bucket.discard(event)
        if not bucket:
            # Drop empty bucket so unbounded agent_ids don't accumulate.
            self._subscribers.pop(agent_id, None)

    def notify(self, agent_id: str) -> None:
        """Wake every subscriber bound to ``agent_id``. Safe from sync
        and async code. No-op when no subscribers."""
        bucket = self._subscribers.get(agent_id)
        if not bucket:
            return
        for event in bucket:
            try:
                event.set()
            except Exception:
                # Tier-2: a corrupted event is a one-off; log and skip.
                logger.debug(
                    "AD-722b: avatar_event_bus.notify failed for agent=%s",
                    agent_id, exc_info=True,
                )

    def subscriber_count(self, agent_id: str) -> int:
        """Test-only introspection."""
        return len(self._subscribers.get(agent_id, ()))
```

### D2 — `AvatarTelemetryConnectionManager` (`src/probos/avatars/ws_connection_manager.py`, new file)

```python
"""AD-722b: per-agent WebSocket connection registry for avatar telemetry.

Tracks active subscribers per agent for fan-out and max-connection
enforcement. Single-process; no cross-process sharing. Pairs with
``runtime.avatar_sampling_state`` (popout-tier flip on register/unregister)
and ``runtime.avatar_event_bus`` (subscriber wake on trigger).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MaxConnectionsExceeded(Exception):
    """Raised by ``register`` when the per-agent cap is reached."""


class AvatarTelemetryConnectionManager:
    """Per-agent WebSocket registry. Each connection is given a stable
    UUID; the UUID is the handle the WS handler uses to deregister.

    The manager does NOT broadcast frames itself — each connection's
    publish loop owns its own send. The manager exists for:

      1. Max-connections-per-agent enforcement (config-driven cap).
      2. Test-time introspection (``connections_for(agent_id)``).
      3. Future fan-out helpers (forward marker AD-722b-4 multi-agent).
    """

    def __init__(self, max_per_agent: int) -> None:
        if max_per_agent < 1:
            raise ValueError(
                f"max_per_agent must be >= 1, got {max_per_agent}"
            )
        self._max_per_agent = int(max_per_agent)
        # agent_id -> {connection_id: WebSocket}
        self._connections: dict[str, dict[str, "WebSocket"]] = {}

    def register(self, agent_id: str, websocket: "WebSocket") -> str:
        """Allocate a connection_id and register the WS. Raises
        ``MaxConnectionsExceeded`` if the cap is hit.
        """
        bucket = self._connections.setdefault(agent_id, {})
        if len(bucket) >= self._max_per_agent:
            raise MaxConnectionsExceeded(
                f"agent={agent_id} already has {len(bucket)} connections "
                f"(max={self._max_per_agent})"
            )
        connection_id = str(uuid.uuid4())
        bucket[connection_id] = websocket
        return connection_id

    def deregister(self, agent_id: str, connection_id: str) -> None:
        """Tier-2: silent on missing keys (idempotent close paths)."""
        bucket = self._connections.get(agent_id)
        if bucket is None:
            return
        bucket.pop(connection_id, None)
        if not bucket:
            self._connections.pop(agent_id, None)

    def connections_for(self, agent_id: str) -> int:
        return len(self._connections.get(agent_id, ()))

    @property
    def max_per_agent(self) -> int:
        return self._max_per_agent
```

### D3 — `enter_popout` / `exit_popout` on `AvatarSamplingStateMachine`

**Modify** `src/probos/avatars/sampling_state.py`.

**SEARCH** the module docstring forward-marker block (lines 15-19 region):

```python
Trigger surfaces NOT wired in Wave 141 (forward markers):
  - ``enter_subscriber`` / ``exit_subscriber`` — Wave 142 / AD-722b WebSocket
    subscribe/unsubscribe. Method names reserved here for forward-marker
    discoverability; bodies are NOT defined in this AD.
```

**REPLACE** with:

```python
Trigger surfaces wired in Wave 142 (AD-722b):
  - ``enter_popout`` / ``exit_popout`` — WS subscribe/unsubscribe at
    ``WS /api/agent/{id}/avatar-telemetry-stream``. Refcount semantics
    match ``enter_dm`` (multiple HXI tabs subscribing to the same agent
    each enter; tier stays HIGH while >= 1 connection is open).
```

**SEARCH** the `_counts` initialisation (around line 60):

```python
        self._counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"dm": 0, "chain": 0},
        )
```

**REPLACE** with:

```python
        self._counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"dm": 0, "chain": 0, "popout": 0},
        )
```

**Insert** new methods after `exit_chain` (around line 100, before `current_tier`):

```python
    def enter_popout(self, agent_id: str) -> None:
        """AD-722b: WS subscribe → HIGH-tier sampling. Ref-counted to
        tolerate multiple HXI tabs subscribing to the same agent."""
        with self._lock:
            self._counts[agent_id]["popout"] += 1

    def exit_popout(self, agent_id: str) -> None:
        """AD-722b: WS unsubscribe. Spurious-exit clamp matches the
        DM/chain pattern (BF-leakage protection on exception paths)."""
        with self._lock:
            n = self._counts[agent_id]["popout"]
            if n <= 0:
                logger.warning(
                    "AD-722b: spurious exit_popout for agent=%s "
                    "(count was %d); clamping to 0",
                    agent_id, n,
                )
                self._counts[agent_id]["popout"] = 0
                return
            self._counts[agent_id]["popout"] = n - 1
```

**SEARCH** `current_tier` (around line 103):

```python
    def current_tier(self, agent_id: str) -> str:
        """Resolve the active tier for an agent. HIGH > NORMAL > LOW."""
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return TIER_LOW
            if counts.get("dm", 0) > 0:
                return TIER_HIGH
            if counts.get("chain", 0) > 0:
                return TIER_NORMAL
            return TIER_LOW
```

**REPLACE** with:

```python
    def current_tier(self, agent_id: str) -> str:
        """Resolve the active tier for an agent. HIGH > NORMAL > LOW.

        AD-722b: ``popout`` (WS subscriber attached) is HIGH-tier — same
        priority bucket as ``dm``. Either trigger flips to HIGH; chain
        is NORMAL; otherwise LOW.
        """
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return TIER_LOW
            if counts.get("dm", 0) > 0 or counts.get("popout", 0) > 0:
                return TIER_HIGH
            if counts.get("chain", 0) > 0:
                return TIER_NORMAL
            return TIER_LOW
```

**SEARCH** `snapshot_counts` default (around line 127):

```python
            if counts is None:
                return {"dm": 0, "chain": 0}
            return dict(counts)
```

**REPLACE** with:

```python
            if counts is None:
                return {"dm": 0, "chain": 0, "popout": 0}
            return dict(counts)
```

### D4 — Config: `max_connections_per_agent` on `AvatarTelemetryConfig`

**Modify** `src/probos/config.py`.

**SEARCH** (around line 990-994):

```python
    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
```

**REPLACE** with:

```python
    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
    max_connections_per_agent: int = 4       # AD-722b — WS popout connections per agent
```

**Insert** field validator (after the existing `_bound_polling` validator, around line 1006):

```python
    @field_validator("max_connections_per_agent")
    @classmethod
    def _bound_max_connections(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"max_connections_per_agent must be >= 1, got {v}"
            )
        return v
```

### D5 — Runtime initialization

**Modify** `src/probos/runtime.py`.

**SEARCH** the AD-722f initialization block (around line 412-418):

```python
        # AD-722f: per-agent avatar-telemetry sampling state machine.
        # Initialized in __init__ (not finalize) so consumers in cognitive
        # services / routers can rely on its presence at any startup phase.
        # State is volatile by design — restart resets to LOW for every agent.
        from probos.avatars.sampling_state import AvatarSamplingStateMachine
        self.avatar_sampling_state = AvatarSamplingStateMachine(
            rates=self.config.avatar_telemetry.sampling_rates,
        )
```

(Read the actual block at HEAD — if line numbers shifted slightly, the SEARCH still matches verbatim.)

**REPLACE** with:

```python
        # AD-722f: per-agent avatar-telemetry sampling state machine.
        # Initialized in __init__ (not finalize) so consumers in cognitive
        # services / routers can rely on its presence at any startup phase.
        # State is volatile by design — restart resets to LOW for every agent.
        from probos.avatars.sampling_state import AvatarSamplingStateMachine
        self.avatar_sampling_state = AvatarSamplingStateMachine(
            rates=self.config.avatar_telemetry.sampling_rates,
        )

        # AD-722b: avatar-telemetry WS push channel — event bus + connection
        # manager. Co-located with sampling_state for the same lifecycle
        # discipline (eager __init__, volatile across restarts).
        from probos.avatars.events import AvatarEventBus
        from probos.avatars.ws_connection_manager import (
            AvatarTelemetryConnectionManager,
        )
        self.avatar_event_bus = AvatarEventBus()
        self.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
            max_per_agent=self.config.avatar_telemetry.max_connections_per_agent,
        )
```

### D6 — Trigger-site notifies

**Modify** `src/probos/routers/agents.py`. The DM enter/exit sites already host `enter_dm` / `exit_dm` (AD-722f). Append `notify` calls at the same sites.

**SEARCH** the AD-722f DM-enter block (the `_sampling_state.enter_dm(agent_id)` line region — around line 540 area; read at HEAD before editing):

```python
    _sampling_state = getattr(runtime, 'avatar_sampling_state', None)
    if _sampling_state is not None:
        _sampling_state.enter_dm(agent_id)
```

**REPLACE** with:

```python
    _sampling_state = getattr(runtime, 'avatar_sampling_state', None)
    _avatar_event_bus = getattr(runtime, 'avatar_event_bus', None)
    if _sampling_state is not None:
        _sampling_state.enter_dm(agent_id)
    if _avatar_event_bus is not None:
        # AD-722b: wake WS publish loop — DM in-flight is a state change.
        _avatar_event_bus.notify(agent_id)
```

**SEARCH** the AD-722f DM-exit block (after `mark_reply_emitted`, around line 724):

```python
    # AD-722f: matched exit for the enter_dm at the top of agent_chat.
    # Spurious-exit clamp in the state machine handles the (rare)
    # exception-path case where enter fired but exit didn't.
    if _sampling_state is not None:
        _sampling_state.exit_dm(agent_id)
```

**REPLACE** with:

```python
    # AD-722f: matched exit for the enter_dm at the top of agent_chat.
    # Spurious-exit clamp in the state machine handles the (rare)
    # exception-path case where enter fired but exit didn't.
    if _sampling_state is not None:
        _sampling_state.exit_dm(agent_id)
    # AD-722b: wake WS publish loop — DM-exit is a state change
    # (working_state goes from 'responding' back to 'idle').
    if _avatar_event_bus is not None:
        _avatar_event_bus.notify(agent_id)
```

**Modify** `src/probos/cognitive/cognitive_agent.py`. Add notify calls at the AD-722f chain wiring.

**SEARCH** (around lines 1394-1410 — the chain `try/finally` block):

```python
            _sampling_state = getattr(self._runtime, 'avatar_sampling_state', None)
            if _sampling_state is not None:
                _sampling_state.enter_chain(self.id)
            try:
                chain_result = await self._execute_chain_with_intent_routing(observation)
            finally:
                if _sampling_state is not None:
                    _sampling_state.exit_chain(self.id)
```

**REPLACE** with:

```python
            _sampling_state = getattr(self._runtime, 'avatar_sampling_state', None)
            _avatar_event_bus = getattr(self._runtime, 'avatar_event_bus', None)
            if _sampling_state is not None:
                _sampling_state.enter_chain(self.id)
            if _avatar_event_bus is not None:
                # AD-722b: wake WS publish loop on chain enter.
                _avatar_event_bus.notify(self.id)
            try:
                chain_result = await self._execute_chain_with_intent_routing(observation)
            finally:
                if _sampling_state is not None:
                    _sampling_state.exit_chain(self.id)
                if _avatar_event_bus is not None:
                    _avatar_event_bus.notify(self.id)
```

**SEARCH** `mark_reply_emitted` (around line 215):

```python
    def mark_reply_emitted(self) -> None:
        """AD-722: stamp the last-reply emission time. Caller wiring is
        the chat handler at `routers/agents.py:460+` — exactly one call site."""
        self._last_reply_emit_ts = time.time()
```

**REPLACE** with:

```python
    def mark_reply_emitted(self) -> None:
        """AD-722: stamp the last-reply emission time. Caller wiring is
        the chat handler at `routers/agents.py:460+` — exactly one call site.

        AD-722b: also notifies the avatar event bus so any open WS
        subscribers wake immediately (mouth_active flips from True back to
        False once the 3 s window elapses; this notify gives the loop a
        head-start so the next iteration emits a fresh snapshot reflecting
        the brand-new last_reply_emitted_at).
        """
        self._last_reply_emit_ts = time.time()
        bus = getattr(self._runtime, 'avatar_event_bus', None)
        if bus is not None:
            try:
                bus.notify(self.id)
            except Exception:
                logger.debug(
                    "AD-722b: avatar_event_bus.notify failed during "
                    "mark_reply_emitted for agent=%s",
                    self.id, exc_info=True,
                )
```

`logger` is already imported at the top of `cognitive_agent.py` — verify at HEAD before editing.

### D7 — WebSocket endpoint

**Modify** `src/probos/routers/agents.py`. Imports first.

**SEARCH** the existing imports block (lines 10-11):

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
```

**REPLACE** with:

```python
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
```

**Insert** the new WebSocket endpoint immediately after the existing `GET /{agent_id}/avatar-telemetry` endpoint (after the function returning `snap.to_dict()`, around line 515):

```python
@router.websocket("/{agent_id}/avatar-telemetry-stream")
async def agent_avatar_telemetry_stream(
    websocket: WebSocket,
    agent_id: str,
) -> None:
    """AD-722b: WebSocket push channel for avatar telemetry.

    Same feature gates as the GET endpoint. Subscribe → tier flip to
    HIGH via ``avatar_sampling_state.enter_popout``; disconnect → flip
    back via ``exit_popout``. Publish loop awaits both an interval timer
    (rate from ``current_rate_ms``) and a per-agent event (set by trigger
    surfaces). On either wake, builds + sends a fresh snapshot.

    Authentication: feature-gate-only — same model as the GET endpoint.
    Forward marker AD-722b-1 covers crew-scoped auth.
    """
    runtime = websocket.app.state.runtime
    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)

    # Feature gate 1: avatars system disabled — close before accept.
    if avatars_cfg is None or not avatars_cfg.enabled:
        await websocket.close(code=1008, reason="avatars_disabled")
        return
    # Feature gate 2: avatar telemetry disabled.
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        await websocket.close(code=1008, reason="avatar_telemetry_disabled")
        return
    # Agent existence check.
    agent = runtime.registry.get(agent_id)
    if agent is None:
        await websocket.close(code=1008, reason="agent_not_found")
        return

    # Accept the handshake.
    await websocket.accept()

    # Max-connections enforcement — accept-then-immediate-close so the
    # client receives a structured close frame.
    from probos.avatars.ws_connection_manager import MaxConnectionsExceeded
    conn_manager = getattr(
        runtime, "avatar_telemetry_connection_manager", None,
    )
    sampling_state = getattr(runtime, "avatar_sampling_state", None)
    event_bus = getattr(runtime, "avatar_event_bus", None)
    if conn_manager is None or sampling_state is None or event_bus is None:
        await websocket.send_json(
            {"type": "error", "reason": "telemetry_runtime_unavailable"},
        )
        await websocket.close(code=1011, reason="runtime_unavailable")
        return

    try:
        connection_id = conn_manager.register(agent_id, websocket)
    except MaxConnectionsExceeded:
        await websocket.send_json(
            {"type": "error", "reason": "max_connections_exceeded"},
        )
        await websocket.close(code=1008, reason="max_connections_exceeded")
        return

    sampling_state.enter_popout(agent_id)
    event = event_bus.subscribe(agent_id)
    publish_task: asyncio.Task | None = None
    receive_task: asyncio.Task | None = None
    try:
        from probos.avatars.telemetry import build_telemetry_snapshot

        # Send an initial snapshot immediately on connect (UI populates fast).
        try:
            initial = await build_telemetry_snapshot(agent_id, runtime)
            await websocket.send_json(initial.to_dict())
        except Exception:
            logger.warning(
                "AD-722b: initial snapshot send failed for agent=%s",
                agent_id, exc_info=True,
            )

        async def _publish_loop() -> None:
            """Per-connection publish loop. Sleep-or-event-driven."""
            while True:
                rate_ms = sampling_state.current_rate_ms(agent_id)
                interval_s = max(0.05, float(rate_ms) / 1000.0)
                event.clear()
                # Race the timer against the event.
                wait_event = asyncio.create_task(event.wait())
                wait_timer = asyncio.create_task(asyncio.sleep(interval_s))
                try:
                    done, pending = await asyncio.wait(
                        {wait_event, wait_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (wait_event, wait_timer):
                        if not t.done():
                            t.cancel()
                # Build + send.
                snap = await build_telemetry_snapshot(agent_id, runtime)
                await websocket.send_json(snap.to_dict())

        async def _receive_loop() -> None:
            """Drain client messages so WebSocketDisconnect surfaces.

            v1 ignores client message content (no client-driven commands);
            the loop exists solely to detect disconnect. 30 s heartbeat
            ping is sent by this side when no other receive arrives.
            """
            while True:
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(), timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {"type": "ping", "timestamp": time.time()},
                    )

        publish_task = asyncio.create_task(_publish_loop())
        receive_task = asyncio.create_task(_receive_loop())

        # Whichever finishes first ends the connection.
        done, pending = await asyncio.wait(
            {publish_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Surface any non-disconnect exception from the completed task.
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "AD-722b: WS task ended for agent=%s with %s",
                    agent_id, type(exc).__name__, exc_info=exc,
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning(
            "AD-722b: WS handler error for agent=%s",
            agent_id, exc_info=True,
        )
    finally:
        # Cleanup MUST always run.
        if publish_task is not None and not publish_task.done():
            publish_task.cancel()
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        try:
            event_bus.unsubscribe(agent_id, event)
        except Exception:
            logger.debug(
                "AD-722b: unsubscribe failed for agent=%s",
                agent_id, exc_info=True,
            )
        try:
            sampling_state.exit_popout(agent_id)
        except Exception:
            logger.debug(
                "AD-722b: exit_popout failed for agent=%s",
                agent_id, exc_info=True,
            )
        try:
            conn_manager.deregister(agent_id, connection_id)
        except Exception:
            logger.debug(
                "AD-722b: deregister failed for agent=%s",
                agent_id, exc_info=True,
            )
```

`asyncio` and `time` are already imported at the top of `routers/agents.py` — verify at HEAD before editing (`time` is at `agents.py:7`; `asyncio` is NOT imported at HEAD as of 2026-05-10 per the current import block — **add** `import asyncio` to the imports block).

### D8 — UI: WS-first with poll fallback

**Modify** `ui/src/components/profile/SelfImageTab.tsx`.

**SEARCH** the existing polling effect (around lines 53-77):

```tsx
  useEffect(() => {
    if (!isActive || !agentId) return;
    let cancelled = false;
    const fetchOnce = () => {
      fetch(`/api/agent/${agentId}/avatar-telemetry`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((data) => {
          if (!cancelled) {
            setSnap(data);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };
    fetchOnce();
    const id = setInterval(fetchOnce, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [agentId, isActive]);
```

**REPLACE** with:

```tsx
  useEffect(() => {
    if (!isActive || !agentId) return;
    let cancelled = false;
    let pollIntervalId: ReturnType<typeof setInterval> | null = null;
    let ws: WebSocket | null = null;
    let wsOpened = false;
    let wsTimeoutId: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = () => {
      fetch(`/api/agent/${agentId}/avatar-telemetry`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((data) => {
          if (!cancelled) {
            setSnap(data);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };

    const startPollFallback = () => {
      // AD-722b: poll fallback — fires when WS open never arrives, or after
      // a previously-open WS closes without recovery. Idempotent.
      if (pollIntervalId !== null) return;
      fetchOnce();
      pollIntervalId = setInterval(fetchOnce, POLL_MS);
    };

    const stopPollFallback = () => {
      if (pollIntervalId !== null) {
        clearInterval(pollIntervalId);
        pollIntervalId = null;
      }
    };

    // AD-722b: open WS first; fall back to poll on error/close-before-open
    // or 5 s open-timeout.
    try {
      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProto}//${window.location.host}/api/agent/${agentId}/avatar-telemetry-stream`;
      ws = new WebSocket(wsUrl);

      wsTimeoutId = setTimeout(() => {
        if (!wsOpened && !cancelled) {
          // Open never arrived — fall back to polling.
          startPollFallback();
        }
      }, 5000);

      ws.onopen = () => {
        wsOpened = true;
        if (wsTimeoutId !== null) {
          clearTimeout(wsTimeoutId);
          wsTimeoutId = null;
        }
        // Suppress polling — WS is the live channel now.
        stopPollFallback();
      };

      ws.onmessage = (ev) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(ev.data as string);
          if (data && data.type === 'ping') return;
          if (data && data.type === 'error') {
            setError(String(data.reason ?? 'ws_error'));
            return;
          }
          setSnap(data);
          setError(null);
        } catch {
          // Ignore malformed frames.
        }
      };

      ws.onerror = () => {
        if (!wsOpened && !cancelled) {
          startPollFallback();
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        if (!wsOpened) {
          // Closed before open — fall back to poll permanently for this
          // mount. Simpler than reconnect for v1; reconnect is fwd marker.
          startPollFallback();
        } else {
          // Was open then closed — fall back to poll. (Reconnect with
          // backoff is forward marker AD-722b-6.)
          startPollFallback();
        }
      };
    } catch {
      // Constructor threw (very rare — invalid URL etc.). Fall back.
      startPollFallback();
    }

    return () => {
      cancelled = true;
      if (wsTimeoutId !== null) {
        clearTimeout(wsTimeoutId);
        wsTimeoutId = null;
      }
      if (ws !== null) {
        try { ws.close(); } catch { /* ignore */ }
        ws = null;
      }
      stopPollFallback();
    };
  }, [agentId, isActive]);
```

### D9 — Python tests (`tests/test_ad722b_websocket_push.py`, new file)

**≥ 24 tests.** Mirror the `_make_runtime` / `_endpoint_runtime` pattern from `tests/test_ad722_avatar_telemetry.py`. The new fixtures must populate `runtime.avatar_event_bus`, `runtime.avatar_telemetry_connection_manager`, and `runtime.avatar_sampling_state` with REAL instances (not MagicMocks) so tier transitions and event wakes are observable.

Required cases (the table is the spec — Builder may consolidate but MUST cover every row):

#### A. Sampling state machine — `enter_popout` / `exit_popout`

| # | Test | Asserts |
|---|---|---|
| 1 | `test_enter_popout_promotes_to_high` | Fresh state machine; `enter_popout("a")` → `current_tier("a") == TIER_HIGH`; `current_rate_ms == 250`. |
| 2 | `test_exit_popout_returns_to_low` | After enter+exit, tier returns to LOW; rate returns to `low_ms`. |
| 3 | `test_concurrent_popout_refcount` | Two `enter_popout("a")` calls → tier still HIGH after one `exit_popout("a")`; LOW after second exit. |
| 4 | `test_concurrent_dm_and_popout_both_high` | DM + popout active → tier HIGH (HIGH+HIGH = HIGH); after DM exits, tier still HIGH (popout); after popout exits, tier LOW. |
| 5 | `test_chain_under_popout_stays_high` | popout active + chain enters → tier HIGH (popout wins); chain exits → still HIGH. |
| 6 | `test_spurious_exit_popout_clamps_to_zero` | `exit_popout("a")` on fresh state → WARNING logged; `current_tier` LOW; subsequent `enter_popout` → HIGH (no poison). |
| 7 | `test_snapshot_counts_includes_popout` | `snapshot_counts("a")` returns `{"dm": 0, "chain": 0, "popout": 0}` for fresh agent. |

#### B. Event bus

| # | Test | Asserts |
|---|---|---|
| 8 | `test_event_bus_notify_sets_subscriber_event` | Subscribe agent A; `notify("A")`; `event.is_set()` True. |
| 9 | `test_event_bus_notify_other_agent_does_not_set` | Subscribe A; `notify("B")`; A's event unset. |
| 10 | `test_event_bus_multiple_subscribers_all_notified` | Two subscribers for A; `notify("A")`; both events set. |
| 11 | `test_event_bus_unsubscribe_drops_event` | Subscribe + unsubscribe; `notify` is a no-op (subscriber count 0). |
| 12 | `test_event_bus_subscriber_count_tracks` | Add/remove subscribers; `subscriber_count` matches. |

#### C. Connection manager

| # | Test | Asserts |
|---|---|---|
| 13 | `test_connection_manager_register_returns_uuid` | `register("a", ws)` returns a string of UUID-shape; `connections_for("a") == 1`. |
| 14 | `test_connection_manager_max_per_agent_enforced` | `register` called `max_per_agent + 1` times → last call raises `MaxConnectionsExceeded`. |
| 15 | `test_connection_manager_deregister_idempotent` | `deregister` for missing connection_id returns silently; no exception. |
| 16 | `test_connection_manager_invalid_max_rejected` | `AvatarTelemetryConnectionManager(max_per_agent=0)` raises `ValueError`. |

#### D. Config

| # | Test | Asserts |
|---|---|---|
| 17 | `test_avatar_telemetry_config_default_max_connections` | `AvatarTelemetryConfig().max_connections_per_agent == 4`. |
| 18 | `test_max_connections_validator_rejects_zero` | `AvatarTelemetryConfig(max_connections_per_agent=0)` → `ValidationError`. |

#### E. WebSocket endpoint (TestClient)

| # | Test | Asserts |
|---|---|---|
| 19 | `test_ws_endpoint_initial_snapshot_on_connect` | `client.websocket_connect("/api/agent/agent-007/avatar-telemetry-stream")` → first `receive_json()` returns a dict with `agent_id == "agent-007"` and the AD-722f `sampling_tier == "high"` (popout active). |
| 20 | `test_ws_endpoint_promotes_to_high_on_subscribe` | Before connect: `sampling_state.current_tier == "low"`. Inside the `with websocket_connect(...)` block: `sampling_state.current_tier == "high"`. After exit: back to `"low"`. |
| 21 | `test_ws_endpoint_publishes_on_event_bus_notify` | Connect; receive initial snapshot; from outside: `runtime.avatar_event_bus.notify("agent-007")`; receive next frame within ≤ 1 s (much faster than the 250 ms HIGH timer would force, but we don't assert sub-timer wake — we just assert another frame arrives). |
| 22 | `test_ws_endpoint_max_connections_rejected` | Open `max_per_agent` connections via `ExitStack`; the next `websocket_connect` receives an `error` frame with `reason == "max_connections_exceeded"` and a close frame. Use `WebSocketDisconnect.code == 1008`. |
| 23 | `test_ws_endpoint_503_telemetry_disabled` | `cfg.avatar_telemetry.enabled = False`; `websocket_connect` raises `WebSocketDisconnect` with `code == 1008` and `reason == "avatar_telemetry_disabled"`. |
| 24 | `test_ws_endpoint_404_unknown_agent` | Unknown agent → `WebSocketDisconnect` with `code == 1008` and `reason == "agent_not_found"`. |
| 25 | `test_ws_endpoint_503_avatars_disabled` | `cfg.avatars.enabled = False` → `WebSocketDisconnect` with `code == 1008` and `reason == "avatars_disabled"`. |
| 26 | `test_ws_endpoint_disconnect_clears_popout` | Open WS; tier HIGH. Close client side. Within 100 ms: `sampling_state.current_tier("agent-007") == "low"`. (Use `time.sleep(0.2)` after `__exit__`.) |

#### F. Trigger-site notifies (integration with AD-722f wirings)

| # | Test | Asserts |
|---|---|---|
| 27 | `test_mark_reply_emitted_notifies_event_bus` | Construct CognitiveAgent with a runtime carrying a real `AvatarEventBus`; subscribe; call `agent.mark_reply_emitted()`; subscriber's event is set. |
| 28 | `test_chain_enter_exit_notify_event_bus` | Drive the chain wiring (mock `_should_activate_chain` and `_execute_chain_with_intent_routing` → returns `None`); subscribe; verify event was set during enter (and again on exit). Use `event.is_set()` polled before each transition. |

(28 tests is the minimum — Builder may consolidate where overlap is genuine.)

#### Test infrastructure notes

- For TestClient WS tests, use the `with` context-manager form documented in FastAPI:

  ```python
  with TestClient(app) as client:
      with client.websocket_connect(f"/api/agent/{agent_id}/avatar-telemetry-stream") as ws:
          first = ws.receive_json()
          assert first["agent_id"] == agent_id
          assert first["sampling_tier"] == "high"
  ```

- The endpoint runtime fixture must construct REAL `AvatarEventBus`, `AvatarTelemetryConnectionManager(max_per_agent=cfg.avatar_telemetry.max_connections_per_agent)`, and `AvatarSamplingStateMachine(rates=cfg.avatar_telemetry.sampling_rates)` instances. MagicMock will not work for these — the WS handler exercises real method calls and asyncio primitives.

- TestClient runs the app in a thread with its own event loop; `asyncio.Event.set()` from the test thread is safe per the CPython model when the event was bound to the server's loop on first `subscribe`. For tests that need to call `notify` from outside the WS lifetime, do it via `client.app.state.runtime.avatar_event_bus.notify(agent_id)` AFTER `websocket_connect` has yielded (the subscribe happens inside the handler, before the first send).

### D10 — Vitest tests (`ui/src/__tests__/SelfImageTab.test.tsx`)

The 7 existing cases must stay green. Add 4 new cases for the WS upgrade path. In-tree mock — no new dep.

**Insert** at the top of the existing test file (after the existing imports, before `describe`):

```tsx
// AD-722b: minimal in-tree WebSocket mock — records connect URL,
// surfaces onopen/onmessage/onerror/onclose so tests can simulate the
// browser's connection lifecycle.
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
    if (this.onclose) this.onclose();
  }
  // Test helpers — drive the lifecycle from the outside.
  simulateOpen() { if (this.onopen) this.onopen(); }
  simulateMessage(data: unknown) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) });
  }
  simulateError() { if (this.onerror) this.onerror(); }
  simulateClose() { if (this.onclose) this.onclose(); }
}
```

**Add** these 4 test cases at the end of the existing `describe` block:

| # | Test | Asserts |
|---|---|---|
| 1 | `WS connects on mount and renders the first frame` | `vi.stubGlobal('WebSocket', MockWebSocket)`; mount; `MockWebSocket.instances[0].simulateOpen(); .simulateMessage(HAPPY_SNAPSHOT)`; `screen.getByTestId('panel-header-current-signals')` present. fetch was NOT called. |
| 2 | `WS open suppresses poll path` | After WS open, advance fake timers 5000 ms; fetch called 0 times. |
| 3 | `WS error before open falls back to poll` | `MockWebSocket.instances[0].simulateError()` (without `simulateOpen`); flush; fetch called 1 time (initial poll); advance 2000 ms; fetch called 2 times. |
| 4 | `WS close after open falls back to poll` | After `simulateOpen` + `simulateMessage` + `simulateClose`; advance 2000 ms; fetch called ≥ 1 time after the close. |

#### Vitest infra notes

- The 5 s WS open-timeout requires `vi.advanceTimersByTime(5000)` for the timeout-fallback case. Use `act()` to drain microtasks after each timer advance.
- Existing 7 cases run with `vi.useFakeTimers()` and never instantiate WebSocket (they don't `vi.stubGlobal('WebSocket', ...)`) — the WS branch in the new useEffect calls `new WebSocket(...)` which throws `ReferenceError` in jsdom unless stubbed. For backwards-compat with the existing tests, the implementation MUST handle the `WebSocket-undefined` case gracefully — the `try/catch` block around `new WebSocket(...)` in D8 already does this (constructor throw → falls back to poll). Verify the existing 7 cases still pass; if any starts failing because the WS constructor throw triggers an extra fetch path that double-counts polls, the fix is to set up an `afterEach` that nulls the global WebSocket reference — DO NOT alter the existing test bodies.

### D11 — Tracking comments

In `src/probos/avatars/telemetry.py` module docstring, append a one-line note:

```python
# AD-722b: WS push channel consumes this snapshot via to_dict() — do NOT
# add fields without updating the AD-722b WS frame contract test.
```

(Exact insertion: above the `from __future__ import annotations` line, in the module docstring's NOTE block.)

---

## 8. Tests required

- **Python:** ≥ 24 boundary tests in `tests/test_ad722b_websocket_push.py`. The 28-row table in D9 is the minimum spec; consolidation OK, dropping rows is NOT.
- **Vitest:** ≥ 4 new cases in `ui/src/__tests__/SelfImageTab.test.tsx` (existing 7 stay green for a total ≥ 11).
- **Existing tests must stay green** — `test_ad722_avatar_telemetry.py` (~22 cases) and `test_ad722f_adaptive_sampling.py` (17 cases) should be unaffected.

---

## 9. Hard-stop conditions

The Builder MUST stop and surface to architect (do not improvise) when:

1. **Read-only contract violated.** Any deliverable mutates `TrustNetwork`, Hebbian routing, `RecordsStore`, `crew_profiles.data`, or any persistent state. AD-722b is a transport-only change.
2. **GET endpoint modified.** The existing `GET /{agent_id}/avatar-telemetry` is the polling fallback target — stay untouched.
3. **App-level `_ws_clients` list accessed.** That list is the AD-254 broadcast channel — distinct from per-agent telemetry. AD-722b's WS state lives in `AvatarTelemetryConnectionManager` only.
4. **Phantom API discovered.** Any concrete claim in §2 fails to verify against the actual codebase at the Builder's commit time. Stop, surface, request a prompt revision.
5. **HXI-fragile file touched.** `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx` MUST stay untouched. Hard stop on any diff.
6. **Existing AD-722 / AD-722f / AD-722-1 tests break.** The two new fields (`sampling_rate_ms` + `sampling_tier`) are unchanged; the modulation manifest is unchanged; the AD-722f state-machine surface is *additive* (`enter_popout`/`exit_popout` are new methods, the WR phantom-API guard test still passes, the existing four trigger methods are unmodified). Any breakage = Builder's WS endpoint or wiring is touching shared state it shouldn't.
7. **New top-level dep.** `pyproject.toml [project.dependencies]` or `ui/package.json` `"dependencies"` / `"devDependencies"` change in any way. `mock-socket` is rejected — the in-tree `MockWebSocket` class is the test infra.
8. **Multiple `mark_reply_emitted` call sites.** AD-722's invariant: exactly one call site in production source. The new `bus.notify(self.id)` line is INSIDE `mark_reply_emitted` itself, not a sibling call. If the chat handler gains a second site, the call moves into a private helper (mirrors AD-722's D6 approach).

**HARD RULE — UI build gate:** Run `cd ui && npm run build` AFTER writing TSX and BEFORE pushing. Type errors in the new branch in `SelfImageTab.tsx` MUST be caught locally — the Vitest gate alone does not cover full TypeScript compilation against the production tsconfig.

---

## 10. Wave-specific reminders

1. **No new auth.** WS endpoint mirrors GET endpoint feature gates exactly. Forward marker AD-722b-1 covers the federation-paired auth work.
2. **WS subscribe IS a popout.** The user-facing language ("popout open") and the API method (`enter_popout`) are deliberately the same. Forward-marker `enter_subscriber` from sampling_state.py docstring is replaced by `enter_popout` in this AD; the docstring update in D3 is the audit trail.
3. **Trigger surfaces are co-located.** Every `enter_dm`/`exit_dm`/`enter_chain`/`exit_chain` call sits next to a `bus.notify(...)` call in the same conditional block. The AD-722f wiring locations are the AD-722b notify locations — no new wiring sites.
4. **State-change detection is coarse, not fine-grained.** Trigger surfaces ARE the state-change surfaces in v1. Forward marker AD-722b-3 is the fine-grained snapshot-diff path.
5. **Connection cleanup is `finally`-bracketed.** Every `register/enter_popout/subscribe` is matched by `deregister/exit_popout/unsubscribe` inside the WS handler's `finally`. Spurious-exit clamps protect against task-cancel races that could double-fire.
6. **WR path remains unwired.** Per AD-722 addendum (h). No `enter_wr`/`exit_wr` surface, no notify on WR posts. The existing AD-722f phantom-API guard test continues to pass without modification.
7. **Initial snapshot on connect.** UI must populate fast — the WS handler sends a snapshot before entering the publish loop. Skipping this would push the first paint to the first publish cycle (up to `high_ms` = 250 ms — acceptable, but fast initial paint is free).
8. **No reconnect with backoff in v1.** WS close → poll fallback. Reconnect-with-backoff is forward-marker AD-722b-6 (file as GH issue post-build). The user-prompt is silent on reconnect; cluster plan §4 listed "lifecycle: connection cleanup on close" only.
9. **Verify-first.** Before any concrete file/line/method citation in the implementation, Builder greps HEAD and pastes the result in the commit message body — especially every line number in §2.

---

## 11. Tracking

After AD-722b ships:

1. **`PROGRESS.md`** — flip the AD-722b row to ✅ in Wave 142 section. One-line outcome: *"WS push channel for avatar telemetry — `WS /api/agent/{id}/avatar-telemetry-stream`; popout-trigger flips sampling tier to HIGH; UI WS-first with 5 s open-timeout poll fallback. Read-only snapshot contract preserved."*
2. **`docs/development/roadmap.md`** — close Wave 142 row. File / link the forward markers below.
3. **`DECISIONS.md` + `decisions-era-5-unification.md`** — append AD-722b entry under the AD-722 addendum block. Document: (a) WS endpoint path, (b) full-snapshot frame contract (no delta encoding in v1), (c) feature-gate-only auth model + AD-722b-1 forward marker, (d) popout-tier addition to sampling state machine, (e) trigger-surface notify model (no fine-grained diff), (f) max-connections-per-agent default 4, (g) UI WS-first with 5 s open-timeout poll fallback.
4. **GH issues** — close [#568](https://github.com/seangalliher/ProbOS/issues/568) with a summary comment citing the commit SHA. File the AD-722b-1, -2, -3, -4, -5, -6 forward markers as new issues (Captain auth required — Builder lacks token scope; Builder lists the marker text in the build report and Captain files via `gh` after).

### Forward markers (Builder lists; Captain files post-build)

| Marker | One-line description |
|---|---|
| **AD-722b-1** | Crew-scope auth on avatar-telemetry surfaces (HTTP + WS). Pairs with federation. |
| **AD-722b-2** | Agent-side WS push — populate `_last_self_avatar_snap` cache via subscriber-side messages. |
| **AD-722b-3** | Fine-grained state-diff at snapshot-build time (working_state / mouth_active / tier3 transitions surfaced sub-timer). |
| **AD-722b-4** | Multi-agent telemetry stream (one connection, fan-out by agent_id). |
| **AD-722b-5** | Federation cross-mesh telemetry push (depends on AD-722b-1). |
| **AD-722b-6** | WS reconnect with capped backoff after `onclose` (replaces v1's poll fallback). |

---

## 12. Acceptance criteria

1. ✅ One commit. Reviewer fails any split — AD-722b is a single atomic feature.
2. ✅ `pytest tests/ -q -n 8 --dist=loadfile` green at the commit. Test count delta: ≥ +24.
3. ✅ `cd ui && npx vitest run` green at the commit. Test count delta: ≥ +4 (existing 7 SelfImageTab cases stay green).
4. ✅ `cd ui && npm run build` green at the commit (HARD RULE — see §9).
5. ✅ Existing AD-722 / AD-722f / AD-722-1 tests stay green. Reviewer fails any modification of those test bodies.
6. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-722b-websocket-push.md` clean.
7. ✅ `pyproject.toml [project.dependencies]` AND `ui/package.json` `"dependencies"` + `"devDependencies"` are bit-for-bit identical pre/post commit.
8. ✅ Manual smoke: open the HXI; click Counselor (Ezri); switch to Self-image tab; observe Network panel — single WebSocket frame `/api/agent/agent-007/avatar-telemetry-stream` open, NO repeating polls. Send Ezri a DM; the SelfImageTab updates within ≤ 250 ms (HIGH tier active because of the popout). Close the tab; the `polling_interval_ms` background poll does not resume from this tab.
9. ✅ Manual smoke: kill the backend process; the SelfImageTab's WS closes; within ≤ 5 s the poll fallback kicks in (Network panel shows 2 s polls resuming).
10. ✅ **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
