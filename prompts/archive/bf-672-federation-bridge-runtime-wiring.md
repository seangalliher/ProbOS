# BF-672 — Production-wire only the FederationBridge attachment resolver

**Verdict:** APPROVED FOR BUILDER HANDOFF
**One-line:** Replace the bridge's broad dormant runtime handle with one narrow optional attachment-resolution callback, inject that callback through the real Phase-3 production construction path, and leave incomplete AD-479e designed-agent reconstruction explicitly dormant.

**Status:** Build-ready on the exact clean base below
**Type:** Bug fix — **BF-672**; no new AD and no `DECISIONS.md` or roadmap entry
**Parent GitHub issue:** seangalliher/ProbOS#638 — https://github.com/seangalliher/ProbOS/issues/638
**Temporary issue draft:** `logs/bf672_issue_body.md`; do not mutate GitHub
**Exact base HEAD:** `34a3425c5e1a6217a3cab2564ea437cd7de6426b`
**Base commit:** `BF-670: replace IntentBus re-subscribe memberships (closes #1037)`
**Numbering verified:** current highest shipped entries are **AD-1122** and **BF-671**; **BF-672 is unused and is the next sequential bug-fix number**
**Dependencies:** AD-443e, AD-479e, AD-517, AD-637e, AD-720, AD-731, AD-731a-1, AD-731a-1c, BF-287
**License disposition:** none — dependency wiring only; no external code or dependency
**Estimated tests:** 7–12 additions/updates in two existing test files; no new source or test file

## Scope

Repair the missing production dependency for the already-shipped AD-731a-1c inbound attachment resolver, without activating the incomplete AD-479e designed-agent reconstruction path.

The implementation must guarantee:

1. a `FederationBridge` constructed by the real `organize_fleet()` production path receives a narrow optional async attachment-resolution callback;
2. the callback is installed before `bridge.start()` exposes `handle_inbound` to the transport;
3. `_handle_intent_request()` invokes that callback, when present, after constructing the inbound `IntentMessage` and before `intent_bus.broadcast(..., federated=False)`;
4. the runtime-side callback delegates to the existing `resolve_missing_attachments(runtime, params, source_node)` unchanged;
5. when `attachments.auto_resolve_remote_enabled=False` (the default), the callback returns before attachment-store method or network work, preserving default-off behavior;
6. when federation is disabled, no bridge and no callback are created;
7. when the callback is absent, inbound processing remains the pre-BF-672 no-resolution path and still broadcasts/responds normally;
8. ordinary callback exceptions are contained at the bridge boundary so the inbound broadcast and response still complete, while `asyncio.CancelledError` propagates unchanged per repository async discipline;
9. the callback supports empty/malformed params and empty source node through the existing guarded resolver and never blocks the broadcast;
10. the broad `_runtime_ref` field and `set_runtime_ref()` are removed from `FederationBridge` so no startup code can accidentally activate unrelated consumers;
11. AD-479e `_reconstruct_designed_agent()` preserves its current production-observable dormant result: `"no_runtime_handle"`; its tests no longer manually wire a fake runtime to manufacture an unreachable production state; and
12. send-side `vision_messages` stripping, the `attachment_ref` wire format, attachment serving/fetch integrity, mobility certificate/chain behavior, transports, gossip, IntentBus federation, startup ordering, and shutdown remain unchanged.

No send-side un-strip, NATS Object Store, designed-agent rehydration redesign, runtime back-reference, self-mod API promotion, config, endpoint, protocol, event, UI, dependency, AD, or parent-issue closeout is authorized.

---

## Problem, live evidence, and verified root cause

At the exact base:

- `FederationBridge.__init__()` initializes `_runtime_ref = None` at `src/probos/federation/bridge.py:61`.
- `set_runtime_ref()` exists at `bridge.py:78-84`, but an AST inventory of every production Python file finds **zero calls** to it.
- The same broad handle has exactly two reads: the AD-731a-1c resolver call at `bridge.py:241` and the AD-479e reconstruction path at `bridge.py:531`.
- `resolve_missing_attachments()` starts at `attachment_resolve.py:99`; it returns `0` immediately for `runtime is None`. Therefore the receive resolver is dead in production even when the operator opts into `auto_resolve_remote_enabled=True`.
- All existing AD-731a-1c tests call `resolve_missing_attachments()` directly with a hand-built runtime-shaped object. They prove resolver behavior, not production wiring.
- All passing AD-479e reconstruction tests call `bridge.set_runtime_ref(fake_runtime)` manually. They prove a test-only state, not a live startup state.
- There is exactly one production `FederationBridge(...)` construction: `startup/fleet_organization.py:207`. That phase starts the bridge at `:216`, then returns it to `ProbOSRuntime.start()`; the runtime assigns it at `runtime.py:1961`.
- `organize_fleet()` runs before cognitive services. `self_mod_pipeline` is assigned only at `runtime.py:1993`; `SelfModManager` is constructed in finalization and assigned only at `runtime.py:2527`. A startup call to `set_runtime_ref(self)` near `runtime.py:1961` would expose a partially initialized runtime.
- The actual runtime has no public `agent_designer` or `code_validator` attributes. `AgentDesigner` exposes no `register_designed_template_from_payload()` method, and `CodeValidator` exposes no `validate_text()` method. The bridge's AD-479e consumer depends on APIs that do not exist in live production.
- The real self-mod dependencies live behind `SelfModificationPipeline`: private `_designer`/`_validator`, with only a public `validator` property. Reaching through those privates would violate Open/Closed and Law of Demeter, and inventing the missing payload-registration API is a separate architectural feature.
- Tracked cluster configs `config/node-1.yaml` and `config/node-2.yaml` enable both federation and self-modification. Broad runtime wiring would therefore make the dormant AD-479e path newly reachable in the canonical multi-node setup, even though its production dependencies are incomplete.
- `FederationConfig.enabled` defaults False, `AttachmentsConfig.auto_resolve_remote_enabled` defaults False, and `A2APeerConfig.node_id` defaults empty. The narrow attachment callback can therefore be installed safely while actual store/network activity remains opt-in.
- `shutdown.py:913-915` stops the bridge before the transport. The proposed callback owns no resource/task/client and requires no teardown or shutdown-order change.

### Counterfactual fail-before proof required

Before production edits, add a test that invokes the real `organize_fleet()` construction path with:

- real `SystemConfig`/`FederationConfig`/`AttachmentsConfig`/`A2APeerConfig` values;
- a connected in-memory `MockNATSBus` so `organize_fleet()` constructs the real `NATSFederationTransport` and `FederationBridge` without ZeroMQ or live network;
- a real `IntentBus(SignalManager())`; install a real local subscriber whose handler records whether the blob exists when broadcast reaches it (do not replace the bus with a mock);
- a real `FilesystemAttachmentStore` on `tmp_path` exposed only through the injected runtime-side callback closure.

Replace the runtime adapter on a lightweight runtime-shaped composition owner with a recording async bound callback **before** calling `organize_fleet()`; the callback records the exact `(params, source_node)`, writes a known blob to the real store, and returns `1`. Send an inbound `intent_request` through the transport-installed handler and assert the blob is stored **before** the real local subscriber observes it. This proves production callback threading/order without calling the setter/resolver directly or using live HTTP.

Separately prove that the real runtime adapter delegates once to `resolve_missing_attachments(self, params, source_node)` by patching that imported function with an async recorder at the adapter unit seam. Existing direct resolver/fetch tests retain `httpx.MockTransport` and remain the no-network proof for enabled mapped fetch, auth, integrity, MIME, size, idempotence, and failure behavior.

This must fail on exact HEAD without any test call to `set_runtime_ref()` and without constructing a bridge directly. A test that manually calls a setter or directly calls `resolve_missing_attachments()` is not the headline proof.

---

## Premise decision: direct setter vs narrow seam vs split prerequisite

### Rejected — direct `set_runtime_ref(self)` wiring

Do not wire the existing broad setter.

It would simultaneously expose:

- AD-731a-1c attachment resolution; and
- AD-479e designed-agent reconstruction.

That is not behavior-neutral. The second consumer is not production-ready: its expected runtime attributes and registration API do not exist. The canonical node configs enable federation + self-mod together, so this is a live activation risk, not a theoretical one.

### Rejected — full split prerequisite that also completes AD-479e

Do not bundle an AD-479e redesign into #638.

Completing cross-node designed-agent reconstruction would require a separate architecture decision covering a typed payload, validation, sandbox execution, registration/pool/trust lifecycle, approval/governance, persistence, rollback, and event semantics. None belongs to the cross-host attachment-distribution issue.

### Selected — narrow injected attachment resolver; explicit dormant AD-479e

Use one narrow callback seam owned by `FederationBridge`:

```text
AttachmentResolver = Callable[[dict[str, Any], str], Awaitable[int]]
```

The bridge receives `attachment_resolver: AttachmentResolver | None = None`. `ProbOSRuntime.start()` supplies a closure to `organize_fleet()` that captures `self` and delegates to `resolve_missing_attachments(self, params, source_node)`; `organize_fleet()` passes it into the one bridge constructor before start.

This preserves layer discipline:

- federation stays independent of `ProbOSRuntime` and cognitive/self-mod internals;
- the runtime composition root owns cross-layer dependency stitching;
- the existing resolver remains the single implementation of config/store/peer/fetch policy;
- the bridge sees only the operation it needs; and
- no construction cycle exists because the closure captures the already-constructed runtime without dereferencing it until an inbound message arrives.

Remove `_runtime_ref` and `set_runtime_ref()`. Make `_reconstruct_designed_agent()` return `"no_runtime_handle"` directly with an explicit BF-672/AD-479e comment that full production rehydration is deferred to its own design. This is behavior-preserving relative to every production boot at HEAD, where `_runtime_ref` is always None.

---

## Pinned design decisions

### DD-1 — Narrow callback type, no runtime object

In `src/probos/federation/bridge.py`:

- define a private/module-level type alias using `Callable`, `Awaitable`, and existing `Any` imports;
- add optional keyword `attachment_resolver: Callable[[dict[str, Any], str], Awaitable[int]] | None = None` at the end of `FederationBridge.__init__()`;
- store it as `_attachment_resolver`;
- remove `_runtime_ref` and remove `set_runtime_ref()` entirely;
- do not import `ProbOSRuntime`, `AttachmentStore`, config models, `httpx`, cognitive classes, or startup modules into the bridge.

Constructor backward compatibility is required: every direct test construction that omits the callback must keep working unchanged.

### DD-2 — Bridge boundary owns fail-open inbound continuation

In `_handle_intent_request()`:

1. construct `IntentMessage` exactly as today;
2. snapshot/read `_attachment_resolver`;
3. if it is not None, await it with `(intent.params, message.source_node)`;
4. catch `asyncio.CancelledError` separately and re-raise it unchanged;
5. catch ordinary `Exception`, log the existing contextual WARNING with traceback, then continue;
6. broadcast locally with `federated=False` and build/send the response exactly as today.

No callback means no resolver call and no new log. Return count is intentionally ignored; storage state is the data-plane effect. Do not add metrics/events/status fields.

Ordinary failure containment here preserves AD-731a-1c's “attachment fetch never blocks the inbound broadcast” contract. Cancellation is different: it is lifecycle control, not a degraded fetch result, and must propagate so an owner can stop the inbound operation cleanly.

### DD-3 — Runtime-side adapter uses the shipped resolver unchanged

Add one fully typed private runtime method near the existing federation methods:

```text
async def _resolve_federated_attachments(
    self,
    params: dict[str, Any],
    source_node: str,
) -> int:
    from probos.federation.attachment_resolve import resolve_missing_attachments
    return await resolve_missing_attachments(self, params, source_node)
```

Requirements:

- no duplicate resolver logic;
- no store or HTTP client construction in the adapter;
- no catch/log wrapper in the adapter (the resolver and bridge already own their tiers);
- no public method/property;
- no direct bridge mutation after construction;
- no callback task or lifecycle resource.

### DD-4 — Thread the callback through the real Phase-3 constructor

Extend `organize_fleet()` with a required keyword-only callback parameter matching DD-1. Pass it to the one `FederationBridge(...)` construction.

At the sole runtime call site, pass `attachment_resolver_fn=self._resolve_federated_attachments` (the exact parameter name may be `attachment_resolver_fn` or `attachment_resolver`, but it must be typed and unambiguous).

Update the two direct test callers of `organize_fleet()` to pass an explicit inert async callback or `None` according to the final signature. Do not add a default to hide missing composition-root updates unless required by a verified external public API; `organize_fleet()` is an internal startup function and all three call sites are tracked.

The callback must be in the bridge constructor before `await bridge.start()`. Do not assign a private bridge field after start and do not reintroduce a setter.

### DD-5 — AD-479e remains explicitly dormant

Refactor `_reconstruct_designed_agent()` only enough to remove the dead broad-runtime branch:

- keep its signature and async return contract;
- return `"no_runtime_handle"` immediately;
- retain an explicit comment/docstring that BF-672 removes the broad runtime handle because its only production use was missing, and AD-479e rehydration requires a future narrow, typed, governance-complete seam;
- remove test-only branches that fabricate `agent_designer`, `code_validator`, `register_designed_template_from_payload`, and `emit_event` on `SimpleNamespace` runtimes.

Keep these AD-479e behaviors unchanged:

- outbound transfer with no payload preserves baseline wire shape;
- outbound transfer with payload still carries `designed_agent_payload`;
- accepted certificate/chain transfer still completes;
- a truthy incoming payload appends `designed_agent_note=no_runtime_handle` to the transfer message;
- the dormant branch exposes no registration dependency and emits no receive event.

Do not remove the wire field, event enum, request parameter, or transfer hook. This BF quarantines activation; it does not redesign or delete the forward marker.

### DD-6 — Default-off and empty/error boundaries

Behavioral tests must prove:

- federation disabled: no bridge and the callback is never observed;
- federation enabled + attachment flag off: real production wiring exists, but resolver performs zero attachment-store method/network work and local broadcast proceeds;
- flag on + no attachment refs: zero HTTP/store write and broadcast proceeds;
- flag on + empty/no-ref params / empty source node / unmapped sender: zero fetch and bridge broadcast proceeds; malformed non-dict params remain covered at the direct resolver boundary (the wire constructor normalizes missing params to `{}`);
- the unchanged direct resolver/fetch suite proves flag on + mapped sender + missing SHA fetches, verifies, and stores;
- already-local SHA: no fetch, broadcast sees existing blob;
- HTTP error/tamper/store error: no stored corrupt blob; broadcast/response still proceeds;
- injected callback ordinary error: broadcast/response still proceeds;
- injected callback `CancelledError`: cancellation propagates and no broadcast/response occurs after the cancellation point;
- no callback: bridge behavior remains valid and no resolver call occurs.

Use real config/store objects. Existing direct resolver/fetch tests use `httpx.MockTransport`; do not add live HTTP. No MagicMock at the attachment or config boundary.

### DD-7 — Lifecycle and shutdown remain unchanged

The callback owns no client/task/store and needs no `stop()`.

Do not edit:

- `FederationBridge.start()` / `stop()` gossip lifecycle;
- transport start/stop ordering;
- `IntentBus.set_federation_handler()`;
- `startup/shutdown.py` federation order;
- runtime `_startup_complete` timing;
- NATS/ZeroMQ/Mock transport code; or
- attachment-store lifecycle/cache.

The runtime closure may outlive Phase 3 only as long as the bridge, which is owned by the same runtime and stopped before the transport. There is no ownership cycle requiring teardown.

---

## Exact file allowlist

### Production files the Builder may modify

- `src/probos/federation/bridge.py` — narrow callback; remove broad runtime handle/setter; keep AD-479e dormant.
- `src/probos/startup/fleet_organization.py` — typed callback parameter and constructor injection before start.
- `src/probos/runtime.py` — private adapter and sole production callback supply.

### Existing tests the Builder may modify

- `tests/test_ad731a_1c_auto_resolve.py` — production-construction red-before integration plus default-off/empty/error/cancellation boundaries.
- `tests/test_ad479_federation_hardening.py` — remove test-only setter activation; pin AD-479e dormant transfer behavior.
- `tests/test_federation_nats.py` — only if needed to update the direct `organize_fleet()` signature and/or host the real NATS startup seam; no unrelated cleanup.
- `tests/test_ad447_phase_gates_pool_group.py` — mechanical direct-call signature update only if required.

### Architect documents already present; retain byte-for-byte during build

- `prompts/bf-672-federation-bridge-runtime-wiring.md`
- `prompts/bf-672-federation-bridge-runtime-wiring-execution.md`

### Ignored Architect issue draft; retain byte-for-byte and do not stage

- `logs/bf672_issue_body.md`

### Conditional closeout only, after green gates and final Architect review

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config/YAML, workflow, standing order, UI, dependency/lockfile, tracker, roadmap, decision, era, archive, data, Git, or GitHub path is authorized.

Reference-only gate files are not authorized for modification. If a required fix reaches one, stop.

---

## Ordered implementation

### Section 1 — Add counterfactual fail-before production-wiring proof

Before production edits:

1. add the `organize_fleet()` integration described above;
2. do not directly construct `FederationBridge` in the headline test;
3. do not call `set_runtime_ref()` or mutate any bridge private;
4. deliver through the transport-installed inbound handler after `organize_fleet()` has started the bridge;
5. assert store presence at the instant local broadcast runs;
6. run only that node and record its exact failure on HEAD—expected: the blob is absent because production construction supplied no resolver dependency.

Also add a source/AST contract assertion that production has no call to `set_runtime_ref()` at HEAD only as supporting evidence, never as the headline proof.

### Section 2 — Introduce the narrow callback and remove the broad handle

Implement DD-1 and DD-2 in `bridge.py`.

Do not change message shapes, dispatch switch, response serialization, forward intent, transport strip, mobility certificate logic, gossip, trust/Hebbian outcome recording, add-peer, or status output.

### Section 3 — Add the runtime adapter and production construction wire

Implement DD-3 and DD-4.

The callback must be supplied before bridge start. Update every `organize_fleet()` call site explicitly. Do not create a late setter, use `hasattr`, reach through a private runtime member, or pass the entire runtime object into `organize_fleet()`/bridge.

### Section 4 — Quarantine dormant AD-479e behavior

Implement DD-5 and update `TestShareDesignedAgent`:

- delete tests whose only setup is manual `set_runtime_ref()` with phantom production APIs;
- add/retain transfer-level coverage proving valid identity transfer + payload returns accepted with `designed_agent_note=no_runtime_handle`; separately pin that no `FEDERATION_DESIGNED_AGENT_RECEIVED` event is emitted;
- preserve outbound payload/no-payload tests;
- no cognitive/self-mod production edit.

### Section 5 — Complete boundary/default-off tests

Implement DD-6 using real configs/store and no-network transport seams.

At minimum include named tests for:

- `test_production_organize_fleet_wires_attachment_resolver_before_broadcast`;
- `test_production_wiring_flag_off_touches_no_store_or_network`;
- `test_production_wiring_no_refs_or_empty_source_broadcasts_without_fetch`;
- `test_attachment_resolver_exception_still_broadcasts_and_responds`;
- `test_attachment_resolver_cancelled_propagates_without_broadcast`;
- `test_bridge_without_resolver_preserves_inbound_behavior`;
- `test_incoming_designed_payload_remains_dormant_without_runtime_handle`.

Existing direct resolver integrity/idempotence/tamper tests remain valuable and should stay unchanged unless a narrow helper refactor requires a mechanical update.

### Section 6 — Run exact gates and three-pass review

Run only the exact serial/isolated commands below. Do not run full `tests/`, xdist, live network/LLM, or live platform data.

### Section 7 — Architect-controlled closeout

Builder returns an uncommitted implementation and report. After Architect review only:

1. prepend one concise BF-672 closeout to `PROGRESS.md` describing the narrow callback, production-construction proof, explicit AD-479e dormancy, exact test counts, and #638 prerequisite status;
2. state **AD-1122 remains the AD ceiling and BF-672 becomes the BF ceiling**;
3. state #638 remains open until its remaining send-side acceptance criteria are separately completed—BF-672 itself does not close #638;
4. include both unchanged BF-672 prompt docs;
5. leave `logs/bf672_issue_body.md` ignored/untracked and never stage it;
6. do not edit `DECISIONS.md`, roadmap, era files, config YAML, or GitHub;
7. archive the two prompt docs only after approval, not during Builder execution; and
8. stage/commit only if a later Architect/orchestrator instruction explicitly authorizes it.

---

## Required behavioral tests

### A. Production construction and ordering

1. Real `organize_fleet()` + real `IntentBus(SignalManager())` + connected `MockNATSBus` builds a bridge with the callback supplied through the constructor—no setter/private mutation; a separate source/AST contract pins the sole `ProbOSRuntime.start()` call to `self._resolve_federated_attachments`.
2. The production-injected callback stores before local broadcast sees the intent, and the runtime adapter delegates to the shipped resolver with runtime/params/source intact.
3. Response is still sent after local broadcast.
4. `intent_bus.set_federation_handler(bridge.forward_intent)` remains wired.
5. Federation disabled constructs no bridge and performs no callback work.

### B. Default-off, empty, and honest-degrade boundaries

6. Flag off: zero HTTP and zero attachment-store method call (use an exploding store sentinel), broadcast/response unchanged.
7. Empty dict, malformed/non-dict params, no SHA, empty source, and unmapped sender through the real resolver return without fetch; bridge-level empty/no-ref/source-miss cases still broadcast/respond.
8. Already-local SHA: no HTTP; broadcast sees it.
9. Peer 404/500, tampered bytes, missing content type, bad MIME, oversize, and store failure preserve existing rejection/non-store semantics and do not block broadcast.
10. Callback ordinary exception is logged/degraded; broadcast/response complete.
11. Callback `CancelledError` propagates unchanged; no broadcast/response occurs after cancellation.
12. No callback: no resolution attempt; broadcast/response complete.

### C. Dependency/layer contract

13. Bridge contains no `_runtime_ref`, `set_runtime_ref`, `ProbOSRuntime` import, cognitive/self-mod import, attachment-store import, or HTTP client construction.
14. Runtime adapter delegates once to `resolve_missing_attachments(self, params, source_node)` and duplicates no policy.
15. `organize_fleet()` takes the narrow callback, not a runtime object.
16. Callback is installed before `bridge.start()`.
17. The sole production runtime call passes `self._resolve_federated_attachments`; all direct `organize_fleet()` test call sites are updated, with no defensive `getattr`/`hasattr` for the required internal callback.

### D. AD-479e activation quarantine

18. No test manually calls `set_runtime_ref()`; method no longer exists.
19. Outbound no-payload transfer remains byte-compatible.
20. Outbound payload transfer still carries the field.
21. Accepted inbound transfer with payload appends `designed_agent_note=no_runtime_handle`; the dormant branch has no registration dependency and emits no `FEDERATION_DESIGNED_AGENT_RECEIVED` event.
22. Identity chain/certificate import and slot behavior remain unchanged.
23. No `AgentDesigner`, `CodeValidator`, `SelfModificationPipeline`, `SelfModManager`, spawner, pool, trust, approval, persistence, or warm-boot production edit.

### E. Regression surfaces

24. Send-side `vision_messages` still strip in federation; original `IntentMessage` remains untouched.
25. AD-731 `attachment_ref` bus shape and LLM dereference tests remain green.
26. AD-731a-1 serve/fetch auth, hash, MIME, and size gates remain green.
27. NATS/Mock/ZeroMQ bridge interface behavior, gossip, forwarding, loop prevention, mobility, runtime status, and shutdown order remain green.
28. No new task/client/resource requires shutdown cleanup.

---

## Exact test gates

Run from `D:\ProbOS`.

Both commands use a unique temporary data directory, local/offline embeddings, serial execution, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error.

Clean-HEAD Architect baselines at `34a3425c`:

| Gate | Baseline |
|---|---:|
| Focused federation/attachment/mobility | **228 passed in 56.64s** |
| Runtime/shutdown blast | **44 passed in 206.93s** |

Post-build counts will increase. Report exact pass/fail/skip counts and durations.

### Focused — resolver, serve/fetch, wire shape/strip, AD-479e, bridge/transports, mobility, startup callers

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf672_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py tests/test_ad731_attachment_ref_wire_format.py tests/test_bf265_transport_stripped_params.py tests/test_ad479_federation_hardening.py tests/test_federation.py tests/test_federation_nats.py tests/test_ad443_mobility.py tests/test_ad447_phase_gates_pool_group.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius — runtime boot, shutdown ordering/idempotency, app mount

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf672_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_runtime.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py tests/test_distribution.py::TestFastAPIEndpoints::test_create_app_returns_fastapi -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute `-n auto`, `-n 4`, full `tests/`, live network/LLM, or live runtime data.

---

## Acceptance criteria

1. Current base is exactly `34a3425c5e1a6217a3cab2564ea437cd7de6426b`; current highest is AD-1122/BF-671; BF-672 is unused and selected; initial status contains exactly the two BF-672 prompt docs while the ignored issue draft exists.
2. Headline test fails before production edits through real `organize_fleet()` production construction, without manually calling a setter or direct resolver.
3. `FederationBridge` receives only an optional narrow async attachment callback; it receives no runtime object.
4. Callback is constructor-injected before `bridge.start()` and production-wired from the sole runtime composition root.
5. Runtime adapter delegates to the existing resolver unchanged and has full type annotations.
6. Default-off config performs zero store/network work and preserves inbound broadcast/response behavior.
7. Production callback injection/order is proven with a recording bound callback; the separate runtime-adapter delegation plus unchanged resolver/fetch suites prove enabled mapped missing SHA is fetched, hash-verified, stored, and then available to local consumers.
8. Empty/malformed params, empty source, unmapped sender, local hit, fetch errors, tamper, MIME/size/store rejection, callback exception, callback cancellation propagation, and absent callback all behave as specified.
9. `_runtime_ref` and `set_runtime_ref()` no longer exist anywhere in production or tests.
10. AD-479e production behavior remains dormant (`no_runtime_handle`); no phantom runtime attributes/API or test-only activation remains.
11. No self-mod/cognitive source, config/YAML, event, endpoint, transport, store, protocol, message/dataclass, UI, dependency, decision, roadmap, era, or GitHub mutation.
12. Send-side strip and parent #638 remaining scope are unchanged; #638 is not closed by BF-672.
13. `FederationBridge.start()`/`stop()`, transport lifecycle, shutdown order, and `_startup_complete` timing are unchanged.
14. Production changes are limited to the three source files; tests are limited to the exact allowlist.
15. Focused and blast commands pass under exact isolated/local/offline/serial/warning-strict settings; exact counts/skips/durations are reported.
16. Tracker closeout, if authorized after final review, edits only `PROGRESS.md`; no `DECISIONS.md`, roadmap, era, or config/YAML entry.
17. Both prompt docs and the ignored issue draft remain byte-identical during Builder execution; prompts archive only after approval.
18. No deletion, broad reformat, generated output, staging, commit, push, issue comment/close/label/edit, or other GitHub mutation occurs during Builder execution.
19. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No direct `set_runtime_ref(self)` wiring and no replacement runtime back-reference under another name.
- No passing `runtime`/`ProbOSRuntime` into `FederationBridge` or `organize_fleet()`.
- No private reach-through to `self_mod_pipeline._designer`, `_validator`, `_sandbox`, spawner internals, or runtime private dependencies.
- No new `AgentDesigner.register_designed_template_from_payload`, `CodeValidator.validate_text`, self-mod registration path, designed-agent payload schema, sandbox/approval/trust/pool/persistence/rollback behavior, or AD-479e completion.
- No removal of the existing `designed_agent_payload` wire field, event enum, request parameter, or forward marker.
- No send-side `vision_messages` un-strip, ref-only re-attach, NATS Object Store, replication, pluggable AttachmentStore backend, URL-in-ref change, or AD-731a-1d/2/3 work.
- No change to `resolve_missing_attachments`, `fetch_remote_attachment`, serving endpoint, `AttachmentStore` Protocol/implementation, attachment config, A2A peer config, auth, hash/MIME/size checks, or HTTP ownership.
- No public API/message/dataclass/protocol/config/event/metric/status/log schema change.
- No edit to IntentBus, NATS/ZeroMQ/Mock transports, federation router, mobility identity registry, startup phase order, shutdown, or runtime `_startup_complete`.
- No `getattr`/`hasattr` guard for the required internal callback and no silent omission at a call site.
- No fire-and-forget task, new lock, client, resource, lifecycle method, or teardown step.
- No new source/test file, dependency, UI, YAML, workflow, standing order, commercial-repo edit, AD, decision, roadmap, era, or GitHub mutation.
- No Builder tracker edit, prompt archival, staging, commit, or push before Architect review.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD or `origin/main` differs from `34a3425c5e1a6217a3cab2564ea437cd7de6426b`, or the initial tree contains anything beyond the two BF-672 prompt docs (the ignored issue draft will not appear in status).
2. The production-wiring test cannot be written through `organize_fleet()` without manually calling a setter or mutating bridge privates.
3. Correctness requires passing the whole runtime, adding a second late-bound handle, editing `resolve_missing_attachments`, changing config, or owning a new resource/task.
4. AD-479e cannot remain dormant without changing its wire field or requiring a cognitive/self-mod production edit.
5. A required behavior needs a production/test path outside the exact allowlist.
6. Send-side strip, attachment wire format, serve/fetch policy, transport, mobility, IntentBus, startup ordering, or shutdown must change.
7. A focused/blast failure reproduces serially and requires an unallowlisted fix, skip, quarantine, weakened assertion, or broad test run.
8. Either Architect doc or the issue draft changes, a deletion/bulk reformat appears, or config/YAML/UI/dependency/tracker/Git/GitHub mutation occurs before review.

Do not guess around a hard stop.

---

## Three-pass Builder self-review

### Pass 1 — Behavior/spec

- Map every DD, required test, and acceptance criterion.
- Verify real production construction and pre-broadcast storage ordering.
- Verify every default-off/empty/error/cancellation/absent-callback branch.
- Verify AD-479e stays dormant and mobility still succeeds.
- Verify send-side strip and attachment integrity remain unchanged.

### Pass 2 — Verify-first/code

- Re-run the AST inventory: one production bridge construction, zero setter calls, zero `_runtime_ref` reads/definitions after build.
- Inspect constructor/start ordering line-by-line.
- Confirm runtime adapter delegates only to the existing resolver.
- Confirm bridge imports no runtime/cognitive/store/http modules.
- Confirm every `organize_fleet()` call site supplies the callback explicitly.
- Confirm no transport/start/stop/shutdown diff.

### Pass 3 — Scope/safety/license

- Verify exact allowlist, no new files/deletion/broad format, prompt docs byte-for-byte, issue draft byte-for-byte, and no YAML/UI/dependency/tracker/GitHub drift.
- Verify ordinary failures are contained at the AD-731a-1c prefetch boundary while cancellation propagates.
- Verify no sensitive token/URL/payload logging was added.
- Verify compliance with `.github/copilot-instructions.md`; license remains none.

---

## Verified Against Codebase (2026-07-16)

```text
git rev-parse HEAD
  34a3425c5e1a6217a3cab2564ea437cd7de6426b

git rev-parse origin/main
  34a3425c5e1a6217a3cab2564ea437cd7de6426b

git status --short before Architect docs
  <empty>

git log -1 --oneline
  34a3425c BF-670: replace IntentBus re-subscribe memberships (closes #1037)

numbering scan (PROGRESS.md / DECISIONS.md / roadmap.md)
  highest AD: AD-1122
  highest BF: BF-671
  BF-672: zero tracked hits

gh issue view 638 --repo seangalliher/ProbOS
  OPEN — AD-731a: Attachment store distribution model (cross-host receiver byte access)

PROGRESS.md
  115: AD-731a-1c shipped; claims receive resolver before local broadcast; default-OFF
  121: AD-731a-1 shipped; serve + content-verifying client

DECISIONS.md
  310: AD-731a-1c decision
  358: AD-731a-1 decision

docs/development/roadmap.md
  696: AD-731a parent #638 remains open
  697: AD-731a-1 HTTP fetch marker
  698: AD-731a-2 NATS Object Store marker
  699: AD-731a-3 MIME fast-path marker

src/probos/federation/bridge.py
  61: _runtime_ref initialized None
  78-84: set_runtime_ref definition
  207+: one bridge class; constructor remains transport/runtime agnostic except broad dead handle
  239-241: AD-731a-1c resolver receives _runtime_ref
  375: accepted transfer invokes _reconstruct_designed_agent only for truthy payload
  517: _reconstruct_designed_agent
  531: second and only other _runtime_ref read
  556: phantom register_designed_template_from_payload lookup

src/probos/federation/attachment_resolve.py
  99: resolve_missing_attachments(runtime, params, source_node, http=None)
  runtime None -> 0; flag off -> 0; store/ref/peer guards; existing fetcher reuse

production AST inventory
  FederationBridge constructions: exactly one — startup/fleet_organization.py:207
  set_runtime_ref calls: zero
  _runtime_ref reads: bridge.py:241 and :531 only

src/probos/startup/fleet_organization.py
  27: organize_fleet internal startup function
  207: sole production FederationBridge constructor
  216: bridge.start occurs before return
  218: IntentBus federation handler wiring

src/probos/runtime.py
  1616: public attachment_store accessor
  1946: sole runtime organize_fleet call
  1961: bridge assigned to runtime after organize_fleet returns
  1993: self_mod_pipeline assigned later (Phase 4)
  2527: self_mod_manager assigned after finalization
  2577: startup_complete set at end

src/probos/startup/finalize.py / shutdown.py
  2652: finalization begins after cognitive/communication phases
  4597: SelfModManager construction
  shutdown.py:913-915: bridge stopped then cleared before transport stop

src/probos/cognitive/agent_designer.py / code_validator.py / self_mod.py
  agent_designer.py:237: AgentDesigner; no payload-registration method
  code_validator.py:18: CodeValidator; no validate_text method
  self_mod.py:83-84: designer/validator are private
  self_mod.py:641: public validator property only

src/probos/config.py / tracked node configs
  2407: serve_remote_enabled=False
  2412: auto_resolve_remote_enabled=False
  2961: A2APeerConfig.node_id=""
  3048: federation.enabled=False default
  3117: self_mod.enabled=False model default
  config/node-1.yaml:89-101: federation=True and self_mod=True
  config/node-2.yaml:89-101: federation=True and self_mod=True

existing tests
  test_ad731a_1c_auto_resolve.py: direct resolver tests only; no startup construction
  test_ad479_federation_hardening.py:561/580/599/612/627 manually call set_runtime_ref
  test_federation_nats.py:318 direct organize_fleet call
  test_ad447_phase_gates_pool_group.py:99 direct organize_fleet call

clean-HEAD exact gates
  focused: 228 passed in 56.64s
  blast: 44 passed in 206.93s
```

---

## Three-pass Architect packet review (2026-07-16)

**Verdict:** ✅ APPROVED FOR BUILDER

### Required

- None. The production-wiring premise is real, but direct `set_runtime_ref(self)` wiring is rejected because it would expose incomplete AD-479e behavior.

### Recommended

- Keep the production-construction integration in `test_ad731a_1c_auto_resolve.py` so the original resolver tests and the missing composition-root proof remain adjacent.
- Prefer an explicit required callback parameter on internal `organize_fleet()` over a default that lets future call sites omit the dependency silently.

### Nits

- Exact private alias/parameter names may vary if the contracts above remain exact.

### Verified

- Full #638 issue, trackers, complete bridge/resolver, every construction/setter/read, startup/finalize/shutdown, AD-479e and AD-731 tests, config activation, and clean serial baselines were reviewed against `34a3425c`.
