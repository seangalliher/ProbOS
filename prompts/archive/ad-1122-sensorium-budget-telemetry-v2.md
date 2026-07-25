# AD-1122 — Sensorium budget telemetry v2: truthful units, attributed overages, sustained-warning debounce

**Issue:** #1036 — `AD-1122: Sensorium budget telemetry v2 — truthful units, attributed overages, sustained-warning debounce`
**Repo:** OSS (`D:\ProbOS`)
**Exact executable base:** `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3` (`BF-669: make attribution conflict hash test deterministic`)
**AD ceiling at drafting:** highest landed top-level is **AD-1121**; issue #1036 reserves **AD-1122**; no other AD number is authorized.
**BF ceiling at drafting:** **BF-669**.
**Status:** **APPROVED / EXECUTABLE.** Exact CI run `29382765061` completed **success** on this exact SHA: Python **18,825 passed / 36 skipped in 18m14s**; UI **301 files, 2,044 passed / 1 skipped**. Issue #1035 is closed; #1036 is open.
**Dependencies:** AD-666 sensorium telemetry; AD-723/723a sensorium registry/dispatch; existing AD-1028 `estimate_tokens`; BF-669 green correction base.
**Estimated tests:** approximately 38–48 additions/updates in three existing test files; no new test file.
**License disposition:** none — no external code, assets, model weights, package, or dependency.

AD-1122 remains observe-only. It corrects what the telemetry claims, attributes the merged chain-sensorium footprint, and debounces sustained warnings. It does **not** alter sensorium content, prompt order, wrappers, context selection, model routing, or LLM calls.

---

## Why / verified root cause

At the exact executable base:

1. `CognitiveAgent._execute_chain_with_intent_routing(self, observation: dict) -> dict | None` builds `_cognitive_state`, then `_situation`, merges both into `observation`, and calls `_track_sensorium_budget(_cognitive_state, _situation)` exactly once before memory formatting and chain execution.
2. `_track_sensorium_budget(self, cognitive_state: dict[str, str], situation: dict[str, str]) -> int` counts string **characters** but reads a token-named config field, warns every cycle for `total_chars > threshold`, and claims that context may crowd instruction space.
3. The method sees only the two post-dispatch merged dictionaries. It does not see standing orders, the composed system prompt, formatted memories added later, prompt wrappers, query results, strategy context, vision messages, or the final provider request. Therefore it cannot truthfully claim to measure the full request/model window or instruction crowding.
4. `SensoriumConfig` currently exposes only `enabled: bool = True` and `token_budget_warning: int = 10000`.
5. `SensoriumBudgetExceededEvent` already exists with `agent_id`, `callsign`, `total_chars`, `threshold`, `cognitive_state_chars`, and `situation_chars`; `EventType.SENSORIUM_BUDGET_EXCEEDED` already exists. This AD extends that event additively and creates no new event type.
6. `config/system.yaml` is tracked, clean at this base, and contains `sensorium.token_budget_warning: 10000`. This build preserves that file unchanged, unstaged, and uncommitted. Pydantic input alias compatibility, not a YAML edit, preserves restart behavior.
7. The live registry can map one output key to multiple producer entries. The ambiguity is resolvable from the **bucket's chain path** and distinct layer values: cognitive entries come from `CHAIN_BASELINE`/`CHAIN_EXTENSIONS`; situation entries come from `CHAIN_SITUATION`. Examples: `_source_attribution_text` has several cognitive producers but all resolve to interoception; `_cold_start_note` resolves to interoception in the cognitive bucket and exteroception in the situation bucket.
8. `estimate_tokens(text: str) -> int` is already the transparent local `~4 chars/token` heuristic. It is an estimate, not a provider-token count.
9. The correction-base delta from the historical preflight SHA `b89fbe74e76da3a43b54d9f7f2dcf29a171fca63` to `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3` touches only `PROGRESS.md` and the unrelated BF-669 test `tests/test_ad980b_dream_attribution.py`; none of the AD-1122 production, config, event, runtime, estimator, or allowlisted test seams changed.

### Historical preflight context — superseded audit record

The original preflight base `b89fbe74e76da3a43b54d9f7f2dcf29a171fca63` and CI run `29376494746` remain recorded only as audit history: that run completed failure on the timing-dependent BF-669 attribution-hash test. They are not an executable base or a current hard stop. The deterministic test correction landed as `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`, and successful run `29382765061` is the binding preflight gate for this build.

### Issue corrections binding on the Builder

- The issue's expected edit to `config/system.yaml` is **removed from committed scope**. Do not modify it.
- “Final merged output entries” means the final merged **chain-sensorium dictionaries passed to `_track_sensorium_budget`**, not the final LLM request or model window.
- Replace the instruction-crowding claim with explicit wording that this is the merged chain-sensorium character footprint and **not the full request/model-window measurement**.
- The master `sensorium.enabled` behavior remains enabled by default. This is not a transitional default-off feature.
- The current roadmap hub does not carry AD-1119/1120/1121 and the latest top-level AD commit updated `PROGRESS.md` + `DECISIONS.md`, not the roadmap. AD-1122 therefore updates `PROGRESS.md` and `DECISIONS.md` only; `docs/development/roadmap.md` stays unchanged.

---

## Pinned design decisions

### DD-1122-1 — Preserve the exact tracking seam and truthful measurement boundary

Keep this exact production signature and return contract:

```python
def _track_sensorium_budget(
    self,
    cognitive_state: dict[str, str],
    situation: dict[str, str],
) -> int:
```

It returns the combined character count of nonempty/string values in those two merged dictionaries. Non-string values are ignored. It never blocks or modifies either input.

The one caller remains in `_execute_chain_with_intent_routing`, after `_build_cognitive_state(...)` and `_build_situation_awareness(...)`, before `_formatted_memories`, triage-chain construction, prompt rendering, or any LLM call. Do not move, duplicate, widen, or rename it. Do not start measuring DM/WR one-shot sensorium, full prompts, standing orders, model windows, or provider token usage in this AD.

### DD-1122-2 — Contributor metadata is path-aware, deterministic, and content-free

Define a **surviving contributor** as one nonempty string entry present in one final post-merge bucket dictionary at the tracking seam. Create exactly one metadata row for every surviving `(bucket, output_key)` pair with this exact wire shape:

```text
{
  "bucket": "cognitive" | "situation",
  "output_key": <the dictionary key>,
  "layer": "proprioception" | "interoception" | "exteroception" | null,
  "chars": <len(value)>,
  "estimated_tokens": <estimate_tokens(value)>
}
```

Layer resolution is exact:

1. For `bucket="cognitive"`, consider only registry entries whose `output_key` equals the dictionary key and whose `paths` include `CHAIN_BASELINE` or `CHAIN_EXTENSIONS`.
2. For `bucket="situation"`, consider only matching entries whose `paths` include `CHAIN_SITUATION`.
3. Reduce the candidates to distinct `entry.layer.value` values.
4. Exactly one distinct layer ⇒ emit it. Zero or more than one distinct layer ⇒ `null`; do not guess, use an inventory-only entry, or infer from the key name.

This resolves same-key cross-bucket cases without assigning provenance to an overwritten producer. The method attributes the **surviving merged key in each bucket**, not every producer invocation. Never deduplicate across buckets: if the same `output_key` survives in both dictionaries, it contributes two rows and both values contribute to character and estimated-token totals. In particular, `_cold_start_note` surviving in both buckets produces separate `cognitive`/interoception and `situation`/exteroception rows and both lengths count.

Sort all contributors by exact tuple `(-chars, output_key, bucket)` and retain the first `config.sensorium.top_contributors`. `top_contributors=0` yields `[]` while totals still work. Log/event metadata must contain only the five fields above. Never include the value, a snippet, prefix/suffix, repr, hash, digest, embedding, or content-derived identifier.

Total `estimated_tokens` is the sum of each surviving entry's individual `estimate_tokens(value)` across the full pre-truncation contributor set. Do not concatenate values and estimate once: per-entry ceiling/rounding is part of the contract. Because only top-N rows are visible, the aggregate may legitimately exceed the sum of `estimated_tokens` in the visible rows. Changing `top_contributors` from `0` to `N` changes rows only—never character totals, aggregate estimated tokens, state transitions, warning cadence, or event cadence. The result must be labeled estimated; never call it provider tokens or model-window tokens.

Private, fully annotated helper methods are allowed to keep attribution/state-transition logic focused. No new public API is allowed.

### DD-1122-3 — Canonical config plus Pydantic v2 legacy input compatibility

Replace the token-named field with these canonical fields and exact defaults:

| Field | Default | Validation |
|---|---:|---|
| `enabled` | `True` | existing master behavior |
| `warning_chars` | `10000` | integer `>= 1`; reject bool |
| `warning_cooldown_seconds` | `21600.0` | finite number `>= 0`; reject bool |
| `warning_rearm_ratio` | `0.90` | finite number, strict `0 < value < 1`; reject bool |
| `warning_escalation_ratio` | `1.25` | finite number `>= 1`; reject bool |
| `top_contributors` | `5` | integer `>= 0`; reject bool |

Import and use Pydantic v2 `AliasChoices`:

```text
validation_alias=AliasChoices("warning_chars", "token_budget_warning")
```

The canonical name is first, so when both input keys are supplied, `warning_chars` wins. `model_dump()` and schema output use only the canonical field name. Add a read-only compatibility property `token_budget_warning -> int` returning `warning_chars`; do not add an assignment setter because live production callers are migrated to `warning_chars`, the source grep found no other production setter/consumer, and assignment would bypass the model's construction-time validation unless the whole model enabled assignment validation.

Use Pydantic v2 `field_validator(..., mode="before")` on every numeric field to reject `bool` **before** Pydantic numeric coercion. Preserve normal integer/float coercion for valid numeric inputs (including numeric strings). Then validate the coerced values: require finite values for every float field before applying its range rule, and apply integer ranges after integer coercion. Production values come from this validated Pydantic model.

Preserve the current missing-config/test-double degradation too: if the runtime has no sensorium config or a generic test double auto-vivifies a wrong-shaped field (including `MagicMock`, bool in a numeric slot, nonfinite, or out-of-range), `_track_sensorium_budget` uses that field's canonical default and never compares/logs the wrong-shaped object. Exercise every numeric field—`warning_chars`, `warning_cooldown_seconds`, `warning_rearm_ratio`, `warning_escalation_ratio`, and `top_contributors`—as a separate **wrong-shaped runtime harness field** while all sibling fields remain valid, so each fallback is proven rather than masked by an earlier invalid field. This is a defensive runtime fallback for incomplete harnesses, not a second config-acceptance path; invalid real configuration must still fail Pydantic parsing at startup.

Required compatibility proofs:

- `SensoriumConfig(token_budget_warning=123).warning_chars == 123`;
- `SensoriumConfig(warning_chars=456, token_budget_warning=123).warning_chars == 456`;
- canonical precedence is proven in both keyword insertion orders, independent of payload order;
- `model_dump()` and `model_dump(by_alias=True)` contain `warning_chars` and not `token_budget_warning`;
- `model_json_schema(mode="validation")` and `model_json_schema(mode="serialization")` expose only canonical field names;
- `load_config()` accepts a temporary YAML containing the legacy key, proving the build-preserved tracked YAML will parse after restart without an edit;
- the compatibility property reads the canonical value and assignment to it fails;
- exact valid boundaries are accepted: `warning_chars=1`, `warning_cooldown_seconds=0`, `warning_rearm_ratio` immediately inside both open bounds, `warning_escalation_ratio=1`, and `top_contributors=0`;
- each numeric field independently rejects bool and its own nonfinite/out-of-range cases while ordinary numeric coercion remains accepted.

Do not add custom YAML parsing, environment-variable reads, or a config migration writer.

### DD-1122-4 — Per-agent scalar debounce state; no task, timer, persistence, or map

Add only bounded per-`CognitiveAgent` scalar state initialized in `__init__`:

- active episode flag;
- last emission monotonic timestamp (`float | None`);
- suppressed over-budget observation count;
- peak character count since the last transition emission;
- whether the one early escalation has been consumed in this active episode;
- last applied character threshold (`int | None`) for config-change detection.

Names may follow local private naming style, but the state must stay instance-owned. No module/class/global dictionary, per-agent registry, deque/history, task, timer, callback, persistence, database row, or background loop.

For deterministic tests, add one **private** clock seam only, such as a private static method returning `time.monotonic()`. Tests may monkeypatch that private seam. Do not add a constructor argument, public setter, protocol, config field, or wall-clock dependency.

### DD-1122-5 — Exact transition table and strict boundaries

Use these exact comparisons and ordering:

- Over budget: `total_chars > warning_chars` (strict; equality does not cross). This preserves AD-666's existing boundary.
- Escalation boundary: `total_chars >= warning_chars * warning_escalation_ratio`.
- Rearm boundary: `total_chars < warning_chars * warning_rearm_ratio` (strictly below; equality does not rearm).
- Cooldown due: `now - last_emitted_at >= warning_cooldown_seconds`.

State machine, in order:

1. If telemetry is disabled, clear the full debounce episode state and return the character count with no warning/event.
2. If `warning_chars` differs from the last applied threshold, clear the episode state, record the new threshold, and evaluate the **current** observation as a fresh episode. Thus a current overage emits a fresh `crossed`; a current non-overage remains quiet.
3. If an active episode falls strictly below the rearm boundary, clear the episode (while retaining the current threshold marker) and return quietly. Values exactly at rearm, in the deadband, or exactly at warning threshold do not rearm.
4. If not over budget, return quietly.
5. If over budget and no active episode exists, emit immediately with `reason="crossed"`, set peak to the current total, set the last emission time, zero suppressed count, and mark early escalation consumed **when this initial sample already meets the escalation boundary**. This “initial severe” rule prevents an unchanged severe value from producing a second immediate warning on the next cycle.
6. For an active overage, update peak first. If early escalation is unconsumed and the current total reaches the escalation boundary, emit `reason="escalated"` before considering routine cooldown and consume the one escalation.
7. Otherwise, if cooldown is due, emit `reason="sustained"`.
8. Otherwise suppress this over-budget observation: increment suppressed count, retain the larger peak, and emit neither warning nor event.
9. On an `escalated` or `sustained` emission, payload `suppressed_count` reports only previously suppressed observations; the current emitted observation is not counted as suppressed. Payload `peak_chars` includes the current sample. After emission, zero the suppressed count, set last emission to `now`, and use the current total as the next interval's peak anchor. Do not re-enable early escalation until rearm/reset.
10. `warning_cooldown_seconds == 0` restores legacy every-overage-cycle visibility: first event is `crossed`; each subsequent active overage is `sustained` unless a not-yet-consumed escalation transition has priority.

Policy changes other than `warning_chars` apply to the next observation without silently rewriting history: cooldown affects the next due check, rearm affects the next below-boundary check, escalation affects the next unconsumed escalation check, and top-N affects the next emitted metadata. Only `enabled=False`, a character-threshold change, strict hysteresis rearm, or `stop()` clears the active episode.

Required ordering proofs are binding: simultaneous escalation + cooldown on the same observation emits exactly one `escalated` transition and no `sustained` transition; after any transition emission, the interval suppressed count is zero and the interval peak is reset to the current emitted sample before the next observation. If `warning_chars` changes while the current sample is over the new threshold, emit a fresh `crossed`; if it is not over, stay quiet with reset state.

### DD-1122-6 — Stop resets debounce state

`CognitiveAgent.stop() -> None` remains the public signature and still detaches organs then awaits `BaseAgent.stop()`. Add a synchronous private state reset at the beginning of `stop()`; no await or cleanup task is needed. After stop, the next overage on a reused/test instance behaves as a fresh `crossed` episode.

### DD-1122-7 — Warning and typed event are one transition surface

At each `crossed`, `escalated`, or `sustained` transition:

1. Commit the debounce state transition **before** event emission.
2. Emit exactly one structured `logger.warning` containing: agent id/callsign, `reason`, `total_chars`, `estimated_tokens`, `character_threshold`, `cognitive_state_chars`, `situation_chars`, `suppressed_count`, `peak_chars`, and metadata-only `top_contributors`.
3. The transition warning must explicitly say: **“merged chain sensorium character footprint; not the full request/model-window measurement.”** Remove the instruction-space/crowding claim.
4. When a runtime exists, call the stable public `runtime.emit_event(...)` with a typed `SensoriumBudgetExceededEvent`, not a new event type and not a private runtime method.
5. If typed event emission raises, log a second contextual degradation warning explaining which event/agent failed, that telemetry continues, and that debounce state remains committed. Do not rewind state or re-emit the same transition on the next call. A test must capture both the transition warning and this degradation warning and assert each complete warning string is clean under the real `_CAPABILITY_GAP_RE`.
6. Outside a transition, emit neither the budget warning nor the budget event.

A runtime-less agent still emits exactly the transition warning and no event. An emitter failure produces the transition warning plus one degradation warning, advances/reset interval state exactly once, and an unchanged next sample before the next valid transition must not repeat `crossed`.

A runtime-less test agent may still write the transition warning but has no event sink. Do not add `hasattr(runtime, "emit_event")`; `emit_event` is a stable public runtime API.

### DD-1122-8 — Extend the existing event additively and keep JSON-safe typing

Keep `EventType.SENSORIUM_BUDGET_EXCEEDED` unchanged. Keep every existing `SensoriumBudgetExceededEvent` field and default. Append only these defaulted fields after the existing ones:

```text
estimated_tokens: int = 0
character_threshold: int = 0
reason: str = ""
suppressed_count: int = 0
peak_chars: int = 0
top_contributors: list[dict[str, str | int | None]] = field(default_factory=list)
```

On live emission, set legacy `threshold` and canonical `character_threshold` to the same `warning_chars` value. `BaseEvent.to_dict()` must remain unchanged. A test must instantiate the event with nested contributor metadata, call `to_dict()`, pass the result through `json.dumps`, and prove old plus new fields survive with plain JSON scalar/list/dict values.

### DD-1122-9 — Prompt/context/LLM behavior is invariant

AD-1122 changes observability only:

- no input dictionary mutation;
- no observation key insertion/removal/reordering;
- no change to `SensoriumEntry`, registry ordering, dispatch, wrappers, or paths;
- no change to `_build_cognitive_state`, `_build_situation_awareness`, `_build_user_message`, sub-task prompt builders, standing orders, memories, salience, attention selection, or context budgets;
- no extra LLM request, no tier/model change, no token cap change, no call-count change;
- no hard truncation, dropping, summarization, retention ranking, or enforcement.

The AD-723 chain snapshot and AD-1028 DM/WR goldens remain byte-identical and their fixture files are not regenerated. The chain/sensorium/attention/blast gates below are mandatory regression proofs.

The direct invariance test must additionally prove all of the following in one production-shaped execution: the exact `_track_sensorium_budget(self, cognitive_state, situation) -> int` signature; exactly one production caller; the call occurs after both bucket builds/merges and before formatted memories and chain construction; the original cognitive/situation inputs and their values/order remain untouched; and the tracking seam causes zero LLM calls.

---

## Ordered implementation

### Section 1 — Fail-before tests and real fixtures

Before production edits, update only the allowlisted tests to encode the new contract and show focused failures against the exact executable base. Use a real `SensoriumConfig`/`SystemConfig` inside a minimal typed runtime stub; do not continue the existing `MagicMock` auto-attribute config pattern for new cases.

Record failing node IDs/reasons in the Builder report. Do not weaken existing layer/registry/event-type assertions.

### Section 2 — Canonical `SensoriumConfig`

In `src/probos/config.py`:

1. Add `AliasChoices` to the existing Pydantic import.
2. Replace only `SensoriumConfig` with the canonical fields/defaults/validators from DD-1122-3.
3. Add the read-only `token_budget_warning` compatibility property.
4. Keep `SystemConfig.sensorium` mounted at the existing seam; do not move or duplicate it.
5. Do not edit `load_config()`; prove its existing `SystemConfig.model_validate(raw)` path accepts the legacy YAML key.
6. Use `mode="before"` numeric validators to reject bool before normal coercion, plus coerced-value validators/constraints for finite-then-range checks as pinned in DD-1122-3.

### Section 3 — Additive event payload

In `src/probos/events.py`, extend only `SensoriumBudgetExceededEvent` per DD-1122-8. Do not alter the event enum or `BaseEvent.to_dict()`.

### Section 4 — Contributor attribution and debounce state

In `src/probos/cognitive/cognitive_agent.py`:

1. Import the existing typed event beside `EventType`.
2. Initialize the per-agent scalar debounce fields in `__init__`.
3. Add fully annotated private reset, clock, attribution, and transition helpers only as needed.
4. Replace `_track_sensorium_budget` internals while preserving its exact signature and return.
5. Resolve layer metadata by bucket/path, keep same-key cross-bucket survivors separate, sort exactly, and cap top-N rows only after computing all per-entry aggregates.
6. Implement the exact state machine and strict comparisons in DD-1122-5.
7. Advance state before warning/event work; catch event-emission failure without rollback.
8. Reset state at the start of `stop()` while preserving organ and base teardown order.

Do not touch the call site except an AD-1122 comment/docstring correction if necessary. The call remains exactly once in the same location.

### Section 5 — Behavioral/config/event tests

#### `tests/test_ad666_sensorium.py`

Keep the AD-666 registry/layer checks and update the budget/config coverage with these named behaviors (a parametrized invalid-value matrix may represent several names, but each listed behavior must be explicit in test names or case IDs):

1. `test_track_signature_and_return_remain_exact`
2. `test_truthful_units_and_metadata_contain_no_content_hash_or_snippet`
3. `test_contributors_sort_by_negative_chars_key_bucket`
4. `test_contributor_layers_are_resolved_by_bucket_chain_path`
5. `test_unknown_or_ambiguous_contributor_layer_is_none`
6. `test_empty_and_nonstring_entries_are_ignored_without_mutating_inputs`
7. `test_equal_warning_threshold_does_not_cross`
8. `test_first_crossing_emits_crossed_warning_and_typed_event_immediately`
9. `test_sustained_overage_suppresses_and_accumulates_count_and_peak`
10. `test_cooldown_boundary_emits_sustained_summary`
11. `test_early_escalation_emits_once_before_cooldown`
12. `test_initial_severe_crossing_is_crossed_and_does_not_double_escalate`
13. `test_rearm_ratio_equality_does_not_rearm`
14. `test_strictly_below_rearm_ratio_rearms_next_crossing`
15. `test_cooldown_zero_emits_every_overage_cycle`
16. `test_disabled_returns_count_emits_nothing_and_resets_episode`
17. `test_warning_chars_change_resets_and_re_evaluates_current_sample`
18. `test_debounce_state_is_isolated_per_agent`
19. `test_stop_resets_debounce_state`
20. `test_emitter_failure_degrades_without_rewinding_debounce_state`
21. `test_warning_and_event_occur_only_at_transitions`
22. `test_no_runtime_uses_defaults_and_preserves_return_contract`
23. `test_sensorium_config_canonical_defaults`
24. `test_sensorium_config_accepts_legacy_alias`
25. `test_sensorium_config_canonical_wins_when_both_keys_present`
26. `test_sensorium_config_dump_is_canonical_and_legacy_property_reads_value`
27. `test_load_config_accepts_legacy_sensorium_yaml_without_repo_yaml_edit`
28. `test_sensorium_config_rejects_bool_nonfinite_and_out_of_range_values`
29. `test_tracking_preserves_chain_prompt_context_and_makes_no_llm_call`
30. `test_same_output_key_surviving_in_both_buckets_counts_two_rows_and_both_totals`
31. `test_estimated_token_aggregate_uses_per_entry_rounding_before_top_n`
32. `test_top_contributors_zero_and_n_change_rows_only`
33. `test_simultaneous_escalation_and_cooldown_emits_escalated_only`
34. `test_emission_resets_interval_suppressed_count_and_peak_anchor`
35. `test_threshold_change_over_emits_crossed_and_non_over_stays_quiet`
36. `test_runtime_less_transition_warns_once_without_event`
37. `test_each_wrong_shaped_runtime_config_field_falls_back_independently`
38. `test_both_transition_and_emitter_degrade_warning_strings_are_capability_gap_clean`

Use a deterministic private fake monotonic clock. Do not sleep.

#### `tests/test_events.py`

Add `test_sensorium_budget_event_additive_json_serialization`: old fields remain, all new defaults/values serialize, nested contributor metadata is JSON-safe, and the event type string remains `sensorium_budget_exceeded`.

#### `tests/test_config.py`

Add/retain direct root-level load coverage if needed to prove `SystemConfig` and a temporary legacy YAML both parse. Do not point this new compatibility test at the build-preserved repo YAML; use `tmp_path`. Explicitly prove before-validator bool rejection, ordinary numeric coercion, finite-then-range validation, canonical precedence in both payload orders, both dump modes, both JSON-schema modes, read-only property assignment failure, exact valid boundaries, and each field's invalid cases.

### Section 6 — Tracker closeout only after all gates are green

- Prepend one concise `AD-1122 shipped` block to `PROGRESS.md` with #1036, exact behavior, issue corrections, exact gate counts/skips, and “AD-1122 is the new top-level; BF ceiling remains BF-669.”
- Prepend `### AD-1122: Sensorium budget telemetry v2 — truthful units, attributed overages, sustained-warning debounce (#1036)` under Era V in `DECISIONS.md`, with Context / Decision / Tests. Include the build-preserved-YAML alias decision and observe-only boundary.
- Do **not** update `docs/development/roadmap.md`; current convention does not require it for this top-level AD and the hub explicitly lags.
- Do not edit era tracker/archive files.

---

## Exact production/test/tracker allowlist

### Production — may modify

- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/config.py`
- `src/probos/events.py`

### Existing tests — may modify

- `tests/test_ad666_sensorium.py`
- `tests/test_events.py`
- `tests/test_config.py`

### Conditional closeout after green gates — may modify

- `PROGRESS.md`
- `DECISIONS.md`

### Architect documents — retain in the implementation commit only

- `prompts/ad-1122-sensorium-budget-telemetry-v2.md`
- `prompts/ad-1122-sensorium-budget-telemetry-v2-execution.md`

No new source or test file is authorized. No other production, test, config, YAML, prompt, archive, workflow, UI, dependency, manifest, data/log, roadmap, era, Git, or GitHub file is authorized. During implementation, these two already-reviewed Architect documents must not be edited again; retain them only in the one authorized AD-1122 implementation commit, then follow normal post-ship prompt archival policy separately if directed.

`config/system.yaml` is explicitly **build-preserved and forbidden to modify/stage/commit** even though it is tracked. This is a build-specific preservation rule, not a universal claim about repository ownership or future operations. Its legacy key is supported by the Pydantic alias. Any later canonical rename is a separate operational action; this Builder run must finish with no local YAML diff.

---

## Exact planned gates — serial, isolated, local/offline, warning-strict

Do not run broad tests, full `tests/`, xdist, `-n auto`, a live model/endpoint, or the live runtime data directory. Run from `D:\ProbOS`. Every gate uses a unique temporary `PROBOS_DATA_DIR`, `PROBOS_EMBEDDINGS=local`, Hugging Face/Transformers offline mode, `-n 0`, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error.

### Gate 1 — focused AD-1122/config/event

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad666_sensorium.py tests/test_events.py tests/test_config.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **81 tests** across these files. This is the collection inventory, not a claimed local baseline execution.

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

Exact executable-base pre-build inventory: **90 tests**. The unchanged AD-1028 DM/WR goldens are the prompt-byte invariance gate.

### Gate 5 — CognitiveAgent lifecycle/skill/spine blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad1122_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_cognitive_agent.py tests/test_cognitive_agent_skills.py tests/test_ad1034_cognitive_spine.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Exact executable-base pre-build inventory: **102 tests**.

Combined exact pre-build inventory across Gates 1–5: **537 tests**.

Report exact passed/failed/skipped counts and durations for all five gates. No broad fallback gate is authorized.

---

## Acceptance criteria

1. Exact base and origin are `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`, and successful exact-base CI run `29382765061` was verified **before** production/test/tracker mutation; otherwise no build occurred.
2. `_track_sensorium_budget(cognitive_state, situation) -> int` retains its exact signature, one call site, strict character count, and return value.
3. Measurement and wording are truthful: merged chain-sensorium characters only; explicitly not full request/model-window measurement; no instruction-crowding claim.
4. Contributor metadata uses surviving `(bucket, output_key)` rows without cross-bucket dedupe, path-aware layer resolution, existing per-entry `estimate_tokens`, exact deterministic sort, configured top-N rows only, and no content/hash/snippet.
5. Empty/non-string values are ignored and caller dictionaries are unchanged.
6. First crossing, suppression, cooldown summary, one early escalation, initial-severe behavior, strict hysteresis, rearm, cooldown zero, disabled reset, threshold-change reset, per-agent isolation, stop reset, and emitter-failure state retention match DD-1122-5/6/7.
7. Budget warning and existing typed event occur only at transitions; event-emission failure degrades without rollback.
8. `SensoriumBudgetExceededEvent` keeps its type and old fields, adds only defaulted JSON-safe fields, and serializes through unchanged `BaseEvent.to_dict()`.
9. Canonical config defaults/validation are exact; before validators reject bool while preserving numeric coercion; finite/range order is pinned; `AliasChoices` accepts the tracked legacy key; canonical input wins in either payload order; both dump and JSON-schema modes are canonical-only; compatibility property is read-only.
10. `config/system.yaml` is unchanged, unstaged, and absent from the commit.
11. Prompt content/order/wrappers, registry/dispatch, context assembly, attention/salience, model tier, request count, and LLM calls remain unchanged; all five exact gates are green.
12. No tokenizer/dependency, UI, persistence, background task, timer, global state map, hard budget enforcement, truncation, dropping, summarization, new event type, or capability-gap prompt text is introduced.
13. `PROGRESS.md` and `DECISIONS.md` receive concise additive AD-1122 closeout only after gates; roadmap and era files remain unchanged.
14. Both approved Architect documents remain unchanged during Builder execution and are retained in the implementation commit only; no archive move occurs within this build.
15. Final local commit subject is exactly: `AD-1122: make sensorium budget telemetry truthful and debounced (closes #1036)`.
16. License disposition remains `none`.
17. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## What this does NOT change / do not build

- No hard context/model-window enforcement, truncation, dropping, summarization, compression, or retention ranking.
- No global attention enablement and no reinterpretation of dispatch priority as retention importance.
- No removal of safety, identity, grounding, working-memory, standing-order, salience, recall, or persistence content.
- No change to prompt text/order/wrappers, `ContextAssembler`, `AttentionBid`, `_build_user_message`, sub-task prompts, model tiers, token caps, or LLM call count.
- No DM/WR one-shot budget telemetry expansion; chain merged dictionaries only.
- No provider tokenizer or new dependency; `estimate_tokens` remains explicitly heuristic.
- No UI/HXI panel, API endpoint, metric store, history, database, persistence, timer, task, or global map.
- No new event type; extend `SENSORIUM_BUDGET_EXCEEDED` only.
- No `config/system.yaml` edit or committed local canonical rename.
- No `docs/development/roadmap.md` or era-file edit.
- No new test file.
- No AD-1123 or BF-670; this handoff is AD-1122 only.
- No GitHub issue/comment/label/close/push mutation by the Builder unless separately directed by the orchestrator after local review.

---

## Hard stops

Stop without production/test/tracker edits if any of these is true:

1. HEAD or `origin/main` differs from exact base `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`.
2. Initial tree is not exactly the two untracked AD-1122 Architect docs.
3. Exact CI run `29382765061` is no longer completed/success for that exact SHA, or its Python/UI summaries differ from the verified evidence below.
4. Issue #1035 is no longer closed or #1036 is no longer open before implementation.
5. The live signatures/caller count/event/config/registry shapes differ from Verified Against Codebase below.
6. A required edit falls outside the allowlist, including `config/system.yaml`, a snapshot fixture, UI, dependency, roadmap, era file, workflow, or new test file.
7. Correctness appears to require changing `SensoriumEntry`, `BaseAgent`, `IntentMessage`, `IntentResult`, `BaseEvent.to_dict()`, an event type, prompt assembly, or an LLM call.
8. Contributor attribution would require logging/serializing content or a content-derived value.
9. A test needs real sleep, wall clock, live network/model, or live data.
10. Any deletion, bulk reformat, or unrelated diff appears.
11. Either complete production warning string introduced by this AD—the transition warning or emitter-degradation warning—matches `_CAPABILITY_GAP_RE`.
12. Any gate fails outside the authorized files; report it rather than expanding scope.

---

## Tracking and exact commit

After all five gates and three-pass review are green, the orchestrator may authorize local staging/commit. Stage explicit allowlisted paths only; never use `git add -A`.

Exact commit subject:

```text
AD-1122: make sensorium budget telemetry truthful and debounced (closes #1036)
```

Retain both prompt docs in the implementation commit; do not archive or delete them within this build. Do not push or mutate GitHub unless the orchestrator separately instructs it.

---

## Pre-dispatch spec-completeness checklist

**Numbering & boundary**

- [x] Highest landed top-level verified from `DECISIONS.md`/`PROGRESS.md` as AD-1121; #1036 reserves AD-1122.
- [x] BF ceiling verified as BF-669.
- [x] OSS repository boundary verified; no private-business material.

**Verify-first**

- [x] Exact HEAD/origin and clean pre-authoring tree verified.
- [x] Full issue #1036 and zero comments read.
- [x] Repository instructions, prompt template, and review criteria read.
- [x] Exact method/caller/event/config/runtime-emitter signatures grepped and opened.
- [x] Registry duplicate-output-key ambiguity empirically enumerated and resolved by bucket/path.
- [x] Pydantic 2.12.5 `AliasChoices` precedence empirically verified with legacy/canonical/both-key inputs.
- [x] Build-preserved tracked YAML and legacy key verified.
- [x] Tracker/roadmap convention and implementation-commit-only prompt retention verified.

**Completeness**

- [x] Every build item maps to acceptance and named tests.
- [x] Strict warning/escalation/rearm/cooldown boundaries are pinned.
- [x] Initial-severe, threshold-change, stop, disabled, and event-failure state semantics are pinned.
- [x] No public API, DB/store, new tier/gate/intent, or destructive operation is introduced.
- [x] No default-off requirement applies; existing enabled/default behavior is preserved.

**Discipline**

- [x] Explicit do-not-build and hard-stop lists supplied.
- [x] No async task/timer; stop remains cancellation-safe through existing base behavior.
- [x] Layer discipline preserved; all work stays in cognitive/config/event seams.
- [x] Compliance sentence present.

**Final Architect self-review (2026-07-14)**

- [x] Pass 1 — behavior/spec: every second-pass Required correction maps to pinned behavior and named tests.
- [x] Pass 2 — verify-first: exact replacement base/origin, one definition/one production caller, live signatures, and zero correction-base seam drift verified.
- [x] Pass 3 — scope/boundary/whitespace: exactly the two Architect docs in the tree; no forbidden diff or private-business material; direct no-index whitespace checks clean.
- **Verdict: APPROVED / EXECUTABLE; no unresolved hard stop.**

---

## Verified Against Codebase (2026-07-14, exact executable HEAD `bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3`)

```text
BASE / TREE / CI
git rev-parse HEAD
  bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3
git rev-parse origin/main
  bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3
git status --short
  ?? prompts/ad-1122-sensorium-budget-telemetry-v2-execution.md
  ?? prompts/ad-1122-sensorium-budget-telemetry-v2.md
git log -1 --format=%H%n%s
  bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3
  BF-669: make attribution conflict hash test deterministic
git diff --name-status b89fbe74...bef881d8
  M PROGRESS.md
  M tests/test_ad980b_dream_attribution.py
git diff --name-only b89fbe74...bef881d8 -- <all AD-1122 seam/allowlist files>
  <empty: no AD-1122 seam drift>
gh run view 29382765061
  completed / success; headSha=bef881d8650ba2e3b5e65b5c6fb49dc40f61b4c3
  python-tests: 18,825 passed / 36 skipped in 1094.75s (18m14s)
  ui-tests: 301 files; 2,044 passed / 1 skipped
historical preflight only
  b89fbe74... / run 29376494746 = completed/failure before deterministic BF-669 test correction

NUMBERING
DECISIONS.md heading maximum
  AD-1121
PROGRESS.md AD maximum
  AD-1121
PROGRESS.md BF maximum
  BF-669
AD-1122 in DECISIONS.md / PROGRESS.md
  zero hits
GitHub issue #1036
  OPEN; AD-1122 reserved; zero comments
GitHub issue #1035
  CLOSED

TRACKING CONVENTION
git show --name-status 509e8cd74a8ea054ca04a94c6f9de9a74884d60d
  latest top-level AD batch includes PROGRESS.md + DECISIONS.md; no roadmap edit
docs/development/roadmap.md:1-12
  hub states PROGRESS.md authoritative and roadmap lags
grep AD-1119|AD-1120|AD-1121 docs/development/roadmap.md
  zero hits
prompts root
  these two AD-1122 docs are retained in the implementation commit only; no archive move within this build

BUILD-PRESERVED TRACKED YAML
git ls-files --error-unmatch config/system.yaml
  config/system.yaml
config/system.yaml:1573-1575
  sensorium:
    enabled: true
    token_budget_warning: 10000
git status --short -- config/system.yaml
  <empty>
git check-ignore -v config/system.yaml
  not ignored

COGNITIVE AGENT / REGISTRY / CALLER
src/probos/cognitive/cognitive_agent.py:20
  imports estimate_tokens from probos.cognitive.attention
src/probos/cognitive/cognitive_agent.py:97
  class SensoriumLayer(StrEnum)
src/probos/cognitive/cognitive_agent.py:105
  class SensoriumPath(StrEnum)
src/probos/cognitive/cognitive_agent.py:139
  class SensoriumEntry (frozen)
src/probos/cognitive/cognitive_agent.py:340
  SENSORIUM_REGISTRY: ClassVar[dict[str, SensoriumEntry]]
src/probos/cognitive/cognitive_agent.py:592
  def __init__(self, **kwargs: Any) -> None
src/probos/cognitive/cognitive_agent.py:806
  async def stop(self) -> None
src/probos/cognitive/cognitive_agent.py:2849
  async def _decide_via_llm(self, observation: dict) -> dict
src/probos/cognitive/cognitive_agent.py:3699
  def _build_chain_for_intent(self, observation: dict)
src/probos/cognitive/cognitive_agent.py:3965
  async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None
src/probos/cognitive/cognitive_agent.py:4070-4080
  _build_cognitive_state -> observation.update -> optional _build_situation_awareness -> observation.update -> one _track_sensorium_budget call
src/probos/cognitive/cognitive_agent.py:4082+
  formatted memories and chain work occur after tracking
src/probos/cognitive/cognitive_agent.py:6581
  def _sensorium_entries_for_path(self, path: SensoriumPath) -> list[tuple[str, SensoriumEntry]]
src/probos/cognitive/cognitive_agent.py:6594
  def _apply_sensorium_result(...)
src/probos/cognitive/cognitive_agent.py:7309
  def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]
src/probos/cognitive/cognitive_agent.py:7348
  def _track_sensorium_budget(self, cognitive_state: dict[str, str], situation: dict[str, str]) -> int
src/probos/cognitive/cognitive_agent.py:7368
  reads token_budget_warning
src/probos/cognitive/cognitive_agent.py:7372
  strict total_chars > threshold
src/probos/cognitive/cognitive_agent.py:7387
  emits existing SENSORIUM_BUDGET_EXCEEDED
src/probos/cognitive/cognitive_agent.py:7400
  returns total_chars
src/probos/cognitive/cognitive_agent.py:7400
  def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]
grep _track_sensorium_budget across src + tests
  one production caller; six direct calls in tests/test_ad666_sensorium.py

LIVE OUTPUT-KEY AMBIGUITY (empirical registry enumeration)
  _cold_start_note: cognitive INTEROCEPTION baseline + situation EXTEROCEPTION situation path
  _confabulation_guard: two cognitive INTEROCEPTION producers
  _no_episodic_memories: two cognitive INTEROCEPTION producers
  _ontology_context: two cognitive INTEROCEPTION producers
  _source_attribution_text: three cognitive INTEROCEPTION producers
  zero dispatched entries with paths and output_key=None at HEAD

TOKEN ESTIMATOR
src/probos/cognitive/attention.py:39
  def estimate_tokens(text: str) -> int
src/probos/cognitive/attention.py:42-49
  ~4 chars/token heuristic; empty=0; no tokenizer dependency

CONFIG
src/probos/config.py:12
  from pydantic import BaseModel, Field, field_validator, model_validator
installed pydantic
  2.12.5
src/probos/config.py:3688
  class SensoriumConfig(BaseModel)
src/probos/config.py:3691-3692
  enabled: bool = True; token_budget_warning: int = 10000
src/probos/config.py:6251
  sensorium: SensoriumConfig = SensoriumConfig()
src/probos/config.py:6338
  def load_config(path: str | Path) -> SystemConfig
src/probos/config.py:6348
  return SystemConfig.model_validate(raw)
AliasChoices empirical check
  legacy only -> canonical value; canonical only -> canonical value; both -> canonical first wins; model_dump uses canonical field
production grep for token_budget_warning
  only cognitive_agent.py reader; no production setter

EVENTS / EMITTER
src/probos/events.py:232
  SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"
src/probos/events.py:530
  class BaseEvent
src/probos/events.py:541
  def to_dict(self) -> dict[str, Any]
src/probos/events.py:920
  class SensoriumBudgetExceededEvent(BaseEvent)
src/probos/events.py:922-928
  existing fields: agent_id, callsign, total_chars, threshold, cognitive_state_chars, situation_chars
src/probos/runtime.py:1350
  def _emit_event(self, event_type: str | EventType, data: dict[str, Any] | None = None) -> None
src/probos/runtime.py:1412
  def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None

TEST SEAMS
tests/test_ad666_sensorium.py:71
  existing TestTrackSensoriumBudget
tests/test_ad666_sensorium.py:137
  existing TestSensoriumConfig
tests/test_events.py:75
  typed-event serialization suite
tests/test_config.py:29
  root config suite; imports ValidationError/load_config
tests/test_ad723_sensorium_dispatch.py:351
  chain-baseline byte-equality snapshot
tests/test_ad1028_context_assembler.py:64/72
  DM/WR prompt byte-identical goldens
tests/test_ad1034_cognitive_spine.py:228
  existing async stop lifecycle test pattern
pyproject.toml:150-166
  pytest timeout/xdist defaults; all handoff gates explicitly override with -n 0

EXACT PRE-BUILD GATE INVENTORY (pytest --collect-only on bef881d8)
  Gate 1 = 81
  Gate 2 = 114
  Gate 3 = 150
  Gate 4 = 90
  Gate 5 = 102
  total = 537
```
