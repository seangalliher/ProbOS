# BF-668 Builder Execution — IntentBus handler latency classes

**Verdict:** APPROVED FOR BUILDER — BF-667 CI SUCCESS VERIFIED; RECHECK AT PRE-FLIGHT
**GitHub issue:** #1034 — https://github.com/seangalliher/ProbOS/issues/1034
**Exact base:** `4d8fb2e289366f3d2c1ffe5398549555a1cb6808`
**Scope:** Execute only `prompts/bf-668-intent-handler-latency-classes.md`. BF-668 is an OSS observability bug fix; no AD, no `DECISIONS.md`, no UI, no dependency.
**License disposition:** none.

## Pre-flight — exact base, CI, and authorized initial tree

Before implementation, test edits, staging, or any other mutation:

1. `git rev-parse HEAD` must equal exactly `4d8fb2e289366f3d2c1ffe5398549555a1cb6808`.
2. `git status --short` may show **only** these two Architect-authored untracked files:
   - `?? prompts/bf-668-intent-handler-latency-classes.md`
   - `?? prompts/bf-668-intent-handler-latency-classes-execution.md`
3. There must be no staged file, tracked modification, or other untracked file.
4. Verify read-only that CI run `29337228647` for exact SHA `4d8fb2e289366f3d2c1ffe5398549555a1cb6808` remains **completed / success**. The Architect verified success on 2026-07-14. If it later appears failed/cancelled, or is superseded by a moved base, stop.
5. Verify `origin/main` still equals the exact base. If HEAD or origin/main moved, stop for Architect re-verification; do not rebase, merge, cherry-pick, reset, or regenerate the prompt against a different tree.
6. Do not stash, restore, checkout, reset, clean, stage, commit, push, close/comment/edit an issue, or otherwise mutate Git/GitHub during pre-flight.
7. Any base/CI/tree difference is a hard stop.

Current numbering at this exact base is **AD-1121 / BF-667**. Use issue-reserved **BF-668** only. Do not mint an AD or edit `DECISIONS.md`.

The Builder must not autonomously perform any Git or GitHub mutation absent an orchestrator instruction. File edits and test execution are authorized only after this pre-flight passes.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/bf-668-intent-handler-latency-classes.md` — **binding; read fully**
- `src/probos/mesh/intent.py`
- `src/probos/types.py`
- `src/probos/config.py`
- `src/probos/substrate/agent.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/agents/http_fetch.py`
- `src/probos/runtime.py`
- `src/probos/agent_onboarding.py`
- `src/probos/self_mod_manager.py`
- `src/probos/perception/consumer.py`
- `src/probos/perception/aggregator.py`
- `src/probos/cognitive/yeoman.py`
- `src/probos/startup/finalize.py`
- `src/probos/cognitive/queue.py` — reference only; do not time this path
- `src/probos/sif.py` — representation compatibility reference
- every test in the exact allowlist below
- `prompts/archive/fix-broadcast-slowdown.md` — historical reason the 100 ms diagnostic exists; do not reinstate its universal assumption

Do not implement from this execution summary alone. The main prompt’s DD-1 through DD-8, required tests, acceptance criteria, do-not-build list, hard stops, and verified evidence are binding.

---

## Exact allowlist

### Builder may modify production

- `src/probos/types.py`
- `src/probos/config.py`
- `src/probos/substrate/agent.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/agents/http_fetch.py`
- `src/probos/mesh/intent.py`
- `src/probos/runtime.py`
- `src/probos/agent_onboarding.py`
- `src/probos/self_mod_manager.py`
- `src/probos/perception/consumer.py`
- `src/probos/perception/aggregator.py`
- `src/probos/cognitive/yeoman.py`
- `src/probos/startup/finalize.py`

### Builder may modify existing tests

- `tests/test_intent.py`
- `tests/test_ad470_intent_bus_enhancements.py`
- `tests/test_targeted_dispatch.py`
- `tests/test_ad654a_async_dispatch.py`
- `tests/test_ad654b_cognitive_queue.py`
- `tests/test_bf296_intent_bus_close.py`
- `tests/test_performance_p0.py`
- `tests/test_config.py`
- `tests/test_onboarding.py`
- `tests/test_cognitive_skill_596b.py`
- `tests/test_ad733a_vision_consumer.py`
- `tests/test_ad746_vision_aggregator.py`
- `tests/test_yeoman_agent.py`
- `tests/test_correction_runtime.py`
- `tests/test_runtime.py`
- `tests/test_sif.py`
- `tests/test_ad843c1_device_actuation.py`
- `tests/test_ad843c2_device_consensus.py`

### Architect documents already present; retain byte-for-byte during build

- `prompts/bf-668-intent-handler-latency-classes.md`
- `prompts/bf-668-intent-handler-latency-classes-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it after review

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config YAML, standing-order, workflow, UI, tracker, roadmap, decision, era, archive, dependency, data/log, or issue file is authorized.

---

## Highest-risk invariants — redundant standing order

1. **Typed class, not a heuristic.** Use `HandlerLatencyClass` with deterministic/network/cognitive only.
2. **Agent metadata is inherited.** BaseAgent deterministic; CognitiveAgent cognitive; HttpFetchAgent network. Do not edit every subclass.
3. **Tier is irrelevant.** Never infer from core/utility/domain.
4. **Callable identity is irrelevant.** Never inspect `handler.__self__`, name, qualname, module, agent id/pool, or intent name.
5. **One object may expose handlers of different classes.** Yeoman normal handler is cognitive through onboarding; Yeoman proactive helper is explicitly deterministic.
6. **`_subscribers` remains raw callables.** Add a sidecar; do not wrap/tuple/dataclass subscriber values.
7. **Legacy/unclassified remains deterministic.** Missing sidecar entry defaults deterministic, including direct test injection.
8. **API changes are additive and keyword-only.** Existing `IntentBus(SignalManager())` and 2/3-argument `subscribe()` calls remain valid; explicit hints must be real enum members and raw strings raise `TypeError`.
9. **Config is injected, not reached through.** IntentBus never imports/reads SystemConfig/MeshConfig/runtime.
10. **Thresholds are finite positive model defaults.** 100/10,000/30,000 ms; local YAML untouched.
11. **Scope is broadcast `_invoke_handler()` only.** Do not time send/NATS/JetStream/dispatch_async/cognitive queue.
12. **Every completed sample is retained in bounded metrics.** Below threshold means metrics-only, not dropped.
13. **Bounds are hard.** 200 samples/key and 1,000 keys LRU; no unbounded labels.
14. **p95 is nearest-rank.** `ceil(.95*n)-1`, deterministic, no external statistics dependency.
15. **Old metrics stay exact.** Add top-level `handlers`; do not rename/reinterpret old fields.
16. **Strict threshold.** Warn only when elapsed `>` threshold; exact threshold does not warn.
17. **Expected latency does not warn.** 8s cognitive/network is metrics-only.
18. **Extreme latency does warn.** >30s cognitive and >10s network.
19. **Errors warn once.** Record error metric; existing handler-error warning only; no second latency warning.
20. **Cancellation is not completion.** Propagate; no metric, warning, or result.
21. **Full structured identifiers.** New warning/metric rows use full agent id and intent; no truncation or payload.
22. **No warning suppression.** Deterministic 101ms and extreme class breaches still warn.
23. **No extra tasks.** Existing one `_invoke_handler` task per selected candidate only.
24. **Fan-out stays concurrent and completion-ordered.** Do not serialize, gather/reorder, or change pending cancellation.
25. **Hot replacement and unsubscribe are coherent.** Replace/remove handler and metadata together.
26. **Snapshot handler + metadata together.** `broadcast()` captures `(handler, class)` pairs before task creation; `_invoke_handler` does not re-read a mutable sidecar mid-fan-out.
27. **Direct service hints are explicit.** Group coordinator and device service/consensus are deterministic at HEAD; VisionConsumer/Aggregator are cognitive; HttpFetch is the v1 network handler.
28. **No broad test.** Exact serial focused/blast gates only.
29. **No Git/GitHub by Builder absent orchestrator.** No stage/commit/push/issue mutation on the Builder's own authority.

---

## Ordered checklist

### Step 1 — Verify base, CI, tree, callers, and current fail-before behavior

- Confirm exact SHA, origin/main, CI success, and two-doc-only status.
- Re-enumerate all eight production `IntentBus.subscribe()` sites.
- Reconfirm `_subscribers` private readers/tests and callable storage.
- Reconfirm `_invoke_handler`, broadcast task creation/wait/cancel, and the separate send/NATS/queue paths.
- Add the headline tests first and prove current behavior fails:
  - 8s cognitive incorrectly warns under universal 100 ms;
  - no handler metrics row exists;
  - subscribe has no class sidecar/hint.
- Do not run a broad baseline suite, live network, live LLM, or live runtime data.

### Step 2 — Add type and public agent metadata

- Add enum.
- Add BaseAgent default and two overrides.
- Add exact inheritance tests.

Hard gate: no per-descriptor field, no names/tier/callable inference, no subclass sweep.

### Step 3 — Add positive MeshConfig thresholds and runtime injection

- Add three float fields and one finite-positive validator.
- Keep `config/system.yaml` untouched.
- Extend `IntentBus.__init__` with optional keyword-only mapping and built-in defaults.
- Pass validated mapping from runtime.

Hard gate: bare test constructor remains valid and default parity is tested.

### Step 4 — Extend bounded metrics

- Add per-key stats, outcome counters, nearest-rank p95, 200-sample cap, 1,000-key LRU.
- Add `record_handler()` with fully typed closed outcomes.
- Add sorted `handlers` rows to `get_summary()`.
- Keep every old field/value unchanged.

Hard gate: no background task, persistence, new endpoint, or unbounded cardinality.

### Step 5 — Add subscription sidecar and metadata lifecycle

- Extend `subscribe()` keyword-only hint.
- Store/replace class synchronously beside handler.
- Remove class in `unsubscribe()`.
- Default sidecar miss deterministic.
- Snapshot each selected handler together with its class before task creation.
- Keep `_subscribers` representation.

Hard gate: SIF and direct `_subscribers` tests remain valid.

### Step 6 — Thread all production classes

- Onboarding uses real public metadata without fallback.
- Hot replacement uses new agent public metadata.
- Add exact explicit service hints from the main prompt table.
- Update strict fakes to match public contracts instead of weakening production.

Hard gate: exactly eight production call sites remain; no new subscription path or skipped site.

### Step 7 — Replace universal warning in `_invoke_handler`

- Record responded/declined/error samples exactly once.
- Apply class threshold only to normal completion.
- Keep one error warning and failed result.
- Let cancellation propagate unobserved as completion.
- Use stable structured warning fields and full identifiers.

Hard gate: no extra task, await, lock, payload logging, result reorder, or timeout change.

### Step 8 — Prove unchanged dispatch semantics

- Concurrent start barrier.
- Completion-order result assertion.
- Timeout-cancel/no-sample assertion.
- Prefilter/fallback, close-in-flight, send, NATS, JetStream, queue, and dispatch_async regression suites.

### Step 9 — Focused then blast gates

Run the exact commands below. Fix only BF-668 regressions within the allowlist. A reproducible need outside it is a hard stop.

### Step 10 — Three-pass Builder self-review

**Pass 1 — Behavior/spec:** map every DD/test/acceptance item; verify class thresholds, metrics-every-completion, errors-once, cancellation-none, all subscription sites.

**Pass 2 — Verify-first/code:** re-grep signatures/callers; inspect enum typing, config validation, sidecar lifecycle, p95/LRU, warning fields, and unchanged task/dispatch flow.

**Pass 3 — Scope/safety/license:** verify exact allowlist, no heuristic/suppression/private reach-through/YAML/UI/dependency/AD drift; license remains none.

### Step 11 — Whitespace, status, and deletion audit

Without staging:

- `git status --short` must contain only the two prompt docs plus authorized production/tests (and `PROGRESS.md` only if closeout was explicitly authorized).
- `git diff --check` for tracked edits.
- Direct no-index whitespace checks for each untracked Architect doc:
  - `git diff --no-index --check -- NUL prompts/bf-668-intent-handler-latency-classes.md`
  - `git diff --no-index --check -- NUL prompts/bf-668-intent-handler-latency-classes-execution.md`
  - Exit code `1` is expected for content difference; any emitted whitespace diagnostic is a failure.
- `git diff --name-only --diff-filter=D 4d8fb2e289366f3d2c1ffe5398549555a1cb6808 --` must be empty.
- Inspect `git diff --stat`, `git diff --numstat`, and exact diff for unrelated reformat/deletion.
- Confirm `config/system.yaml`, UI, dependency manifests, `DECISIONS.md`, roadmap, and era files are absent.

### Step 12 — Conditional closeout/commit only when directed

Only after green gates, Architect approval, and an explicit orchestrator instruction:

1. update only `PROGRESS.md` with concise BF-668 closeout, exact counts/skips, #1034, and no new AD;
2. keep both prompt docs unchanged and include them;
3. do not edit `DECISIONS.md`, roadmap, era files, issue metadata, or GitHub;
4. stage only allowlisted paths;
5. rerun staged name/deletion/whitespace audits;
6. commit exactly:

`BF-668: classify IntentBus handler latency (closes #1034)`

Do not push or mutate GitHub unless the orchestrator separately directs it. The Builder does not autonomously commit, push, close, comment, label, or edit issue #1034.

---

## Exact test gates

Run from `D:\ProbOS`.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf668_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_config.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_correction_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf668_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_targeted_dispatch.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py tests/test_performance_p0.py tests/test_config.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_correction_runtime.py tests/test_runtime.py tests/test_sif.py tests/test_ad843c1_device_actuation.py tests/test_ad843c2_device_consensus.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Report exact passed/failed/skipped counts and duration. Do not substitute `-n auto`, parallel xdist, full `tests/`, live endpoint, live LLM, network, or live runtime data.

---

## Deletion and scope audit commands

Run before any authorized staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 4d8fb2e289366f3d2c1ffe5398549555a1cb6808 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-668-intent-handler-latency-classes.md
git diff --no-index --check -- NUL prompts/bf-668-intent-handler-latency-classes-execution.md
```

Expected final paths before conditional closeout are only the two prompt docs plus the production/test allowlists above. `PROGRESS.md` is allowed only after explicit closeout direction. Any deletion, unrelated file, or bulk reformat is a hard stop.

---

## Stop conditions

Stop and report to the Architect if:

- exact base, origin/main, two-doc-only tree, or BF-667 CI-success pre-flight fails;
- any needed file is outside the allowlist;
- a name/tier/intent/callable heuristic appears necessary;
- `_subscribers` must stop storing callables;
- a sealed method/protocol/IntentMessage/IntentResult/IntentDescriptor change appears necessary;
- IntentBus must import/read config/runtime or test constructors would all need a required new argument;
- metrics would be unbounded, persistent, task-driven, or require a dependency;
- cancellation would be caught as an ordinary error or recorded as completion;
- errors would emit both error and latency warnings;
- fan-out task count/concurrency/ordering/timeout/cancel, send, NATS, JetStream, queue, dispatch_async, signal, or federation semantics change;
- warning suppression replaces class-aware thresholds;
- a serial focused/blast failure requires unallowlisted edits, skipping, quarantine, or weakened assertions;
- config YAML, UI, dependency, tracker-before-closeout, Git, or GitHub mutation appears;
- any prompt doc changes during the build.

Do not guess around a hard stop.

## Do NOT build

- Do not change Yeoman/calendar/cron/LLM behavior to make the warning disappear.
- Do not infer class from tier, names, ids, intents, modules, descriptors, or bound-callable internals.
- Do not replace `_subscribers` callables with wrapper records.
- Do not add warning filters/suppression, per-handler tasks, persistence, external metrics, or a new endpoint/event.
- Do not time send, NATS, JetStream, `dispatch_async`, or cognitive queues in BF-668.
- Do not change fan-out concurrency/order/timeout/cancellation, result shape, trust, consensus, operational status, circuit breakers, UI, dependencies, or local YAML.
- Do not add an AD, edit `DECISIONS.md`/roadmap/era files, or mutate Git/GitHub absent explicit orchestrator direction.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
