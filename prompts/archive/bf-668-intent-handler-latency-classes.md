# BF-668 — Class-aware IntentBus handler latency telemetry

**Verdict:** APPROVED FOR BUILDER
**One-line:** Replace the broadcast path's universal 100 ms handler warning with explicit deterministic/network/cognitive metadata, validated per-class thresholds, and bounded per-handler outcome telemetry while preserving every dispatch result and scheduling rule.

**Status:** Ready to build — BF-667 CI succeeded; Builder must reverify success and unchanged base at pre-flight
**Type:** Bug fix — **BF-668**; no new AD and no `DECISIONS.md` entry
**GitHub issue:** #1034 — https://github.com/seangalliher/ProbOS/issues/1034
**Exact base HEAD:** `4d8fb2e289366f3d2c1ffe5398549555a1cb6808`
**Numbering verified:** highest shipped entries at this base are **AD-1121** and **BF-667**; issue #1034 reserves BF-668
**Dependencies:** AD-470, AD-515, AD-654a/b, BF-296, BF-667
**License disposition:** none — standard-library enum/dataclass/statistics only; no dependency or absorbed external code
**Estimated tests:** 16–24 additions/updates across the existing IntentBus/config/onboarding/vision/Yeoman/hot-replacement suites; no new test file

## Scope

Repair only class-aware latency metadata, thresholds, broadcast-handler sampling, and the existing subscription plumbing that carries the metadata.

The implementation must guarantee:

1. every completed broadcast-handler invocation records one bounded sample keyed by `(agent_id, intent, latency_class)`;
2. deterministic handlers retain the current 100 ms warning sensitivity;
3. expected cognitive and network latency remains measurable without recurring false-positive warnings;
4. an extreme cognitive/network completion still warns at its own configured class threshold;
5. errors keep exactly one handler-error WARNING and never add a second latency WARNING;
6. cancellation/timeout does not become an error/latency sample or warning;
7. unclassified/legacy subscribers remain deterministic;
8. `CognitiveAgent` subscribers classify cognitive and `HttpFetchAgent` subscribers classify network without names, pool tiers, descriptor tiers, or callable introspection;
9. onboarding, direct service subscription, hot replacement, and unsubscribe preserve/replace/remove metadata coherently;
10. `_subscribers` remains the callable map for compatibility; metadata is a separate sidecar;
11. the existing `get_metrics()` response remains backward-compatible and gains only an additive `handlers` section; and
12. fan-out concurrency, candidate filtering, timeout, result ordering, send/NATS/JetStream paths, federation, and queue behavior remain unchanged.

No LLM, UI, dependency, persistence, event, trust, consensus, circuit-breaker, or Yeoman/calendar behavior work is authorized.

---

## Problem, live evidence, and verified root cause

At the exact base:

- `src/probos/mesh/intent.py:791-824` owns broadcast-handler timing in `_invoke_handler()`.
- `src/probos/mesh/intent.py:799-807` measures `await handler(intent)` with `time.monotonic()` and emits a WARNING for every elapsed value above the universal literal `100`, regardless of handler execution shape.
- `src/probos/mesh/intent.py:812-824` catches ordinary handler exceptions, emits one handler-error WARNING, and appends a failed `IntentResult`; elapsed time is currently neither recorded nor warned on that path.
- `src/probos/mesh/intent.py:483-600` prefilters candidates, creates one task per selected subscriber, waits concurrently with the existing timeout, cancels pending tasks, then returns `_pending_results` in actual completion/append order. BF-668 must not add tasks or reorder this path.
- `src/probos/mesh/intent.py:407-473`, `210-239`, `606-696`, and `startup/finalize.py:4146-4152` are separate handler paths: targeted `send()`, NATS request/reply, `dispatch_async()` direct fallback, and `AgentCognitiveQueue`. Issue #1034 is the recurring broadcast `_invoke_handler` warning; broadening telemetry to these paths would be scope and semantic churn.
- `src/probos/mesh/intent.py:26-69` already owns `IntentMetrics`. Broadcast/send samples are capped at 200 and `get_summary()` returns stable top-level `broadcast_count`, `send_count`, `total_results`, and `types` fields.
- `src/probos/routers/system.py:241-250` exposes `IntentBus.get_metrics()` verbatim at `/api/intent-metrics`; existing consumers therefore require additive response compatibility.
- `src/probos/mesh/intent.py:81-113` constructs the bus with a required `SignalManager`, a callable-only `_subscribers` map, and internal `IntentMetrics`. `src/probos/runtime.py:370/386` has validated `SystemConfig` before it constructs the sole production `IntentBus`, which is the correct threshold injection seam.
- `src/probos/config.py:126-141` has `MeshConfig` but no handler latency fields. `config/system.yaml:12-20` has the local mesh block; issue #1034 explicitly requires model defaults and forbids changing local YAML.
- `src/probos/types.py:16` and `:776` already host cross-layer typed enums/metadata (`AgentState`, `IntentDescriptor`). No latency class exists.
- `src/probos/substrate/agent.py:18-29` has public class metadata (`agent_type`, `tier`, `intent_descriptors`) but no execution-cost metadata. `tier` is mesh role, not latency class.
- `src/probos/cognitive/cognitive_agent.py:295/311/5627` proves all cognitive agents share one base and handler lifecycle. Its LLM call and journal awaits are live at `:3411` and `:3424`; expected multi-second runtime is intrinsic to this class.
- `src/probos/agents/http_fetch.py:34/44/62` shows `HttpFetchAgent` is a `BaseAgent`, core tier, with an 8-second network timeout. Core tier therefore cannot mean deterministic.
- `src/probos/agent_onboarding.py:124-172` is the common agent subscription choke point. It currently passes only `agent.id`, `agent.handle_intent`, and intent names.
- `src/probos/self_mod_manager.py:188-224` recreates a patched designed agent and re-subscribes the replacement handler under the existing agent id; this path must replace latency metadata along with the handler.
- There are exactly eight production `IntentBus.subscribe()` call sites: onboarding, Yeoman's proactive helper, VisionAggregator, VisionConsumer, group-chat coordinator, device service, patched-agent hot replacement, and sensitive-device consensus dispatch. They are enumerated in the Verified section.
- The separate service handlers are not all cognitive: group-chat creation (`threads/agent_group_chat.py:242-252`) is synchronous deterministic work under an async wrapper; the device service (`substrate/device_service.py:60-120`) awaits the currently local NoOp adapter/episode path; the consensus dispatch (`runtime.py:3709-3721`) awaits local governance/actuation. BF-668 does not hide these behind a broad I/O class: all three remain explicitly deterministic. Network is pinned only where the live handler contract is external transport (`HttpFetchAgent`).
- `src/probos/perception/consumer.py:463/886/959` performs a vision LLM describe inside its bus handler, so this non-agent service subscriber is explicitly cognitive. `src/probos/perception/aggregator.py:96-174` can forward to that same consumer and is therefore explicitly cognitive as well.
- `src/probos/cognitive/yeoman.py:74/122/130` proves `schedule_lookup` is handled by `YeomanAgent(CognitiveAgent)`. The extra proactive helper at `:242` points to `_handle_proactive_scan()` (`:337`), which only buffers/schedules and should be explicitly deterministic despite living on a CognitiveAgent instance. This is why `handler.__self__`, callable names, and agent-id prefixes are forbidden classifiers.

### Live console evidence (read-only, 2026-07-14)

The local rotating logs under `%LOCALAPPDATA%\ProbOS\data\logs\probos.log*` contained **488** retained current-format `Slow handler` warnings:

- **488 responded**, **0 declined**;
- `schedule_lookup`: **331**, median **6,390 ms**, p95 **8,875 ms**, max **9,907 ms**;
- `http_fetch`: **66**, median **2,812 ms**, p95 **7,453 ms**;
- `scout_report`: **32**, median **6,414 ms**, p95 **9,250 ms**.

Latest live line:

```text
02:45:18  WARNING   probos.mesh.intent              Slow handler: agent=yeoman_yeoman_0_ intent=schedule_lookup elapsed=8469ms result=responded
```

This is healthy completed work, not slow self-deselection. `CognitiveAgent.decide()` performs the LLM await and journal write before `IntentResult` completion. The universal 100 ms diagnostic from the archived broadcast-slowdown investigation no longer describes all handler classes.

### Live signatures that BF-668 may change additively

```text
IntentBus.__init__(self, signal_manager: SignalManager) -> None
IntentBus.subscribe(
    self,
    agent_id: str,
    handler: IntentHandler,
    intent_names: list[str] | None = None,
) -> None
IntentBus.unsubscribe(self, agent_id: str) -> None
IntentBus.get_metrics(self) -> dict[str, Any]
IntentBus._invoke_handler(
    self,
    intent: IntentMessage,
    agent_id: str,
    handler: IntentHandler,
) -> None

IntentMetrics.record_broadcast(
    self,
    intent_type: str,
    result_count: int,
    duration_ms: float,
) -> None
IntentMetrics.record_send(self, intent_type: str, duration_ms: float) -> None
IntentMetrics.get_summary(self) -> dict[str, Any]
```

Pinned additive forms:

```text
IntentBus.__init__(
    self,
    signal_manager: SignalManager,
    *,
    handler_latency_thresholds_ms: Mapping[HandlerLatencyClass, float] | None = None,
) -> None

IntentBus.subscribe(
    self,
    agent_id: str,
    handler: IntentHandler,
    intent_names: list[str] | None = None,
    *,
    latency_class: HandlerLatencyClass = HandlerLatencyClass.DETERMINISTIC,
) -> None
```

Every existing positional/three-argument caller remains valid. The new constructor and subscription parameters are keyword-only and fully typed.

---

## Issue-contract resolutions and clarifications

1. **Class enum belongs in shared types.** Add `HandlerLatencyClass(StrEnum)` to `probos.types` with exact values `deterministic`, `network`, and `cognitive`. Config remains numeric fields; it does not import mesh types.
2. **Class metadata belongs on the agent class, not each intent descriptor.** Add public `BaseAgent.handler_latency_class`, override it once on `CognitiveAgent`, and override it once on `HttpFetchAgent`. All current/future subclasses inherit the right default without editing every agent or every intent.
3. **Do not infer from `tier`.** `HttpFetchAgent.tier == "core"` but is network; `CognitiveAgent.tier == "domain"` but class is cognitive. Core/utility/domain classifies mesh role only.
4. **Do not infer from callable identity.** The Yeoman object has both an LLM-backed agent handler and a deterministic proactive-buffer helper. Onboarding reads the public agent metadata; direct service subscriptions pass an explicit hint. No `handler.__self__`, `__qualname__`, agent-id prefix, pool name, `isinstance(CognitiveAgent)`, or descriptor-name heuristic belongs in `IntentBus`.
5. **Keep `_subscribers` as `dict[str, IntentHandler]`.** Current source/tests/SIF directly inspect or replace it. Store classes in a parallel private `dict[str, HandlerLatencyClass]`. This is the smallest compatibility-preserving change. When `broadcast()` snapshots candidates, snapshot each selected handler together with its class before creating tasks so a synchronous re-subscribe cannot pair an old callable with new metadata (or vice versa) mid-fan-out.
6. **Constructor defaults preserve test callers.** When thresholds are omitted, `IntentBus` uses the exact built-in defaults 100/10,000/30,000 ms. Production passes the validated `MeshConfig` values explicitly. No runtime service locator/config reach-through from the mesh layer.
7. **Thresholds are config-backed because issue #1034 requires operator tuning.** Add three positive `MeshConfig` float fields with defaults 100.0/10_000.0/30_000.0 and one shared `field_validator` rejecting `<= 0`, NaN, and infinity. Leave `config/system.yaml` unchanged so model defaults apply.
8. **Only completed broadcast invocations are sampled.** `_invoke_handler()` records responded, declined, or error after the await completes/raises. An outer timeout cancellation raises `CancelledError` (a `BaseException` in supported Python), bypasses `except Exception`, records no completed sample, emits no warning, and propagates. Do not add a cancellation catch unless it re-raises immediately and records nothing.
9. **Errors are measured but not double-warned.** Record one `error` sample, emit the existing handler-error WARNING once, append the same failed `IntentResult`, and suppress latency warning regardless of elapsed time.
10. **Successful threshold breaches warn; below-threshold completions are metrics-only.** No new per-call DEBUG/INFO log is needed. Metrics are the observability surface. This avoids replacing WARNING floods with DEBUG floods.
11. **Extreme cognitive/network warnings are required.** A completed cognitive handler above 30,000 ms and network handler above 10,000 ms must warn. Threshold comparison remains strict `elapsed_ms > threshold_ms`: 100 ms exactly does not warn; 101 ms does.
12. **Warning context is one stable structured message.** Use full `agent_id`, full `intent`, `latency_class`, `threshold_ms`, `elapsed_ms`, `outcome`, and `dispatch=completed`. Do not truncate the identifiers in the new warning. The phrase must state that the handler completed but exceeded its class budget, not that it merely was “slow.”
13. **Metrics key and p95 are deterministic.** The public `handlers` value is a sorted list of rows (not delimiter-packed string keys) with fields `agent_id`, `intent`, `latency_class`, `count`, `mean_ms`, `p95_ms`, `max_ms`, `responded_count`, `declined_count`, `error_count`. p95 is nearest-rank: `sorted_samples[ceil(0.95*n)-1]`; one sample returns itself.
14. **Bound per-key and global cardinality.** Keep at most 200 elapsed samples per key, matching AD-470. Keep at most 1,000 active `(agent_id,intent,class)` keys using an `OrderedDict` access/insertion LRU: recording an existing key moves it to the end; inserting key 1,001 evicts the oldest complete key, including its outcome counters. Add constants and tests; no persistence or external metrics backend.
15. **Preserve existing metrics API fields byte-for-byte.** `broadcast_count`, `send_count`, `total_results`, and `types` retain their exact meaning and shape. Add only top-level `handlers`.
16. **Scope remains broadcast `_invoke_handler()`.** Do not retrofit target `send()`, NATS callbacks, JetStream queue execution, or `dispatch_async()` in this BF. Their timeout/ack/queue semantics differ and issue #1034 does not report those warnings.
17. **No extra tasks or gathers.** Timing and metric recording run inline in the already-created `_invoke_handler` task. Fan-out task count, task names, `asyncio.wait`, cancellation, and completion-order append remain unchanged.

---

## Pinned design decisions

### DD-1 — Typed execution class and inherited public agent metadata

The classes describe expected execution cost, not trust, capability, or mesh role:

- `DETERMINISTIC` — local/in-process mechanics whose completed hot-path work should ordinarily fit under 100 ms; a breach is actionable diagnostic signal.
- `NETWORK` — handlers whose normal completion crosses an external network transport; v1's explicit member is `HttpFetchAgent`; budget 10,000 ms.
- `COGNITIVE` — handlers that may run an LLM-backed cognitive lifecycle (including journaled reasoning or vision description); budget 30,000 ms.

Classification does not promise that every invocation uses the expensive boundary (for example Calculator's safe local fast path remains cognitive because the subscribed handler can fall through to the LLM). It selects the truthful worst normal execution class for that handler contract.

In `src/probos/types.py`, add near other small cross-layer `StrEnum`s:

```text
class HandlerLatencyClass(StrEnum):
    DETERMINISTIC = "deterministic"
    NETWORK = "network"
    COGNITIVE = "cognitive"
```

In `src/probos/substrate/agent.py`, import it and add:

```text
handler_latency_class: HandlerLatencyClass = HandlerLatencyClass.DETERMINISTIC
```

beside `tier`/`instructions`/descriptor class metadata.

Override exactly:

```text
CognitiveAgent.handler_latency_class = HandlerLatencyClass.COGNITIVE
HttpFetchAgent.handler_latency_class = HandlerLatencyClass.NETWORK
```

Requirements:

- no `IntentDescriptor` field;
- no per-instance mutation in `__init__`;
- no import of cognitive or HTTP classes into onboarding/IntentBus;
- no mapping by core/utility/domain tier;
- no stringly-typed class value inside the bus;
- public class metadata must be fully typed.

This class-level inheritance covers current designed agents and every current `CognitiveAgent` subclass, including Yeoman, Scout, medical/science specialists, M365 connectors, and bundled utilities. The `HttpFetchAgent` override wins over the `BaseAgent` deterministic default.

### DD-2 — Positive MeshConfig thresholds; local YAML unchanged

Add to `MeshConfig`:

```text
handler_latency_deterministic_ms: float = 100.0
handler_latency_network_ms: float = 10_000.0
handler_latency_cognitive_ms: float = 30_000.0
```

Add one shared field validator that:

- rejects booleans and non-numeric values with `ValueError`;
- accepts finite native/coercible numeric values;
- returns `float(v)` after conversion;
- raises `ValueError` for `<= 0`, NaN, or positive/negative infinity;
- names handler latency thresholds in the error.

Do not add a nested model, mapping with enum keys, runtime reload watcher, environment variable, or edit `config/system.yaml`.

In `ProbOSRuntime.__init__()`, after `self.config` is available, construct the bus with an explicit typed mapping from `HandlerLatencyClass` to those three fields. `IntentBus` does not import or retain `SystemConfig`/`MeshConfig`.

### DD-3 — Preserve callable subscriber storage; add a metadata sidecar

Keep:

```text
self._subscribers: dict[str, IntentHandler]
```

Add:

```text
self._subscriber_latency_classes: dict[str, HandlerLatencyClass]
```

`subscribe()` writes/replaces the handler and its class in the same synchronous call. `unsubscribe()` removes both with `pop(..., None)` before queue/index/NATS cleanup.

In `broadcast()`, preserve all current candidate-selection rules but snapshot candidates as `(handler, latency_class)` pairs. Pass the snapshotted enum into `_invoke_handler()` as a new final private parameter. Do not have `_invoke_handler()` re-read the mutable sidecar after tasks were created. A legacy direct `_subscribers` insertion receives the deterministic fallback while the snapshot is built.

Direct/manual mutation of `_subscribers` remains unsupported production behavior but is present in legacy tests. `_invoke_handler()` therefore resolves class with:

```text
self._subscriber_latency_classes.get(agent_id, HandlerLatencyClass.DETERMINISTIC)
```

This keeps legacy/unclassified behavior deterministic and avoids a crash if a test injects a callable directly.

Do not wrap subscribers in a dataclass/tuple and do not migrate SIF/private tests in this BF.

### DD-4 — Additive `subscribe()` hint; classify at the ownership boundary

Use the exact additive keyword-only parameter from the live-signature section. It must accept an actual `HandlerLatencyClass`, not arbitrary strings. Enforce this synchronously with `isinstance(latency_class, HandlerLatencyClass)` and raise `TypeError` on a raw string/other value; type hints alone are not a runtime boundary. No silent name inference or string coercion is permitted.

#### Common agent onboarding

`AgentOnboardingService.wire_agent()` passes:

```text
latency_class=agent.handler_latency_class
```

This is public metadata inherited from `BaseAgent`, so every real agent has it. Do not use `getattr(..., fallback)` in production. Tests that use non-real MagicMock agent fixtures must either use a real/minimal BaseAgent subclass or explicitly set the public metadata; do not weaken production to accommodate divergent mocks.

#### Patched designed-agent replacement

`SelfModManager._apply_agent_correction()` passes `new_agent.handler_latency_class`. Designed agents are CognitiveAgent subclasses at the generated template boundary, so hot replacement remains cognitive. The same `subscribe()` call replaces the sidecar entry under the retained agent id.

#### Direct service subscriptions

Audit and pass explicit classes at the seven non-onboarding call sites:

| Site | Handler | Pinned class | Reason |
|---|---|---:|---|
| `runtime.py` group-chat coordinator | `AgentGroupChatService.handle_intent` | deterministic | synchronous validation/SQLite call under async wrapper; no network/LLM |
| `runtime.py` device service | `DeviceNodeService.handle_intent` | deterministic | current NoOp/local actuation and episode path; do not hide local regression signal behind network budget |
| `startup/finalize.py` device consensus dispatch | runtime governed actuation | deterministic | local governance/NoOp actuation at HEAD; not an external network handler |
| `perception/consumer.py` | vision consumer `_handle` | cognitive | awaits vision LLM describe |
| `perception/aggregator.py` | aggregator `_handle` | cognitive | can await/forward the consumer's LLM pipeline |
| `cognitive/yeoman.py` proactive helper | `_handle_proactive_scan` | deterministic | buffer/schedule helper, no LLM; object class must not leak into helper class |
| `self_mod_manager.py` | new designed agent handler | cognitive via public metadata | replacement preserves agent-class metadata |

The eighth production call is common onboarding, covered above.

Do not introduce metadata on `IntentDescriptor`; one subscribed handler can serve many intents but has one execution class at this boundary.

### DD-5 — Threshold injection and immutable lookup

`IntentBus.__init__()` accepts optional `Mapping[HandlerLatencyClass, float]`. Normalize into a fresh private dict covering all three enum members and reject missing/non-positive/non-finite entries with `ValueError`. If the mapping is `None`, use module constants:

```text
_DETERMINISTIC_HANDLER_LATENCY_MS = 100.0
_NETWORK_HANDLER_LATENCY_MS = 10_000.0
_COGNITIVE_HANDLER_LATENCY_MS = 30_000.0
```

Keep these defaults aligned with `MeshConfig`; tests assert parity so drift becomes red.

No config import from `intent.py`, no runtime callback, no mutable public threshold map, and no local YAML edit.

### DD-6 — Bounded handler metrics inside `IntentMetrics`

Add a private per-key stats carrier in `mesh/intent.py` (name may vary, behavior may not) with:

- `durations_ms: list[float]` capped at 200;
- `responded_count`, `declined_count`, `error_count`;
- derived `count == sum(outcome counts)`;
- derived nearest-rank p95.

Add a fully typed public method:

```text
IntentMetrics.record_handler(
    self,
    agent_id: str,
    intent_type: str,
    latency_class: HandlerLatencyClass,
    duration_ms: float,
    outcome: Literal["responded", "declined", "error"],
) -> None
```

Validation/behavior:

- outcome is an internal closed literal; reject any other value with `ValueError` rather than silently miscount;
- record every finite non-negative completed sample; reject a negative/non-finite internal duration with `ValueError`;
- key by the full `agent_id`, full intent, and enum class;
- per-key samples cap at 200 while `count`/outcome counters remain lifetime-since-key-admission totals;
- use `OrderedDict` for a 1,000-key LRU; eviction removes the complete oldest row/counters;
- `get_summary()` adds `handlers`, sorted by `(agent_id, intent, latency_class)` for deterministic API/tests;
- round mean/p95/max to two decimals, matching existing type-summary rounding;
- do not alter existing broadcast/send `type_counts` or duration samples.

No lock is required: record/get run on the one event-loop thread and contain no await. Do not add background aggregation, persistence, histograms, Prometheus/OpenTelemetry, or numpy.

### DD-7 — One completed-sample decision in `_invoke_handler()`

Preserve the current handler await and result append. Restructure narrowly:

1. start `time.monotonic()` immediately before `await handler(intent)`;
2. on normal return, compute elapsed once;
3. classify outcome as `responded` when `result is not None`, else `declined`;
4. record exactly one handler sample;
5. if `elapsed_ms > threshold_for_class`, emit one WARNING with full structured context;
6. append non-None result exactly where the current code appends it;
7. on `Exception`, compute elapsed once, record exactly one `error` sample, emit the existing error WARNING once with improved full context if needed, append the same failed `IntentResult`, and do **not** run the latency-warning branch;
8. on cancellation, allow propagation with no sample/log/result.

Pinned warning semantics:

```text
Handler completed over latency budget: agent_id=%s intent=%s latency_class=%s threshold_ms=%.0f elapsed_ms=%.0f outcome=%s dispatch=completed
```

Equivalent wording is allowed only if all seven fields remain stable and machine-searchable. `outcome` is responded/declined only on this warning. Do not include payloads, result contents, exception text in the latency warning, or truncate identifiers.

The error warning must retain one WARNING and identify full `agent_id`, full intent name, intent id, and exception reason. It must not be followed by the latency warning even when elapsed exceeds the class budget.

### DD-8 — Preserve all dispatch semantics

BF-668 must not change:

- candidate prefiltering or fallback subscriber rules;
- per-candidate `asyncio.create_task()` count/name;
- `asyncio.wait(tasks, timeout=...)`;
- pending-task cancellation or add a gather/drain;
- completion-order appends to `_pending_results`;
- directed `send()` timeout/result behavior;
- NATS request/reply subscription and serialization;
- JetStream max-ack/term/nak behavior;
- `AgentCognitiveQueue` execution;
- `dispatch_async()` task cap/fallback;
- signal tracking/untracking;
- federation forwarding;
- broadcast/send AD-470 metrics;
- error `IntentResult` shape.

No warning suppression filter is authorized. A genuinely slow deterministic completion still warns at 100 ms; a genuinely extreme cognitive/network completion still warns at its own budget.

---

## Exact file allowlist

### Production files the Builder may modify

- `src/probos/types.py` — `HandlerLatencyClass`.
- `src/probos/config.py` — validated MeshConfig thresholds.
- `src/probos/substrate/agent.py` — deterministic public metadata default.
- `src/probos/cognitive/cognitive_agent.py` — cognitive metadata override.
- `src/probos/agents/http_fetch.py` — network metadata override.
- `src/probos/mesh/intent.py` — sidecar, thresholds, bounded metrics, class-aware warning.
- `src/probos/runtime.py` — threshold injection and direct service hints.
- `src/probos/agent_onboarding.py` — common agent metadata plumbing.
- `src/probos/self_mod_manager.py` — hot-replacement metadata plumbing.
- `src/probos/perception/consumer.py` — explicit cognitive service hint.
- `src/probos/perception/aggregator.py` — explicit cognitive service hint.
- `src/probos/cognitive/yeoman.py` — explicit deterministic helper hint.
- `src/probos/startup/finalize.py` — explicit deterministic device-consensus hint.

### Existing tests the Builder may modify

- `tests/test_intent.py` — handler outcomes, warnings, cancellation, fan-out semantics, sidecar unsubscribe/replacement.
- `tests/test_ad470_intent_bus_enhancements.py` — bounded handler stats, p95/LRU, API compatibility.
- `tests/test_targeted_dispatch.py` — send behavior unchanged/no handler-sample claim.
- `tests/test_ad654a_async_dispatch.py` — async/JetStream paths unchanged.
- `tests/test_ad654b_cognitive_queue.py` — queue path unchanged.
- `tests/test_bf296_intent_bus_close.py` — in-flight/close behavior and direct `_subscribers` compatibility.
- `tests/test_performance_p0.py` — prefilter/fallback behavior unchanged.
- `tests/test_config.py` — defaults/load/positive finite validation.
- `tests/test_onboarding.py` — real public metadata plumbing for deterministic/cognitive/network agents.
- `tests/test_cognitive_skill_596b.py` — subscription assertion updated to include cognitive class; replace divergent mock metadata as needed.
- `tests/test_ad733a_vision_consumer.py` — explicit cognitive hint assertion.
- `tests/test_ad746_vision_aggregator.py` — explicit cognitive hint assertion.
- `tests/test_yeoman_agent.py` — fake subscribe signature and deterministic helper hint assertion.
- `tests/test_correction_runtime.py` — hot replacement preserves cognitive metadata.
- `tests/test_runtime.py` — runtime threshold injection/default parity and real pool metadata smoke.
- `tests/test_sif.py` — run unchanged where possible; only compatibility assertion adjustment if strictly required by the sidecar.
- `tests/test_ad843c1_device_actuation.py` — direct-service subscription representation/metadata smoke if needed.
- `tests/test_ad843c2_device_consensus.py` — direct consensus subscription metadata smoke if needed.

### Architect documents already present; retain unchanged during build

- `prompts/bf-668-intent-handler-latency-classes.md`
- `prompts/bf-668-intent-handler-latency-classes-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config YAML, standing-order, workflow, UI, tracker, roadmap, decision, era, archive, dependency, data/log, or issue file is authorized.

---

## Ordered implementation

### Section 1 — Add typed class metadata and validated config

1. Add `HandlerLatencyClass` to `types.py`.
2. Add the BaseAgent/CognitiveAgent/HttpFetchAgent class metadata exactly per DD-1.
3. Add the three `MeshConfig` fields and shared finite-positive validator.
4. Add tests for enum values, inheritance/overrides, defaults, YAML load fallback, zero/negative/NaN/infinity rejection.

Hard gate: no class inference, no descriptor/tier repurposing, and no local YAML edit.

### Section 2 — Extend `IntentMetrics` before changing warnings

1. Add the private bounded handler-stat carrier and 1,000-key LRU.
2. Add `record_handler()` and additive `handlers` summary.
3. Preserve all old summary fields and tests exactly.
4. Add exact p95, outcome-count, sample-cap, global-key-cap/LRU, deterministic ordering, invalid-outcome, and endpoint-shape tests.

Hard gate: 200 samples per key and 1,000 keys globally are behaviorally proven; existing AD-470 fields are unchanged.

### Section 3 — Add threshold injection and subscriber metadata sidecar

1. Extend `IntentBus.__init__()` keyword-only threshold map with built-in defaults.
2. Extend `subscribe()` keyword-only class hint with deterministic default.
3. Keep `_subscribers` callable-only; add sidecar.
4. Replace/remove metadata on re-subscribe/unsubscribe.
5. Inject config values from runtime.
6. Add compatibility tests for old constructor, old 2/3-argument subscribe calls, direct `_subscribers` injection fallback, re-subscribe, unsubscribe, and SIF map access.

Hard gate: no wrapper replaces `_subscribers` values; no existing call becomes positionally incompatible.

### Section 4 — Thread metadata through all eight live subscription sites

1. Common onboarding uses `agent.handler_latency_class` with no fallback.
2. Hot replacement uses `new_agent.handler_latency_class`.
3. Add explicit direct-service hints from DD-4.
4. Update strict fakes/tests so their public contracts match real agents/bus.

Hard gate: a real Yeoman agent handler is cognitive, its proactive helper is deterministic, VisionConsumer/Aggregator are cognitive, HttpFetchAgent is network, and ordinary BaseAgent subclasses are deterministic.

### Section 5 — Make `_invoke_handler()` class-aware

Implement DD-7 narrowly. Add fail-before/pass-after log tests with a deterministic fake monotonic clock or direct `_invoke_handler()` harness; do not sleep 8/30 seconds.

Hard gate: an exception above threshold emits one error warning only; cancellation emits no sample/warning/result; result append semantics remain.

### Section 6 — Preserve broadcast and non-broadcast behavior

Extend existing tests to prove:

- concurrent fan-out still begins all handlers before release;
- results remain completion ordered;
- timeout still cancels pending work and returns completed results;
- targeted send still uses its own AD-470 send metrics only;
- dispatch_async/NATS/queue behavior remains unchanged;
- no per-handler task is added.

### Section 7 — Focused gate, then blast gate

Run only the exact serial warning-strict commands below. Do not run full `tests/`, broad xdist, live LLM/network, or live runtime data.

### Section 8 — Three-pass self-review and scope audit

Perform the required three review passes below, then run whitespace/status/deletion checks. Do not modify the two Architect docs.

### Section 9 — Conditional `PROGRESS.md` closeout and commit

Only after green gates, Architect approval, and explicit orchestrator direction:

- prepend one concise BF-668 closeout to `PROGRESS.md` with exact focused/blast counts and #1034;
- state no new AD and BF-668 as the BF ceiling;
- retain both BF-668 prompt documents;
- do not edit `DECISIONS.md`, roadmap, era files, config YAML, or GitHub;
- stage only allowlisted paths;
- commit exactly:

`BF-668: classify IntentBus handler latency (closes #1034)`

Do not push or mutate GitHub unless separately directed by the orchestrator.

---

## Required behavioral tests

All latency-duration tests must use a deterministic clock/monkeypatch or direct metric recording. Do not add real 8-second or 30-second sleeps.

### A. Type/config/metadata

1. `HandlerLatencyClass` has exactly deterministic/network/cognitive string values.
2. `BaseAgent.handler_latency_class` defaults deterministic.
3. `CognitiveAgent` and a real `YeomanAgent` expose cognitive.
4. `HttpFetchAgent` exposes network despite `tier == "core"`.
5. `MeshConfig` defaults are 100/10,000/30,000 ms; existing `config/system.yaml` loads those defaults without adding keys.
6. Each threshold rejects booleans, non-numeric values, zero, negative, NaN, `inf`, and `-inf`; positive fractional values are accepted.
7. Runtime passes all three config values into its bus; a bare `IntentBus(SignalManager())` uses identical built-in defaults.

### B. Subscription metadata lifecycle

8. Legacy `subscribe(agent_id, handler)` and `subscribe(agent_id, handler, intent_names=[...])` classify deterministic.
9. Explicit class hint stores the exact enum without changing the callable `_subscribers[agent_id]` value.
10. A raw string or non-enum explicit hint raises `TypeError` before either subscriber map changes.
11. Re-subscribing the same id replaces both handler and class.
12. A broadcast snapshot taken before a re-subscribe invokes the old handler with its old class; the next broadcast invokes the new handler with its new class.
13. `unsubscribe()` removes handler, class, queue, and intent-index membership as before.
14. A legacy test that directly injects `_subscribers[agent_id] = handler` still invokes as deterministic (sidecar miss fallback).
15. SIF's current `_subscribers.keys()` coherence read remains valid.
16. Onboarding passes deterministic for a real/minimal BaseAgent subclass, cognitive for a real/minimal CognitiveAgent subclass, and network for HttpFetchAgent. No tier/name inference.
17. Hot replacement re-subscribes the designed CognitiveAgent with cognitive class.
18. Yeoman proactive helper explicitly subscribes deterministic while Yeoman's normal onboarding handler is cognitive.
19. VisionConsumer and VisionAggregator explicitly subscribe cognitive.
20. Group-chat coordinator, device service, and device consensus dispatch are deterministic; only HttpFetch onboarding supplies the v1 network class.

### C. Fail-before/pass-after warnings and metrics

21. **Headline deterministic regression:** a completed deterministic response at 101 ms emits exactly one latency WARNING. Assert full `agent_id`, intent, `latency_class=deterministic`, `threshold_ms=100`, elapsed, `outcome=responded`, and `dispatch=completed`.
22. Deterministic 100 ms exactly does not warn but records a responded sample.
23. **Headline cognitive false-positive repair:** an 8,000 ms cognitive response emits no WARNING but records one cognitive responded sample.
24. **Headline network false-positive repair:** an 8,000 ms network response emits no WARNING but records one network responded sample.
25. **Extreme cognitive:** 30,001 ms cognitive response warns with `threshold_ms=30000` and remains recorded.
26. **Extreme network:** 10,001 ms network response warns with `threshold_ms=10000` and remains recorded.
27. Default/unclassified subscriber at 101 ms warns as deterministic.
28. A declined completion records `declined_count=1`; above-threshold decline warns with `outcome=declined`.
29. A handler exception records `error_count=1`, returns the same failed `IntentResult`, and emits exactly one handler-error WARNING with no latency-budget WARNING even above threshold.
30. A cancelled `_invoke_handler` propagates `CancelledError`, adds no result, records no sample, and logs no handler-error/latency warning.
31. Metrics record every below-threshold completion; absence of a warning does not mean absence of telemetry.
32. Full identifiers are present in warning fields and handler metric rows; no `[:8]`/`[:16]` truncation.

### D. Metrics bounds and compatibility

33. Existing AD-470 summary fields and values are unchanged after broadcast/send recording.
34. Handler row contains exactly the required fields and nearest-rank p95.
35. p95 matrix records ascending `1..20`: one sample `[1] -> 1`; two samples `[1,2] -> 2`; twenty samples `[1..20] -> 19` (`ceil(0.95*20)-1 == 18`).
36. 250 samples retain only the last 200 for mean/p95/max while `count` and outcome totals equal 250.
37. Re-recording an existing key refreshes LRU recency; inserting key 1,001 evicts the oldest non-refreshed key and all of its counters.
38. `handlers` rows are sorted deterministically independent of insertion order.
39. `/api/intent-metrics` still returns `subscriber_count`, `subscribers`, and old metrics fields; `handlers` is additive.
40. Invalid handler outcomes and negative/NaN/infinite elapsed values raise `ValueError` without inserting or mutating a handler row.

### E. Dispatch semantics unchanged

41. Broadcast still starts selected handlers concurrently; no serialized await is introduced.
42. Result list remains handler-completion order, not subscription order.
43. Timeout still cancels pending handler tasks and returns only results completed before the timeout; timed-out cancellation creates no completed handler sample.
44. Intent prefilter/fallback subscriber behavior remains unchanged.
45. In-flight handler still completes if the bus is closed after dispatch starts.
46. `send()` timeout/result and `send_count` behavior remain unchanged; BF-668 handler rows are not asserted for send because the scope is broadcast `_invoke_handler` only.
47. NATS, JetStream term/ack, cognitive queue, and dispatch_async tests remain green without new timing behavior.

---

## Exact test gates

Run from `D:\ProbOS`. Both commands use a unique temporary data directory, local/offline embeddings, serial execution, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf668_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_config.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_correction_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf668_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_targeted_dispatch.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py tests/test_performance_p0.py tests/test_config.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_correction_runtime.py tests/test_runtime.py tests/test_sif.py tests/test_ad843c1_device_actuation.py tests/test_ad843c2_device_consensus.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Report exact passed/failed/skipped counts and duration. Do not substitute `-n auto`, `-n 4`, full `tests/`, live network/LLM, or live runtime data.

---

## Acceptance criteria

1. `HandlerLatencyClass` is typed and has exactly deterministic/network/cognitive values.
2. BaseAgent/unclassified subscribers are deterministic; CognitiveAgent is cognitive; HttpFetchAgent is network; no core/utility/domain, name, pool, descriptor, or callable heuristic exists.
3. MeshConfig owns finite positive defaults 100/10,000/30,000 ms; runtime injects them; local `config/system.yaml` is unchanged.
4. `IntentBus.subscribe()` is additive, keyword-only for latency class, and fully typed; every existing positional caller remains valid.
5. `_subscribers` remains a callable map; class metadata is a separate sidecar with deterministic fallback.
6. Onboarding, all direct subscriptions, patched-agent replacement, and unsubscribe preserve metadata correctly.
7. Every completed broadcast-handler response/decline/error records one bounded sample keyed by full `(agent_id,intent,class)`.
8. Handler metrics expose count, mean, nearest-rank p95, max, and responded/declined/error counts; samples cap 200/key and keys cap 1,000 LRU.
9. Existing AD-470 top-level fields and `/api/intent-metrics` response remain backward-compatible; `handlers` is additive.
10. 101 ms deterministic warns; 100 ms does not.
11. 8-second cognitive and network handlers do not warn but appear in metrics.
12. 30,001 ms cognitive and 10,001 ms network handlers warn at their own class budgets.
13. Unclassified 101 ms handler remains a deterministic warning.
14. Warning contains full agent_id, intent, class, threshold, elapsed, outcome, and completed-dispatch context; no warning suppression filter is added.
15. Handler errors retain exactly one error WARNING and one error metric; no second latency WARNING.
16. Cancellation/timeout propagates/cancels as before and produces no completed handler sample, warning, or failed result from `_invoke_handler`.
17. Broadcast results, prefiltering, fan-out concurrency, completion ordering, timeout cancellation, signal lifecycle, and federation remain unchanged.
18. Targeted send, NATS request/reply, JetStream, cognitive queue, and dispatch_async behavior remain unchanged and are not silently redefined as part of handler telemetry.
19. Focused and blast gates pass isolated/local/offline/serial with `RuntimeWarning` as error; exact counts/skips are reported.
20. Only allowlisted files change; no deletion, bulk reformat, config YAML, UI, dependency, AD, decision, roadmap, era, or GitHub mutation occurs.
21. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No Yeoman, calendar lookup, persistent-task, cron cadence, M365 connector, model, prompt, LLM timeout/cache, journal, or schedule behavior change.
- No blanket logger filter, warning suppression list, rate-limit/dedup of warnings, or demotion of all latency warnings.
- No inference from core/utility/domain tier, agent id/name/pool, intent name, descriptor tier, `handler.__self__`, `__qualname__`, module path, or `isinstance(CognitiveAgent)` inside the bus/onboarding.
- No per-intent latency class on `IntentDescriptor`.
- No subscriber wrapper replacing `_subscribers` callables and no migration of SIF to a new private representation.
- No per-handler task, executor, lock, queue, semaphore, gather, sleep, or changed fan-out scheduling.
- No timing of targeted send, NATS, JetStream, `dispatch_async`, or `AgentCognitiveQueue` in this BF.
- No Prometheus, OpenTelemetry, numpy, metrics package, new endpoint, event type, persistence table/file, or external telemetry backend.
- No unbounded metrics dict/list; no payload/result/exception content in latency metric keys or latency warnings.
- No change to broadcast timeout, pending cancellation, result order, candidate filtering, signal tracking, or federation.
- No operational status, circuit breaker, trust, Hebbian, consensus, episodic, self-modification design, or agent lifecycle change beyond metadata plumbing.
- No `config/system.yaml` edit, config reload watcher, environment override, UI, npm/Python dependency, or commercial content.
- No new AD, no `DECISIONS.md`, roadmap, era file, or GitHub edit.

---

## Hard stops

Stop and return to the Architect if any of the following occurs:

1. HEAD differs from `4d8fb2e289366f3d2c1ffe5398549555a1cb6808`, BF-667 CI is not successful, origin/main/base moves, or the initial tree contains anything beyond the two BF-668 prompt documents.
2. A required behavior needs a file outside the allowlist.
3. The implementation appears to require changing `IntentMessage`, `IntentResult`, `IntentDescriptor`, `BaseAgent` method signatures, or any sealed protocol rather than adding class metadata.
4. Correct classification appears to require agent/intent/name/tier/callable heuristics or editing every CognitiveAgent subclass.
5. `_subscribers` would need to stop storing raw callables.
6. Per-class thresholds cannot be injected without importing `SystemConfig`/`MeshConfig` into the mesh layer or changing every test constructor.
7. Metrics cannot be bounded at 200 samples per key and 1,000 keys without persistence/background tasks.
8. Cancellation would be swallowed, converted into an error sample/result, or require changing broadcast cancellation/drain semantics.
9. Error timing would emit both handler-error and latency warnings.
10. Fan-out concurrency, task count, task names, candidate filtering, completion ordering, timeout, send/NATS/JetStream/queue, or federation behavior changes.
11. A focused/blast failure reproduces serially and needs an unallowlisted fix; do not quarantine, skip, or weaken it in this handoff.
12. Any local config YAML, dependency, UI, tracker (before authorized closeout), Git, or GitHub mutation appears necessary.

---

## Three-pass self-review

### Pass 1 — Behavior/spec

- Map every DD, required test, and acceptance item.
- Verify expected cognitive/network completions are metrics-only below threshold.
- Verify deterministic and extreme-class warnings remain.
- Verify errors/cancellations have exactly the pinned outcome semantics.
- Verify all eight production subscription sites are classified explicitly or through common onboarding.

### Pass 2 — Verify-first/code

- Re-grep every changed signature/import/caller.
- Confirm `_subscribers` values remain callable and SIF/private tests still match.
- Confirm BaseAgent inheritance covers every real agent; CognitiveAgent and HttpFetch overrides are exact.
- Inspect p95, 200-sample cap, 1,000-key LRU, enum/string serialization, and old metrics response.
- Count task creation before/after: one existing `_invoke_handler` task per selected candidate, no new task.

### Pass 3 — Scope/safety/license

- Verify exact allowlist and no YAML/UI/dependency/tracker drift.
- Verify no warning suppression, name/tier/callable heuristics, payload logging, private cross-module reach-through, or broad refactor.
- Verify cancellation and type annotations against `.github/copilot-instructions.md`.
- License remains none.

---

## Verified Against Codebase (2026-07-14)

```text
git rev-parse HEAD
  4d8fb2e289366f3d2c1ffe5398549555a1cb6808

git status --short
  <empty before these two Architect docs were created>

gh issue view 1034 --repo seangalliher/ProbOS
  OPEN — BF-668: Add class-aware IntentBus handler latency telemetry

gh run view 29337228647 --repo seangalliher/ProbOS
  completed / success for 4d8fb2e289366f3d2c1ffe5398549555a1cb6808

grep -n "class IntentMetrics\|def __init__(self, signal_manager\|def subscribe\|async def broadcast\|async def _invoke_handler\|Slow handler:\|Handler error for agent" src/probos/mesh/intent.py
  26: class IntentMetrics
  81: def __init__(self, signal_manager: SignalManager) -> None
  145: def subscribe(self, agent_id: str, handler: IntentHandler, intent_names: list[str] | None = None) -> None
  483: async def broadcast(
  791: async def _invoke_handler(
  804: "Slow handler: agent=%s intent=%s elapsed=%.0fms result=%s"
  814: "Handler error for agent %s on intent %s: %s"

grep -n "asyncio.create_task\|asyncio.wait\|task.cancel\|_metrics.record_broadcast" src/probos/mesh/intent.py
  566: asyncio.create_task(... _invoke_handler ...)
  574: done, pending = await asyncio.wait(tasks, timeout=timeout)
  577: task.cancel()
  584: self._metrics.record_broadcast(...)

grep -n "durations.append\|len(durations) > 200\|mean_ms\|max_ms" src/probos/mesh/intent.py
  41/50: durations.append(duration_ms)
  42/51: cap at 200
  61/62: mean_ms / max_ms

grep -n "@router.get(\"/intent-metrics\")\|intent_bus.get_metrics" src/probos/routers/system.py
  241: endpoint
  248: verbatim get_metrics response

grep -n "class MeshConfig\|class SystemConfig\|mesh: MeshConfig" src/probos/config.py
  126: MeshConfig
  6080: SystemConfig
  6085: mesh: MeshConfig = MeshConfig()

grep -n "class BaseAgent\|tier: str\|intent_descriptors" src/probos/substrate/agent.py
  18: BaseAgent
  26: tier role metadata
  29: intent descriptors

grep -n "class CognitiveAgent\|tier = \"domain\"\|async def handle_intent" src/probos/cognitive/cognitive_agent.py
  295/311/5627

grep -n "llm_client.complete\|cognitive_journal.record" src/probos/cognitive/cognitive_agent.py
  3411: LLM completion await
  3424: journal await

grep -n "class HttpFetchAgent\|tier = \"core\"\|DEFAULT_TIMEOUT" src/probos/agents/http_fetch.py
  34/44/62

grep -n "async def wire_agent\|_intent_bus.subscribe" src/probos/agent_onboarding.py
  124/172

grep -n "async def _apply_agent_correction\|_intent_bus.subscribe" src/probos/self_mod_manager.py
  188/218

grep -n "self.config = config\|self.intent_bus = IntentBus" src/probos/runtime.py
  370/386

git grep -n -E "(intent_bus|_intent_bus)\.subscribe\(" -- src/probos
  exactly 8 production sites:
  agent_onboarding.py:172
  cognitive/yeoman.py:242
  perception/aggregator.py:86
  perception/consumer.py:248
  runtime.py:496
  runtime.py:919
  self_mod_manager.py:218
  startup/finalize.py:168

grep -n "schedule_lookup\|class YeomanAgent" src/probos/cognitive/yeoman.py
  74: schedule_lookup descriptor
  122: YeomanAgent(CognitiveAgent)

grep -n "async def _handle\|async def _describe\|llm_client.complete" src/probos/perception/consumer.py
  463/886/959

grep -n "async def _handle\|await self._forward" src/probos/perception/aggregator.py
  96/103/109/144/174

grep -n "AgentCognitiveQueue\|handler=agent.handle_intent\|register_queue" src/probos/startup/finalize.py
  4146/4148/4152

grep -n "await self._handler\|Handler error for" src/probos/cognitive/queue.py
  333/342

grep -n "_subscribers" src/probos/sif.py tests/test_bf296_intent_bus_close.py tests/test_ad843c1_device_actuation.py tests/test_ad843c2_device_consensus.py
  sif.py:290 reads _subscribers.keys()
  BF-296 test directly replaces _subscribers["a1"]
  device tests assert membership in _subscribers

grep -n "test_metrics_summary\|test_broadcast_records_metrics" tests/test_ad470_intent_bus_enhancements.py
  88/138

grep -n "test_broadcast_multiple_subscribers\|test_subscriber_can_decline\|test_subscriber_error_recorded\|test_unsubscribe" tests/test_intent.py
  52/76/98/110

grep -n "test_send_timeout\|test_broadcast_with_target_delegates_to_send" tests/test_targeted_dispatch.py
  58/81

grep -n "test_in_flight_handler_completes_after_close" tests/test_bf296_intent_bus_close.py
  110

grep -n "test_dispatch_async_fallback_to_direct\|test_js_consumer_terms_on_error" tests/test_ad654a_async_dispatch.py
  75/203

grep -n "test_default_config\|test_load_from_yaml" tests/test_config.py
  12/18
```
