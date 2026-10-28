# AD-1270 (#1324) slice 4b: the AD-638 boot camp repair -- TrustNetwork.get_trust_score (which also repairs /conn), activation moved to finalization, a timeout enforced by construction, crew DMs counted, and the Evaluate/Reflect relaxation behind a default-off flag

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

**Status:** build-ready. Drafted on `4fd31e6c` (`origin/main` `4aa1062f` + the slice-3 contract `8da8da16` + slice 3's M1). It builds after slice 3 and slice 4 merge. No new AD or BF number: this is slice 4b of #1324 (D7). **Captain:** only `boot_camp.relax_quality_gates` being switched on (a weakened control); it ships off and nothing is parked (D9). Overrulable: D2 (no enrolment flag), D5 (crew DMs only), the 4c dispositions in the register.

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
| A real-boot test is a cold start | `tests/test_bf927_boot_claims.py:545-547` |

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
  - The event fires at the first read after the deadline.
- **D5.** Crew DMs count; DMs to the Captain and unsent DMs do not. A counting failure is logged at debug (as at `proactive.py:4115`): the DM stands and the timeout bounds the miss.
- **D6.**
  - Activation runs once, awaited, in `finalize_startup` after the BF-261 snapshot late-bind, gated on `runtime.is_cold_start` (a property, `runtime.py:2238-2241`).
  - It uses `is_crew_agent` (`crew_utils.py:69`). No live behaviour changes, because the old block never ran.
  - Log-and-degrade: a failure leaves the crew unenrolled and startup continues.
- **D7.** No BF: one root cause, one change, already on the #1324 register.
- **D8.** The rest is slice 4c (register R4 to R7).
- **D9.** Captain: only switching `relax_quality_gates` on.

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

## 5. Consumers of every value this adds or changes

| Value | Consumers | Effect |
|---|---|---|
| `TrustNetwork.get_trust_score` | `boot_camp.py:160,224`, `runtime.py:2116` | from AttributeError to the `get_score` value |
| `boot_camp.relax_quality_gates` | `BootCampCoordinator.relaxes_quality_gates` only; `config-reference.md`; `config-profiles.yaml` row | new, default off |
| `BootCampCoordinator.relaxes_quality_gates` | `cognitive_agent.py` `_execute_sub_task_chain`, `_execute_chain_with_intent_routing` | new public method |
| `_boot_camp_active` (observation key) | evaluate, reflect, AD-639 skip, AD-683 injection, journal | set only when the flag is on (was: on enrolment) |
| `BootCampCoordinator(clock=...)` | tests; `runtime.py:3330` (default) | new keyword-only argument |
| Reads after the timeout | `is_active`, `is_enrolled`, `relaxes_quality_gates`, `check_graduation`, `on_agent_post`, `on_agent_dm`, `check_timeout` | enrolment ends; one `BOOT_CAMP_TIMEOUT` |
| `force_graduate_all` with nobody remaining | `test_ad638` timeout tests | now also sets `_active=False` |
| Crew DM count | `on_agent_dm` from `proactive.py` | new caller |
| `_activate_boot_camp_on_cold_start` | `finalize_startup` | new; every cold-start boot, including test boots on a fresh `tmp_path` |
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
- `test_both_chain_entry_points_ask_for_the_relaxation_not_enrolment` (AST)

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

## 8. Tracking (M3's commit)

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 4b -- the AD-638 boot camp is repaired, and `/conn` works.** Two independent defects kept the boot camp inert: `TrustNetwork` had no `get_trust_score` (declared by `protocols.TrustNetworkProtocol` and the coordinator, called three times, mocked by every test), and cold-start activation ran in `startup/dreaming.py` at Phase 5, before the coordinator is built at Phase 7, so its guard was always false. `TrustNetwork.get_trust_score` now calls `get_score`, which also lets `/conn <callsign>` grant the conn to a COMMANDER+ bridge officer or chief (it raised before). Activation moved into finalization, after the AD-683 snapshot late-bind; `timeout_minutes` is enforced by every coordinator read, with no task; a crew DM sent through the proactive path counts toward graduation; the coordinator reads time through an injected clock. AD-638's Evaluate/Reflect auto-approval is behind `boot_camp.relax_quality_gates` (default false): off, enrolment changes no agent's prompt, chain, trust or authority, and switching it on is the Captain's call. The AD-509 phase tracker, phases 2 and 3, AD-683's snapshot injection and `holodeck/chamber.py:289` are slice 4c. The contract is `prompts/ad-1270-boot-camp-repair.md`.

```

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- the AD-638 boot camp is repaired: a protocol method, activation at finalization, a timeout by construction, DM counting, and the relaxation behind a default-off flag (2026-10-2X)

**Decision.** Add `TrustNetwork.get_trust_score`, delegating by call to `get_score`, rather than renaming three callers, two protocols and about thirteen mocks; a call (not a class alias) keeps instance patches of `get_score` governing both reads. Move AD-638 activation from `startup/dreaming.py` (Phase 5, where `runtime.boot_camp` is always `None`) into `finalize_startup`, after the AD-683 snapshot late-bind. Enforce `timeout_minutes` in every coordinator read rather than with a task; a timeout graduates the remaining agents, emits one `BOOT_CAMP_TIMEOUT`, and deletes or demotes nothing. Count crew DMs at the proactive DM path; DMs to the Captain do not count. Gate the Evaluate/Reflect auto-approval at its producer through `BootCampCoordinator.relaxes_quality_gates` and `boot_camp.relax_quality_gates: false`, so that off, an enrolled agent's Evaluate, Reflect and AD-639 tuning run as for any other agent. **Why.** The boot camp had a caller but no reachable path: the guard ran before its object existed, and the method it called existed only on mocks. With the relaxation off, enrolment is bookkeeping and events of existing types, so it needs no flag of its own; `boot_camp.enabled` remains the off switch. **Captain.** Switching `relax_quality_gates` on weakens the anti-confabulation gate; it is his call. AD-639's low-trust band (`chain_tuning.low_trust_ceiling` 0.6) already skips Evaluate and Reflect for every agent the boot camp enrols (trust below 0.55), so the recommendation is to retire the relaxation after the first live cold start rather than enable it. `/conn` was restored as AD-471 specified it; only the Captain's command reaches it, and no permission check reads the conn. **Rejected.** Renaming to `get_score` everywhere (wider blast radius, a shared-protocol change); a separate enrolment flag (duplicates `boot_camp.enabled`, protects no agent-visible effect); gating Evaluate and Reflect at the consumers (leaves AD-639 suppressed for enrolled agents); a timeout task (one more lifecycle to own).

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

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline of M1's and M2's focused lists passes; run on the Captain's Windows host)

A Line cell whose text occurs twice says so: mutate every occurrence.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| T-1 | M1 | `consensus/trust.py` | `return self.get_score(agent_id)` | `return 0.5` | `test_get_trust_score_is_get_score[recorded-agent]`, `test_get_trust_score_follows_a_patched_get_score` |
| T-2 | M1 | `config_models/crew.py` | `relax_quality_gates: bool = False` | `relax_quality_gates: bool = True` | `test_the_relaxation_is_off_by_default`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]` |
| T-3 | M1 | `boot_camp.py` | `return self._config.relax_quality_gates and self.is_enrolled(agent_id)` | `return self.is_enrolled(agent_id)` | `test_an_enrolled_agent_relaxes_only_when_the_flag_is_on[off]`, `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]` |
| T-4 | M1 | `boot_camp.py` | `return self._config.relax_quality_gates and self.is_enrolled(agent_id)` | `return self._config.relax_quality_gates` | `test_an_agent_not_enrolled_never_relaxes[unknown]`, `test_an_agent_not_enrolled_never_relaxes[graduated]` |
| T-5 | M1 | `cognitive/cognitive_agent.py` | `if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.relaxes_quality_gates(self.id):` (occurs twice) | `if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):` | `test_the_chain_marks_boot_camp_only_when_the_relaxation_is_on[off]`, `test_both_chain_entry_points_ask_for_the_relaxation_not_enrolment` |
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
| S-1 | M2 | `startup/finalize.py` | `if coordinator is None or not runtime.is_cold_start:` | `if coordinator is None:` | `test_cold_start_finalization_enrols_crew[warm]` |
| S-2 | M2 | `startup/finalize.py` | `if coordinator is None or not runtime.is_cold_start:` | `if not runtime.is_cold_start:` | `test_no_coordinator_or_no_crew_means_no_activation` |
| S-3 | M2 | `startup/finalize.py` | `if is_crew_agent(agent, ontology)` | `if True` | `test_cold_start_finalization_enrols_crew[cold]` |
| S-4 | M2 | `startup/finalize.py` | `if not crew_agents:` | `if False:` | `test_no_coordinator_or_no_crew_means_no_activation` |
| S-5 | M2 | `startup/finalize.py` | `await coordinator.activate(crew_agents)` | `pass` | `test_cold_start_finalization_enrols_crew[cold]` |
| S-6 | M2 | `startup/finalize.py` | `await _activate_boot_camp_on_cold_start(runtime=runtime)` | `pass` | `test_finalization_activates_the_boot_camp_after_the_snapshot_late_bind` |

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

CLAIM: only the Captain's /conn command reaches is_conn_qualified and grant_conn; no permission check reads the conn
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

CLAIM: no test pins the dreaming.py block or TrustNetwork's member list
RUN:   Grep '_activate_boot_camp|Boot camp activation failed|Boot camp activated for' tests/; Grep '(getmembers|vars|dir)\(TrustNetwork|TrustNetwork\.__dict__' tests/
FOUND: none; none
HOLDS: yes
```

## Not verified (the orchestrator verifies by running)

- Every predicted count: test cases, the census figures, the facade diff and the failing-case lists on each base.
- That the AD-632g harness reaches `cognitive_agent.py:6054` in the [off] case without raising later in `_execute_sub_task_chain`. If it raises, keep the assertion on `observation` and wrap the call in `contextlib.suppress(Exception)` with a reason comment.
- That real-boot tests on a fresh `tmp_path` (now cold starts that activate the boot camp) still pass. `test_bf927_boot_claims.py::test_the_booted_vessel_prints_the_reworded_lines` and the AD-1185 smoke boot are in M2's focused list; the broad gate covers the rest.
- That `BootCampCoordinator`'s body stays ≤ 500 lines (predicted about 465).

## 12. Deterministic gate checks, resolved up front

- `check_architecture_principles.py --check`: P-Z1 lowers `init_dreaming` to `count: 1`. `finalize.py` gains no bare task. `BootCampCoordinator` keeps `[methods]`.
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
  - (3) `ConnManager.is_authorized` has no caller, so the conn's scope is prompt text only.
  - (4) Channel adapters without pairing can send any slash command, `/conn` included.
  - (5) DMs an agent only *replies* to inside a DM thread may not pass through `[DM @x]` extraction. Such an agent graduates only by timeout, which bounds it.
  - (6) Activation is awaited inline at startup. A slow AD-683 snapshot build would delay startup; it reads empty stores on a cold start.

## 14. Diff Reviewer: properties to verify

1. `TrustNetwork.get_trust_score` calls `self.get_score`; it is not an alias, and `get_score` is unchanged.
2. With `relax_quality_gates` false, nothing in the diff sets `_boot_camp_active`, and `evaluate.py` and `reflect.py` are unchanged.
3. No line in `BootCampCoordinator` reads `time.time()` or `time.monotonic()`. Every public reader and tracker calls `_expire_if_timed_out()` first. The timeout deletes no state and calls nothing on the trust network.
4. `BOOT_CAMP_TIMEOUT` is emitted at most once per activation.
5. Activation runs only when `runtime.is_cold_start` is true, once, awaited, after the BF-261 late-bind, inside `try/except` with a warning. Nothing in `dreaming.py` references `boot_camp`.
6. The DM count sits after a successful crew DM only (not the Captain branch, not a skipped DM), and its failure cannot change the DM's actions or return.
7. Each generated file was produced by its tool. `config/system.yaml` is staged as one comment hunk.
8. The tracker claims match §0 and §11.

## 15. Acceptance criteria

- Both new files pass. Every listed mutant is killed except D-2 (equivalent).
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
- **R6 (slice 4c): wire the AD-683 snapshot injection** (`cognitive_agent.py:10481`) on enrolment instead of `_boot_camp_active`, with a `_build_user_message` test. Replace BF-261's private write `_bc._ship_state_builder` (`finalize.py:4174`) with a public setter.
- **R7 (slice 4c, STANDARD): fix `holodeck/chamber.py:289`**, `m.id` → `m.module_id`, with a test on `HOLODECK_PHASE_ENTERED.modules`.
- **R8 (staged, owner #1324, unscheduled):** `ConnManager.is_authorized` has no caller, so the conn's scope limits are prompt text only. Channel adapters without pairing can send any slash command (`channels/base.py:367-369`). Wiring `is_authorized` would add enforcement (in the envelope). Restricting which channel senders may run slash commands is a security-surface decision to bring to the Captain.
- **R9 (after the first live cold start):** compare AD-639 skip lines with enrolled agents. If AD-639 covered them, retire `relax_quality_gates` and its producer path.
