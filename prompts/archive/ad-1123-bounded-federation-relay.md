# AD-1123 — Bounded federation one-way relay

**Status:** **RE-APPROVED / CORRECTION EXECUTABLE** — Architect BLOCKED review resolved against the live uncommitted AD-1123 implementation on exact `main` HEAD `8eeaf406a1121a131c73a5cb6e361c0e6ce3e1a5`
**Prerequisite issue:** new GitHub issue proposed in ignored `logs/ad1123_issue_body.md`; do not mutate GitHub during architecture
**Unblocks:** #659 / AD-722b-5a telemetry streaming hop, but does not implement or close it
**Dependencies:** AD-637e NATS-first federation; AD-722b-5 local `FederationTelemetryRelay`; AD-730-4 directed federation correlation/security hardening
**Estimated tests:** the live new pytest module collects **75 tests** before this correction; add the exact correction cases below and report the final collection count; zero Vitest
**Numbering:** highest landed top-level is **AD-1122**; **AD-1123** is the next unused top-level; highest landed BF is BF-672
**Scope:** OSS federation control plane only; no new dependency, config field, EventType, runtime object, UI, database, or wire transport
**License disposition:** original Apache-2.0 repository code only; no external code, model, asset, package, or license change

---

## BLOCKED implementation review correction packet (binding, 2026-07-17)

This is the highest-precedence continuation contract for the live uncommitted AD-1123 diff. Preserve every prior closed-topic, exact-envelope, one-target, bounded-work, no-response, no-loop, no-learning, cancellation, privacy, transport-parity, AST, gate, and scope requirement. C1–C3 below supersede only conflicting wording about reuse of the bridge-private node predicate, callable-introspection failure handling, and startup-success coverage. Do not restart, discard, restore, stash, or rewrite the accepted implementation.

### Exact continuation state and hashes

HEAD remains `8eeaf406a1121a131c73a5cb6e361c0e6ce3e1a5`. There are no staged paths. Before Builder correction edits, the visible implementation state is exactly:

```text
 M src/probos/federation/bridge.py
 M src/probos/runtime.py
 M src/probos/startup/fleet_organization.py
?? prompts/ad-1123-bounded-federation-relay-execution.md
?? prompts/ad-1123-bounded-federation-relay.md
?? src/probos/federation/relay.py
?? tests/test_ad1123_bounded_federation_relay.py
```

The ignored `logs/ad1123_issue_body.md` remains unstaged. The live pre-correction SHA-256 values are:

| File | SHA-256 |
|---|---|
| `src/probos/federation/relay.py` | `33fa02e30c7541f95bc485e0be9d82ed817c7ecef225acd56d73907c04e97501` |
| `src/probos/federation/bridge.py` | `d9b134846d73604d734fa2f07266e152406c142b917fa0495cd8aaa57af8b2ef` |
| `src/probos/startup/fleet_organization.py` | `7b9e17dd24bf020ef5c2797d3601c97fac62996c5c5fa53a21a1c2a6494abbc8` |
| `src/probos/runtime.py` | `97b3a45c3841cbd8957ad0d7549233eee702e97bbbe138c45f57483ac011347b` |
| `tests/test_ad1123_bounded_federation_relay.py` | `0509cadb59628c5fcc6ecfbc72e125622c763f0ea003e9d72ae3d1ad46133c66` |

The active Builder correction allowlist is exactly three paths:

1. `src/probos/federation/relay.py`
2. `src/probos/federation/bridge.py`
3. `tests/test_ad1123_bounded_federation_relay.py`

The current `fleet_organization.py` and `runtime.py` wiring is accepted and frozen at the hashes above during correction. The two active prompts are Architect-owned and must remain unchanged by the Builder until conditional archive. The original eventual implementation/closeout allowlist remains exact and is not broadened.

### C1 — One relay-local safe-node predicate owns every relay identity boundary

Add one public, pure, fully annotated helper in `src/probos/federation/relay.py`:

```python
def is_safe_relay_node_id(value: Any) -> bool:
```

It requires `type(value) is str` and a full match of exactly `^[A-Za-z0-9_-]{1,128}$`. Keep the compiled regex in `relay.py`; do not import the bridge-private `_DIRECTED_NODE_ID_RE`, duplicate a second relay regex, coerce values, or accept `str` subclasses.

Use this same helper at all relay identity boundaries:

1. `finalize_relay_wire_payload()` rejects unless both server-supplied `source_node` and the exact five-key payload's `target_node_id` pass it. Perform both checks before nested payload detachment or generic JSON serialization.
2. `FederationBridge.relay_one_way()` rejects an unsafe local `self._node_id` before configured-peer lookup, connected-peer lookup, topic lookup, payload traversal, validator invocation, `FederationMessage` construction, or transport work. The caller-selected target uses the same relay helper.
3. `_handle_relay_one_way()` rejects an unsafe local `self._node_id` immediately after relay admission/exact-message-type checks and before configured-source work, payload traversal, target equality, topic lookup, monotonic clock access, or rate-state lookup/allocation. After extracting the exact target field, require the same helper before comparing it with `self._node_id`. Require the source to pass the same helper before configured-peer admission; configured membership remains independently required.

This is local identity validation, not cryptographic authentication. Do not add parse-time config validation, change the directed-DM predicate, or couple the relay module back to the bridge.

Tests must cover `""`, a dot-containing ID, a space-containing ID, 129 characters, and a `str` subclass as rejection cases, plus exactly 128 characters as acceptance. Cover both source and target through (a) the pure predicate/finalizer and (b) outbound and inbound bridge behavior. Invalid outbound local source must perform zero finalizer/validator/transport work. Invalid inbound local target must perform zero finalizer/validator/sink/rate work even when the wire target equals that malformed local value. A bridge round trip with exact-128 source and target must succeed.

### C2 — Complete topic-callable introspection containment and conservative classification

`build_relay_topic_registry()` must normalize **every ordinary `Exception`** raised anywhere in callable contract inspection to exactly `ValueError("relay_topics_invalid")`. The containment boundary covers, for validator and sink independently:

- `callable(value)`;
- `inspect.iscoroutinefunction(value)`;
- `inspect.signature(value)` and all parameter materialization/inspection;
- hostile `__call__`, `__signature__`, `__wrapped__`, `__name__`, partial metadata, decorator metadata, or other metadata reached by those operations.

Catch `Exception`, not `BaseException`, around the complete inspection sequence. Raise a fresh exact built-in `ValueError` whose `args == ("relay_topics_invalid",)` and do not expose the hostile exception text. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and any custom `BaseException` must propagate unchanged. Do not invoke either callable to discover whether its result is awaitable.

The classification policy is deliberately conservative and must be explicit in code tests:

1. A `functools.partial` is accepted only when stdlib introspection classifies the supplied partial itself correctly and its **effective** signature has exactly the required positional arity. Binding away a required argument or leaving an extra one rejects.
2. A synchronous callable object may be a validator when `inspect.iscoroutinefunction(object)` is false and `inspect.signature(object)` exposes exactly one positional parameter. Do not promote a callable object to an async sink merely because its `__call__` method is `async def`; if the supplied object itself is not classified as a coroutine function, reject it.
3. A decorated async sink is accepted only when the supplied wrapper itself remains an `async def` coroutine function and exposes exactly two positional parameters. A synchronous wrapper that merely returns a coroutine is rejected even when it uses `functools.wraps`.
4. Ambiguous, opaque, hostile, or uninspectable callables reject closed with the exact `ValueError`; no probe call, fallback signature, `getattr(__call__)`, or truthy approximation is allowed.

Tests must force ordinary exceptions independently from `callable`, `inspect.signature`, and `inspect.iscoroutinefunction`, plus hostile metadata reached through a real callable object, and assert the exact normalized `ValueError` class/args. Force `BaseException` at the same inspection boundary and assert identity-preserving propagation. Add accepted/rejected partial, synchronous callable-object, async-callable-object, async-decorated-wrapper, and sync-wrapper-returning-coroutine cases.

Because Python's built-in `callable()` is normally non-throwing for ordinary objects, the independent `callable`-failure case may monkeypatch the module's built-in lookup in the focused registry test. The `inspect.signature`/`inspect.iscoroutinefunction` cases must separately exercise the real imported inspection seams, and at least one hostile metadata case must flow through an unpatched real callable object. Production must contain the complete sequence regardless.

### C3 — Failed bridge startup remains relay-closed and is restartable

Add one regression at the real current `FederationBridge.start()` seam. Prefer a narrow transport whose `_inbound_handler` assignment fails once with an ordinary exception, then succeeds; equivalently, a monkeypatched `asyncio.create_task()` may fail before task creation if the test closes the unawaited gossip coroutine without warning. Do not use `MagicMock`. Pre-seed one relay-rate bucket before the first start call. Assert:

1. the startup exception propagates;
2. `_relay_admission_open is False`;
3. `_relay_rate == {}`;
4. `_gossip_task is None` and no gossip task was created;
5. `relay_one_way()` returns `False` with zero validator/finalizer/send work while startup remains failed;
6. after enabling the same transport assignment and calling `start()` again, relay admission opens, one gossip task exists, and a valid outbound relay succeeds; then `stop()` performs normal cleanup.

This freezes the current fail-closed ordering: close admission and clear rate state before inbound-handler wiring; open admission only after wiring and gossip task creation succeed. Do not swallow the startup exception, add rollback tasks, add a task registry, alter transport lifecycle, or redesign `start()`. If the current implementation already satisfies this regression, add only the test.

### Correction red-first and unchanged gates

The original pre-production headline red remains a required report item. Do not fabricate it by reverting the live worktree. Preserve the exact original command/failure in the final Builder handback; if the output was not retained, report that truthfully and hard-stop before closeout rather than inventing evidence.

Write all C1–C3 tests before correction code and run the named correction tests against the current live implementation. Record the expected red failures for missing finalizer/local-identity admission and incomplete introspection containment; the startup regression may already pass because it freezes current ordering. Do not weaken tests after red. All four existing Windows gates, every pinned bridge/transport AST hash, warning baseline, and the exact eventual file allowlist remain unchanged.

---

## Decision / verdict

Build a **generic but closed** best-effort one-way relay primitive.

A telemetry-only wire type would duplicate the transport and security mechanics for every later bounded sensor stream. An open generic event/intent relay would be unsafe: it would let a configured peer choose runtime intents, `EventType` values, callbacks, or arbitrary local dispatch surfaces. AD-1123 therefore generalizes only the safe transport mechanics while keeping semantic authority local:

1. one fixed `FederationMessage.type == "relay_one_way"`;
2. one exact five-key payload schema;
3. a receiver-local constructor registry maps a small literal topic to one validator and one sink;
4. the sender can emit only a topic registered on its own bridge;
5. the receiver invokes only the exact registered sink—never `IntentBus`, event dispatch, a runtime method by name, or a wildcard callback;
6. the first registered topic in AD-1123 is a **test contract only**. AD-722b-5a will later register `avatar.telemetry.v1` and wire the existing relay callback.

This is a datagram-style prerequisite, not a stream session: no handshake, subscription negotiation, response, ack, retry, correlation map, durable queue, replay, ordering promise, trust update, Hebbian update, or background loop. A fixed receiver-side admission cap drops excess configured-source traffic before payload traversal or sink work.

---

## Problem grounded at HEAD

- AD-722b-5 shipped only local subscription/rate-limit/emit plumbing. `FederationTelemetryRelay.set_emit_callback()` expects an async callback shaped `(peer_id, agent_id, frame_type, payload)`.
- `FederationBridge` now has robust directed DM request/response, but no safe one-way message surface. Reusing `forward_intent()` would inject telemetry into the local mesh and trigger an `intent_response`; reusing `forward_direct_message()` would require an agent target and correlation wait. Both are the wrong protocol.
- All transports already expose `send_to_peer(peer_node_id, FederationMessage)`. No transport API change is needed.
- NATS and ZeroMQ already serialize the same five `FederationMessage` fields. The new wire type can travel through the existing per-node subject/socket and inbound handler.
- #659 says the telemetry hop advances when a federation relay primitive exists. AD-1123 creates that prerequisite only; the local telemetry producer/sink wiring remains a child AD.

### Why not add a second transport callback

Each transport currently owns one inbound callback, installed by `FederationBridge.start()`. Adding a parallel relay callback to all transports would create a second dispatch owner and broaden the transport protocol. The bridge already owns message-type dispatch and configured-peer policy. AD-1123 adds one bridge branch and leaves transport APIs/serializers unchanged.

### Why not share AD-730-4's detacher verbatim

`_detach_directed_result_value()` is private and enforces response-specific policy, including result error semantics and image/data-URL rejection. Importing or renaming it would alter AD-730-4's security surface. AD-1123 adds one small federation-private bounded-JSON module with a purpose-neutral exact-built-in detacher. The directed helper remains byte/executable-AST identical. This is intentional, scoped duplication of the traversal *pattern*, not a coupling between independent wire contracts.

---

## Public protocol and APIs

### Topic contract

Create in `src/probos/federation/relay.py`:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

RelayPayloadValidator = Callable[[dict[str, Any]], bool]
RelaySink = Callable[[str, dict[str, Any]], Awaitable[None]]

@dataclass(frozen=True)
class FederationRelayTopic:
    name: str
    validate_payload: RelayPayloadValidator
    sink: RelaySink
```

`FederationRelayTopic` is bridge-construction policy. It never crosses the wire.

### Bridge constructor

Append one optional keyword to `FederationBridge.__init__()`:

```python
relay_topics: tuple[FederationRelayTopic, ...] = (),
```

Direct constructions remain compatible. Store an immutable name-to-contract copy after validating it synchronously:

- exact built-in topic name matching `^[a-z][a-z0-9_.-]{0,63}$`;
- duplicate names are a constructor `ValueError`;
- `relay_topics` must be an exact built-in tuple of at most 16 exact `FederationRelayTopic` instances; reject tuple/list subclasses or other iterables before iteration;
- validator and sink must be callable;
- validator signature must contain exactly one positional parameter and no variadic/extra parameters; sink signature exactly two positional parameters and no variadic/extra parameters;
- validator must be synchronous (`inspect.iscoroutinefunction` is false); sink must be asynchronous (`inspect.iscoroutinefunction` is true);
- the complete `callable`/`inspect.iscoroutinefunction`/`inspect.signature` sequence is fail-closed per C2: ordinary inspection exceptions normalize to exact `ValueError("relay_topics_invalid")`, while `BaseException` propagates;
- partials, callable objects, and decorated async wrappers follow C2's conservative no-invocation policy—only the supplied callable's stdlib coroutine classification and effective exact signature count;
- maximum 16 registered topics;
- no runtime back-reference, no late-bound setter, no private mutation from startup.

Store the registry behind `types.MappingProxyType`. It is fixed for one bridge lifetime. AD-1123 does not add dynamic callback registration.

Every topic validator is local trusted policy and must validate an exact semantic schema (fixed keys/types/ranges and no unknown fields), not merely JSON safety. A production `lambda _: True` is forbidden. The generic detacher's credential checks are defense-in-depth; the local topic validator is the semantic no-secret/no-unknown-field authority.

### Outbound bridge API

Add the fully annotated method:

```python
async def relay_one_way(
    self,
    target_node_id: str,
    topic: str,
    payload: dict[str, Any],
) -> bool:
```

Return meaning:

- `True`: one validated envelope was handed to `send_to_peer()` without an ordinary exception;
- `False`: closed bridge, invalid/unconfigured/disconnected/self target, unregistered/invalid topic, invalid/oversized payload, or an ordinary send exception observable by the bridge;
- cancellation at the caller-owned outbound transport await propagates (the validator is synchronous).

This is best-effort admission, **not remote receipt acknowledgement**. Current NATS/ZeroMQ `send_to_peer()` methods may internally swallow/log some transport failures, so `True` means only that the await returned; do not claim delivery or infer peer receipt.

Outbound admission must bounded-detach the payload, enforce the complete-wire byte cap, and then require the sender-local topic validator to return literal `True` before sending the message. The receiver independently repeats bounded detachment/final-wire validation before its own local validator; sender validation is not a trust boundary. Give each validator an independent bounded detached copy so a mutating local validator cannot alter the payload later sent to the transport or sink.

Before all of that work, outbound relay admission must require both the local source `self._node_id` and caller-selected target to satisfy C1's exact relay-local safe-node predicate.

### Exact wire envelope

Use `FederationMessage(type="relay_one_way", source_node=self._node_id, ...)` and preserve the existing top-level serializer exactly.

The payload is an exact built-in dict with exactly these five keys:

```json
{
  "relay_version": 1,
  "target_node_id": "node-b",
  "topic": "avatar.telemetry.v1",
  "payload": {},
  "hop_count": 0
}
```

Rules:

- `relay_version`: exact built-in `int`, not `bool`, exactly `1`;
- `target_node_id`: exact safe configured node ID under `^[A-Za-z0-9_-]{1,128}$`, must equal the receiver on inbound;
- `topic`: exact built-in string, canonical regex, registered locally;
- `payload`: detached exact-built-in JSON object; root must be an exact dict;
- `hop_count`: exact built-in `int`, exactly `0`.

No `delivery_mode`, intent, agent target, TTL, urgency, context, reply subject, response type, or caller-authored provenance exists.

The byte cap applies to the complete normalized five-field transport object—not only the nested relay payload. The finalizer first requires both `source_node` and payload `target_node_id` to satisfy C1's one relay-local exact safe-node predicate:

```json
{
  "type": "relay_one_way",
  "source_node": "node-a",
  "message_id": "...",
  "payload": {"relay_version": 1, "target_node_id": "node-b", "topic": "avatar.telemetry.v1", "payload": {}, "hop_count": 0},
  "timestamp": 0.0
}
```

The inbound `timestamp` must be an exact built-in finite `int` or `float` so compact `allow_nan=False` encoding is total, but it remains sender-local metadata and is never interpreted as age, TTL, ordering, or replay authority. Existing transports already normalize raw input to the five-field `FederationMessage`; AD-1123 does not alter their raw deserializers.

### Server-owned receiver provenance

The sink receives two positional values only:

```python
await contract.sink(message.source_node, detached_payload)
```

`source_node` is taken from the validated `FederationMessage`, not from payload content. The payload schema has no source/origin/provenance key. If a semantic consumer needs `origin_mesh_id`, it derives it from the first sink argument. AD-722b-5a must not trust a caller-authored origin field.

Configured-source admission is the existing deployment/transport ACL boundary. It is **not cryptographic source authentication**; AD-1123 must say so in docs/logs and must not resurrect the phantom AD-480 signing API from the old AD-722b-5 draft.

---

## Bounds and forbidden values

Put the bounded detacher in `src/probos/federation/relay.py`; it must be iterative and total over arbitrary Python values without invoking user overrides.

Use these fixed constants:

- maximum depth: **8** (root dict depth 0);
- maximum visited nodes: **512**, counting every scalar/container and every dict key inspected;
- maximum one string/key: **4,096 Unicode code points**;
- maximum aggregate UTF-8 bytes across all keys and string values: **32,768**;
- signed integer range: **64-bit**;
- maximum final compact UTF-8 envelope JSON: **32,768 bytes**;
- maximum registered topics: **16**;
- topic maximum: **64 characters**;
- receiver admission: **64 messages/second per `(configured_source_node, registered_topic)`**;
- receiver rate keys: at most `configured peer count × registered topic count`; create only after exact admission and remove a key when its pruned window is empty;
- node ID predicate: one compiled relay-local `^[A-Za-z0-9_-]{1,128}$` predicate in `relay.py`, exact built-in strings only, used by the pure finalizer for source and target and by the bridge per C1; do not import or duplicate the private directed constant.

Admit only exact built-ins:

- `None`, `bool`, signed-64 `int`, finite `float`, `str`, `list`, `dict`;
- dict keys must be exact strings;
- reject tuple/set/frozenset, bytes/bytearray/memoryview, Decimal, dataclass/model instances, subclasses of every admitted scalar/container, nonfinite floats, oversized ints, cycles, excessive depth/nodes/strings/UTF-8/final JSON.

The traversal must use built-in descriptors (`dict.items`, `dict.__len__`, `dict.__getitem__`, `list.__len__`, `list.__getitem__`, `str.__len__`, `str.encode`) only after exact-type checks. Before iterating a container, use its exact built-in length to reject an impossible node budget immediately (`1 + list length`, `1 + 2 * dict length`, plus nodes already visited); a million duplicate/invalid entries must not extend work. It must not call generic `json.dumps()` until the bounded detached graph exists. Treat `UnicodeEncodeError` as rejection. Final JSON uses `ensure_ascii=False`, `allow_nan=False`, `separators=(",", ":")`; decode the complete normalized transport object once to prove final wire content contains detached built-ins and return/use only its detached relay payload. The **32,768-byte complete-wire ceiling is independently load-bearing** even though the nested string budget is also 32,768: fixed envelope keys, metadata, and punctuation make a payload at the aggregate string ceiling exceed the complete-wire ceiling. Test this case through the complete finalizer, not the value helper.

### Secrets and binary policy

Binary and data-URL content is forbidden by the exact type/string policy. In addition, reject a dict key (case-insensitive exact match after ASCII lowercase) in this finite set anywhere in the payload:

```text
password
passwd
secret
token
access_token
refresh_token
api_key
authorization
cookie
set-cookie
private_key
client_secret
```

Also reject every string whose first non-ASCII-whitespace characters case-insensitively begin with any of:

```text
data:
bearer<SPACE>
basic<SPACE>
-----begin private key-----
-----begin rsa private key-----
-----begin openssh private key-----
```

`<SPACE>` means one literal ASCII space after the word; the marker avoids Markdown trailing-whitespace ambiguity in this prompt.

This is defense-in-depth, not a claim to detect every secret. Rejections must log only target/topic/reason/exception type; never payload values, keys, reprs, hashes, or serialized bodies.

---

## Inbound behavior

Extend `FederationBridge.handle_inbound()` with exactly one new branch:

```python
elif message.type == "relay_one_way":
    await self._handle_relay_one_way(message)
```

The branch is terminal: after `_handle_relay_one_way()` returns for success or any rejection, `handle_inbound()` returns. A malformed relay never falls through to legacy intent, response, gossip, mobility, or ping handling.

The private handler admits in this order, before sink work:

1. bridge relay admission is open;
2. exact `FederationMessage` and exact `type == "relay_one_way"`;
3. the receiver-local `self._node_id` satisfies C1's exact relay predicate, before configured-source work, payload traversal, target equality, clock access, or rate state;
4. exact safe configured non-self `source_node`, with relay-predicate admission before configured membership;
5. safe correlation-shaped `message_id` only as bounded envelope metadata—there is no pending map and no response;
6. exact five-key payload before iterating nested content;
7. `relay_version == 1`, `hop_count == 0`;
8. exact safe `target_node_id` under the same relay predicate, then equality with the already-validated `self._node_id`;
9. exact canonical topic registered in this receiver's immutable registry;
10. receiver rate precheck for the exact `(source_node, topic)` key (prune + reject when already full, but do not append yet);
11. bounded detach/final envelope cap, which independently revalidates source and target;
12. receiver-local topic validator receives an independent detached copy and returns literal `True` (not merely truthy);
13. append one accepted timestamp, then invoke the exact registered sink once.

Drop on any failure. Do not send an error response: unknown, malformed, unconfigured-source, wrong-target, decoy/unregistered-topic, rejected payload, and sink failure all produce **zero outbound message**. This avoids reflection and target/topic discovery.

- Validator ordinary exception: warning + drop (the validator is synchronous).
- Sink ordinary exception: warning + drop. On `asyncio.CancelledError`, inspect `asyncio.current_task().cancelling()`: re-raise when the enclosing task has a real cancellation request; when a misbehaving sink directly raises `CancelledError` without cancelling the task (`cancelling() == 0`), log/drop it as plugin failure. Do not call `uncancel()` and do not create a child task.
- Neither path retries or invokes another sink.
- Never mutate the detached payload after validation.
- Never call `handle_inbound()` recursively, `send_to_peer()`, `send_to_all_peers()`, `IntentBus.broadcast()`, `IntentBus.send()`, `_emit_event`, or a runtime dispatcher from the relay handler.
- `hop_count` is fixed at 0 and inbound relay is terminal. There is no rebroadcast or relay-of-relay API.

### Lifecycle

Reuse the bridge lifecycle owner:

- add `_relay_admission_open`, initialized `True` for direct-construction compatibility (matching AD-730-4 directed admission);
- `start()` closes it and clears stale relay-rate state while wiring, then opens it only after successful startup;
- a transport inbound-handler assignment failure propagates while leaving relay admission closed, relay-rate state empty, and `_gossip_task is None`; a later successful `start()` reopens admission and creates the one existing gossip task, as frozen by C3;
- `stop()` closes it and clears bounded relay-rate state before awaiting gossip cancellation;
- outbound after stop returns `False` before transport work;
- inbound after stop drops before validator/sink work;
- successful restart reopens it;
- an already-admitted call has no bridge task/future registry. Cancellation at the outbound transport or inbound sink await propagates after no bridge-owned cleanup.

Do not add a task, message queue, worker, timer, condition, semaphore, or drain loop. Shutdown already stops the bridge before the transport and NATS bus; preserve that order.

---

## Backpressure and drop policy

AD-1123 adds no message buffering. Backpressure is the caller's awaited `relay_one_way()` call plus the existing transport await.

- One caller → one target → one `send_to_peer()` call maximum.
- No bridge fanout API. A producer wanting multiple peers iterates its **already admitted subscriptions** and awaits one call per peer. AD-722b-5 already owns peer subscription filtering and the 10 fps/peer rate limit.
- Receiver defense-in-depth uses a fixed sliding one-second timestamp window capped at 64 schema-valid entries per `(configured source, registered topic)`. Run a non-allocating/full-bucket precheck after exact source/target/topic admission but before payload traversal; append the timestamp only after bounded detach and literal-True topic validation, immediately before the sink await. Thus malformed payloads pay bounded validation work but cannot consume valid capacity. Do not allocate state for unknown sources/topics. The finite Cartesian key space is bounded by static config peers × immutable topics; prune on access and delete empty windows. A full-bucket drop is silent, produces no response, does not consume detach/validator/sink work, and does not append another timestamp. Use `time.monotonic()`; clear all rate state on `start()` and `stop()`. There are no awaits between rate precheck and timestamp append, so event-loop execution makes admission atomic without a lock. This state is admission accounting, not a delivery queue.
- No message queue means no stale telemetry backlog and no shutdown drain.
- An ordinary transport exception that reaches the bridge is logged and returns `False`; a transport-internal silent drop may still yield `True` under the legacy transport contract. Caller telemetry continues either way.
- Cancellation is lifecycle control and propagates.
- AD-722b-5a remains responsible for its stricter 10 fps/peer outbound telemetry cadence. The generic 64/s receiver cap is only a safety ceiling, not a promised throughput SLA.

---

## Implementation sections

### Section 0 — Event types

**None.** AD-1123 adds no `EventType` and does not dispatch any received topic into the runtime event system. Relay failures use structured logs only; `src/probos/events.py` is forbidden.

### Section 1 — New bounded relay contract module

**New file:** `src/probos/federation/relay.py`

Implement:

- constants above;
- `RelayPayloadValidator`, `RelaySink` aliases;
- frozen `FederationRelayTopic`;
- canonical topic predicate plus C1's one public pure `is_safe_relay_node_id()` helper; relay finalization and bridge relay paths use that helper, while correlation/configured-membership policy remains with the bridge;
- exact five-key payload extractor;
- iterative exact-built-in bounded detacher;
- forbidden secret-key/string-prefix checks;
- complete five-field compact-wire detachment/cap helper (the `FederationMessage` normalization shape, including outer metadata).

All public names have complete type annotations. Keep bridge-independent helpers pure. Do not import runtime, IntentBus, events, telemetry, config, or transport implementations.

### Section 2 — Add relay policy and terminal dispatch to the bridge

**Modify:** `src/probos/federation/bridge.py`

- import only the relay contract/helpers needed;
- append `relay_topics` to `FederationBridge.__init__()`;
- build the immutable topic map and `_relay_admission_open` state;
- extend `start()`/`stop()` as specified;
- add public `relay_one_way()`;
- add one `handle_inbound()` branch;
- add private `_handle_relay_one_way()`;
- do not touch trust/Hebbian stats or existing counters.

Preserve these executable method bodies exactly at their HEAD AST hashes:

| Method | HEAD AST SHA-256 |
|---|---|
| `FederationBridge.forward_intent` | `595c3fd2fc311b91f8ba3049909d0c383985dbdb15f9d9f19b35f806bf1a7eac` |
| `FederationBridge.forward_direct_message` | `8189296e1b8902126031f0f9e35050c48eebce5f2e03ea142ecc968285595cb4` |
| `FederationBridge._handle_intent_request` | `e9f950e1c291249f86a6181c1198284da4e783945540c486b148a21978a47348` |
| `FederationBridge._send_directed_response` | `ba1ce85fdd6fb6c3f7e821795c92cc97d8d0f3eb39980145491649c46e8f35f2` |
| `FederationBridge._handle_direct_message_request` | `3c42fe328f49c3667d4e19d8c8a5a9ce15d1c890de8d61bcac48686913487673` |

`start()`, `stop()`, and `handle_inbound()` necessarily gain relay-only statements/branch; preserve every existing statement, order, and branch around those additive changes.

### Section 3 — Production composition supports explicit relay topics

**Modify:** `src/probos/startup/fleet_organization.py`

Append a backward-compatible keyword-only input:

```python
relay_topics: tuple[FederationRelayTopic, ...] = (),
```

Pass it to the sole production `FederationBridge(...)` construction before `bridge.start()`. The empty-tuple default preserves the five existing direct test callers of `organize_fleet()` without editing their files; the sole runtime composition remains explicit so production policy is visible.

**Modify:** `src/probos/runtime.py`

At the sole `organize_fleet()` call, pass:

```python
relay_topics=(),
```

AD-1123 production therefore registers no topics and is inert/byte-identical. AD-722b-5a will replace that empty tuple with the avatar contract and wire the producer/sink. Do not add a runtime relay attribute, callback, config read, avatar import, or startup phase.

**Rollback:** before any child topic is registered, reverting AD-1123 is a code-only rollback—there is no config, persisted state, stream, durable subscription, migration, or external cleanup. After a child AD registers a topic, revert that child wiring first, then this primitive.

### Section 4 — Red-first and complete relay tests

**New file:** `tests/test_ad1123_bounded_federation_relay.py`

Write the complete test file first. Before production edits, run only the headline test and record the expected failure because `FederationBridge.relay_one_way`/`FederationRelayTopic` do not exist. Do not weaken the test.

Define one reusable **test-only strict topic contract** named `test.telemetry.v1`. Its validator accepts only an exact built-in three-key payload `{"agent_id": <safe exact str>, "frame_type": "snapshot" | "diff", "data": <exact built-in dict>}`, rejects unknown/missing fields and subclasses, and applies finite/range/type checks to its test data. The headline and normal happy paths use this validator—never `lambda _: True`. Separate tests may intentionally install rejecting/raising/mutating validators.

The final test file must cover at minimum:

1. **Headline production composition:** two real `organize_fleet()` calls, two real bridges and `NATSFederationTransport`s over one started shared `MockNATSBus`; each node receives the explicit immutable strict `test.telemetry.v1` topic contract; one origin call reaches exactly the receiver sink once with `(source_node="node-a", detached_payload)`. A decoy sink on another topic remains untouched. No direct bridge construction in this test.
2. **Specific one-peer addressing:** add a third configured node and prove `relay_one_way("node-b", ...)` reaches B only, never C; exactly one target subject publish.
3. **Receiver sink only:** exact registered topic invokes only its sink; decoy registered topic and unregistered topic invoke none.
4. **Unregistered sender topic:** rejected before `send_to_peer()`.
5. **Unregistered receiver topic:** dropped with zero response/outbound work.
6. **Configured source admission:** unconfigured/self/spoofed source drops before validator/sink and sends no response.
7. **Wrong target:** drops before validator/sink and sends no response.
8. **Exact schema/version/hop:** missing key, extra key, bad key type, dict subclass, wrong version type/value, wrong hop type/value all drop.
9. **Canonical names/contracts:** invalid/oversized/self/unconfigured/disconnected target; invalid/oversized topic; duplicate or >16 topic registrations; bad validator/sink signatures; sync sink rejection.
10. **Payload happy path:** nested exact JSON built-ins detach without aliasing; mutating the original after send cannot mutate sink capture.
11. **Bounds:** exact boundary success and over-bound rejection for depth, 512 nodes, 4,096-char string/key, 32,768 aggregate UTF-8, 32,768 final envelope bytes, signed-64 integer; final-byte cases call the complete wire finalizer.
12. **Hostile values:** list/dict/str/int/float subclasses whose iteration/access/conversion methods raise are rejected without invoking overrides; tuple/set/Decimal/model/object are rejected.
13. **Cycles/nonfinite/binary:** self/mutual cycles, NaN/±Inf, bytes/bytearray/memoryview reject before send/sink.
14. **Secrets:** every forbidden key at nested depths, every forbidden string prefix with case/leading-whitespace variants, data URLs, bearer/basic credentials, and private-key headers reject; payload values never appear in logs.
15. **Bounded-work proof:** a million-item list and million-key/hostile structure fails at the node/final bounds before generic JSON serialization or scanning the whole object; instrument access count.
16. **Validator policy:** literal `True` admits; `False`, non-bool truthy, and ordinary exception drop; a mutating validator cannot alter transport/sink payload.
17. **Sink policy:** ordinary exception is contained with contextual warning and no response/retry/other sink; a directly raised plugin `CancelledError` with no task cancellation request is contained, while a real enclosing-task cancellation propagates. Test real `task.cancel()` while a sink awaits an event.
18. **Transport policy:** ordinary send exception returns `False`; cancellation propagates; no response/receive/request API is invoked.
19. **Backpressure/drop:** first 64 same-source/topic schema-valid messages in one monotonic second may reach the sink; the 65th drops before detach/validator/sink; malformed/validator-rejected messages consume no capacity; another topic/source has an independent bucket; the window recovers; unknown traffic allocates no state; empty windows are removed; map cardinality never exceeds configured peers × registered topics; start/stop clear state.
20. **Lifecycle:** post-stop outbound returns `False`, post-stop inbound drops, successful restart reopens; zero task/future/message-queue registry is added.
21. **No loop:** inbound relay never calls transport send, broadcast, targeted send, `_emit_event`, or `handle_inbound` recursively; `hop_count != 0` drops.
22. **No learning:** recording trust and Hebbian fakes remain untouched for send, receive, malformed, validator-fail, sink-fail.
23. **NATS/ZeroMQ parity:** the same valid relay envelope serializes/deserializes identically through the real NATS and ZeroMQ serializer methods; no serializer edit.
24. **Mock transport parity:** valid round trip over `MockFederationTransport` reaches one sink and no response queue.
25. **Legacy unchanged:** existing untargeted intent envelope/broadcast and AD-730-4 directed DM target/correlation paths still behave exactly; include AST hash assertions for all five frozen bridge methods and serializer/send methods listed below.
26. **Empty-registry golden:** direct construction and real runtime composition with `relay_topics=()` reject outbound relay before transport work and drop inbound relay before payload traversal, rate-state allocation, or sink work; every pre-AD federation path remains unchanged.
27. **Layer/dispatch source guards:** no `IntentMessage`, `IntentBus`, `EventType`, `_emit_event`, trust/Hebbian call, `send_to_all_peers`, response construction, message-queue/task creation, or runtime import in `relay.py`/relay handler; no allow-all validator appears in production or the standard test fixture.
28. **Relay identity predicate:** pure helper/finalizer and outbound/inbound bridge matrices reject empty, dot, space, 129-character, and `str`-subclass source/target IDs without downstream work; exact-128 source and target succeed through helper, finalizer, outbound, and inbound paths.
29. **Callable introspection containment:** ordinary failures from `callable`, `inspect.signature`, `inspect.iscoroutinefunction`, and hostile callable metadata normalize to exact `ValueError("relay_topics_invalid")`; `BaseException` propagates; partial/callable-object/decorated-async accepted and rejected cases lock C2's conservative policy.
30. **Startup failure/restart:** a fail-once transport inbound-handler assignment leaves relay admission closed, rate state empty, no gossip task, and outbound false; a later successful start opens admission and sends normally.

Freeze unchanged serializer/send AST hashes:

| Method | HEAD AST SHA-256 |
|---|---|
| `NATSFederationTransport._serialize` | `1f45de4520164bcbb565259b2b9356ae0b42ad7a39434a1c85483dc37409cbbf` |
| `NATSFederationTransport._deserialize` | `88b50d275a63b5a92db1d208350679c179dbc2906756b51d40ff1fad1524d8f1` |
| `NATSFederationTransport.send_to_peer` | `9ad857133b2532ae9d5176c9530724108d531ebf5f3b4779541f0f45581e1cd6` |
| `FederationTransport._serialize` | `11491399ff191d2fb65ff5f0480aafad8a0145f633359dcfd82b1a8b03c5f702` |
| `FederationTransport._deserialize` | `7b5024d9d18ea5d90c6eb2ba04e62619c486edafe60b025bfeafea3075aa34f2` |
| `FederationTransport.send_to_peer` | `95f05ada8a2e84aa11648a8fae9a10f86b7b10d8383bb88170aa9783e51c3ad9` |
| `MockFederationTransport.send_to_peer` | `39a597a65eb1948bec8d323549f6dee70e37e2d66d880620a1e6d9c28bc33b8b` |
| `MockFederationTransport.deliver_response` | `a6bc723bb6466adf51f92af12e34f7221bfaac3713258aa5a60ae03aabddda0e` |

Do not edit any existing test file. A conflicting existing assertion is a hard stop.

---

## AD-722b-5a dependency status

After AD-1123 ships, #659 becomes **unblocked but remains open**.

The child build must separately:

- construct an `avatar.telemetry.v1` topic contract at the runtime composition root;
- validate exact avatar frame schema (`agent_id`, `frame_type`, bounded frame payload) rather than merely returning `True`;
- set the existing `FederationTelemetryRelay.set_emit_callback()` to an adapter that calls `bridge.relay_one_way(peer_id, "avatar.telemetry.v1", ...)`;
- register configured subscriptions and connect the local avatar frame producer;
- provide a receiver-local avatar sink that surfaces remote telemetry to the intended local fleet consumer;
- derive `origin_mesh_id` from the sink's server-owned `source_node` argument;
- preserve the existing 10 fps/peer rate limiter and add no duplicate buffer;
- decide the concrete remote fleet sink contract without changing the generic relay.

AD-1123 does not close #659 because none of those telemetry semantics are built here.

---

## Exact file allowlist

### Production

- `src/probos/federation/relay.py` — new
- `src/probos/federation/bridge.py`
- `src/probos/startup/fleet_organization.py`
- `src/probos/runtime.py`

### Test

- `tests/test_ad1123_bounded_federation_relay.py` — new

### Architect prompts retained in the implementation commit

- `prompts/ad-1123-bounded-federation-relay.md`
- `prompts/ad-1123-bounded-federation-relay-execution.md`

### Conditional closeout after all gates

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- move, do not rewrite, both prompt docs to `prompts/archive/`

No other source, test, config, YAML, event, protocol, type, transport, UI, desktop, dependency, workflow, era, data, or log file is authorized. In particular, do not edit:

- `src/probos/types.py`
- `src/probos/events.py`
- `src/probos/protocols.py`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`
- `src/probos/federation/telemetry_relay.py`
- `src/probos/mesh/nats_bus.py`
- `src/probos/mesh/intent.py`
- `src/probos/routers/agents.py`
- `src/probos/avatars/**`
- `src/probos/startup/results.py`
- `src/probos/startup/shutdown.py`
- `src/probos/federation/__init__.py`
- `config/system.yaml`

The ignored `logs/ad1123_issue_body.md` is Architect output only. It remains ignored and unstaged.

---

## Four isolated Windows gates and recorded baselines

Every gate uses a unique temporary `PROBOS_DATA_DIR`, `PROBOS_EMBEDDINGS=local`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, no pytest cache, serial `-n 0`, `--timeout=90`, short traceback, and `RuntimeWarning` promoted to error.

| Gate | Exact existing baseline at HEAD | Expected after build |
|---|---:|---:|
| 1 — relay/federation | **91 passed** | 91 + new AD-1123 module count |
| 2 — directed/transport | **333 passed** | 333 + new AD-1123 module count |
| 3 — avatar surface | **77 passed, 5 known BF-326 warnings** | unchanged 77; AD-1123 test is not duplicated here |
| 4 — startup/lifecycle | **243 passed, 2 third-party deprecation warnings** | 243 + new AD-1123 module count |

### Gate 1 — AD-1123 + relay/federation

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_gate1_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1123_bounded_federation_relay.py tests/test_ad722b_5_federation_telemetry.py tests/test_federation.py tests/test_federation_nats.py tests/test_ad637a_nats_foundation.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 2 — AD-1123 + AD-730-4/transport parity

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_gate2_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1123_bounded_federation_relay.py tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_federation.py tests/test_federation_nats.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 3 — avatar producer/WS baseline unchanged

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_gate3_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722_avatar_telemetry.py tests/test_ad722b_websocket_push.py tests/test_ad722b4_fleet_telemetry.py tests/test_ad722b_3_snapshot_diff.py tests/test_ad722b_5_federation_telemetry.py tests/test_bf626_ws_safe_close.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 4 — AD-1123 + federation governance/runtime/shutdown

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_gate4_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1123_bounded_federation_relay.py tests/test_ad479_federation_hardening.py tests/test_ad480_federation_mcp_a2a.py tests/test_ad443_mobility.py tests/test_runtime.py tests/test_ad447_phase_gates_pool_group.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

The 5 BF-326 warnings in Gate 3 and 2 dependency deprecations in Gate 4 are recorded HEAD baselines. No new warning is allowed. Do not use `-n auto` or substitute a shared/live data directory.

---

## Tracking, archival, and commit

Only after all four gates pass:

1. prepend a concise AD-1123 shipped entry to `PROGRESS.md`, including exact test counts/warnings, the closed relay boundary, #659 remaining open/unblocked, AD-1123 as the new ceiling, and unchanged BF-672 ceiling;
2. prepend `### AD-1123` under Era V in `DECISIONS.md` with Context / Decision / Tests; explicitly state configured-peer admission is not cryptographic authentication and no intent/event injection exists;
3. update the roadmap row for AD-722b-5a so its prerequisite is **SHIPPED via AD-1123; #659 unblocked/open**, without claiming the telemetry hop itself shipped;
4. add a nearby AD-1123 shipped row for the generic primitive if the roadmap table structure requires it;
5. move the two prompt docs unchanged to `prompts/archive/` in the same implementation commit;
6. leave `logs/ad1123_issue_body.md` ignored and unstaged;
7. commit exactly:

```text
AD-1123: add bounded federation one-way relay
```

Do not add `closes #659`. The proposed AD-1123 prerequisite issue does not exist yet and this architecture session must not mutate GitHub. If the Captain creates it before build, the Captain decides whether to add a closing trailer.

Before commit: `git diff --cached --stat`, `git diff --cached --check`, and verify the staged name set exactly matches the allowlist after prompt moves.

---

## Do Not Build

- Do not build #659 / AD-722b-5a telemetry producer, subscription config, receiver avatar sink, `origin_mesh_id` UI/frame field, or HXI work.
- Do not add arbitrary intent forwarding, arbitrary `EventType` forwarding, runtime event replay, callback names on the wire, reflection/dynamic import, wildcard topics, topic patterns, or remote registration.
- Do not add request/response, correlation futures, ack/nak, retry, durable queue, replay, ordering/at-least-once claims, backfill, persistence, JetStream stream, NATS Object Store, WebSocket, SSE, gRPC, or a new socket.
- Do not add transport methods or alter transport serializers/deserializers/send methods.
- Do not add trust, Hebbian, consensus, episodic, registry, router, gossip, cluster-monitor, or EventType mutation.
- Do not add signing/JWT/CURVE/NATS-account auth; do not claim configured source IDs are cryptographically authenticated.
- Do not add config/YAML fields, default-on topic registrations, runtime mutable callback registries, a runtime relay attribute, or a broad runtime handle.
- Do not refactor AD-730-4 helpers, move `FederationMessage`, edit `NATSBusProtocol`, or export relay names from the package root.
- Do not alter avatar WS frame shapes or tests.
- Do not close #659.

---

## Acceptance criteria

1. `src/probos/federation/relay.py` contains a pure, iterative, exact-built-in bounded JSON detacher and frozen local topic contract.
2. `FederationBridge.relay_one_way(target_node_id, topic, payload) -> bool` addresses exactly one configured connected peer via existing `send_to_peer()` and has no response/correlation path.
3. Sender and receiver independently enforce topic registration, payload bounds, secret/binary rejection, complete-wire bytes, and literal-True local validation on isolated copies; receiver additionally enforces exact source, target, version, and hop before exactly one sink.
4. Receiver provenance comes from validated `FederationMessage.source_node`; payload cannot author source/origin metadata.
5. Invalid/unconfigured/wrong-target/unregistered/malformed cases drop without response or local side effects.
6. Ordinary validator/sink/transport errors honest-degrade; `asyncio.CancelledError` propagates from outbound transport and inbound sink awaits.
7. No message queue/task/timer/retry/fanout/rebroadcast/trust/Hebbian/intent/event dispatch is added; only bounded receiver rate-accounting state exists.
8. NATS, ZeroMQ, and mock transport APIs and serializers remain unchanged; parity is test-proven.
9. Legacy untargeted federation and AD-730-4 directed DM methods retain their pinned executable AST hashes.
10. Real production composition passes an explicit empty topic tuple, so default behavior and avatar paths are inert/unchanged.
11. Headline test uses two real `organize_fleet()` bridges over one shared `MockNATSBus` and proves exact receiver sink only.
12. One relay-local exact `^[A-Za-z0-9_-]{1,128}$` predicate validates finalizer source/target plus outbound local source and inbound local target before downstream work; all C1 boundary matrices pass.
13. Topic callable introspection follows C2: every ordinary inspection failure becomes exact `ValueError("relay_topics_invalid")`, lifecycle `BaseException` propagates, and ambiguous async callables reject without invocation.
14. A failed bridge start is relay-fail-closed with empty rate/no task/no outbound work, and a later successful restart reopens exactly once.
15. The original headline red and the correction-red results are reported truthfully; all adversarial, lifecycle, error, cancellation, loop, no-response, and no-learning tests listed above pass.
16. Four isolated Windows gates meet or exceed their recorded baselines with no new warnings.
17. Trackers state AD-1123 is the new top-level; #659 is unblocked but open; BF-672 remains the BF ceiling.
18. Prompts are archived unchanged only at closeout; ignored issue draft is never staged.
19. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-07-17, exact HEAD `8eeaf406`)

```text
PROGRESS.md:13
  AD-1122 is the new top-level.
DECISIONS.md:29
  ### AD-1122
PROGRESS.md:850
  AD-722b-5 local relay + set_emit_callback; bridge hop forward-marked.
DECISIONS.md:5887,5899
  AD-722b-5 decision and future bridge hookup.
docs/development/roadmap.md:669-671
  AD-722b-5 shipped local-only; AD-722b-5a/5b remain forward markers.

src/probos/federation/telemetry_relay.py:30,53,71,78,130
  FederationTelemetryRelay, register_peer, set_emit_callback,
  on_local_telemetry_frame, and callback shape exist.
src/probos/federation/bridge.py:863,910,920,932,1033,1206,1367
  FederationBridge lifecycle, legacy forward, directed forward,
  inbound dispatch, and directed handler exist.
src/probos/federation/bridge.py:518
  AD-730-4 iterative bounded detacher precedent exists.
src/probos/federation/bridge.py:1316
  Configured-directed-source admission precedent exists.
src/probos/federation/bridge.py:1293
  Legacy inbound loop prevention uses federated=False.
src/probos/federation/bridge.py:1514
  Directed receiver installs source provenance server-side.

src/probos/federation/nats_transport.py:157,253,272,282
  Existing send_to_peer, inbound callback, serializer, deserializer.
src/probos/federation/transport.py:165,263,287,298
  Existing ZeroMQ send_to_peer, recv loop, serializer, deserializer.
src/probos/federation/mock_transport.py:64,141,203
  Existing in-process deliver/send and response routing.
src/probos/startup/fleet_organization.py:28,211,221
  Sole organize_fleet path, sole production bridge construction, bridge start.
src/probos/runtime.py:1962
  Runtime receives organized bridge.
src/probos/startup/shutdown.py:912-917,973
  Bridge stops before transport; NATS stops later.
src/probos/types.py:926
  FederationMessage free-form type exists.
src/probos/events.py:20,179,196
  EventType taxonomy exists; relay must not dispatch into it.
src/probos/protocols.py:262,279-280
  NATSBusProtocol already includes raw publish/subscribe; unchanged.
src/probos/mesh/nats_bus.py:896,908,948,1235,1251
  Real/mock raw NATS APIs and MockNATSBus exist.

src/probos/config.py:1388,2205,2300,3045
  PeerConfig, AvatarTelemetryConfig/fleet flag, FederationConfig exist.
src/probos/runtime.py:547
  AvatarEventBus is runtime-owned; AD-1123 does not wire it.
src/probos/routers/agents.py:2158,2231,2288,2311
  Fleet WS endpoint and snapshot/diff frame emit sites exist; unchanged.
src/probos/routers/agents.py:1992-2092,2258-2342
  Per-agent and fleet publish loops own timer/event wakes, snapshot/diff sends,
  ping, history, and Records side effects; AD-1123 does not hook them.
src/probos/avatars/telemetry.py:345,376,586
  Snapshot/to_dict/build surface exists; unchanged.
src/probos/avatars/events.py:32,63
  Local event bus/notify exists; unchanged.
src/probos/avatars/sampling_state.py:104-145
  Popout sampling refcount and current-rate surface exist; unchanged.
src/probos/cognitive/cognitive_agent.py:2818-2826,4380-4393
  Chain/reply trigger notifications exist; unchanged.
src/probos/cognitive/dm/reply_pipeline.py:1706-1721
  DM exit + telemetry wake remains the single post-reply path.

tests/test_ad730_4_directed_federated_vision_dm.py:411
  Two real organize_fleet bridge headline precedent.
tests/test_ad730_4_directed_federated_vision_dm.py:829
  Unconfigured spoofed-source drop precedent.
tests/test_ad730_4_directed_federated_vision_dm.py:1573
  NATS/ZeroMQ serializer parity precedent.
tests/test_ad730_4_directed_federated_vision_dm.py:1821
  Legacy exact-envelope guard precedent.
tests/test_ad730_4_directed_federated_vision_dm.py:2447,2553
  Binary/nonfinite/cycle/bounds and hostile-subclass precedents.
tests/test_ad730_4_directed_federated_vision_dm.py:3278
  Stop/restart admission precedent.
tests/test_ad722b_5_federation_telemetry.py:119
  Existing callback receives (peer_id, agent_id, frame_type, payload).
tests/test_ad722_avatar_telemetry.py, test_ad722f_adaptive_sampling.py,
test_ad722b_websocket_push.py, test_ad722b4_fleet_telemetry.py,
test_ad722b_3_snapshot_diff.py, test_ad722b_1_crew_scope_auth.py,
test_ad722b_5_federation_telemetry.py, and test_bf626_ws_safe_close.py
  Full AD-722/722b backend producer, sampling, auth, WS, diff, local-relay,
  and close-race test surfaces were read before approval.
ui/src/avatars/useFleetAvatarTelemetry.ts:13-66
  Fleet hook parses local WS frames into {type, agent_id, payload}; unchanged.
ui/src/store/useStore.ts:1020-1043
  Store owns snapshot replace/diff merge; unchanged.
ui/src/components/CognitiveCanvas.tsx:68-74 and
ui/src/components/profile/MeetingView.tsx:299-307
  Current local fleet hook consumers are unchanged; remote-source identity
  and HXI multiplexing remain #659/AD-722b-5a scope.
ui/src/__tests__/useFleetAvatarTelemetry.test.ts and
ui/src/__tests__/useStore.avatarTelemetry.test.ts
  Consumer contract tests were read; no AD-1123 UI edit or Vitest gate needed.
```

Issue #659 was read in full through GitHub on 2026-07-17. It remains open and states that AD-722b-5 shipped local callback plumbing while the federation bridge hop waits for a streaming/relay primitive.

GitHub state was re-read after artifact creation: `OPEN`, `updatedAt=2026-05-15T21:45:32Z`; no issue mutation occurred.
