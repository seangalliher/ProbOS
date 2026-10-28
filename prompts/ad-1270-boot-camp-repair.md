# AD-1270 (#1324) slice 4b: the AD-638 boot camp repair -- TrustNetwork.get_trust_score (which also repairs /conn), activation moved to finalization, a timeout enforced by construction, crew DMs counted, and the Evaluate/Reflect relaxation behind a default-off flag

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

**Status:** build-ready. Drafted on `4fd31e6c` (`origin/main` `4aa1062f` + the slice-3 contract `8da8da16` + slice 3's M1). It builds after slice 3 and slice 4 merge. No new AD or BF number: this is slice 4b of #1324 (D7). **Captain:** only `boot_camp.relax_quality_gates` being switched on (a weakened control); it ships off and nothing is parked (D9). Overrulable: D2 (no enrolment flag), D5 (crew DMs only), the 4c dispositions in the register.

**Amendment A1 (2026-10-28, after review round 1 of M1+M2 at `31066065`; `claude-architect`).** Repairs the two `gpt-6.1-sol` reviews' findings (`logs/ad1270/review-ad1270b-r1-a.md`, `review-ad1270b-r1-b.md`) in one commit, **R1**, on top of M2 and before M3, by the pairs in §7.16 and the new file §7.17. §7.1 to §7.15 keep their text; where §7.16 differs, §7.16 wins.
- **B1 (P1):** the draft gated activation on BF-034's `runtime.is_cold_start`, which reads the memory object's truthiness (`dreaming.py:262`) and so is false whenever a memory object exists, and Phase 7 builds the coordinator only when one does: M2's activation could not run. D6 now gates it on `_is_new_crew_start` (no previous session record and an empty episode store). BF-034's detector and its readers are unchanged (D11, register R10).
- **A1 (P2):** a `_boot_camp_active` marker set in triage survived into the routed chain's phase 2 after the timeout. Both producers now clear it before asking (D10).
- **A2/B2, A3/B3 (P3):** the expiry docstrings and the activation comment and warning claimed more than the code does; reworded. U2, the `/conn` Absence entry, §13 (3) and R8 said only the Captain reaches `/conn` and that its scope is prompt text; corrected (R8, R11).
- The test-strength gap is folded in: §7.17 drives the real routed entry with AD-639 on, and the ordering test checks the await.

**Captain:** unchanged (D9). Told, overrulable: at the next reset that removes the session record and the episodes, crew below `min_trust_score` are enrolled (bookkeeping and events while the relaxation is off; `boot_camp.enabled: false` turns it off). R1 changes no shared contract (§4, Repair 1).

**Amendment A2 (2026-10-28, after review round 2 of R1 at `8855783b`; `claude-architect`).** Repairs the two round-2 `gpt-6.1-sol` reviews' findings (`logs/ad1270/review-ad1270b-r2-a.md`, `review-ad1270b-r2-b.md`) in one commit, **R2**, on top of R1 and before M3, by the pairs in §7.18. §7.1 to §7.17 keep their text; where §7.18 differs, §7.18 wins. §7.17's docstring sentence "The new-crew cases use a real ``EpisodicMemory`` on ``tmp_path``." is false (only the two finalization cases do); it is not edited in place, because §7.17 records R1's file as built, and P-S6 replaces it in the file.
- **A-F1 (P2):** `_re_reflect_with_feedback` runs the AD-643b feedback Reflect on phase 2a's observation without asking again, so a deadline crossed in phase 2a left the bypass on and AD-639's band unset. The producer becomes one private helper, `CognitiveAgent._refresh_boot_camp_relaxation`, called at both chain entry points and by the feedback Reflect (D10); an AST guard classifies every chain-executing method.
- **B-F1 (P3):** a malformed `get_stats()` answer raised past `_is_new_crew_start`'s own catch; the whole interpretation is inside it now.
- **A-F2, A-F3/B-F2 (P3):** D4's event sentence and the R1 test docstring said more than the code does; reworded. D10, §5, U1, U2 and §14 (9) now name the feedback Reflect.

**Captain:** unchanged (D9). R2 changes no shared contract (§4, Repair 2).

**Re-anchoring after slices 3 and 4 merge:**
- Anchored on slice-3 text: P-T2 (`test_ad1270e1_config_facade.py`, the `1880` line) and P-C2 (the `config-profiles.yaml` census header). Re-anchor both if slice 3's review repair changes those lines.
- Not touched by slices 3 or 4: every other pair (`trust.py`, `crew.py`, `boot_camp.py`, `cognitive_agent.py`, `proactive.py`, `dreaming.py`, the `finalize.py` anchors at `def _wire_boot_camp_tracker` and the BF-261 block, `architecture-baseline.yaml`, `system.yaml` lines 2106-2108, the e2g and AD-1152 tests).
- Regenerate on the real base, never hand-merge: `config-facade-baseline.yaml` and `config-reference.md`. `dormant-class-baseline.yaml` is checked only (4b makes no class live or dormant).
- U1 and U2 follow the standing rule.

**Milestones and tiers:**
- **M1, the trust repair and the flag.** **HIGH**: the shared `TrustNetwork` API and AD-514 protocol conformance, the `/conn` authority path, an agent cognition gate, the config surface.
- **M2, the lifecycle** (activation moved, timeout, DM count, injected clock). **HIGH**: startup order (`finalize.py`, `dreaming.py`), agent-facing lifecycle, the architecture baseline.
- **M3, trackers.** **docs**.

Each milestone is one Builder delegation and one local commit, staged by explicit path, never `git add -A`. `config/system.yaml` may hold the Captain's local edits: stage only P-Y1's hunk. Recommended: one cross-family review (`gpt-6.1-sol`) of the M1+M2 candidate against §14, and one mutation campaign of record on the M2 tree (§10). The broad gate is the orchestrator's single run after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-boot-camp-repair --receipt logs/gates/ad1270-boot-camp-repair.receipt.json`.

**Tests:**
- New: `tests/test_ad1270_boot_camp_trust.py` (M1, 16 cases) and `tests/test_ad1270_boot_camp_lifecycle.py` (M2, 23 cases: the draft predicted 24, the orchestrator measured 23 on its oracle).
- Updated, each with an inline reason: `tests/test_ad1270e2g_crew_models.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1152_agentic_correlation.py`, `tests/test_ad702_diplomatic_relations.py` (docstring only).
- No test reads or writes `%LOCALAPPDATA%\ProbOS\data` or starts a vessel. Every time read in the new tests comes from an injected clock.

**Line endings:** working copies are CRLF (`core.autocrlf=true`). SEARCH blocks are LF: match and write with the file's own endings. New files are written LF.

**Measured by the orchestrator (2026-10-28, on slice 4's head `fec42595`, whose source and tests equal slice 4's merge; the oracle, built by tool, is the scratch refs `ad1270b-oracle-{m1,m1g,m2,trk,trkd}-<tag>`).** All 29 SEARCH/REPLACE pairs apply with 0 failures (M1 12 and the new file 7.5; M2 17 and the new file 7.15; then U1 and U2). Every prediction held except one, corrected above (the lifecycle test file has 23 cases, the draft said 24), and one omission, corrected in §4 step 5 (the facade baseline's top-level `canonical_dump_sha256` also moves). **Tests first:** the new trust file fails 16 of 16 over M1's base (none passes, no collection error); the four updated files over the base fail exactly the six cases §4 predicts (`test_ad1152_agentic_correlation.py` 3, `test_ad1270e1_config_facade.py` 1, `test_ad1270e2g_crew_models.py` 2: 6 failed, 422 passed; 428 passed on the plain base); the lifecycle file fails at collection with `ImportError: cannot import name '_activate_boot_camp_on_cold_start' from 'probos.startup.finalize'`. **M1:** the new file passes 16; M1's 19-file focused list passes 1,090; the five `--check` scripts pass (facade `fields=1881`; profiles `default-OFF flags=227`, census header 451, 227, 224, 85, 142; config reference current; architecture fitness `srp-size=92, layer-import=0, db-connect=30, unowned-task=14`; dormant `160 dormant class(es): 0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant`); the facade diff is 6 lines added and 5 removed and the reference diff is the one new row. **M2:** the lifecycle file passes 23; M2's 22-file focused list passes 743; the architecture and dormant checks pass. **Live facts** (read-only, `%LOCALAPPDATA%\ProbOS\data`, 2026-10-28 05:01Z, probes `probe-bootcamp-live.py` and `probe-bootcamp-live2.py`) are unchanged from the evidence the draft used: 0 cold starts in the six logs (68 stasis recoveries), 0 `AD-639` skip lines, 0 `Slash command failed` lines, and 0 `boot_camp_*` rows in all four retained events stores (258 database files checked). No open PR touched `consensus/trust.py` at 04:03Z. U1's head line and U2's heading were checked against `scripts/gen_ad_ledger.py` `_head_status` (slice 4's register R4): neither holds a status keyword in its first 120 characters, so the regenerated ledger keeps AD-1270 `shipped`.

---

## 0. Premise: what is present on this tree

| Fact | Evidence |
|---|---|
| `TrustNetwork` defines `get_score` only | `consensus/trust.py:1017-1022`; `get_trust_score` exists only as stubs at `boot_camp.py:24` and `protocols.py:76` |
| Production calls `get_trust_score` three times | `boot_camp.py:160`, `:224`, `runtime.py:2116` |
| Activation is dead by startup order | `runtime.py:3162` (Phase 5, `init_dreaming`) runs `startup/dreaming.py:306` (`if cold_start and ... runtime.boot_camp:`). `runtime.boot_camp` is `None` (`runtime.py:1244`) until `runtime.py:3330` (Phase 7), its only assignment |
| The relaxation's consumers | `sub_tasks/evaluate.py:532`, `sub_tasks/reflect.py:449`, `cognitive_agent.py:6058,6246` (AD-639 skipped), `:10481` (AD-683 snapshot), `sub_task.py:722` → `journal.py:467` |
| AD-639 already skips Evaluate and Reflect below trust 0.6 | `config/system.yaml:2134-2136`; `cognitive_agent.py:6068-6069`; `evaluate.py:554-574`; `reflect.py:471` |
| Timeout is never enforced | `check_timeout` (`boot_camp.py:459-465`) has no caller |
| DMs are never counted | `on_agent_dm` (`boot_camp.py:451-457`) has no caller |
| `/conn` raises today | `commands_autonomous.py:91` → `runtime.py:2116` |
| Pinned contracts a new field moves | `test_ad1270e1_config_facade.py:1560-1561`; `test_ad1270e2g_crew_models.py:137-144`; `test_ad1152_agentic_correlation.py:317-324`; `config-profiles.yaml:14-25,624-637` |
| Architecture baseline pins | `architecture-baseline.yaml:1165-1168` (`init_dreaming` `loop.create_task` count 2); `:323-329` (`BootCampCoordinator` srp-size `methods`; body must stay ≤ 500 lines, `check_architecture_principles.py:187`) |
| BF-034's `is_cold_start` cannot be true while a coordinator exists (A1) | `dreaming.py:262` `episodes_empty = not episodic_memory`; `EpisodicMemory` (`episodic.py:1358`, no base class) defines no `__len__` or `__bool__`; Phase 7 builds the coordinator only with a memory object (`runtime.py:3323-3328`). A second veto: `dreaming.py:257-261` compares every record with the generic prior, and AD-640 gives bridge and chief agents other priors before Phase 5 (`agent_onboarding.py:255-265`) |
| A real-boot test with no episodic memory builds no coordinator | `tests/test_bf927_boot_claims.py:545` passes no memory; `runtime.py:3327` |
| AD-502 records whether a crew has served | `startup/cognitive_services.py:583-591`: `session_last.json` present gives `stasis_recovery`, else `first_boot`; written at shutdown (`__main__.py:713`), never created by a failed start (`startup/shutdown.py:880-883`); deleted by reset tier 2 and above, kept by tier 1 (`__main__.py:2654-2662`) |

## 1. Problem

AD-638's boot camp has never enrolled an agent:
- Cold-start activation is scheduled in `startup/dreaming.py` at Phase 5, before the coordinator exists, so its guard is always false.
- Even if it ran, `activate` calls `TrustNetwork.get_trust_score`, which does not exist. The same missing method makes `/conn <callsign>` raise.
- Nothing calls `check_timeout` or `on_agent_dm`, so with `min_dm_conversations: 1` graduation is unreachable and the timeout never fires.
- Once enrolment works, AD-638 auto-approves Evaluate and Reflect for every enrolled agent. That is a weakened control, and today nothing would end it.

## 2. Solution overview

- **M1.** Add `TrustNetwork.get_trust_score`, delegating by call to `get_score`. Add `BootCampConfig.relax_quality_gates: bool = False`. Add `BootCampCoordinator.relaxes_quality_gates`, and make the two chain entry points call it instead of `is_enrolled`. Off, enrolment relaxes nothing and AD-639 runs as today.
- **M2.**
  - Inject a clock into the coordinator.
  - Enforce the timeout on every read.
  - Count crew DMs at `proactive.py:4964`.
  - Move activation into finalization, after the AD-683 late-bind.
  - Delete the dead Phase-5 block and lower its architecture-baseline count.
- **M3.** Trackers.

## 3. Decisions

- **D1.** `get_trust_score` calls `self.get_score(agent_id)`; it is not a class alias, so instance patches of `get_score` (`test_ad1259:1215,1287`, `test_ad1261:114`) apply to both reads. Rejected: renaming the callers and both protocols (5 src sites plus about 13 mocks, and a change to AD-514's shared protocol); changing only `protocols.py:76`.
- **D2.** No enrolment flag. Off, enrolment changes no agent's prompt, chain, trust, memory or authority. `boot_camp.enabled` stays the off switch.
- **D3.** The relaxation is gated at the producer (`relaxes_quality_gates`). `evaluate.py` and `reflect.py` are unchanged. Gating them instead would leave AD-639 suppressed for enrolled agents.
- **D4.**
  - The timeout is enforced by construction: no task.
  - It deletes nothing and touches no trust record, rank or memory. It ends enrolment and emits one `BOOT_CAMP_TIMEOUT`.
  - `_active` becomes False even when nobody remains.
  - The event fires at the first expiring reader after the deadline: `is_active`, `is_enrolled`, `check_graduation`, `on_agent_post`, `on_agent_dm` or `check_timeout`, or `relaxes_quality_gates` while `relax_quality_gates` is on (through `is_enrolled`). `get_state`, and `relaxes_quality_gates` with the flag off, do not expire it (A2).
- **D5.** Crew DMs count; DMs to the Captain and unsent DMs do not. A counting failure is logged at debug (as at `proactive.py:4115`): the DM stands and the timeout bounds the miss.
- **D6 (as amended by A1).**
  - Activation runs once, awaited, in `finalize_startup` after the BF-261 snapshot late-bind, gated on `_is_new_crew_start(runtime)`: `runtime._lifecycle_state` is `first_boot` or `reset` (no previous session record; `finalize.py` already reads `_lifecycle_state` at `:6334`) and `await runtime.episodic_memory.get_stats()` reports `total == 0`. An unreadable count is not a new crew. It does not read BF-034's `runtime.is_cold_start` (§0; register R10), and no reader of that flag changes. The helper keeps its name, `_activate_boot_camp_on_cold_start`.
  - It uses `is_crew_agent` (`crew_utils.py:69`). A stasis recovery and a restart after a recorded session activate nothing. At the next reset that removes the session record and the episodes, crew below `min_trust_score` are enrolled; with the relaxation off that is bookkeeping and events (D2).
  - Log-and-degrade: a failure logs a warning and startup continues. `activate` enrols agent by agent and nothing is rolled back, so a failure part-way can leave some crew enrolled.
- **D7.** No BF: one root cause, one change, already on the #1324 register.
- **D8.** The rest is slice 4c (register R4 to R7).
- **D9.** Captain: only switching `relax_quality_gates` on.
- **D10 (A1, as amended by A2).** The producer owns `_boot_camp_active`. One private helper, `CognitiveAgent._refresh_boot_camp_relaxation`, removes the key, then sets it only on a current true answer from `relaxes_quality_gates`, and otherwise computes AD-639's band for that phase. `_execute_sub_task_chain`, `_execute_chain_with_intent_routing` and `_re_reflect_with_feedback` call it before they run their chain: the AD-643b feedback Reflect reuses phase 2a's observation, so it asks again too (A2). The routed hand-off needs no call of its own: phase 2 and the fallback re-enter `_execute_sub_task_chain`. The routed entry keeps its call, so triage's journal rows record a current answer. The oracle and Ward Room lookups run one QUERY step each and do not ask. Once the relaxation has ended, AD-639's `if not observation.get("_boot_camp_active")` branch runs in the next phase that asks, and the journal's `boot_camp_active` (`sub_task.py:722`) records each step's answer as of its phase's start. Off, the key stays absent, not `False`.
- **D11 (A1).** BF-034's detector is not repaired in this slice. Repairing it switches on the dormant readers listed in R10 at the next reset, with no flag, and one of them is a fresh-start prompt note that nothing clears for the session. The boot camp gets its own predicate; R10 repairs BF-034 and converges it on the same test.

## 4. Milestones

Write each milestone's new test file first and run it on that milestone's base:
- **M1's file:** every case fails by name, with no collection error. The causes are `AttributeError: ... 'get_trust_score'`, `AttributeError: ... 'relax_quality_gates'` or `'relaxes_quality_gates'`, and assertion failures in the protocol and AST cases. Any case that passes on the base is a stop.
- **M2's file:** collection fails with `ImportError: cannot import name '_activate_boot_camp_on_cold_start'`.

Then apply §7.6 (M1's updated tests) on M1's base. Predicted failures:
- `test_ad1270e2g_crew_models.py::test_system_config_dump_is_unchanged_for_the_moved_model[BootCampConfig]`
- `test_ad1270e2g_crew_models.py::test_constructing_with_no_arguments_matches_the_pre_move_dump[BootCampConfig]`
- `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface`
- the `test_ad1152_agentic_correlation.py` cases that reach `_off_observation`, with `KeyError: 'relax_quality_gates'` (slice 3 measured 3)

If any other test fails, stop and report. Never delete or loosen a test. Run focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** | HIGH | 7.1 `consensus/trust.py`; 7.2 `config_models/crew.py`; 7.3 `boot_camp.py` (P-B0); 7.4 `cognitive/cognitive_agent.py`; 7.5 new `tests/test_ad1270_boot_camp_trust.py`; 7.6 four tests; 7.7 `config/system.yaml` (one comment hunk); 7.8 `config-profiles.yaml`; 7.9 generated | `tests/test_ad1270_boot_camp_trust.py tests/test_ad638_boot_camp.py tests/test_ad640_tiered_trust.py tests/test_ad683_ship_state_snapshot.py tests/test_ad702_diplomatic_relations.py tests/test_ad639_chain_tuning.py tests/test_ad632g_cognitive_jit_integration.py tests/test_commands_autonomous.py tests/test_autonomous_operations.py tests/test_ad1259_one_source_of_truth.py tests/test_ad1261_authority_domain.py tests/test_ad1270e2g_crew_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_bf926_config_readers.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py`; then `-P scripts/check_config_facade.py --check`, `-P scripts/check_config_profiles.py --check`, `scripts/gen_config_reference.py --check`, `-P scripts/check_architecture_principles.py --check`, `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M2** | HIGH | 7.10 `boot_camp.py`; 7.11 `proactive.py`; 7.12 `startup/finalize.py`; 7.13 `startup/dreaming.py`; 7.14 `architecture-baseline.yaml`; 7.15 new `tests/test_ad1270_boot_camp_lifecycle.py` | `tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_trust.py tests/test_ad638_boot_camp.py tests/test_ad640_tiered_trust.py tests/test_ad683_ship_state_snapshot.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf874_dm_e2e.py tests/test_bf163_dm_send_flood.py tests/test_ward_room_dms.py tests/test_hebbian_social.py tests/test_bf296_dm_outbound_in_reply.py tests/test_ad1156_plan_mode_reply_tags.py tests/test_ad1229_message_receipts.py tests/test_bf909_proactive_young_clock.py tests/test_bf927_boot_claims.py tests/test_ad1185_config_profiles.py tests/test_finalize.py tests/test_ad1270_working_memory_cognition.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1346_admission_service.py`; then `-P scripts/check_architecture_principles.py --check` and `-P scripts/check_dormant_classes.py --check` |
| **M3** | docs | §8; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

**M1 build order:**
1. Write 7.5 and run it (named failures). Apply 7.6 and run those files (failures as above).
2. Apply 7.1 to 7.4, then 7.7 and 7.8.
3. Measure the census with the instrument. Predicted: 451, 227, 224, 85, 142. Any other change is a stop.
4. Regenerate (7.9): `-P scripts/check_config_facade.py --update-baseline` and `scripts/gen_config_reference.py`.
5. Check the facade diff. Allowed:
   - `BootCampConfig`'s fields (+1) and `schema_sha256`;
   - `SystemConfig`'s `schema_sha256`;
   - `surface_counts.field_definitions` 1880 → 1881 and `canonical_dump_leaves` +1;
   - the top-level `canonical_dump_sha256` (the draft omitted it; the orchestrator measured that it moves, as slice 3's finding B2 recorded).

   Nothing else. The reference diff must show only the new field.
6. Run the focused gate. Commit by explicit path; stage `config/system.yaml` by partial hunk.

**M2 build order:**
1. Write 7.15 and run it (collection fails).
2. Apply 7.10 to 7.14.
3. Run the focused gate. `check_architecture_principles.py --check` must pass: the `init_dreaming` row reads `count: 1`, and `BootCampCoordinator` keeps triggers `[methods]` only. If a `lines` trigger appears, stop and report; do not trim docstrings to fit.
4. Commit by explicit path.

**Repair 1 (A1) build order** (one Builder delegation and one local commit, **R1**, on top of M2 and before M3; **HIGH**; §7.16's pairs and §7.17, written against the files as committed at `31066065`):
1. Write §7.17 and apply P-R6 to P-R9 (the lifecycle test file). Run both files over `31066065`. Predicted: §7.17 has 11 cases, 9 failed and 2 passed (`test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[held]` and `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[stasis-recovery]` are controls). The five `test_a_new_crew_needs_no_session_record_and_no_episodes` cases fail with `ImportError: cannot import name '_is_new_crew_start'` inside each test, not at collection. `[expired-in-triage]` fails with `analysis.markers == [True, True]`, and both reused-observation cases fail on their marker lists. The lifecycle file fails only `test_cold_start_finalization_enrols_crew[cold]`. Any other result, or any case that raises before its assertions, is a stop.
2. Apply P-R1 to P-R5.
3. Focused gate (`-n 0`): `tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_trust.py tests/test_ad638_boot_camp.py tests/test_ad639_chain_tuning.py tests/test_ad632g_cognitive_jit_integration.py tests/test_ad632a_sub_task_foundation.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad666_sensorium.py tests/test_bf206_confab_feedback.py tests/test_bf189_chain_memory_context.py tests/test_ad683_ship_state_snapshot.py tests/test_finalize.py tests/test_bf927_boot_claims.py tests/test_ad1185_config_profiles.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py`; then `-P scripts/check_architecture_principles.py --check` (unchanged: `srp-size=92, layer-import=0, db-connect=30, unowned-task=14`; no method is added to any class) and `-P scripts/check_dormant_classes.py --check` (paste its whole output).
4. Commit by explicit path: `src/probos/cognitive/cognitive_agent.py`, `src/probos/boot_camp.py`, `src/probos/startup/finalize.py`, `tests/test_ad1270_boot_camp_lifecycle.py`, `tests/test_ad1270_boot_camp_repair_a1.py`.

R1 changes no shared contract: no public signature or return shape, persisted schema, config field, event type or payload, wire shape, or gate or tooling script. `_is_new_crew_start` is module-private, `_boot_camp_active` keeps its shape and meaning, and the journal column is unchanged. Round 2 reviews the R1 delta.

**Repair 2 (A2) build order** (one Builder delegation and one local commit, **R2**, on top of R1 `8855783b` and before M3; **HIGH**; §7.18's pairs, written against the files as committed at `8855783b`):
1. Apply P-S6 to P-S11 (the two test files). Run `tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py` (`-n 0`) over R1's source. Predicted: 33 cases, 5 failed, 28 passed. Failures: `test_the_feedback_reflection_asks_again_after_phase_two[expired-before-feedback]` (on `assert "_boot_camp_active" not in observation`, after its premises pass); `test_a_malformed_stats_answer_is_not_a_new_crew[none]`, `[list]`, `[int]` (each `AttributeError: '<type>' object has no attribute 'get'` raised from `_is_new_crew_start`); `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` (on the `_refresh_boot_camp_relaxation` assertion for a gating method; the classification assertion before it passes). Controls that pass: `[held]` and `[no-total]`. Any other result is a stop.
2. Apply P-S1 to P-S5.
3. Focused gate (`-n 0`): R1's list (§4, Repair 1, step 3) plus `tests/test_trigger_learning.py tests/test_ad643a_intent_routing.py tests/test_bf688_chain_priority_inheritance.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad632d_compose_handler.py tests/test_bf922_fallback_gate.py tests/test_bf922_output_grounding.py tests/test_bf921_counselor_event_delivery.py`. `test_trigger_learning.py::TestReReflect` passes unchanged (its agent is a `MagicMock`, so the helper call is a mock call). Then `-P scripts/check_architecture_principles.py --check` (unchanged: `srp-size=92, layer-import=0, db-connect=30, unowned-task=14`; `CognitiveAgent` gains one method and keeps `[lines, methods]`, all its row records) and `-P scripts/check_dormant_classes.py --check` (paste its whole output).
4. Commit by explicit path: `src/probos/cognitive/cognitive_agent.py`, `src/probos/startup/finalize.py`, `tests/test_ad1270_boot_camp_repair_a1.py`, `tests/test_ad1270_boot_camp_trust.py`.

R2 changes no shared contract: `_refresh_boot_camp_relaxation` is private to `CognitiveAgent` and `_is_new_crew_start` to `finalize.py`, with the same bool return; `_boot_camp_active`, `_chain_trust_band` and the journal columns keep their shape and meaning; the AST test it renames is this slice's own, referenced only by this contract and its census. Round 3 reviews the R2 delta.

## 5. Consumers of every value this adds or changes

| Value | Consumers | Effect |
|---|---|---|
| `TrustNetwork.get_trust_score` | `boot_camp.py:160,224`, `runtime.py:2116` | from AttributeError to the `get_score` value |
| `boot_camp.relax_quality_gates` | `BootCampCoordinator.relaxes_quality_gates` only; `config-reference.md`; `config-profiles.yaml` row | new, default off |
| `BootCampCoordinator.relaxes_quality_gates` | `CognitiveAgent._refresh_boot_camp_relaxation` only (A2), called by `_execute_sub_task_chain`, `_execute_chain_with_intent_routing` and `_re_reflect_with_feedback` | new public method |
| `_boot_camp_active` (observation key) | evaluate, reflect, AD-639 skip, AD-683 injection, journal | set only when the flag is on (was: on enrolment); A1 and A2: one producer helper removes it before it asks, at both chain entry points and the AD-643b feedback Reflect, so phase 2, the fallback and the feedback Reflect ask again. The AD-683 injection also reads it when a chain falls through to the single call (R6) |
| `BootCampCoordinator(clock=...)` | tests; `runtime.py:3330` (default) | new keyword-only argument |
| Reads after the timeout | `is_active`, `is_enrolled`, `check_graduation`, `on_agent_post`, `on_agent_dm`, `check_timeout`; `relaxes_quality_gates` only when the flag is on (off, it returns before `is_enrolled`); not `get_state` | enrolment ends; one `BOOT_CAMP_TIMEOUT` |
| `force_graduate_all` with nobody remaining | `test_ad638` timeout tests | now also sets `_active=False` |
| Crew DM count | `on_agent_dm` from `proactive.py` | new caller |
| `_activate_boot_camp_on_cold_start` | `finalize_startup` | new; activates when `_is_new_crew_start` is true (A1). A test boot activates only when it passes an episodic memory, enables the Ward Room (`runtime.py:3323-3328`) and boots a fresh data directory |
| `_is_new_crew_start` (A1) | `_activate_boot_camp_on_cold_start` only | new, module-private; reads `runtime._lifecycle_state` and `episodic_memory.get_stats()`. BF-034's `is_cold_start` and its readers are unchanged |
| `init_dreaming` | `architecture-baseline.yaml` row | one fewer bare task |

## 6. Tests

**M1, `tests/test_ad1270_boot_camp_trust.py`** (real `TrustNetwork` throughout; nothing mocks the method under repair):
- `test_trust_network_satisfies_the_trust_protocol`
- `test_get_trust_score_is_get_score[unknown-agent]`, `test_get_trust_score_is_get_score[recorded-agent]`
- `test_get_trust_score_follows_a_patched_get_score`
- `test_activate_with_the_real_trust_network_enrols_crew_and_skips_chiefs`
- `test_graduation_reads_the_real_trust_network`
- `test_conn_goes_to_a_qualified_chief_through_the_real_trust_network`: crosses `cmd_conn` → `ProbOSRuntime.is_conn_qualified` → `TrustNetwork` → `ConnManager.grant_conn`
- `test_conn_is_refused_below_commander`
- `test_the_relaxation_is_off_by_default`
- `test_an_enrolled_agent_relaxes_only_when_the_flag_is_on[off]`, `test_an_enrolled_agent_relaxes_only_when_the_flag_is_on[on]`
- `test_an_agent_not_enrolled_never_relaxes[unknown]`, `test_an_agent_not_enrolled_never_relaxes[graduated]`
- `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[on]`: crosses coordinator → `CognitiveAgent._execute_sub_task_chain`
- `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` (AST; A2 renamed and widened it: every method that executes a sub-task chain is a gating phase that calls the producer helper or a QUERY-only lookup)

**M2, `tests/test_ad1270_boot_camp_lifecycle.py`** (injected clock; real `TrustNetwork`):
- timeout:
  - `test_nobody_is_enrolled_past_the_timeout[just-before]`, `test_nobody_is_enrolled_past_the_timeout[at]`
  - `test_is_active_turns_false_at_the_timeout`
  - `test_the_timeout_emits_one_event_and_graduates_the_rest`
  - `test_the_timeout_ends_the_relaxation`
  - `test_the_timeout_changes_no_trust_record_and_forgets_nobody`
  - `test_activity_past_the_timeout_is_not_counted[post]`, `test_activity_past_the_timeout_is_not_counted[dm]`
  - `test_check_graduation_past_the_timeout_reports_graduated`
  - `test_the_timeout_with_nobody_enrolled_ends_boot_camp`
  - `test_reads_before_activation_are_safe`
  - `test_check_timeout_still_ends_boot_camp`
- clock:
  - `test_graduation_waits_for_min_time_on_the_injected_clock`
  - `test_the_coordinator_reads_time_only_through_its_clock` (AST)
- DM path (BF-874 rig, real `WardRoomService` on `tmp_path`):
  - `test_a_crew_dm_through_the_proactive_path_is_counted`
  - `test_a_dm_to_the_captain_is_not_counted`
  - `test_an_unsent_dm_is_not_counted`
  - `test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust`: crosses the DM path → coordinator → real trust → graduation event
- activation:
  - `test_cold_start_finalization_enrols_crew[cold]`, `test_cold_start_finalization_enrols_crew[warm]`
  - `test_no_coordinator_or_no_crew_means_no_activation`
  - `test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind` (AST)
  - `test_phase_5_no_longer_tries_to_activate_the_boot_camp` (AST)

**Amendment A1, `tests/test_ad1270_boot_camp_repair_a1.py`** (11 cases at R1, 17 after A2; real `CognitiveAgent`, `SubTaskExecutor`, `EvaluateHandler` and `ReflectHandler` with AD-639 on; injected clock; real `TrustNetwork`; a real `EpisodicMemory` on `tmp_path` in the two finalization cases only):
- `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[held]`, `[expired-in-triage]`: crosses the routed entry, triage, the timeout, phase 2 and the real Evaluate and Reflect handlers
- `test_each_chain_entry_asks_again_on_a_reused_observation[direct]`, `[routed]`
- `test_a_new_crew_needs_no_session_record_and_no_episodes[first-boot]`, `[reset]`, `[stasis-recovery]`, `[episodes]`, `[count-raises]`
- `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[first-boot]`, `[stasis-recovery]`: crosses a real, started, empty `EpisodicMemory` (truthy, so BF-034 calls it warm), `_is_new_crew_start`, `_activate_boot_camp_on_cold_start` and enrolment, with `is_cold_start=False` as production reports it

**Updated by A1 in `tests/test_ad1270_boot_camp_lifecycle.py`** (still 23 cases): the module docstring; `_startup_runtime` (a new crew, not `is_cold_start`) and its three call sites; `test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind` also checks the await.

**Added by A2 in `tests/test_ad1270_boot_camp_repair_a1.py`** (6 cases):
- `test_the_feedback_reflection_asks_again_after_phase_two[held]`, `[expired-before-feedback]`: crosses the routed entry, phase 2a, AD-643b's undeclared-action detection and the feedback Reflect through the real `ReflectHandler`, with the deadline passing in phase 2a
- `test_a_malformed_stats_answer_is_not_a_new_crew[none]`, `[list]`, `[int]`, `[no-total]`

**Updated by A2 in `tests/test_ad1270_boot_camp_trust.py`** (still 16 cases): the AST case, renamed and widened (above).

## 7. The contract

### 7.1 `src/probos/consensus/trust.py` (M1)

**Pair P-T1 (`src/probos/consensus/trust.py`).** SEARCH:
```
    def get_score(self, agent_id: AgentID) -> float:
        """Get an agent's current trust score (BF-907: a sovereign identity reads its slot)."""
        record = self._records.get(self._canonical_key(agent_id))
        if record is None:
            return self.prior_alpha / (self.prior_alpha + self.prior_beta)
        return record.score

    def get_record(self, agent_id: AgentID) -> TrustRecord | None:
```
REPLACE:
```
    def get_score(self, agent_id: AgentID) -> float:
        """Get an agent's current trust score (BF-907: a sovereign identity reads its slot)."""
        record = self._records.get(self._canonical_key(agent_id))
        if record is None:
            return self.prior_alpha / (self.prior_alpha + self.prior_beta)
        return record.score

    def get_trust_score(self, agent_id: AgentID) -> float:
        """The ``TrustNetworkProtocol`` name for :meth:`get_score` (AD-1270, #1324).

        ``protocols.TrustNetworkProtocol`` and the AD-638 coordinator declare this
        name; the boot camp and ``/conn`` call it. It calls ``get_score`` rather than
        aliasing it, so a patched ``get_score`` governs both reads.
        """
        return self.get_score(agent_id)

    def get_record(self, agent_id: AgentID) -> TrustRecord | None:
```

### 7.2 `src/probos/config_models/crew.py` (M1)

**Pair P-K1 (`src/probos/config_models/crew.py`).** SEARCH:
```
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600


class ShipStateSnapshotConfig(BaseModel):
```
REPLACE:
```
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600
    # AD-1270 (#1324): AD-638's Evaluate/Reflect auto-approval for enrolled crew. Off,
    # enrolment relaxes nothing. On weakens the anti-confabulation gate: the Captain's switch.
    relax_quality_gates: bool = False


class ShipStateSnapshotConfig(BaseModel):
```

### 7.3 `src/probos/boot_camp.py` (M1)

**Pair P-B0 (`src/probos/boot_camp.py`).** SEARCH:
```
    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        state = self._agents.get(agent_id)
        return state is not None and not state.graduated
```
REPLACE:
```
    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        state = self._agents.get(agent_id)
        return state is not None and not state.graduated

    def relaxes_quality_gates(self, agent_id: str) -> bool:
        """AD-1270 (#1324): True only while enrolled AND ``relax_quality_gates`` is on.

        The chain reads this, not ``is_enrolled``. Off (the default), an enrolled
        agent's Evaluate, Reflect and AD-639 tuning run as for any other agent.
        """
        return self._config.relax_quality_gates and self.is_enrolled(agent_id)
```

### 7.4 `src/probos/cognitive/cognitive_agent.py` (M1)

**Pair P-A1 (`src/probos/cognitive/cognitive_agent.py`).** SEARCH:
```
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True
```
REPLACE:
```
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):
            observation["_boot_camp_active"] = True
```

**Pair P-A2 (`src/probos/cognitive/cognitive_agent.py`).** SEARCH:
```
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True
```
REPLACE:
```
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):
            observation["_boot_camp_active"] = True
```

### 7.5 New file: `tests/test_ad1270_boot_camp_trust.py` (M1)

```python
"""AD-1270 (#1324) slice 4b, M1: the AD-638 boot camp and /conn read trust through the real TrustNetwork.

TrustNetwork had ``get_score`` only, while ``protocols.TrustNetworkProtocol`` and the
coordinator's own protocol declare ``get_trust_score``; every earlier test mocked the
missing method. Nothing here mocks it: each case uses a real ``TrustNetwork``.
"""

from __future__ import annotations

import ast
import io
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskChain, SubTaskResult, SubTaskSpec, SubTaskType
from probos.config import BootCampConfig, ChainTuningConfig, SystemConfig
from probos.conn import ConnManager
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.experience.commands import commands_autonomous
from probos.protocols import TrustNetworkProtocol
from probos.runtime import ProbOSRuntime

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"

CHIEF = {"agent_id": "chief-1", "callsign": "Worf", "department": "security"}
CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}


class _Episodes:
    """The coordinator's episode-count collaborator (not under repair)."""

    def __init__(self, count: int) -> None:
        self.count = count

    async def count_for_agent(self, agent_id: str) -> int:
        return self.count


def _coordinator(trust: TrustNetwork, *, events: list | None = None, **config: object) -> BootCampCoordinator:
    settings = {"min_time_minutes": 0, "nudge_cooldown_seconds": 0, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        ward_room=SimpleNamespace(),
        trust_service=trust,
        episodic_memory=_Episodes(10),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
    )


# --- the method under repair -------------------------------------------------------------


def test_trust_network_satisfies_the_trust_protocol() -> None:
    """AD-514's runtime-checkable protocol; closes the gap test_ad702 recorded."""
    assert isinstance(TrustNetwork(), TrustNetworkProtocol)


@pytest.mark.parametrize("alpha_beta", [None, (3.0, 1.0)], ids=["unknown-agent", "recorded-agent"])
def test_get_trust_score_is_get_score(alpha_beta: tuple[float, float] | None) -> None:
    trust = TrustNetwork()
    if alpha_beta is not None:
        trust.create_with_prior("agent-x", *alpha_beta)

    assert trust.get_trust_score("agent-x") == trust.get_score("agent-x")
    assert trust.get_trust_score("agent-x") == pytest.approx(0.5 if alpha_beta is None else 0.75)


def test_get_trust_score_follows_a_patched_get_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegation by call, not a class alias: a patched get_score governs both reads."""
    trust = TrustNetwork()
    monkeypatch.setattr(trust, "get_score", lambda agent_id: 0.123)

    assert trust.get_trust_score("anyone") == 0.123


# --- the boot camp through the real trust network ----------------------------------------


@pytest.mark.asyncio
async def test_activate_with_the_real_trust_network_enrols_crew_and_skips_chiefs() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CHIEF["agent_id"], 3.0, 1.0)  # 0.75, the AD-640 chief tier
    events: list = []
    coord = _coordinator(trust, events=events)

    await coord.activate([CHIEF, CREW])

    assert coord.is_enrolled(CREW["agent_id"])
    assert not coord.is_enrolled(CHIEF["agent_id"])  # AD-640: 0.75 >= min_trust_score 0.55
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED]


@pytest.mark.asyncio
async def test_graduation_reads_the_real_trust_network() -> None:
    trust = TrustNetwork()
    events: list = []
    coord = _coordinator(trust, events=events)
    await coord.activate([CREW])
    crew = CREW["agent_id"]
    for _ in range(3):
        await coord.on_agent_post(crew, "department")
    await coord.on_agent_dm(crew)

    assert coord.is_enrolled(crew)  # every criterion met except trust: 0.5 < 0.55

    trust.create_with_prior(crew, 3.0, 2.0)  # 0.6
    await coord.on_agent_post(crew, "department")

    assert not coord.is_enrolled(crew)
    graduations = [data for event_type, data in events if event_type == EventType.BOOT_CAMP_GRADUATION]
    assert [g["agent_id"] for g in graduations] == [crew]
    assert graduations[0]["trust_score"] == pytest.approx(0.6)


# --- /conn through the real trust network ------------------------------------------------


def _conn_host(trust: TrustNetwork) -> SimpleNamespace:
    """A runtime stand-in carrying the real ProbOSRuntime.is_conn_qualified (BF-708 pattern)."""
    chief = SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf")
    junior = SimpleNamespace(id="engineering_officer-0", agent_type="engineering_officer", callsign="Reed")
    agents = {agent.id: agent for agent in (chief, junior)}
    posts = {  # both hold conn-eligible posts: only trust tells them apart
        "security_officer": SimpleNamespace(id="chief_security"),
        "engineering_officer": SimpleNamespace(id="chief_engineer"),
    }
    host = SimpleNamespace(
        registry=SimpleNamespace(get=agents.get, all=lambda: list(agents.values())),
        trust_network=trust,
        ontology=SimpleNamespace(get_post_for_agent=posts.get),
        conn_manager=ConnManager(),
        ward_room=None,
    )
    host.is_conn_qualified = types.MethodType(ProbOSRuntime.is_conn_qualified, host)
    return host


@pytest.mark.asyncio
async def test_conn_goes_to_a_qualified_chief_through_the_real_trust_network() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("security_officer-0", 9.0, 1.0)  # 0.9: Senior
    host = _conn_host(trust)
    out = io.StringIO()

    await commands_autonomous.cmd_conn(host, Console(file=out, width=200), "Worf")

    assert host.conn_manager.is_active
    assert host.conn_manager.holder == "Worf"
    assert "has the conn" in out.getvalue()


@pytest.mark.asyncio
async def test_conn_is_refused_below_commander() -> None:
    host = _conn_host(TrustNetwork())  # Reed reads the 0.5 prior: Lieutenant
    out = io.StringIO()

    await commands_autonomous.cmd_conn(host, Console(file=out, width=200), "Reed")

    assert not host.conn_manager.is_active
    assert "not qualified" in out.getvalue()


# --- the relaxation flag ------------------------------------------------------------------


def test_the_relaxation_is_off_by_default() -> None:
    assert BootCampConfig().relax_quality_gates is False
    assert SystemConfig().boot_camp.relax_quality_gates is False


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True], ids=["off", "on"])
async def test_an_enrolled_agent_relaxes_only_when_the_flag_is_on(flag: bool) -> None:
    coord = _coordinator(TrustNetwork(), relax_quality_gates=flag)
    await coord.activate([CREW])

    assert coord.is_enrolled(CREW["agent_id"])
    assert coord.relaxes_quality_gates(CREW["agent_id"]) is flag


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown", "graduated"])
async def test_an_agent_not_enrolled_never_relaxes(case: str) -> None:
    coord = _coordinator(TrustNetwork(), relax_quality_gates=True)
    await coord.activate([CREW])
    agent_id = CREW["agent_id"]
    if case == "unknown":
        agent_id = "not-enrolled"
    else:
        await coord.force_graduate_all()

    assert coord.relaxes_quality_gates(agent_id) is False


def _chain_agent(coord: BootCampCoordinator) -> CognitiveAgent:
    """The AD-632g harness (tests/test_ad632g_cognitive_jit_integration.py:212-223), real coordinator."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = CREW["agent_id"]
    agent.agent_type = "test_agent"
    agent._sub_task_executor = MagicMock()
    agent._sub_task_executor.enabled = True
    agent._sub_task_executor.execute = AsyncMock(return_value=[SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE, name="compose", success=True,
        result={"output": "Hello"}, tier_used="standard",
    )])
    agent._runtime = MagicMock()
    agent._runtime.cognitive_journal = MagicMock()
    agent._runtime.boot_camp = coord
    agent._runtime.config.chain_tuning = ChainTuningConfig(enabled=False)
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True], ids=["off", "on"])
async def test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on(flag: bool) -> None:
    settings = {"relax_quality_gates": True} if flag else {}  # off uses the model default
    coord = _coordinator(TrustNetwork(), **settings)
    await coord.activate([CREW])
    observation: dict = {"intent": "ward_room_notification"}
    chain = SubTaskChain(steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose")])

    await _chain_agent(coord)._execute_sub_task_chain(chain, observation)

    assert observation.get("_boot_camp_active") is (True if flag else None)


def _attribute_calls(node: ast.AST) -> list[str]:
    return [
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]


def test_both_chain_entry_points_ask_for_the_relaxation_not_enrolment() -> None:
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    wanted = {"_execute_sub_task_chain", "_execute_chain_with_intent_routing"}
    entry_points = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted
    }

    assert set(entry_points) == wanted
    for name, node in entry_points.items():
        assert "relaxes_quality_gates" in _attribute_calls(node), name
    assert "is_enrolled" not in _attribute_calls(tree)
```

### 7.6 Updated tests (M1)

**Pair P-T2 (`tests/test_ad1270e1_config_facade.py`).** SEARCH:
```
    # AD-1270 (#1324) slice 3 adds working_memory.cognition_enabled (1879 -> 1880).
    assert counts["field_definitions"] == 1880  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1270 (#1324) slice 3 adds working_memory.cognition_enabled (1879 -> 1880).
    # AD-1270 (#1324) slice 4b adds boot_camp.relax_quality_gates (1880 -> 1881).
    assert counts["field_definitions"] == 1881  # AD-1206 intentionally adds github_repository.
```

**Pair P-T3 (`tests/test_ad1270e2g_crew_models.py`).** SEARCH:
```
    'BootCampConfig': {   'enabled': True,
                          'min_episodes': 5,
                          'min_ward_room_posts': 3,
                          'min_dm_conversations': 1,
                          'min_trust_score': 0.55,
                          'min_time_minutes': 60,
                          'timeout_minutes': 120,
                          'nudge_cooldown_seconds': 600},
```
REPLACE:
```
    'BootCampConfig': {   'enabled': True,
                          'min_episodes': 5,
                          'min_ward_room_posts': 3,
                          'min_dm_conversations': 1,
                          'min_trust_score': 0.55,
                          'min_time_minutes': 60,
                          'timeout_minutes': 120,
                          'nudge_cooldown_seconds': 600,
                          # AD-1270 (#1324) slice 4b added this default-off flag after the
                          # move; every other key is still the pre-move dump.
                          'relax_quality_gates': False},
```

**Pair P-T4 (`tests/test_ad1152_agentic_correlation.py`).** SEARCH:
```
    runtime = _local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(lambda event: events.append(_snapshot(event)), LOOP_EVENTS)
    unrelated: list[dict[str, Any]] = []
```
REPLACE:
```
    # AD-1270 (#1324) slice 4b's boot-camp relaxation flag was added after this capture too. It is
    # default off, and while off no agent's Evaluate or Reflect is relaxed; this observation runs no chain.
    assert config["boot_camp"].pop("relax_quality_gates") is False
    runtime = _local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(lambda event: events.append(_snapshot(event)), LOOP_EVENTS)
    unrelated: list[dict[str, Any]] = []
```

**Pair P-T5 (`tests/test_ad702_diplomatic_relations.py`).** SEARCH:
```
    The widened ``TrustNetworkProtocol`` requires these methods. We do not
    use ``isinstance(net, TrustNetworkProtocol)`` here because the existing
    Protocol also declares ``get_trust_score`` which TrustNetwork does not
    implement (pre-existing gap predating AD-702; tracked separately).
    """
```
REPLACE:
```
    The widened ``TrustNetworkProtocol`` requires these methods. AD-1270 (#1324)
    slice 4b closed the ``get_trust_score`` gap this docstring used to record;
    tests/test_ad1270_boot_camp_trust.py pins the protocol isinstance.
    """
```

### 7.7 `config/system.yaml` (M1; one comment hunk, staged by partial hunk)

**Pair P-Y1 (`config/system.yaml`).** SEARCH:
```
  nats_payload_max_bytes: 16384
boot_camp:
  enabled: true
```
REPLACE:
```
  nats_payload_max_bytes: 16384
# AD-1270 (#1324): relax_quality_gates (default false, absent here) auto-approves Evaluate and Reflect for
# enrolled cold-start crew until they graduate or time out. A weakened control: only the Captain sets it.
boot_camp:
  enabled: true
```

### 7.8 `docs/development/config-profiles.yaml` (M1)

**Pair P-C1 (`docs/development/config-profiles.yaml`).** SEARCH:
```
ci_divergences:
- id: nats-forced-off-in-tests
```
REPLACE:
```
- path: boot_camp.relax_quality_gates
  kind: research-treatment
  profiles: []
  evidence_to_promote: tests/test_ad1270_boot_camp_trust.py::test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on
    -- OFF, an enrolled cold-start agent's Evaluate, Reflect and AD-639 tuning run as for any other agent.
    Arming it auto-approves the anti-confabulation gate for enrolled crew until they graduate or the boot
    camp times out, a weakened control, so no profile arms it; supported cannot (research-treatment). The
    Captain decides, after a live cold start shows graduation and timeout events (AD-1270 slice 4b).
  external_dependency: null
  requires: []
  conflicts_with: []
ci_divergences:
- id: nats-forced-off-in-tests
```

**Pair P-C2 (`docs/development/config-profiles.yaml`).** Re-anchor if slice 3 changes this header. Figures are predicted: write the instrument's measured values. SEARCH:
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
REPLACE:
```
  measured_at_commit: AD-1270 (issue 1324) slice 4b M1 on the slice-4 merge, every count re-measured with
    this instrument (slice 4b adds boot_camp.relax_quality_gates, a default-False boolean no tracked
    config arms; slice 3 measured 450, 226, 224, 85 and 141)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 451
  default_false: 227
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 142
```

### 7.9 Generated files (M1; no pairs)

- `docs/development/config-facade-baseline.yaml`: `-P scripts/check_config_facade.py --update-baseline` (allowed diff in §4 M1 step 5).
- `docs/development/config-reference.md`: `scripts/gen_config_reference.py`.

### 7.10 `src/probos/boot_camp.py` (M2)

**Pair P-L1 (`src/probos/boot_camp.py`).** SEARCH:
```
        emit_event_fn: Callable[..., Any] | None = None,
        *,
        ship_state_builder: Any | None = None,  # AD-683: ShipStateSnapshotBuilder | None
    ) -> None:
        self._config = config
```
REPLACE:
```
        emit_event_fn: Callable[..., Any] | None = None,
        *,
        ship_state_builder: Any | None = None,  # AD-683: ShipStateSnapshotBuilder | None
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        # AD-1270 (#1324): every time read goes through the clock, so tests need no wall time.
        self._clock = clock
```

**Pair P-L2 (`src/probos/boot_camp.py`).** SEARCH:
```
    @property
    def is_active(self) -> bool:
        """True while boot camp is in progress."""
        return self._active
```
REPLACE:
```
    @property
    def is_active(self) -> bool:
        """True while boot camp is in progress."""
        self._expire_if_timed_out()  # AD-1270: is_active is False once the timeout passes
        return self._active
```

**Pair P-L3 (`src/probos/boot_camp.py`).** SEARCH:
```
    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        state = self._agents.get(agent_id)
```
REPLACE:
```
    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        self._expire_if_timed_out()  # AD-1270: nobody is enrolled past the timeout
        state = self._agents.get(agent_id)
```

**Pair P-L4 (`src/probos/boot_camp.py`).** SEARCH:
```
        self._active = True
        self._started_at = time.time()
```
REPLACE:
```
        self._active = True
        self._started_at = self._clock()
```

**Pair P-L5 (`src/probos/boot_camp.py`).** SEARCH:
```
            self._agents[agent_id] = AgentBootCampState(
                agent_id=agent_id,
                callsign=callsign,
                department=agent_info.get("department", ""),
            )
```
REPLACE:
```
            self._agents[agent_id] = AgentBootCampState(
                agent_id=agent_id,
                callsign=callsign,
                department=agent_info.get("department", ""),
                enrolled_at=self._started_at,
            )
```

**Pair P-L6 (`src/probos/boot_camp.py`).** SEARCH:
```
        """Check if agent meets graduation criteria."""
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return True

        # Time gate
        elapsed_min = (time.time() - state.enrolled_at) / 60
```
REPLACE:
```
        """Check if agent meets graduation criteria."""
        self._expire_if_timed_out()  # AD-1270: a timed-out agent is already graduated
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return True

        # Time gate
        elapsed_min = (self._clock() - state.enrolled_at) / 60
```

**Pair P-L7 (`src/probos/boot_camp.py`).** SEARCH:
```
    async def force_graduate_all(self) -> None:
        """Force-graduate all remaining agents (timeout)."""
        remaining = [
            s for s in self._agents.values() if not s.graduated
        ]
        if not remaining:
            return

        agent_ids = []
        for state in remaining:
            state.graduated = True
            state.graduated_at = time.time()
            state.phase = 4
            agent_ids.append(state.agent_id)

        elapsed_min = 0.0
        if self._started_at:
            elapsed_min = (time.time() - self._started_at) / 60

        self._active = False
```
REPLACE:
```
    async def force_graduate_all(self) -> None:
        """Force-graduate all remaining agents (timeout)."""
        self._graduate_remaining_on_timeout()

    def _graduate_remaining_on_timeout(self) -> None:
        """AD-1270 (#1324): end boot camp; mark each remaining agent graduated, once.

        Deletes nothing and touches no trust record, rank or memory.
        """
        self._active = False  # AD-1270: ends even when nobody is left to graduate
        remaining = [
            s for s in self._agents.values() if not s.graduated
        ]
        if not remaining:
            return

        now = self._clock()
        agent_ids = []
        for state in remaining:
            state.graduated = True
            state.graduated_at = now
            state.phase = 4
            agent_ids.append(state.agent_id)

        elapsed_min = 0.0
        if self._started_at:
            elapsed_min = (now - self._started_at) / 60
```

**Pair P-L8 (`src/probos/boot_camp.py`).** SEARCH:
```
        """Track agent activity for graduation criteria."""
        state = self._agents.get(agent_id)
```
REPLACE:
```
        """Track agent activity for graduation criteria."""
        self._expire_if_timed_out()  # AD-1270: no post is counted past the timeout
        state = self._agents.get(agent_id)
```

**Pair P-L9 (`src/probos/boot_camp.py`).** SEARCH:
```
        """Track DM activity for graduation criteria."""
        state = self._agents.get(agent_id)
```
REPLACE:
```
        """Track DM activity for graduation criteria."""
        self._expire_if_timed_out()  # AD-1270: no DM is counted past the timeout
        state = self._agents.get(agent_id)
```

**Pair P-L10 (`src/probos/boot_camp.py`).** SEARCH:
```
    async def check_timeout(self) -> None:
        """Check if boot camp has exceeded its timeout."""
        if not self._active or not self._started_at:
            return
        elapsed_seconds = time.time() - self._started_at
        if elapsed_seconds >= self._config.timeout_minutes * 60:
            await self.force_graduate_all()
```
REPLACE:
```
    async def check_timeout(self) -> None:
        """Check if boot camp has exceeded its timeout."""
        self._expire_if_timed_out()

    def _expire_if_timed_out(self) -> None:
        """AD-1270 (#1324): enforce ``timeout_minutes`` by construction, with no task.

        Every public reader and tracker calls this first, so nothing can observe an
        enrolment, or a relaxation, past the timeout.
        """
        if not self._active or self._started_at is None:
            return
        if self._clock() - self._started_at >= self._config.timeout_minutes * 60:
            self._graduate_remaining_on_timeout()
```

**Pair P-L11 (`src/probos/boot_camp.py`).** SEARCH:
```
        state.graduated = True
        state.graduated_at = time.time()
        state.phase = 4

        elapsed_min = (state.graduated_at - state.enrolled_at) / 60
```
REPLACE:
```
        state.graduated = True
        state.graduated_at = self._clock()
        state.phase = 4

        elapsed_min = (state.graduated_at - state.enrolled_at) / 60
```

**Pair P-L12 (`src/probos/boot_camp.py`).** SEARCH:
```
        last = self._nudge_cooldowns.get(agent_id, 0.0)
        return (time.time() - last) >= self._config.nudge_cooldown_seconds

    def _record_nudge(self, agent_id: str) -> None:
        """Record nudge timestamp."""
        self._nudge_cooldowns[agent_id] = time.time()
```
REPLACE:
```
        last = self._nudge_cooldowns.get(agent_id, 0.0)
        return (self._clock() - last) >= self._config.nudge_cooldown_seconds

    def _record_nudge(self, agent_id: str) -> None:
        """Record nudge timestamp."""
        self._nudge_cooldowns[agent_id] = self._clock()
```

### 7.11 `src/probos/proactive.py` (M2)

**Pair P-D1 (`src/probos/proactive.py`).** SEARCH:
```
                logger.info("AD-453: %s sent DM to @%s", sender_callsign or agent.agent_type, target_callsign)

                # Record Hebbian social connection
```
REPLACE:
```
                logger.info("AD-453: %s sent DM to @%s", sender_callsign or agent.agent_type, target_callsign)

                # AD-1270 (#1324): a crew DM counts toward AD-638 graduation. Bookkeeping only:
                # a failure is logged and the DM stands (the boot-camp timeout bounds the miss).
                _boot_camp = getattr(rt, "boot_camp", None)
                if _boot_camp is not None:
                    try:
                        await _boot_camp.on_agent_dm(agent.id)
                    except Exception:
                        logger.debug("AD-1270: boot-camp DM tracking failed for %s", sender_label, exc_info=True)

                # Record Hebbian social connection
```

### 7.12 `src/probos/startup/finalize.py` (M2)

**Pair P-F1 (`src/probos/startup/finalize.py`).** SEARCH:
```
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
```
REPLACE:
```
async def _activate_boot_camp_on_cold_start(*, runtime: Any) -> bool:
    """AD-1270 (#1324): enrol cold-start crew in the AD-638 boot camp.

    Moved from ``startup/dreaming.py``, which runs at Phase 5, before the coordinator
    exists (Phase 7), so it never ran. Called after the AD-683 snapshot late-bind.
    Returns True when ``activate`` ran; a warm boot or no coordinator does nothing.
    """
    coordinator = getattr(runtime, "boot_camp", None)
    if coordinator is None or not runtime.is_cold_start:
        return False
    from probos.cognitive.standing_orders import get_department

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [
        {
            "agent_id": agent.id,
            "callsign": getattr(agent, "callsign", "") or agent.agent_type,
            "department": getattr(agent, "department", "") or get_department(agent.agent_type) or "unassigned",
        }
        for agent in runtime.registry.all()
        if is_crew_agent(agent, ontology)
    ]
    if not crew_agents:
        return False
    await coordinator.activate(crew_agents)
    return True


def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
```

**Pair P-F2 (`src/probos/startup/finalize.py`).** SEARCH:
```
        _bc = getattr(runtime, "boot_camp", None)
        if _bc is not None and getattr(_bc, "_ship_state_builder", None) is None:
            _bc._ship_state_builder = runtime.ship_state_snapshot

    if _wire_duty_scope_provider(runtime=runtime, config=config):
```
REPLACE:
```
        _bc = getattr(runtime, "boot_camp", None)
        if _bc is not None and getattr(_bc, "_ship_state_builder", None) is None:
            _bc._ship_state_builder = runtime.ship_state_snapshot

    # AD-1270 (#1324): AD-638 activation on a cold start, after the coordinator (Phase 7) and the
    # AD-683 snapshot late-bind above. Log-and-degrade: a failure leaves the crew unenrolled.
    try:
        await _activate_boot_camp_on_cold_start(runtime=runtime)
    except Exception:
        logger.warning("AD-1270: boot-camp activation failed; no crew is enrolled this run", exc_info=True)

    if _wire_duty_scope_provider(runtime=runtime, config=config):
```

### 7.13 `src/probos/startup/dreaming.py` (M2)

**Pair P-R1 (`src/probos/startup/dreaming.py`).** SEARCH:
```
    # AD-638: Activate boot camp for cold-start crew
    if cold_start and runtime and hasattr(runtime, 'boot_camp') and runtime.boot_camp:
        from probos.cognitive.standing_orders import get_department
        crew_agents = []
        for a in runtime.registry.all():
            if getattr(a, 'tier', '') in ("crew", "domain"):
                crew_agents.append({
                    "agent_id": a.id,
                    "callsign": getattr(a, 'callsign', '') or a.agent_type,
                    "department": getattr(a, 'department', '') or get_department(a.agent_type) or "unassigned",
                })
        if crew_agents:
            async def _activate_boot_camp():
                try:
                    await runtime.boot_camp.activate(crew_agents)
                    logger.info("AD-638: Boot camp activated for %d crew agents", len(crew_agents))
                except Exception:
                    logger.debug("AD-638: Boot camp activation failed", exc_info=True)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_activate_boot_camp())
            except RuntimeError:
                pass

    # Wire post-dream analysis callback (AD-237)
```
REPLACE:
```
    # AD-638 boot-camp activation moved to finalization (AD-1270, #1324): at this phase the
    # coordinator does not exist yet (it is built at Phase 7), so the block here never ran.

    # Wire post-dream analysis callback (AD-237)
```

### 7.14 `docs/development/architecture-baseline.yaml` (M2)

**Pair P-Z1 (`docs/development/architecture-baseline.yaml`).** SEARCH:
```
  key: probos.startup.dreaming::init_dreaming
  callee: loop.create_task
  count: 2
```
REPLACE:
```
  key: probos.startup.dreaming::init_dreaming
  callee: loop.create_task
  count: 1
```

### 7.15 New file: `tests/test_ad1270_boot_camp_lifecycle.py` (M2)

```python
"""AD-1270 (#1324) slice 4b, M2: the AD-638 boot camp activates, counts DMs and times out.

Activation moved from startup/dreaming.py (Phase 5, before the coordinator exists) into
finalization; every coordinator read enforces the timeout, with no task; a crew DM sent through
the proactive path counts. Time comes from an injected clock, trust from a real TrustNetwork.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.proactive import ProactiveCognitiveLoop
from probos.startup.finalize import _activate_boot_camp_on_cold_start
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.ward_room.service import WardRoomService

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_START = 1_000_000.0
_TIMEOUT_S = 120 * 60

CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}
CHIEF = {"agent_id": "chief-1", "callsign": "Worf", "department": "security"}


class _Clock:
    def __init__(self, now: float = _START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Episodes:
    def __init__(self, count: int) -> None:
        self.count = count

    async def count_for_agent(self, agent_id: str) -> int:
        return self.count


def _coordinator(
    trust: TrustNetwork,
    clock: _Clock,
    *,
    events: list | None = None,
    ward_room: object | None = None,
    **config: object,
) -> BootCampCoordinator:
    settings = {"min_time_minutes": 0, "nudge_cooldown_seconds": 0, "timeout_minutes": 120, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        ward_room=ward_room if ward_room is not None else SimpleNamespace(),
        trust_service=trust,
        episodic_memory=_Episodes(10),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
        clock=clock,
    )


async def _enrolled(clock: _Clock, **config: object) -> BootCampCoordinator:
    coord = _coordinator(TrustNetwork(), clock, **config)
    await coord.activate([CREW])
    return coord


# --- the timeout, by construction ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("offset", "enrolled"), [(_TIMEOUT_S - 1, True), (_TIMEOUT_S, False)], ids=["just-before", "at"])
async def test_nobody_is_enrolled_past_the_timeout(offset: float, enrolled: bool) -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + offset

    assert coord.is_enrolled(CREW["agent_id"]) is enrolled
    state = coord.get_state(CREW["agent_id"])
    assert state.graduated is (not enrolled)
    if not enrolled:
        assert state.graduated_at == _START + offset
        assert state.phase == 4


@pytest.mark.asyncio
async def test_is_active_turns_false_at_the_timeout() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    assert coord.is_active is False


@pytest.mark.asyncio
async def test_the_timeout_emits_one_event_and_graduates_the_rest() -> None:
    clock, events = _Clock(), []
    coord = _coordinator(TrustNetwork(), clock, events=events)
    await coord.activate([CREW, {"agent_id": "crew-2", "callsign": "Nog", "department": "operations"}])
    clock.now = _START + _TIMEOUT_S + 30

    for _ in range(3):
        assert not coord.is_enrolled(CREW["agent_id"])
    assert coord.is_active is False

    timeouts = [data for event_type, data in events if event_type == EventType.BOOT_CAMP_TIMEOUT]
    assert len(timeouts) == 1
    assert sorted(timeouts[0]["agent_ids"]) == ["crew-1", "crew-2"]
    assert timeouts[0]["duration_minutes"] == 120.5
    for agent_id in ("crew-1", "crew-2"):
        assert coord.get_state(agent_id).graduated_at == _START + _TIMEOUT_S + 30


@pytest.mark.asyncio
async def test_the_timeout_ends_the_relaxation() -> None:
    clock = _Clock()
    coord = await _enrolled(clock, relax_quality_gates=True)
    assert coord.relaxes_quality_gates(CREW["agent_id"])

    clock.now = _START + _TIMEOUT_S

    assert not coord.relaxes_quality_gates(CREW["agent_id"])


@pytest.mark.asyncio
async def test_the_timeout_changes_no_trust_record_and_forgets_nobody() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CREW["agent_id"], 2.0, 3.0)  # 0.4
    clock = _Clock()
    coord = _coordinator(trust, clock)
    await coord.activate([CREW])
    before = trust.get_record(CREW["agent_id"])
    alpha_beta = (before.alpha, before.beta)

    clock.now = _START + _TIMEOUT_S
    assert not coord.is_enrolled(CREW["agent_id"])

    after = trust.get_record(CREW["agent_id"])
    assert (after.alpha, after.beta) == alpha_beta
    assert coord.get_state(CREW["agent_id"]) is not None  # graduated, not deleted


@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["post", "dm"])
async def test_activity_past_the_timeout_is_not_counted(activity: str) -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    if activity == "post":
        await coord.on_agent_post(CREW["agent_id"], "department")
    else:
        await coord.on_agent_dm(CREW["agent_id"])

    state = coord.get_state(CREW["agent_id"])
    assert (state.ward_room_posts, state.dm_conversations) == (0, 0)
    assert state.graduated


@pytest.mark.asyncio
async def test_check_graduation_past_the_timeout_reports_graduated() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)  # no posts or DMs: the criteria are not met
    clock.now = _START + _TIMEOUT_S

    assert await coord.check_graduation(CREW["agent_id"]) is True


@pytest.mark.asyncio
async def test_the_timeout_with_nobody_enrolled_ends_boot_camp() -> None:
    trust = TrustNetwork()
    trust.create_with_prior(CHIEF["agent_id"], 3.0, 1.0)
    clock, events = _Clock(), []
    coord = _coordinator(trust, clock, events=events)
    await coord.activate([CHIEF])  # AD-640 skips the only agent
    clock.now = _START + _TIMEOUT_S

    assert coord.is_active is False
    assert EventType.BOOT_CAMP_TIMEOUT not in [event_type for event_type, _ in events]


@pytest.mark.asyncio
async def test_reads_before_activation_are_safe() -> None:
    coord = _coordinator(TrustNetwork(), _Clock())

    assert coord.is_active is False
    assert coord.is_enrolled(CREW["agent_id"]) is False
    assert coord.relaxes_quality_gates(CREW["agent_id"]) is False


@pytest.mark.asyncio
async def test_check_timeout_still_ends_boot_camp() -> None:
    clock = _Clock()
    coord = await _enrolled(clock)
    clock.now = _START + _TIMEOUT_S

    await coord.check_timeout()

    assert coord.get_state(CREW["agent_id"]).graduated  # get_state reads without expiring


# --- the injected clock -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graduation_waits_for_min_time_on_the_injected_clock() -> None:
    trust, clock = TrustNetwork(), _Clock()
    coord = _coordinator(trust, clock, min_time_minutes=60)
    await coord.activate([CREW])
    trust.create_with_prior(CREW["agent_id"], 3.0, 2.0)  # 0.6, after enrolment
    for _ in range(3):
        await coord.on_agent_post(CREW["agent_id"], "department")
    await coord.on_agent_dm(CREW["agent_id"])
    assert coord.is_enrolled(CREW["agent_id"])  # 0 of 60 minutes served

    clock.now = _START + 60 * 60

    assert await coord.check_graduation(CREW["agent_id"]) is True
    assert coord.get_state(CREW["agent_id"]).graduated_at == _START + 60 * 60


def test_the_coordinator_reads_time_only_through_its_clock() -> None:
    tree = ast.parse((_SRC / "boot_camp.py").read_bytes())
    coordinator = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BootCampCoordinator")
    wall_reads = [
        call.lineno
        for call in ast.walk(coordinator)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in {"time", "monotonic"}
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "time"
    ]

    assert wall_reads == []


# --- DMs through the real proactive path ---------------------------------------------------

_DM_CREW = (
    ("security_officer", "Worf", "security"),
    ("counselor", "Troi", "medical"),
)


def _crew_member(agent_type: str, callsign: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type,
        pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
    )


@pytest.fixture
async def dm_rig(tmp_path):
    """The BF-874 rig (tests/test_bf874_dm_callsign_and_fail_closed.py:65-98) with a real
    coordinator and a real TrustNetwork in place of ``boot_camp=None``."""
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    registry = AgentRegistry()
    agents = {callsign: _crew_member(agent_type, callsign) for agent_type, callsign, _ in _DM_CREW}
    for agent in agents.values():
        await registry.register(agent)
    callsigns = CallsignRegistry()
    for agent_type, callsign, _ in _DM_CREW:
        callsigns.set_callsign(agent_type, callsign)
    callsigns.bind_registry(registry)
    departments = {agent_type: dept for agent_type, _, dept in _DM_CREW}
    config = SystemConfig()
    config.communications.dm_min_rank = "ensign"
    trust, clock, events = TrustNetwork(), _Clock(), []
    coord = _coordinator(trust, clock, events=events, ward_room=ws, min_time_minutes=60)
    rt = SimpleNamespace(
        ward_room=ws, registry=registry, callsign_registry=callsigns,
        ontology=SimpleNamespace(get_agent_department=lambda t: departments.get(t)),
        config=config, trust_network=trust, ward_room_router=None,
        episodic_memory=None, hebbian_router=None, dispatcher=None, _records_store=None,
        working_memory=None, dm_sanity_gate=DmSanityGate(), skill_service=None,
        boot_camp=coord, emit_event=lambda *a, **k: None,
    )
    loop = ProactiveCognitiveLoop(cooldown=300.0)
    loop.set_runtime(rt)
    sender = agents["Worf"]  # 0.5 prior: below 0.55, so enrolled
    await coord.activate([{"agent_id": sender.id, "callsign": "Worf", "department": "security"}])
    yield SimpleNamespace(loop=loop, sender=sender, coord=coord, trust=trust, clock=clock, events=events)
    await ws.stop()


@pytest.mark.asyncio
async def test_a_crew_dm_through_the_proactive_path_is_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Troi] Reporting in for duty. [/DM]")

    assert [action["target_callsign"] for action in actions] == ["Troi"]
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 1


@pytest.mark.asyncio
async def test_a_dm_to_the_captain_is_not_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Captain] Settling in well. [/DM]")

    assert [action["target_callsign"] for action in actions] == ["captain"]
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 0


@pytest.mark.asyncio
async def test_an_unsent_dm_is_not_counted(dm_rig) -> None:
    _, actions = await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Nobody] Hello there. [/DM]")

    assert actions == []
    assert dm_rig.coord.get_state(dm_rig.sender.id).dm_conversations == 0


@pytest.mark.asyncio
async def test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust(dm_rig) -> None:
    agent_id = dm_rig.sender.id
    for _ in range(3):
        await dm_rig.coord.on_agent_post(agent_id, "department")
    await dm_rig.loop.extract_and_execute_dms(dm_rig.sender, "[DM @Troi] First watch report. [/DM]")
    assert dm_rig.trust.get_record(agent_id) is None
    dm_rig.trust.create_with_prior(agent_id, 3.0, 2.0)  # 0.6: above min_trust_score
    assert dm_rig.coord.is_enrolled(agent_id)  # 0 of 60 minutes served

    dm_rig.clock.now = _START + 61 * 60
    await dm_rig.coord.on_agent_post(agent_id, "department")

    assert not dm_rig.coord.is_enrolled(agent_id)
    graduations = [data for event_type, data in dm_rig.events if event_type == EventType.BOOT_CAMP_GRADUATION]
    assert [g["agent_id"] for g in graduations] == [agent_id]
    assert dm_rig.coord.get_state(agent_id).graduated_at == _START + 61 * 60


# --- activation at finalization ------------------------------------------------------------

_FLEET = [
    SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf", department="security"),
    SimpleNamespace(id="file_reader-0", agent_type="file_reader", callsign="", department=""),
]


def _startup_runtime(coord: BootCampCoordinator | None, *, cold: bool, agents: list) -> SimpleNamespace:
    return SimpleNamespace(
        boot_camp=coord, is_cold_start=cold, ontology=None,
        registry=SimpleNamespace(all=lambda: list(agents)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cold", [True, False], ids=["cold", "warm"])
async def test_cold_start_finalization_enrols_crew(cold: bool) -> None:
    coord = _coordinator(TrustNetwork(), _Clock())

    ran = await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(coord, cold=cold, agents=_FLEET))

    assert ran is cold
    assert coord.is_enrolled("security_officer-0") is cold
    assert not coord.is_enrolled("file_reader-0")  # not crew (crew_utils.is_crew_agent)
    assert coord.is_active is cold


@pytest.mark.asyncio
async def test_no_coordinator_or_no_crew_means_no_activation() -> None:
    assert await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(None, cold=True, agents=_FLEET)) is False

    coord = _coordinator(TrustNetwork(), _Clock())
    no_crew = _startup_runtime(coord, cold=True, agents=_FLEET[1:])
    assert await _activate_boot_camp_on_cold_start(runtime=no_crew) is False
    assert coord.is_active is False


def _named_calls(node: ast.AST, name: str) -> list[int]:
    return sorted(
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name
    )


def test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    body = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")
    activations = _named_calls(body, "_activate_boot_camp_on_cold_start")
    snapshots = _named_calls(body, "_wire_ship_state_snapshot")

    assert len(activations) == 1 and len(snapshots) == 1
    assert activations[0] > snapshots[0]


def test_phase_5_no_longer_tries_to_activate_the_boot_camp() -> None:
    tree = ast.parse((_SRC / "startup" / "dreaming.py").read_bytes())

    assert [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "boot_camp"] == []
```

### 7.16 Repair 1 (A1)

Written against the files as committed at `31066065`. Every SEARCH occurs once in its file; match with the file's own (CRLF) endings.

**Pair P-R1 (`src/probos/cognitive/cognitive_agent.py`).** `_execute_sub_task_chain`'s producer. M1's tests keep passing: `[off]` still sees the key absent, `[on]` still sees `True`, and the AST case still finds `relaxes_quality_gates` and no `is_enrolled`. SEARCH:
```
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
```
REPLACE:
```
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        observation.pop("_boot_camp_active", None)  # AD-1270: ask again; phase 2 and the fallback reuse triage's dict
```

**Pair P-R2 (`src/probos/cognitive/cognitive_agent.py`).** `_execute_chain_with_intent_routing`'s producer. SEARCH:
```
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
```
REPLACE:
```
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        observation.pop("_boot_camp_active", None)  # AD-1270: ask again; a reused observation carries an old answer
```

**Pair P-R3 (`src/probos/boot_camp.py`).** Docstring only; no test changes. `test_check_timeout_still_ends_boot_camp` keeps relying on `get_state` not expiring. SEARCH:
```
        """AD-1270 (#1324): enforce ``timeout_minutes`` by construction, with no task.

        Every public reader and tracker calls this first, so nothing can observe an
        enrolment, or a relaxation, past the timeout.
        """
```
REPLACE:
```
        """AD-1270 (#1324): enforce ``timeout_minutes`` by construction, with no task.

        ``is_active``, ``is_enrolled``, ``check_graduation``, ``on_agent_post``,
        ``on_agent_dm`` and ``check_timeout`` call this first; ``relaxes_quality_gates``
        reaches it through ``is_enrolled`` when ``relax_quality_gates`` is on. ``get_state``
        returns the raw state and does not call it.
        """
```

**Pair P-R4 (`src/probos/startup/finalize.py`).** The new-crew gate. It updates the expectations of M2's activation tests (P-R6 to P-R9). SEARCH:
```
async def _activate_boot_camp_on_cold_start(*, runtime: Any) -> bool:
    """AD-1270 (#1324): enrol cold-start crew in the AD-638 boot camp.

    Moved from ``startup/dreaming.py``, which runs at Phase 5, before the coordinator
    exists (Phase 7), so it never ran. Called after the AD-683 snapshot late-bind.
    Returns True when ``activate`` ran; a warm boot or no coordinator does nothing.
    """
    coordinator = getattr(runtime, "boot_camp", None)
    if coordinator is None or not runtime.is_cold_start:
        return False
```
REPLACE:
```
async def _is_new_crew_start(runtime: Any) -> bool:
    """AD-1270 (#1324): True when this boot starts a new crew, for the AD-638 boot camp.

    A new crew has no previous session record (AD-502's ``_lifecycle_state`` is
    ``first_boot``, or ``reset``) and an empty episode store; a stasis recovery is not one.
    This is not BF-034's ``runtime.is_cold_start``: that flag reads the memory object's
    truthiness, so it is false whenever an ``EpisodicMemory`` exists, and Phase 7 builds
    the coordinator only when a memory object is present (#1324 register R10). Fails warm:
    an unreadable count is not a new crew.
    """
    if runtime._lifecycle_state not in ("first_boot", "reset"):
        return False  # AD-1270: a session record means this crew has served before
    try:
        stats = await runtime.episodic_memory.get_stats()
    except Exception:
        logger.debug("AD-1270: episode count unavailable; not treated as a new crew", exc_info=True)
        return False  # AD-1270: an unreadable count is not a new crew
    return stats.get("total") == 0


async def _activate_boot_camp_on_cold_start(*, runtime: Any) -> bool:
    """AD-1270 (#1324): enrol a new crew in the AD-638 boot camp.

    Moved from ``startup/dreaming.py``, which runs at Phase 5, before the coordinator
    exists (Phase 7), so it never ran. Called after the AD-683 snapshot late-bind and
    gated on ``_is_new_crew_start``. Returns True when ``activate`` ran; a boot after a
    recorded session, a non-empty episode store or no coordinator does nothing.
    """
    coordinator = getattr(runtime, "boot_camp", None)
    if coordinator is None or not await _is_new_crew_start(runtime):
        return False
```

**Pair P-R5 (`src/probos/startup/finalize.py`).** The comment and the warning; no test pins the text. SEARCH:
```
    # AD-1270 (#1324): AD-638 activation on a cold start, after the coordinator (Phase 7) and the
    # AD-683 snapshot late-bind above. Log-and-degrade: a failure leaves the crew unenrolled.
    try:
        await _activate_boot_camp_on_cold_start(runtime=runtime)
    except Exception:
        logger.warning("AD-1270: boot-camp activation failed; no crew is enrolled this run", exc_info=True)
```
REPLACE:
```
    # AD-1270 (#1324): AD-638 activation for a new crew, after the coordinator (Phase 7) and the
    # AD-683 snapshot late-bind above. Log-and-degrade: startup continues. ``activate`` enrols
    # agent by agent and nothing is rolled back, so a failure part-way can leave some crew enrolled.
    try:
        await _activate_boot_camp_on_cold_start(runtime=runtime)
    except Exception:
        logger.warning("AD-1270: boot-camp activation failed; startup continues", exc_info=True)
```

**Pair P-R6 (`tests/test_ad1270_boot_camp_lifecycle.py`).** The module docstring (M2's file). SEARCH:
```
Activation moved from startup/dreaming.py (Phase 5, before the coordinator exists) into
finalization; every coordinator read enforces the timeout, with no task; a crew DM sent through
the proactive path counts. Time comes from an injected clock, trust from a real TrustNetwork.
```
REPLACE:
```
Activation moved from startup/dreaming.py (Phase 5, before the coordinator exists) into
finalization, for a new crew (Amendment A1: no session record and no episodes). ``is_active``,
``is_enrolled``, ``check_graduation``, ``on_agent_post``, ``on_agent_dm`` and ``check_timeout``
enforce the timeout, with no task, and ``relaxes_quality_gates`` does when its flag is on;
``get_state`` returns raw state. A crew DM sent through the proactive path counts. Time comes
from an injected clock, trust from a real TrustNetwork.
```

**Pair P-R7 (`tests/test_ad1270_boot_camp_lifecycle.py`).** `_startup_runtime` now models a new crew, not `is_cold_start`. M2's `test_cold_start_finalization_enrols_crew` and `test_no_coordinator_or_no_crew_means_no_activation` keep their names and assertions. SEARCH:
```
def _startup_runtime(coord: BootCampCoordinator | None, *, cold: bool, agents: list) -> SimpleNamespace:
    return SimpleNamespace(
        boot_camp=coord, is_cold_start=cold, ontology=None,
        registry=SimpleNamespace(all=lambda: list(agents)),
    )
```
REPLACE:
```
class _Stats:
    """The one episodic-memory read ``_is_new_crew_start`` makes."""

    def __init__(self, total: int) -> None:
        self.total = total

    async def get_stats(self) -> dict:
        return {"total": self.total}


def _startup_runtime(coord: BootCampCoordinator | None, *, new_crew: bool, agents: list) -> SimpleNamespace:
    # AD-1270 A1: is_cold_start is False, as production reports it whenever a coordinator exists
    # (register R10); a new crew is no session record (first_boot) and an empty episode store.
    return SimpleNamespace(
        boot_camp=coord, is_cold_start=False, ontology=None,
        _lifecycle_state="first_boot" if new_crew else "stasis_recovery", episodic_memory=_Stats(0),
        registry=SimpleNamespace(all=lambda: list(agents)),
    )
```

**Pair P-R8 (`tests/test_ad1270_boot_camp_lifecycle.py`).** The three call sites. SEARCH:
```
    ran = await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(coord, cold=cold, agents=_FLEET))
```
REPLACE:
```
    ran = await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(coord, new_crew=cold, agents=_FLEET))
```
Then SEARCH:
```
    assert await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(None, cold=True, agents=_FLEET)) is False
```
REPLACE:
```
    assert await _activate_boot_camp_on_cold_start(runtime=_startup_runtime(None, new_crew=True, agents=_FLEET)) is False
```
Then SEARCH:
```
    no_crew = _startup_runtime(coord, cold=True, agents=_FLEET[1:])
```
REPLACE:
```
    no_crew = _startup_runtime(coord, new_crew=True, agents=_FLEET[1:])
```

**Pair P-R9 (`tests/test_ad1270_boot_camp_lifecycle.py`).** The ordering test also checks the await (reviewer B, property 5). SEARCH:
```
    assert len(activations) == 1 and len(snapshots) == 1
    assert activations[0] > snapshots[0]
```
REPLACE:
```
    assert len(activations) == 1 and len(snapshots) == 1
    assert activations[0] > snapshots[0]
    awaited = sorted(
        node.value.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name) and node.value.func.id == "_activate_boot_camp_on_cold_start"
    )
    assert awaited == activations  # A1: awaited, not a coroutine left unawaited
```

### 7.17 New file: `tests/test_ad1270_boot_camp_repair_a1.py` (R1)

```python
"""AD-1270 (#1324) slice 4b, Amendment A1: each chain phase asks for the relaxation again, and
the boot camp finds a new crew without BF-034's cold-start flag.

The chain cases use the AD-1347 S4 harness: a real ``CognitiveAgent`` and ``SubTaskExecutor``,
with ANALYZE and COMPOSE as stand-ins that make no model call, and the real ``EvaluateHandler``
and ``ReflectHandler`` with AD-639 on. The coordinator is real, with an injected clock, and
trust is a real ``TrustNetwork``. The new-crew cases use a real ``EpisodicMemory`` on
``tmp_path``. Nothing here reads the vessel's data directory or starts a vessel.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.startup.finalize import _activate_boot_camp_on_cold_start

_START = 1_000_000.0
_TIMEOUT_S = 120 * 60
CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}
_FLEET = [
    SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf", department="security"),
    SimpleNamespace(id="file_reader-0", agent_type="file_reader", callsign="", department=""),
]


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def __call__(self) -> float:
        return self.now


class _Episodes:
    """The coordinator's episode-count collaborator (not under repair)."""

    async def count_for_agent(self, agent_id: str) -> int:
        return 0


def _coordinator(clock: _Clock, *, trust: TrustNetwork | None = None, memory: Any = None) -> BootCampCoordinator:
    return BootCampCoordinator(
        config=BootCampConfig(
            relax_quality_gates=True, min_time_minutes=0, nudge_cooldown_seconds=0, timeout_minutes=120,
        ),
        ward_room=SimpleNamespace(),
        trust_service=trust if trust is not None else TrustNetwork(),
        episodic_memory=memory if memory is not None else _Episodes(),
        emit_event_fn=lambda event_type, data: None,
        clock=clock,
    )


# --- each chain phase asks again ------------------------------------------------------------


class _Runtime:
    """The runtime attributes the chain entry points read directly, plus a no-op emit_event."""

    def __init__(self, coord: BootCampCoordinator, trust: TrustNetwork) -> None:
        self.boot_camp = coord
        self.trust_network = trust  # no record for the crew agent: the 0.5 prior, AD-639's low band
        self.config = SystemConfig()  # chain_tuning on, low_trust_ceiling 0.60

    def emit_event(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Analysis:
    """ANALYZE's JSON contract, with no model call. Records the marker each call is given."""

    def __init__(self, during_triage: Callable[[], None]) -> None:
        self.markers: list[Any] = []
        self._during_triage = during_triage

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        self.markers.append(context.get("_boot_camp_active"))
        if len(self.markers) == 1:
            self._during_triage()
        return SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE, name=spec.name, success=True,
            result={"intended_actions": ["ward_room_reply"], "contribution_assessment": "RESPOND"},
        )


class _Compose:
    """COMPOSE with no model call."""

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": "The sweep is clean."},
        )


class _Seen:
    """A real handler, with each result it returned recorded."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.results: list[dict] = []

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        result = await self._handler(spec, context, prior_results)
        self.results.append(result.result)
        return result


def _chain() -> SubTaskChain:
    return SubTaskChain(steps=[
        SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="analyze"),
        SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose"),
        SubTaskSpec(sub_task_type=SubTaskType.EVALUATE, name="evaluate"),
        SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="reflect"),
    ])


def _agent(coord: BootCampCoordinator, trust: TrustNetwork, analysis: _Analysis) -> tuple[Any, _Seen, _Seen]:
    # Every path here returns before a model call; a client with no methods makes one fail loudly.
    evaluate = _Seen(EvaluateHandler(llm_client=SimpleNamespace(), runtime=None))
    reflect = _Seen(ReflectHandler(llm_client=SimpleNamespace(), runtime=None))
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.ANALYZE, analysis)
    executor.register_handler(SubTaskType.COMPOSE, _Compose())
    executor.register_handler(SubTaskType.EVALUATE, evaluate)
    executor.register_handler(SubTaskType.REFLECT, reflect)
    agent: Any = CognitiveAgent(agent_id=CREW["agent_id"], instructions="Test instructions.", runtime=None)
    agent.agent_type = "science_officer"
    agent.callsign = CREW["callsign"]
    agent.set_sub_task_executor(executor)
    agent._runtime = _Runtime(coord, trust)
    agent._build_chain_for_intent = lambda observation: _chain()  # chain construction is not under test
    return agent, evaluate, reflect


def _observation() -> dict:
    return {
        "intent": "ward_room_notification",
        "intent_id": "ad1270-a1",
        "context": "LaForge: Wesley, what did the sensor sweep show?",
        "params": {
            "channel_name": "Science", "is_dm_channel": False,
            "author_id": "laforge-1", "author_callsign": "LaForge",
            "title": "Sensor sweep", "text": "Wesley, what did the sensor sweep show?",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("expires", [False, True], ids=["held", "expired-in-triage"])
async def test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two(expires: bool) -> None:
    clock, trust = _Clock(), TrustNetwork()
    coord = _coordinator(clock, trust=trust)
    await coord.activate([CREW])

    def during_triage() -> None:
        if expires:
            clock.now = _START + _TIMEOUT_S  # ordinary elapsed time: the deadline passes during triage

    analysis = _Analysis(during_triage)
    agent, evaluate, reflect = _agent(coord, trust, analysis)
    observation = _observation()

    await agent._execute_chain_with_intent_routing(observation)

    assert len(analysis.markers) == 2, "premise: triage and phase 2 both ran"
    assert evaluate.results and reflect.results, "premise: phase 2 reached the real gates"
    assert coord.is_enrolled(CREW["agent_id"]) is not expires
    if expires:
        assert analysis.markers == [True, None]
        assert "_boot_camp_active" not in observation
        assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"  # AD-639 ran in phase 2
        assert reflect.results[-1].get("reflection") == "low_trust_band_bypass"
    else:
        assert analysis.markers == [True, True]
        assert evaluate.results[-1].get("bypass_reason") == "boot_camp"
        assert reflect.results[-1].get("bypass_reason") == "boot_camp"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["direct", "routed"])
async def test_each_chain_entry_asks_again_on_a_reused_observation(entry: str) -> None:
    clock, trust = _Clock(), TrustNetwork()
    coord = _coordinator(clock, trust=trust)
    await coord.activate([CREW])
    clock.now = _START + _TIMEOUT_S  # the relaxation ended before this chain started
    analysis = _Analysis(lambda: None)
    agent, evaluate, _ = _agent(coord, trust, analysis)
    observation = _observation()
    observation["_boot_camp_active"] = True  # an earlier phase's answer on the same dict (the phase-2 hand-off)

    if entry == "direct":
        await agent._execute_sub_task_chain(_chain(), observation)
    else:
        await agent._execute_chain_with_intent_routing(observation)

    assert analysis.markers == ([None] if entry == "direct" else [None, None])
    assert "_boot_camp_active" not in observation
    assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"


# --- a new crew, without BF-034's flag ------------------------------------------------------


class _Stats:
    """The one read ``_is_new_crew_start`` makes of the episodic memory."""

    def __init__(self, total: int = 0, error: Exception | None = None) -> None:
        self.total = total
        self.error = error

    async def get_stats(self) -> dict:
        if self.error is not None:
            raise self.error
        return {"total": self.total}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "memory", "expected"),
    [
        ("first_boot", _Stats(0), True),
        ("reset", _Stats(0), True),
        ("stasis_recovery", _Stats(0), False),
        ("first_boot", _Stats(3), False),
        ("first_boot", _Stats(error=OSError("collection unavailable")), False),
    ],
    ids=["first-boot", "reset", "stasis-recovery", "episodes", "count-raises"],
)
async def test_a_new_crew_needs_no_session_record_and_no_episodes(lifecycle: str, memory: _Stats, expected: bool) -> None:
    from probos.startup.finalize import _is_new_crew_start  # imported here so each case fails by name on M2

    runtime = SimpleNamespace(_lifecycle_state=lifecycle, episodic_memory=memory, is_cold_start=False)

    assert await _is_new_crew_start(runtime) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle", ["first_boot", "stasis_recovery"], ids=["first-boot", "stasis-recovery"])
async def test_finalization_enrols_a_new_crew_with_a_real_empty_memory(tmp_path: Path, lifecycle: str) -> None:
    from probos.cognitive.episodic import EpisodicMemory

    memory = EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db"))
    await memory.start()
    try:
        assert memory, "premise: a live memory object is truthy, so BF-034's `not episodic_memory` reads it as warm"
        coord = _coordinator(_Clock(), memory=memory)
        runtime = SimpleNamespace(
            boot_camp=coord, is_cold_start=False, ontology=None, _lifecycle_state=lifecycle,
            episodic_memory=memory, registry=SimpleNamespace(all=lambda: list(_FLEET)),
        )
        ran = await _activate_boot_camp_on_cold_start(runtime=runtime)
    finally:
        await memory.stop()

    new_crew = lifecycle == "first_boot"
    assert ran is new_crew
    assert coord.is_enrolled("security_officer-0") is new_crew
    assert not coord.is_enrolled("file_reader-0")  # not crew (crew_utils.is_crew_agent)
```

### 7.18 Repair 2 (A2)

Written against the files as committed at `8855783b`. Every SEARCH occurs once in its file; match with the file's own (CRLF) endings.

**Pair P-S1 (`src/probos/cognitive/cognitive_agent.py`).** The producer helper, placed before `_execute_sub_task_chain`. SEARCH:
```
    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
```
REPLACE:
```
    def _refresh_boot_camp_relaxation(self, observation: dict) -> None:
        """AD-638/AD-639 (AD-1270, #1324): set this chain phase's boot-camp answer and trust band.

        The one writer of ``_boot_camp_active``. It removes the key, then sets it only on a
        current true answer from ``relaxes_quality_gates`` (only while
        ``boot_camp.relax_quality_gates`` is on; enrolment alone relaxes nothing). Otherwise,
        when ``chain_tuning`` is enabled, it computes AD-639's ``_chain_trust_band``.
        ``_execute_sub_task_chain``, ``_execute_chain_with_intent_routing`` and
        ``_re_reflect_with_feedback`` call it before they execute, because a routed chain
        reuses one observation across its phases.
        """
        _rt = getattr(self, '_runtime', None)
        observation.pop("_boot_camp_active", None)  # AD-1270: the producer owns the marker; ask again
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                    # BF-263: Use self.id (deterministic agent_id), not agent_type.
                    # TrustNetwork._records is keyed by agent_id, not agent_type.
                    _trust = _rt.trust_network.get_score(self.id)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"
                logger.debug(
                    "AD-639: %s trust=%.2f band=%s",
                    _agent_type, _trust, observation["_chain_trust_band"],
                )

    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
```

**Pair P-S2 (`src/probos/cognitive/cognitive_agent.py`).** The direct entry calls the helper; `_rt` stays, because AD-653 reads it below. SEARCH:
```
        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        observation.pop("_boot_camp_active", None)  # AD-1270: ask again; phase 2 and the fallback reuse triage's dict
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                                        # BF-263: Use self.id (deterministic agent_id), not agent_type.
                    # TrustNetwork._records is keyed by agent_id, not agent_type.
                    _trust = _rt.trust_network.get_score(self.id)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"
                logger.debug(
                    "AD-639: %s trust=%.2f band=%s",
                    _agent_type, _trust, observation["_chain_trust_band"],
                )
```
REPLACE:
```
        # AD-638: Boot camp quality gate relaxation and AD-639's trust band (AD-1270, #1324)
        _rt = getattr(self, '_runtime', None)
        self._refresh_boot_camp_relaxation(observation)  # AD-1270: phase 2 and the fallback reuse triage's dict
```

**Pair P-S3 (`src/probos/cognitive/cognitive_agent.py`).** The routed entry calls the helper; `_rt` stays, because AD-653 and AD-696 read it below. SEARCH:
```
        # AD-638: Boot camp quality gate relaxation (AD-1270, #1324: only while
        # boot_camp.relax_quality_gates is on; enrolment alone relaxes nothing)
        _rt = getattr(self, '_runtime', None)
        observation.pop("_boot_camp_active", None)  # AD-1270: ask again; a reused observation carries an old answer
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                                        # BF-263: Use self.id (deterministic agent_id), not agent_type.
                    # TrustNetwork._records is keyed by agent_id, not agent_type.
                    _trust = _rt.trust_network.get_score(self.id)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"
```
REPLACE:
```
        # AD-638: Boot camp quality gate relaxation and AD-639's trust band (AD-1270, #1324)
        _rt = getattr(self, '_runtime', None)
        self._refresh_boot_camp_relaxation(observation)  # AD-1270: a reused observation carries an old answer
```

**Pair P-S4 (`src/probos/cognitive/cognitive_agent.py`).** The feedback Reflect asks again, inside its log-and-degrade `try`. SEARCH:
```
        try:
            reflect_results = await self._sub_task_executor.execute(
```
REPLACE:
```
        try:
            self._refresh_boot_camp_relaxation(observation)  # AD-1270: phase 2a's answer may have expired
            reflect_results = await self._sub_task_executor.execute(
```

**Pair P-S5 (`src/probos/startup/finalize.py`).** The whole interpretation sits inside the catch. SEARCH:
```
    the coordinator only when a memory object is present (#1324 register R10). Fails warm:
    an unreadable count is not a new crew.
    """
    if runtime._lifecycle_state not in ("first_boot", "reset"):
        return False  # AD-1270: a session record means this crew has served before
    try:
        stats = await runtime.episodic_memory.get_stats()
    except Exception:
        logger.debug("AD-1270: episode count unavailable; not treated as a new crew", exc_info=True)
        return False  # AD-1270: an unreadable count is not a new crew
    return stats.get("total") == 0
```
REPLACE:
```
    the coordinator only when a memory object is present (#1324 register R10). Fails warm:
    an unreadable count, or an answer whose ``get("total")`` is not ``== 0`` (``None``, a
    list, an int, a mapping without ``total``), is not a new crew.
    """
    if runtime._lifecycle_state not in ("first_boot", "reset"):
        return False  # AD-1270: a session record means this crew has served before
    try:
        stats = await runtime.episodic_memory.get_stats()
        return stats.get("total") == 0
    except Exception:  # AD-1270: an unreadable or malformed answer is not a new crew
        logger.debug("AD-1270: episode count unavailable or malformed; not treated as a new crew", exc_info=True)
        return False  # AD-1270: an unreadable count is not a new crew
```

**Pair P-S6 (`tests/test_ad1270_boot_camp_repair_a1.py`).** The module docstring. SEARCH:
```
"""AD-1270 (#1324) slice 4b, Amendment A1: each chain phase asks for the relaxation again, and
the boot camp finds a new crew without BF-034's cold-start flag.

The chain cases use the AD-1347 S4 harness: a real ``CognitiveAgent`` and ``SubTaskExecutor``,
with ANALYZE and COMPOSE as stand-ins that make no model call, and the real ``EvaluateHandler``
and ``ReflectHandler`` with AD-639 on. The coordinator is real, with an injected clock, and
trust is a real ``TrustNetwork``. The new-crew cases use a real ``EpisodicMemory`` on
``tmp_path``. Nothing here reads the vessel's data directory or starts a vessel.
"""
```
REPLACE:
```
"""AD-1270 (#1324) slice 4b, Amendments A1 and A2: each chain phase that can run Evaluate or
Reflect asks for the relaxation again, and the boot camp finds a new crew without BF-034's
cold-start flag.

The chain cases use the AD-1347 S4 harness: a real ``CognitiveAgent`` and ``SubTaskExecutor``,
with ANALYZE and COMPOSE as stand-ins that make no model call, and the real ``EvaluateHandler``
and ``ReflectHandler`` with AD-639 on. The coordinator is real, with an injected clock, and
trust is a real ``TrustNetwork``. The two finalization cases use a real ``EpisodicMemory`` on
``tmp_path``; the predicate cases use stand-ins for ``get_stats``. Nothing here reads the
vessel's data directory or starts a vessel.
"""
```

**Pair P-S7 (`tests/test_ad1270_boot_camp_repair_a1.py`).** COMPOSE takes its text and a hook. SEARCH:
```
class _Compose:
    """COMPOSE with no model call."""

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": "The sweep is clean."},
        )
```
REPLACE:
```
class _Compose:
    """COMPOSE with no model call. ``during_compose`` runs inside each call (A2: a deadline in phase 2a)."""

    def __init__(self, text: str = "The sweep is clean.", during_compose: Callable[[], None] = lambda: None) -> None:
        self._text = text
        self._during_compose = during_compose

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        self._during_compose()
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": self._text},
        )
```

**Pair P-S8 (`tests/test_ad1270_boot_camp_repair_a1.py`).** `_agent` accepts a COMPOSE stand-in; existing callers are unchanged. SEARCH:
```
def _agent(coord: BootCampCoordinator, trust: TrustNetwork, analysis: _Analysis) -> tuple[Any, _Seen, _Seen]:
    # Every path here returns before a model call; a client with no methods makes one fail loudly.
    evaluate = _Seen(EvaluateHandler(llm_client=SimpleNamespace(), runtime=None))
    reflect = _Seen(ReflectHandler(llm_client=SimpleNamespace(), runtime=None))
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.ANALYZE, analysis)
    executor.register_handler(SubTaskType.COMPOSE, _Compose())
```
REPLACE:
```
def _agent(
    coord: BootCampCoordinator, trust: TrustNetwork, analysis: _Analysis, compose: _Compose | None = None,
) -> tuple[Any, _Seen, _Seen]:
    # Every path here returns before a model call; a client with no methods makes one fail loudly.
    evaluate = _Seen(EvaluateHandler(llm_client=SimpleNamespace(), runtime=None))
    reflect = _Seen(ReflectHandler(llm_client=SimpleNamespace(), runtime=None))
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.ANALYZE, analysis)
    executor.register_handler(SubTaskType.COMPOSE, compose if compose is not None else _Compose())
```

**Pair P-S9 (`tests/test_ad1270_boot_camp_repair_a1.py`).** The feedback-deadline cases, through the real routed entry. SEARCH:
```
    assert analysis.markers == ([None] if entry == "direct" else [None, None])
    assert "_boot_camp_active" not in observation
    assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"


# --- a new crew, without BF-034's flag ------------------------------------------------------
```
REPLACE:
```
    assert analysis.markers == ([None] if entry == "direct" else [None, None])
    assert "_boot_camp_active" not in observation
    assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"


_UNDECLARED_DM = "[DM @LaForge]\nThe sweep is clean.\n[/DM]"  # a DM triage did not declare (AD-643b)


@pytest.mark.asyncio
@pytest.mark.parametrize("expires", [False, True], ids=["held", "expired-before-feedback"])
async def test_the_feedback_reflection_asks_again_after_phase_two(expires: bool) -> None:
    clock, trust = _Clock(), TrustNetwork()
    coord = _coordinator(clock, trust=trust)
    await coord.activate([CREW])

    def during_compose() -> None:
        if expires:
            clock.now = _START + _TIMEOUT_S  # the deadline passes in phase 2a, after its producer asked

    analysis = _Analysis(lambda: None)
    agent, evaluate, reflect = _agent(coord, trust, analysis, _Compose(_UNDECLARED_DM, during_compose))
    observation = _observation()

    await agent._execute_chain_with_intent_routing(observation)

    assert analysis.markers == [True, True], "premise: triage and phase 2a both ran relaxed"
    assert observation.get("_undeclared_action_feedback"), "premise: phase 2b found the undeclared DM"
    assert len(reflect.results) == 2, "premise: phase 2a's Reflect and the feedback Reflect both ran"
    assert evaluate.results[-1].get("bypass_reason") == "boot_camp"  # phase 2a keeps the answer it asked for
    assert reflect.results[0].get("bypass_reason") == "boot_camp"
    assert coord.is_enrolled(CREW["agent_id"]) is not expires
    if expires:
        assert "_boot_camp_active" not in observation
        assert reflect.results[-1].get("reflection") == "low_trust_band_bypass"  # AD-639 ran for the feedback Reflect
    else:
        assert observation.get("_boot_camp_active") is True
        assert reflect.results[-1].get("bypass_reason") == "boot_camp"


# --- a new crew, without BF-034's flag ------------------------------------------------------
```

**Pair P-S10 (`tests/test_ad1270_boot_camp_repair_a1.py`).** Malformed answers, through a stand-in that returns what it is given. SEARCH:
```
    runtime = SimpleNamespace(_lifecycle_state=lifecycle, episodic_memory=memory, is_cold_start=False)

    assert await _is_new_crew_start(runtime) is expected
```
REPLACE:
```
    runtime = SimpleNamespace(_lifecycle_state=lifecycle, episodic_memory=memory, is_cold_start=False)

    assert await _is_new_crew_start(runtime) is expected


class _Answer:
    """A memory whose ``get_stats`` returns exactly what it is given (A2: a malformed answer)."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer

    async def get_stats(self) -> Any:
        return self.answer


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, [], 0, {"episodes": 0}], ids=["none", "list", "int", "no-total"])
async def test_a_malformed_stats_answer_is_not_a_new_crew(answer: Any) -> None:
    from probos.startup.finalize import _is_new_crew_start

    runtime = SimpleNamespace(_lifecycle_state="first_boot", episodic_memory=_Answer(answer), is_cold_start=False)

    assert await _is_new_crew_start(runtime) is False  # fails warm, and raises nothing
```

**Pair P-S11 (`tests/test_ad1270_boot_camp_trust.py`).** The AST case, renamed and widened into a census of every method that executes a chain. SEARCH:
```
def test_both_chain_entry_points_ask_for_the_relaxation_not_enrolment() -> None:
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    wanted = {"_execute_sub_task_chain", "_execute_chain_with_intent_routing"}
    entry_points = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted
    }

    assert set(entry_points) == wanted
    for name, node in entry_points.items():
        assert "relaxes_quality_gates" in _attribute_calls(node), name
    assert "is_enrolled" not in _attribute_calls(tree)
```
REPLACE:
```
# A2 (AD-1270, #1324): every method that executes a sub-task chain is classified here. A gating
# phase can run Evaluate or Reflect and must ask again through the one producer; a lookup runs
# QUERY steps only. A new chain-executing method fails this test until it is classified.
_GATING_PHASES = {"_execute_sub_task_chain", "_execute_chain_with_intent_routing", "_re_reflect_with_feedback"}
_LOOKUP_PHASES = {"_maybe_dispatch_oracle_lookup", "_maybe_dispatch_ward_room_lookup"}


def _executes_a_chain(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "_sub_task_executor"
        for call in ast.walk(node)
    )


def _step_kinds(node: ast.AST) -> set[str]:
    return {
        keyword.value.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "SubTaskSpec"
        for keyword in call.keywords
        if keyword.arg == "sub_task_type" and isinstance(keyword.value, ast.Attribute)
    }


def test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment() -> None:
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = {node.name: node for node in functions}

    assert {node.name for node in functions if _executes_a_chain(node)} == _GATING_PHASES | _LOOKUP_PHASES
    for name in _GATING_PHASES:
        assert "_refresh_boot_camp_relaxation" in _attribute_calls(methods[name]), name
    for name in _LOOKUP_PHASES:
        assert _step_kinds(methods[name]) == {"QUERY"}, name
    assert "relaxes_quality_gates" in _attribute_calls(methods["_refresh_boot_camp_relaxation"])
    assert "is_enrolled" not in _attribute_calls(tree)
```

## 8. Tracking (M3's commit)

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 4b -- the AD-638 boot camp is repaired, and `/conn` works.** Two independent defects kept the boot camp inert: `TrustNetwork` had no `get_trust_score` (declared by `protocols.TrustNetworkProtocol` and the coordinator, called three times, mocked by every test), and cold-start activation ran in `startup/dreaming.py` at Phase 5, before the coordinator is built at Phase 7, so its guard was always false. `TrustNetwork.get_trust_score` now calls `get_score`, which also lets `/conn <callsign>` grant the conn to a COMMANDER+ bridge officer or chief (it raised before). Activation moved into finalization, after the AD-683 snapshot late-bind, and runs for a new crew: no previous session record and an empty episode store. It does not use BF-034's `is_cold_start`, which reads the memory object's truthiness and so is false whenever a coordinator exists; that detector's repair is #1324 register R10. `timeout_minutes` is enforced by the coordinator's enrolment and activity reads, with no task; a crew DM sent through the proactive path counts toward graduation; the coordinator reads time through an injected clock. AD-638's Evaluate/Reflect auto-approval is behind `boot_camp.relax_quality_gates` (default false), and every chain phase that can run Evaluate or Reflect (a direct chain, the routed chain's triage, phase 2 and fallback, and the AD-643b feedback Reflect) asks the coordinator again, so a relaxation that times out during a chain ends at the chain's next such phase. Off, enrolment changes no agent's prompt, chain, trust or authority, and switching it on is the Captain's call. The AD-509 phase tracker, phases 2 and 3, AD-683's snapshot injection and `holodeck/chamber.py:289` are slice 4c. The contract is `prompts/ad-1270-boot-camp-repair.md`.

```

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- the AD-638 boot camp is repaired: a protocol method, activation at finalization, a timeout by construction, DM counting, and the relaxation behind a default-off flag (2026-10-2X)

**Decision.** Add `TrustNetwork.get_trust_score`, delegating by call to `get_score`, rather than renaming three callers, two protocols and about thirteen mocks; a call (not a class alias) keeps instance patches of `get_score` governing both reads. Move AD-638 activation from `startup/dreaming.py` (Phase 5, where `runtime.boot_camp` is always `None`) into `finalize_startup`, after the AD-683 snapshot late-bind, and run it for a new crew: no previous session record and an empty episode store. It does not read BF-034's `is_cold_start`, which reads the memory object's truthiness and so is false whenever a coordinator exists. Enforce `timeout_minutes` in the coordinator's enrolment and activity reads (`is_active`, `is_enrolled`, `check_graduation`, `on_agent_post`, `on_agent_dm`, `check_timeout`) rather than with a task; a timeout graduates the remaining agents, emits one `BOOT_CAMP_TIMEOUT`, and deletes or demotes nothing. Count crew DMs at the proactive DM path; DMs to the Captain do not count. Gate the Evaluate/Reflect auto-approval at its producer through `BootCampCoordinator.relaxes_quality_gates` and `boot_camp.relax_quality_gates: false`, so that off, an enrolled agent's Evaluate, Reflect and AD-639 tuning run as for any other agent; one producer helper clears its marker before it asks, at both chain entry points and at the AD-643b feedback Reflect, so the routed chain's phase 2 and its feedback Reflect ask again rather than inheriting an earlier phase's answer. **Why.** The boot camp had a caller but no reachable path: the guard ran before its object existed, the method it called existed only on mocks, and BF-034's cold-start flag cannot be true while a coordinator exists. With the relaxation off, enrolment is bookkeeping and events of existing types, so it needs no flag of its own; `boot_camp.enabled` remains the off switch. **Captain.** Switching `relax_quality_gates` on weakens the anti-confabulation gate; it is his call. AD-639's low-trust band (`chain_tuning.low_trust_ceiling` 0.6) already skips Evaluate and Reflect for every agent the boot camp enrols (trust below 0.55), so the recommendation is to retire the relaxation after the first live new-crew start rather than enable it. `/conn` was restored as AD-471 specified it. It is a slash command, so any sender that can run one reaches it: the shell, the API chat route and channel adapters, the webhook adapter included. Nothing calls `ConnManager.is_authorized`, and the holder's proactive prompt does not show the conn's scope (#1324 register R8 and R11). **Rejected.** Renaming to `get_score` everywhere (wider blast radius, a shared-protocol change); a separate enrolment flag (duplicates `boot_camp.enabled`, protects no agent-visible effect); gating Evaluate and Reflect at the consumers (leaves AD-639 suppressed for enrolled agents); a timeout task (one more lifecycle to own); repairing BF-034's detector in this slice (it switches on its dormant readers at the next reset, one of them a fresh-start prompt note that nothing clears for the session; register R10).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): add and tick a slice-4b item with the commits and the receipt; add a slice-4c item, unticked.

## 9. What this does NOT change

- `sub_tasks/evaluate.py`, `sub_tasks/reflect.py`, `sub_task.py`, `journal.py`; the AD-683 injection at `cognitive_agent.py:10481` (still keyed on `_boot_camp_active`; slice 4c).
- `protocols.py`, `tiered_trust.py`, `conn.py`, `commands_autonomous.py`, `runtime.py`.
- `crew_development/boot_camp.py` (AD-509), `_wire_boot_camp_tracker`, `BootCampPhaseConfig`, `boot_camp_phase:` (slice 4c); `run_phase_2_introductions` and `run_phase_3_observation` (slice 4c); `holodeck/chamber.py`.
- Any event type, `event_persistence.py`, persisted schema.
- `proactive.py:4104-4115` (post counting).
- `dormant-class-baseline.yaml` (checked, not regenerated).
- (A1) BF-034's detector in `startup/dreaming.py`, `runtime.is_cold_start` and every reader of it (register R10).
- (A2) `_maybe_dispatch_oracle_lookup` and `_maybe_dispatch_ward_room_lookup` (QUERY only; they do not ask), the AD-683 read in `_build_user_message` (R6), the AD-272 decision cache, and `tests/test_trigger_learning.py`.

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline of M1's and M2's focused lists passes; run on the Captain's Windows host)

A Line cell whose text occurs twice says so: mutate every occurrence.

**Amendment A1.** Rows marked **R1** (A-1 to A-3, N-1 to N-7, S-7, S-8 and the rewritten S-1 and S-2) run on the R1 tree, after an unmutated baseline of R1's focused list passes. Rerun T-5, S-3, S-4, S-5 and S-6 there, because their file or killing test changed. Every other row stands from the M2 campaign of record on `31066065`, because its file is unchanged on R1 or differs only in a docstring (`boot_camp.py`, P-R3). The original S-1 and S-2 mutated a line that P-R4 rewrites; they are retired and replaced below.

**Amendment A2.** Rows marked **R2** (the rewritten T-5 and A-1 to A-3, the updated N-6, and N-8 to N-11) run on the R2 tree, after an unmutated baseline of R2's focused list passes. Rerun there every other `startup/finalize.py` row (S-1 to S-8, N-1 to N-5 and N-7), because that file and the test file holding most of their killers changed. Every other row stands from its campaign of record (M2 on `31066065`, R1 on `8855783b`): R2 does not change `trust.py`, `crew.py`, `boot_camp.py` or `proactive.py`. The R1 rows A-1 to A-3 and the M1 row T-5 mutated lines that P-S1 to P-S3 move into the helper; they are retired and replaced below. No new row is equivalent.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| T-1 | M1 | `consensus/trust.py` | `return self.get_score(agent_id)` | `return 0.5` | `test_get_trust_score_is_get_score[recorded-agent]`, `test_get_trust_score_follows_a_patched_get_score` |
| T-2 | M1 | `config_models/crew.py` | `relax_quality_gates: bool = False` | `relax_quality_gates: bool = True` | `test_the_relaxation_is_off_by_default`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]` |
| T-3 | M1 | `boot_camp.py` | `return self._config.relax_quality_gates and self.is_enrolled(agent_id)` | `return self.is_enrolled(agent_id)` | `test_an_enrolled_agent_relaxes_only_when_the_flag_is_on[off]`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]` |
| T-4 | M1 | `boot_camp.py` | `return self._config.relax_quality_gates and self.is_enrolled(agent_id)` | `return self._config.relax_quality_gates` | `test_an_agent_not_enrolled_never_relaxes[unknown]`, `test_an_agent_not_enrolled_never_relaxes[graduated]` |
| T-5 | R2 | `cognitive/cognitive_agent.py` | `if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):` | `if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):` | `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]`, `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` |
| L-1 | M2 | `boot_camp.py` | `self._clock = clock` | `self._clock = time.time` | `test_nobody_is_enrolled_past_the_timeout[at]` |
| L-2 | M2 | `boot_camp.py` | `self._started_at = self._clock()` | `self._started_at = 0.0` | `test_nobody_is_enrolled_past_the_timeout[just-before]` |
| L-3 | M2 | `boot_camp.py` | `enrolled_at=self._started_at,` | `enrolled_at=0.0,` | `test_graduation_waits_for_min_time_on_the_injected_clock` |
| L-4 | M2 | `boot_camp.py` | `elapsed_min = (self._clock() - state.enrolled_at) / 60` | `elapsed_min = 0.0` | `test_graduation_waits_for_min_time_on_the_injected_clock`, `test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust` |
| L-5 | M2 | `boot_camp.py` | `self._expire_if_timed_out()  # AD-1270: is_active is False once the timeout passes` | `pass` | `test_is_active_turns_false_at_the_timeout` |
| L-6 | M2 | `boot_camp.py` | `self._expire_if_timed_out()  # AD-1270: nobody is enrolled past the timeout` | `pass` | `test_nobody_is_enrolled_past_the_timeout[at]`, `test_the_timeout_ends_the_relaxation` |
| L-7 | M2 | `boot_camp.py` | `self._expire_if_timed_out()  # AD-1270: a timed-out agent is already graduated` | `pass` | `test_check_graduation_past_the_timeout_reports_graduated` |
| L-8 | M2 | `boot_camp.py` | `self._expire_if_timed_out()  # AD-1270: no post is counted past the timeout` | `pass` | `test_activity_past_the_timeout_is_not_counted[post]` |
| L-9 | M2 | `boot_camp.py` | `self._expire_if_timed_out()  # AD-1270: no DM is counted past the timeout` | `pass` | `test_activity_past_the_timeout_is_not_counted[dm]` |
| L-10 | M2 | `boot_camp.py` | `self._expire_if_timed_out()` (the bare line, `check_timeout`'s body) | `pass` | `test_check_timeout_still_ends_boot_camp` |
| L-11 | M2 | `boot_camp.py` | `if not self._active or self._started_at is None:` | `if False:` | `test_reads_before_activation_are_safe` |
| L-12 | M2 | `boot_camp.py` | `if self._clock() - self._started_at >= self._config.timeout_minutes * 60:` | `if self._clock() - self._started_at > self._config.timeout_minutes * 60:` | `test_nobody_is_enrolled_past_the_timeout[at]`, `test_is_active_turns_false_at_the_timeout` |
| L-13 | M2 | `boot_camp.py` | `self._active = False  # AD-1270: ends even when nobody is left to graduate` | `pass` | `test_the_timeout_with_nobody_enrolled_ends_boot_camp`, `test_the_timeout_emits_one_event_and_graduates_the_rest` |
| L-14 | M2 | `boot_camp.py` | `now = self._clock()` | `now = 0.0` | `test_the_timeout_emits_one_event_and_graduates_the_rest`, `test_nobody_is_enrolled_past_the_timeout[at]` |
| L-15 | M2 | `boot_camp.py` | `state.graduated_at = now` | `state.graduated_at = None` | `test_nobody_is_enrolled_past_the_timeout[at]`, `test_the_timeout_emits_one_event_and_graduates_the_rest` |
| L-16 | M2 | `boot_camp.py` | `state.graduated_at = self._clock()` | `state.graduated_at = 0.0` | `test_graduation_waits_for_min_time_on_the_injected_clock`, `test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust` |
| L-17 | M2 | `boot_camp.py` | `self._graduate_remaining_on_timeout()` (occurs twice: `force_graduate_all` and `_expire_if_timed_out`) | `pass` | `test_force_graduate_all`, `test_nobody_is_enrolled_past_the_timeout[at]` |
| D-1 | M2 | `proactive.py` | `await _boot_camp.on_agent_dm(agent.id)` | `pass` | `test_a_crew_dm_through_the_proactive_path_is_counted`, `test_a_crew_agent_graduates_through_the_real_dm_path_and_real_trust` |
| D-2 | M2 | `proactive.py` | `if _boot_camp is not None:` | `if True:` | none: equivalent mutant -- with no coordinator, `None.on_agent_dm` raises AttributeError inside the `try`, which logs at debug; the DM, its actions and its return value are unchanged |
| S-1 | R1 | `startup/finalize.py` | `if coordinator is None or not await _is_new_crew_start(runtime):` | `if coordinator is None:` | `test_cold_start_finalization_enrols_crew[warm]`, `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[stasis-recovery]` |
| S-2 | R1 | `startup/finalize.py` | `if coordinator is None or not await _is_new_crew_start(runtime):` | `if not await _is_new_crew_start(runtime):` | `test_no_coordinator_or_no_crew_means_no_activation` |
| S-3 | M2 | `startup/finalize.py` | `if is_crew_agent(agent, ontology)` | `if True` | `test_cold_start_finalization_enrols_crew[cold]` |
| S-4 | M2 | `startup/finalize.py` | `if not crew_agents:` | `if False:` | `test_no_coordinator_or_no_crew_means_no_activation` |
| S-5 | M2 | `startup/finalize.py` | `await coordinator.activate(crew_agents)` | `pass` | `test_cold_start_finalization_enrols_crew[cold]` |
| S-6 | M2 | `startup/finalize.py` | `await _activate_boot_camp_on_cold_start(runtime=runtime)` | `pass` | `test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind` |
| S-7 | R1 | `startup/finalize.py` | `if coordinator is None or not await _is_new_crew_start(runtime):` | `if coordinator is None or not runtime.is_cold_start:` | `test_cold_start_finalization_enrols_crew[cold]`, `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[first-boot]` |
| S-8 | R1 | `startup/finalize.py` | `await _activate_boot_camp_on_cold_start(runtime=runtime)` | `_activate_boot_camp_on_cold_start(runtime=runtime)` | `test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind` |
| N-1 | R1 | `startup/finalize.py` | `if runtime._lifecycle_state not in ("first_boot", "reset"):` | `if False:` | `test_a_new_crew_needs_no_session_record_and_no_episodes[stasis-recovery]`, `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[stasis-recovery]` |
| N-2 | R1 | `startup/finalize.py` | `if runtime._lifecycle_state not in ("first_boot", "reset"):` | `if runtime._lifecycle_state != "first_boot":` | `test_a_new_crew_needs_no_session_record_and_no_episodes[reset]` |
| N-3 | R1 | `startup/finalize.py` | `return False  # AD-1270: a session record means this crew has served before` | `pass` | `test_a_new_crew_needs_no_session_record_and_no_episodes[stasis-recovery]`, `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[stasis-recovery]` |
| N-4 | R1 | `startup/finalize.py` | `stats = await runtime.episodic_memory.get_stats()` | `stats = {"total": 0}` | `test_a_new_crew_needs_no_session_record_and_no_episodes[episodes]`, `test_a_new_crew_needs_no_session_record_and_no_episodes[count-raises]` |
| N-5 | R1 | `startup/finalize.py` | `return False  # AD-1270: an unreadable count is not a new crew` | `return True` | `test_a_new_crew_needs_no_session_record_and_no_episodes[count-raises]` |
| N-6 | R2 | `startup/finalize.py` | `return stats.get("total") == 0` | `return True` | `test_a_new_crew_needs_no_session_record_and_no_episodes[episodes]`, `test_a_malformed_stats_answer_is_not_a_new_crew[none]`, `test_a_malformed_stats_answer_is_not_a_new_crew[no-total]` |
| N-7 | R1 | `startup/finalize.py` | `return stats.get("total") == 0` | `return False` | `test_a_new_crew_needs_no_session_record_and_no_episodes[first-boot]`, `test_a_new_crew_needs_no_session_record_and_no_episodes[reset]`, `test_finalization_enrols_a_new_crew_with_a_real_empty_memory[first-boot]` |
| A-1 | R2 | `cognitive/cognitive_agent.py` | `self._refresh_boot_camp_relaxation(observation)  # AD-1270: phase 2 and the fallback reuse triage's dict` | `pass` | `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[on]`, `test_each_chain_entry_asks_again_on_a_reused_observation[direct]`, `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[expired-in-triage]`, `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` |
| A-2 | R2 | `cognitive/cognitive_agent.py` | `self._refresh_boot_camp_relaxation(observation)  # AD-1270: a reused observation carries an old answer` | `pass` | `test_each_chain_entry_asks_again_on_a_reused_observation[routed]`, `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[held]`, `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` |
| A-3 | R2 | `cognitive/cognitive_agent.py` | `if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):` | `if False:` | `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[held]`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[on]` |
| N-8 | R2 | `cognitive/cognitive_agent.py` | `self._refresh_boot_camp_relaxation(observation)  # AD-1270: phase 2a's answer may have expired` | `pass` | `test_the_feedback_reflection_asks_again_after_phase_two[expired-before-feedback]`, `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` |
| N-9 | R2 | `cognitive/cognitive_agent.py` | `observation.pop("_boot_camp_active", None)  # AD-1270: the producer owns the marker; ask again` | `pass` | `test_each_chain_entry_asks_again_on_a_reused_observation[direct]`, `test_each_chain_entry_asks_again_on_a_reused_observation[routed]`, `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[expired-in-triage]`, `test_the_feedback_reflection_asks_again_after_phase_two[expired-before-feedback]` |
| N-10 | R2 | `cognitive/cognitive_agent.py` | `if not observation.get("_boot_camp_active"):` | `if False:` | `test_each_chain_entry_asks_again_on_a_reused_observation[direct]`, `test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two[expired-in-triage]`, `test_the_feedback_reflection_asks_again_after_phase_two[expired-before-feedback]` |
| N-11 | R2 | `startup/finalize.py` | `except Exception:  # AD-1270: an unreadable or malformed answer is not a new crew` | `except OSError:` | `test_a_malformed_stats_answer_is_not_a_new_crew[none]`, `test_a_malformed_stats_answer_is_not_a_new_crew[list]`, `test_a_malformed_stats_answer_is_not_a_new_crew[int]` |

`test_force_graduate_all` is the existing `tests/test_ad638_boot_camp.py::TestTimeout::test_force_graduate_all`.

## 11. Verified Against Codebase (2026-10-28, on `4fd31e6c`)

```
Grep "def get_score\(|def get_trust_score\(" src/            trust.py:1017; boot_camp.py:24 and protocols.py:76 (stubs); agentic_dispatch.py:466, self_telemetry_domains.py:60 (other get_score)
Grep "get_trust_score" (repo)                                 boot_camp.py:160,224; runtime.py:2116; tests: test_ad638:59,224,295,313,479,504,532,585; test_ad640:210,235; test_ad683:240; test_bf206:39; test_ad702:236 (docstring)
Read consensus/trust.py:240-279, 358-371, 1005-1044         TrustNetwork() needs no I/O; create_with_prior; get_score/get_record
Read protocols.py:60-93                                       @runtime_checkable TrustNetworkProtocol
Read boot_camp.py (whole, 513 lines)                          every line paired in §7.3, §7.10
Read runtime.py:2095-2168, 2236-2241, 3155-3214, 3318-3342    is_conn_qualified; is_cold_start property; Phase 5 init_dreaming; Phase 7 construction
Read startup/dreaming.py:300-329                              the dead activation block
Read startup/finalize.py:880-897, 4145-4184                   _wire_boot_camp_tracker; finalize_startup BF-261 block
git diff -U0 4aa1062f 4fd31e6c -- src/probos/startup/finalize.py config/system.yaml   slice 3's hunks: finalize 819-863, 6373-6379; system.yaml 1965, 2008, 2042
Read cognitive_agent.py:6009-6087, 6236-6251, 10470-10499     chain entry points; AD-639; AD-683 injection
Read sub_tasks/evaluate.py:515-575; reflect.py:435-475        boot-camp and low-band bypasses
Read proactive.py:2525-2554, 4092-4119, 4820-4984             conn context; post counting; extract_and_execute_dms
Read conn.py:1-200; commands_autonomous.py:1-118; api.py:80-110; channels/base.py:345-370
Read config_models/crew.py:1-50; config/system.yaml:2104-2139, 2344-2349
Read tests/test_ad638_boot_camp.py:1-120, 381-475, 544-603; test_ad640_tiered_trust.py:200-256; test_ad683_ship_state_snapshot.py:228-277; test_ad702:225-254
Read tests/test_bf874_dm_callsign_and_fail_closed.py:28-167   the DM rig copied in 7.15
Read tests/test_ad632g_cognitive_jit_integration.py:200-249   the chain harness copied in 7.5
Read tests/test_ad1270e2g_crew_models.py:130-144, 255-284, 440-449, 528-547, 700-749
Read tests/test_ad1270e1_config_facade.py:1550-1563; test_ad1152_agentic_correlation.py:296-324
Read docs/development/config-profiles.yaml:10-49, 620-637; scripts/check_config_profiles.py:90-104
Read docs/development/architecture-baseline.yaml:1-30, 316-329, 1158-1171
Read scripts/check_architecture_principles.py:187-188, 928-934, 984-998, 1158-1171
Read crew_utils.py:60-77; finalize.py:20 (is_crew_agent import)
Grep "boot_prefixes|AD-1270" tests/test_bf927_boot_claims.py  no AD-1270 claim prefix
Grep "ChainTuningConfig" tests/test_ad639_chain_tuning.py:14   from probos.config
Grep "^\s*# Phase \d+" runtime.py                             Phase 2 2853, 5 3159, 7 3255, 8 3595
```

## Verified Against Codebase (Amendment A1, 2026-10-28, on `31066065`)

```
Read startup/dreaming.py:225-307                     BF-034 detector: :256-261 generic prior, :262 `not episodic_memory`, :265 suppression, :276-301 announcement; :305-306 M2's note
Grep '^class EpisodicMemory' cognitive/episodic.py   :1358, no base class
Grep 'def __len__|def __bool__|_collection\.count\(\)|def is_empty' cognitive/episodic.py   no __len__/__bool__; count() call sites only
Read cognitive/episodic.py:1644-1683, 4261-4293      start(); count_for_agent; get_stats() returns {"total": 0} for an empty or unstarted store
Grep 'get_stats\(\)' src/probos                      introspect.py:678, commands_status.py:25, cognitive/dreaming.py:241 await episodic_memory.get_stats()
Read startup/cognitive_services.py:577-596           AD-502: session_last.json gives stasis_recovery, else first_boot
Read __main__.py:696-717, 2642-2679; startup/shutdown.py:876-889   BF-141 writes the record at shutdown; reset tier 2 deletes it, tier 1 keeps it; a failed start never creates one
Read runtime.py:3318-3339; Grep 'is_cold_start|_cold_start\b' src   coordinator needs a memory object; readers in R10
Read agent_onboarding.py:240-271; tiered_trust.py:55-86; consensus/trust.py:340-371   AD-640 role priors via create_with_prior
Read boot_camp.py:90-200, 380-540                    activate enrols per agent; _expire_if_timed_out docstring; get_state raw
Read startup/finalize.py:860-910, 4190-4211, 6326-6355   activation helper; BF-261 block; AD-435 lifecycle titles
Read cognitive/cognitive_agent.py:6009-6264, 6343-6509   both producers; triage; fallback :6391; phase 2 :6457
Read cognitive/cognitive_agent.py:1708-1713, 3032-3075, 9674-9758   journal property; DM roster hasattr guards; sensorium guards
Read sub_tasks/evaluate.py:386-575; sub_tasks/reflect.py:368-490   guards before the boot-camp and low-band branches
Read tests/test_ad1347_s4_chain_lookup.py:1-245      the routed harness §7.17 copies
Grep 'low_trust_ceiling|enabled: bool' config_models/knowledge.py   ChainTuningConfig enabled True, low_trust_ceiling 0.60
Read logs/ad1270/evidence-ad1270bbr1a-expiry-contract.txt, -expiry-memory-fix-final.txt, -boundary-artifacts.txt:1-12   reviewer A's runs; line 10 real low-band verdicts
git log -S "episodes_empty = not" -- src/probos      36a7ffee (2026-03-25, BF-034); 0e4f91d6 (AD-517 move)
```

## Verified Against Codebase (Amendment A2, 2026-10-28, on `8855783b`)

```
rg -n "_sub_task_executor\.execute\(" src/probos/cognitive/cognitive_agent.py
  5752 (_maybe_dispatch_oracle_lookup), 5815 (_maybe_dispatch_ward_room_lookup), 6100 (_execute_sub_task_chain), 6366 (_execute_chain_with_intent_routing, triage), 6559 (_re_reflect_with_feedback)
rg -n "sub_task_type=SubTaskType.QUERY" cognitive_agent.py   5741, 5805 (the two lookups' only specs)
cognitive_agent.py:6052-6079   direct producer block + AD-639 band + debug log
cognitive_agent.py:6242-6265   routed producer block + AD-639 band (no debug log)
rg -n "^ {40}# BF-263: Use self\.id" cognitive_agent.py   6066, 6256 (40-space indentation, reproduced in P-S2 and P-S3)
cognitive_agent.py:6511-6513   phase 2c calls _re_reflect_with_feedback(full_chain, observation, chain_result)
cognitive_agent.py:6558-6559   try: / reflect_results = await self._sub_task_executor.execute(
cognitive_agent.py:3846, 3985, 10485   decide -> _decide_via_llm -> _build_user_message -> AD-683 read
reflect.py:449-462   boot_camp bypass, "bypass_reason": "boot_camp"
reflect.py:471-484   low band, "reflection": "low_trust_band_bypass"
finalize.py:883-900  _is_new_crew_start; `return stats.get("total") == 0` at :900, outside the try
episodic.py:4282-4313  get_stats returns {"total": <int>, ...}
check_architecture_principles.py:558-569, 937-944   srp-size counts methods, compares triggers only
architecture-baseline.yaml:407-412   CognitiveAgent triggers [lines, methods]
test_trigger_learning.py:317-344   TestReReflect agent = MagicMock()
test_bf206_confab_feedback.py:111  CognitiveAgent.__new__ (real class: the helper resolves)
```

## Absence Verified (Amendment A2, 2026-10-28)

```
CLAIM: nothing else in src writes _boot_camp_active
RUN:   rg -n "_boot_camp_active|_chain_trust_band" src/probos
FOUND: writes cognitive_agent.py:6055/6057, 6245/6247 only; reads sub_task.py:720,722; evaluate.py:142,230,532,554; reflect.py:109,197,279,449,471; cognitive_agent.py:6000,10485
HOLDS: yes

CLAIM: SpeculationExecutor has no caller
RUN:   rg -n "speculation_executor\.|\.dispatch_anticipatory\(" src/probos ; rg -n "SpeculationExecutor\(" src/probos
FOUND: none ; finalize.py:2820 (construction only)
HOLDS: yes

CLAIM: only TestReReflect calls the three chain methods unbound
RUN:   rg -c "CognitiveAgent\._(execute_sub_task_chain|execute_chain_with_intent_routing|re_reflect_with_feedback)\(" tests
FOUND: tests/test_trigger_learning.py: 4
HOLDS: yes

CLAIM: no test asserts the AD-639 debug line
RUN:   rg -n "AD-639: " tests
FOUND: no "AD-639: %s trust" match
HOLDS: yes

CLAIM: nothing outside this slice references the renamed AST test
RUN:   rg -n "test_both_chain_entry_points_ask_for_the_relaxation_not_enrolment"
FOUND: tests/test_ad1270_boot_camp_trust.py:244; contract :175, :582, :2081
HOLDS: yes
```

## Absence Verified (2026-10-28)

```
CLAIM: nothing assigns runtime.boot_camp before Phase 7
RUN:   Grep '\.boot_camp\s*=[^=]|setattr\([^)]*boot_camp' src/
FOUND: runtime.py:3330 (Phase 7); runtime.py:1244 initialises it to None
HOLDS: yes -- dreaming.py:306 (Phase 5) always sees None

CLAIM: on_agent_dm, check_timeout and run_phase_2/3 have no production caller; force_graduate_all only from check_timeout
RUN:   Grep '\.(on_agent_dm|check_timeout|force_graduate_all|run_phase_2_introductions|run_phase_3_observation|check_graduation|activate)\(' src/
FOUND: boot_camp.py:449,457,465; dreaming.py:319; capability_requests.py:308, bills.py:176, sop/instance.py:71 (other classes)
HOLDS: yes

CLAIM: is_conn_qualified and grant_conn are reached only through the /conn slash command, and nothing calls ConnManager.is_authorized (A1: corrected. Any sender that can run a slash command reaches /conn: the entries below, the webhook adapter included, which reviewer A executed after its shared-secret check; R11)
RUN:   Grep 'is_conn_qualified|conn_manager\.grant|def grant\(|check_escalation|def grant_conn|\.grant_conn\(' src/; Grep '\.is_authorized\(' src/; Grep 'cmd_conn|_handle_slash_command' src/
FOUND: commands_autonomous.py:91,96; conn.py:78,165; runtime.py:2102,2158,2164; watch_rotation.py:420. is_authorized: mcp_workbench.py:397,475,723 (MCP access, another class). Entry: shell.py:302,528; api.py:77; channels/base.py:368; routers/chat.py:101
HOLDS: yes

CLAIM: nothing subscribes to BOOT_CAMP_* events
RUN:   Grep 'boot_camp|BOOT_CAMP_|BootCamp' src/ (excluding boot_camp.py); Grep 'boot_camp|BOOT_CAMP' ui/src
FOUND: events.py:404-408,492; event_persistence.py:142-146; config and wiring sites; ui: none
HOLDS: yes

CLAIM: no test drives the real TrustNetwork through activate or is_conn_qualified
RUN:   Grep 'get_trust_score' tests/; Grep 'is_conn_qualified|cmd_conn' tests/
FOUND: every get_trust_score site is a MagicMock; test_autonomous_operations.py:54,83 (simulated); test_commands_autonomous.py:35-54 (no grant)
HOLDS: yes

CLAIM: cognitive_agent.py calls is_enrolled only at the two chain entry points; the new names collide with nothing
RUN:   Grep 'is_enrolled|relaxes_quality_gates' src/; Grep 'self\.get_score\(|relax_quality_gates|_expire_if_timed_out|_graduate_remaining_on_timeout|_activate_boot_camp_on_cold_start' src/probos
FOUND: cognitive_agent.py:6054,6242 (plus unrelated perception is_enrolled); second grep: none
HOLDS: yes

CLAIM (A1): runtime._cold_start is set at Phase 5 and nothing clears it for the session
RUN:   Grep 'is_cold_start|_cold_start\b' src/
FOUND: assignments runtime.py:1241 (init), :3207 (Phase 5); dream_adapter.py:116, :144 set and clear only the adapter's own copy, copied from runtime at finalize.py:6193
HOLDS: yes

CLAIM (A1): EpisodicMemory defines neither __len__ nor __bool__ and has no base class
RUN:   Grep 'def __len__|def __bool__|_collection\.count\(\)|def is_empty' cognitive/episodic.py; Grep '^class EpisodicMemory' cognitive/episodic.py
FOUND: _collection.count() call sites only; class EpisodicMemory: at :1358
HOLDS: yes -- an instance is truthy, so dreaming.py:262 reads every live memory as non-empty

CLAIM (A1): nothing in src reads the proactive conn_authority context value
RUN:   Grep 'conn_authority' src/probos
FOUND: proactive.py:2555 (the write) only
HOLDS: yes by name; reviewer A's run (evidence-ad1270bbr1a-boundary-artifacts.txt:6-7) found neither its role text nor conn_scope in the holder's prompt

CLAIM (A1): no test seeds _boot_camp_active and then calls a chain entry point expecting it honoured
RUN:   Grep '_boot_camp_active' tests/; Grep '_execute_sub_task_chain\(|_execute_chain_with_intent_routing\(' tests/ (files)
FOUND: seeders test_ad638_boot_camp.py:338,363, test_ad639_chain_tuning.py:137,200,319, test_ad658_chain_harness_metrics.py:192 are not among the 11 entry-point files; test_ad1270_boot_camp_trust.py:233 asserts absence
HOLDS: yes

CLAIM: no test pins the dreaming.py block or TrustNetwork's member list
RUN:   Grep '_activate_boot_camp|Boot camp activation failed|Boot camp activated for' tests/; Grep '(getmembers|vars|dir)\(TrustNetwork|TrustNetwork\.__dict__' tests/
FOUND: none; none
HOLDS: yes
```

## Not verified (the orchestrator verifies by running)

- Every predicted count: test cases, the census figures, the facade diff and the failing-case lists on each base.
- That the AD-632g harness reaches `cognitive_agent.py:6054` in the [off] case without raising later in `_execute_sub_task_chain`. If it raises, keep the assertion on `observation` and wrap the call in `contextlib.suppress(Exception)` with a reason comment.
- That real-boot tests that pass an episodic memory, enable the Ward Room and boot a fresh data directory still pass (A1: these now activate the boot camp; before A1 none did). `test_bf927_boot_claims.py:545` passes no memory, so it builds no coordinator; the broad gate covers the rest.
- (A1) That §7.17's harness reaches the real Evaluate and Reflect handlers with its minimal runtime. If any case raises before its assertions on `31066065`, stop and report; do not wrap the call.
- (A1) That a real `EpisodicMemory.start()` on `tmp_path` completes in the focused gate (26 test files construct one on `tmp_path`; `tests/benchmarks/test_locomo_episodic.py:58-59` starts one).
- That `BootCampCoordinator`'s body stays ≤ 500 lines (predicted about 465).

## 12. Deterministic gate checks, resolved up front

- `check_architecture_principles.py --check`: P-Z1 lowers `init_dreaming` to `count: 1`. `finalize.py` gains no bare task. `BootCampCoordinator` keeps `[methods]`. (A2) `CognitiveAgent` gains one method, `_refresh_boot_camp_relaxation`, and keeps `[lines, methods]`: an `srp-size` row records triggers only (`check_architecture_principles.py:937-944`), so no row changes.
- `check_config_facade.py`, `gen_config_reference.py`, `check_config_profiles.py`: regenerated or paired in M1.
- `check_dormant_classes.py --check`: unchanged (no class becomes live or dormant).
- Test collection: two new files; no manifest lists them.

## 13. Prior Art and Blind Spots

- **Internal:**
  - `prompts/archive/ad-638-cold-start-boot-camp.md:45,142`: the narrow protocol was designed with `get_trust_score`. Kept, and the concrete class now implements it.
  - `decisions-era-4-evolution.md:1681` (BF-091): an earlier phantom `get_trust_score` was fixed by renaming to `get_score` in tests. Not followed here because the production protocols already carry the name (D1).
  - `DECISIONS.md:6746` (AD-702): the gap is recorded there; it is closed now.
  - The AD-640 tiered-trust research memory: tiers set before Phase 8, so chiefs are skipped correctly.
  - The Tucker onboarding case study (crew onboard newcomers themselves): informs the phase 2/3 retirement in 4c.
- **External:** skipped. This is ProbOS-specific repair plumbing with no outside design to borrow. `docs/research/reference-projects.md` was not examined (nothing new designed).
- **Blind spots found:**
  - (1) Activation was dead by startup order (P5), not only by the missing method.
  - (2) AD-639 already covers the relaxation's population (P8).
  - (3) `ConnManager.is_authorized` has no production caller, and `conn_authority` (`proactive.py:2555`) has no reader, so the conn's scope is neither enforced nor shown to the holder (R8; A1 corrects "prompt text only").
  - (4) Channel adapters without pairing can send any slash command, `/conn` included.
  - (5) DMs an agent only *replies* to inside a DM thread may not pass through `[DM @x]` extraction. Such an agent graduates only by timeout, which bounds it.
  - (6) Activation is awaited inline at startup. A slow AD-683 snapshot build would delay startup; it reads empty stores on a cold start.
  - (7) A1: BF-034's flag is false whenever a memory object exists (R10), so the draft's gate could not open; a boot-camp-local new-crew test replaces it. `get_stats()` reads every episode's metadata on a non-empty store, but the lifecycle check comes first, so that read happens only on a boot with no session record.
  - (8) A1: the routed chain's phase 2 and its fallback reuse triage's observation, so any per-chain answer stored on it must be asked again; the producer now clears the marker before it asks.
  - (9) A2: the AD-643b feedback Reflect (`_re_reflect_with_feedback`) is a third chain phase on the same observation, so the producer became one helper rather than a third copy, and an AST guard classifies every method that executes a chain. Two other reads of a reused observation remain: the AD-683 injection when a chain falls through to the single call (R6 rekeys it) and the default-off AD-272 decision cache, which replays a decision rather than re-running a gate (unchanged). `SpeculationExecutor` has no caller.
  - (10) A2: a malformed `get_stats()` answer raised past `_is_new_crew_start`'s own catch; the whole interpretation is inside it now. `{"total": False}` compares equal to 0 and reads as empty; no memory returns it (`episodic.py:4282-4313` returns an int count), so it is left.

## 14. Diff Reviewer: properties to verify

1. `TrustNetwork.get_trust_score` calls `self.get_score`; it is not an alias, and `get_score` is unchanged.
2. With `relax_quality_gates` false, nothing in the diff sets `_boot_camp_active`, and `evaluate.py` and `reflect.py` are unchanged.
3. No line in `BootCampCoordinator` reads `time.time()` or `time.monotonic()`. `is_active`, `is_enrolled`, `check_graduation`, `on_agent_post`, `on_agent_dm` and `check_timeout` call `_expire_if_timed_out()` first; `relaxes_quality_gates` reaches it through `is_enrolled` when the flag is on; `get_state` does not, and no docstring says it does. The timeout deletes no state and calls nothing on the trust network.
4. `BOOT_CAMP_TIMEOUT` is emitted at most once per activation.
5. Activation runs only when `_is_new_crew_start(runtime)` is true (`_lifecycle_state` is `first_boot` or `reset`, and `episodic_memory.get_stats()["total"] == 0`; a failed read is not a new crew), once, awaited, after the BF-261 late-bind, inside `try/except` with a warning that says only that startup continues. It does not read `runtime.is_cold_start`, and no reader of that flag changes. A stasis recovery activates nothing. Nothing in `dreaming.py` references `boot_camp`.
6. The DM count sits after a successful crew DM only (not the Captain branch, not a skipped DM), and its failure cannot change the DM's actions or return.
7. Each generated file was produced by its tool. `config/system.yaml` is staged as one comment hunk.
8. The tracker claims match §0 and §11.
9. (A1, as amended by A2) `_boot_camp_active` is written only in `CognitiveAgent._refresh_boot_camp_relaxation`, which removes it before `relaxes_quality_gates` is asked and sets it only on a true answer. `_execute_sub_task_chain`, `_execute_chain_with_intent_routing` and `_re_reflect_with_feedback` each call it before they execute their chain. The helper's body is the two removed blocks' text (the routed entry now also writes AD-639's debug line). A chain whose relaxation ends during triage runs phase 2 with AD-639's band and no boot-camp bypass, and one whose relaxation ends during phase 2a runs the feedback Reflect the same way.
10. (A1) Each changed sentence in code, tests and §8 is true: the expiry docstrings name the readers that expire; the activation comment and warning claim no rollback; U2 does not say only the Captain reaches `/conn`.
11. (A2) Every method in `cognitive_agent.py` that calls `self._sub_task_executor.execute(` is a gating phase that calls the helper or a lookup whose chain is QUERY only, and the AST test fails when one is added unclassified. `TestReReflect`'s four cases pass unchanged.
12. (A2) `_is_new_crew_start` returns False, and raises nothing, for a `get_stats()` answer of `None`, a list, an int or a mapping without `total`; it still returns True for `{"total": 0}` on `first_boot` and `reset`; its docstring says exactly that. The new malformed cases build no coordinator; the new feedback cases build theirs through `_coordinator`.
13. (A2) D4's event sentence, D10, §5, §6, U1, U2 and the R1 test docstring are true of the R2 tree; U1's head line and U2's heading are unchanged.

## 15. Acceptance criteria

- The three new files pass (`tests/test_ad1270_boot_camp_trust.py`, `tests/test_ad1270_boot_camp_lifecycle.py`, `tests/test_ad1270_boot_camp_repair_a1.py`). Every listed mutant is killed except D-2 (equivalent); S-1 and S-2 are A1's rewrites, and T-5 and A-1 to A-3 are A2's.
- `isinstance(TrustNetwork(), TrustNetworkProtocol)` is true.
- `check_architecture_principles.py --check` and `check_dormant_classes.py --check` pass; for the dormant check, paste its whole output.
- The focused gates pass, and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R4 (slice 4c, HIGH): retire the AD-509 `BootCampPhaseTracker`.** It deletes:
  - `crew_development/boot_camp.py` and its exports at `crew_development/__init__.py:17-20,40-42`;
  - `_wire_boot_camp_tracker` and its call (`finalize.py:883-899`, `4151-4152`);
  - `BootCampPhaseConfig` and `SystemConfig.boot_camp_phase` (`config.py:3706`, `:4128`) and the `boot_camp_phase:` section (`system.yaml:2346-2347`);
  - the AD-509 tests.

  It must also decide about `BOOT_CAMP_PHASE_ADVANCED` (`events.py:492`, `event_persistence.py:145`) after the live count, and pin that a config still carrying `boot_camp_phase:` loads (the BF-926 precedent).
- **R5 (slice 4c): retire phases 2 and 3.** That covers `run_phase_2_introductions`, `run_phase_3_observation`, `_DEPARTMENT_CHIEFS`, the nudge cooldown and `nudge_cooldown_seconds`, the observation-thread state and `shared_observation`. Reason: no caller, and the posts are written in the Counselor's name without the Counselor composing them. The Captain can overrule.
- **R6 (slice 4c): wire the AD-683 snapshot injection** (`cognitive_agent.py:10481`) on enrolment instead of `_boot_camp_active`, with a `_build_user_message` test. Replace BF-261's private write `_bc._ship_state_builder` (`finalize.py:4174`) with a public setter. A2: this also ends the one read of a phase's `_boot_camp_active` after its chain returns: when a chain falls through to the single call (`decide` → `_decide_via_llm` → `_build_user_message`), the injection reads the last phase's answer, so with the flag on, a relaxation that ended during that chain can add the snapshot once more.
- **R7 (slice 4c, STANDARD): fix `holodeck/chamber.py:289`**, `m.id` → `m.module_id`, with a test on `HOLODECK_PHASE_ENTERED.modules`.
- **R8 (staged, owner #1324, unscheduled):** `ConnManager.is_authorized` has no production caller, so nothing enforces the conn's scope. `_gather_context` writes `conn_authority` (`proactive.py:2555`), but nothing in `src` reads it, and reviewer A's run found neither the role text nor `conn_scope` in the holder's proactive prompt (A1 corrects "prompt text only"). Recommendation: wire `is_authorized` at the actions the scope names, and render the scope in the holder's prompt, with a `_build_user_message` test (in the envelope). Who may run `/conn` is R11.
- **R9 (after the first live cold start):** compare AD-639 skip lines with enrolled agents. If AD-639 covered them, retire `relax_quality_gates` and its producer path.
- **R10 (A1; owner #1324; its own BF, before or with slice 4c; BF number unresolved, enumerate it when filed per `.github/copilot-instructions.md:92`): BF-034's cold-start detector.** It has never fired with a memory object present since it landed (`36a7ffee`, 2026-03-25): `dreaming.py:262` reads the memory object's truthiness, and `:257-261` compares every record with the generic prior, which AD-640's bridge and chief priors differ from. Its readers stay dormant: the 5-minute trust-anomaly suppression (`dreaming.py:265`), the "Fresh Start" All Hands thread (`:276-301`), `_lifecycle_state = "reset"` (`runtime.py:3208-3209`; it also changes AD-435's startup title, `finalize.py:6348-6355`), the fresh-start prompt notes (`cognitive_agent.py:9276`, `:10917`; `proactive.py:1751`), `dream_adapter._cold_start` (`finalize.py:6193`) and the skipped auto-welcome (`finalize.py:6441`). `runtime._cold_start` is never cleared, because the AD-517 extraction left the post-dream clear on the adapter's own copy (`dream_adapter.py:143-145`), so a repaired detector would keep "you have no prior episodic memories" in every prompt for the whole session. Recommendation: wire. Use one predicate shared with `_is_new_crew_start`, clear or bound the session flag in the same BF, and add a detector-to-reader test with stasis-recovery and restart controls. It is agent-facing at the next reset and restores designed behaviour: in the envelope, and the Captain is told.
- **R11 (A1; staged, owner #1324; a security-surface decision for the Captain): who can send `/conn`.** It is a slash command, so the shell, the API chat route (`api.py:77`, `routers/chat.py:101`) and channel adapters (`channels/base.py:367-369`) reach the grant, and so does the webhook adapter after its shared-secret check (reviewer A executed it). Recommendation: limit `/conn`, or slash commands generally, to the Captain's console and paired senders. Who may hold that power is the Captain's decision.
- **R12 (A1; slice 4c, owner #1324):** `relax_quality_gates` (`config_models/crew.py:28`) has no `Field(description=...)`, so its generated reference row is blank (reviewer A, property 4); the safety note lives only in `system.yaml` and `config-profiles.yaml`. Recommendation: wire. Add `BootCampConfig` field descriptions in 4c, and regenerate the facade baseline and the reference by tool.
- **R13 (A1; slice 4c, with R6):** the ordering test does not detect removal of the BF-261 late-bind (reviewer B, property 5); A1 covers only the await. Recommendation: land R6's public setter with a behavioural test that activation's snapshot capture uses the late-bound builder.
