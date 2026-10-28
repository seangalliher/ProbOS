# AD-1270 (#1324) slice 3: working-memory cognition, wired behind a default-off flag -- AD-668's salience gate and AD-670's metabolism reach every crew agent's working memory, a runtime-owned cycle runs and drains them, and off is byte-identical

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-27

**Status:** build-ready. Drafted on `de7ecc7d` (`origin/main` `65f5e02b` + the slice-2 contract + slice 2's M1 `935acb6a`). The orchestrator re-anchors on slice 2's merge. Slice 2 changes no file under `src/` and none of the tests or docs this contract pairs, except `PROGRESS.md` and `DECISIONS.md`, whose anchors follow the standing rule (§8), and `docs/development/dormant-class-baseline.yaml`, which this contract regenerates and never pairs. No new AD or BF number: this is slice 3 of #1324 (`logs/ad1270/answer-ad1270-first-slice.txt:1156-1161`). **Captain:** no condition met (D12). The default-on switch is his, later, with evidence (R1). Overrulable: D7 (no observe-only stage), D9 (validated at startup, not at parse time), D10 (no novelty gate, no agent context).

**Re-anchored by the orchestrator (2026-10-28).** (1) **Base:** `origin/main` `4aa1062fce6c492156ce2f425bf3085abce2fdbc`, the merge of AD-1270 slice 2 (PR #1692); its tree is `7daf4318df9fe9aa2471431cff738069d5c62b7f`. (2) **What slice 2 changed:** `scripts/check_dormant_classes.py`, `tests/test_ad1270_dormant_classes.py`, `docs/development/dormant-class-baseline.yaml` (171 rows at this base: wire 84, staged 25, retire 54, false-positive 8; the five rows this slice makes live leave it, so 166 are predicted), `DECISIONS.md`, `PROGRESS.md`, the AD ledger and its own contract. None of the files this contract pairs changed. (3) **Anchors:** every SEARCH of pairs P1 to P23, U1 and U2 occurs exactly once on this base; the oracle applies them by tool (a dry check against slice 2's head, whose `src/` and tests equal this base's, applied 23 pairs with 0 failures). (4) **Trackers:** U1 anchors on `# ProbOS Progress` and its blank line, which slice 2 left in place (its paragraph follows them); U2 anchors on the `### Explicit delegation models...` heading, which slice 2's entry sits directly before. (5) **File name:** committed as `prompts/ad-1270-working-memory-cognition.md`, the name §8's PROGRESS text already uses. (6) **Line endings:** LF, as the Architect wrote it. (7) **`config/system.yaml`:** the three comment hunks of §7.7 apply to the tracked file in this work tree, which holds none of the Captain's local edits (those live only in his main checkout and stay there).

**Milestones and tiers:**
- **M1, the wiring** (config field and docstrings, `AgentWorkingMemory` hooks, the new driver module, the startup and shutdown seams, the tests, and the regenerated config, profile and dormant baselines). **HIGH**: agent memory behaviour, plus shared contracts (`AgentWorkingMemory`'s public API, the startup/shutdown order, the config surface, and a source-scan test of production source).
- **M2, trackers** (`PROGRESS.md`, `DECISIONS.md`, the regenerated AD ledger). **docs**.

Each milestone is one Builder delegation and one local commit, staged by explicit path, never `git add -A`. `config/system.yaml` may hold the Captain's local edits: stage only this contract's three comment hunks. M1 gets a cross-family review (`gpt-6.1-sol`) against §14 and one mutation campaign (§10). The broad gate is the orchestrator's single run after M2: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-working-memory-cognition --receipt logs/gates/ad1270-working-memory-cognition.receipt.json`.

**Tests:** new `tests/test_ad1270_working_memory_cognition.py`, predicted at 60 cases. Updated, each with an inline reason: `tests/test_bf926_config_readers.py`, `tests/test_ad1270e2b_cognition_models.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1152_agentic_correlation.py`. No test touches a live system or the real data directory. The BF-926-sibling case reads the tracked `config/system.yaml` and writes nothing.

**Line endings:** working copies are CRLF (`core.autocrlf=true`). SEARCH blocks are LF: match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| No production code constructs `SalienceFilter`, `MemoryMetabolism`, `SalienceScore`, `AuditFlag` or `MetabolismReport`; nothing calls `set_metabolism` or passes `salience_filter=` | present | Absence AV1 |
| One `AgentWorkingMemory()` per cognitive agent, no arguments; public `working_memory` property | present | `cognitive/cognitive_agent.py:1364-1365`, `:1703-1706` |
| The salience gate is constructor-only and creates the background stream; TRIAGE runs in all five record paths when metabolism is set | present | `agent_working_memory.py:291,297-299,381-397`; `:417-421,437-441,458-462,479-483,499-503` |
| `run_metabolism_cycle` returns `None` and runs only over the five rings; named buffers dual-write the same entry object, cap 20, have no remove | present | `agent_working_memory.py:572-586`; `:222-264,423,443,464,485,505` |
| Working memory is frozen at shutdown and restored at finalize by replacing `agent._working_memory` with `from_dict()` → `cls()` (no gate, no engine); `from_dict` rebuilds ring and named entries as separate objects | present | `startup/shutdown.py:1946-1965`; `startup/finalize.py:6289-6326`; `agent_working_memory.py:932-1020` |
| The freeze persists entry metadata (`INSERT OR REPLACE` snapshot); the AD-671 pre-dream flush stores counts only; the API returns `to_dict()` | present | `agent_working_memory.py:860-930`; `cognitive/working_memory_store.py:67,85`; `cognitive/dream_wm_bridge.py:39-95`; `routers/agents.py:3900-3913` |
| `metabolism.*` (8 fields) and `salience.*` exist; nothing reads them; `MetabolismConfig` is marked inert; the tracked yaml sets both `enabled: true` | present | `config_models/cognition.py:278-293,333-343`; `config_models/knowledge.py:489-501`; `config.py:4056,4060,4066`; `config/system.yaml:1965-1974,2007-2016,2040-2048`; Absence AV6 |
| BF-926 pins every `metabolism.*` field as inert | present | `tests/test_bf926_config_readers.py:116-150` |
| The runtime has a NoveltyGate; `SalienceFilter` would call it per `agent_id`; `set_agent_context` has no caller | present | `startup/finalize.py:4275-4280`; `cognitive/salience_filter.py:128-143`; Absence AV2 |
| At default weights and threshold with an empty context, a fresh entry scores ≥ 0.575 > 0.3 | present | `cognitive/salience_filter.py:17-23,79-185` (D7) |
| Precedent: a default-off periodic service started from finalize, stopped in shutdown | present | `startup/finalize.py:780-816,5818-5824`; `startup/shutdown.py:1641-1647`; `threads/transcript_reaper.py:31-103` |
| Pinned contracts a new config field moves | present | `tests/test_ad1270e1_config_facade.py:1559-1560`; `tests/test_ad1270e2b_cognition_models.py:202-214,360-393`; `tests/test_ad1152_agentic_correlation.py:215-317`; `docs/development/config-profiles.yaml:12-25,611-623`; `scripts/check_config_profiles.py:12-14`; `tests/test_config_reference_current.py:41-60` |
| The dormant check counts any use from another module, and spreads in-module from live definitions | present | `scripts/check_dormant_classes.py:8-16,170-182` |
| AD intent: background stream for idle review; metabolism's async driver deferred to integration; metabolism operates on named buffers | present | `DECISIONS.md:5523-5542`; `prompts/archive/ad-668-salience-filter.md:21,215`; `docs/research/ambient-awareness-optimal-working-memory.md:480-482,577-589,739` |
| AD-1339 (#1566) needs only that FORGET stays attention management of a transient buffer, and no change to AD-670 | present | #1566 body (lines 22, 55, 129, 135) |

## 1. Problem

AD-668 (salience filter) and AD-670 (DECAY, AUDIT, FORGET, TRIAGE) shipped on 2026-04-27 with tests, and nothing in production constructs either. `metabolism.enabled: true` in the tracked config promises behaviour that never runs (BF-926 marked it inert). The 2026-10-16 audit (`logs/ad1270/dormant-audit-2026-10-16.md:19`) lists both as dormant: "working-memory decay, FORGET and audit never run". AD-1339 assumes AD-670's FORGET exists as attention management.

Wiring them naively breaks in three places:
- A gate injected at construction is lost on every stasis restore (`from_dict` → `cls()`).
- FORGET leaves the forgotten entry in the named buffers, which the AD-1030 bid path, `render_buffers` and the freeze still read.
- Neither section's `enabled` can be the switch, because both are already `true` in the tracked config.

## 2. Solution overview

- **M1.** A new flag, `working_memory.cognition_enabled` (default false), is read once, by `build_working_memory_cognition` in the new `cognitive/working_memory_cognition.py`. Off, it returns `None` and constructs nothing.
  - On, it builds one shared `SalienceFilter` (no novelty gate) and one shared `MemoryMetabolism` from their sections (each section's `enabled` turns its part off), and a `WorkingMemoryCognition` driver.
  - Finalize starts the driver after the AD-573 restore: it attaches both to every crew agent's working memory through a new `AgentWorkingMemory.attach_cognition`.
  - Every `metabolism.cycle_interval_seconds` the driver re-attaches, runs one metabolism cycle per agent, drains each background stream and logs per agent what it forgot, flagged and demoted.
  - Shutdown stops it before the freeze.
  - `run_metabolism_cycle` returns its report, and FORGET also removes the entry from the named buffers, matched by value.
  - A salience scorer that raises admits the entry.
  - The five dormant rows leave the baseline.
- **M2.** Trackers.

## 3. Decisions

- **D1. The flag:** `WorkingMemoryConfig.cognition_enabled: bool = False`. It is read only in `build_working_memory_cognition`. The Captain enables it under `working_memory:` and restarts (R16). Rejected: a new section (more surface, four more pinned counts); a field on `MetabolismConfig` (next to `enabled: true` it reads as a contradiction); `metabolism.enabled` or `salience.enabled` (already `true`).
- **D2. Sub-switches.** `salience.enabled` and `metabolism.enabled` are read only when D1 is on, and each turns its own part off. Both off: nothing is attached (`None`, logged). `metabolism.cycle_interval_seconds` is the driver's period even when metabolism is off (the drain still runs).
- **D3. Construction and injection.** The cognitive-layer builder builds one filter and one engine, shared: neither holds per-agent state (`salience_filter.py:37-63`, `memory_metabolism.py:43-68`). The driver attaches them through `AgentWorkingMemory.attach_cognition`, which reuses `set_metabolism`, at start and on every cycle, from a provider callable that finalize builds over `runtime.registry.all()`, `is_crew_agent` and the public `working_memory` property. No `_private` reach is added, and the cognitive module imports config types only under `TYPE_CHECKING`. Rejected: constructor injection at `cognitive_agent.py:1365` (no config there; lost on every restore); a one-shot AD-672-style loop (misses agents that join later, and misses restored memories unless ordered after the restore).
- **D4. The cycle driver.** A single named task (`ad1270-working-memory-cognition`), held in `WorkingMemoryCognition._task`, with this lifecycle:
  - `start()` attaches at once and is idempotent.
  - The loop sleeps one period, then ticks.
  - A tick is synchronous on the event loop: at most 10 entries per ring, and AD-670 measured a cycle at under 1 ms.
  - A per-agent failure is logged with the agent id and skipped.
  - A raising provider yields an empty cycle.
  - A raising tick is logged and the next tick runs on time.
  - Cancellation propagates out of the loop.
  - `stop()` cancels and awaits the task, and absorbs only the cancellation it caused itself. If its caller is being cancelled, the `CancelledError` propagates (Async Discipline). The `TranscriptReaper` precedent swallows it; this does not.

  Rejected: driving it from the proactive loop (couples metabolism to whether an agent thinks; touches `proactive.py`); from the dream cycle (idle-only, about every 600 s, so busy agents are never metabolised).
- **D5. The background-stream consumer** is the cycle. It drains each stream and counts the entries (`CognitionTickReport.demoted`, plus one INFO line per agent when anything happened). Nothing durable or user-visible results except that log line. AD-670's audit flags are counted the same way and not shown to the agent. Re-promotion after review and showing flags to the agent are deferred (R5, R6).
- **D6. Data integrity.**
  - FORGET and TRIAGE act on in-memory ring and named buffers only.
  - No episode, Ward Room post or store record is deleted, so the destructive-intent standard (`requires_consensus`, an intent that deletes durable state) does not apply.
  - Indirect effects: the AD-573 freeze snapshot (`INSERT OR REPLACE`, a snapshot of transient state) and the AD-671 pre-dream counts hold only the surviving entries, and each kept ring entry carries `_decay_score`, an extra key in free-form metadata that `from_dict` restores as-is. That is not a persisted-schema change (R7, R8).
  - This is consistent with AD-1339's carve-out and with the Captain's decision that agents never delete their own memory: FORGET is automatic decay of a transient view.
- **D7. No observe-only stage.**
  - At the defaults the salience gate demotes nothing. With an empty context and no novelty gate, the lowest fresh score is 0.3·0.5 + 0.25·1 + 0.15·0.5 + 0.2·0.3 + 0.1·0.4 = 0.575, against a threshold of 0.3. `test_at_the_default_threshold_the_gate_demotes_nothing` pins this.
  - FORGET removes ring entries whose decay score is below 0.05 (older than log2(20) ≈ 4.32 half-lives, about 4.3 h at 3600 s), beyond 2 kept per buffer.
  - TRIAGE refuses whitespace-only entries, and entries shorter than 20 characters when a ring is more than 85.7% full.
  - Evidence for default-on comes cheaper from replaying the frozen snapshots offline and from the per-agent log lines.
  - Rejected: an observe-only mode (dry-run paths in five record methods and in `MemoryMetabolism`; roughly doubles the census). Deferred: a per-agent canary allowlist.
- **D8. FORGET is coherent.** An entry FORGET removes from a ring also leaves every named buffer, matched by `(timestamp, content, category, source_pathway)`: the restore rebuilds named buffers as separate copies, so identity fails. Entries FIFO evicted earlier are untouched. Each named buffer keeps its maximum length of 20.
- **D9. Validation at startup, not at parse time.** The builder refuses (`ValueError`) values that would spin the loop, raise on an agent's record path or make a gate refuse every entry:
  - period: non-finite or ≤ 0;
  - half-life: non-finite;
  - triage fullness: outside [0, 1);
  - triage base: outside [0, 1];
  - salience threshold: outside [0, 1];
  - stream size: below 0.

  `MemoryMetabolism` already refuses a half-life ≤ 0, a forget threshold outside [0, 1] and a negative floor. Finalize logs the refusal and leaves cognition off. Rejected: Pydantic bounds, which would fail boot on a value that changes nothing today with the flag off (R15).
- **D10. No novelty gate, no agent context.** Passing the runtime's NoveltyGate would record working-memory content in the per-agent novelty history that the proactive loop and the Ward Room use, keyed `"unknown"` while the context is empty. Feeding department, duty, alert level and trust is a later slice (R2, R3).
- **D11. Every count stays "predicted"** until the orchestrator measures it.
- **D12. Captain conditions: none.** No control is weakened, no gate is added or waived, no compatibility promise or persisted schema changes, nothing is spent, nothing crosses the OSS boundary. Default-on is his (R1).

## 4. Milestones

Write the new test file first and run it on M1's base. Collection must fail with `ModuleNotFoundError: No module named 'probos.cognitive.working_memory_cognition'`, so every case fails and no negative case passes (predicted). Then apply §7.10 and run those four files on the base. Predicted failures:
- `test_ad1270e2b_cognition_models.py`: 2 cases (`test_system_config_dump_is_unchanged_for_the_moved_field[working_memory]`, `test_constructing_with_no_arguments_matches_the_pre_move_dump[WorkingMemoryConfig]`).
- `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface`.
- 3 cases of `test_ad1152_agentic_correlation.py` (`KeyError: 'cognition_enabled'`).
- `test_bf926_config_readers.py` passes, with 8 fewer cases.

If any other test fails, stop and report. Never delete or loosen a test. Run focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the wiring | HIGH | 7.1 `config_models/cognition.py`; 7.2 `config_models/knowledge.py`; 7.3 `cognitive/agent_working_memory.py`; 7.4 new `cognitive/working_memory_cognition.py`; 7.5 `startup/finalize.py`; 7.6 `startup/shutdown.py`; 7.7 `config/system.yaml` (comments only); 7.8 `docs/development/config-profiles.yaml`; 7.9 new test file; 7.10 four tests; 7.11 three generated files | `tests/test_ad1270_working_memory_cognition.py tests/test_ad670_memory_metabolism.py tests/test_ad668_salience_filter.py tests/test_agent_working_memory.py tests/test_bf926_config_readers.py tests/test_ad1270e2b_cognition_models.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_ad1270_dormant_classes.py tests/test_bf927_boot_claims.py tests/test_ad1346_admission_service.py tests/test_ad1343_stop_seam_inventory.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_finalize.py tests/test_ad986d_transcript_retention.py`; then `-P scripts/check_config_facade.py --check`, `-P scripts/check_config_profiles.py --check`, `scripts/gen_config_reference.py --check`, `-P scripts/check_architecture_principles.py --check`, `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M2** trackers | docs | §8; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

**M1 build order:**
1. Write 7.9; run it (collection fails). Apply 7.10; run those files (failures as above).
2. Apply 7.1 to 7.6 and 7.4.
3. Apply 7.7 and 7.8. Measure the census with the instrument (`default_false_flags()` and the armed counts the header names). The predicted header is 450, 226, 224, 85, 141. If any figure differs by anything other than this one flag, stop and report.
4. Regenerate (7.11): `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline`; `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --update-baseline` (it must print `baseline rewritten: docs/development/dormant-class-baseline.yaml`).
5. Check the regenerated diffs:
   - facade: `WorkingMemoryConfig`'s fields and `schema_sha256`; the `schema_sha256` of `MetabolismConfig`, `SalienceConfig` and `SystemConfig`; `surface_counts.field_definitions` 1879 → 1880 and `canonical_dump_leaves` +1. Nothing else.
   - reference: the three docstrings and the new field only.
   - dormant: exactly the five rows `cognitive/memory_metabolism.py::AuditFlag`, `::MemoryMetabolism`, `::MetabolismReport`, `cognitive/salience_filter.py::SalienceFilter`, `::SalienceScore` removed, none added.

   Report each diff's hunk list.
6. Run the focused gate. `check_dormant_classes.py --check` must report `0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant`.
7. Commit by explicit path. Stage `config/system.yaml` by partial hunk (only §7.7's three).

## 5. Consumers of every value this adds or changes

| Value | Consumers | Effect |
|---|---|---|
| `working_memory.cognition_enabled` | `build_working_memory_cognition` only; `config-reference.md`; `config-profiles.yaml` row | new, default off |
| `salience.*`, `metabolism.*` | the builder, only when the flag is on | from inert to read-when-on |
| `AgentWorkingMemory.attach_cognition` | `WorkingMemoryCognition` | new public method |
| `run_metabolism_cycle()` return value | `WorkingMemoryCognition.tick_once`; `tests/test_ad670_memory_metabolism.py:329-346` (ignores it) | `None` → `MetabolismReport \| None`; off still `None` |
| `NamedBuffer.discard` | `run_metabolism_cycle` | new |
| Named-buffer contents after FORGET | `render_buffers` (no production caller), `iter_salience_entries` (`cognitive_agent.py:10412`), `to_dict` (freeze, API, AD-671 flush) | the forgotten entry is gone from them too (on only) |
| `runtime.working_memory_cognition` | `_stop_working_memory_cognition` (shutdown) | new attribute, `None` when off |
| Log lines `AD-1270: working memory of <id>: ...` | the vessel log; the default-on evidence (R1) | new, INFO, on only |

## 6. Tests

| ID | Case | Proves |
|---|---|---|
| T1 | `test_the_flag_is_off_by_default` | default and parse |
| T2 | `test_flag_off_the_builder_constructs_nothing` | off builds no class and lists no crew |
| T3 | `test_each_section_turns_its_own_part_off` ×2; `test_both_sections_off_attaches_nothing` | D2 |
| T4 | `test_the_salience_section_sets_the_threshold_and_the_stream_size`; `test_the_metabolism_section_sets_decay_forget_and_floor`; `test_the_metabolism_section_sets_audit` ×2; `test_the_metabolism_section_sets_triage` ×2 | every section value reaches its engine |
| T5 | `test_invalid_values_are_refused` ×12; `test_the_driver_needs_a_part_and_a_finite_period` ×4 | D9 |
| T6 | `test_attach_cognition_is_idempotent_and_keeps_the_stream`; `test_attach_cognition_with_none_leaves_that_part_as_it_is` | the attach API |
| T7 | `test_forget_leaves_the_named_buffers_too`; `test_discard_matches_by_value_and_keeps_the_rest`; `test_run_metabolism_cycle_returns_its_report_or_none` | D8 |
| T8 | `test_a_salience_scorer_that_raises_admits_the_entry` | fail open on the record path |
| T9 | `test_at_the_default_threshold_the_gate_demotes_nothing` | D7's evidence; no mutation row (it documents a property of AD-668's defaults) |
| T10 | `test_start_attaches_now_and_stop_ends_the_cycle`; `test_start_twice_keeps_one_task`; `test_stop_passes_on_a_cancellation_aimed_at_its_caller`; `test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle` | D4 task ownership |
| T11 | `test_a_tick_attaches_a_memory_that_joined_or_was_replaced`; `test_one_failing_agent_does_not_stop_the_others`; `test_a_provider_that_raises_makes_an_empty_cycle`; `test_the_tick_logs_what_it_did_per_agent` | D3, D4, D5 |
| X1 | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` | **crossing:** AD-573 restore → real finalize helper → real driver → AD-670 → `render_context` and `to_dict`, restored named copies included; non-crew and memory-less agents untouched |
| X2 | `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it` | **crossing:** record path → AD-668 → stream → drained by the cycle |
| X3 | `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged` | **off crossing:** the real helper builds nothing; a restored memory's `to_dict` is byte-identical; no gate, no TRIAGE |
| X4 | `test_an_invalid_value_leaves_cognition_off_at_startup` | D9 at the seam |
| X5 | `test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else` | shutdown seam |
| X6 | `test_shutdown_stops_the_cycle_before_working_memory_is_frozen`; `test_startup_starts_the_cycle_after_the_stasis_restore` | **source scan of production source, a shared contract:** `ast.parse` of the file's bytes, host-independent; call order inside `shutdown` and `finalize_startup` |
| X7 | `test_the_reader_check_reports_the_wired_fields_as_read` ×11 | the BF-926 sibling: `metabolism.*`, `working_memory.cognition_enabled`, `salience.threshold`, `salience.background_max_entries` are neither inert nor unread |

Predicted: 60 cases in the new file. On the base every case fails at collection (no negative case passes there). The orchestrator measures the count and the focused-list totals.

## 7. The contract

### 7.1 `src/probos/config_models/cognition.py` (M1)

**Pair P1 (`src/probos/config_models/cognition.py`).** SEARCH:
```
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration. BF-926 (#1656): only stale_threshold_hours is read; AgentWorkingMemory uses its own defaults for everything else."""
```
REPLACE:
```
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration. BF-926 (#1656): only stale_threshold_hours and cognition_enabled (AD-1270, #1324) are read; AgentWorkingMemory uses its own defaults for everything else."""
```

**Pair P2 (`src/probos/config_models/cognition.py`).** SEARCH:
```
    engagement_budget: int = Field(default=800, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")


class MemoryBudgetConfig(BaseModel):
```
REPLACE:
```
    engagement_budget: int = Field(default=800, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    cognition_enabled: bool = Field(default=False, description="AD-1270 (#1324): attach AD-668 salience filtering and AD-670 metabolism to every crew agent's working memory and run their cycle every metabolism.cycle_interval_seconds. Off: nothing is constructed. Read once at startup.")


class MemoryBudgetConfig(BaseModel):
```

**Pair P3 (`src/probos/config_models/cognition.py`).** SEARCH:
```
class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management. Inert: no production code reads this section to act on it (BF-926, #1656): nothing constructs MemoryMetabolism, so enabled and every threshold change nothing (#1324)."""
```
REPLACE:
```
class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management. Read only when working_memory.cognition_enabled is on (AD-1270, #1324): enabled then turns metabolism off on its own, cycle_interval_seconds sets the cycle's period, and the rest configure MemoryMetabolism."""
```

### 7.2 `src/probos/config_models/knowledge.py` (M1)

**Pair P4 (`src/probos/config_models/knowledge.py`).** SEARCH:
```
class SalienceConfig(BaseModel):
    """AD-668: Salience filter for working memory promotion."""
```
REPLACE:
```
class SalienceConfig(BaseModel):
    """AD-668: Salience filter for working memory promotion. Read only when working_memory.cognition_enabled is on (AD-1270, #1324): enabled then turns the filter off on its own; no novelty gate is passed."""
```

### 7.3 `src/probos/cognitive/agent_working_memory.py` (M1)

**Pair P5 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
if TYPE_CHECKING:
    from probos.cognitive.memory_metabolism import MemoryMetabolism
    from probos.config import PinnedKnowledgeConfig
```
REPLACE:
```
if TYPE_CHECKING:
    from probos.cognitive.memory_metabolism import MemoryMetabolism, MetabolismReport
    from probos.config import PinnedKnowledgeConfig
```

**Pair P6 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
    def token_estimate(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class PinnedFact:
```
REPLACE:
```
    def token_estimate(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN


def _entry_key(entry: WorkingMemoryEntry) -> tuple[float, str, str, str]:
    """AD-1270 (#1324): what makes two entries the same record (FORGET's named-buffer match)."""
    return (entry.timestamp, entry.content, entry.category, entry.source_pathway)


@dataclass(frozen=True)
class PinnedFact:
```

**Pair P7 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
    @property
    def entries(self) -> list[WorkingMemoryEntry]:
        """Read-only snapshot of current entries."""
        return list(self._entries)
```
REPLACE:
```
    @property
    def entries(self) -> list[WorkingMemoryEntry]:
        """Read-only snapshot of current entries."""
        return list(self._entries)

    def discard(self, entries: list[WorkingMemoryEntry]) -> int:
        """AD-1270 (#1324): remove the entries equal to these by ``_entry_key``; return how many.

        Matched by value, not identity: the AD-573 restore rebuilds the named buffers from
        their own copies, so a restored ring entry and its named-buffer copy are different
        objects. The buffer keeps its maximum length.
        """
        keys = {_entry_key(entry) for entry in entries}
        kept = [entry for entry in self._entries if _entry_key(entry) not in keys]
        removed = len(self._entries) - len(kept)
        if removed:
            self._entries.clear()
            self._entries.extend(kept)
        return removed
```

**Pair P8 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
        if self._salience_filter is None:
            return True
        scored = self._salience_filter.score(entry, self._agent_context)
```
REPLACE:
```
        if self._salience_filter is None:
            return True
        try:
            scored = self._salience_filter.score(entry, self._agent_context)
        except Exception:
            logger.warning(
                "AD-1270: salience scoring failed; entry admitted (category=%s)",
                entry.category,
                exc_info=True,
            )
            return True  # AD-1270 (#1324): fail open; a scorer fault must not cost the agent the entry
```

**Pair P9 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
    def set_metabolism(self, metabolism: MemoryMetabolism) -> None:
        """AD-670: Attach a metabolism engine for active lifecycle management."""
        self._metabolism = metabolism
```
REPLACE:
```
    def set_metabolism(self, metabolism: MemoryMetabolism) -> None:
        """AD-670: Attach a metabolism engine for active lifecycle management."""
        self._metabolism = metabolism

    def attach_cognition(
        self,
        *,
        salience_filter: SalienceFilter | None,
        metabolism: MemoryMetabolism | None,
        background_max_entries: int = 50,
    ) -> None:
        """AD-1270 (#1324): attach the AD-668 salience filter and the AD-670 metabolism engine.

        Idempotent: attaching again changes nothing, and an existing background stream
        keeps its entries. ``None`` leaves that part as it is.
        """
        if salience_filter is not None:
            self._salience_filter = salience_filter  # AD-1270: the gate now runs on every record_*
            if self._background_stream is None:
                self._background_stream = BackgroundStream(max_entries=background_max_entries)
        if metabolism is not None:
            self.set_metabolism(metabolism)
```

**Pair P10 (`src/probos/cognitive/agent_working_memory.py`).** SEARCH:
```
    def run_metabolism_cycle(self) -> None:
        """AD-670: Run one metabolism cycle if metabolism is attached."""
        if self._metabolism is None:
            return
        self._metabolism.run_cycle(self.get_buffers())
```
REPLACE:
```
    def run_metabolism_cycle(self) -> MetabolismReport | None:
        """AD-670: Run one metabolism cycle if metabolism is attached.

        AD-1270 (#1324): returns the cycle's report (``None`` when detached), and an entry
        FORGET removes from a ring buffer leaves the named buffers too, so neither
        ``render_context``, ``render_buffers`` nor the AD-573 freeze keeps it.
        """
        if self._metabolism is None:
            return None
        buffers = self.get_buffers()
        before = [entry for buffer in buffers.values() for entry in buffer]
        report = self._metabolism.run_cycle(buffers)
        if report.forgotten_count:
            kept = {id(entry) for buffer in buffers.values() for entry in buffer}
            forgotten = [entry for entry in before if id(entry) not in kept]
            for named in self._named_buffers.values():
                named.discard(forgotten)
        return report
```

### 7.4 New file: `src/probos/cognitive/working_memory_cognition.py` (M1)

```python
"""AD-1270 (#1324): AD-668 salience filtering and AD-670 metabolism, wired to crew working memory.

Default off. ``working_memory.cognition_enabled`` is read in one place,
:func:`build_working_memory_cognition`. Off, it returns ``None``: nothing here is constructed
and every agent's working memory behaves as it did before.

On, :class:`WorkingMemoryCognition` attaches one shared :class:`SalienceFilter` and one shared
:class:`MemoryMetabolism` (neither holds per-agent state) to each crew agent's working memory,
and every ``metabolism.cycle_interval_seconds`` runs one metabolism cycle per agent and drains
its background stream. Each cycle attaches again, so a working memory the AD-573 stasis restore
replaced, or an agent that joined later, is covered from its next cycle.

What it touches: the in-memory ring and named buffers only. FORGET and TRIAGE delete no
episode, Ward Room post or store record. The AD-573 freeze and the AD-671 pre-dream summary
see the entries that remain, and each kept ring entry carries ``_decay_score`` in its metadata.

The background-stream consumer counts what the salience gate demoted and discards it; it
promotes nothing back. Audit flags are counted and logged, not shown to the agent.

Log-and-degrade: a cycle that raises for one agent is logged, and the other agents and the
loop carry on; that agent's working memory is left as it is.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.cognitive.memory_metabolism import MemoryMetabolism
from probos.cognitive.salience_filter import SalienceFilter

if TYPE_CHECKING:
    from probos.cognitive.agent_working_memory import AgentWorkingMemory
    from probos.config import MetabolismConfig, SalienceConfig, WorkingMemoryConfig

logger = logging.getLogger(__name__)

#: ``(agent id, working memory)`` for every crew agent; called again on every cycle.
WorkingMemories = Callable[[], Iterable[tuple[str, "AgentWorkingMemory"]]]


@dataclass(frozen=True)
class CognitionTickReport:
    """What one cycle did, summed over the crew."""

    agents: int
    forgotten: int
    audit_flags: int
    demoted: int
    failed: int


class WorkingMemoryCognition:
    """Attaches AD-668 and AD-670 to crew working memory and runs their cycle; one per runtime."""

    def __init__(
        self,
        *,
        working_memories: WorkingMemories,
        salience_filter: SalienceFilter | None,
        metabolism: MemoryMetabolism | None,
        background_max_entries: int,
        interval_seconds: float,
    ) -> None:
        if salience_filter is None and metabolism is None:
            raise ValueError("working-memory cognition needs a salience filter or a metabolism engine")
        if not (math.isfinite(interval_seconds) and interval_seconds > 0):
            raise ValueError("metabolism.cycle_interval_seconds must be finite and above 0")
        if background_max_entries < 0:
            raise ValueError("salience.background_max_entries must not be negative")
        self._working_memories = working_memories
        self._salience_filter = salience_filter
        self._metabolism = metabolism
        self._background_max_entries = background_max_entries
        self._interval = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """True while the cycle task exists and has not finished."""
        return self._task is not None and not self._task.done()

    def attach_all(self) -> int:
        """Attach the filter and the engine to every crew working memory; return how many took it."""
        attached = 0
        for agent_id, memory in self._members():
            try:
                self._attach(memory)
            except Exception:
                logger.warning(
                    "AD-1270: could not attach working-memory cognition for %s", agent_id, exc_info=True
                )
            else:
                attached += 1
        return attached

    def tick_once(self) -> CognitionTickReport:
        """One cycle per crew agent: attach, run metabolism, drain the background stream."""
        members = self._members()
        forgotten = audit_flags = demoted = failed = 0
        for agent_id, memory in members:
            try:
                self._attach(memory)  # every cycle: a replaced or joining working memory is covered
                report = memory.run_metabolism_cycle()
                stream = memory.get_background_stream()
                drained = len(stream.drain()) if stream is not None else 0
            except Exception:
                failed += 1
                logger.warning(
                    "AD-1270: working-memory cycle failed for %s; its working memory is left as it is",
                    agent_id,
                    exc_info=True,
                )
                continue
            agent_forgotten = report.forgotten_count if report is not None else 0
            agent_flags = len(report.audit_flags) if report is not None else 0
            if agent_forgotten or agent_flags or drained:
                logger.info(
                    "AD-1270: working memory of %s: forgotten=%d audit_flags=%d demoted=%d",
                    agent_id,
                    agent_forgotten,
                    agent_flags,
                    drained,
                )
            forgotten += agent_forgotten
            audit_flags += agent_flags
            demoted += drained
        return CognitionTickReport(
            agents=len(members),
            forgotten=forgotten,
            audit_flags=audit_flags,
            demoted=demoted,
            failed=failed,
        )

    async def start(self) -> None:
        """Attach now, then run a cycle after every interval. Idempotent."""
        if self.running:
            return
        self.attach_all()
        self._task = asyncio.create_task(self._loop(), name="ad1270-working-memory-cognition")

    async def stop(self) -> None:
        """Cancel the cycle task and wait for it to end. Idempotent.

        Only the cancellation it caused is absorbed: if the caller is itself being cancelled,
        the ``CancelledError`` propagates (Async Discipline).
        """
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise

    def _members(self) -> list[tuple[str, AgentWorkingMemory]]:
        try:
            return list(self._working_memories())
        except Exception:
            logger.warning(
                "AD-1270: could not list crew working memory; this cycle does nothing", exc_info=True
            )
            return []

    def _attach(self, memory: AgentWorkingMemory) -> None:
        memory.attach_cognition(
            salience_filter=self._salience_filter,
            metabolism=self._metabolism,
            background_max_entries=self._background_max_entries,
        )

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self.tick_once()
            except Exception:
                logger.warning("AD-1270: working-memory cycle raised; the next one runs on time", exc_info=True)


def build_working_memory_cognition(
    *,
    working_memory: WorkingMemoryConfig,
    salience: SalienceConfig,
    metabolism: MetabolismConfig,
    working_memories: WorkingMemories,
) -> WorkingMemoryCognition | None:
    """Read ``working_memory.cognition_enabled``; this is the one place it is read.

    Off: returns ``None`` and constructs nothing. On: builds the shared filter and engine from
    their own sections, where ``salience.enabled`` and ``metabolism.enabled`` each turn their part
    off, and the driver, whose period is ``metabolism.cycle_interval_seconds``. Raises
    ``ValueError`` for a value that would spin the cycle, raise on an agent's record path or make
    a gate refuse every entry; the caller logs it and leaves cognition off.
    """
    if not working_memory.cognition_enabled:
        return None
    salience_filter = _build_salience_filter(salience) if salience.enabled else None
    engine = _build_metabolism(metabolism) if metabolism.enabled else None
    if salience_filter is None and engine is None:
        logger.info(
            "AD-1270: working_memory.cognition_enabled is on, but salience and metabolism are both "
            "disabled; nothing is attached"
        )
        return None
    return WorkingMemoryCognition(
        working_memories=working_memories,
        salience_filter=salience_filter,
        metabolism=engine,
        background_max_entries=salience.background_max_entries,
        interval_seconds=metabolism.cycle_interval_seconds,
    )


def _build_salience_filter(config: SalienceConfig) -> SalienceFilter:
    if not (0.0 <= config.threshold <= 1.0):
        raise ValueError("salience.threshold must be between 0 and 1")
    return SalienceFilter.from_config(config)


def _build_metabolism(config: MetabolismConfig) -> MemoryMetabolism:
    if not math.isfinite(config.decay_half_life_seconds):
        raise ValueError("metabolism.decay_half_life_seconds must be finite")
    if not (0.0 <= config.triage_fullness_threshold < 1.0):
        raise ValueError("metabolism.triage_fullness_threshold must be at least 0 and below 1")
    if not (0.0 <= config.triage_base_score <= 1.0):
        raise ValueError("metabolism.triage_base_score must be between 0 and 1")
    return MemoryMetabolism(
        decay_half_life_seconds=config.decay_half_life_seconds,
        forget_threshold=config.forget_threshold,
        min_entries_per_buffer=config.min_entries_per_buffer,
        audit_enabled=config.audit_enabled,
        triage_fullness_threshold=config.triage_fullness_threshold,
        triage_base_score=config.triage_base_score,
    )
```

### 7.5 `src/probos/startup/finalize.py` (M1)

**Pair P11 (`src/probos/startup/finalize.py`).** SEARCH:
```
    except Exception:
        logger.warning(
            "AD-986d: TranscriptReaper start failed; "
            "transcripts will not be reaped this run",
            exc_info=True,
        )


def _wire_curriculum_registry(*, runtime: Any, config: "SystemConfig") -> bool:
```
REPLACE:
```
    except Exception:
        logger.warning(
            "AD-986d: TranscriptReaper start failed; "
            "transcripts will not be reaped this run",
            exc_info=True,
        )


async def _start_working_memory_cognition(*, runtime: Any, config: "SystemConfig") -> None:
    """AD-1270 (#1324): attach AD-668/AD-670 to crew working memory and start their cycle.

    Default off: with ``working_memory.cognition_enabled`` false the builder returns ``None``,
    nothing is constructed and working memory behaves as before. Called after the AD-573
    restore, which replaces each restored agent's working memory. Log-and-degrade: an invalid
    value leaves cognition off and every working memory as it is.
    """
    runtime.working_memory_cognition = None
    from probos.cognitive.working_memory_cognition import build_working_memory_cognition

    def _crew_working_memories() -> list[tuple[str, Any]]:
        ontology = getattr(runtime, "ontology", None)
        members: list[tuple[str, Any]] = []
        for agent in runtime.registry.all():
            if not is_crew_agent(agent, ontology):
                continue
            memory = getattr(agent, "working_memory", None)
            if memory is not None:
                members.append((agent.id, memory))
        return members

    try:
        cognition = build_working_memory_cognition(
            working_memory=config.working_memory,
            salience=config.salience,
            metabolism=config.metabolism,
            working_memories=_crew_working_memories,
        )
    except ValueError:  # AD-1270: an invalid metabolism or salience value
        logger.warning(
            "AD-1270: working-memory cognition config is invalid; it stays off this run",
            exc_info=True,
        )
        return
    if cognition is None:
        return
    await cognition.start()
    runtime.working_memory_cognition = cognition
    logger.info(
        "AD-1270: working-memory cognition started for crew working memory (cycle every %.0fs)",
        config.metabolism.cycle_interval_seconds,
    )


def _wire_curriculum_registry(*, runtime: Any, config: "SystemConfig") -> bool:
```

**Pair P12 (`src/probos/startup/finalize.py`).** SEARCH:
```
        except Exception:
            logger.debug("AD-573: Working memory restore failed", exc_info=True)

    # BF-235: Always clear identity caches on stasis resume, regardless of
```
REPLACE:
```
        except Exception:
            logger.debug("AD-573: Working memory restore failed", exc_info=True)

    # AD-1270 (#1324): AD-668/AD-670 for crew working memory, default off. After the
    # AD-573 restore above, which replaces each restored agent's working memory.
    try:
        await _start_working_memory_cognition(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-1270: _start_working_memory_cognition failed", exc_info=True)

    # BF-235: Always clear identity caches on stasis resume, regardless of
```

### 7.6 `src/probos/startup/shutdown.py` (M1)

**Pair P13 (`src/probos/startup/shutdown.py`).** SEARCH:
```
    try:
        if callable(close):
            await close()
    finally:
        runtime.crew_session_delivery_service = None


def _close_voice_synthesis(runtime: Any) -> None:
```
REPLACE:
```
    try:
        if callable(close):
            await close()
    finally:
        runtime.crew_session_delivery_service = None


async def _stop_working_memory_cognition(runtime: Any) -> None:
    """AD-1270 (#1324): stop the working-memory cognition cycle. Raises no ``Exception``.

    Called before working memory is frozen, so no cycle runs during or after the freeze. A
    runtime that never started it (the flag is off, or startup refused a value) has nothing
    to stop.
    """
    from probos.cognitive.working_memory_cognition import WorkingMemoryCognition

    cognition = getattr(runtime, "working_memory_cognition", None)
    if not isinstance(cognition, WorkingMemoryCognition):
        return
    try:
        await cognition.stop()
    except Exception:
        logger.warning("AD-1270: working-memory cognition stop failed", exc_info=True)
    runtime.working_memory_cognition = None


def _close_voice_synthesis(runtime: Any) -> None:
```

**Pair P14 (`src/probos/startup/shutdown.py`).** SEARCH:
```
    # AD-986d: Stop transcript retention reaper.
    if hasattr(runtime, 'transcript_reaper') and runtime.transcript_reaper is not None:
        try:
            await runtime.transcript_reaper.stop()
        except Exception:
            logger.warning("AD-986d: transcript_reaper.stop() failed", exc_info=True)
        runtime.transcript_reaper = None
```
REPLACE:
```
    # AD-986d: Stop transcript retention reaper.
    if hasattr(runtime, 'transcript_reaper') and runtime.transcript_reaper is not None:
        try:
            await runtime.transcript_reaper.stop()
        except Exception:
            logger.warning("AD-986d: transcript_reaper.stop() failed", exc_info=True)
        runtime.transcript_reaper = None

    # AD-1270 (#1324): stop the working-memory cognition cycle before working memory is frozen below.
    await _stop_working_memory_cognition(runtime)
```

### 7.7 `config/system.yaml` (M1; comments only, staged by partial hunk)

**Pair P15 (`config/system.yaml`).** SEARCH:
```
# BF-926 (#1656): only stale_threshold_hours is read; the other keys change nothing.
working_memory:
```
REPLACE:
```
# BF-926 (#1656): only stale_threshold_hours and cognition_enabled are read; the other keys change nothing.
# AD-1270 (#1324): cognition_enabled (default false, absent here) turns on AD-668 salience and AD-670 metabolism.
working_memory:
```

**Pair P16 (`config/system.yaml`).** SEARCH:
```
# BF-926 (#1656): inert. No production code acts on this section; enabled: true turns nothing on (#1324).
metabolism:
```
REPLACE:
```
# AD-1270 (#1324): read only when working_memory.cognition_enabled is on (default off); enabled then keeps
# metabolism on within it, and cycle_interval_seconds sets the cycle's period.
metabolism:
```

**Pair P17 (`config/system.yaml`).** SEARCH:
```
  contradiction_check_enabled: true
salience:
```
REPLACE:
```
  contradiction_check_enabled: true
# AD-1270 (#1324): read only when working_memory.cognition_enabled is on (default off).
salience:
```

### 7.8 `docs/development/config-profiles.yaml` (M1)

**Pair P18 (`docs/development/config-profiles.yaml`).** SEARCH:
```
  measured_at_commit: AD-1341 S5 (issue 1569) M3 on the BF-939 base, every count re-measured with
    this instrument (S5 adds archive_promotion.enabled, a default-False boolean no tracked config
    arms; the BF-924 merge plus the BF-926/BF-927 candidate measured 448, 224, 224, 85 and 139)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 449
  default_false: 225
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 140
```
REPLACE:
```
  measured_at_commit: AD-1270 (issue 1324) slice 3 M1 on the slice-2 merge, every count re-measured with
    this instrument (slice 3 adds working_memory.cognition_enabled, a default-False boolean no tracked
    config arms; AD-1341 S5 on the BF-939 base measured 449, 225, 224, 85 and 140)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 450
  default_false: 226
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 141
```

**Pair P19 (`docs/development/config-profiles.yaml`).** SEARCH:
```
  external_dependency: null
  requires:
  - archive.enabled
  conflicts_with: []
ci_divergences:
```
REPLACE:
```
  external_dependency: null
  requires:
  - archive.enabled
  conflicts_with: []
- path: working_memory.cognition_enabled
  kind: product-feature
  profiles: []
  evidence_to_promote: tests/test_ad1270_working_memory_cognition.py::test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere
    -- armed, the real startup helper attaches AD-668 and AD-670 to a restored crew working memory
    and the cycle forgets its stale entries from every view;
    tests/test_ad1270_working_memory_cognition.py::test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged
    -- OFF constructs nothing and leaves working memory byte-identical. Arming it changes what every
    crew agent keeps in working memory, so no profile arms it until the Captain enables it (AD-1270 slice 3).
  external_dependency: null
  requires: []
  conflicts_with: []
ci_divergences:
```

### 7.9 New file: `tests/test_ad1270_working_memory_cognition.py` (M1)

```python
"""AD-1270 (#1324) slice 3: AD-668 salience and AD-670 metabolism, wired to crew working memory.

Default off: with ``working_memory.cognition_enabled`` false nothing is constructed and working
memory behaves as before (``test_flag_off_*``). On, AD-573's restore, the real startup helper,
the real driver and the real engines meet across the startup seam (``test_flag_on_*``), and what
the agent is shown (``render_context``) and what shutdown freezes (``to_dict``) change as AD-670
and AD-668 say. Two cases scan production source with ``ast`` (a shared contract: the cycle's
order against the AD-573 restore and freeze); they parse bytes, so they read the same on every
host.

No test touches a live system or the real data directory. The BF-926 sibling reads the tracked
``config/system.yaml`` and changes nothing.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import importlib.util
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from probos.cognitive import working_memory_cognition as wmc
from probos.cognitive.agent_working_memory import AgentWorkingMemory, NamedBuffer, WorkingMemoryEntry
from probos.cognitive.memory_metabolism import MemoryMetabolism, MetabolismReport
from probos.cognitive.salience_filter import SalienceFilter
from probos.cognitive.working_memory_cognition import (
    CognitionTickReport,
    WorkingMemoryCognition,
    build_working_memory_cognition,
)
from probos.config import MetabolismConfig, SalienceConfig, SystemConfig, WorkingMemoryConfig
from probos.startup import finalize as finalize_module
from probos.startup import shutdown as shutdown_module

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "probos"
_HOUR = 3600.0
_TASK_NAME = "ad1270-working-memory-cognition"
_STALE = {
    "checked the warp core telemetry": 12 * _HOUR,
    "filed the morning duty report": 11 * _HOUR,
    "reviewed the sensor sweep logs": 10 * _HOUR,
}
_FRESH = "answered the Captain about the plan"
_KEPT = ["reviewed the sensor sweep logs", _FRESH]


# --- helpers ------------------------------------------------------------------------------


def _on(**sections: dict[str, Any]) -> SystemConfig:
    """A config with the flag on and these sections overridden."""
    return SystemConfig.model_validate({"working_memory": {"cognition_enabled": True}, **sections})


def _build(
    config: SystemConfig, members: list[tuple[str, AgentWorkingMemory]]
) -> WorkingMemoryCognition | None:
    return build_working_memory_cognition(
        working_memory=config.working_memory,
        salience=config.salience,
        metabolism=config.metabolism,
        working_memories=lambda: list(members),
    )


def _backdate(memory: AgentWorkingMemory, buffer: str, ages: dict[str, float]) -> None:
    """Age ring entries by content; a live-recorded named-buffer entry is the same object."""
    now = time.time()
    for entry in memory.get_buffers()[buffer]:
        if entry.content in ages:
            entry.timestamp = now - ages[entry.content]


def _frozen_state(now: float) -> dict[str, Any]:
    """A working memory as AD-573 freezes it: three stale actions and a fresh one, in both views."""
    ages = {**_STALE, _FRESH: 60.0}
    actions = [
        {
            "content": content, "category": "action", "source_pathway": "proactive",
            "timestamp": now - age, "metadata": {}, "knowledge_source": "unknown",
        }
        for content, age in ages.items()
    ]
    return {
        "recent_actions": actions,
        "named_buffers": {
            "duty": {"name": "duty", "token_budget": 600, "entries": [dict(action) for action in actions]},
        },
    }


def _agent(agent_id: str, agent_type: str, memory: AgentWorkingMemory | None) -> SimpleNamespace:
    return SimpleNamespace(id=agent_id, agent_type=agent_type, working_memory=memory)


def _runtime(*agents: SimpleNamespace) -> SimpleNamespace:
    """What the startup helper reads: the registry, and the ontology (None selects the legacy crew set)."""
    return SimpleNamespace(registry=SimpleNamespace(all=lambda: list(agents)), ontology=None)


def _snapshot(memory: AgentWorkingMemory) -> str:
    return json.dumps(memory.to_dict(), sort_keys=True)


class _Refuse:
    """Stands in for a class that must not be built with the flag off."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("constructed with working_memory.cognition_enabled off")

    @classmethod
    def from_config(cls, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("constructed with working_memory.cognition_enabled off")


def _calls_in(path: Path, function: str) -> list[tuple[int, str]]:
    """``(line, callee name)`` for every call inside the top-level function ``function``."""
    tree = ast.parse(path.read_bytes(), filename=path.as_posix())
    target = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    )
    calls: list[tuple[int, str]] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.append((node.lineno, node.func.attr))
            elif isinstance(node.func, ast.Name):
                calls.append((node.lineno, node.func.id))
    return sorted(calls)


def _load_reader_check() -> Any:
    path = _REPO_ROOT / "scripts" / "check_config_readers.py"
    spec = importlib.util.spec_from_file_location("_ad1270_wmc_config_readers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=1)
def _reader_report() -> Any:
    """Built once per process from the real model, source and tracked yaml; tests only read it."""
    checker = _load_reader_check()
    document = yaml.safe_load(checker.DEFAULT_YAML.read_text(encoding="utf-8"))
    return checker.build_report(SystemConfig, checker.DEFAULT_SOURCE, document)


# --- T1 to T5: the flag, the sections and the refusals ------------------------------------


def test_the_flag_is_off_by_default() -> None:
    assert WorkingMemoryConfig().cognition_enabled is False
    assert SystemConfig().working_memory.cognition_enabled is False
    assert WorkingMemoryConfig.model_validate({"cognition_enabled": True}).cognition_enabled is True


def test_flag_off_the_builder_constructs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SalienceFilter", "MemoryMetabolism", "WorkingMemoryCognition"):
        monkeypatch.setattr(wmc, name, _Refuse)

    def never() -> list[tuple[str, AgentWorkingMemory]]:
        raise AssertionError("crew listed with the flag off")

    assert build_working_memory_cognition(
        working_memory=WorkingMemoryConfig(), salience=SalienceConfig(),
        metabolism=MetabolismConfig(), working_memories=never,
    ) is None


@pytest.mark.parametrize("part", ["salience-off", "metabolism-off"])
def test_each_section_turns_its_own_part_off(part: str) -> None:
    memory = AgentWorkingMemory()
    section = {"salience": {"enabled": False}} if part == "salience-off" else {"metabolism": {"enabled": False}}
    cognition = _build(_on(**section), [("crew-1", memory)])

    assert cognition is not None and cognition.attach_all() == 1
    if part == "salience-off":
        assert memory.get_background_stream() is None
        assert isinstance(memory.run_metabolism_cycle(), MetabolismReport)
    else:
        assert memory.get_background_stream() is not None
        assert memory.run_metabolism_cycle() is None


def test_both_sections_off_attaches_nothing() -> None:
    config = _on(salience={"enabled": False}, metabolism={"enabled": False})

    assert _build(config, []) is None


def test_the_salience_section_sets_the_threshold_and_the_stream_size() -> None:
    memory = AgentWorkingMemory()
    config = _on(salience={"threshold": 0.99, "background_max_entries": 2}, metabolism={"enabled": False})
    cognition = _build(config, [("crew-1", memory)])
    assert cognition is not None and cognition.attach_all() == 1

    for number in range(3):
        memory.record_observation(f"routine reading number {number}", source="proactive")

    assert len(memory.get_buffers()["observations"]) == 0
    assert len(memory.get_background_stream()) == 2


def test_the_metabolism_section_sets_decay_forget_and_floor() -> None:
    """Half-life 60 s, forget below 0.5, keep none: a 90 s entry scores 2**-1.5 = 0.354 and goes."""
    memory = AgentWorkingMemory()
    config = _on(
        salience={"enabled": False},
        metabolism={"decay_half_life_seconds": 60.0, "forget_threshold": 0.5, "min_entries_per_buffer": 0},
    )
    cognition = _build(config, [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    memory.record_action("ran the ninety second diagnostic", source="proactive")
    _backdate(memory, "actions", {"ran the ninety second diagnostic": 90.0})

    report = memory.run_metabolism_cycle()

    assert report is not None and report.forgotten_count == 1
    assert len(memory.get_buffers()["actions"]) == 0


@pytest.mark.parametrize(("audit", "flags"), [(True, 1), (False, 0)], ids=["on", "off"])
def test_the_metabolism_section_sets_audit(audit: bool, flags: int) -> None:
    memory = AgentWorkingMemory()
    cognition = _build(_on(salience={"enabled": False}, metabolism={"audit_enabled": audit}), [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    memory.record_observation("the reactor coolant pump is running", source="proactive")
    memory.record_observation("the reactor coolant pump is not running", source="proactive")

    assert cognition.tick_once().audit_flags == flags


@pytest.mark.parametrize(
    ("section", "prior"),
    [({"triage_base_score": 0.6}, 0), ({"triage_fullness_threshold": 0.0}, 5)],
    ids=["base", "fullness"],
)
def test_the_metabolism_section_sets_triage(section: dict[str, float], prior: int) -> None:
    """A short entry scores 0.5. Base 0.6 refuses it in an empty ring; fullness 0.0 refuses it at 5 of 10."""
    memory = AgentWorkingMemory()
    cognition = _build(_on(salience={"enabled": False}, metabolism=section), [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    for number in range(prior):
        memory.record_action(f"a long enough action number {number}", source="proactive")

    memory.record_action("short note", source="proactive")

    assert "short note" not in [entry.content for entry in memory.get_buffers()["actions"]]


_INVALID: dict[str, dict[str, dict[str, float]]] = {
    "interval-zero": {"metabolism": {"cycle_interval_seconds": 0.0}},
    "interval-nan": {"metabolism": {"cycle_interval_seconds": float("nan")}},
    "interval-inf": {"metabolism": {"cycle_interval_seconds": float("inf")}},
    "half-life-nan": {"metabolism": {"decay_half_life_seconds": float("nan")}},
    "half-life-inf": {"metabolism": {"decay_half_life_seconds": float("inf")}},
    "fullness-one": {"metabolism": {"triage_fullness_threshold": 1.0}},
    "fullness-negative": {"metabolism": {"triage_fullness_threshold": -0.1}},
    "base-nan": {"metabolism": {"triage_base_score": float("nan")}},
    "base-above-one": {"metabolism": {"triage_base_score": 1.5}},
    "threshold-nan": {"salience": {"threshold": float("nan")}},
    "threshold-above-one": {"salience": {"threshold": 1.5}},
    "background-negative": {"salience": {"background_max_entries": -1}},
}


@pytest.mark.parametrize("case", sorted(_INVALID))
def test_invalid_values_are_refused(case: str) -> None:
    config = _on(**_INVALID[case])  # parsed outside the raises block: pydantic's error is a ValueError too

    with pytest.raises(ValueError):
        _build(config, [])


_DRIVER_INVALID: dict[str, dict[str, Any]] = {
    "nothing": {"salience_filter": None, "metabolism": None},
    "zero": {"interval_seconds": 0.0},
    "inf": {"interval_seconds": float("inf")},
    "negative-stream": {"background_max_entries": -1},
}


@pytest.mark.parametrize("case", sorted(_DRIVER_INVALID))
def test_the_driver_needs_a_part_and_a_finite_period(case: str) -> None:
    arguments: dict[str, Any] = {
        "working_memories": lambda: [], "salience_filter": SalienceFilter(), "metabolism": MemoryMetabolism(),
        "background_max_entries": 50, "interval_seconds": 300.0, **_DRIVER_INVALID[case],
    }

    with pytest.raises(ValueError):
        WorkingMemoryCognition(**arguments)


# --- T6 to T9: AgentWorkingMemory ---------------------------------------------------------


def test_attach_cognition_is_idempotent_and_keeps_the_stream() -> None:
    memory = AgentWorkingMemory()
    gate = SalienceFilter(threshold=0.99)
    memory.attach_cognition(salience_filter=gate, metabolism=None)
    memory.record_observation("routine reading kept in the stream", source="proactive")
    stream = memory.get_background_stream()

    memory.attach_cognition(salience_filter=gate, metabolism=None)

    assert memory.get_background_stream() is stream
    assert len(stream) == 1


def test_attach_cognition_with_none_leaves_that_part_as_it_is() -> None:
    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=None, metabolism=MemoryMetabolism())
    assert memory.get_background_stream() is None

    memory.attach_cognition(salience_filter=SalienceFilter(), metabolism=None)

    assert memory.get_background_stream() is not None
    assert isinstance(memory.run_metabolism_cycle(), MetabolismReport)


def test_forget_leaves_the_named_buffers_too() -> None:
    memory = AgentWorkingMemory()
    memory.set_metabolism(MemoryMetabolism())
    for content in (*_STALE, _FRESH):
        memory.record_action(content, source="proactive")
    _backdate(memory, "actions", _STALE)

    report = memory.run_metabolism_cycle()

    assert report is not None and report.forgotten_count == 2
    assert [entry.content for entry in memory.get_buffers()["actions"]] == _KEPT
    assert [entry.content for entry in memory.get_buffer("duty").entries] == _KEPT
    assert "checked the warp core telemetry" not in memory.render_buffers(["duty"])


def test_discard_matches_by_value_and_keeps_the_rest() -> None:
    first, second, third = (
        WorkingMemoryEntry(content=text, category="action", source_pathway="proactive", timestamp=1000.0 + number)
        for number, text in enumerate(("one", "two", "three"))
    )
    named = NamedBuffer(name="duty", token_budget=600)
    for entry in (first, second, third):
        named.append(entry)

    assert named.discard([replace(second, metadata={"_decay_score": 0.0})]) == 1
    assert named.entries == [first, third]
    assert named.discard([]) == 0
    for number in range(25):
        named.append(WorkingMemoryEntry(content=f"filler {number}", category="action", source_pathway="proactive"))
    assert len(named) == 20


def test_run_metabolism_cycle_returns_its_report_or_none() -> None:
    memory = AgentWorkingMemory()
    assert memory.run_metabolism_cycle() is None

    memory.set_metabolism(MemoryMetabolism())
    memory.record_action("did something worth keeping", source="proactive")
    report = memory.run_metabolism_cycle()

    assert isinstance(report, MetabolismReport)
    assert report.decayed_count == 1 and report.forgotten_count == 0


def test_a_salience_scorer_that_raises_admits_the_entry(caplog: pytest.LogCaptureFixture) -> None:
    class _Raising(SalienceFilter):
        def score(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> Any:
            raise RuntimeError("scorer fault")

    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=_Raising(), metabolism=None)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_working_memory"):
        memory.record_action("kept despite the scorer fault", source="proactive")

    assert [entry.content for entry in memory.get_buffers()["actions"]] == ["kept despite the scorer fault"]
    assert "salience scoring failed" in caplog.text


def test_at_the_default_threshold_the_gate_demotes_nothing() -> None:
    """D7's evidence: with no agent context and no novelty gate a fresh entry scores at least 0.575
    against 0.3, so enabling the flag at the defaults changes nothing through the salience gate.
    If this fails, AD-668's defaults changed: that is a Captain-visible change to agent memory."""
    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=SalienceFilter.from_config(SalienceConfig()), metabolism=None)

    memory.record_action("ok", source="proactive", metadata={"severity": "low"})
    memory.record_observation("ok", source="proactive")
    memory.record_conversation("ok", partner="someone-unknown", source="dm")
    memory.record_event("ok")
    memory.record_reasoning("ok", source="chain")

    assert len(memory.get_background_stream()) == 0


# --- T10, T11: the driver -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_attaches_now_and_stop_ends_the_cycle() -> None:
    first, second = AgentWorkingMemory(), AgentWorkingMemory()
    cognition = _build(_on(), [("crew-1", first), ("crew-2", second)])
    assert cognition is not None
    await cognition.stop()  # before start: nothing to stop

    await cognition.start()
    try:
        assert cognition.running
        assert first.get_background_stream() is not None
        assert second.get_background_stream() is not None
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert not cognition.running
    await asyncio.wait_for(cognition.stop(), timeout=2)  # idempotent


@pytest.mark.asyncio
async def test_start_twice_keeps_one_task() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    await cognition.start()
    try:
        live = [task for task in asyncio.all_tasks() if task.get_name() == _TASK_NAME and not task.done()]
        assert len(live) == 1
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)


@pytest.mark.asyncio
async def test_stop_passes_on_a_cancellation_aimed_at_its_caller() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    stopper = asyncio.create_task(cognition.stop())
    await asyncio.sleep(0)  # the stopper has cancelled the cycle and is waiting for it

    stopper.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert not cognition.running


@pytest.mark.asyncio
async def test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    cognition = WorkingMemoryCognition(
        working_memories=lambda: [], salience_filter=None, metabolism=MemoryMetabolism(),
        background_max_entries=50, interval_seconds=0.01,
    )
    calls: list[int] = []

    def tick() -> CognitionTickReport:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first cycle fails")
        return CognitionTickReport(agents=0, forgotten=0, audit_flags=0, demoted=0, failed=0)

    monkeypatch.setattr(cognition, "tick_once", tick)
    caplog.set_level(logging.WARNING, logger=wmc.__name__)
    await cognition.start()
    try:
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert len(calls) >= 2
    assert "the next one runs on time" in caplog.text


def test_a_tick_attaches_a_memory_that_joined_or_was_replaced() -> None:
    members: list[tuple[str, AgentWorkingMemory]] = []
    cognition = _build(_on(), members)
    assert cognition is not None and cognition.attach_all() == 0
    joined = AgentWorkingMemory()
    members.append(("crew-1", joined))

    tick = cognition.tick_once()

    assert tick.agents == 1
    assert joined.get_background_stream() is not None


def test_one_failing_agent_does_not_stop_the_others(caplog: pytest.LogCaptureFixture) -> None:
    class _Broken(AgentWorkingMemory):
        def run_metabolism_cycle(self) -> MetabolismReport | None:
            raise RuntimeError("cycle fault")

    good = AgentWorkingMemory()
    cognition = _build(_on(salience={"threshold": 0.99}), [("crew-broken", _Broken()), ("crew-good", good)])
    assert cognition is not None
    cognition.attach_all()
    good.record_observation("routine reading for the good agent", source="proactive")

    with caplog.at_level(logging.WARNING, logger=wmc.__name__):
        tick = cognition.tick_once()

    assert tick == CognitionTickReport(agents=2, forgotten=0, audit_flags=0, demoted=1, failed=1)
    assert "crew-broken" in caplog.text


def test_a_provider_that_raises_makes_an_empty_cycle(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> list[tuple[str, AgentWorkingMemory]]:
        raise RuntimeError("registry fault")

    cognition = WorkingMemoryCognition(
        working_memories=broken, salience_filter=SalienceFilter(), metabolism=None,
        background_max_entries=50, interval_seconds=1.0,
    )
    with caplog.at_level(logging.WARNING, logger=wmc.__name__):
        assert cognition.attach_all() == 0
        assert cognition.tick_once() == CognitionTickReport(agents=0, forgotten=0, audit_flags=0, demoted=0, failed=0)

    assert "could not list crew working memory" in caplog.text


def test_the_tick_logs_what_it_did_per_agent(caplog: pytest.LogCaptureFixture) -> None:
    quiet, busy = AgentWorkingMemory(), AgentWorkingMemory()
    cognition = _build(_on(salience={"threshold": 0.99}), [("crew-quiet", quiet), ("crew-busy", busy)])
    assert cognition is not None
    cognition.attach_all()
    busy.record_observation("routine reading for the busy agent", source="proactive")

    with caplog.at_level(logging.INFO, logger=wmc.__name__):
        cognition.tick_once()

    lines = [record.getMessage() for record in caplog.records if record.name == wmc.__name__]
    assert lines == ["AD-1270: working memory of crew-busy: forgotten=0 audit_flags=0 demoted=1"]


# --- X1 to X7: across the startup and shutdown seams ------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere() -> None:
    """The crossing: AD-573's restore -> the real startup helper -> the real driver -> AD-670 ->
    what the agent is shown and what shutdown freezes, including the restored named-buffer copies."""
    restored = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    bystander = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    bystander_before = _snapshot(bystander)
    runtime = _runtime(
        _agent("crew-1", "counselor", restored),
        _agent("crew-2", "scout", None),
        _agent("tool-1", "not_a_crew_type", bystander),
    )

    await finalize_module._start_working_memory_cognition(runtime=runtime, config=_on())
    cognition = runtime.working_memory_cognition
    try:
        assert isinstance(cognition, WorkingMemoryCognition) and cognition.running
        tick = cognition.tick_once()
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert tick == CognitionTickReport(agents=1, forgotten=2, audit_flags=0, demoted=0, failed=0)
    shown = restored.render_context()
    assert "reviewed the sensor sweep logs" in shown and _FRESH in shown
    assert "checked the warp core telemetry" not in shown and "filed the morning duty report" not in shown
    frozen = restored.to_dict()
    assert [entry["content"] for entry in frozen["recent_actions"]] == _KEPT
    assert [entry["content"] for entry in frozen["named_buffers"]["duty"]["entries"]] == _KEPT
    assert all("_decay_score" in entry["metadata"] for entry in frozen["recent_actions"])
    assert bystander.get_background_stream() is None
    assert _snapshot(bystander) == bystander_before


@pytest.mark.asyncio
async def test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it() -> None:
    memory = AgentWorkingMemory()
    runtime = _runtime(_agent("crew-1", "counselor", memory))
    await finalize_module._start_working_memory_cognition(runtime=runtime, config=_on(salience={"threshold": 0.99}))
    cognition = runtime.working_memory_cognition
    try:
        memory.record_observation("routine hull temperature reading", source="proactive")
        assert "routine hull temperature reading" not in memory.render_context()
        assert len(memory.get_background_stream()) == 1

        tick = cognition.tick_once()
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert tick.demoted == 1
    assert len(memory.get_background_stream()) == 0


@pytest.mark.asyncio
async def test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SalienceFilter", "MemoryMetabolism", "WorkingMemoryCognition"):
        monkeypatch.setattr(wmc, name, _Refuse)
    memory = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    before = _snapshot(memory)
    runtime = _runtime(_agent("crew-1", "counselor", memory))

    await finalize_module._start_working_memory_cognition(runtime=runtime, config=SystemConfig())

    assert runtime.working_memory_cognition is None
    assert _snapshot(memory) == before
    assert memory.get_background_stream() is None
    assert memory.run_metabolism_cycle() is None
    memory.record_action("   ", source="proactive")  # no TRIAGE: a blank entry is still admitted
    assert [entry.content for entry in memory.get_buffers()["actions"]][-1] == "   "


@pytest.mark.asyncio
async def test_an_invalid_value_leaves_cognition_off_at_startup(caplog: pytest.LogCaptureFixture) -> None:
    memory = AgentWorkingMemory()
    runtime = _runtime(_agent("crew-1", "counselor", memory))

    with caplog.at_level(logging.WARNING, logger=finalize_module.__name__):
        await finalize_module._start_working_memory_cognition(
            runtime=runtime, config=_on(metabolism={"cycle_interval_seconds": 0.0}),
        )

    assert runtime.working_memory_cognition is None
    assert memory.get_background_stream() is None
    assert "working-memory cognition config is invalid" in caplog.text


@pytest.mark.asyncio
async def test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    runtime = SimpleNamespace(working_memory_cognition=cognition)

    await asyncio.wait_for(shutdown_module._stop_working_memory_cognition(runtime), timeout=2)

    assert not cognition.running
    assert runtime.working_memory_cognition is None
    foreign = object()
    other = SimpleNamespace(working_memory_cognition=foreign)
    await shutdown_module._stop_working_memory_cognition(other)
    assert other.working_memory_cognition is foreign
    await shutdown_module._stop_working_memory_cognition(SimpleNamespace())


def test_shutdown_stops_the_cycle_before_working_memory_is_frozen() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    calls = _calls_in(_SRC / "startup" / "shutdown.py", "shutdown")
    stops = [line for line, name in calls if name == "_stop_working_memory_cognition"]
    freezes = [line for line, name in calls if name == "save_all"]

    assert len(stops) == 1 and len(freezes) == 1
    assert stops[0] < freezes[0]


def test_startup_starts_the_cycle_after_the_stasis_restore() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    calls = _calls_in(_SRC / "startup" / "finalize.py", "finalize_startup")
    starts = [line for line, name in calls if name == "_start_working_memory_cognition"]
    restores = [line for line, name in calls if name == "from_dict"]

    assert len(starts) == 1 and restores
    assert starts[0] > max(restores)


_WIRED_FIELDS = (
    *(f"metabolism.{name}" for name in MetabolismConfig.model_fields),
    "working_memory.cognition_enabled",
    "salience.threshold",
    "salience.background_max_entries",
)


@pytest.mark.parametrize("path", _WIRED_FIELDS)
def test_the_reader_check_reports_the_wired_fields_as_read(path: str) -> None:
    """BF-926's sibling: these fields are read now, so they carry no inert marker and are not unread."""
    report = _reader_report()

    assert path not in report.inert
    assert path not in report.unread
```

### 7.10 Updated tests (M1)

**Pair P20 (`tests/test_bf926_config_readers.py`).** SEARCH:
```
_SECTIONS_INERT = {
    "memory_budget": ("enabled", "total_budget_tokens", "l0_budget", "l1_budget", "l2_budget", "l3_budget"),
    "metabolism": (
        "enabled", "decay_half_life_seconds", "forget_threshold", "min_entries_per_buffer", "audit_enabled",
        "cycle_interval_seconds", "triage_fullness_threshold", "triage_base_score",
    ),
    "pinned_knowledge": ("enabled", "max_tokens", "max_pins", "default_ttl_seconds"),
```
REPLACE:
```
# AD-1270 (#1324) slice 3: "metabolism" left this table. working_memory.cognition_enabled now builds
# MemoryMetabolism from that section, so its fields are read and no longer marked inert;
# tests/test_ad1270_working_memory_cognition.py pins that they are neither inert nor unread.
_SECTIONS_INERT = {
    "memory_budget": ("enabled", "total_budget_tokens", "l0_budget", "l1_budget", "l2_budget", "l3_budget"),
    "pinned_knowledge": ("enabled", "max_tokens", "max_pins", "default_ttl_seconds"),
```

**Pair P21 (`tests/test_ad1270e2b_cognition_models.py`).** SEARCH:
```
                                   'ship_budget': 800,
                                   'engagement_budget': 800},
        'MemoryBudgetConfig': {   'enabled': True,
```
REPLACE:
```
                                   'ship_budget': 800,
                                   'engagement_budget': 800,
                                   # AD-1270 (#1324) slice 3 added this default-off flag after the
                                   # move; every other key is still the pre-move dump.
                                   'cognition_enabled': False},
        'MemoryBudgetConfig': {   'enabled': True,
```

**Pair P22 (`tests/test_ad1270e1_config_facade.py`).** SEARCH:
```
    # AD-1341 S5 (#1569) adds ArchivePromotionConfig's three fields and SystemConfig.archive_promotion (1875 -> 1879).
    assert counts["field_definitions"] == 1879  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1341 S5 (#1569) adds ArchivePromotionConfig's three fields and SystemConfig.archive_promotion (1875 -> 1879).
    # AD-1270 (#1324) slice 3 adds working_memory.cognition_enabled (1879 -> 1880).
    assert counts["field_definitions"] == 1880  # AD-1206 intentionally adds github_repository.
```

**Pair P23 (`tests/test_ad1152_agentic_correlation.py`).** SEARCH:
```
    assert config.pop("archive_promotion") == {"enabled": False, "settle_hours": 24.0, "max_per_cycle": 8}
    runtime = _local_runtime()
```
REPLACE:
```
    assert config.pop("archive_promotion") == {"enabled": False, "settle_hours": 24.0, "max_per_cycle": 8}
    # AD-1270 (#1324) slice 3's working-memory cognition flag was added after this capture too. It is default
    # off, and while off nothing attaches to working memory; this agentic-loop observation records none.
    assert config["working_memory"].pop("cognition_enabled") is False
    runtime = _local_runtime()
```

### 7.11 Generated files (M1; no pairs)

- `docs/development/config-facade-baseline.yaml`: `check_config_facade.py --update-baseline` (§4 step 5 lists the allowed diff).
- `docs/development/config-reference.md`: `gen_config_reference.py`.
- `docs/development/dormant-class-baseline.yaml`: `check_dormant_classes.py --update-baseline` removes exactly the five rows (predicted: 166 rows remain from slice 2's 171).

## 8. Tracking (M2's commit)

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 3 -- working-memory cognition, wired behind a default-off flag.** AD-668's salience filter and AD-670's metabolism (DECAY, AUDIT, FORGET, TRIAGE) were built in April and never constructed: nothing called `set_metabolism` or passed `salience_filter=`, so `metabolism.enabled: true` changed nothing. A new flag, `working_memory.cognition_enabled` (default false, read once at startup by `build_working_memory_cognition`), attaches one shared filter and one shared engine, built from the `salience` and `metabolism` sections, to every crew agent's working memory. `WorkingMemoryCognition`, started in finalize after the AD-573 stasis restore and stopped in shutdown before the freeze, runs one metabolism cycle per agent every `metabolism.cycle_interval_seconds`, drains each background stream, re-attaches on every cycle and logs per agent what it forgot, flagged and demoted. FORGET now also removes the entry from the named buffers, matched by value because the restore rebuilds them as copies; a salience scorer that raises admits the entry; values that would spin the cycle or refuse every entry leave it off with a warning. Off, nothing is constructed and working memory is byte-identical. Nothing durable is deleted. At the default threshold the salience gate demotes nothing (a fresh entry scores at least 0.575 against 0.3). Turning it on by default is the Captain's decision. The five dormant rows (`MemoryMetabolism`, `AuditFlag`, `MetabolismReport`, `SalienceFilter`, `SalienceScore`) leave the baseline. New: `src/probos/cognitive/working_memory_cognition.py`, `tests/test_ad1270_working_memory_cognition.py`. The contract is `prompts/ad-1270-working-memory-cognition.md`.

```

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- working-memory cognition (AD-668 salience, AD-670 metabolism) wired behind a default-off flag (2026-10-2X)

**Decision.** `working_memory.cognition_enabled` (default false) is read once, in `build_working_memory_cognition`. Off, nothing is constructed. On, one shared `SalienceFilter` (no novelty gate) and one shared `MemoryMetabolism`, built from `salience` and `metabolism` (each section's `enabled` turns its own part off), are attached to every crew agent's working memory by `WorkingMemoryCognition`. It runs one metabolism cycle per agent and drains its background stream every `metabolism.cycle_interval_seconds`, re-attaching on every cycle so memories the AD-573 restore replaced, and agents that join later, are covered. FORGET also removes the forgotten entry from the named buffers, matched by `(timestamp, content, category, source_pathway)`. Values that would spin the cycle or make a gate refuse every entry are refused at startup and leave it off. **Why.** `metabolism.enabled` and `salience.enabled` are already true in the tracked config, so neither could be the switch; one flag keeps "off" byte-identical; injection at agent construction is lost on every stasis restore. **What it touches.** In-memory buffers only: no episode, Ward Room post or store record is deleted (AD-1339's carve-out); the freeze and the AD-671 summary see the survivors, and kept entries carry `_decay_score`. **Rejected.** An observe-only stage (at the defaults the gate demotes nothing and FORGET acts only on ring entries older than about 4.3 hours, so evidence comes cheaper from replaying frozen snapshots and the per-agent log lines); passing the runtime's NoveltyGate (it would record working-memory content in the novelty history the proactive loop and the Ward Room use); driving the cycle from the proactive loop or from dreams; Pydantic bounds on the sections (they would fail boot on a value that changes nothing while the flag is off). **Captain.** Turning it on by default changes what every crew agent keeps in working memory; that is his decision, with evidence.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): tick the working-memory item with the commit and receipt, and post the register rows.

## 9. What this does NOT change

- AD-670's operations (the decay formula, the audit heuristic, triage scoring) and AD-668's scoring. Only `run_metabolism_cycle`'s return value and named-buffer coherence change (AD-1339: "no change to the AD-670 metabolism").
- `AgentWorkingMemory()` at `cognitive_agent.py:1365`; `to_dict`/`from_dict`; `working_memory_store`; the dream bridge; episodic memory; `render_context`.
- No novelty gate; `set_agent_context` still has no caller (R2, R3).
- No EventType, route, HXI view or persisted schema. Config values in `config/system.yaml` are unchanged; only three comments are.
- The default stays off; nothing starts, stops or restarts the vessel.
- `finalize.py:6321`'s private `agent._working_memory` assignment (R11).

## 10. Mutation rows (one campaign on the M1 tree, after an unmutated baseline of M1's focused list passes; run on the Captain's Windows host)

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| G-1 | M1 | `cognitive/working_memory_cognition.py` | `if not working_memory.cognition_enabled:` | `if False:` | `test_flag_off_the_builder_constructs_nothing`, `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged` |
| G-2 | M1 | `cognitive/working_memory_cognition.py` | `salience_filter = _build_salience_filter(salience) if salience.enabled else None` | `salience_filter = _build_salience_filter(salience)` | `test_each_section_turns_its_own_part_off[salience-off]` |
| G-3 | M1 | `cognitive/working_memory_cognition.py` | `engine = _build_metabolism(metabolism) if metabolism.enabled else None` | `engine = _build_metabolism(metabolism)` | `test_each_section_turns_its_own_part_off[metabolism-off]` |
| G-4 | M1 | `cognitive/working_memory_cognition.py` | `if salience_filter is None and engine is None:` | `if False:` | `test_both_sections_off_attaches_nothing` |
| G-5 | M1 | `cognitive/working_memory_cognition.py` | `background_max_entries=salience.background_max_entries,` | `background_max_entries=50,` | `test_the_salience_section_sets_the_threshold_and_the_stream_size`, `test_invalid_values_are_refused[background-negative]` |
| G-6 | M1 | `cognitive/working_memory_cognition.py` | `interval_seconds=metabolism.cycle_interval_seconds,` | `interval_seconds=300.0,` | `test_invalid_values_are_refused[interval-zero]`, `test_an_invalid_value_leaves_cognition_off_at_startup` |
| G-7 | M1 | `cognitive/working_memory_cognition.py` | `if not (0.0 <= config.threshold <= 1.0):` | `if False:` | `test_invalid_values_are_refused[threshold-nan]`, `test_invalid_values_are_refused[threshold-above-one]` |
| G-8 | M1 | `cognitive/working_memory_cognition.py` | `return SalienceFilter.from_config(config)` | `return SalienceFilter()` | `test_the_salience_section_sets_the_threshold_and_the_stream_size`, `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it` |
| G-9 | M1 | `cognitive/working_memory_cognition.py` | `if not math.isfinite(config.decay_half_life_seconds):` | `if False:` | `test_invalid_values_are_refused[half-life-nan]`, `test_invalid_values_are_refused[half-life-inf]` |
| G-10 | M1 | `cognitive/working_memory_cognition.py` | `if not (0.0 <= config.triage_fullness_threshold < 1.0):` | `if not (0.0 <= config.triage_fullness_threshold <= 1.0):` | `test_invalid_values_are_refused[fullness-one]` |
| G-11 | M1 | `cognitive/working_memory_cognition.py` | `if not (0.0 <= config.triage_fullness_threshold < 1.0):` | `if False:` | `test_invalid_values_are_refused[fullness-one]`, `test_invalid_values_are_refused[fullness-negative]` |
| G-12 | M1 | `cognitive/working_memory_cognition.py` | `if not (0.0 <= config.triage_base_score <= 1.0):` | `if False:` | `test_invalid_values_are_refused[base-nan]`, `test_invalid_values_are_refused[base-above-one]` |
| G-13 | M1 | `cognitive/working_memory_cognition.py` | `decay_half_life_seconds=config.decay_half_life_seconds,` | `decay_half_life_seconds=3600.0,` | `test_the_metabolism_section_sets_decay_forget_and_floor` |
| G-14 | M1 | `cognitive/working_memory_cognition.py` | `forget_threshold=config.forget_threshold,` | `forget_threshold=0.05,` | `test_the_metabolism_section_sets_decay_forget_and_floor` |
| G-15 | M1 | `cognitive/working_memory_cognition.py` | `min_entries_per_buffer=config.min_entries_per_buffer,` | `min_entries_per_buffer=2,` | `test_the_metabolism_section_sets_decay_forget_and_floor` |
| G-16 | M1 | `cognitive/working_memory_cognition.py` | `audit_enabled=config.audit_enabled,` | `audit_enabled=True,` | `test_the_metabolism_section_sets_audit[off]` |
| G-17 | M1 | `cognitive/working_memory_cognition.py` | `triage_fullness_threshold=config.triage_fullness_threshold,` | `triage_fullness_threshold=0.8,` | `test_the_metabolism_section_sets_triage[fullness]` |
| G-18 | M1 | `cognitive/working_memory_cognition.py` | `triage_base_score=config.triage_base_score,` | `triage_base_score=0.3,` | `test_the_metabolism_section_sets_triage[base]` |
| G-19 | M1 | `cognitive/working_memory_cognition.py` | `if salience_filter is None and metabolism is None:` | `if False:` | `test_the_driver_needs_a_part_and_a_finite_period[nothing]` |
| G-20 | M1 | `cognitive/working_memory_cognition.py` | `if not (math.isfinite(interval_seconds) and interval_seconds > 0):` | `if not interval_seconds > 0:` | `test_invalid_values_are_refused[interval-inf]`, `test_the_driver_needs_a_part_and_a_finite_period[inf]` |
| G-21 | M1 | `cognitive/working_memory_cognition.py` | `if not (math.isfinite(interval_seconds) and interval_seconds > 0):` | `if False:` | `test_invalid_values_are_refused[interval-zero]`, `test_invalid_values_are_refused[interval-nan]`, `test_the_driver_needs_a_part_and_a_finite_period[zero]` |
| G-22 | M1 | `cognitive/working_memory_cognition.py` | `if background_max_entries < 0:` | `if False:` | `test_invalid_values_are_refused[background-negative]`, `test_the_driver_needs_a_part_and_a_finite_period[negative-stream]` |
| G-23 | M1 | `cognitive/working_memory_cognition.py` | `return self._task is not None and not self._task.done()` | `return self._task is not None` | `test_start_attaches_now_and_stop_ends_the_cycle` |
| G-24 | M1 | `cognitive/working_memory_cognition.py` | `self._attach(memory)` | `pass` | `test_start_attaches_now_and_stop_ends_the_cycle`, `test_each_section_turns_its_own_part_off[metabolism-off]` |
| G-25 | M1 | `cognitive/working_memory_cognition.py` | `attached += 1` | `pass` | `test_each_section_turns_its_own_part_off[salience-off]`, `test_the_salience_section_sets_the_threshold_and_the_stream_size` |
| G-26 | M1 | `cognitive/working_memory_cognition.py` | `self._attach(memory)  # every cycle: a replaced or joining working memory is covered` | `pass` | `test_a_tick_attaches_a_memory_that_joined_or_was_replaced` |
| G-27 | M1 | `cognitive/working_memory_cognition.py` | `report = memory.run_metabolism_cycle()` | `report = None` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| G-28 | M1 | `cognitive/working_memory_cognition.py` | `drained = len(stream.drain()) if stream is not None else 0` | `drained = len(stream.peek()) if stream is not None else 0` | `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it` |
| G-29 | M1 | `cognitive/working_memory_cognition.py` | `failed += 1` | `pass` | `test_one_failing_agent_does_not_stop_the_others` |
| G-30 | M1 | `cognitive/working_memory_cognition.py` | `continue` | `pass` | `test_one_failing_agent_does_not_stop_the_others` |
| G-31 | M1 | `cognitive/working_memory_cognition.py` | `agent_forgotten = report.forgotten_count if report is not None else 0` | `agent_forgotten = 0` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| G-32 | M1 | `cognitive/working_memory_cognition.py` | `agent_flags = len(report.audit_flags) if report is not None else 0` | `agent_flags = 0` | `test_the_metabolism_section_sets_audit[on]` |
| G-33 | M1 | `cognitive/working_memory_cognition.py` | `if agent_forgotten or agent_flags or drained:` | `if False:` | `test_the_tick_logs_what_it_did_per_agent` |
| G-34 | M1 | `cognitive/working_memory_cognition.py` | `if agent_forgotten or agent_flags or drained:` | `if True:` | `test_the_tick_logs_what_it_did_per_agent` |
| G-35 | M1 | `cognitive/working_memory_cognition.py` | `forgotten += agent_forgotten` | `pass` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| G-36 | M1 | `cognitive/working_memory_cognition.py` | `audit_flags += agent_flags` | `pass` | `test_the_metabolism_section_sets_audit[on]` |
| G-37 | M1 | `cognitive/working_memory_cognition.py` | `demoted += drained` | `pass` | `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it`, `test_one_failing_agent_does_not_stop_the_others` |
| G-38 | M1 | `cognitive/working_memory_cognition.py` | `agents=len(members),` | `agents=0,` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere`, `test_a_tick_attaches_a_memory_that_joined_or_was_replaced` |
| G-39 | M1 | `cognitive/working_memory_cognition.py` | `return []` | `raise` | `test_a_provider_that_raises_makes_an_empty_cycle` |
| G-40 | M1 | `cognitive/working_memory_cognition.py` | `if self.running:` | `if False:` | `test_start_twice_keeps_one_task` |
| G-41 | M1 | `cognitive/working_memory_cognition.py` | `self.attach_all()` | `pass` | `test_start_attaches_now_and_stop_ends_the_cycle` |
| G-42 | M1 | `cognitive/working_memory_cognition.py` | `self._task = asyncio.create_task(self._loop(), name="ad1270-working-memory-cognition")` | `self._task = None` | `test_start_attaches_now_and_stop_ends_the_cycle`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| G-43 | M1 | `cognitive/working_memory_cognition.py` | `if task is None:` | `if False:` | `test_start_attaches_now_and_stop_ends_the_cycle` |
| G-44 | M1 | `cognitive/working_memory_cognition.py` | `task.cancel()` | `pass` | `test_start_attaches_now_and_stop_ends_the_cycle`, `test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else` |
| G-45 | M1 | `cognitive/working_memory_cognition.py` | `if current is not None and current.cancelling():` | `if False:` | `test_stop_passes_on_a_cancellation_aimed_at_its_caller` |
| G-46 | M1 | `cognitive/working_memory_cognition.py` | `await asyncio.sleep(self._interval)` | `await asyncio.sleep(3600)` | `test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle` |
| G-47 | M1 | `cognitive/working_memory_cognition.py` | `self.tick_once()` | `pass` | `test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle` |
| G-48 | M1 | `cognitive/working_memory_cognition.py` | `logger.warning("AD-1270: working-memory cycle raised; the next one runs on time", exc_info=True)` | `pass` | `test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle` |
| A-1 | M1 | `cognitive/agent_working_memory.py` | `if salience_filter is not None:` | `if True:` | `test_attach_cognition_with_none_leaves_that_part_as_it_is` |
| A-2 | M1 | `cognitive/agent_working_memory.py` | `self._salience_filter = salience_filter  # AD-1270: the gate now runs on every record_*` | `pass` | `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it`, `test_attach_cognition_is_idempotent_and_keeps_the_stream` |
| A-3 | M1 | `cognitive/agent_working_memory.py` | `if self._background_stream is None:` | `if True:` | `test_attach_cognition_is_idempotent_and_keeps_the_stream` |
| A-4 | M1 | `cognitive/agent_working_memory.py` | `self._background_stream = BackgroundStream(max_entries=background_max_entries)` | `self._background_stream = BackgroundStream()` | `test_the_salience_section_sets_the_threshold_and_the_stream_size` |
| A-5 | M1 | `cognitive/agent_working_memory.py` | `if metabolism is not None:` | `if True:` | `test_attach_cognition_with_none_leaves_that_part_as_it_is` |
| A-6 | M1 | `cognitive/agent_working_memory.py` | `self.set_metabolism(metabolism)` | `pass` | `test_attach_cognition_with_none_leaves_that_part_as_it_is`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-7 | M1 | `cognitive/agent_working_memory.py` | `if self._metabolism is None:` | `if False:` | `test_run_metabolism_cycle_returns_its_report_or_none`, `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged` |
| A-8 | M1 | `cognitive/agent_working_memory.py` | `if report.forgotten_count:` | `if False:` | `test_forget_leaves_the_named_buffers_too`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-9 | M1 | `cognitive/agent_working_memory.py` | `forgotten = [entry for entry in before if id(entry) not in kept]` | `forgotten = []` | `test_forget_leaves_the_named_buffers_too`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-10 | M1 | `cognitive/agent_working_memory.py` | `named.discard(forgotten)` | `pass` | `test_forget_leaves_the_named_buffers_too`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-11 | M1 | `cognitive/agent_working_memory.py` | `return report` | `return None` | `test_run_metabolism_cycle_returns_its_report_or_none`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-12 | M1 | `cognitive/agent_working_memory.py` | `return (entry.timestamp, entry.content, entry.category, entry.source_pathway)` | `return id(entry)` | `test_discard_matches_by_value_and_keeps_the_rest`, `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| A-13 | M1 | `cognitive/agent_working_memory.py` | `kept = [entry for entry in self._entries if _entry_key(entry) not in keys]` | `kept = list(self._entries)` | `test_discard_matches_by_value_and_keeps_the_rest` |
| A-14 | M1 | `cognitive/agent_working_memory.py` | `if removed:` | `if False:` | `test_discard_matches_by_value_and_keeps_the_rest` |
| A-15 | M1 | `cognitive/agent_working_memory.py` | `self._entries.extend(kept)` | `pass` | `test_discard_matches_by_value_and_keeps_the_rest` |
| A-16 | M1 | `cognitive/agent_working_memory.py` | `return removed` | `return 0` | `test_discard_matches_by_value_and_keeps_the_rest` |
| A-17 | M1 | `cognitive/agent_working_memory.py` | `return True  # AD-1270 (#1324): fail open; a scorer fault must not cost the agent the entry` | `return False` | `test_a_salience_scorer_that_raises_admits_the_entry` |
| F-1 | M1 | `startup/finalize.py` | `runtime.working_memory_cognition = None` | `pass` | `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged`, `test_an_invalid_value_leaves_cognition_off_at_startup` |
| F-2 | M1 | `startup/finalize.py` | `if not is_crew_agent(agent, ontology):` | `if False:` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| F-3 | M1 | `startup/finalize.py` | `if memory is not None:` | `if True:` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| F-4 | M1 | `startup/finalize.py` | `except ValueError:  # AD-1270: an invalid metabolism or salience value` | `except ZeroDivisionError:  # AD-1270: an invalid metabolism or salience value` | `test_an_invalid_value_leaves_cognition_off_at_startup` |
| F-5 | M1 | `startup/finalize.py` | `if cognition is None:` | `if False:` | `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged` |
| F-6 | M1 | `startup/finalize.py` | `await cognition.start()` | `pass` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere` |
| F-7 | M1 | `startup/finalize.py` | `runtime.working_memory_cognition = cognition` | `pass` | `test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere`, `test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it` |
| F-8 | M1 | `startup/finalize.py` | `await _start_working_memory_cognition(runtime=runtime, config=config)` | `pass` | `test_startup_starts_the_cycle_after_the_stasis_restore` |
| S-1 | M1 | `startup/shutdown.py` | `if not isinstance(cognition, WorkingMemoryCognition):` | `if False:` | `test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else` |
| S-2 | M1 | `startup/shutdown.py` | `await cognition.stop()` | `pass` | `test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else` |
| S-3 | M1 | `startup/shutdown.py` | `runtime.working_memory_cognition = None` | `pass` | `test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else` |
| S-4 | M1 | `startup/shutdown.py` | `await _stop_working_memory_cognition(runtime)` | `pass` | `test_shutdown_stops_the_cycle_before_working_memory_is_frozen` |
| C-1 | M1 | `config_models/cognition.py` | `cognition_enabled: bool = Field(default=False, description="AD-1270 (#1324): attach AD-668 salience filtering and AD-670 metabolism to every crew agent's working memory and run their cycle every metabolism.cycle_interval_seconds. Off: nothing is constructed. Read once at startup.")` | `cognition_enabled: bool = Field(default=True, description="AD-1270 (#1324): attach AD-668 salience filtering and AD-670 metabolism to every crew agent's working memory and run their cycle every metabolism.cycle_interval_seconds. Off: nothing is constructed. Read once at startup.")` | `test_the_flag_is_off_by_default`, `test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged` |
| C-2 | M1 | `config_models/cognition.py` | `"""AD-670: Working memory metabolism — active lifecycle management. Read only when working_memory.cognition_enabled is on (AD-1270, #1324): enabled then turns metabolism off on its own, cycle_interval_seconds sets the cycle's period, and the rest configure MemoryMetabolism."""` | `"""AD-670: Working memory metabolism — active lifecycle management. Inert: no production code reads this section to act on it (BF-926, #1656): nothing constructs MemoryMetabolism, so enabled and every threshold change nothing (#1324)."""` | `test_the_reader_check_reports_the_wired_fields_as_read[metabolism.enabled]`, `test_the_reader_check_reports_the_wired_fields_as_read[metabolism.cycle_interval_seconds]` |

## 11. Verified Against Codebase (2026-10-27, on `de7ecc7d`)

```
Grep "MemoryMetabolism|SalienceFilter|set_metabolism|salience_filter|BackgroundStream|SalienceScore|MetabolismReport|AuditFlag" src
  agent_working_memory.py:26,29,291,297,299,328,377,383,385,393,568; config_models/cognition.py:334; memory_metabolism.py:24,34,39,43,118,130,154,198,204,225; salience_filter.py:28,37,71,79,91,188-209
Read agent_working_memory.py:1-60, 180-610, 692-1021
Read memory_metabolism.py:1-231; salience_filter.py:1-210
Read cognitive_agent.py:1340-1384, 1700-1709, 10398-10415
Read finalize.py:518-529, 707-817, 4055-4066, 5800-5827, 5940-5980, 6280-6339; Grep "^logger = " finalize.py -> :27; "^from probos.crew_utils import is_crew_agent" finalize.py:20, shutdown.py:21
Read shutdown.py:1-100, 1638-1650, 1940-1969
Read threads/transcript_reaper.py:1-110
Read dream_wm_bridge.py:25-99; routers/agents.py:3900-3914; runtime.py:1082-1089
Grep working_memory_store.py -> :22 CREATE TABLE, :67/:85 INSERT OR REPLACE, :130 DELETE (clear)
Read config_models/cognition.py:275-354; config_models/knowledge.py:485-502; Grep config.py:4056,4060,4066
Read config/system.yaml:1960-1967, 2000-2011, 2034-2041
Read scripts/check_config_readers.py:1-145; tests/test_bf926_config_readers.py:1-40, 100-171
Read tests/test_ad1270e2b_cognition_models.py:1-80, 180-314, 355-394, 440-499
Read tests/test_ad1270e1_config_facade.py:1510-1564
Read tests/test_ad1152_agentic_correlation.py:189-357, 488-520
Read docs/development/config-profiles.yaml:10-49, 618-629; scripts/check_config_profiles.py:1-40; Grep tests/test_ad1185_config_profiles.py:857,864-866
Read scripts/check_dormant_classes.py:1-40, 165-204; docs/development/dormant-class-baseline.yaml:1-6,68-74,144-148
Read tests/test_ad670_memory_metabolism.py:1-46, 326-363
Read prompts/ad-1270-night-orders-escalation.md (shape); prompts/ad-1270-dormant-class-check.md:1-112 (shape)
Read docs/research/ambient-awareness-optimal-working-memory.md:467-491, 562-611, 727-741; DECISIONS.md:5520-5548
Grep pyproject.toml -> requires-python = ">=3.12"; asyncio_mode = "auto"
Grep "\.cancelling\(\)" src -> 21 uses (precedent)
gh issue view 1566 (body); gh issue list --state all --search "AD-670 OR AD-668 OR MemoryMetabolism OR SalienceFilter"
```

## Absence Verified (2026-10-27)

| ID | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No production constructor of the five classes; no `set_metabolism` caller; no `salience_filter=` argument | Grep of the eight names in `src` | definitions and annotation/TYPE_CHECKING uses only (§11) | yes |
| AV2 | `set_agent_context` and `render_buffers` have no production caller | Grep `render_buffers\(\|render_context\(\|iter_salience_entries\(\|set_agent_context\(` in `src` | defs at `agent_working_memory.py:352,373,692,789`; `render_context` callers `cognitive_agent.py:9109,10550,10882,11077`; `iter_salience_entries` `:10412` | yes |
| AV3 | One construction site | Grep `AgentWorkingMemory\(` in `src` | `cognitive_agent.py:1365` (plus `cls()` in `from_dict`) | yes |
| AV4 | No NoveltyGate reaches `SalienceFilter` | Grep `NoveltyGate\(\|novelty_gate\s*=` in `src` | `runtime.py:3675`, `proactive.py:675`, `ward_room_pipeline.py:244`, `finalize.py:4275-4280`, `salience_filter.py:63,76` | yes |
| AV5 | The only restore and freeze sites | Grep `save_all\(\|\.from_dict\(` in `src/probos/startup` | `shutdown.py:1962`, `finalize.py:6308` | yes |
| AV6 | Nothing reads `config.salience`/`config.metabolism` | Grep `\.salience\b\|\.metabolism\b\|SalienceConfig\|MetabolismConfig` in `src` | declarations and `salience_filter.py:13,68` (`from_config`, uncalled) | yes |
| AV7 | Only two test files exercise the engines | Grep (count) `MemoryMetabolism\|SalienceFilter\|set_metabolism\|run_metabolism_cycle\|get_background_stream\|salience_filter=` in `tests` | `test_ad668_salience_filter.py` 36, `test_ad670_memory_metabolism.py` 32 | yes |
| AV8 | No test source-scans `agent_working_memory.py` | Grep `agent_working_memory\.py` in `tests` | `fixtures/file_durations.json` only | yes |
| AV9 | The new finalize lines are unique | Grep `if cognition is None:\|if memory is not None:\|if not is_crew_agent\(agent, ontology\):\|await cognition\.start\(\)\|runtime\.working_memory_cognition` in `src/probos/startup` | none | yes |
| AV10 | New `agent_working_memory.py` mutation lines are unique | Grep `^\s*(return report\|if self\._metabolism is None:\|self\._salience_filter = salience_filter\|return removed\|if removed:)\s*$` | `:297` (the constructor's, so A-2 carries a comment), `:584` (A-7, unique) | yes |
| AV11 | Only BF-926 and e2b pin these config models in tests (besides the dump goldens) | Grep `MemoryMetabolism\|MetabolismConfig\|metabolism\|only stale_threshold_hours\|WorkingMemoryConfig` in `tests`, excluding `test_ad670_*` | `test_ad1270e2b_cognition_models.py`, `test_bf926_config_readers.py:118` | yes |
| AV12 | Only #1566 among issues citing AD-668/670 states a requirement here | `gh issue list --state all --search "AD-670 OR AD-668 OR MemoryMetabolism OR SalienceFilter"` | #1566 (open), #1656, #1324, #1523, #1568, #1565, #1654, #349, #1037, #351, #984, #352, #675 | yes |

## Not verified (the orchestrator verifies by running)

1. The counts: the new file's 60 cases; the census header (450, 226, 224, 85, 141); the facade regeneration's hunks; the dormant baseline's 166 rows.
2. P21's leading spaces (35, counted from the Read output of a CRLF working copy).
3. That `check_architecture_principles.py --check` stays green, and that `tests/test_ad1346_admission_service.py`'s and `tests/test_ad1343_stop_seam_inventory.py`'s censuses do not classify the new loop (reasoned; files not read in full).
4. That the P19 YAML row parses (plain multi-line scalars, no `: `).
5. G-44's kill through `asyncio.wait_for` on 3.12 (it awaits in the current task; G-44's second killer is independent of that).
6. Line numbers after slice 2's merge in `PROGRESS.md` and `DECISIONS.md` (anchors are the standing lines).

## 12. Deterministic gate checks, resolved up front

- `check_architecture_principles.py --check`: the one `create_task` result is stored (`self._task = ...`), so there is no `unowned-task` row. The new class is small. `cognitive` → `config` is a type-only import of an unranked package.
- `check_config_facade.py --check`, `gen_config_reference.py --check`: green after §7.11.
- `check_config_profiles.py --check`: the new default-False flag has a row (gate 3); the census header matches (`tests/test_ad1185_config_profiles.py:864-866`).
- `check_dormant_classes.py --check`: `0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant`.
- `check_config_readers.py` (report-only): eight fewer inert fields; the metabolism fields, `cognition_enabled` and `background_max_entries` are read.

## 13. Prior Art and Blind Spots

- **Internal.** AD-668/AD-670/AD-671 contracts and DECISIONS. The research note `ambient-awareness-optimal-working-memory.md` (§6.3: the background stream for idle review; §8.2: the entry lifecycle; Phase 4: metabolism operates on named buffers) is absorbed: D5 and D8. BF-926's reader check (absorbed as X7). AD-986d's reaper (lifecycle precedent, absorbed; its cancellation swallow is rejected, D4). AD-672's per-crew wiring loop (rejected, D3).
- **External.**
  - [MemoryBank](https://arxiv.org/abs/2305.10250) decays memories on an Ebbinghaus curve and strengthens them each time they are recalled. Considered, deferred: AD-670 decays by age only, and adding reinforcement changes AD-670, which AD-1339 excludes (R14).
  - ACT-R base-level activation ([overview](https://arxiv.org/pdf/1306.0125); [a practitioner's eviction-without-deletion account](https://dev.to/futhgar/eviction-without-deletion-running-an-act-r-decay-policy-for-agent-memory-36hi)) treats forgetting as falling below a retrieval threshold, never as deletion. Absorbed as the framing of D6: FORGET leaves the transient view, and the episodic record stays.
  - `docs/research/reference-projects.md`: the Letta row was last reviewed 2026-10-17 on a 180-day interval, so it is not overdue (judged 2026-10-27). Other rows were not scanned.
- **Blind spots found and handled:**
  - The stasis restore replaces the memory, and its named copies are distinct objects (D3, D8).
  - Both `enabled` keys are already true (D1).
  - The shared novelty history (D10).
  - The salience gate cannot bite at its defaults (D7, T9).
  - NaN, infinite and edge values reach a division or a refuse-all (D9).
  - A triage fullness of 1.0 divides by zero on the record path (D9).
  - Agents join late (D3).
  - Cancellation was swallowed in the precedent (D4).
  - FORGET was incomplete against the named buffers (D8).
  - The freeze and API now show `_decay_score` (R7).
- **Recorded, not fixed:** R2 to R16.

## 14. Diff Reviewer: properties to verify

1. **Off:** `build_working_memory_cognition` returns `None` before it constructs anything or calls the provider. Finalize leaves `runtime.working_memory_cognition` as `None`. For a memory nothing was attached to, no `AgentWorkingMemory` behaviour changes: `run_metabolism_cycle` returns `None`; `_passes_salience_gate` returns `True` before the new `try`; `to_dict` is byte-identical.
2. `cognition_enabled` is read in exactly one place in `src` (besides its declaration).
3. **On:** every crew agent with a working memory is attached, at start and on every cycle, and no other agent is. One `SalienceFilter` and one `MemoryMetabolism` are shared. No NoveltyGate is passed.
4. **Failures:**
   - One agent's failure is logged with its id and counted, and the other agents still run.
   - A provider that raises yields an empty cycle.
   - A raising tick does not end the loop.
   - `CancelledError` leaves the loop.
   - `stop()` absorbs only the cancellation it caused itself.
5. **Ordering:**
   - There is one named, stored task, and `start` and `stop` are idempotent.
   - Shutdown calls the stop helper before `save_all`.
   - Finalize calls the start helper after the AD-573 `from_dict`.
6. **Named buffers:** after a cycle, no named buffer holds an entry equal by `_entry_key` to one FORGET removed from a ring. Other entries and each buffer's maximum length are unchanged.
7. **Refused values:**
   - the builder refuses every value in `_INVALID` with `ValueError`;
   - `MemoryMetabolism` still refuses its own;
   - finalize logs the refusal and leaves cognition off.
8. **Durable writes:** no episodic, Ward Room, store or file write is added. The only persisted differences are the `_decay_score` key and fewer entries in the freeze snapshot.
9. **Config and generated files:** the field defaults to `False`. No docstring says metabolism is inert. The regenerated files differ only as §4 step 5 lists. The dormant baseline loses exactly the five rows.
10. **Updated pins:** each says why inline, and none is loosened beyond the new field. BF-926 drops `metabolism` from the inert table and X7 pins those fields as read; e2b gains one key; e1 gains one count; AD-1152 gains one pop.

## 15. Acceptance criteria

- [ ] M1 and M2 built in order, one delegation and one local commit each, staged by explicit path; `config/system.yaml` by partial hunk.
- [ ] The new test file failed at collection on M1's base. §7.10's files failed on the base as §4 predicts.
- [ ] M1's focused gate passes with `-n 0`. All five `--check` scripts pass, and the dormant check reports `0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant` (whole output in the report).
- [ ] The regenerated diffs match §4 step 5 (hunk lists in the report).
- [ ] M1 has a cross-family review (`gpt-6.1-sol`) against §14, with its findings repaired.
- [ ] The §10 campaign runs once on the M1 tree. Every row is killed, or returned to the Architect.
- [ ] `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass after M2.
- [ ] The orchestrator's single broad gate passes with its receipt.
- [ ] #1324's working-memory item is ticked with the commit and receipt; the register rows are posted.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R1. Default-on is the Captain's decision.** Evidence to bring him:
  - a replay of each agent's frozen state from `%LOCALAPPDATA%\ProbOS\data\working_memory.db` (table `working_memory`, `state_json`) through the two engines offline, counting what FORGET and TRIAGE would remove;
  - after he enables it, the `AD-1270: working memory of <id>` lines.
- **R2.** `set_agent_context` has no caller, so relevance and social scores sit at neutral, and the gate demotes nothing at a threshold of 0.3 (lowest fresh score 0.575). Owner: the slice that feeds department, duty, alert level and trust.
- **R3.** No novelty gate. The runtime's gate would record working-memory content in the shared per-agent novelty history.
- **R4.** TRIAGE refusals are logged at DEBUG only, not counted. A counter needs edits in five record methods.
- **R5.** Audit flags are counted and logged, not shown to the agent.
- **R6.** The drain discards what it reads. Re-promotion after idle review (research note §8.2, "pattern detected: promote") is not built.
- **R7.** `_decay_score` persists in the AD-573 freeze and shows in `GET /agents/{id}/working-memory`. It is an extra key in free-form metadata, not a schema change, and stays inert if the flag is later turned off.
- **R8.** When on, the AD-671 pre-dream summary's counts reflect the survivors.
- **R9.** Value-keyed discard also removes an identical duplicate (same timestamp, content, category and pathway).
- **R10.** The `TranscriptReaper` precedent swallows a cancellation aimed at its caller. This slice's `stop()` does not. A BF for the reaper is recommended.
- **R11.** `finalize.py:6321` assigns the private `agent._working_memory` across modules (pre-existing).
- **R12.** `_passes_salience_gate` reads `SalienceFilter._threshold` across modules (pre-existing, `agent_working_memory.py:393`).
- **R13.** Two INFO lines per busy agent: AD-670's own, which has no agent id (`memory_metabolism.py:215-223`), and this slice's.
- **R14.** Decay is by age only, with no reinforcement on use (MemoryBank). A rarely touched but important ring entry can be forgotten. Active engagements and pinned knowledge sit outside metabolism.
- **R15.** Section values are validated at startup in the builder, not at parse time (D9).
- **R16.** The flag is read at startup only. Turning it on or off is the Captain's action and needs a restart. Nothing in this slice restarts the vessel.
