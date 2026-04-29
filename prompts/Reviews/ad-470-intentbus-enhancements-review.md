# Review: AD-470 — IntentBus Enhancements

**Verdict:** ⚠️ Conditional
**Headline:** Missing `defaultdict` import; timing-instrumentation insertion needs precise placement.

## Required

1. **Missing import.** [src/probos/mesh/intent.py:1-12](src/probos/mesh/intent.py#L1) does not import `defaultdict`. Add `from collections import defaultdict` near line 13 (after current imports, before `from probos.types`).
2. **Verify `broadcast()` timing insertion point.** Prompt says insert `_broadcast_start = time.monotonic()` "after target_agent_id check, around line 389" — confirm the line content matches `timeout = timeout if timeout is not None else intent.ttl_seconds`. Timing must start BEFORE async work in the broadcast path.
3. **`send()` timing left as "add similarly."** Spell out the same context-manager wrapper for `send()` and add a test asserting metrics update after a `send()` call.

## Recommended

1. Cap of 200 samples per intent type is hardcoded — consider a config knob (`max_durations_per_type`).
2. `get_subscriber_map()` infers fallback agents by exclusion. Add a test with an agent subscribed to multiple intent types to confirm correct multi-bucket placement vs. single fallback.
3. Metrics are point-in-time only; document that `/api/intent-metrics` must be scraped externally for trends.

## Nits

- `type_durations_ms` is a `defaultdict(list)` but reassigned via slicing (`durations[-200:]`). After reassignment, the key holds a plain list, breaking defaultdict semantics on further appends. Use `self.type_durations_ms[intent_type] = durations[-200:]` only inside an explicit branch, OR switch to `deque(maxlen=200)`.

## Verified

- `IntentBus` class at [mesh/intent.py:23](src/probos/mesh/intent.py#L23).
- `async def broadcast` at [mesh/intent.py:369](src/probos/mesh/intent.py#L369).
- `async def send` at [mesh/intent.py:309](src/probos/mesh/intent.py#L309).
- `_subscribers` and `_intent_index` at [mesh/intent.py:33-34](src/probos/mesh/intent.py#L33).
- `record_broadcast()` at [mesh/intent.py:565](src/probos/mesh/intent.py#L565); `subscriber_count` property at [intent.py:306](src/probos/mesh/intent.py#L306).
- `runtime.intent_bus` is public (no leading underscore) at [runtime.py:299](src/probos/runtime.py#L299).
