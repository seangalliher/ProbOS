# AD-1276 (BF-789, #1253): a node charges its policy exactly once

**Status:** Ready to build
**Dependencies:** BF-771 (#1228, landed), BF-789 Dispatcher slice (commit `f60ba750`, landed), AD-698, AD-654a/b/c
**Estimated tests:** ~34 new (Section 0: 6 · Section 1: 14 · Section 2: 8 · Section 3: 6)
**Do NOT close #1253 on Section 1 alone.** All three sections are required — see *Closure*.

---

## Problem

BF-771 closed the **producer** side: `IntentBus.broadcast()`, `send()` and `dispatch_async()` each
evaluate AD-698 pre-intent authorization exactly once, at
[intent.py](../src/probos/mesh/intent.py#L1043), [intent.py](../src/probos/mesh/intent.py#L943) and
[intent.py](../src/probos/mesh/intent.py#L1256).

Three **consumer-side** paths still reach a subscriber's handler with the hook never consulted.
Verified by enumeration, not recall — `Select-String -Pattern 'authorize'` over
`src/probos/mesh/intent.py` lines 526–780 (the `_nats_subscribe_agent` and
`_js_subscribe_agent_dispatch` bodies) returns **0 matches**:

| # | Path | Site | Reaches handler at |
|---|---|---|---|
| 1 | NATS request/reply callback | `_on_nats_intent`, [intent.py](../src/probos/mesh/intent.py#L530) | [intent.py](../src/probos/mesh/intent.py#L534) |
| 2 | JetStream direct callback | `_on_dispatch`, [intent.py](../src/probos/mesh/intent.py#L634) | [intent.py](../src/probos/mesh/intent.py#L718) |
| 3 | JetStream → AD-654b cognitive queue | same callback | [intent.py](../src/probos/mesh/intent.py#L709) → [queue.py](../src/probos/cognitive/queue.py#L333) |

### The fourth row of the issue is already closed — do not rebuild it

Issue #1253 lists a fourth path, the AD-654c `Dispatcher`. It was fixed in commit `f60ba750`
("BF-789: the Dispatcher authorizes what nothing else does"). Both unguarded arms now call
`authorize_intent` — [dispatcher.py](../src/probos/activation/dispatcher.py#L135) (`dispatcher_queue`)
and [dispatcher.py](../src/probos/activation/dispatcher.py#L198) (`dispatcher_direct`) — and the third
arm deliberately does not, because it delegates to `IntentBus.dispatch_async`, which does. Tests live
in [test_bf789_dispatcher_authorization.py](../tests/test_bf789_dispatcher_authorization.py).
**The issue body was not updated.** A Builder reading only the issue will redo this. Do not.

### Why this is a design decision, not a patch

Every locally-subscribed agent also subscribes to its *own* NATS and JetStream subjects
([intent.py](../src/probos/mesh/intent.py#L465-L483)). So on a connected node, `send()` and
`dispatch_async()` **loop back into this same process**: producer authorizes, wire, consumer
authorizes. A stateless RBAC hook does not care. A **rate limiter is a hook**, and it silently loses
half its allowance with nothing reporting that it happened. That is the same double-evaluation trap
BF-771 avoided on the `broadcast → send` path, and it is already written down as the open question in
[pre_intent_auth.py](../src/probos/mesh/pre_intent_auth.py#L23-L28) ("an origin distinction is needed
first").

---

## Decision

### The invariant, stated per node

> **Each node's hook registry evaluates each intent at most once, and at least once before any
> handler on that node runs.**

Global exactly-once across a federation is neither achievable nor desirable: node B's RBAC is not
node A's RBAC, and each node's policy must apply to work crossing *that* node. Within one process it
must be exactly once, because that is where a stateful hook's counter lives.

### The producer-side check stays where it is

AD-698 is a **pre**-intent gate. It must refuse before the payload is serialized onto the wire.
Moving the check to the receiving end only would (a) put a denied payload on the network before
anyone refused it, and (b) make a purely local denial depend on a network round trip — and when no
subscriber exists, `request()` times out, so a refusal would present as
`"Agent did not respond in time."` This rejects the "authorize at the RECEIVING callback, not both
ends" half of the issue's suggested shape for the loopback case. Keep both ends; make the second one
free.

### The mechanism: a process-local authorization ledger, never a wire field

Add to `IntentBus` a bounded, monotonic-clock-keyed record of intent IDs **this process** authorized.

- `_authorize()` records `intent.id` on ALLOW, and only when it actually evaluated.
- A new consumer-side helper `_authorize_inbound(intent, *, entry_point)` **pops** `intent.id`:
  - **Hit** → this process already charged the hook for this intent → allow **without evaluating**.
  - **Miss** → evaluate via `authorize_intent(intent, entry_point=...)`.

**Hard constraint — the marker must never travel on the wire.** A wire field is peer-controlled: a
peer sets `authorized: true` and bypasses node B's policy completely, converting a latent gap into a
remote policy bypass strictly worse than today. Do not add a field to
[`_serialize_intent`](../src/probos/mesh/intent.py#L1606). Do not read one in
[`_deserialize_intent`](../src/probos/mesh/intent.py#L1624). The ledger is in-process memory a peer
cannot write to, and that is the entire security argument.

**Pop, not peek.** JetStream redelivers — BF-234 exists because it does
([intent.py](../src/probos/mesh/intent.py#L1547)). A record that persisted would wave every
redelivery of that id through unauthorized forever. Popping means the first delivery consumes the
producer's charge and every later delivery is evaluated on its own merits. The error direction is
therefore **over-charge, never under-charge**.

**The honest failure mode, which the code comment must state rather than hide:** if a record is
evicted before the loopback consumes it, the hook is charged twice for that intent. It is bounded,
it is in the fail-safe direction, and it needs an in-flight dispatch longer than the eviction age.
Do not write "exactly once" unconditionally in a docstring — see the standing lesson that a docstring
claiming a property the code lacks *is* the defect (BF-754).

**Empty ids never enter the ledger.** [`_deserialize_intent`](../src/probos/mesh/intent.py#L1624)
defaults `id` to `""`. One empty-id record would wave through every other empty-id intent. Mirror the
existing guard at [intent.py](../src/probos/mesh/intent.py#L1547) (`if not intent_id: return False`):
an empty id is never recorded and is always evaluated.

**Eviction** reuses the BF-234 shape — `dict[str, float]` + `time.monotonic()` + an opportunistic
sweep ([intent.py](../src/probos/mesh/intent.py#L281-L282),
[intent.py](../src/probos/mesh/intent.py#L1553-L1571)) — plus a **hard max-entry cap**, because
`_evict_stale_seen_intents` rebuilds the whole dict and only runs opportunistically. The age cutoff
must be ≥ 300s to cover a queued dispatch: `ack_wait=300` on the dispatch consumer, matching
`_WARD_ROOM_DISPATCH_DEDUP_WINDOW` at [intent.py](../src/probos/mesh/intent.py#L1544).

### The AD-654b queue gets no check — this deliberately rejects the issue's suggested site

Issue #1253 names "the eventual queue invocation in `cognitive/queue.py`". Do not put one there.
Every path that enqueues to `AgentCognitiveQueue` now passes a check first: `_on_dispatch`
(Section 1), the `dispatch_async` local fallback ([intent.py](../src/probos/mesh/intent.py#L1256)),
and the `Dispatcher` ([dispatcher.py](../src/probos/activation/dispatcher.py#L135)). The queue is
in-memory, so no restart resurrects an unauthorized item — a JetStream redelivery re-enters
`_on_dispatch`. A check at [queue.py](../src/probos/cognitive/queue.py#L333) would double-charge all
three. **Record this reasoning in a comment at the enqueue site**, or a later reader closes the
"gap" and reintroduces the bug this AD exists to avoid.

---

## Section 0 — `MockNATSBus` must be able to witness the transport

Acceptance demands *connected* `request()` / `js_publish()` transports, "explicitly not mocks that
skip the transport". `MockNATSBus` ([nats_bus.py](../src/probos/mesh/nats_bus.py#L1370)) is already a
routing loopback: `request()` ([nats_bus.py](../src/probos/mesh/nats_bus.py#L1586)) invokes the
matching subscriber and captures `respond()`; `js_publish()`
([nats_bus.py](../src/probos/mesh/nats_bus.py#L1621)) delegates to `publish()`
([nats_bus.py](../src/probos/mesh/nats_bus.py#L1524)), which delivers to matching subscribers. Three
fidelity gaps make it unable to witness this fix:

**0a — `term()`/`ack()` are unobservable.** `publish()` constructs
`NATSMessage(subject=full, data=data, headers=headers or {})` at
[nats_bus.py](../src/probos/mesh/nats_bus.py#L1536) with **no `_msg`**, and `NATSMessage.term()`
no-ops when `_msg` is None ([nats_bus.py](../src/probos/mesh/nats_bus.py#L195)). So "term() denied
work rather than acking it" cannot be asserted at all: the mutant `term()` → `ack()` is INERT, not
killed. Give `publish()` a recording stub as `_msg` that appends to `acks` / `terms` / `naks` lists.

**0b — `js_publish()` returns the wrong type.** The mock returns `None`; the real one returns `str`
(`"jetstream"` / `"core_nats"` / `"dropped"`, [nats_bus.py](../src/probos/mesh/nats_bus.py#L875-L880)).
`dispatch_async` branches on `outcome != "dropped"` at
[intent.py](../src/probos/mesh/intent.py#L1265-L1271), so the mock currently yields
`DispatchAdmission(True, route=None)` — a route production can never produce. Return `"jetstream"`.

**0c — the reply budget path is untested on the mock.** `_MockReplyMsg`
([nats_bus.py](../src/probos/mesh/nats_bus.py#L1601)) exposes `respond` only and no `headers`, so
`reply_body_budget` falls back to the wrapper's own copy
([nats_bus.py](../src/probos/mesh/nats_bus.py#L218-L245)). Give it a `headers` attribute carrying the
request's headers, so a budgeted denial (Section 1) can be exercised against a real echo cost.

**Do not extend the existing AD-654a tests as evidence.**
[test_ad654a_async_dispatch.py](../tests/test_ad654a_async_dispatch.py) replaces the transport with
`mock_nats_bus.js_publish = AsyncMock()` (lines 68 and 106) — those are precisely the transport-
skipping mocks acceptance forbids. They stay as they are; they are not proof of anything here.

**Tests (Section 0):** `tests/test_ad1276_mock_transport_fidelity.py`
1. `test_js_publish_reports_the_route_the_real_bus_reports`
2. `test_a_delivered_jetstream_message_can_be_acked_and_the_ack_is_visible`
3. `test_a_delivered_jetstream_message_can_be_termed_and_the_term_is_visible`
4. `test_ack_and_term_are_distinguishable_not_merely_both_recorded`
5. `test_a_request_reply_message_carries_the_requests_headers_for_budgeting`
6. `test_publish_still_delivers_to_every_matching_subscriber` (regression: 19 test files use this bus)

---

## Section 1 — the two `mesh/intent.py` consumer checks

### 1a — the ledger

Add alongside the BF-234 fields at [intent.py](../src/probos/mesh/intent.py#L281-L282):
`_authorized_intents: dict[str, float]`, `_last_authorized_eviction: float`, a
`_AUTHORIZED_LEDGER_WINDOW: float = 300.0` class constant and a `_AUTHORIZED_LEDGER_MAX_ENTRIES: int`
cap. Record on ALLOW inside `_authorize` ([intent.py](../src/probos/mesh/intent.py#L842)). Add
`_authorize_inbound(self, intent, *, entry_point) -> bool` implementing pop-then-evaluate.

Update the SCOPE paragraph of the `_authorize` docstring
([intent.py](../src/probos/mesh/intent.py#L878-L889)), which currently says the consumer side is *not*
covered. Leaving it is the exact BF-754 defect class.

### 1b — `_on_nats_intent` ([intent.py](../src/probos/mesh/intent.py#L530))

Call `_authorize_inbound(intent, entry_point="nats_inbound")` after
`intent = self._deserialize_intent(msg.data)` ([intent.py](../src/probos/mesh/intent.py#L533)) and
**before** `result = await handler(intent)` ([intent.py](../src/probos/mesh/intent.py#L534)).

On deny, respond with a **structured denial envelope** — silence is not an option here. Both the real
and mock `request()` return `None` when nothing responds, and `_nats_send` maps `None` → `None` and
`{"declined": true}` → `None` ([intent.py](../src/probos/mesh/intent.py#L994-L997)). So a denial that
sends nothing is indistinguishable from a decline, and one that raises out of the callback is
indistinguishable from a timeout. Use a distinct key — `{"denied": true, "reason": ..., "entry_point": ...}`.

**Budget it.** This is the fourth reply site on this callback; the other three are budgeted
(`_reply_budget` [intent.py](../src/probos/mesh/intent.py#L1713), `_reply_bytes`
[intent.py](../src/probos/mesh/intent.py#L1733), `_decline_bytes`
[intent.py](../src/probos/mesh/intent.py#L1641), `_smallest_error_bytes`
[intent.py](../src/probos/mesh/intent.py#L1859)). Adding an un-budgeted one re-opens BF-827 exactly.
A denial that will not fit must degrade to the smallest honest form or log that the caller will time
out — never submit an oversized payload the server refuses asynchronously.

### 1c — `_nats_send` converts the envelope back ([intent.py](../src/probos/mesh/intent.py#L973))

Check the `denied` key **before** the `declined` check at
[intent.py](../src/probos/mesh/intent.py#L997). `_nats_send` takes a new keyword-only
`raise_on_denial: bool` threaded from `send()` ([intent.py](../src/probos/mesh/intent.py#L910)) — this
is a signature change on a private method with one call site
([intent.py](../src/probos/mesh/intent.py#L978-L983)). The **default shape stays `None`**, so none of
the 14 `send` seams sees a type it did not already handle. Only a caller that already passed
`raise_on_denial=True` gets `IntentAuthorizationDenied`.

### 1d — `_on_dispatch` ([intent.py](../src/probos/mesh/intent.py#L634))

Place `_authorize_inbound(intent_msg, entry_point="jetstream_inbound")` **after** the BF-234 dedup
gate (which returns at [intent.py](../src/probos/mesh/intent.py#L706) having already acked, so a
suppressed duplicate needs no charge) and **before** `self._record_response(...)` at
[intent.py](../src/probos/mesh/intent.py#L695-L699) — that is ward-room state a denied intent must
not mutate. This precedes both the enqueue at
[intent.py](../src/probos/mesh/intent.py#L709) and the direct handler at
[intent.py](../src/probos/mesh/intent.py#L718), covering rows 2 and 3 in one check.

On deny: `await msg.term()`, never `ack()`. `term()` is the established shape on this callback —
[intent.py](../src/probos/mesh/intent.py#L651) (BF-296 shutdown),
[intent.py](../src/probos/mesh/intent.py#L711) (queue rejection),
[intent.py](../src/probos/mesh/intent.py#L726) (handler error).

**Tests (Section 1):** `tests/test_ad1276_inbound_authorization.py`

*Enforcement — connected transport, no transport mocking*
1. `test_a_denied_intent_never_reaches_the_handler_over_request_reply`
2. `test_a_denied_intent_never_reaches_the_handler_over_jetstream`
3. `test_a_denied_intent_is_never_enqueued_on_the_cognitive_queue`
4. `test_an_allowed_intent_still_reaches_the_handler_on_both_transports` (the benign control — a fix
   that denies everything passes 1–3 and destroys the ship)

*Exactly-once, counted across a full round trip*
5. `test_a_local_send_over_a_connected_bus_charges_the_hook_once`
6. `test_a_local_dispatch_over_a_connected_bus_charges_the_hook_once`
7. `test_an_intent_with_no_producer_record_is_charged_once_at_the_consumer` (the cross-node case)
8. `test_a_jetstream_redelivery_of_the_same_id_is_charged_again_not_waved_through`
9. `test_an_empty_intent_id_is_never_recorded_and_is_always_evaluated`

*Denial shape*
10. `test_a_remote_denial_surfaces_as_intent_authorization_denied_not_a_timeout`
11. `test_a_remote_denial_is_distinguishable_from_a_decline` (both would be `None` without the key)
12. `test_the_default_send_shape_for_a_remote_denial_is_still_none`
13. `test_a_denial_envelope_that_cannot_fit_the_budget_is_not_submitted` (BF-827 parity)
14. `test_a_denied_jetstream_message_is_termed_and_not_acked`

---

## Section 2 — the inbound-federation denial reaches the peer

`_on_intent_message` ([nats_transport.py](../src/probos/federation/nats_transport.py#L253)) has **no
`try`/`except`** around `await self._inbound_handler(message)`
([nats_transport.py](../src/probos/federation/nats_transport.py#L261)). Anything raising out of
`FederationBridge.handle_inbound` ([bridge.py](../src/probos/federation/bridge.py#L1416)) escapes into
the NATS subscription wrapper and no `intent_response` is ever sent — the peer waits out its timeout.

**State the current shape accurately in the code comment.** Today the broadcast path
([bridge.py](../src/probos/federation/bridge.py#L1631)) uses the default denial shape and returns
`[]`, so a denial presents to the peer as an empty result set, *not* as a timeout. The timeout is what
happens the moment anything on that path raises. Fix both: return a structured denial in the
`intent_response` payload rather than an empty `results` list, and give
`_on_intent_message` a bounded handler so an escaping exception becomes a reported failure instead of
silence. Use the **same envelope shape** as Section 1 — one shape, two transports.

The directed path already degrades honestly via `_directed_error`
([bridge.py](../src/probos/federation/bridge.py#L1896-L1915)); do not change it.

**Tests (Section 2):** `tests/test_ad1276_federation_denial_reaches_the_peer.py`
1. `test_an_inbound_intent_denied_by_policy_returns_a_denial_not_an_empty_result_set`
2. `test_an_empty_result_set_from_no_subscriber_is_still_reported_as_empty` (the two must stay
   distinguishable — this is the control that stops the fix from relabelling every empty response)
3. `test_an_exception_from_handle_inbound_still_produces_a_response`
4. `test_the_peer_can_tell_a_denial_from_a_transport_failure`
5. `test_an_allowed_inbound_intent_is_unchanged_byte_for_byte`
6. `test_the_directed_federation_path_is_not_altered`

---

## Section 3 — the Yeoman digest task retrieves its own exception

[yeoman.py](../src/probos/cognitive/yeoman.py#L482-L487) creates a background broadcast task whose
only done-callback is `self._pending_dispatch_tasks.discard`, so the task's exception is never
retrieved.

**The issue's stated cause does not reproduce as written.** #1253 says "a denial becomes an
unretrieved task exception". It does not: `broadcast`'s default denial shape is `[]`, not a raise
([intent.py](../src/probos/mesh/intent.py#L1043-L1046)). Do **not** write a test that pins the
fabricated premise. The real defect is broader and simpler — *any* exception from that broadcast is
lost, silently. Add a done-callback that calls `task.exception()` and logs it with context, keeping
the `discard`.

**Tests (Section 3):** `tests/test_ad1276_yeoman_digest_task_reports.py`
1. `test_an_exception_in_the_digest_broadcast_is_logged_not_swallowed`
2. `test_the_task_is_still_discarded_from_the_pending_set`
3. `test_a_cancelled_digest_task_does_not_log_an_error` (cancellation is lifecycle control)
4. `test_a_successful_digest_broadcast_logs_nothing`
5. `test_a_policy_denial_returns_an_empty_list_and_is_not_reported_as_an_exception` (pins the actual
   shape, so the next reader does not re-adopt the issue's wrong premise)
6. `test_the_no_running_loop_fallback_path_is_unchanged`

---

## Mutation coverage (required by acceptance #4)

Run the **unmutated baseline first** and abort if it is already red or if every mutant looks killed.
Mutate **in place** with a `.mutbak` sibling, restore in `finally`. **Single-line anchors only** —
this is a CRLF tree and a multi-line anchor silently matches nothing. An anchor that is not found is
an **INERT** mutant, not a killed one; report it as such.

| ID | Mutation | Must be killed by |
|---|---|---|
| M1 | Move the `_on_nats_intent` check below `result = await handler(intent)` | 1.1 |
| M2 | Move the `_on_dispatch` check below `queue.enqueue(...)` | 1.3 |
| M3 | Move the `_on_dispatch` check below `await handler(intent_msg)` | 1.2 |
| M4 | `msg.term()` → `msg.ack()` on the JetStream denial | 1.14 |
| M5 | Ledger `pop` → `get` (peek) | 1.8 |
| M6 | Delete the empty-`intent.id` guard | 1.9 |
| M7 | Record into the ledger unconditionally, not only on ALLOW | 1.7 |
| M8 | `_nats_send` checks `declined` before `denied` | 1.11 |

M4 is INERT without Section 0a. If a mutant survives, first check whether the **mutant** is wrong —
whether it actually reaches the behaviour it claims to break — before concluding the test is weak.

---

## What this does NOT change

- **The AD-654c `Dispatcher`.** Already fixed in `f60ba750`. Do not touch
  [dispatcher.py](../src/probos/activation/dispatcher.py) or
  [test_bf789_dispatcher_authorization.py](../tests/test_bf789_dispatcher_authorization.py).
- **`cognitive/queue.py`.** No authorization check inside the queue — see *Decision*. A comment at the
  enqueue site only.
- **The wire format.** No new field in `_serialize_intent` / `_deserialize_intent`. BF-742's drift
  guard must keep passing untouched.
- **The producer-side checks** at [intent.py](../src/probos/mesh/intent.py#L943),
  [intent.py](../src/probos/mesh/intent.py#L1043) and
  [intent.py](../src/probos/mesh/intent.py#L1256). They stay exactly where they are.
- **The default denial shapes.** `send` → `None`, `broadcast` → `[]`, `dispatch_async` →
  `DispatchAdmission(False, reason="denied")`. No seam sees a new type.
- **BF-790's reporting opt-ins** (#1254) — `/api/agent/{id}/chat`, `/api/chat` inline-callsign, the
  proactive vision observer, the multi-mention fan-out refusal. That is the *reporting* half; this is
  the *enforcement* half. Do not re-derive or re-touch them.
- **BF-813 (#1277)** and the unconfirmed AST-census callsites. In particular
  [mcp_server.py](../src/probos/federation/mcp_server.py#L262) renders a policy denial to an inbound
  MCP peer as `"no agent handled tool"` — real, on a consumer-side path, and **out of scope here**.
  File it against #1277 rather than widening this AD.
- **The directed federation path** ([bridge.py](../src/probos/federation/bridge.py#L1896)).
- **`SignalManager`, Hebbian routing, trust, consensus.** Untouched.

---

## Closure

`#1253` closes only when Sections 0–3 are all green. Section 1 alone satisfies acceptance items 1, 2
and 4 and closes rows 1–3 of the issue's table (row 4 is already closed), but **not** item 3 — "a
remote denial reaches the originating caller as `IntentAuthorizationDenied`" — for a *federated*
caller, which is Section 2. Sections 2 and 3 are named in the issue's "Also worth fixing here".

Section 1 is nonetheless a coherent shippable slice: enforcement on all three bus paths, with Section
0 as its hard prerequisite. If the wave has to stop, stop after Section 1 and say plainly on the issue
that it is not closed.

---

## Tracking

- `PROGRESS.md` — AD-1276 entry, one line, with the enforcement/reporting split named.
- `docs/development/roadmap.md` — Bug Tracker row for BF-789 moving to CLOSED on full closure only.
- `DECISIONS.md` — record the ledger decision: **why the marker is process-local and never on the
  wire** (a peer-settable flag is a remote policy bypass), **why pop and not peek** (JetStream
  redelivery), and **why `cognitive/queue.py` gets no check** (all three enqueue paths are already
  guarded; a fourth check double-charges every one).
- Update the issue body of #1253 to strike the `Dispatcher` row as already closed.

---

## Acceptance criteria

1. A denying hook stops the handler on all three remaining consumer-side paths, proven with
   **connected** `MockNATSBus.request()` / `js_publish()` round trips and a real
   `AgentCognitiveQueue` — not with `AsyncMock` substitutions for the transport.
2. Hook invocations are **counted across a full round trip** and equal 1 for a loopback send, 1 for a
   loopback dispatch, and 1 for an intent arriving with no producer record.
3. A remote denial reaches the originating caller as `IntentAuthorizationDenied` when it asked for it,
   and as the pre-existing `None` when it did not — never as a timeout, never as a decline.
4. All eight mutants in the table are **killed** (not INERT, not timed out — a timeout is INVALID,
   never SURVIVED).
5. A benign control test exists for every enforcement test: the allowed path must still work.
6. No new field on the wire. BF-742's serialization drift guard passes unchanged.
7. Focused gate green:
   `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1276_*.py tests/test_bf789_dispatcher_authorization.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf234_ward_room_dispatch_dedup.py tests/test_bf296_intent_bus_close.py tests/test_bf805_reply_metadata_degrade.py tests/test_bf827_decline_is_budgeted.py tests/test_intent.py tests/test_federation_nats.py -q -p no:randomly`
8. Adversarial review on the staged diff with a **different model than the author**, per the standing
   order. Point it at the exactly-once claim and at the ledger eviction window specifically.
9. Full repository gate green once, after the wave is frozen.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-26)

```
Select-String -Path src/probos/mesh/intent.py -Pattern 'authorize'
  943:  if not self._authorize(          # send
  1043: if not self._authorize(          # broadcast
  1256: if not self._authorize(          # dispatch_async

ABSENCE CLAIM: no authorization on the consumer-side callbacks
RUN:   Select-String -Path src/probos/mesh/intent.py -Pattern 'authorize' |
         Where-Object { $_.LineNumber -ge 526 -and $_.LineNumber -le 780 } | Measure-Object
FOUND: 0
HOLDS: yes -- lines 526-780 span _nats_subscribe_agent and _js_subscribe_agent_dispatch entire

Select-String -Path src/probos/mesh/intent.py
  281:  self._seen_intents: dict[str, float] = {}
  282:  self._last_seen_eviction: float = time.monotonic()
  530:  async def _on_nats_intent(msg: Any) -> None:
  533:      intent = self._deserialize_intent(msg.data)
  534:      result = await handler(intent)
  634:  async def _on_dispatch(msg: Any) -> None:
  658:      intent_msg = self._deserialize_intent(msg.data)
  709:      accepted = queue.enqueue(intent_msg, priority, js_msg=msg)
  718:      await handler(intent_msg)
  973:  async def _nats_send(self, intent: IntentMessage) -> IntentResult | None:
  994:      if reply is None:
  997:      if isinstance(data, dict) and data.get("declined"):
  1544: _WARD_ROOM_DISPATCH_DEDUP_WINDOW: float = 300.0
  1547: if not intent_id: return False          # the empty-id guard to mirror
  1641: def _decline_bytes(limit: int) -> bytes | None:
  1713: def _reply_budget(self, msg: Any) -> int:
  1733: def _reply_bytes(
  1859: def _smallest_error_bytes(

Select-String -Path src/probos/mesh/nats_bus.py
  195:  async def term(self) -> None:        # no-ops when _msg is None
  875:  async def js_publish(...) -> str:    # real: returns a route string
  1370: class MockNATSBus:
  1524: async def publish(                   # mock fan-out
  1536:     msg = NATSMessage(subject=full, data=data, headers=headers or {})   # no _msg
  1586: async def request(                   # mock: routes and captures respond()
  1601:     class _MockReplyMsg:             # respond only, no headers
  1621: async def js_publish(                # mock: delegates to publish(), returns None

Select-String -Path src/probos/activation/dispatcher.py
  135:  if not authorize_intent(intent, entry_point="dispatcher_queue")[0]:
  198:  if not authorize_intent(             # dispatcher_direct
git log --oneline -- src/probos/activation/dispatcher.py
  f60ba750 BF-789: the Dispatcher authorizes what nothing else does

Select-String -Path src/probos/cognitive/queue.py
  108:  def enqueue(
  333:  await self._handler(item.intent)

Select-String -Path src/probos/federation/nats_transport.py
  253:  async def _on_intent_message(self, nats_msg: Any) -> None:   # no try/except
  261:      await self._inbound_handler(message)
Select-String -Path src/probos/federation/bridge.py
  1416: async def handle_inbound(self, message: FederationMessage) -> None:
  1631: local_results = await self._intent_bus.broadcast(intent, federated=False)
  1896: local_result = await self._intent_bus.send(intent)            # already degrades

Select-String -Path src/probos/cognitive/yeoman.py
  482:  task = loop.create_task(
  483:      runtime.intent_bus.broadcast(dm),
  487:  task.add_done_callback(self._pending_dispatch_tasks.discard)   # exception never retrieved

Select-String -Path tests/test_ad654a_async_dispatch.py
  68:   mock_nats_bus.js_publish = AsyncMock()                # transport-skipping
  106:  mock_nats_bus.js_publish = AsyncMock(side_effect=...)  # transport-skipping

Get-ChildItem tests | Select-String 'nats-server|NATS_TEST_URL|nats\.connect\('
  (no real NATS server fixture exists anywhere in tests/)
```
