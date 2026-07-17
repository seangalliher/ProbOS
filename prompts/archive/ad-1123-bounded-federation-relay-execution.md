# AD-1123 Builder Execution — Bounded federation one-way relay

**Binding specification:** `prompts/ad-1123-bounded-federation-relay.md`
**Exact base:** clean `D:\ProbOS` `main` at `8eeaf406a1121a131c73a5cb6e361c0e6ce3e1a5`
**Numbering:** highest landed top-level **AD-1122**; build **AD-1123** only; BF ceiling **BF-672**
**GitHub:** do not create/edit/close any issue; #659 stays open
**Mode:** continue the live uncommitted AD, correction-test-first, no production work outside the three-path active correction allowlist

---

## Builder re-approval

**RE-APPROVED / CORRECTION EXECUTABLE** on the exact base and live uncommitted implementation below. The prior implementation review was BLOCKED; binding corrections C1–C3 now resolve it.

The architecture is settled. Continue the accepted work; do not restart, discard, restore, stash, or rewrite it. Do not redesign it into a telemetry-only wire, arbitrary event/intent relay, request/response RPC, stream session, transport callback, or background queue. If any binding contract is impossible against the live base, hard-stop and return to Architect rather than improvising.

The main prompt's **“BLOCKED implementation review correction packet”** is highest precedence. Its one relay-local node predicate, complete callable-introspection containment, fail-closed startup/restart regression, correction-red requirements, and exact three-path correction allowlist are binding. Every prior envelope, bound, log, cancellation, rate, parity, AST, gate, closeout, and Do Not Build requirement remains in force.

---

## Correction pre-flight — exact live state

1. Read in full:
   - `.github/copilot-instructions.md`
   - `prompts/ad-1123-bounded-federation-relay.md`
   - `src/probos/federation/bridge.py`
   - `src/probos/federation/telemetry_relay.py`
   - `src/probos/federation/nats_transport.py`
   - `src/probos/federation/transport.py`
   - `src/probos/federation/mock_transport.py`
   - `src/probos/startup/fleet_organization.py`
   - `src/probos/startup/shutdown.py`
   - `tests/test_ad730_4_directed_federated_vision_dm.py`
   - `tests/test_ad722b_5_federation_telemetry.py`
2. Verify:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected status is exactly the live AD-1123 implementation under review:

```text
 M src/probos/federation/bridge.py
 M src/probos/runtime.py
 M src/probos/startup/fleet_organization.py
?? prompts/ad-1123-bounded-federation-relay-execution.md
?? prompts/ad-1123-bounded-federation-relay.md
?? src/probos/federation/relay.py
?? tests/test_ad1123_bounded_federation_relay.py
```

`logs/ad1123_issue_body.md` is ignored and must not appear or be staged.
3. Confirm HEAD and origin/main both equal `8eeaf406a1121a131c73a5cb6e361c0e6ce3e1a5`.
4. Confirm `PROGRESS.md` and `DECISIONS.md` still identify AD-1122 as the top-level ceiling and no AD-1123 is landed.
5. Recompute or assert the binding AST hashes before edits. A mismatch on any frozen method is a hard stop.
6. Confirm the live pre-correction hashes exactly:

| File | SHA-256 |
|---|---|
| `src/probos/federation/relay.py` | `33fa02e30c7541f95bc485e0be9d82ed817c7ecef225acd56d73907c04e97501` |
| `src/probos/federation/bridge.py` | `d9b134846d73604d734fa2f07266e152406c142b917fa0495cd8aaa57af8b2ef` |
| `src/probos/startup/fleet_organization.py` | `7b9e17dd24bf020ef5c2797d3601c97fac62996c5c5fa53a21a1c2a6494abbc8` |
| `src/probos/runtime.py` | `97b3a45c3841cbd8957ad0d7549233eee702e97bbbe138c45f57483ac011347b` |
| `tests/test_ad1123_bounded_federation_relay.py` | `0509cadb59628c5fcc6ecfbc72e125622c763f0ea003e9d72ae3d1ad46133c66` |

7. Confirm the live test module collects exactly **75 tests** before correction additions.
8. Confirm no staged path, deletion, or other tracked/untracked path exists. Any unexpected source/test change is a hard stop.
9. Do not fetch, pull, rebase, merge, cherry-pick, switch branch, reset, restore, clean, stash, stage, commit, push, or mutate GitHub during correction pre-flight.

### Exact active correction allowlist

The Builder may edit exactly:

1. `src/probos/federation/relay.py`
2. `src/probos/federation/bridge.py`
3. `tests/test_ad1123_bounded_federation_relay.py`

`src/probos/startup/fleet_organization.py` and `src/probos/runtime.py` are accepted and frozen at the hashes above during correction. The two active prompts are Architect-owned and must not be edited by the Builder. No production, test, tracker, config, transport, Git, or GitHub path is added to this correction allowlist. The binding prompt's eventual closeout allowlist remains conditional and unchanged.

---

## BLOCKED-review corrections — execute in this order

### Correction Step 1 — Add all C1–C3 tests first

Continue only `tests/test_ad1123_bounded_federation_relay.py`. Add the complete matrices from the binding correction packet:

- exact relay-node predicate/finalizer source+target boundaries for empty, dot, space, 129 characters, `str` subclass, and exact 128;
- outbound malformed local source and inbound malformed local target prove zero downstream work; exact-128 source→target succeeds across the bridge;
- ordinary failures independently from `callable` (focused monkeypatch allowed), real `inspect.signature`, real `inspect.iscoroutinefunction`, and real hostile callable metadata normalize to exact `ValueError("relay_topics_invalid")`; `BaseException` propagates unchanged;
- partial, sync callable object, async callable object, decorated true-async wrapper, and sync-wrapper-returning-coroutine accepted/rejected cases pin the conservative policy;
- fail-once `_inbound_handler` assignment proves startup propagation, closed relay admission, empty rate state, no gossip task, outbound false/zero work, and later successful restart/open/send/stop. A pre-task `asyncio.create_task()` failure is an allowed equivalent only if the unawaited gossip coroutine is explicitly closed without warnings.

Do not delete or weaken any existing test. Do not edit an existing committed test file.

### Correction Step 2 — Run and record the correction red

Run only the newly named correction tests in one isolated serial invocation before production correction. Record the complete command, each red test name, and its exact assertion/exception. C1 and C2 must fail against the pinned live implementation for the defects they specify. C3 may pass because it freezes the current startup ordering; report that as a green pre-existing invariant, not a missing red.

The original headline red-before remains mandatory historical evidence. Do not recreate it by reverting the worktree. Preserve its exact prior result in the final handback. If it was not retained, state that truthfully and hard-stop before tracker/archive/commit closeout; never fabricate it.

### Correction Step 3 — Implement C1 in the pure relay module and bridge

- Add exactly one compiled relay-local `^[A-Za-z0-9_-]{1,128}$` predicate and public fully annotated `is_safe_relay_node_id(value: Any) -> bool` in `relay.py`.
- Make the complete finalizer validate both `source_node` and exact payload `target_node_id` before nested detach/JSON.
- Import/reuse that same helper in bridge relay code. Outbound validates local source before every peer/topic/payload/message/transport operation. Inbound validates local target before configured-source/payload/equality/clock/rate work, validates source before configured membership, and validates wire target before equality.
- Do not change `_is_safe_node_id` or any directed-DM method/hash.

### Correction Step 4 — Implement C2 as one complete containment boundary

- Refactor only relay-topic registry inspection so every ordinary exception from `callable`, coroutine classification, signature extraction/materialization, or hostile metadata becomes a fresh exact built-in `ValueError("relay_topics_invalid")`.
- Catch `Exception`, never `BaseException`; do not include the hostile message or chain it.
- Preserve no-invocation conservative classification for partials, callable objects, and decorated wrappers exactly as binding.

### Correction Step 5 — Keep C3 production unchanged unless its test disproves the current ordering

The current `start()` shape closes relay admission, clears rate state, assigns the inbound handler, creates the gossip task, then opens admission. The fail-once assignment regression should pass without a production edit. If it fails, make only the smallest relay-lifecycle correction in `bridge.py`; do not add rollback tasks, registries, transport lifecycle calls, or exception swallowing.

### Correction Step 6 — Focused tests, ASTs, then unchanged four gates

Run the complete AD-1123 module and report its final collected/pass count. Recompute all frozen AST hashes; they must remain exact. Then run Gates 1–4 copied verbatim from the binding prompt. All prior minimums and warning baselines remain unchanged.

Only after these correction gates and a new Architect implementation review are green may the original Steps 8–9 tracker/archive/stage/commit procedure run. Until then: no tracker, archive, Git, or GitHub mutation.

---

## Binding architecture in one page

- Wire type: exact `FederationMessage.type == "relay_one_way"`.
- Payload: exact five keys `{relay_version, target_node_id, topic, payload, hop_count}`.
- Version/hop: exact built-in integers `1` and `0`.
- Addressing: exactly one configured, connected, non-self target via existing `send_to_peer()`.
- Semantics: immutable local `FederationRelayTopic(name, validate_payload, sink)` registry, max 16.
- Registry input is an exact built-in tuple and stored behind `MappingProxyType`; validator is exact one-parameter sync callable, sink exact two-parameter async callable.
- One relay-local exact `^[A-Za-z0-9_-]{1,128}$` predicate owns finalizer source/target plus outbound local-source and inbound local-target admission; exact built-in strings only.
- Callable contract introspection is fully contained: ordinary inspection exceptions become exact `ValueError("relay_topics_invalid")`, lifecycle `BaseException` propagates, and ambiguous async callables reject without invocation.
- Sender can send only a locally registered topic; receiver can deliver only to its locally registered exact topic.
- Sink signature: `await sink(validated_source_node, detached_payload)`.
- Source is server-owned from `FederationMessage.source_node`; payload cannot author provenance.
- Payload is exact-built-in JSON only with bounds 8 depth / 512 nodes / 4,096 chars per key/string / 32,768 aggregate UTF-8 / signed-64 ints / 32,768 compact final envelope bytes.
- Final bytes cover the complete normalized five-field `FederationMessage` wire object; sender-local timestamp is finite but never used as age/order/replay authority.
- Binary, cycles, nonfinite, subclasses, secret keys, credential/data/private-key string prefixes are rejected.
- Validators see independent detached copies and must return literal `True`; they cannot mutate transport/sink payload. Topic registration rejects bad signatures and sync sinks.
- Invalid input and ordinary failure drop with no response/retry/fallback. Outbound transport and real task cancellation propagate; a sink directly raising `CancelledError` with `current_task().cancelling() == 0` degrades as plugin failure.
- Receiver drops above 64 accepted messages/second per configured source/topic before payload/sink work; this is bounded admission state, not a delivery queue.
- No fanout, message queue, task, timer, ack, correlation, response, trust, Hebbian, IntentBus, EventType, runtime dispatch, or rebroadcast.
- Production composition passes `relay_topics=()`; #659 remains open/unblocked.
- Failed bridge start leaves relay admission closed, rate state empty, and no gossip task; the same bridge can later start successfully and reopen.

---

## Original build execution order — retained for audit and conditional closeout

The original Steps 1–5 below describe how the accepted live implementation was created. Do **not** rerun or recreate them during correction. They remain the audit contract and govern any missing original evidence; correction work follows the higher-precedence steps above.

### Step 1 — Write the complete test module first

Create only `tests/test_ad1123_bounded_federation_relay.py`. Include every case listed in binding Section 4, including the two-real-`organize_fleet()`/shared-`MockNATSBus` headline test, decoy/unregistered topics, malicious payload matrices, cancellation/error/lifecycle/no-loop/no-response/no-learning assertions, NATS/ZeroMQ/mock parity, and frozen AST hashes.

Use the binding's strict exact-schema `test.telemetry.v1` validator for all normal fixtures and the headline. Do not use `lambda _: True` except nowhere; specialized negative tests install explicit rejecting/raising/mutating validators.

Use real `SystemConfig`, `IntentBus`, `PoolGroupRegistry`, `MockNATSBus`, `NATSFederationTransport`, `FederationBridge`, and `organize_fleet()` at composition boundaries. Do not use permissive `MagicMock` fixtures for config, bridge, transport, or topic registration. Narrow fakes are allowed only to record a specific dependency contract.

### Step 2 — Run the mandatory red-before test

Run only the headline test under a unique isolated environment:

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_red_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1123_bounded_federation_relay.py::test_two_organized_bridges_deliver_registered_topic_to_exact_receiver_sink_only -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected: collection/import or assertion failure because AD-1123 production symbols do not exist. Save the output to an ignored `logs/ad1123_red.txt` if desired. Record; do not weaken the test.

**Correction directive:** this original red must still be reported exactly, but must not be recreated by reverting/discarding the live implementation. If its output was not retained, report the evidence gap and stop before closeout.

### Step 3 — Implement the pure relay module

Create `src/probos/federation/relay.py` exactly to the binding spec.

Critical review points:

- no recursive traversal;
- exact built-ins only;
- built-in descriptor access only after exact-type check;
- exact container-length lower-bound rejection before iteration so duplicates/invalid entries cannot extend work;
- active-container IDs detect cycles;
- node count includes dict keys and values/containers;
- per-string + aggregate UTF-8 accounting applies to keys and values;
- finite float + signed-64 int only;
- secret key/prefix tests occur during bounded traversal;
- generic JSON serialization only after bounded detach;
- final cap covers the complete normalized five-field wire object, not only the user or five-key relay payload;
- complete-finalizer coverage proves the 32,768-byte cap is independently active despite the same aggregate string budget;
- no payload value in logs;
- no runtime/intent/event/config/transport import.

Run the new module after this step; bridge tests may still fail because the bridge API is not implemented.

### Step 4 — Extend FederationBridge additively

Modify only the binding sections of `src/probos/federation/bridge.py`:

- constructor topic tuple and immutable registry;
- relay lifecycle admission;
- `relay_one_way()`;
- one inbound dispatch branch;
- terminal `_handle_relay_one_way()`.

Do not edit the five frozen bridge methods. Do not alter existing lines/branches in `start()`, `stop()`, or `handle_inbound()` except for additive relay lifecycle/dispatch statements.

Run the AD-1123 module. Fix only failures inside the allowlist.

### Step 5 — Wire explicit empty production policy

Modify `src/probos/startup/fleet_organization.py` and `src/probos/runtime.py` only:

- backward-compatible keyword-only `relay_topics=()` on `organize_fleet()`;
- pass it into the sole bridge constructor;
- sole runtime caller passes `relay_topics=()`.

Do not edit the five existing direct test callers. The default empty tuple preserves them; the runtime call is explicit so production policy remains visible.

### Step 6 — Run focused module, then all four gates

First run editor diagnostics on every changed Python file and compile the changed production/test modules with the configured venv. Any new syntax/type/lint diagnostic attributable to AD-1123 is a blocker.

First:

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1123_module_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1123_bounded_federation_relay.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Then run Gates 1–4 copied verbatim from the binding prompt. Do not substitute xdist, live services, a shared data directory, or a partial file list.

Expected minimums:

| Gate | Minimum |
|---|---:|
| Gate 1 | 91 + AD-1123 module count |
| Gate 2 | 333 + AD-1123 module count |
| Gate 3 | 77, only the 5 recorded BF-326 warnings |
| Gate 4 | 243 + AD-1123 module count, only the 2 recorded dependency warnings |

Any new warning is a failure. A serial failure in an unchanged existing test is a hard stop unless the failure is clearly environmental and independently reproduces on clean HEAD.

### Step 7 — Source and diff audits

Run:

```powershell
git diff --check
git diff --stat
git status --short
git diff -- src/probos/federation/nats_transport.py src/probos/federation/transport.py src/probos/federation/mock_transport.py src/probos/federation/telemetry_relay.py src/probos/types.py src/probos/events.py src/probos/protocols.py src/probos/mesh/nats_bus.py src/probos/routers/agents.py src/probos/startup/shutdown.py
```

The last command must be empty.

Recompute every frozen AST hash. All must equal the binding table.

Search the changed production code for forbidden shapes:

```powershell
Select-String -Path src/probos/federation/relay.py,src/probos/federation/bridge.py -Pattern 'IntentMessage|IntentBus|EventType|_emit_event|send_to_all_peers|record_outcome|hebbian|create_task|Queue\(|request_peer|receive_with_timeout|intent_response|relay_one_way.*relay_one_way'
```

Any occurrence in the new relay module/handler must be justified by test/source guards; executable forbidden calls are a hard stop.

### Step 8 — Tracker closeout

Only after all gates/audits pass:

- update `PROGRESS.md`, `DECISIONS.md`, and `docs/development/roadmap.md` exactly as binding;
- state #659 **unblocked/open**, not closed;
- state configured-peer source admission is not cryptographic auth;
- state AD-1123 new top-level and BF-672 unchanged BF ceiling;
- include exact final gate counts/warnings;
- move the two prompts unchanged to `prompts/archive/`.

Do not create a build report unless explicitly requested; it is outside the exact allowlist.

### Step 9 — Stage and commit

Stage only the final allowlist, with the prompt paths now under `prompts/archive/`. Never stage the ignored issue draft or test logs.

Run:

```powershell
git diff --cached --stat
git diff --cached --check
git status --short
```

No unexpected file and no >200-line deletion outside prompt moves is allowed.

Commit subject:

```text
AD-1123: add bounded federation one-way relay
```

Do not push unless the Captain separately directs it. Do not mutate GitHub.

---

## Hard-stop conditions

1. HEAD/origin/worktree or any live pre-correction hash differs from the exact correction pre-flight contract before Builder edits.
2. Any frozen method/hash differs before work or after implementation.
3. An existing test file requires modification.
4. Correct implementation requires a transport, `FederationMessage`, `NATSBusProtocol`, IntentBus, EventType, avatar WS, config, shutdown, or startup-result edit.
5. A topic must be dynamically registered after bridge construction to make the primitive work.
6. A receiver needs arbitrary callback/event/intent names from the wire.
7. A response, correlation map, queue, retry, task, timer, rebroadcast, or fanout becomes necessary.
8. Payload bounds cannot be enforced before generic serialization/unbounded traversal.
9. Any ordinary payload/validator/sink failure leaks a payload value or raises through the inbound callback.
10. Cancellation is swallowed.
11. Any trust/Hebbian/consensus/episodic side effect occurs.
12. Gate 3 gains a warning or changes avatar behavior.
13. Gate 4 reveals shutdown order/lifecycle regression.
14. #659 would be closed without telemetry producer/sink wiring.
15. C1 requires a second node predicate, bridge-private import, config schema change, or directed-DM edit.
16. C2 requires invoking a callable, swallowing `BaseException`, accepting a sync wrapper as async, or surfacing hostile metadata text.
17. Failed startup leaves relay admission open, rate state populated, or a gossip task alive, or successful restart cannot reopen.
18. The original headline red is reported from memory/fabricated rather than retained evidence.
19. Correction needs any edit outside the exact three active paths before Architect re-review.

---

## Test-review checklist

Before closeout, answer yes to every item:

- [ ] Red-before headline failed for missing AD-1123 production surface.
- [ ] Headline uses two real organized bridges and one shared `MockNATSBus`.
- [ ] One-peer addressing and third-node decoy are proven.
- [ ] Receiver exact sink and decoy/unregistered topic behavior are proven.
- [ ] Unknown/self/spoofed source and wrong target drop with no response.
- [ ] Exact schema/version/hop/topic registration are proven.
- [ ] Depth/node/string/UTF-8/complete-final-byte/int boundary pairs are proven.
- [ ] Hostile subclasses are never invoked.
- [ ] Cycles, nonfinite, binary, objects, secret keys/prefixes reject.
- [ ] Million-item work is bounded before generic JSON.
- [ ] Validator literal-True/mutation-isolation/error and sink ordinary-error, direct-plugin-cancel containment, and real inbound/outbound task-cancellation propagation are proven.
- [ ] Transport exception/cancellation/no-response contract is proven.
- [ ] Per-source/topic 64/s drop, malformed-no-capacity, isolation, recovery, empty-key pruning, finite cardinality, no-unknown-allocation, and start/stop-clear are proven.
- [ ] Stop/restart/post-stop inbound/outbound behavior is proven.
- [ ] No loop/rebroadcast/fanout/task/message-queue/retry is proven.
- [ ] Trust/Hebbian remain untouched.
- [ ] NATS/ZeroMQ/mock parity is proven.
- [ ] Legacy and AD-730-4 AST/behavior remain unchanged.
- [ ] Direct-construction/runtime empty-registry golden rejects relay with zero transport/traversal/rate/sink work.
- [ ] One relay-local predicate rejects empty/dot/space/129/subclass and accepts exact-128 for source and target through pure finalizer and bridge paths.
- [ ] Invalid outbound local source and inbound local target stop before finalizer/validator/sink/rate/transport work as applicable.
- [ ] Ordinary callable/introspection/hostile-metadata failures normalize to exact `ValueError("relay_topics_invalid")`; `BaseException` propagates unchanged.
- [ ] Partial, sync/async callable-object, true async decorated wrapper, and sync coroutine-returning wrapper cases pin conservative behavior without probe invocation.
- [ ] Fail-once startup leaves relay closed/rate empty/no gossip/outbound false; later start opens and sends.
- [ ] Correction-red results and the retained original headline red are both reported truthfully.
- [ ] Four gates meet minimums with no new warnings.

---

## What this execution must not build

- #659 telemetry semantics/wiring or issue closure.
- Avatar producer, remote sink, `origin_mesh_id`, WS/UI changes.
- Arbitrary intent/event/runtime injection.
- Dynamic/wildcard/remote topic registration.
- Request/reply, ack, retry, replay, persistence, backfill, ordering guarantees.
- New transport/NATS/ZeroMQ API or serializer behavior.
- Authentication/signing/JWT/CURVE.
- Trust/Hebbian/consensus/episodes/events/stats.
- Config/YAML/dependency/package/export changes.
- Any refactor adjacent to the minimal relay primitive.

---

## Final handback format

Return a compact table with:

- commit hash/subject or “uncommitted”;
- files changed;
- retained original red-before command/result;
- correction-red command and per-test results, distinguishing any C3 already-green invariant;
- AD-1123 final collection/pass count;
- Gates 1–4 exact pass/warning counts;
- frozen AST hash audit result;
- final SHA-256 for every implementation/test file plus both active prompt documents;
- #659 status “unblocked/open”;
- AD/BF ceilings;
- deviations (must be none unless Architect approved a hard-stop revision).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
