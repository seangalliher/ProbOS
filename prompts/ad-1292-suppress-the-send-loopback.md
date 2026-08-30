# AD-1292 — Suppress the `send()` loopback; keep the durable dispatch publish

**Status:** Ready to build
**Issue:** #1330 (AD-1276 follow-up)
**Depends on:** AD-1276 (shipped), BF-815 (shipped)
**Files:** `src/probos/mesh/intent.py`, `tests/test_ad1276_inbound_authorization.py` (one assertion), new `tests/test_ad1292_send_loopback_suppression.py`
**Estimated tests:** 9 new, 1 modified
**AD ceiling when drafted:** AD-1291 (three sources, see footer)

One line: `send()` stops publishing to the wire when the target is subscribed on this node, so one logical delivery charges the AD-698 hook once. `dispatch_async()` is deliberately left alone, because its publish is a durability mechanism rather than a transport hop.

---

## 1. The premise, verified by execution

Issue #1330 says a loopback charges the pre-intent-auth hook twice. That was confirmed by running, not by reading, and the control discriminates.

```
tests/test_ad1276_inbound_authorization.py::TestALoopbackIsEvaluatedOnBothSides
tests/test_ad1276_inbound_authorization.py::TestThereIsNoSuppressionLedger
  -> 8 passed in 7.24s          (HEAD c75428bb)
```

The tests prove double evaluation but not its cause, so a connected/disconnected control was run against the same handler and the same hook:

| bus | `handler` invocations | AD-698 hook evaluations | delivered? |
|---|---|---|---|
| CONNECTED (loopback) | 1 | **2** | yes (`result is not None`) |
| DISCONNECTED (control) | 1 | **1** | yes (`result is not None`) |

The control still delivered, so it discriminates: the count differs only in the presence of the wire. **The loopback is the cause.** One logical delivery, two evaluations.

Mechanism, confirmed in source: `subscribe()` (intent.py:452) inserts the handler into `self._subscribers` **and** spawns NATS + JetStream subscriptions on the same node (intent.py:466-483). `send()` then publishes to `intent.{target}` (intent.py:1119), which this node's own `_on_nats_intent` receives and re-authorizes via `_authorize_inbound` (intent.py:563-568).

---

## 2. Decision

**Adopt the Captain's direction for `send()`. Refute it for `dispatch_async()`, on evidence.**

### 2a. `send()` — suppress. Safe.

`send()` uses **core NATS request/reply** (`self._nats_bus.request`, intent.py:1122). Core request/reply is not persisted: if this process dies mid-flight, the caller's `await` dies with it and nothing is redelivered. So the wire hop carries **no durability** for a local target — it is pure overhead plus a second hook charge.

### 2b. `dispatch_async()` — do NOT suppress. The publish is crash recovery.

This is the half of the direction that does not survive contact with the code. The dispatch consumer is created as:

```
intent.py:812   sub = await self._nats_bus.js_subscribe(
intent.py:815       durable=durable_name,
intent.py:816       stream="INTENT_DISPATCH",
intent.py:817       max_ack_pending=1,
intent.py:818       ack_wait=300,
intent.py:819       manual_ack=True,
intent.py:820       max_deliver=10,
```

backed by a real stream (`startup/nats.py:70-75`, `recreate_stream("INTENT_DISPATCH", ["intent.dispatch.>"], max_msgs=10000, max_age=300)`).

A dispatch published to JetStream is **persisted for 5 minutes, manually acked, and redelivered up to 10 times** — it survives a process crash and is re-delivered on restart. BF-234's dedup gate exists precisely *because* JetStream redelivers.

The local fallback has none of that. It is either an in-memory cognitive queue — the source's own comment at intent.py:1500 reads `js_msg=None — no JetStream backing for fallback path` — or a bare `asyncio.create_task` (intent.py:1485-1497).

So suppressing the dispatch publish would replace durable, crash-surviving, redelivered work with an in-memory task. **That is message loss on crash**, traded for a rate limiter's accounting. It violates the Captain's own rule — *degrade toward delivering, never toward dropping* — so it is refused here rather than built.

The double charge on `dispatch_async` therefore **remains, deliberately**, and gets a test pinning it with the reason.

### 2c. Why this is not a ledger

The change adds **no state to the bus**. It is a route-selection decision computed inside `send()` from a dict the method is about to read anyway. There is no record to mint, nothing to spend, nothing to key, and therefore none of the three reproduced bypasses has a surface to reappear on. `TestThereIsNoSuppressionLedger` must remain **passing and unmodified** — see §6.

---

## 3. Is "the target is subscribed locally" a SAFE test?

The issue warns that `has_subscriber` is not equivalent to dispatch-consumer readiness. That warning was made about the **ledger** design, where `has_subscriber` was used to justify *waiving* an evaluation. Here it is used for *route selection*, and for route selection it is not an approximation — it is the same predicate the destination path already uses.

**What the producer can actually know at publish time**, enumerated:

| Fact | Available? | Where |
|---|---|---|
| `self._subscribers[target]` exists | yes, synchronously | intent.py:963 `has_subscriber`, intent.py:1087 fallback |
| the handler object itself | yes | `self._subscribers.get(target)` |
| a NATS subscription task was spawned | yes, but it may still be pending | intent.py:466-474 |
| the remote consumer is *ready* | **no** | task is async |
| another node holds this agent | not applicable | subjects are per-node prefixed (`_full_subject`, nats_bus.py:476/1533) |

Three properties make the test safe:

1. **It is the identical predicate.** `send()`'s existing local path reads `self._subscribers.get(intent.target_agent_id)` (intent.py:1087) — the same dict, the same key that `has_subscriber` queries. Measured: `has_subscriber('agent-1')` and `_subscribers.get('agent-1') is not None` agree on both present (`True/True`) and absent (`False/False`). A True answer cannot be followed by "no handler found", because the handler *is* the answer.

2. **The error direction is safe.** `subscribe()` sets `_subscribers[agent_id]` **synchronously** (intent.py:452) and creates wire subscriptions **asynchronously** via `create_task` (intent.py:468). Measured immediately after `subscribe()`: `has_subscriber=True` while `wire_sub_tasks_still_pending=1`. So the predicate becomes true **earlier** than wire readiness, never later. In that window local delivery works and the *wire* is the path that might not be listening. Suppressing is strictly safer there.

3. **There is precedent in production.** `federation/bridge.py:1894` already uses `has_subscriber(target_agent_id)` to decide whether a federated intent has a deliverable local target, answering `federation_target_not_found` when it does not. The predicate is already trusted for routing.

**Can local delivery silently fail where the wire would have succeeded? No — provided the handler reference is captured once.** Capture `handler = self._subscribers.get(target)` and use *that* object. A concurrent `unsubscribe` cannot then strand the message, which is exactly the semantics the wire path already has: `_on_nats_intent` is a closure over its `handler` argument (intent.py:557, 586) and keeps delivering after the dict entry is gone. Do not re-read the dict after the check.

**Answer: the risk of converting an accounting nuisance into message loss does not exist for `send()`, because the suppression predicate and the delivery lookup are the same read.**

---

## 4. The one real divergence, and the fallback rule

### 4a. Envelope divergence — must be closed FIRST

The wire and local paths are **not** currently interchangeable. Measured, same handler, connected vs disconnected:

| handler behaviour | wire path returns | local path returns | parity |
|---|---|---|---|
| returns a result | `IntentResult(success=True, result='ok', confidence=0.75)` | identical | **yes** |
| returns `None` (declines) | `None` | `None` | **yes** |
| raises `ValueError` | `IntentResult(success=False, result=None, error='handler exploded', confidence=0.0)` | **raises `ValueError` into the caller** | **NO** |

This is pre-existing, and #1330 does not mention it. It matters here because suppression moves traffic that takes the wire today onto the local path. Per the `_authorize` docstring (intent.py:995-1002), 14 `send` seams sit inside broad `except Exception` blocks — a handler crash would start being rendered as whatever those blocks report, which *relocates* a defect instead of fixing one. **Close the divergence in the same change**, by giving both local call sites the wire path's envelope.

No test depends on the current raising behaviour: the only `pytest.raises` near a `.send(` are for the opt-in `IntentAuthorizationDenied` (`tests/test_bf771_intent_authorization.py:256, 283, 317`).

### 4b. Fallback rule — suppression is an ATTEMPT, never a commitment

> **If the local route is not certainly available, do not suppress — publish exactly as today. If a local handler is held, deliver to it and never let a failure become a drop.**

Concretely:

- `handler is None` **and** connected → **do not suppress**; take `_nats_send` unchanged.
- `handler is None` **and** disconnected → return `None`, unchanged.
- `handler is not None` → deliver locally, and convert every non-cancellation failure into the wire path's envelope. Timeout → the existing "Agent did not respond in time." result. Exception → `success=False, error=str(exc), confidence=0.0`.
- `asyncio.CancelledError` inherits from `BaseException`, so `except Exception` does not catch it; cancellation must keep propagating. Do not widen to `BaseException`.

There is no branch that can reach "suppressed, and then not delivered".

---

## 5. Implementation

### Section 1 — route selection in `send()`

`src/probos/mesh/intent.py`

```
===SEARCH===
        _send_start = time.monotonic()  # AD-470: timing
        try:
            # NATS path when connected
            if self._nats_bus and self._nats_bus.connected:
                return await self._nats_send(intent, raise_on_denial=raise_on_denial)

            # Direct-call fallback when NATS disconnected
            handler = self._subscribers.get(intent.target_agent_id)
            if handler is None:
                return None
            try:
                result = await asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)
                return result
            except asyncio.TimeoutError:
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=intent.target_agent_id,
                    success=False,
                    error="Agent did not respond in time.",
                    confidence=0.0,
                )
        finally:
===REPLACE===
        _send_start = time.monotonic()  # AD-470: timing
        try:
            # AD-1292: read ONCE and deliver to this object. Re-reading after
            # the check would let a concurrent unsubscribe strand a message the
            # wire would have delivered -- `_on_nats_intent` closes over its
            # handler and keeps delivering after the dict entry is gone, so
            # holding the reference is parity, not a leak.
            handler = self._subscribers.get(intent.target_agent_id)

            # AD-1292: suppress the loopback. A locally-subscribed agent also
            # subscribes to its own `intent.{id}` subject, so publishing to a
            # LOCAL target re-enters this process and `_authorize_inbound`
            # charges the AD-698 hook a second time for one logical delivery.
            # Suppression is an ATTEMPT: with no local handler the wire path
            # runs exactly as before, so this can never turn into a drop.
            if handler is None and self._nats_bus and self._nats_bus.connected:
                return await self._nats_send(intent, raise_on_denial=raise_on_denial)

            if handler is None:
                return None

            return await self._deliver_to_local_handler(intent, handler)
        finally:
===END REPLACE===
```

### Section 2 — the shared local-delivery helper

Insert immediately **after** `send()`'s `finally` block and **before** `async def _nats_send(` (intent.py:1105).

```python
    async def _deliver_to_local_handler(
        self,
        intent: IntentMessage,
        handler: IntentHandler,
    ) -> IntentResult | None:
        """Invoke a local handler with the WIRE path's result envelope (AD-1292).

        ``send``'s callers must not be able to tell which route ran, and before
        AD-1292 they could. Measured, same handler raising ``ValueError``,
        connected versus disconnected:

            wire  -> IntentResult(success=False, error='handler exploded',
                                  confidence=0.0)
            local -> ValueError raised into send()'s caller

        Suppressing the loopback moves traffic that used to take the wire onto
        this path, so that divergence had to close first: 14 ``send`` seams sit
        inside broad ``except Exception`` blocks, which would have rendered a
        handler crash as whatever each of those blocks reports.

        ``asyncio.CancelledError`` derives from ``BaseException``, so it is not
        caught here and shutdown still propagates. Do not widen this.
        """
        try:
            return await asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)
        except asyncio.TimeoutError:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "",
                success=False,
                error="Agent did not respond in time.",
                confidence=0.0,
            )
        except Exception as exc:
            logger.warning(
                "AD-1292: local handler for %s raised %s while delivering %s; "
                "returning the wire path's error envelope so the caller cannot "
                "tell the two routes apart",
                (intent.target_agent_id or "")[:12],
                type(exc).__name__,
                intent.intent,
                exc_info=True,
            )
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "",
                success=False,
                error=str(exc),
                confidence=0.0,
            )
```

### Section 3 — two stale comments that describe the removed ledger

Both are actively misleading now: they narrate a "ledger pop" that no longer exists, and the first is orphaned above an unrelated field.

**3a** — intent.py:285, an orphaned line with no member under it:

```
===SEARCH===
        # AD-1276: intent ids THIS PROCESS already charged the AD-698 hook for.
        # BF-234: Injected event emitter for duplicate-suppressed telemetry.
===REPLACE===
        # BF-234: Injected event emitter for duplicate-suppressed telemetry.
===END REPLACE===
```

**3b** — intent.py:563, inside `_on_nats_intent`:

```
===SEARCH===
                # AD-1276: this node's policy applies to work crossing THIS
                # node, and an intent off the wire has not passed the producer
                # gate. A loopback send() already charged the hook, so the
                # ledger pop makes the second look free.
===REPLACE===
                # AD-1276: this node's policy applies to work crossing THIS
                # node, and an intent off the wire has not passed the producer
                # gate. AD-1292: a local `send` no longer publishes here, so
                # what reaches this callback is a genuine peer message rather
                # than this node's own loopback.
===END REPLACE===
```

### Section 4 — `_authorize_inbound`'s docstring states an accepted cost that is now half true

Update **only** the paragraph beginning `The accepted cost, stated rather than hidden:` (intent.py, inside `_authorize_inbound`) to:

```
        The accepted cost, stated rather than hidden: a `dispatch_async`
        loopback still charges the hook twice. AD-1292 removed the `send`
        half by not publishing to the wire when the target is subscribed
        here, but the dispatch publish is deliberately kept -- it is a
        DURABLE JetStream delivery (`durable=`, `manual_ack=True`,
        `max_deliver=10`, 5-minute retention), so suppressing it would trade
        crash-recovery redelivery for an in-memory task. Over-charging a rate
        limiter is a smaller harm than losing work on restart, and neither
        ever lets an unauthorized intent through. Restoring suppression there
        needs a delivery identity the peer cannot influence and that names the
        channel; see #1330 before adding one back.
```

Leave the rest of that docstring — especially the three-bypass history and `ALWAYS evaluates.` — **exactly as it is**.

---

## 6. Tests

### 6a. Modify exactly one existing assertion

`tests/test_ad1276_inbound_authorization.py:254`, in `TestALoopbackIsEvaluatedOnBothSides::test_a_loopback_send_charges_the_hook_on_both_sides`. It pins the cost AD-1292 removes, so it must change — and it must change by *editing the assertion with the reason inline*, never by deletion. Rename the method to `test_a_loopback_send_is_charged_once_now_that_it_does_not_publish` and assert:

```python
        assert hook.calls == 1, (
            "AD-1292: `send` no longer publishes to the wire when the target "
            "is subscribed on this node, so one logical delivery is one "
            "evaluation. A count of 2 means the loopback is back; a count of "
            "0 means a suppression LEDGER is back -- read "
            "TestThereIsNoSuppressionLedger before changing this"
        )
```

Update the class docstring's first paragraph to say the dispatch path is the one still evaluated twice, and why (durability). **Do not touch** `test_a_loopback_dispatch_charges_the_hook_on_both_sides`, `test_a_redelivered_dispatch_is_evaluated_every_time`, or `test_a_denied_inbound_is_denied_however_many_times_it_arrives`.

### 6b. `TestThereIsNoSuppressionLedger` — do not modify, do not touch

It must pass **unchanged**. If it cannot, the design has drifted back to a ledger; stop and escalate rather than editing it.

### 6c. New file `tests/test_ad1292_send_loopback_suppression.py`

Reuse the AD-1276 harness shape (`MockNATSBus`, `_settle`, the autouse hook-clearing fixture). Drive a **connected** `MockNATSBus` throughout — never an `AsyncMock` transport, for the reason stated at the top of the AD-1276 file. Every test asserts its own premise (that the handler actually ran) before asserting a count.

1. `test_a_local_send_consults_the_hook_exactly_once` — **end-to-end, spans the seam.** Connected bus, locally subscribed agent, counting hook. `send()` → assert `result is not None` (premise: delivery happened), `handler.calls == ["…"]` (exactly one delivery), `hook.calls == 1` (exactly one evaluation). **This must FAIL at HEAD with `hook.calls == 2`** — run it before the source edit and record that it fails.
2. `test_a_send_to_a_target_that_is_not_local_still_crosses_the_wire` — the negative control that stops over-suppression. Connected bus, target **not** in `_subscribers`; assert the mock recorded a request on `intent.{target}`. Without this, test 1 passes just as well if `send()` stopped publishing entirely.
3. `test_a_local_send_returns_the_result_the_handler_produced` — envelope parity for the success case: `success`, `result`, `confidence`, `agent_id`, `intent_id`.
4. `test_a_declining_handler_still_yields_None` — parity for `return None`.
5. `test_a_handler_exception_becomes_an_error_envelope_not_a_raise` — handler raises `ValueError("boom")`; assert `send()` returns `IntentResult(success=False, error="boom", confidence=0.0)` and does not raise.
6. `test_cancellation_still_propagates` — handler raises `asyncio.CancelledError`; assert it escapes `send()` rather than being converted to an envelope.
7. `test_a_concurrent_unsubscribe_does_not_strand_the_send` — handler awaits an event; unsubscribe the agent after `send()` is in flight; release; assert the result still arrives. Pins the capture-once rule.
8. `test_a_dispatch_loopback_is_still_evaluated_twice` — pins the deliberate non-change, with the durability reason in the assertion message so the next reader does not "finish the job".
9. `test_a_denied_local_send_is_denied_exactly_once` — denying hook; assert `send()` returns `None`, the handler never ran, and `hook.calls == 1`. Enforcement is unchanged; only the duplicate is gone.

---

## 7. Consumer that must accept the change

**Named consumer: `IntentBus.send`'s 14 callers**, and specifically any that distinguishes an error envelope from a raised exception. The seam that must hold is *route selection is invisible to the caller*: before this change a connected local `send` returned an envelope on handler failure and a disconnected one raised; after it, both return the envelope.

The **stateful AD-698 hook** is the consumer whose observable behaviour changes on purpose — it is charged once per logical `send` instead of twice.

The end-to-end path a test spans (test 1): **caller → `send()` → route selection → local handler → envelope**, asserting the hook is consulted exactly once and the handler runs exactly once for one call. Test 2 spans the other branch: **caller → `send()` → route selection → wire publish**, asserting the wire is still used when the target is not local.

---

## 8. What this does NOT change

- `dispatch_async()` — no edit at all. Its double charge stays, on the durability grounds in §2b.
- `broadcast()`, `publish()`, the AD-654b cognitive queue, the AD-654c `Dispatcher`.
- `_authorize` / `_authorize_inbound` logic. Both still **always** evaluate. Nothing is waived anywhere.
- The AD-698 hook contract. No new parameter, no signature change.
- The BF-234 dedup gate, BF-815 admission shapes, BF-827 reply budgeting.
- Federation. `bridge.py` is untouched; it is cited only as precedent.
- **Explicitly not built:** a channel-scoped delivery identity, and a `stage=` discriminator on the hook contract that would let a stateful hook count only producer evaluations. The latter is the most promising future answer for `dispatch_async` because it adds no bus state, but it changes a public extension point and belongs in its own AD. Record it on #1330; do not build it here.

---

## 9. Constraints for the builder

- **Modify only** `src/probos/mesh/intent.py`, `tests/test_ad1276_inbound_authorization.py` (the one assertion plus its class docstring), and the new test file.
- **Never touch** `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md`.
- These carry another session's in-flight work — do not edit or read as truth: `cognitive_agent.py`, `agentic_dispatch.py`, `continue_or_ask.py`, `repair_verification.py`, `fault_report.py`, `tools/browser/url_route_guard.py`. **This AD needs none of them**, verified: `git status --short -- src/probos/mesh/intent.py tests/test_ad1276_inbound_authorization.py` is empty. Work can start now.
- Do not "also fix" the `dispatch_async` double charge. That is the refuted half; §2b is the reason.

### Gating — the tree cannot run the full suite in place

`src/probos/tools/browser/session.py` imports `RedirectEscalation`, which the in-flight work removed from `url_route_guard.py`, breaking collection for ~423 tests. Confirmed on the affected cluster at HEAD: **213 passed, 1 failed**, the single failure being `test_bf771_intent_authorization.py::test_a_denial_is_403_through_the_real_app` with `ImportError: cannot import name 'RedirectEscalation'`.

Gate in a **linked worktree**, never by stashing the foreign work:

```powershell
git worktree add d:\probos-gate-1292 HEAD
git diff > d:\wip-foreign-1292.patch        # staged + unstaged foreign work
cd d:\probos-gate-1292
git apply d:\wip-foreign-1292.patch          # optional; omit to gate on clean HEAD + your change
$env:PYTHONPATH = 'd:\probos-gate-1292\src'  # shadows the editable install
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

Known worktree artefact: **3 `test_phantom_api_precheck_*` tests fail in a linked worktree and pass in the main tree** — they shell out to repo-relative scripts. Verify that is the failure mode, then **count them as passes**.

Run the broad gate **synchronously, with no timeout**. It takes roughly 15–19 minutes and sits at `[ 99%]` for several of them before printing the summary; that is normal, not a hang.

Focused gate for the slice:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1292_send_loopback_suppression.py `
  tests/test_ad1276_inbound_authorization.py tests/test_bf771_intent_authorization.py `
  tests/test_bf815_dispatch_admission.py tests/test_bf742_wire_carries_every_field.py `
  tests/test_bf827_decline_is_budgeted.py tests/test_ad637z_nats_cleanup.py `
  tests/test_ad654a_async_dispatch.py tests/test_intent.py -q -p no:randomly
```

---

## 10. Acceptance criteria

- [ ] `test_a_local_send_consults_the_hook_exactly_once` is confirmed **failing at HEAD** (`hook.calls == 2`) before the source edit, and passing after. A test that never failed proves nothing.
- [ ] `TestThereIsNoSuppressionLedger` passes **unmodified**. No new attribute on `IntentBus`; `IntentBus(SignalManager())` still has no ledger-shaped member.
- [ ] `test_a_send_to_a_target_that_is_not_local_still_crosses_the_wire` passes — suppression did not become "never publish".
- [ ] A handler exception yields an envelope on **both** local routes; `asyncio.CancelledError` still propagates.
- [ ] `dispatch_async` is byte-unchanged, and its loopback still charges twice.
- [ ] Focused gate green; broad gate green in a linked worktree, with only the 3 known `test_phantom_api_precheck_*` worktree artefacts failing.
- [ ] Adversarial `Diff Reviewer` run on the staged diff with a **different model than the author**, findings addressed before commit. Point it at: route selection when `handler is None`, the capture-once rule, envelope parity, and whether anything it can reach makes the local path drop a message the wire would have delivered.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- [ ] #1330 updated: `send` half fixed by AD-1292; dispatch half closed as **won't fix, with reason**; the `stage=` discriminator recorded as the open future option.

---

## Verified Against Codebase (2026-08-29, HEAD c75428bb)

```
git log --oneline -1
  c75428bb (HEAD -> main, origin/main) AD-1291 / BF-858 (#1328): one device, one owner

git status --short -- src/probos/mesh/intent.py tests/test_ad1276_inbound_authorization.py
  (empty -- both targets clean of the foreign in-flight work)

rg -n "def has_subscriber" src/probos/mesh/intent.py
  963:    def has_subscriber(self, agent_id: str) -> bool:

rg -n "_subscribers.get" src/probos/mesh/intent.py
  1087:            handler = self._subscribers.get(intent.target_agent_id)   # send fallback
  1471:        handler = self._subscribers.get(intent.target_agent_id)       # dispatch fallback

rg -n 'f"intent\.' src/probos/mesh/intent.py
  529:        subject = f"intent.{agent_id}"                       # loopback subscribe
  679:        subject = f"intent.dispatch.{agent_id}"
  1119:        subject = f"intent.{intent.target_agent_id}"         # loopback publish
  1423:            subject = f"intent.dispatch.{intent.target_agent_id}"

rg -n "js_subscribe\(" src/probos/mesh/intent.py -A 9
  812-820: durable=durable_name, stream="INTENT_DISPATCH", max_ack_pending=1,
           ack_wait=300, manual_ack=True, max_deliver=10

src/probos/startup/nats.py:70-75
  recreate_stream("INTENT_DISPATCH", ["intent.dispatch.>"], max_msgs=10000, max_age=300)

src/probos/mesh/intent.py:1500
  # js_msg=None — no JetStream backing for fallback path

rg -n "has_subscriber" src/probos/federation/bridge.py
  1894:        if not self._intent_bus.has_subscriber(target_agent_id):

pytest tests/test_ad1276_inbound_authorization.py::TestALoopbackIsEvaluatedOnBothSides \
       tests/test_ad1276_inbound_authorization.py::TestThereIsNoSuppressionLedger -q
  8 passed in 7.24s

pytest <9-file affected cluster> -q -p no:randomly
  1 failed, 213 passed   (failure = RedirectEscalation ImportError, foreign work)
```

### Absence verified

```
CLAIM: nobody except the target agent consumes intent.{id} / intent.dispatch.{id}
RUN:   rg -n '"intent\.|f"intent\.|intent\.dispatch|intent\.\*|intent\.>' src/probos --glob '*.py'
FOUND: 7 hits, all in mesh/intent.py (the agent's own sub/pub) plus
       startup/nats.py:72, which is the STREAM subject filter, not a consumer.
HOLDS: yes -- and subjects are per-node prefixed (nats_bus.py:476, 1533), so
       the loopback is intra-node.

CLAIM: no test depends on send() propagating a handler exception
RUN:   rg -n "pytest.raises" tests/ -B 3 | rg "\.send\("
FOUND: test_bf771_intent_authorization.py:256, 283, 317 -- all
       IntentAuthorizationDenied (the opt-in denial), none a handler crash.
HOLDS: yes

CLAIM: only two tests pin hook.calls == 2
RUN:   rg -n "hook.calls" tests/ --glob '*.py'
FOUND: test_ad1276_inbound_authorization.py:254 (send), :270 (dispatch), :284
HOLDS: yes -- :254 changes to 1, :270 stays 2

CLAIM: BF-742's wire-fidelity tests do not go inert
RUN:   rg -n "\.send\(|_deserialize_intent" tests/test_bf742_wire_carries_every_field.py
FOUND: exercises IntentBus._deserialize_intent(IntentBus._serialize_intent(x))
       directly; no .send( call.
HOLDS: yes -- unaffected by route selection
```

### AD ceiling

**AD-1291.** All three sources enumerated; the highest came from `git log` **and** `prompts/`, with issue titles one below:

| Source | Command | Highest |
|---|---|---|
| git subjects | `git log --all --format='%s'` | AD-1291 |
| **issue titles, ALL states** | `gh issue list --state all --limit 2000 --json number,title,state` → **1338 returned** (not 2000, so not truncated) | AD-1290 |
| in-flight prompts | `Get-ChildItem prompts -Filter 'ad-*.md'` | ad-1291 |

Issue titles carry AD-1286–1290 (epic #1332's children, allocated but unbuilt) which `git log` cannot see; they are below the ceiling this time but were checked, because skipping that source caused a real double-allocation earlier today.

**This AD: AD-1292.**
