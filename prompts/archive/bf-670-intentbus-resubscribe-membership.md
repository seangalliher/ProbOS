# BF-670 — Replace stale IntentBus intent-index memberships on re-subscribe

**Verdict:** APPROVED FOR BUILDER HANDOFF
**One-line:** Make each successful same-ID `IntentBus.subscribe()` replace the agent's intent-index membership set exactly, while preserving its callable/class sidecars, transport/queue lifecycle, and every in-flight dispatch snapshot.

**Status:** Build-ready on the exact clean base below
**Type:** Bug fix — **BF-670**; no new AD and no `DECISIONS.md` or roadmap entry
**GitHub issue:** seangalliher/ProbOS#1037 — https://github.com/seangalliher/ProbOS/issues/1037
**Exact base HEAD:** `9a23705e5f4fa41d5dcc02209496bdcff56f09e7`
**Base commit:** `BF-671: unify chat and call audio control (closes #1038)`
**Numbering verified:** current highest shipped entries are **AD-1122** and **BF-671**; issue #1037 reserves **BF-670**
**Dependencies:** AD-289, AD-397, AD-470, AD-515, AD-637b/z, AD-654a/b, BF-223, BF-296, BF-668
**License disposition:** none — standard-library collection operations only; no dependency or absorbed external code
**Estimated tests:** 10–16 additions/updates in two existing test files; no new source or test file

## Scope

Repair only the local `IntentBus` intent-index membership lifecycle on re-subscription.

The implementation must guarantee:

1. after a successful `subscribe(agent_id, handler, intent_names, latency_class=...)`, that `agent_id` belongs to exactly the intent-index sets named by the supplied truthy `intent_names` sequence;
2. every prior membership for that ID is discarded before the new memberships are added;
3. re-subscribing with `None` or `[]` gives the ID zero indexed memberships, making it a fallback subscriber under the existing broadcast rules;
4. prior intent keys remain present with empty sets, preserving the existing known-empty versus never-indexed distinction;
5. `_subscribers` remains the raw callable map and `_subscriber_latency_classes` remains the BF-668 typed sidecar;
6. validation failure leaves handler, latency class, index, NATS/JetStream subscriptions, queues, and tasks unchanged;
7. `subscribe()` does not call public `unsubscribe()`, recreate/clear cognitive queues, remove transport subscriptions/consumers, or change transport task behavior;
8. `unsubscribe()` reuses the same index-only removal primitive, then preserves its current full teardown behavior;
9. a broadcast that already snapshotted `(handler, latency_class)` continues with that old pair after re-subscription; later broadcasts use the new pair and exact new membership;
10. targeted `send()`/targeted `broadcast()`, NATS request/reply, JetStream dispatch, `dispatch_async()`, cognitive queues, completion ordering, timeout cancellation, close semantics, and federation remain unchanged; and
11. the real patched-agent hot-replacement subscription path can replace changed descriptors under the preserved ID without the patched handler receiving an old-intent broadcast.

No routing redesign, reverse index, public API, config, persistence, event, logging, metric, lifecycle, UI, dependency, or AD is authorized.

---

## Problem, live evidence, and verified root cause

At the exact base:

- `src/probos/mesh/intent.py` around lines 281–324 defines `IntentBus.subscribe(self, agent_id, handler, intent_names=None, *, latency_class=DETERMINISTIC) -> None`.
- It validates `latency_class` before mutation, then overwrites `_subscribers[agent_id]` and `_subscriber_latency_classes[agent_id]`.
- When `intent_names` is truthy, it only creates missing sets and calls `add(agent_id)`. It never removes the ID from earlier sets.
- `src/probos/mesh/intent.py` around lines 510–540 defines `unsubscribe()`. It already loops through every `_intent_index.values()` set and calls `discard(agent_id)` without deleting empty keys, but that logic is duplicated inline rather than exposed as an index-only primitive.
- `src/probos/mesh/intent.py` around lines 681–733 owns broadcast candidate selection. If `intent.intent` has an index key—even an empty set—the bus invokes only matching indexed IDs plus IDs absent from every index set. If no key exists, it fans out to all subscribers.
- Therefore an empty retained key and a never-created key are deliberately different: known-empty excludes every currently indexed non-fallback ID, while never-indexed fans out to all subscribers.
- The candidate dict captures each selected handler and BF-668 latency class together before task creation, and `_invoke_handler()` receives that pair. Re-subscription during an in-flight handler must not alter that invocation.
- `_subscribers` is also read directly by targeted `send()` and `dispatch_async()`; neither consults `_intent_index`. Their behavior must remain unchanged.
- `subscribe()` also schedules targeted-NATS and, after BF-223 deferral clears, JetStream consumer subscription tasks. `unsubscribe()` additionally removes the queue, targeted NATS subscription, and JetStream durable consumer. Calling `unsubscribe()` from `subscribe()` would therefore destroy state outside the index and is forbidden.
- `src/probos/self_mod_manager.py` around lines 188–225 owns patched-agent hot replacement. It reads a healthy pool member's ID, constructs the patched class, preserves the ID for the subscription call, and re-subscribes `new_agent.handle_intent` with names derived from the new `intent_descriptors` and the inherited BF-668 latency class. Changed descriptors are a real trigger for same-ID re-subscription.
- There are exactly eight production `IntentBus.subscribe()` sites: common onboarding, Yeoman proactive helper, VisionAggregator, VisionConsumer, group-chat coordinator, device service, patched-agent replacement, and device-consensus dispatch. There is no production direct `IntentBus.unsubscribe()` caller at this base; the public method is exercised by tests and remains part of the lifecycle contract.

### Empirical fail-before reproduction at exact HEAD

A real `IntentBus(SignalManager())` probe produced:

```text
map_after_new={'old.intent': ['same'], 'new.intent': ['same']}
old_results=1 new_results=1
calls=[('new', 'old.intent'), ('new', 'new.intent')]
```

The replacement handler is therefore invoked by the stale old membership.

Re-subscribing the same ID with `None` left both old memberships present:

```text
map_after_none={'old.intent': ['same'], 'new.intent': ['same']}
```

It did not become a fallback subscriber.

An in-flight probe confirmed the BF-668 snapshot itself is correct: the already-running broadcast used the old handler, but a later old-intent broadcast incorrectly used the new handler because stale membership survived.

---

## Issue-contract corrections and clarifications

Issue #1037 is directionally correct. These clarifications are binding:

1. **The input-validation boundary is the existing `latency_class` type check.** `subscribe()` currently performs no runtime validation of `agent_id`, `handler`, or individual intent-name values. BF-670 must not add unrelated validation or coercion. Call the index-removal helper only after the existing latency-class check so the one current failure path remains mutation-free.
2. **`None` and `[]` are equivalent fallback requests.** The current truthiness branch already treats both as no explicit memberships. Preserve that public behavior; do not distinguish them, reject empty lists, or create an empty-string intent.
3. **Duplicates in `intent_names` remain harmless set semantics.** Do not deduplicate into a new public contract or reject duplicates; repeated `set.add()` remains idempotent.
4. **Known-empty and never-indexed are intentionally different.** The private helper must discard IDs from values only. It must never delete empty keys or rebuild `_intent_index` from non-empty sets.
5. **Replacement is synchronous and non-transactional only in the existing sense.** There is no await between sidecar/index mutations. Do not add a lock, generation, rollback layer, or reverse index. Under the one event-loop thread, broadcast snapshots and subscribe replacement remain atomic with respect to task switching.
6. **Do not call `unsubscribe()` from `subscribe()`.** Public unsubscribe tears down the cognitive queue and transport subscriptions/consumer. BF-670 needs an index-only helper.
7. **Hot replacement test correction:** the existing BF-668 `TestHotReplacementLatencyMetadata` uses a mocked bus and proves only the class keyword. BF-670 must replace/extend that case with a real `IntentBus`; no production `SelfModManager` edit is needed. The test may keep narrow fakes for unrelated manager collaborators, but the bus and dispatch behavior must be real.
8. **Registry oddities are out of scope.** `SelfModManager._apply_agent_correction()` calls the registry without awaiting its async method and assigns `new_agent._id` while `BaseAgent` exposes public `id`. Those pre-existing issues are unrelated to stale bus membership. Use a narrow recording registry fake in the BF-670 test; do not edit self-mod or registry code.
9. **Fallback status is global membership absence.** An ID becomes fallback only after it is absent from every index set. The helper must sweep all values, not only names supplied on the current call.
10. **Transport re-subscribe behavior remains exactly current.** A same-ID `subscribe()` may continue scheduling the existing NATS/JetStream subscription tasks. BF-670 does not redesign or deduplicate those tasks; it only guarantees the index update does not invoke teardown.
11. **Tracker precedent is `PROGRESS.md` only.** BF-668, BF-669, and BF-671 closeouts used `PROGRESS.md` and explicitly created no new AD/decision entry. BF-670 follows that precedent. No roadmap or `DECISIONS.md` edit.

---

## Pinned design decisions

### DD-1 — One private index-only removal helper

Add one fully typed private method on `IntentBus`, adjacent to `subscribe()`/`unsubscribe()`:

```text
def _remove_intent_index_memberships(self, agent_id: str) -> None:
    for agent_ids in self._intent_index.values():
        agent_ids.discard(agent_id)
```

The exact private name may vary, but its contract may not:

- removes only the supplied ID from every existing set;
- leaves every dictionary key in place, including keys whose set becomes empty;
- does not touch `_subscribers`, `_subscriber_latency_classes`, `_agent_queues`, `_pending_sub_tasks`, `_nats_bus`, `_defer_dispatch_consumers`, metrics, signals, or any transport;
- is idempotent for unknown/already-absent IDs;
- contains no await, task, logging, allocation of a reverse map, or public return value.

Do not add a reverse index. The current index cardinality is small, and `unsubscribe()` already performs this O(number-of-known-intents) sweep.

### DD-2 — `subscribe()` makes the supplied sequence authoritative

Keep the exact public signature and existing latency-class validation.

After the current validation succeeds and before adding any new names:

1. replace `_subscribers[agent_id]` with `handler`;
2. replace `_subscriber_latency_classes[agent_id]` with `latency_class`;
3. call the private index-only helper exactly once;
4. add the ID to each truthy supplied intent name using the existing set-creation/add behavior; and
5. preserve the NATS/JetStream scheduling block byte-for-byte.

The relative order of steps 1–3 is not externally yield-visible because they are synchronous, but tests must prove the final triple—callable, class, memberships—is coherent. Do not introduce a lock or temporary reverse map.

Calling the helper after the existing type validation is mandatory: a rejected raw latency string must preserve the prior handler, class, and memberships exactly and must schedule no transport work.

### DD-3 — `unsubscribe()` reuses the helper but keeps full teardown

Replace only the duplicated inline index sweep in `unsubscribe()` with the private helper.

Preserve this teardown order and behavior:

1. remove handler;
2. remove latency class;
3. unregister cognitive queue;
4. remove all intent-index memberships through the helper;
5. retain existing targeted NATS removal task scheduling;
6. retain existing JetStream consumer deletion scheduling.

Unknown/repeated unsubscribe remains idempotent. Empty index keys remain. Do not turn the helper into public unsubscribe logic or move transport cleanup into it.

### DD-4 — Broadcast selection and in-flight snapshot remain unchanged

Do not edit `broadcast()` or `_invoke_handler()`.

Required behavior:

- old-intent key retained empty after replacement means the replacement ID is not selected there;
- new-intent broadcast selects the replacement once;
- never-indexed broadcast still fans out to all subscribers;
- an indexed-to-`None`/`[]` replacement has no memberships and therefore qualifies as fallback for every known indexed intent as well as never-indexed intents;
- a broadcast whose candidates were captured before replacement invokes the old `(handler, latency_class)` and records the old BF-668 metric class;
- later old-intent broadcast does not invoke the replacement;
- later new-intent broadcast invokes the new handler and records the new class;
- completion ordering, one-task-per-candidate, timeout cancellation, and result append order are untouched.

### DD-5 — Real hot-replacement integration proof, no self-mod production edit

Update `tests/test_correction_runtime.py` within the existing `TestHotReplacementLatencyMetadata` area:

- use a real `IntentBus(SignalManager())`, not `MagicMock`, as `manager._intent_bus`;
- provide an old subscriber under the pool member ID with `intent_descriptors`/membership `old.intent`;
- patched `CognitiveAgent` class declares only `new.intent` and returns a distinct result/call marker from `handle_intent` (or overrides that handler narrowly in the test subclass);
- use narrow fakes for pool, registry, spawner, and capability registry so `_apply_agent_correction()` reaches its live `subscribe()` call without relying on MagicMock auto-attributes or the unrelated async-registry defect;
- run the real `_apply_agent_correction()` method;
- assert the real bus's callable was replaced and its BF-668 class is cognitive;
- assert `old.intent` remains a known empty key and a broadcast to it cannot invoke the patched handler;
- assert `new.intent` invokes the patched handler exactly once.

Do not modify `SelfModManager`, `AgentRegistry`, `ResourcePool`, `CognitiveAgent`, or any startup code for this BF.

### DD-6 — Non-index dispatch/transport/lifecycle paths are regression-only

BF-670 must not alter:

- targeted direct `send()` or targeted `broadcast()` (target ID bypasses membership filtering);
- NATS request/reply subject/callback behavior;
- JetStream durable consumer creation, ack/term, and deletion;
- `dispatch_async()` JetStream publish, cognitive-queue fallback, direct fallback, or task cap;
- cognitive queue registrations on re-subscribe;
- close-to-new-dispatches or in-flight completion;
- federation forwarding and `federated=False` suppression;
- BF-668 metrics schema, thresholding, warning, cancellation, or sidecar snapshot;
- public `get_subscriber_map()` shape.

These files are blast-run only. A regression requiring edits outside the narrow allowlist is a hard stop.

---

## Exact file allowlist

### Production file the Builder may modify

- `src/probos/mesh/intent.py` — private index-only helper; authoritative re-subscribe sweep; helper reuse from unsubscribe.

### Existing tests the Builder may modify

- `tests/test_intent.py` — direct membership replacement matrix, fallback/empty behavior, validation no-mutation, in-flight BF-668 snapshot, queue/transport non-teardown assertions.
- `tests/test_correction_runtime.py` — real-IntentBus patched-agent changed-descriptor integration proof.

### Architect documents already present; retain byte-for-byte during build

- `prompts/bf-670-intentbus-resubscribe-membership.md`
- `prompts/bf-670-intentbus-resubscribe-membership-execution.md`

### Conditional closeout only, after green gates and final Architect review

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config/YAML, workflow, standing order, UI, dependency/lockfile, tracker, roadmap, decision, era, archive, data/log, Git, or GitHub path is authorized.

Reference-only gate files are not authorized for modification. If a required fix reaches one, stop.

---

## Ordered implementation

### Section 1 — Add counterfactual fail-before tests

Before production edits, add tests that fail on exact HEAD for the reason they are meant to prevent:

1. `old.intent` → `new.intent` same-ID replacement leaves `old.intent` stale and invokes the new handler on HEAD;
2. indexed → `None` and indexed → `[]` fail to become fallback on HEAD;
3. real `SelfModManager._apply_agent_correction()` + real `IntentBus` leaves old descriptors routable on HEAD.

Record exact failing node IDs and assertion reasons. Do not weaken existing BF-668 tests or use source inspection as the headline proof.

### Section 2 — Add the private helper and wire exact replacement

1. Add DD-1's private typed helper.
2. Invoke it from `subscribe()` only after the existing latency-class check.
3. Reuse it from `unsubscribe()`.
4. Do not edit broadcast, send, transport, queue, metrics, or self-mod production code.

### Section 3 — Complete direct membership and boundary tests

In `tests/test_intent.py`, behaviorally cover:

- disjoint old→new replacement;
- subset, superset, overlap, and repeated-identical replacement;
- duplicate names in the supplied list;
- `None` and empty-list fallback conversion;
- new fallback→indexed conversion;
- unknown/empty-ID helper behavior where applicable without defining a new public validation rule;
- invalid latency class leaves the complete prior state unchanged;
- known-empty keys remain in `get_subscriber_map()` with `[]` while never-indexed key remains absent;
- removed old intent cannot invoke the replacement; new intent invokes exactly once;
- targeted send still reaches the replacement regardless of its membership;
- registered cognitive queue object remains registered across re-subscribe;
- with a NATS stub/reference installed, re-subscribe never calls `remove_tracked_subscription` or `delete_consumer`;
- unsubscribe still removes callable, class, queue, and every membership, leaves keys empty, and retains existing transport cleanup tests.

Use parameterization for the membership matrix; do not create repetitive tests for the same set algebra.

### Section 4 — Strengthen the in-flight snapshot regression

Extend the existing `test_broadcast_snapshots_handler_and_latency_class_together` rather than duplicating it:

1. subscribe old cognitive handler to `old.intent`;
2. begin old-intent broadcast and pause inside old handler;
3. re-subscribe same ID with new deterministic handler to `new.intent`;
4. release first handler and prove old handler + cognitive metric class completed;
5. broadcast `old.intent` again and prove no new invocation/result/metric row;
6. broadcast `new.intent` and prove new handler + deterministic metric class exactly once.

This proves both the preserved in-flight snapshot and the repaired post-replacement route.

### Section 5 — Add the real hot-replacement integration

Implement DD-5 in `tests/test_correction_runtime.py`. Keep the bus real and unrelated collaborators narrow. Assert behavior, not only call kwargs.

### Section 6 — Run exact gates and three-pass review

Run only the exact serial/isolated commands below. Do not run full `tests/`, xdist, live network/LLM, or live platform data.

### Section 7 — Architect-controlled closeout

Builder returns an uncommitted implementation and report. After Architect review only:

1. prepend one concise BF-670 closeout to `PROGRESS.md` with #1037, exact focused/blast counts, exact membership replacement semantics, and preservation of BF-668/transport/federation behavior;
2. state no new AD and retain BF-671 as the numeric BF ceiling while BF-670 is now shipped;
3. include both unchanged BF-670 prompt docs;
4. do not edit `DECISIONS.md`, roadmap, era files, config YAML, or GitHub;
5. stage explicit allowlisted paths only; and
6. commit exactly:

`BF-670: replace IntentBus re-subscribe memberships (closes #1037)`

Do not push or mutate GitHub unless separately directed by the autonomous orchestrator after final review.

---

## Required behavioral tests

### A. Exact membership replacement

1. **Counterfactual headline:** subscribe ID with old handler/`old.intent`, then new handler/`new.intent`; final map contains old key `[]`, new key `[ID]`; old broadcast returns no local result and never calls new handler; new broadcast calls it exactly once. This test must fail on HEAD because old membership remains.
2. Subset replacement removes only dropped memberships and retains intersecting ones.
3. Superset replacement adds new memberships and retains old ones exactly once.
4. Overlap replacement yields exactly the new set, no union residue.
5. Repeated-identical replacement is idempotent in membership and invokes only the newest handler once.
6. Duplicate names in one supplied list still produce one set membership and one handler invocation.
7. Different agent IDs sharing one intent are unaffected by replacing one ID.

### B. Fallback, empty, and error boundaries

8. Indexed→`None` and indexed→`[]` each leave the old key present/empty and put the ID under `__fallback__` in `get_subscriber_map()`.
9. A fallback replacement receives a known-empty old intent and a never-indexed intent under the existing rules.
10. Fallback→indexed removes fallback status and selects only the supplied known intent; never-indexed fan-out remains unchanged.
11. Unknown/already-absent ID removal is idempotent and does not delete empty keys.
12. Invalid raw latency class on an already-subscribed ID raises `TypeError` before mutation: old callable identity, old class, exact index snapshot, queue, transport-task set, and NATS teardown-call counts remain unchanged.
13. `None`/`[]` do not create a new index key. Empty string supplied inside a truthy list retains existing set-key behavior; BF-670 adds no new name validation.

### C. BF-668 callable/class snapshot and dispatch semantics

14. Re-subscribe replaces raw callable and latency class sidecar together.
15. In-flight old broadcast completes with old handler and old class metric after replacement.
16. Later old-intent broadcast does not invoke the new handler; later new-intent broadcast does and records its new class.
17. Fan-out still uses one task per selected candidate, starts concurrently, returns completion order, and cancels timed-out pending handlers without a sample.
18. Handler metrics schema, thresholds, warnings, cancellation, and error semantics remain unchanged.

### D. Queue, transport, targeted send, and unsubscribe

19. Registered cognitive queue survives re-subscribe by identity; `unregister_queue` is not invoked.
20. Re-subscribe does not call targeted-NATS removal or JetStream consumer deletion. Existing subscribe scheduling remains unchanged.
21. Targeted direct `send()` and targeted `broadcast()` reach the current replacement handler regardless of indexed membership and invoke it once.
22. Existing NATS request/reply remains single-delivery; prefix re-subscription remains green.
23. JetStream dispatch/ack/term and `dispatch_async()` queue/direct fallback remain green.
24. Public `unsubscribe()` removes handler, class, queue, and all memberships through the helper; leaves empty keys; retains current NATS/JetStream cleanup behavior; repeated/unknown unsubscribe remains safe.
25. Closing the bus does not interrupt an already-running handler and still rejects new broadcast/send/dispatch work.

### E. Hot replacement and federation

26. Real `SelfModManager._apply_agent_correction()` with a real `IntentBus` and changed descriptors preserves the ID subscription, replaces class/handler, leaves old intent known-empty, prevents old-intent dispatch to patched code, and dispatches new intent once.
27. Federation forwarding still runs after local resolution when enabled, is skipped with `federated=False`, and merges remote results unchanged.
28. No self-mod source, registry, pool, capability, decomposer, trust, Hebbian, or persistence behavior changes.

---

## Exact test gates

Run from `D:\ProbOS`.

Both commands use a unique temporary data directory, `PROBOS_EMBEDDINGS=local`, serial execution, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error. Do not add offline environment variables not requested by this packet.

Clean-HEAD Architect baselines at `9a23705e`:

- focused: **106 passed**;
- blast: **306 passed**.

Post-build counts will increase. Report exact pass/fail/skip counts and durations.

### Focused — membership owner, BF-668 metadata, filtering, hot replacement

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf670_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_performance_p0.py tests/test_correction_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius — targeted/NATS/JetStream/queues/federation/all subscription owners/shutdown

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf670_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_targeted_dispatch.py tests/test_ad637z_nats_cleanup.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py tests/test_federation.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_runtime.py tests/test_sif.py tests/test_ad843c1_device_actuation.py tests/test_ad843c2_device_consensus.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute `-n auto`, `-n 4`, full `tests/`, live network/LLM, or live runtime data.

---

## Acceptance criteria

1. Current base is exactly `9a23705e5f4fa41d5dcc02209496bdcff56f09e7`; current highest is AD-1122/BF-671; BF-670 remains the issue-reserved identifier.
2. `IntentBus.subscribe()` public signature and return remain unchanged.
3. One private typed helper discards an ID from every existing index set and leaves all keys, including empty keys, intact.
4. Successful re-subscribe leaves the ID in exactly the truthy supplied intent-name sets; no union residue remains.
5. `None` and `[]` produce zero memberships and true fallback status; duplicate/repeated names retain set idempotence.
6. A rejected non-enum latency class mutates nothing and schedules no transport work.
7. `_subscribers` remains the raw callable map; `_subscriber_latency_classes` remains aligned and typed; BF-668 metrics/thresholds/warnings are unchanged.
8. In-flight broadcast uses the old handler/class pair; later old intent cannot dispatch the replacement; later new intent dispatches it once.
9. Known-empty and never-indexed behavior remains unchanged; empty keys are not deleted.
10. Registered cognitive queue survives re-subscribe; no unsubscribe teardown path is invoked.
11. Re-subscribe does not remove targeted NATS subscriptions or JetStream consumers and does not change existing subscribe-task scheduling.
12. `unsubscribe()` reuses the helper and still removes handler, class, queue, memberships, targeted NATS subscription, and JetStream consumer as before.
13. Targeted send/targeted broadcast remains membership-independent and single-delivery.
14. NATS request/reply, prefix handling, JetStream dispatch/ack/term, `dispatch_async`, cognitive queues, close semantics, completion order, timeout cancellation, and federation remain green.
15. The real hot-replacement test uses a real `IntentBus` and proves changed descriptors cannot route patched code through the old intent.
16. Production changes are limited to `src/probos/mesh/intent.py`; test changes are limited to `tests/test_intent.py` and `tests/test_correction_runtime.py`.
17. Focused and blast commands pass under exact isolated/local/serial/warning-strict settings; exact counts/skips/durations are reported.
18. Tracker closeout, if authorized after final review, edits only `PROGRESS.md`; no `DECISIONS.md`, roadmap, era, or config/YAML entry.
19. No deletion, broad reformat, new source/test file, dependency, config, UI, event, metric, persistence, lock, reverse index, AD, or GitHub mutation appears.
20. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No new AD or BF renumbering; no `DECISIONS.md`, roadmap, era, or commercial edit.
- No reverse index, membership cache, lock, generation, transaction wrapper, subscriber dataclass, or replacement of raw callable `_subscribers` values.
- No public API/signature change to `subscribe()`, `unsubscribe()`, `broadcast()`, `send()`, `dispatch_async()`, `IntentMessage`, `IntentResult`, `IntentDescriptor`, `BaseAgent`, or any protocol.
- No new validation/coercion for agent IDs, handlers, intent names, empty strings, duplicate names, or list element types.
- No deletion of empty `_intent_index` keys and no change to known-empty/no-index fallback semantics.
- No call to public `unsubscribe()` from `subscribe()`.
- No queue unregister/re-register, NATS removal/recreate redesign, JetStream durable-consumer deletion/recreate redesign, or subscribe-task deduplication.
- No edit to broadcast candidate construction, task creation, `_invoke_handler`, BF-668 latency classes/thresholds/metrics/warnings, completion ordering, timeout, cancellation, error result, or signal lifecycle.
- No targeted-send, targeted-broadcast, NATS/JetStream, `dispatch_async`, cognitive-queue, close/shutdown, federation, trust, Hebbian, consensus, capability, registry, pool, onboarding, or self-mod production change.
- No fix for the pre-existing unawaited registry call or `_id`/`id` mismatch in `SelfModManager`; those are outside issue #1037.
- No config field, `config/system.yaml`, environment variable, dependency, event, endpoint, persistence, UI, log/metric surface, or data migration.
- No new test file and no edit to reference-only blast tests.
- No Builder tracker edit, staging, commit, push, issue comment/close/label/edit, or other Git/GitHub mutation before Architect review.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD or `origin/main` differs from `9a23705e5f4fa41d5dcc02209496bdcff56f09e7`, or the initial tree contains anything beyond the two BF-670 Architect docs.
2. A required behavior needs a production/test path outside the exact allowlist.
3. Correctness appears to require a reverse index, lock, public API, config, event, metric, persistence, dependency, or changed intent-name validation.
4. Empty intent-index keys would need deletion or known-empty/no-index behavior would change.
5. Re-subscribe would need to call `unsubscribe()` or tear down/recreate a queue, targeted NATS subscription, or JetStream consumer.
6. Broadcast, `_invoke_handler`, targeted send, NATS/JetStream, `dispatch_async`, cognitive queue, close, federation, or BF-668 telemetry source must change.
7. The real hot-replacement test cannot reach the existing real `subscribe()` seam with narrow unrelated fakes and a real bus without production self-mod edits.
8. A focused/blast failure reproduces serially and requires an unallowlisted fix, skip, quarantine, weakened assertion, or broad test run.
9. Either Architect doc changes, a deletion/bulk reformat appears, or config/YAML/UI/dependency/tracker/Git/GitHub mutation occurs before review.

Do not guess around a hard stop.

---

## Three-pass Builder self-review

### Pass 1 — Behavior/spec

- Map every DD, required test, and acceptance criterion.
- Verify final membership equality for disjoint/subset/superset/overlap/repeated/duplicate-name and fallback transitions.
- Verify old intent cannot invoke replacement, new intent invokes once, and other IDs are unaffected.
- Verify in-flight old snapshot and later new snapshot behavior.
- Verify hot replacement through a real bus.

### Pass 2 — Verify-first/code

- Re-grep the exact `subscribe()`/`unsubscribe()` signatures and all eight production subscribe sites.
- Inspect the helper line-by-line: values only, `discard`, no key deletion or other state touch.
- Confirm helper call occurs after latency validation and before new membership adds.
- Confirm `_subscribers`/class sidecar, NATS/JetStream block, broadcast, send, dispatch, queues, metrics, and federation diffs are absent.
- Confirm the hot-replacement test uses real bus behavior and no MagicMock auto-attribute at that boundary.

### Pass 3 — Scope/safety/license

- Verify exact allowlist, no new files/deletion/broad format, prompt docs byte-for-byte, and no YAML/UI/dependency/tracker/Git/GitHub drift.
- Verify cancellation and async task behavior are unchanged; no new task or fire-and-forget path exists.
- Verify no new logs and no sensitive payload logging.
- Verify compliance with `.github/copilot-instructions.md`; license remains none.

---

## Verified Against Codebase (2026-07-16)

```text
git rev-parse HEAD
  9a23705e5f4fa41d5dcc02209496bdcff56f09e7

git rev-parse origin/main
  9a23705e5f4fa41d5dcc02209496bdcff56f09e7

git status --short before Architect docs
  <empty>

git log -1 --oneline
  9a23705e BF-671: unify chat and call audio control (closes #1038)

gh issue view 1037 --repo seangalliher/ProbOS
  OPEN — BF-670: Replace stale IntentBus intent-index memberships on re-subscribe

PROGRESS.md:3
  BF-671 is the new BF ceiling; BF-670 remains reserved/open for #1037.

numbering scan
  highest AD referenced in canonical trackers: AD-1122
  highest BF referenced in canonical trackers: BF-671

src/probos/mesh/intent.py
  218: _subscribers is dict[str, IntentHandler]
  219: _subscriber_latency_classes is the BF-668 sidecar
  220: _intent_index is dict[str, set[str]]
  281-324: subscribe signature, latency validation, handler/class replacement, add-only memberships, NATS/JetStream scheduling
  510-540: unsubscribe removes handler/class/queue, inline-discard sweep, NATS/JetStream teardown
  553-588: targeted send reads _subscribers directly, not _intent_index
  681-733: known-key/no-key filtering and (handler,class) snapshot
  724-730: one create_task per snapshotted candidate
  733-737: asyncio.wait + pending cancellation
  743-749: federation forwarding after local results
  783-847: dispatch_async NATS/queue/direct paths read target handler independently of memberships
  951-1016: _invoke_handler BF-668 completion/error/cancellation behavior

production IntentBus subscribe call inventory (exactly 8)
  src/probos/agent_onboarding.py:172
  src/probos/cognitive/yeoman.py:247
  src/probos/perception/aggregator.py:86
  src/probos/perception/consumer.py:249
  src/probos/runtime.py:508
  src/probos/runtime.py:932
  src/probos/self_mod_manager.py:218
  src/probos/startup/finalize.py:169
  production direct IntentBus.unsubscribe call sites: 0

src/probos/self_mod_manager.py
  188: _apply_agent_correction
  209: healthy-agent iteration
  212-216: replacement construction / retained-ID setup
  218-222: re-subscribe patched handler with new descriptor names and new_agent.handler_latency_class

tests/test_intent.py
  148: raw callable + explicit latency sidecar test
  177: invalid latency class before mutation (currently only tests a new ID)
  191: handler/class replacement (currently does not assert memberships)
  215: unsubscribe handler/class/queue/index
  251: in-flight callable/class snapshot
  537: fan-out concurrency/one task
  578: completion order
  607: timeout cancellation/no sample
  674-876: NATS/targeted/publish/serialization paths
  878: federation handler integration

tests/test_ad470_intent_bus_enhancements.py
  304: subscriber map indexed shape
  317: fallback map
  340: broadcast metrics
  355: targeted send metrics

tests/test_performance_p0.py
  39: matching prefilter
  62: no-index fan-out
  80: fallback with known indexed intent
  104: unsubscribe index removal

tests/test_correction_runtime.py
  149: existing BF-668 hot replacement case
  164-180: MagicMock bus; only latency keyword asserted; no routing proof

tests/test_targeted_dispatch.py
  20-111: direct send, timeout, targeted broadcast, no-target validation

tests/test_ad637z_nats_cleanup.py
  159-325: task tracking, connected send, prefix resubscribe

tests/test_ad654a_async_dispatch.py / test_ad654b_cognitive_queue.py
  JetStream publish/consumer/cleanup/ack/term and queue/direct fallback coverage

tests/test_bf296_intent_bus_close.py
  110: in-flight handler completes after close

tests/test_federation.py
  644-694: federation enabled/disabled/no-handler integration

empirical HEAD probe
  after old.intent -> new.intent: map contains both memberships
  old.intent invokes the new replacement handler (incorrect)
  after re-subscribe None: stale memberships remain (incorrect)
  in-flight old broadcast uses old handler (correct snapshot)
  later old broadcast uses new handler because stale membership remains (incorrect)

clean-HEAD exact gates
  focused: 106 passed in 2.79s
  blast: 306 passed in 316.81s
```
