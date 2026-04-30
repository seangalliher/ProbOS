# Review: AD-438 — Ontology-Based Task Routing

**Verdict:** ⚠️ Conditional
**Re-review (2026-04-29 second pass): ✅ Approved.** Required event-type addition is now in the prompt.

**Headline:** Missing `EventType.TASK_ROUTED` in the enum.

## Required (must fix before building)

1. **`EventType.TASK_ROUTED` does not exist.** Grep confirms no `TASK_ROUTED` in [src/probos/events.py](src/probos/events.py). Section 1 wires `self._emit_fn(EventType.TASK_ROUTED, ...)`; the enum value must be added before any emission code lands. Insert near `TOOL_PERMISSION_DENIED` (around line 165) per existing convention.

## Recommended

1. The TaskRouter module's defensive try/except around ontology lookup should log with `exc_info=True` for any `WARNING`+ lines (already correct for debug; check error tier).

## Nits

- `RouteDecision.agent_ids` uses `field(default_factory=list)` — correct, no mutable-default trap.
- Test 10 (`EventType.TASK_ROUTED.exists`) — verify reference compiles after enum addition.

## Verified

- `IntentBus.broadcast()` exists at [src/probos/mesh/intent.py:369](src/probos/mesh/intent.py#L369) with the asserted signature.
- `OntologyService.get_posts()` and `get_all_assignments()` are public at [src/probos/ontology/service.py:117](src/probos/ontology/service.py#L117).
- `Dispatcher` exists at [src/probos/activation/dispatcher.py:40](src/probos/activation/dispatcher.py#L40).
- `Depends(get_runtime)` pattern in [src/probos/routers/system.py](src/probos/routers/system.py) matches.
- No conflicts with existing routing code.

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

| Prior Required | Status | Evidence |
|---|---|---|
| `EventType.TASK_ROUTED` missing | ✅ Fixed | Section 2 SEARCH/REPLACE inserts after `KNOWLEDGE_TIER_LOADED` at [events.py:170](src/probos/events.py#L170). |

No new findings. Ship it.
