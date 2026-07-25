# AD-1122 Builder Execution — Sensorium budget telemetry v2

**Verdict:** **APPROVED / EXECUTABLE.**
**Issue:** #1036 — `AD-1122: Sensorium budget telemetry v2 — truthful units, attributed overages, sustained-warning debounce`
**Binding specification:** `prompts/ad-1122-sensorium-budget-telemetry-v2.md`
**Exact executable base:** `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`
**Exact base subject:** `BF-669: make attribution conflict hash test deterministic`
**Exact successful CI:** run `29382765061` — Python **18,825 passed / 36 skipped in 18m14s**; UI **301 files, 2,044 passed / 1 skipped**.
**Numbering:** highest landed top-level **AD-1121**; issue #1036 reserves **AD-1122**; BF ceiling **BF-669**.
**Scope:** OSS observability/config/event correction only. No UI, dependency, new event type, persistence, context enforcement, or YAML commit.
**License disposition:** none.

Do not implement from this execution summary alone. Read the binding main prompt fully. Its DD-1122-1 through DD-1122-9, exact comparisons, contributor schema, named behavioral tests, allowlist, gates, acceptance criteria, do-not-build list, hard stops, and verified evidence control the build.

---

## Cleared execution gate

The historical preflight failed, then BF-669's deterministic test correction supplied a clean replacement base:

- Historical base `b89fbe74e76da3a43b54d9f7f2dcf29a171fca63` and run `29376494746` remain audit-only context: completed/failure on the timing-dependent attribution-conflict hash assertion.
- Exact executable base `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3` is at both HEAD and `origin/main`.
- Run `29382765061` is completed/success on that exact SHA.
- Python: `18825 passed, 36 skipped` in `1094.75s (0:18:14)`.
- UI: `301 passed` test files; `2044 passed / 1 skipped` tests.
- Issue #1035 is closed; issue #1036 remains open with zero comments.
- The correction-base delta touches only `PROGRESS.md` and unrelated `tests/test_ad980b_dream_attribution.py`; it does not touch any AD-1122 production, config, event, runtime, estimator, or allowlisted test seam.

**Therefore:** the Builder may proceed on this exact base inside the allowlist. The old SHA/run are not a current hard stop. Do not reopen or modify BF-669 inside AD-1122.

---

## Pre-flight — exact base, CI, issue, and authorized initial tree

Before implementation, test edits, staging, commit, or any mutation:

1. `git rev-parse HEAD` must equal exactly `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`.
2. `git rev-parse origin/main` must equal exactly the same SHA.
3. `git status --short` must contain only:
   - `?? prompts/ad-1122-sensorium-budget-telemetry-v2.md`
   - `?? prompts/ad-1122-sensorium-budget-telemetry-v2-execution.md`
4. There must be no staged path, tracked modification, deletion, or other untracked path.
5. Query CI read-only. Run `29382765061` must remain **completed/success** for the exact SHA with the exact Python/UI summaries above. Run `29376494746` is historical only.
6. Verify issue #1035 remains closed and issue #1036 remains open, read-only only. Do not comment, label, edit, close, reopen, or assign.
7. Verify `config/system.yaml` is tracked and clean and still contains `sensorium.token_budget_warning: 10000`. This is build-preservation evidence, not authorization to edit it in AD-1122.
8. Verify `DECISIONS.md` and `PROGRESS.md` still have AD ceiling 1121 and no AD-1122 entry.
9. Re-grep every seam in the main prompt's Verified section. If signatures, caller count, registry shape, event fields, config, or tracker convention differ, stop for Architect re-verification.
10. If HEAD/origin moved, the two-doc-only tree differs, or exact run `29382765061` is not green, stop. Do not rebase, merge, cherry-pick, reset, clean, stash, restore, checkout, regenerate prompts, or switch bases.
11. Do not stage, commit, push, or mutate Git/GitHub during pre-flight.

The only authorized mutation after all pre-flight checks pass is implementation/test editing inside the exact allowlist.

---

## Read first

Read every item fully before changing assertions:

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/ad-1122-sensorium-budget-telemetry-v2.md` — **binding**
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/cognitive/attention.py` — reference only; existing estimator
- `src/probos/config.py`
- `src/probos/events.py`
- `src/probos/runtime.py` around public `emit_event` — reference only
- `src/probos/substrate/agent.py` around lifecycle — reference only
- `src/probos/cognitive/decomposer.py` around `_CAPABILITY_GAP_RE` — reference only
- `tests/test_ad666_sensorium.py`
- `tests/test_events.py`
- `tests/test_config.py`
- every file in all five exact gate commands before changing assertions
- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md` — reference only; verify no current AD-1122 insertion convention appeared

Do not infer behavior from issue prose or this execution summary when the main prompt pins a stricter rule.

---

## Exact allowlist

### Production — may modify

- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/config.py`
- `src/probos/events.py`

### Existing tests — may modify

- `tests/test_ad666_sensorium.py`
- `tests/test_events.py`
- `tests/test_config.py`

### Conditional top-level AD closeout — may modify only after all gates and self-review are green

- `PROGRESS.md`
- `DECISIONS.md`

### Architect documents — already present; retain unchanged in the implementation commit only

- `prompts/ad-1122-sensorium-budget-telemetry-v2.md`
- `prompts/ad-1122-sensorium-budget-telemetry-v2-execution.md`

### Reference-only / forbidden to modify

- `config/system.yaml`
- `docs/development/roadmap.md`
- every `progress-era-*` / `decisions-era-*` file
- `.github/**`
- `pyproject.toml` and all dependency manifests/locks
- `src/probos/cognitive/attention.py`
- `src/probos/runtime.py`
- `src/probos/substrate/agent.py`
- `src/probos/cognitive/decomposer.py`
- every snapshot/golden fixture
- UI/desktop files
- workflows
- data/log files
- Git/GitHub state except an explicitly orchestrator-authorized final local commit

No new source or test file is authorized. A reproducible need outside this allowlist is a hard stop.

---

## Build-preserved YAML standing order — redundant and binding

`config/system.yaml` is tracked at this base and currently clean. It contains the legacy key. As a build-specific preservation rule, despite the issue's expected-file list, the Builder must **not** edit, stage, or commit it in AD-1122.

Implementation compatibility is through Pydantic v2:

- canonical field `warning_chars`;
- `validation_alias=AliasChoices("warning_chars", "token_budget_warning")` in that order;
- canonical input wins when both appear;
- canonical serialization emits `warning_chars` only;
- read-only compatibility property `token_budget_warning` if retained per the main prompt;
- temporary-YAML test proves the old key loads through existing `load_config()`.

Do not add a YAML migration writer. Do not change the build-preserved YAML “for the test.” Do not use `git update-index`, skip-worktree, assume-unchanged, `.gitignore`, attributes, or any other Git mechanism to hide a YAML diff.

Any later canonical rename is a separate operational action, outside this AD and commit; this Builder's final tree must have no YAML diff.

---

## Highest-risk invariants — redundant standing order

1. **Observe-only.** No selection, dropping, truncation, summarization, retention, or enforcement.
2. **Exact seam.** `_track_sensorium_budget(cognitive_state, situation) -> int` stays exact and has one production caller.
3. **Truthful boundary.** It measures only merged chain-sensorium string characters, not full request/model-window size.
4. **Strict boundaries.** Over `>` threshold; escalate `>=` ratio; rearm `<` ratio; cooldown `>=` duration.
5. **Path-aware attribution.** Bucket values are exactly `cognitive` / `situation`; cognitive uses baseline/extensions paths; situation uses situation path; distinct layer set must have exactly one value or serialize `null`.
6. **Survivors, not producer history.** A survivor is one nonempty string entry in one final bucket dictionary. Attribute each surviving `(bucket, output_key)` once after merge; never deduplicate the same key across buckets. `_cold_start_note` may therefore produce two rows and both totals.
7. **Metadata only.** No content/snippet/hash/repr/digest/embedding/content-derived id in logs or events.
8. **Exact ordering.** `(-chars, output_key, bucket)`; then top N.
9. **Existing estimator.** Use `estimate_tokens` independently per surviving entry; aggregate estimated tokens is the sum of those per-entry estimates across the full pre-truncation set and may exceed the visible top-N row sum. Never estimate concatenated text. `top_contributors=0` versus `N` changes rows only; label the aggregate estimated, never provider/model-window tokens.
10. **Per-agent bounded state.** Scalars only; no map/history/deque/task/timer/persistence/global state.
11. **Private clock seam.** Monotonic, monkeypatchable privately; no constructor/public API and no sleep tests.
12. **First crossing immediate.** Reason `crossed` even when initially severe.
13. **Initial severe consumes escalation.** No second immediate escalation for unchanged severe input.
14. **One early escalation per active episode.** Rearm/reset is required before another.
15. **Suppressed count excludes current emitted sample.** Peak includes it.
16. **Transition priority and interval reset.** Simultaneous escalation + cooldown emits `escalated` only. After sustained/escalated emission, suppressed count is zero and peak anchor=current total.
17. **Cooldown zero visibility.** First `crossed`, subsequent `sustained` unless escalation has priority.
18. **Threshold changes reset.** Current observation is immediately reevaluated as a fresh episode.
19. **Other config changes do not erase history.** They apply on the next observation.
20. **Disabled and stop reset.** No stale active episode survives either.
21. **State before emission.** Event failure never rewinds/de-duplicates incorrectly.
22. **Warning/event together at transition.** Suppressed observations produce neither.
23. **Typed existing event.** No new `EventType`; retain old fields and defaults.
24. **Legacy threshold populated twice.** Live event `threshold == character_threshold == warning_chars`.
25. **Canonical config validation.** Use Pydantic `mode="before"` validators to reject bool before coercion, preserve ordinary numeric coercion, then validate coerced values with finite-float checks before exact range checks.
26. **Canonical alias precedence and output.** `warning_chars` wins both-key input in either payload order; `model_dump()`, `model_dump(by_alias=True)`, validation JSON schema, and serialization JSON schema are canonical-only; compatibility property assignment fails.
27. **YAML untouched.** Alias is the restart compatibility mechanism.
28. **Defensive harness fallback.** Missing/wrong-shaped non-Pydantic sensorium config fields use canonical defaults; invalid real config still fails Pydantic startup validation.
29. **Prompt invariance.** Registry/order/wrappers/context/standing orders/model/tier/call count are unchanged.
30. **No gap text.** Capture the complete transition and emitter-degradation warnings and assert each is clean under the real `_CAPABILITY_GAP_RE`.
31. **No scope expansion.** No UI/dependency/new file/roadmap/era/GitHub mutation.

---

## Ordered Builder checklist

### Step 0 — Reconfirm the cleared executable gate

- Re-run only the read-only pre-flight checks.
- Confirm exact base `bef881d8...`, exact green run `29382765061`, #1035 closed, and #1036 open.
- Do not rerun the full CI suite locally.
- Do not alter the BF-669 attribution-hash test in this AD.
- Proceed because the binding replacement-base gate is green; stop only if one of those facts changes.

### Step 1 — Fail-before tests

After the executable preflight is reconfirmed:

1. Read the three mutable test files and all gate files.
2. Replace new config-boundary `MagicMock` use with a real `SensoriumConfig`/`SystemConfig` in a minimal typed runtime stub.
3. Add the main prompt's named tests first.
4. Use a private fake monotonic clock; never sleep.
5. Run only Gate 1 and capture the expected fail-before node IDs/reasons.
6. Confirm failures prove missing alias/config fields, missing event fields, missing attribution, and missing debounce behavior—not fixture drift.

Hard stop if the fail-before requires a production/test file outside the allowlist.

### Step 2 — Canonical config

- Add `AliasChoices` to the existing import.
- Implement exact defaults and validation.
- Keep `enabled=True`.
- Implement canonical-first legacy validation alias.
- Add only the read-only compatibility property.
- Use `mode="before"` numeric validators to reject bool first; preserve normal numeric coercion, then validate coerced values for finite values and ranges.
- Prove canonical precedence in both payload orders, both dump modes, both JSON-schema modes, property assignment failure, exact valid boundaries, and each invalid field independently.
- Do not enable assignment validation across the model and do not add a property setter.
- Prove temporary legacy YAML restart compatibility.

Hard gate: repo YAML remains clean.

### Step 3 — Additive event extension

- Append only the six new defaulted fields.
- Use `field(default_factory=list)` for contributor metadata.
- Do not change `BaseEvent.to_dict()` or enum membership.
- Prove `json.dumps(event.to_dict())` succeeds.

### Step 4 — Contributor attribution

- Count only nonempty/string entries.
- Build exact metadata shape.
- Resolve layer by bucket/path and distinct layer set.
- Keep surviving same-key rows separate across buckets and count both values.
- Sort exactly and cap after sorting.
- Use existing estimator per entry; compute aggregate before top-N and never from concatenated text.
- Prove top-N `0`/`N` changes rows only.
- Add no content-bearing field or log argument.

Hard gate: unknown/ambiguous layer is `None`, never guessed.

### Step 5 — Per-agent debounce

- Add scalar state in `__init__` and private reset/clock helper.
- Implement the exact ordered transition table.
- Test strict boundaries and initial-severe behavior.
- Force simultaneous escalation+cooldown and require `escalated` only.
- Prove suppressed/peak interval state resets after emission and threshold-change over/non-over outcomes.
- Reset at start of `stop()` before existing organ/base cleanup.
- Keep state transition committed before warning/event.

Hard gate: no task, timer, map, persistence, wall clock, or sleep.

### Step 6 — Transition warning + typed event

- Use the exact truthful wording.
- Include every required structured field.
- Instantiate `SensoriumBudgetExceededEvent` and pass it to public `runtime.emit_event`.
- Event failure logs/degrades and leaves state advanced.
- Suppression writes no warning/event.
- Runtime-less transition emits warning/no event; emitter failure emits transition+degrade warnings and no repeated crossing.
- Assert both complete warning strings are capability-gap-clean.

Hard gate: no `hasattr(runtime, "emit_event")`, private runtime access, or retry.

### Step 7 — Focused and regression gates

Run Gates 1–5 exactly as copied below. Fix only AD-1122 regressions inside the allowlist. Do not substitute xdist, broad tests, or live services.

### Step 8 — Three-pass self-review

#### Pass 1 — Behavior/spec

Map every DD, named behavior, and acceptance item to code/tests. Walk every state transition manually: disabled, threshold change over/non-over, rearm equality, strict rearm, equal threshold, crossed, initial severe, suppressed, escalation, cooldown boundary, simultaneous escalation+cooldown, cooldown zero, stop, per-agent, runtime-less, and event failure. Verify counts/peaks/reasons and post-emission interval reset at each transition.

#### Pass 2 — Verify-first APIs/callers

Re-grep:

- exact method signature and one caller;
- call order after both cognitive/situation bucket builds/merges and before formatted memories/chain construction;
- registry duplicate output keys and layer/path resolution;
- `estimate_tokens` import and unchanged body;
- Pydantic aliases/defaults/validators/load path;
- existing event enum/dataclass and runtime public emitter;
- every production/test use of `token_budget_warning`;
- stop lifecycle ordering;
- untouched input dictionaries/order and zero LLM calls from tracking;
- no prompt/LLM-related diff.

#### Pass 3 — Scope/boundary/license

Verify:

- exact allowlist only;
- no content/hash/snippet telemetry;
- no YAML/roadmap/era/UI/dependency/workflow/golden/GitHub change;
- no deletion or bulk reformat;
- no capability-gap wording;
- no external material; license remains none.

### Step 9 — Closeout trackers

Only after all gates and reviews pass:

- prepend concise AD-1122 closeout to `PROGRESS.md` with exact counts/skips;
- prepend AD-1122 Context/Decision/Tests to `DECISIONS.md`;
- explicitly record build-preserved tracked-YAML alias compatibility and no YAML edit;
- state AD-1122 top-level ceiling and BF-669 BF ceiling;
- do not edit roadmap or era files.

### Step 10 — Deletion/scope/whitespace audit

Without staging:

- inspect status, stat, numstat, exact diff, and deletion list against base;
- direct no-index whitespace-check both untracked prompt docs because `git diff --check` ignores them;
- verify config YAML is absent and clean;
- verify only allowlisted files appear.

### Step 11 — Orchestrator handoff / optional local commit

Do **not** stage or commit merely because tests pass. Return the build report to the orchestrator. If and only if the orchestrator authorizes a local commit:

1. retain both prompt docs unchanged in the AD-1122 implementation commit only;
2. stage explicit allowlisted paths only—never `git add -A`;
3. rerun staged audits;
4. verify `config/system.yaml` is not staged and has no worktree diff;
5. commit exactly:

```text
AD-1122: make sensorium budget telemetry truthful and debounced (closes #1036)
```

Do not push or mutate GitHub.

---

## Exact gates

Run from `D:\ProbOS`. Every gate is serial, isolated, local/offline, cache-free, timeout-bounded, and RuntimeWarning-strict. Report exact counts/skips/durations. Do not run broad tests.

### Gate 1 — focused AD-1122/config/event

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad666_sensorium.py tests/test_events.py tests/test_config.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **81 tests**.

### Gate 2 — sensorium dispatch/merge/registry blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_sensorium_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad723_sensorium_dispatch.py tests/test_ad723a3_sensorium_metadata.py tests/test_ad723a_1_consumer_migration.py tests/test_ad723a_2_wr_consumer_migration.py tests/test_ad644_phase3_situation_awareness.py tests/test_ad646_cognitive_baseline.py tests/test_ad646b_chain_parity.py tests/test_ad635f_clinical_proactive_context.py tests/test_ad648_post_capability_profiles.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **114 tests**.

### Gate 3 — chain execution/context blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_chain_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad643a_intent_routing.py tests/test_ad632f_activation_triggers.py tests/test_ad632a_sub_task_foundation.py tests/test_bf189_chain_memory_context.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **150 tests**.

### Gate 4 — attention/prompt invariance

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_attention_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1028_context_assembler.py tests/test_ad1029_attention_faculty.py tests/test_ad1030_salience.py tests/test_ad1031_camera_bid.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **90 tests**.

### Gate 5 — CognitiveAgent lifecycle/skill/spine blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_cognitive_agent.py tests/test_cognitive_agent_skills.py tests/test_ad1034_cognitive_spine.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **102 tests**.

Combined exact pre-build inventory across Gates 1–5: **537 tests**.

No full suite, `-n auto`, parallel xdist, live endpoint, live model, or live runtime data is authorized.

---

## Deletion and scope audit

Run before staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3 --
git diff --stat
git diff --numstat
git diff -- config/system.yaml
git diff -- docs/development/roadmap.md
git diff --no-index --check -- NUL prompts/ad-1122-sensorium-budget-telemetry-v2.md
git diff --no-index --check -- NUL prompts/ad-1122-sensorium-budget-telemetry-v2-execution.md
```

For each no-index command, exit code `1` is expected because the document differs from an empty file. Any emitted whitespace diagnostic is a failure.

Expected final paths are only:

- the two Architect docs;
- the three production files;
- the three existing test files;
- `PROGRESS.md` and `DECISIONS.md` after closeout.

Any deletion, unrelated path, snapshot/golden update, YAML diff, roadmap/era diff, or bulk reformat is a hard stop.

If local staging is explicitly authorized, run:

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached --name-only --diff-filter=D
git diff --cached --stat
git diff --cached --numstat
git diff --cached -- config/system.yaml
git diff --cached -- docs/development/roadmap.md
```

Stage explicit allowlisted paths only. Never use `git add -A`.

---

## Required Builder report

Return a concise table with:

- exact base, origin, and—only if authorized—local commit SHA;
- exact successful CI run ID/SHA verified before build;
- fail-before node IDs and reasons;
- Gate 1–5 exact passed/failed/skipped counts and durations;
- changed file list;
- exact retained `_track_sensorium_budget` signature and caller count;
- exact canonical config fields/defaults and alias behavior, including before-validator bool rejection, ordinary coercion, finite/range checks, both-key precedence in both orders, both dump modes, both schema modes, property assignment failure, valid boundaries, and each invalid field;
- confirmation temporary legacy YAML loaded and tracked `config/system.yaml` stayed clean/unstaged;
- exact contributor metadata shape, surviving-per-bucket/no-cross-bucket-dedupe rule, `_cold_start_note` two-row proof, layer resolution, per-entry aggregate rounding, top-N row-only effect, sort, and no-content proof;
- state-transition table results, including strict boundaries, initial severe, simultaneous escalation+cooldown priority, interval reset, cooldown zero, threshold-change over/non-over, runtime-less behavior, every wrong-shaped harness fallback, stop, per-agent isolation, event failure, no repeated crossing, and both capability-gap-clean warnings;
- exact additive event fields and JSON serialization proof;
- prompt/context/wrapper/model/tier/call-count invariance evidence;
- tracker updates and confirmed roadmap/era omission;
- license `none`;
- three-pass review verdict;
- no deletion, UI, dependency, new event, persistence, task/timer, YAML, roadmap, era, workflow, GitHub, or push mutation.

---

## Stop conditions

Stop and report to the Architect/orchestrator if:

- exact base/origin/two-doc-only tree fails;
- exact CI run `29382765061` is no longer completed/success on the exact base or its verified summaries differ;
- #1035 is no longer closed or #1036 is no longer open;
- the historical BF-669 failure is proposed for repair inside AD-1122;
- issue/numbering/seams differ from the binding prompt;
- an edit outside the allowlist is needed;
- `config/system.yaml` changes for any reason;
- contributor telemetry would expose content or content-derived metadata;
- a public API/new event type/timer/task/global map/persistence/tokenizer/UI/dependency is needed;
- prompt/registry/dispatch/attention/LLM behavior changes;
- a gate requires sleep/live network/live model/live data;
- a test failure reproduces outside the allowlist;
- a deletion, unrelated diff, snapshot rewrite, roadmap/era edit, or bulk reformat appears;
- either complete production warning string matches the capability-gap regex;
- either approved Architect document changes during Builder execution;
- staging/commit/push/GitHub mutation is requested without orchestrator authorization.

Do not broaden scope to “make CI green.” The preflight gate is green and **no unresolved hard stop exists** at handoff.

---

## Final Architect self-review (2026-07-14)

- **Pass 1 — behavior/spec:** APPROVED; every second-pass Required correction is explicit in the binding spec and execution checklist.
- **Pass 2 — verify-first:** APPROVED; HEAD/origin are the exact executable base, the correction delta has zero AD-1122 seam drift, and `_track_sensorium_budget` still has one definition and one production caller.
- **Pass 3 — scope/boundary/whitespace:** APPROVED; only these two docs exist in the tree, forbidden paths are untouched, and both direct no-index whitespace checks emit no diagnostics.
- **Final verdict:** **APPROVED / EXECUTABLE — no unresolved hard stop.**
