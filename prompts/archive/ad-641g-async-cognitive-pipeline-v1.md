# AD-641g v1 — Asynchronous Cognitive Pipeline via NATS (Foundation)

**Issue:** #403  
**Type:** Architecture Decision (sub-AD of AD-641)  
**Depends on:** AD-637 (NATS Event Bus — COMPLETE), AD-632 (Chain Architecture — COMPLETE)  
**Forward deps unblocked:** AD-644, AD-645 Phase 5, AD-646, AD-647, AD-651  
**Wave:** 105

## Scope (Foundation Only)

Lay the **transport foundation** for the async cognitive pipeline. Ship subject schema + chain-step lifecycle publishing + opt-in config flag. Do **not** add a JetStream consumer side, do **not** rewire `SubTaskExecutor` to await NATS messages, do **not** add deeper QUERY browsing. Synchronous chain remains the live path; NATS publishes are observability/replayable trail only.

**Why this cut:** AD-645 Phase 5 (composition brief streaming), AD-647 (process chains), and AD-644 (situation awareness) all reference `chain.{agent_id}.{step}.complete` subjects as a forward dependency. Shipping the publish-side subject contract first lets those ADs land their consumer logic without re-litigating the schema. The decoupled-execution flip (Phase 3 in the design doc) becomes its own AD-641g-1 once a real consumer exists.

## What this AD does NOT change (out of scope)

- No replacement of `SubTaskExecutor.execute()`; it stays synchronous
- No QUERY-side deepening (no channel browsing, no document reading) — that's AD-641g Phase 3
- No department-level shared queues — that's AD-641g Phase 4
- No JetStream consumer logic (subscribers, ack/nak loops, redelivery)
- No `_gather_context()` rewrite
- No new EventType — chain step events are NATS-only, not on the system event bus
- No Scout/Bills/SOPs migration

## Deliverables

### D1. Subject schema module — `src/probos/cognitive/chain_subjects.py` (NEW)

Single small module exporting subject builders:

```python
"""AD-641g: NATS subject schema for cognitive chain step lifecycle."""
from __future__ import annotations
from probos.cognitive.sub_task import SubTaskType

# Stream name (provisioned at startup when feature flag on)
CHAIN_STREAM = "COGNITIVE_CHAIN"

# Subject template: chain.{agent_id}.{step}.{phase}
# phase ∈ {"start", "complete", "error"}

def chain_subject(agent_id: str, step: SubTaskType | str, phase: str = "complete") -> str:
    step_str = step.value if isinstance(step, SubTaskType) else str(step)
    # Sanitize agent_id same way nats_bus does (token chars only)
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in agent_id)
    return f"chain.{safe}.{step_str}.{phase}"

def chain_wildcard(agent_id: str = "*", step: str = "*") -> str:
    """Wildcard subject for subscribers — agent_id='*' or step='*'."""
    return f"chain.{agent_id}.{step}.>"
```

Acceptance: pure function, no imports beyond `sub_task.SubTaskType`.

### D2. ChainNATSBridge — `src/probos/cognitive/chain_nats_bridge.py` (NEW)

Thin bridge owned by the runtime that publishes chain step lifecycle to NATS JetStream. Constructor injection only — no globals, no late binds.

```python
class ChainNATSBridge:
    """AD-641g: Publishes cognitive chain step lifecycle to NATS JetStream.

    Foundation-only: publish-side. No consumer logic.
    """

    def __init__(self, *, nats_bus: "NATSBus | None", config: Any) -> None:
        self._nats_bus = nats_bus
        self._config = config  # CognitiveChainConfig — has .nats_publish_enabled
        self._publish_tasks: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(
            self._config
            and getattr(self._config, "nats_publish_enabled", False)
            and self._nats_bus
            and self._nats_bus.connected
        )

    async def ensure_stream(self) -> None:
        """Create COGNITIVE_CHAIN JetStream stream if missing. Idempotent.
        Called once during startup finalize. No-op if disabled or NATS down.
        """
        # Use existing nats_bus.ensure_stream API; subjects=["chain.>"]
        ...

    def publish_step_complete(
        self,
        *,
        agent_id: str,
        step: SubTaskType,
        result: SubTaskResult,
        intent_id: str = "",
    ) -> None:
        """Fire-and-forget publish. Stores task ref. Catches all exceptions."""
        if not self.enabled:
            return
        subject = chain_subject(agent_id, step, "complete")
        payload = {
            "agent_id": agent_id,
            "step": step.value,
            "name": result.name,
            "intent_id": intent_id,
            "ok": result.ok,
            "duration_ms": result.duration_ms,
            "result": result.result,  # handler-specific dict
            "ts": time.time(),
        }
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._safe_publish(subject, payload))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    def publish_step_error(self, *, agent_id, step, error, intent_id="") -> None:
        # symmetric to step_complete
        ...

    async def _safe_publish(self, subject: str, payload: dict) -> None:
        try:
            await self._nats_bus.js_publish(subject, payload)
        except Exception:
            logger.warning("AD-641g: chain publish to %s failed; dropping", subject, exc_info=True)
```

**Engineering principle compliance:**
- Constructor injection (D); no `getattr/hasattr` for wiring
- Public `enabled` property; no private-attr access from callers
- Fire-and-forget publishes hold task ref + done callback (async hygiene)
- Bare `except Exception` is allowed here only because the exception is logged with context and the system degrades cleanly (publish failure must never break the synchronous chain — log-and-degrade tier)
- Full type annotations on all public methods

### D3. Config — extend existing `CognitiveChainConfig`

In `src/probos/config.py` (or wherever `CognitiveChainConfig` lives — Builder must verify path), add:

```python
nats_publish_enabled: bool = False  # AD-641g: opt-in
nats_payload_max_bytes: int = 16384  # 16KB cap on result dict
```

**Default False** (per memory note: "Default-True on transitional flags is breaking-change-on-first-commit anti-pattern").

In `ChainNATSBridge.publish_step_complete`, before `js_publish`, if `len(json.dumps(payload)) > nats_payload_max_bytes`, replace `result` field with `{"truncated": True, "size": <n>}` and log warning.

### D4. SubTaskExecutor wiring — minimal

In `src/probos/cognitive/sub_task.py`, extend `SubTaskExecutor.__init__` to accept an optional bridge:

```python
def __init__(
    self,
    *,
    config: Any = None,
    emit_event_fn: Callable | None = None,
    nats_bridge: "ChainNATSBridge | None" = None,  # AD-641g
) -> None:
    ...
    self._nats_bridge = nats_bridge
```

In the per-step result handling inside `_execute_chain` (after a step completes successfully OR fails), call:

```python
if self._nats_bridge is not None:
    if result.ok:
        self._nats_bridge.publish_step_complete(
            agent_id=agent_id, step=step.sub_task_type,
            result=result, intent_id=intent_id,
        )
    else:
        self._nats_bridge.publish_step_error(
            agent_id=agent_id, step=step.sub_task_type,
            error=result.error or "", intent_id=intent_id,
        )
```

Keep this an additive call — no behavioral change to the synchronous chain. If bridge is None or `enabled` is False, zero overhead.

### D5. Runtime startup wiring

In the cognitive startup module (Builder must locate — likely `src/probos/startup/cognitive.py` or similar; check where `SubTaskExecutor` is instantiated for the runtime), construct one `ChainNATSBridge` after `nats_bus` exists, pass it to `SubTaskExecutor`. Call `await bridge.ensure_stream()` once during finalize phase (alongside the existing `_setup_nats_event_subscriptions`).

Pattern reference: `runtime.py` `_setup_nats_event_subscriptions()` and the SYSTEM_EVENTS stream provisioning.

### D6. Tests — `tests/test_ad641g_chain_nats_bridge.py` (NEW)

Use existing `MockNATSBus` from `probos.mesh.nats_bus`. Minimum 8 tests:

1. `test_chain_subject_format` — subject builder produces `chain.<id>.analyze.complete`
2. `test_chain_subject_sanitizes_agent_id` — colons/spaces become underscore
3. `test_bridge_disabled_when_flag_false` — `enabled` returns False; publish is no-op
4. `test_bridge_disabled_when_nats_disconnected` — `enabled` False even with flag on
5. `test_publish_step_complete_publishes_to_correct_subject` — MockNATSBus records publish
6. `test_publish_step_error_publishes_error_payload`
7. `test_payload_oversize_truncates_result` — 64KB result dict → truncated marker
8. `test_publish_failure_does_not_raise` — js_publish raises → caller continues
9. (Bonus) `test_executor_publishes_per_step_when_bridge_attached` — integration with `SubTaskExecutor`, mock chain with 2 steps

**Test isolation:** each test creates own `MockNATSBus`, own bridge. No class-level state. No shared fixtures across tests.

## Verification

- `pytest tests/test_ad641g_chain_nats_bridge.py -v` — all green
- `pytest tests/ -n 0 --timeout 90` — total test count increases by 8-9, no regressions
- Manually verify: `grep -r "chain\." src/probos | grep -v test_` shows new subjects only inside `chain_subjects.py` and `chain_nats_bridge.py` (no scattered string literals)
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Hard constraints (do NOT do)

- Do NOT add subscribers/consumers — publish-side only
- Do NOT touch `_gather_context()` or proactive loop
- Do NOT change `SubTaskResult` shape (additive only on payload — do not modify dataclass)
- Do NOT default `nats_publish_enabled` to True
- Do NOT register a system EventType for chain steps (NATS-only stream)
- Do NOT add HXI/UI surface
- Do NOT modify any existing test
- Do NOT introduce a new dependency package

## Forward markers (next ADs that consume this)

- **AD-641g-1** — flip executor to optionally `await` ANALYZE results from NATS (Phase 3 in design doc)
- **AD-645 Phase 5** — composition brief streamed on `chain.{agent}.compose.complete`
- **AD-647 Phase 3** — process chain billet_instructions via NATS envelope
- **AD-644 Phase 4** — situation awareness consumes `chain.{agent}.query.complete` for cross-agent observation
