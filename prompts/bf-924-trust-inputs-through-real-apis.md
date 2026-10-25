# BF-924: trust inputs are read through APIs that exist (#1654): the procedure-compilation clamp reads the agent's live trust, profile trust history and avatar trust delta come from `TrustNetwork.get_history`, `/grant list` names a target by certificate, and `CounselorConfig` is read or removed

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A1, after the oracle run)

**Status:** build-ready. One BF, two milestones, one PR, one gate; #1654 closes with it. **BF number:** BF-924 (#1654); this contract allocates nothing. **Tier:** M1 **HIGH** (the AD-535/536 trust clamp: it decides how much an agent may replay without the LLM, and its failure mode is fail-closed by design); M2 **STANDARD** (no safety property: every wired value defaults to the constant it replaces, F05 is Captain-only, F04's effect is a display and a voice pitch). Review the batch at HIGH because M1 is: use the Copilot `Diff Reviewer`. **Base:** written against `ba45c61f` (BF-923's branch head on `origin/main` `7808d182`); BF-923 merges first as a merge commit with this tree; the orchestrator re-verifies every SEARCH on the merge SHA, and a changed REPLACE returns to the Architect. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf924_compilation_trust.py` (M1: 6 functions, 7 cases).
- New `tests/test_bf924_trust_inputs.py` (M2: 11 functions, 15 cases).
- Updated pins, M1: `tests/test_graduated_compilation.py` (factory and two inline sites set `_trust_score` by hand), `tests/test_level_5_dispatch.py` (factory). M2: `tests/test_ad722_avatar_telemetry.py` (docstring of the no-method double), `tests/test_ad1260_wellness_domain.py` (`_FakeTrust` gains `get_history`), `tests/test_ad622_clearance_grants.py` (`list_all` invented by a `MagicMock`), `tests/test_counselor_activation.py` (defaults of removed fields), `tests/test_ad1270e2h_emergence_models.py` (the pre-move dump of `CounselorConfig`), `tests/test_ad642_communication_benchmarks.py` (a hand-set `_config` nothing reads), `tests/test_counselor_therapeutic.py` (A1: its `__new__` builder sets `_counselor_config`), `tests/test_ad1270e1_config_facade.py` (A1: the field-count pin, 1880 to 1876).

**Amendment A1 (2026-10-25, after the oracle run on `8f9fd379`: 32 labels applied, the union of the focused lists 4 failed / 1,302 passed).** Every original pair stands; A1 changes only:
1. §7.15 also gives `_FakeTrust.all_scores` the real `crew_only` parameter (the seam test's `all_scores` failure); the seam test stays whole (decision A1-1, section 3).
2. New §7.21: `tests/test_counselor_therapeutic.py`'s `_make_counselor` (`object.__new__`) sets `_counselor_config`, as BF-921 set `_suppression_history` in the same shape of builder (decision A1-2). No production line changes.
3. New §7.22: `tests/test_ad1270e1_config_facade.py`'s `field_definitions` pin, 1880 to 1876, with its comment line.
4. §7.13 gains a second pair: the manifest's `census:` header, re-measured on this tree (decision A1-4).
5. Section 6's expected generated diff is corrected to the exact hunks the oracle produced; the tests-first list gains the field-count pin (19 cases); the collected counts are the oracle's.
6. D4 records the live count (posted on #1654): no active procedure is at Level 3 or above, so F02 restricts no stored procedure today.

## 0. Premise: what is present on this tree

| Claim of #1654 | On `ba45c61f` | Holds |
|---|---|---|
| F02 clamp reads `getattr(self, "_trust_score", 0.5)` at `cognitive_agent.py:1852`, `:7768`; clamp `:2663-2676` | same | yes; nothing assigns `_trust_score` (section 12) |
| `COMPILATION_TRUST_LEVEL_3_MIN = 0.5` `config.py:271` | same; `TRUST_COMMANDER = 0.7` `:217` | yes |
| Rank read `get_score(self.id)` at `:3351` | same (BF-263); also `:2870`, `:6042`, `:6230`, `:9123`, `:11455` | yes |
| F04 callers `routers/agents.py:259-260`, `avatars/telemetry.py:723-728`; `get_events_for_agent` `trust.py:1033` | same | yes; no `TrustNetwork.get_history` (section 12) |
| F04 doubles `_FakeTrustNetwork` in `test_ad722_avatar_telemetry`, `test_ad722b4_fleet_telemetry`, `test_ad722b_websocket_push` | `:71`, `:38`, `:219`, each `get_history(agent_id, limit=20) -> list[float]` | yes; `test_bf711_*:110` (`_Store`) and `test_ad566c_*:54` (`MockQualificationStore`) define a *qualification-store* `get_history`, not a trust one |
| **New, found here:** `test_ad1260_wellness_domain.py:45` `_FakeTrust` reaches the profile route (`:555`) without `get_history` | the route's `hasattr` guard hides it | it gains the method (section 7.15) |
| F05 `commands_clearance.py:171` calls `callsign_registry.list_all()` | same; `CallsignRegistry` `crew_profile.py:660-806` has no `list_all` | yes |
| **New, found here:** a grant's target is the **sovereign** id (`commands_clearance.py:66-71`, `resolve_sovereign_id_from_slot`) | even a `list_all` returning slot ids would never match | repaired through the identity registry (D5) |
| F10 `CounselorConfig` `config_models/emergence.py:251-259`, `config/system.yaml:1176-1182` unread | same; the Counselor never receives the config | yes; constants `counselor.py:1736` (0.15), `:969` (50) |
| **New, found here:** today's Bridge alerts follow no single red/yellow rule | circuit-breaker trips always alert, severity by fitness (`counselor.py:1263`, `:2006`, `:2288`); trust paths alert only when unfit (`:1751`, `:1794`); the sweep never alerts | `alert_on_*` cannot be wired without reducing or inventing alerts (D7) |

## 1. Problem

- **F02.** `_check_procedural_memory` (`cognitive_agent.py:1722`) and the post-execution promotion (`:7755-7785`) read `getattr(self, "_trust_score", 0.5)`; nothing ever assigns the attribute, so every agent counts as a Lieutenant: an Ensign replays Level 3 and 4 procedures without the LLM, and a Commander's approved procedure can never be promoted to Level 5.
- **F04.** `TrustNetwork` has no `get_history`; both callers guard with `hasattr`, so the Captain's profile `trustHistory` is always `[]` and the avatar `trust_delta` is always 0.0 with `insufficient_trust_history`.
- **F05.** `/grant list` raises `AttributeError` for any existing grant.
- **F10.** No `CounselorConfig` field has a reader.

## 2. Solution overview

- **M1.** One helper, `CognitiveAgent._compilation_trust_score()`, reads `self._runtime.trust_network.get_score(self.id)` as the rank read does (`:3351`); both sites use it. A failed or impossible read logs a WARNING and returns 0.0, which takes the Ensign cap (Level 2). No hold (D3). Two test factories that hand-set `_trust_score` now give their runtime a real `TrustNetwork` at that score.
- **M2.** `TrustNetwork.get_history(agent_id, limit=20) -> list[float]` maps `get_events_for_agent` to `new_score`; both callers drop their guards. `/grant list` names a target through its birth certificate and the live callsign. `CounselorAgent` takes the operator's `CounselorConfig` by constructor injection (`agent_fleet.py`) and reads `trust_delta_threshold` and `sweep_max_agents`; the other four fields are removed from the model, `system.yaml` and the profile manifest; the config reference and the facade baseline are regenerated.

## 3. Decisions (for #1654)

**D1, the F02 read.** Ranked: (1, chosen) one helper reading `get_score(self.id)` through the runtime, as BF-263's rank read (`:3349-3353`) and teaching (`:2865-2870`) already do: the trust gauge that decides Rank, agency and the A2UI gate decides the compilation level too; (2) `observation["_trust_score"]` (`:6043`, `:6231`): set only on the two chain paths and only when chain tuning is enabled, and absent at the post-execution promotion (`:7768`); (3) assign `self._trust_score` from `TRUST_UPDATE` events: a second, stale copy of the score with a second writer.

**D2, a failed read.** Ranked: (1, chosen) fail closed: WARNING and 0.0, so the Ensign cap (Level 2) applies and the LLM path still serves the intent; an unknown trust never unlocks replay or Level 5; (2) fail open at 0.5 (today's value): keeps the defect on every failure; (3) raise: the clamp sits in `decide`, so a trust-store fault would fail the intent although the LLM path can serve it. "Absent" (no runtime, or `trust_network` None) is a failed read: production always wires one (`runtime.py:760`).

**D3, no hold (BF-921 D3 does not apply).** `get_score` is already the live gauge for Rank, agency, A2UI, teaching and the profile (section 0); the clamp's consumer is the dispatch level, not a crew-facing judgement; the clamp writes no stored level (section 5a). Ranked: (1, chosen) no hold, with the effects disclosed (E1 to E4) and one read-only count before the build (D4); (2) hold at 0.5 until measured: keeps the defect it measures; (3) shadow (log the level the clamp would have chosen): there is no unqualified gauge to qualify. Within the envelope: the change restricts Ensigns and opens AD-536's designed Level 5 path to Commanders; it weakens no control.

**D4, the count before the build (read-only, the orchestrator).** "Ensign-owned procedures stored at Level 3 or above" is read from three SQLite files under `%LOCALAPPDATA%\ProbOS\data`, each opened read-only (`sqlite3.connect("file:<path>?mode=ro", uri=True)`); the Builder never opens them:
1. `trust.db`, table `trust_scores(agent_id, alpha, beta, updated)` (`consensus/trust.py:32-37`; path `runtime.py:764`): `SELECT agent_id, alpha / (alpha + beta) AS score FROM trust_scores WHERE alpha / (alpha + beta) < 0.5 ORDER BY score`. These are the Ensigns (`get_score` is `alpha/(alpha+beta)`, `trust.py:97-99`; keys are slot ids, BF-907). Record the count and each id.
2. `identity.db`, table `slot_mappings(slot_id, agent_uuid)` (`identity.py:458-463`; path `identity.py:569`, data root per `startup/infrastructure.py:170`): `SELECT slot_id, agent_uuid FROM slot_mappings`. Build the set E = the Ensign slot ids from step 1 plus their `agent_uuid`s.
3. `procedures/procedures.db`, table `procedure_records` (`procedure_store.py:98-124`; path `runtime.py:3020` plus `procedure_store.py:207`):
   - (a) `SELECT compilation_level, COUNT(*) FROM procedure_records WHERE is_active = 1 AND is_negative = 0 GROUP BY compilation_level ORDER BY compilation_level`: every procedure an Ensign executor is now held from is at Level 3 or above (procedures are matched ship-wide, `find_matching` has no agent filter, `procedure_store.py:925-958`); Level 5 is expected 0 (only `:7774` writes a level, and it could not reach 5).
   - (b) `SELECT id, name, compilation_level, origin_agent_ids FROM procedure_records WHERE is_active = 1 AND is_negative = 0 AND compilation_level >= 3`, then count, in Python, the rows whose `origin_agent_ids` (a JSON list) intersects E. This is the requested number.
   - Post on #1654 before the build: the Ensign count, (a) by level, and (b). `trust.db` is written at shutdown (`trust.py:336-345`), so a running vessel's file can lag its memory; say whether the vessel was running.
   - **Done (A1):** the count is posted on #1654: no active procedure is at Level 3 or above, so (b) is 0 and F02 restricts no stored procedure today. E1 to E3 apply to procedures promoted from now on.

**D5, the F05 repair.** Ranked: (1, chosen) one helper, `_grant_target_callsign`, resolving the stored id by certificate (`get_by_uuid`, else `get_by_slot`: `_grant_issue` stores the sovereign id, or the slot id when no identity registry is bound) and naming it with `callsign_registry.get_callsign(cert.agent_type)`, the live callsign, falling back to the birth callsign; the id prefix as before when nothing resolves; (2) add `CallsignRegistry.list_all()`: a new API for one caller that would still compare slot ids with a sovereign id and never match; (3) iterate `all_callsigns()` and `resolve()` each: per-grant O(n) and the same id-form mismatch.

**D6, the F04 repair.** Ranked: (1, chosen) add `TrustNetwork.get_history(agent_id, limit=20) -> list[float]`, the `new_score` of `get_events_for_agent(agent_id, n=limit)`, oldest first, `[]` for `limit <= 0` (`filtered[-0:]` would return all): one owner of the mapping; the callers' contract (`limit`, a list of floats the UI validates in [0, 1], `useProfileResource.ts:54`) holds unchanged; the three avatar doubles already have this signature; the 13 `runtime.trust_network.get_history.return_value = []` fixtures stay meaningful. Both `hasattr` guards are removed: they are what hid the defect; telemetry keeps its `try` (its never-raise contract, `telemetry.py:7-11`). (2) Call `get_events_for_agent` in both callers: the mapping three times (`standing_interests.py:701` already does it), and the doubles and fixtures would pin a dead name. (3) A persisted history: scope (R6).
**Doubles audit (5 files named by the issue, plus one found):** the three avatar `_FakeTrustNetwork`s match the new method; `test_bf711_*:110 _Store.get_history(agent_id, test_name, limit)` and `test_ad566c_*:54 MockQualificationStore.get_history` double the qualification store (`qualification.py:255`) and are out of scope; `test_ad1260_*:45 _FakeTrust` reaches the route and gains the method, and its `all_scores` gains `crew_only` (A1-1); `test_ad1259_*:70 _FakeTrustNetwork` never reaches either caller (its two `agent_profile` calls, `:238`, `:348`, use runtimes without a trust network) and is unchanged. A seam test pins the four doubles that stand for `TrustNetwork` on these paths: every public method each defines exists on `TrustNetwork` with the same parameter names and kinds (defaults are not compared: callers pass them). **Effect:** no hold (Captain-facing display, a ±3 % voice pitch and a rule name; section 5b).

**D7, `CounselorConfig` field by field.**
- `trust_delta_threshold`: wired into `_on_trust_update` (`counselor.py:1736`); default 0.15 = today. The comparison stays against `profile.baseline.trust_score`, the default baseline (BF-923 D8); BF-923's `_gather_agent_metrics` hold, `trust_observations` and `observed_baseline` are untouched.
- `sweep_max_agents`: the default of `_run_wellness_sweep` (`:969`), so both callers that pass none (`act` `:2878`, `routers/counselor.py:199`) read it; default 50 = today; an explicit `max_agents` still wins.
- `alert_on_red`, `alert_on_yellow`: removed. Ranked: (1, chosen) remove both: section 0's last row shows no single red/yellow rule; `alert_on_yellow: false` (model default and `system.yaml:1182`) wired as a filter would silence today's yellow circuit-breaker alerts (a reduction, forbidden), and wired as "also alert yellow where only red alerts" it invents alerts and their semantics; `alert_on_red` wired can only silence alerts (default True = today): adding a switch whose only effect is to weaken a safety alert is outside the envelope (R3 if the Captain wants an alert policy); (2) wire `alert_on_red` as a filter: the Captain's call; (3) wire `alert_on_yellow` additively: design work.
- `enabled`: removed (wiring it is a switch that disables a crew-facing wellness service; nothing asked for it). `profile_retention_days`: removed (AD-503's cleanup was never built, `prompts/archive/ad-503-counselor-activation.md:879`; R2).
- **Loading:** `CounselorConfig` has no `model_config` (section 12), so Pydantic v2 ignores unknown keys: an operator `system.yaml` that still sets a removed key loads unchanged, as the key was unread. The tracked `config/system.yaml` block drops the four keys. `docs/development/config-profiles.yaml:758` (`unclassified_flags`, `counselor.alert_on_yellow`) is deleted, or `check_config_profiles.py` fails its stale check (`scripts/check_config_profiles.py:726-731`). `docs/development/config-facade-baseline.yaml:1322-1334` and `docs/development/config-reference.md:1283-1294` are regenerated by their tools (`check_config_facade.py --update-baseline`, `gen_config_reference.py`), which `tests/test_ad1270e1_config_facade.py` and `tests/test_config_reference_current.py` check. No bounds are added (R4).
- **Injection:** constructor, like `profile_store` (`agent_fleet.py:192`, `counselor.py:562`): `create_pool` keeps spawn kwargs for respawn (`substrate/pool.py:70`, `:210`, `:304-308`). A Counselor built without one (tests) uses `CounselorConfig()`, the zero-config default.

**D8, scope and milestones.** BF-924 alone; M1 = F02 (HIGH); M2 = F04, F05, F10 (STANDARD). One gate after both.

**A1-1, the seam test's `all_scores` failure.** `test_ad1260_*:61 _FakeTrust.all_scores(self)` lacks the real `crew_only` (`trust.py:1077`). It masks nothing today: all 8 production calls pass no argument (`introspect.py:550`, `:709`; `vitals_monitor.py:126`, `:235`; `commands_status.py:70`; `crew_assignment.py:159`; `sif.py:214`; `observable_state.py:207`). The other three doubles define only `get_history` and `get_score`, both with the real names and kinds (the oracle's three passing cases; `test_ad722b4_*:38-43`, `test_ad722b_*:219-229`, `test_ad722_*:71-79`). The changed callers read `get_score` and `get_history` (route `agents.py:255`, `:260`) and `get_history` (telemetry `:725`). Ranked: (1, chosen) repair the double (§7.15: `crew_only: bool = False`, returning every score as before) and keep the test whole: a double that stands for `TrustNetwork` must keep the class's shape, so the next drift is caught wherever it is; (2) narrow the parameter comparison to `get_score` and `get_history`: lets doubles drift on methods other paths of the same fixture call (`_FakeTrust` also serves `get_record` and `get_events_for_agent`); (3) both: the narrowing gives up coverage for nothing once the double is repaired.

**A1-2, a Counselor built without `__init__`.** `_counselor_config` has two readers, `_on_trust_update` and `_run_wellness_sweep` (§7.9). Of the 22 `__new__` sites in 17 files (plus `test_ad1229_message_receipts.py:90`, which imports `_make_counselor` from the e2e file), only `test_counselor_therapeutic.py:38-69 _make_counselor` reaches one (`:276`, `_on_trust_update`); grep evidence in section 12. `CounselorAgent` has no class-level instance defaults: `_trust_network`, `_hebbian_router`, `_registry` and every other attribute are set in `__init__` (`counselor.py:565-590`); the class body holds only constants (`:504-558`). Ranked: (1, chosen) fix the builder that reaches a reader (§7.21), as BF-921 did for `_suppression_history` (`test_bf206_confab_feedback.py:357`) and §7.19 does for `test_ad642_*`: no production line changes, and a future `__new__` builder that reaches a reader fails loudly with `AttributeError`, which is the signal that it skips `__init__`; (2) a class-level `_counselor_config = CounselorConfig()`: one mutable Pydantic instance shared by every Counselor (assignment is allowed), dead in production (every production Counselor passes through `__init__`), and a new pattern for this class that exists only for tests; (3) `getattr(self, "_counselor_config", None) or CounselorConfig()` at both reads: a defensive `getattr` on an attribute the same class defines, two production branches that only tests reach (an anti-pattern in the standing orders).

**A1-3, the facade pin.** The count pin `test_ad1270e1_*:1555-1556` moves 1880 to 1876 with a comment line (§7.22). It is the only hand-written pin of the measured numbers (section 12).

**A1-4, the manifest's `census:` header.** Only `default_false` is pinned (`test_ad1185_*:857-859`), but the block is one measurement under one `measured_at_commit`. Measured on this tree (section 11): base 452 booleans, 226 default False, 226 default True, 85 armed, 141 never armed; after BF-924's removals 449, 225, 224, 85, 140. The committed header says 445, 226, 225, 85, 136: three figures had already drifted before this change. Ranked: (1, chosen) write all five post-change measurements and name this candidate in `measured_at_commit` (§7.13 pair 2): a header that mixes measured and stale figures under one commit is a false record, and the pair touches only lines BF-924 must already touch; (2) move only `default_false` (226 to 225): passes the test, leaves the drifted figures; (3) move every figure by BF-924's delta (445 to 442, 225 to 223, 136 to 135): carries the drift forward as if measured. The drift's cause is on the register (R8).

## 4. Interaction with the queue

- **BF-923 (#1652)** is this base. Its Counselor changes (sections 3, 5(c), 7.8 of `prompts/bf-923-episodic-recall-callers-and-counselor-assessment-inputs.md`) are in this tree; this contract's `counselor.py` pairs anchor on the import block, `__init__`, `_run_wellness_sweep`'s head and `_on_trust_update`'s threshold, none of which BF-923 changed. No pair touches `_gather_agent_metrics`, `_record_trust_observation`, `CognitiveProfile`, `behavioral_*`, `orientation.py`, `proactive.py`, `runtime.py`, `startup/finalize.py` or `ward_room/channels.py`.
- **#1626 M6+M7** edits `ui/` only. No pair here is in `ui/`; the UI readers of `trustHistory` and `trust_delta` are read, not changed.
- **Tracker anchors:** `PROGRESS.md`'s title line (once) and `DECISIONS.md`'s heading `### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)` (line 739, once).
- **PR text, BF-924's part:** "BF-924 (#1654). Trust inputs were read through APIs that don't exist. The AD-535/536 procedure-compilation clamp read an attribute nothing sets, so every agent counted as a Lieutenant; it now reads the agent's live trust (`get_score`, as Rank does): Ensigns are held to Guided (Level 2), a Commander's approved procedure can reach Level 5, and an unreadable trust is held to Level 2 with a WARNING. `TrustNetwork.get_history` now exists, so the Captain's profile shows trust history and the avatar's trust delta is real. `/grant list` no longer raises and names a grant's target by its live callsign. The Counselor reads `trust_delta_threshold` and `sweep_max_agents` from its config (defaults unchanged); the four `CounselorConfig` fields nothing read are removed."

## 5. Consumers of every value this changes

**(a) F02: the clamp's trust value and every dispatch that follows it.** States of the read: *measured* (a float), *errored* (`get_score` raised) and *absent* (no runtime or trust network) → 0.0 with a WARNING; *timed out* does not occur (an in-memory dict read, `trust.py:1017-1022`); *skipped* does not occur (read whenever a procedure is loaded).

| Reader | Effect of a real score |
|---|---|
| `_max_compilation_level_for_trust` (`:1853`) | trust < 0.5 → 2; else 4 (unchanged function) |
| `_max_compilation_level_for_promoted` (`:1858`, only for a stored Level ≥ 5) | 5 only for `approved` and trust ≥ 0.7 |
| dispatch `:1864-1877` | ≤1 None; 2 `_build_guided_decision` (LLM with hints, `:2449-2472`); 3 validated replay; ≥4 zero-token replay. **E1:** an Ensign executing a stored Level 3 or 4 procedure now runs Guided: an LLM call with the procedure as hints, its output LLM-written, its tokens spent. Level 5 dispatch equals Level 4 (`test_level_5_dispatch.py:159-179`), so a Commander's dispatch is unchanged |
| promotion `:7768-7783` | **E2:** an Ensign's consecutive successes no longer promote a procedure above Level 2 (`next_level <= min(max_allowed, 5)`, `:7773`), and Ensigns no longer reach Level 4, so they no longer request institutional promotion (`:7782-7783`). **E3:** a Commander's (≥ 0.7) `approved` Level 4 procedure is promoted to Level 5 after `COMPILATION_PROMOTION_THRESHOLD` (3) successes; Level 5 makes the Captain's `/procedure teach` and the teach route available (`commands_procedure.py:412`, `routers/procedures.py:167`); the agent's own `_teach_procedure` has no caller (section 12) |
| demotion `:7786-7799` | unchanged rule: any failure of a procedure-associated decision demotes a stored level above 2 to 2, a Guided run's failure as a replay's did before. The clamp itself writes no level |
| **E4** | a failed read logs `BF-924 (#1654): trust read failed for <id>; procedure compilation held to Level 2` at WARNING per procedure match |

**The Level 2 path and AD-534 / dream-time evolution (enumerated).** Writers of the four counters (`procedure_store.py:1052-1074`): selection and applied are recorded before the clamp (`cognitive_agent.py:1831`, `:1847`), unchanged; completion or fallback is recorded once per decision, by the cached branch (`:7732-7741`) or the guided branch (`:7744-7753`), the same counters. So the clamp changes which branch records, not what is recorded: one selection, one applied and one completion-or-fallback per run, either way. Readers of those counters: `diagnose_procedure_health` (`procedures.py:289-320`, thresholds on the four rates), called by the agent at `:1817` (the quality gate, before the clamp, unchanged) and `:1887` (Level ≥ 4 only: an Ensign's run no longer reaches it, so fewer AD-534 WARNING lines; log-only, `:2639-2646`), and by dreaming at `dreaming.py:1880` (`_evolve_degraded_procedures`), `:2151` (reactive), `:2464` (sweep), plus the gap predictor's own rule at `dreaming.py:1303-1310` and `gap_predictor.py:580`. All read `get_quality_metrics` (`procedure_store.py:1135-1162`) only; none reads the dispatch level, `cached` or `guided_by_procedure` (`guided_by_procedure` has two readers, both in `cognitive_agent.py`: `:2468` writes it, `:7744` reads it). So the change sets off no diagnosis and no evolution by itself; the counters move only with the outcomes of the Guided runs. Two behaviours differ for an Ensign's run: the AD-534b service recovery (`:7805`) runs only for a failed *cached* replay, and `:1887`'s log-only diagnosis does not run.

**(b) F04: `get_history` and the values it makes real.** States: *measured* (≥ 2 events); *fewer than 2 events* → `insufficient_trust_history` as today (the event log is in memory, 500 events ship-wide, empty at boot: `trust.py:265`); *errored* → telemetry's `except` gives `[]` (degraded as today); the route does not catch (as for `get_score` today).

| Value | Reader | Effect |
|---|---|---|
| `trustHistory` (`routers/agents.py:383`) | `ui/src/hooks/useProfileResource.ts:54` (validates floats in [0, 1]: `new_score` is a Beta mean), `ui/src/components/profile/ProfileHealthTab.tsx:41-44` (sparkline when more than one) | **E5:** the Captain's profile shows the last 20 trust scores |
| `trust_delta` (`telemetry.py:734`) | `apply_voice_modulation` (`:452-457`, ±0.2 from `ui/src/audio/modulation_manifest.json:3-4`; factors 1.03 / 0.97, `:8-9`) | **E6:** when the last two scores differ by more than 0.2, the pitch moves 3 % and `high_trust_pitch` or `low_trust_pitch` enters `fired_rules` |
| `applied_modulation` | the voice the Captain hears (UI); the agent's interoception `pitch=` (`cognitive_agent.py:6903-6905`, gated by `avatar_telemetry.inject_into_agent_context`, default False `config.py:2023`, **true** in `config/system.yaml:1631`); the divergence note (`:6950-6956`) lists the applied rules | **E6 (crew-visible):** an agent can read its pitch factor and a rule name `low_trust_pitch` / `high_trust_pitch` in its own context; a factual display of a qualified gauge, no action |
| divergence (`divergence_detector.py:390-633`) | `compute_divergence` scores only `intent_*` rules (`:320-334`); `_applied_direction` uses operational rules only when no intent rule fired (`:281-301`), and a parsed intent always fires its rule (`telemetry.py:470-495`; every v1 emotion has one, `modulation_manifest.json:19-26`) | sign, magnitude, the trust write (`:589-612`) and the Hebbian update (`:624-631`) unchanged |
| `records_writer._classify` (`records_writer.py:87-122`) | reads divergence magnitude, working state, silence | unchanged |
| `SelfPerceptionProjection.modulation_pitch_factor` (`self_perception.py:125`) | `project_self_perception` has no caller (section 12) | none |
| frames (`telemetry_frames.py:161-176`) | `trust_delta` must be finite in [-1, 1] | a difference of two [0, 1] scores is |
| `degraded_reasons` | `insufficient_trust_history` (`telemetry.py:730-731`, logged through `_warn`) | fewer such warnings (74 in the issue's live log) |

**(c) F05.** One reader: the table's Agent column. A failure of the lookup shows the id prefix as before.

**(d) F10.** `trust_delta_threshold`: one reader (`_on_trust_update`); `sweep_max_agents`: one reader (`_run_wellness_sweep`'s default) reached by `act` and the API. Every result state of both handlers is as today with the defaults. **E7:** an operator value now changes behaviour: a lower threshold reassesses more trust updates (each can DM on today's live inputs, BF-923 D8), a lower sweep bound assesses fewer crew. Writers of the fields: `config/system.yaml:1179-1180` (same values as the defaults); no profile under `config/profiles/` and neither node config sets a counselor key (section 11).

## 6. Milestones and tests

**M1 (HIGH), §7.1 to §7.4.** First heading: `### 7.1 \`src/probos/cognitive/cognitive_agent.py\` (M1)`. Commit "BF-924 M1: the procedure-compilation trust clamp reads the agent's live trust (part of #1654)", body ending "AD-535/536 read a _trust_score attribute nothing sets, so every agent counted as 0.5. The clamp and the promotion step now read TrustNetwork.get_score(self.id), as the rank read does; an unreadable trust logs a WARNING and takes the Ensign cap (Level 2). Ensigns run stored Level 3 and 4 procedures as Guided; a Commander's approved procedure can reach Level 5."

Before editing, grep the pins: `grep -rn "_trust_score\|_max_compilation_level_for\|_check_procedural_memory\|promote_compilation_level" tests/`. The hand-set `_trust_score` in `test_graduated_compilation.py` and `test_level_5_dispatch.py` is replaced (§7.3, §7.4). `test_teaching_protocol.py:93` also sets it, but none of its tests reaches the clamp (it does not call `_check_procedural_memory`); it is left, now dead (R7).

**Named doubles and what they mask (M1).** `test_ad573_memory_budget.py:157-164` replaces `_check_procedural_memory` whole, so it never reaches the clamp. `MagicMock` runtimes in `test_replay_dispatch.py`, `test_multi_agent_replay_dispatch.py`, `test_fallback_learning.py` and the inline sites `test_graduated_compilation.py:545`, `:573`: `runtime.trust_network.get_score(...)` returns a `MagicMock`, which `float()` reads as 1.0, so each such test now runs the clamp at Senior trust. It masks nothing they assert: each dispatches a non-`approved` procedure, where every trust ≥ 0.5 caps at 4 (the grep `approved` over these files finds only `test_level_5_dispatch.py`, whose factory §7.4 repairs, and `test_teaching_protocol.py`). `ReplayTestAgent`, `_make_store_mock` and `_make_runtime_with_store` (`test_replay_dispatch.py:28`, `:63`, `:87`) and the lifecycle helpers of `test_fallback_learning.py:28-115` are reused: the store doubles return chosen procedures (they mask the semantic match, not the clamp); `_recall_relevant_memories` and `_store_action_episode` are patched as `test_fallback_learning.py:237-239` does (memory recall and episode storage, not on the changed path). `_UnreadableTrustNetwork` stands for a failing store. In the two failure cases `_build_guided_decision` is a spy: it replaces only the Guided LLM call, so the only trust read is the clamp's.

Tests first: with §7.2 to §7.4 applied and §7.1 not, exactly 6 cases fail:
- `test_an_ensign_runs_a_stored_level_4_procedure_as_guided`: `assert None is True` on `guided_by_procedure` (a cached replay);
- `test_an_unreadable_trust_is_held_to_level_2_and_warned[raises]`, `[absent]`: `Expected '_build_guided_decision' to have been awaited once. Awaited 0 times.`;
- `test_a_commanders_approved_procedure_is_promoted_to_level_5`: `promote_compilation_level` awaited 0 times;
- `test_an_ensigns_successes_do_not_promote_it_past_level_2`: `Expected 'promote_compilation_level' to not have been awaited. Awaited 1 times.`;
- `TestTrustClamping::test_clamping_applied_in_check_procedural_memory` (`test_graduated_compilation.py:146`): its factory no longer sets `_trust_score`, so the base reads 0.5: `assert None is True`.

`test_a_lieutenant_still_replays_a_stored_level_4_procedure` passes on both sides (the premise). A failure for another reason (an exception before the asserted line) is a hard stop for the Architect. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_compilation_trust.py tests/test_graduated_compilation.py tests/test_level_5_dispatch.py tests/test_replay_dispatch.py tests/test_multi_agent_replay_dispatch.py tests/test_fallback_learning.py tests/test_ad573_memory_budget.py tests/test_teaching_protocol.py tests/test_promotion_approval.py tests/test_promotion_integration.py -n 0 -q
```

(Collected on `ba45c61f` without the new file: 270, all passing. Expect 277 passed. A1: the orchestrator's measured counts supersede this line; A1 adds and removes no M1 case.)

**M2 (STANDARD), §7.5 to §7.22.** First heading: `### 7.5 \`src/probos/consensus/trust.py\` (M2)`. After applying §7.5 to §7.22, regenerate and check, in this order:

```
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
```

The regenerated `docs/development/config-reference.md` and `docs/development/config-facade-baseline.yaml` go in M2's commit. Their diff is exactly these hunks (A1: measured by the oracle on the applied tree, `logs/bf924r1/generated-config-diff.txt`):
- `config-facade-baseline.yaml`, `surface_counts` (at `:50-51`): `canonical_dump_leaves` 1891 to 1887 and `field_definitions` 1880 to 1876; `aliased_fields` 1, `incidental` 13, `own_models` 228, `owned` 296 and `public_names` 309 unchanged;
- the same file, `canonical_dump_sha256` (`:56`): `fc24f1a1...` to `bbf47ad58a4316e1906cd1efff1ec25594b81c66dd6ff5b096a9fbd18aa16969`;
- the same file, the `CounselorConfig` row (`:1322-1334`): `schema_sha256` `291ee4ff...` to `49520476ec22781ac072400fab49280779d5bd5dbf85a49bab5d9656e0705abc`, and the four field lines `enabled`, `profile_retention_days`, `alert_on_red`, `alert_on_yellow` deleted; `trust_delta_threshold` and `sweep_max_agents` unchanged;
- the same file, the `SystemConfig` row (`:3418`, the model that contains `CounselorConfig`): `schema_sha256` `ba3ec2db...` to `dc10c4795616d785b6c6860834ef150fab29c53abd48d9052f3950c44abc82aa`, nothing else;
- `config-reference.md`, the `counselor` section (`:1289-1294`): the four rows of the removed fields deleted; the description line ("Counselor cognitive wellness configuration (AD-503).", the docstring's first line) and the two remaining rows unchanged.

The three hashes are the values for §7.11 applied byte for byte (the schema includes the docstring). Any other file, hunk or value, or a `--check` failure, is a hard stop for the Architect. Commit "BF-924 M2: trust history, /grant list and the Counselor's config read real APIs (part of #1654)", body ending "TrustNetwork.get_history returns the agent's last trust scores, so profile trust history and the avatar trust delta are real; both hasattr guards are removed. /grant list names a target through its birth certificate and live callsign. The Counselor takes CounselorConfig by constructor injection and reads trust_delta_threshold and sweep_max_agents (defaults unchanged); enabled, profile_retention_days, alert_on_red and alert_on_yellow had no reader and are removed." The tracker entries (section 8) go in this commit.

Before editing, grep the pins: `grep -rn "get_history\|list_all\|CounselorConfig\|trust_delta_threshold\|sweep_max_agents\|alert_on_\|profile_retention_days\|_run_wellness_sweep" tests/`. The 13 `runtime.trust_network.get_history.return_value = []` fixtures (`test_ad1052a_*:131` and 12 more, section 11) now name a real method and stay.

**Named doubles and what they mask (M2).** The route test reuses `test_api_profile.py`'s `mock_runtime` (a `MagicMock(spec=ProbOSRuntime)`) and replaces its `trust_network` `MagicMock`, which invented `get_history`, with a real `TrustNetwork`. The telemetry test reuses `test_ad722_avatar_telemetry.py`'s `_make_runtime` and replaces its `_FakeTrustNetwork` with a real one. F05 uses a real `AgentIdentityRegistry`, `ClearanceGrantStore`, `CallsignRegistry` and `AgentRegistry`; the one stand-in is the registered agent, a `SimpleNamespace` with `id`, `agent_type`, `pool` and `is_alive`, the only attributes `CallsignRegistry.resolve` and `AgentRegistry.register` read (`crew_profile.py:726-731`, `substrate/registry.py:29-37`). F10 uses real `CounselorAgent`s and `AgentRegistry`s; the sweep's crew are `SimpleNamespace`s with the attributes the sweep reads; one test boots a real `ProbOSRuntime`.

Tests first: with §7.14 to §7.22 applied and §7.5 to §7.13 not (and nothing regenerated), exactly 19 cases fail:
- the new file's 15: `test_get_history_*` (2, `AttributeError: 'TrustNetwork' object has no attribute 'get_history'`); `test_the_profile_route_returns_the_trust_history` (`assert [] == [...]`); `test_the_avatar_trust_delta_is_the_last_trust_change` (`0.0 == approx(...)`); `test_the_trust_network_doubles_match_the_real_class` (4 cases, `get_history is not a TrustNetwork method`); `test_grant_list_*` (2, `AttributeError: 'CallsignRegistry' object has no attribute 'list_all'`); `test_the_trust_update_threshold_comes_from_the_config` (2: `assert 1 == 0` and `assert 0 == 1`); `test_the_sweep_bound_comes_from_the_config` (`assert 3 == 2`); `test_the_booted_counselor_takes_the_operators_config` (the eligible crew count `== 2` fails); `test_the_removed_counselor_fields_are_gone_and_old_configs_still_load` (the field set);
- `TestCounselorConfig::test_default_values` (the field set);
- `test_system_config_dump_is_unchanged_for_the_moved_model[CounselorConfig]` and `test_constructing_with_no_arguments_matches_the_pre_move_dump[CounselorConfig]` (the dump);
- A1: `test_committed_baseline_records_the_measured_surface` (`assert 1880 == 1876`: the committed baseline is not yet regenerated).

`test_cmd_grant_list_renders`, the `test_ad1260_*` and `test_ad642_*` pins, the no-method telemetry test, every `test_counselor_therapeutic.py` case (§7.21 sets an attribute nothing reads before §7.9) and `test_the_measured_census_matches_the_manifest_header` (header and model both 226 before §7.11 and §7.13) pass on both sides. The `[test_ad1260_wellness_domain-_FakeTrust]` seam case still fails first on `get_history` (it precedes `all_scores` in the class body). Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_trust_inputs.py tests/test_trust.py tests/test_trust_events.py tests/test_ad722_avatar_telemetry.py tests/test_ad722b4_fleet_telemetry.py tests/test_ad722b_websocket_push.py tests/test_api_profile.py tests/test_ad1260_wellness_domain.py tests/test_ad1259_one_source_of_truth.py tests/test_ad622_clearance_grants.py tests/test_counselor.py tests/test_counselor_activation.py tests/test_counselor_therapeutic.py tests/test_ad642_communication_benchmarks.py tests/test_bf923_counselor_assessment_inputs.py tests/test_ad1270e2h_emergence_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py -n 0 -q
```

(Collected on `ba45c61f` without the new file: 1,015; not run here. Expect 1,030 collected; the orchestrator computes the pass and skip counts by tool. A1: the oracle collected 1,306 for the union of both lists (29 files); A1 adds and removes no case, so expect 1,306 collected and 1,306 passed for the union.)

**The broad gate is run once for #1654 by the main session, not by the Builder.**

## 7. The contract

### 7.1 `src/probos/cognitive/cognitive_agent.py` (M1)

Pair 1 (the clamp):

SEARCH:
````python
        # AD-535: Trust-tier clamping
        trust_score = getattr(self, "_trust_score", 0.5)
        max_level = self._max_compilation_level_for_trust(trust_score)
````
REPLACE:
````python
        # AD-535: Trust-tier clamping (BF-924: the agent's live trust)
        trust_score = self._compilation_trust_score()
        max_level = self._max_compilation_level_for_trust(trust_score)
````

Pair 2 (the helper):

SEARCH:
````python
    def _max_compilation_level_for_trust(self, trust_score: float) -> int:
        """AD-535: Return the maximum compilation level allowed for the given trust score.
````
REPLACE:
````python
    def _compilation_trust_score(self) -> float:
        """BF-924 (#1654): the live trust the AD-535/536 compilation clamp uses.

        Read with ``TrustNetwork.get_score(self.id)``, as BF-263's rank read does. The
        ``_trust_score`` attribute read before is assigned nowhere, so every agent counted as 0.5.
        A read that fails, or a runtime without a trust network, logs a WARNING and returns 0.0:
        an unknown trust takes the Ensign cap (Level 2) and never unlocks replay or Level 5.
        """
        trust_network = getattr(self._runtime, "trust_network", None)
        try:
            return float(trust_network.get_score(self.id))
        except Exception:
            logger.warning("BF-924 (#1654): trust read failed for %s; procedure compilation held to Level 2", self.id, exc_info=True)
            return 0.0  # BF-924: unknown trust takes the Ensign cap (Level 2)

    def _max_compilation_level_for_trust(self, trust_score: float) -> int:
        """AD-535: Return the maximum compilation level allowed for the given trust score.
````

Pair 3 (the promotion step):

SEARCH:
````python
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = getattr(self, "_trust_score", 0.5)
````
REPLACE:
````python
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = self._compilation_trust_score()  # BF-924 (#1654): the live trust, as in the clamp
````

### 7.2 New file: `tests/test_bf924_compilation_trust.py` (M1)

````python
"""BF-924 (#1654) M1: the AD-535/536 procedure-compilation clamp reads the agent's live trust.

The clamp and the promotion step read ``getattr(self, "_trust_score", 0.5)``, which nothing assigns,
so every agent counted as a Lieutenant. Each test drives the clamp through its production caller
(``decide`` or ``handle_intent``) on a real ``CognitiveAgent`` whose runtime carries a real
``TrustNetwork``.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.config import COMPILATION_PROMOTION_THRESHOLD
from probos.consensus.trust import TrustNetwork
from tests.test_fallback_learning import _make_cognitive_agent as _make_lifecycle_agent
from tests.test_fallback_learning import _make_intent, _make_procedure
from tests.test_fallback_learning import _make_store_mock as _make_lifecycle_store
from tests.test_replay_dispatch import (
    ReplayTestAgent,
    _make_runtime_with_store,
    _make_store_mock,
    _MockProcedure,
)


def trust_network_at(agent_id: str, score: float) -> TrustNetwork:
    """A real ``TrustNetwork`` in which ``agent_id`` holds trust ``score`` (a Beta prior of weight 10).

    Shared with ``test_graduated_compilation.py`` and ``test_level_5_dispatch.py`` (BF-924), whose
    agents reached the clamp through a hand-set ``_trust_score`` that production never sets.
    """
    network = TrustNetwork()
    alpha = 10.0 * score
    network.create_with_prior(agent_id, alpha=alpha, beta=10.0 - alpha)
    return network


class _UnreadableTrustNetwork:
    """Stands in for a failing trust store: ``get_score`` is the only method the clamp calls."""

    def get_score(self, agent_id: str) -> float:
        raise RuntimeError("trust store unavailable")


_OBSERVATION = {"intent": "test_intent", "params": {"message": "do it"}}


@pytest.fixture(autouse=True)
def _clear_decision_caches():
    from probos.cognitive.cognitive_agent import _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES

    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


def _level_4_runtime() -> MagicMock:
    """A runtime whose procedure store matches one stored Level 4 procedure."""
    proc = _MockProcedure(id="proc-bf924", name="Handle test task", compilation_level=4)
    store = _make_store_mock(
        find_result=[{"id": proc.id, "name": proc.name, "score": 0.9}],
        get_result=proc,
    )
    return _make_runtime_with_store(store)


@pytest.mark.asyncio
async def test_an_ensign_runs_a_stored_level_4_procedure_as_guided() -> None:
    """An Ensign (trust 0.3) is held to Level 2: the LLM runs with the procedure as hints."""
    llm = MockLLMClient()
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=llm, runtime=rt)
    rt.trust_network = trust_network_at(agent.id, 0.3)

    result = await agent.decide(dict(_OBSERVATION))

    assert result.get("guided_by_procedure") is True
    assert result.get("compilation_level") == 2
    assert result.get("procedure_id") == "proc-bf924"
    assert result.get("cached") is not True
    assert llm.call_count >= 1


@pytest.mark.asyncio
async def test_a_lieutenant_still_replays_a_stored_level_4_procedure() -> None:
    """The premise: at trust 0.5 the clamp allows Level 4, a zero-token replay, as before."""
    llm = MockLLMClient()
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=llm, runtime=rt)
    rt.trust_network = trust_network_at(agent.id, 0.5)

    result = await agent.decide(dict(_OBSERVATION))

    assert result.get("cached") is True
    assert result.get("procedure_id") == "proc-bf924"
    assert llm.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("trust_network", [_UnreadableTrustNetwork(), None], ids=["raises", "absent"])
async def test_an_unreadable_trust_is_held_to_level_2_and_warned(trust_network, caplog) -> None:
    """Fail closed: an unknown trust takes the Ensign cap and says so at WARNING."""
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=MockLLMClient(), runtime=rt)
    rt.trust_network = trust_network
    # Spy on the Level 2 builder: it replaces only the Guided LLM call, so the clamp's is the only trust read.
    guided = AsyncMock(return_value={
        "action": "execute", "guided_by_procedure": True, "procedure_id": "proc-bf924", "compilation_level": 2,
    })

    with patch.object(agent, "_build_guided_decision", guided), caplog.at_level(
        logging.WARNING, logger="probos.cognitive.cognitive_agent",
    ):
        result = await agent.decide(dict(_OBSERVATION))

    guided.assert_awaited_once()
    assert guided.await_args.args[0].id == "proc-bf924"
    assert result.get("cached") is not True
    assert any(
        record.levelno == logging.WARNING and "BF-924" in record.getMessage() for record in caplog.records
    )


def _lifecycle_runtime(store: AsyncMock, agent_id: str, score: float) -> MagicMock:
    runtime = MagicMock()
    runtime.procedure_store = store
    runtime.cognitive_journal = None
    runtime.emit_event = MagicMock()
    runtime.trust_network = trust_network_at(agent_id, score)
    return runtime


async def _handle_once(agent):
    with patch.object(
        agent, "_recall_relevant_memories", new_callable=AsyncMock,
        return_value={"intent": "test_intent", "params": {"message": "test query"}},
    ), patch.object(agent, "_store_action_episode", new_callable=AsyncMock):
        return await agent.handle_intent(_make_intent())


@pytest.mark.asyncio
async def test_a_commanders_approved_procedure_is_promoted_to_level_5() -> None:
    """AD-536's Level 5 path, unreachable while every agent counted as 0.5."""
    agent = _make_lifecycle_agent()
    proc = _make_procedure(compilation_level=4)
    store = _make_lifecycle_store()
    store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
    store.get.return_value = proc
    store.record_consecutive_success.return_value = COMPILATION_PROMOTION_THRESHOLD
    store.get_promotion_status = AsyncMock(return_value="approved")
    agent._runtime = _lifecycle_runtime(store, agent.id, 0.8)

    result = await _handle_once(agent)

    assert result is not None and result.success is True
    store.promote_compilation_level.assert_awaited_once_with(proc.id, 5)


@pytest.mark.asyncio
async def test_an_ensigns_successes_do_not_promote_it_past_level_2() -> None:
    """An Ensign's Guided successes complete (premise) but no longer promote the procedure to Level 3."""
    agent = _make_lifecycle_agent(llm_client=MockLLMClient())
    proc = _make_procedure(compilation_level=2)
    store = _make_lifecycle_store()
    store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
    store.get.return_value = proc
    store.record_consecutive_success.return_value = COMPILATION_PROMOTION_THRESHOLD
    agent._runtime = _lifecycle_runtime(store, agent.id, 0.3)

    result = await _handle_once(agent)

    assert result is not None and result.success is True
    store.record_completion.assert_awaited_once_with(proc.id)
    store.promote_compilation_level.assert_not_awaited()
````

### 7.3 `tests/test_graduated_compilation.py` (M1: the hand-set `_trust_score`)

Pair 1:

SEARCH:
````python
import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep
````
REPLACE:
````python
import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep
from tests.test_bf924_compilation_trust import trust_network_at
````

Pair 2 (the factory):

SEARCH:
````python
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.5)
    agent._trust_score = defaults.get("trust_score", 0.5)
    return agent
````
REPLACE:
````python
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.5)
    # BF-924 (#1654): the clamp reads live trust through the runtime (TrustNetwork.get_score). The
    # ``_trust_score`` attribute set here before is never set in production, so it masked the defect
    # (every agent counted as 0.5); a given runtime now carries a real network at this score.
    if agent._runtime is not None:
        agent._runtime.trust_network = trust_network_at(agent.id, defaults.get("trust_score", 0.5))
    return agent
````

Pair 3:

SEARCH:
````python
        runtime.procedure_store = store
        agent._runtime = runtime
        agent._trust_score = 0.6

        result = await agent._check_procedural_memory({
````
REPLACE:
````python
        runtime.procedure_store = store
        agent._runtime = runtime
        runtime.trust_network = trust_network_at(agent.id, 0.6)  # BF-924: was a hand-set _trust_score

        result = await agent._check_procedural_memory({
````

Pair 4:

SEARCH:
````python
            agent._runtime = runtime
            agent._trust_score = 0.6

            await agent._check_procedural_memory({
````
REPLACE:
````python
            agent._runtime = runtime
            runtime.trust_network = trust_network_at(agent.id, 0.6)  # BF-924: was a hand-set _trust_score

            await agent._check_procedural_memory({
````

### 7.4 `tests/test_level_5_dispatch.py` (M1: the hand-set `_trust_score`)

Pair 1:

SEARCH:
````python
import pytest

from probos.cognitive.procedures import Procedure
````
REPLACE:
````python
import pytest

from probos.cognitive.procedures import Procedure
from tests.test_bf924_compilation_trust import trust_network_at
````

Pair 2:

SEARCH:
````python
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.5)
    agent._trust_score = defaults.get("trust_score", 0.5)
    return agent
````
REPLACE:
````python
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.5)
    # BF-924 (#1654): the clamp reads live trust through the runtime; the hand-set ``_trust_score``
    # here before is never set in production. A given runtime now carries a real network at this score.
    if agent._runtime is not None:
        agent._runtime.trust_network = trust_network_at(agent.id, defaults.get("trust_score", 0.5))
    return agent
````

### 7.5 `src/probos/consensus/trust.py` (M2)

SEARCH:
````python
    def get_events_for_agent(self, agent_id: str, n: int = 20) -> list[TrustEvent]:
        """Return last N trust events for a specific agent (BF-907: by slot id)."""
        key = self._canonical_key(agent_id)
        filtered = [e for e in self._event_log if e.agent_id == key]
        return filtered[-n:]
````
REPLACE:
````python
    def get_events_for_agent(self, agent_id: str, n: int = 20) -> list[TrustEvent]:
        """Return last N trust events for a specific agent (BF-907: by slot id)."""
        key = self._canonical_key(agent_id)
        filtered = [e for e in self._event_log if e.agent_id == key]
        return filtered[-n:]

    def get_history(self, agent_id: str, limit: int = 20) -> list[float]:
        """BF-924 (#1654): the agent's last ``limit`` trust scores, oldest first.

        Each is the ``new_score`` of one of the agent's events in the in-memory event log
        (``get_events_for_agent``: the ship's last 500 events, empty at boot). Read by the Captain's
        agent profile (``trustHistory``) and the avatar telemetry's ``trust_delta``.
        """
        if limit <= 0:
            return []
        return [event.new_score for event in self.get_events_for_agent(agent_id, n=limit)]
````

### 7.6 `src/probos/routers/agents.py` (M2)

SEARCH:
````python
        agency_level = agency_from_rank(Rank.from_trust(trust_score)).value
        if hasattr(runtime.trust_network, 'get_history'):
            trust_history = runtime.trust_network.get_history(agent.id, limit=20)
````
REPLACE:
````python
        agency_level = agency_from_rank(Rank.from_trust(trust_score)).value
        trust_history = runtime.trust_network.get_history(agent.id, limit=20)  # BF-924 (#1654): the guard here hid that the method did not exist
````

### 7.7 `src/probos/avatars/telemetry.py` (M2)

Pair 1 (module docstring):

SEARCH:
````python
                       else ``0.0`` + ``"insufficient_trust_history"``.
                       Method existence is guarded via ``hasattr`` — mirrors
                       the call-site at ``routers/agents.py:91``.
````
REPLACE:
````python
                       else ``0.0`` + ``"insufficient_trust_history"``.
                       BF-924 (#1654): ``TrustNetwork.get_history`` (the
                       agent's last trust scores); a read that raises
                       degrades like a short history.
````

Pair 2 (the snapshot's docstring):

SEARCH:
````python
    Note on ``trust_delta``: v1 reads ``runtime.trust_network.get_history(
    agent_id, limit=2)`` behind a ``hasattr`` guard mirroring
    ``routers/agents.py:91``. When the method is absent OR history < 2
    entries → ``trust_delta=0.0`` + degraded reason
    ``"insufficient_trust_history"``. No magnitude smoothing, no decay.
````
REPLACE:
````python
    Note on ``trust_delta``: reads ``runtime.trust_network.get_history(
    agent_id, limit=2)`` (BF-924: the ``hasattr`` guard that hid its absence is
    gone). When the read raises OR history < 2 entries → ``trust_delta=0.0`` +
    degraded reason ``"insufficient_trust_history"``. No magnitude smoothing,
    no decay.
````

Pair 3 (the read):

SEARCH:
````python
    # 4. Trust delta — guarded mirror of routers/agents.py:91.
    trust_delta = 0.0
    trust_network = getattr(runtime, "trust_network", None)
    history: list[float] = []
    if trust_network is not None and hasattr(trust_network, "get_history"):
````
REPLACE:
````python
    # 4. Trust delta — the last two trust scores (BF-924: TrustNetwork.get_history).
    trust_delta = 0.0
    trust_network = getattr(runtime, "trust_network", None)
    history: list[float] = []
    if trust_network is not None:
````

### 7.8 `src/probos/experience/commands/commands_clearance.py` (M2)

Pair 1 (the helper):

SEARCH:
````python
async def _grant_list(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """List clearance grants."""
````
REPLACE:
````python
def _grant_target_callsign(runtime: "ProbOSRuntime", target_agent_id: str) -> str:
    """BF-924 (#1654): the live callsign of a grant's target, or "" when it cannot be named.

    ``_grant_issue`` stores the sovereign id, or the slot id when no identity registry is bound, so
    the target is found by its birth certificate either way. It is named by the callsign registry's
    live callsign for its agent type (a naming ceremony can replace the birth callsign).
    """
    identity_reg = getattr(runtime, "identity_registry", None)
    if identity_reg is None:
        return ""
    cert = identity_reg.get_by_uuid(target_agent_id) or identity_reg.get_by_slot(target_agent_id)
    if cert is None:
        return ""
    return runtime.callsign_registry.get_callsign(cert.agent_type) or cert.callsign


async def _grant_list(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """List clearance grants."""
````

Pair 2 (the column):

SEARCH:
````python
        # Resolve callsign for display
        agent_display = g.target_agent_id[:12]
        if hasattr(runtime, 'callsign_registry'):
            for agent in runtime.callsign_registry.list_all():
                if agent.get("agent_id") == g.target_agent_id:
                    agent_display = agent.get("callsign", agent_display)
                    break
````
REPLACE:
````python
        # Resolve callsign for display (BF-924: no CallsignRegistry has list_all; every grant raised)
        agent_display = _grant_target_callsign(runtime, g.target_agent_id) or g.target_agent_id[:12]
````

### 7.9 `src/probos/cognitive/counselor.py` (M2)

Pair 1 (import):

SEARCH:
````python
    COUNSELOR_WELLNESS_YELLOW,
    TRUST_DEFAULT,
)
````
REPLACE:
````python
    COUNSELOR_WELLNESS_YELLOW,
    CounselorConfig,
    TRUST_DEFAULT,
)
````

Pair 2 (constructor injection):

SEARCH:
````python
    def __init__(self, **kwargs: Any) -> None:
        # AD-503: Extract counselor-specific kwargs before super().__init__
        self._profile_store: CounselorProfileStore | None = kwargs.pop("profile_store", None)
        kwargs.setdefault("pool", "bridge")
````
REPLACE:
````python
    def __init__(self, **kwargs: Any) -> None:
        # AD-503: Extract counselor-specific kwargs before super().__init__
        self._profile_store: CounselorProfileStore | None = kwargs.pop("profile_store", None)
        # BF-924 (#1654): the operator's CounselorConfig (startup passes config.counselor). A Counselor
        # built without one uses the model defaults, which are the values this class hard-coded before.
        self._counselor_config: CounselorConfig = kwargs.pop("counselor_config", None) or CounselorConfig()
        kwargs.setdefault("pool", "bridge")
````

Pair 3 (the sweep bound):

SEARCH:
````python
    async def _run_wellness_sweep(self, max_agents: int = 50) -> list[CounselorAssessment]:
        """Iterate crew agents, gather metrics, assess, persist.

        Skips non-crew agents and the counselor itself.
        """
        results: list[CounselorAssessment] = []
````
REPLACE:
````python
    async def _run_wellness_sweep(self, max_agents: int | None = None) -> list[CounselorAssessment]:
        """Iterate crew agents, gather metrics, assess, persist.

        Skips non-crew agents and the counselor itself. BF-924 (#1654): at most ``max_agents``, by
        default ``CounselorConfig.sweep_max_agents`` (50, the bound hard-coded before).
        """
        if max_agents is None:
            max_agents = self._counselor_config.sweep_max_agents
        results: list[CounselorAssessment] = []
````

Pair 4 (the trust-update threshold):

SEARCH:
````python
        delta = abs(new_score - profile.baseline.trust_score)
        # Only react to significant changes (configurable via counselor config)
        if delta < 0.15:
            return
````
REPLACE:
````python
        delta = abs(new_score - profile.baseline.trust_score)
        # BF-924 (#1654): CounselorConfig.trust_delta_threshold (0.15, the constant before). The baseline
        # stays the default one until the trust gauge is qualified (BF-923 D8, DECISIONS.md).
        if delta < self._counselor_config.trust_delta_threshold:
            return
````

### 7.10 `src/probos/startup/agent_fleet.py` (M2)

SEARCH:
````python
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
            profile_store=counselor_profile_store,
        )
````
REPLACE:
````python
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
            profile_store=counselor_profile_store,
            counselor_config=config.counselor,  # BF-924 (#1654): the operator's CounselorConfig
        )
````

### 7.11 `src/probos/config_models/emergence.py` (M2)

SEARCH:
````python
class CounselorConfig(BaseModel):
    """Counselor cognitive wellness configuration (AD-503)."""

    enabled: bool = True
    profile_retention_days: int = 90
    trust_delta_threshold: float = 0.15
    sweep_max_agents: int = 50
    alert_on_red: bool = True
    alert_on_yellow: bool = False
````
REPLACE:
````python
class CounselorConfig(BaseModel):
    """Counselor cognitive wellness configuration (AD-503).

    BF-924 (#1654): both fields are read by ``CounselorAgent`` and default to the values it hard-coded
    before. ``enabled``, ``profile_retention_days``, ``alert_on_red`` and ``alert_on_yellow`` had no
    reader and were removed; a config that still sets them loads (unknown keys are ignored).
    """

    trust_delta_threshold: float = 0.15  # |new trust - baseline| below this: no trust-update reassessment
    sweep_max_agents: int = 50  # crew assessed per wellness sweep
````

### 7.12 `config/system.yaml` (M2)

SEARCH:
````yaml
counselor:
  enabled: true
  profile_retention_days: 90
  trust_delta_threshold: 0.15
  sweep_max_agents: 50
  alert_on_red: true
  alert_on_yellow: false
circuit_breaker:
````
REPLACE:
````yaml
counselor:
  trust_delta_threshold: 0.15
  sweep_max_agents: 50
circuit_breaker:
````

### 7.13 `docs/development/config-profiles.yaml` (M2: the frozen row of a removed flag)

SEARCH:
````yaml
- consultation_delivery.default_requires_approval
- counselor.alert_on_yellow
- degradation.auto_pause_enabled
````
REPLACE:
````yaml
- consultation_delivery.default_requires_approval
- degradation.auto_pause_enabled
````

Pair 2 (A1-4: the header's census, re-measured; `test_ad1185_*:857-859` pins `default_false`):

SEARCH:
````yaml
  measured_at_commit: 376903a55303d292efd617ef87c7bef3fd5537cf plus the AD-1198 candidate
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 445
  default_false: 226
  default_true: 225
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 136
````
REPLACE:
````yaml
  measured_at_commit: ba45c61f5550e110aab4b00441d78f3f590ba513 plus the BF-924 candidate, every count
    re-measured (the base measured 452, 226, 226, 85 and 141 with this instrument; three of the
    figures kept since AD-1198 had drifted)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 449
  default_false: 225
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 140
````

### 7.14 `tests/test_ad722_avatar_telemetry.py` (M2: the no-method double)

SEARCH:
````python
class _FakeTrustNetworkNoHistoryMethod:
    """Mirrors a trust-network shape that lacks ``get_history`` (hasattr → False)."""
````
REPLACE:
````python
class _FakeTrustNetworkNoHistoryMethod:
    """A trust network whose history read raises (AttributeError): the snapshot still degrades.

    BF-924 (#1654): no real TrustNetwork lacks ``get_history`` now; the ``hasattr`` guard this double
    once exercised hid that the method did not exist. It now exercises the read's ``except``.
    """
````

### 7.15 `tests/test_ad1260_wellness_domain.py` (M2: `_FakeTrust` reaches the profile route)

SEARCH:
````python
    def get_events_for_agent(self, agent_id: str, n: int = 5) -> list[Any]:
        return []

    def all_scores(self) -> dict[str, float]:
        return dict(self.scores)
````
REPLACE:
````python
    def get_events_for_agent(self, agent_id: str, n: int = 5) -> list[Any]:
        return []

    def get_history(self, agent_id: str, limit: int = 20) -> list[float]:
        # BF-924 (#1654): TrustNetwork's method; the profile route calls it without a guard now.
        return []

    def all_scores(self, crew_only: bool = False) -> dict[str, float]:
        # BF-924 (#1654): TrustNetwork.all_scores takes crew_only (no caller passes it today); the
        # seam test in tests/test_bf924_trust_inputs.py pins this double to the real signature.
        return dict(self.scores)
````

### 7.16 `tests/test_ad622_clearance_grants.py` (M2: `list_all` invented by a `MagicMock`)

SEARCH:
````python
        mock_runtime.clearance_grant_store = mock_store
        mock_runtime.callsign_registry.list_all.return_value = []
````
REPLACE:
````python
        mock_runtime.clearance_grant_store = mock_store
        # BF-924 (#1654): ``list_all`` was invented by the MagicMock; no CallsignRegistry has it, and the
        # real command raised AttributeError for any grant. The list names a target through the identity
        # registry; with none bound it shows the id (tests/test_bf924_trust_inputs.py covers both).
        mock_runtime.identity_registry = None
````

### 7.17 `tests/test_counselor_activation.py` (M2: defaults of removed fields)

SEARCH:
````python
        cfg = CounselorConfig()
        assert cfg.enabled is True
        assert cfg.profile_retention_days == 90
        assert cfg.trust_delta_threshold == 0.15
        assert cfg.sweep_max_agents == 50
        assert cfg.alert_on_red is True
        assert cfg.alert_on_yellow is False
````
REPLACE:
````python
        cfg = CounselorConfig()
        # BF-924 (#1654): the four fields nothing read are removed; the two left are read by the
        # Counselor and default to the values it hard-coded before.
        assert set(CounselorConfig.model_fields) == {"trust_delta_threshold", "sweep_max_agents"}
        assert cfg.trust_delta_threshold == 0.15
        assert cfg.sweep_max_agents == 50
````

### 7.18 `tests/test_ad1270e2h_emergence_models.py` (M2: the pre-move dump)

SEARCH:
````python
    'CounselorConfig': {   'enabled': True,
                           'profile_retention_days': 90,
                           'trust_delta_threshold': 0.15,
                           'sweep_max_agents': 50,
                           'alert_on_red': True,
                           'alert_on_yellow': False},
````
REPLACE:
````python
    # BF-924 (#1654): enabled, profile_retention_days, alert_on_red and alert_on_yellow had no reader
    # and were removed after the move.
    'CounselorConfig': {   'trust_delta_threshold': 0.15,
                           'sweep_max_agents': 50},
````

### 7.19 `tests/test_ad642_communication_benchmarks.py` (M2: a hand-set `_config` nothing reads)

SEARCH:
````python
        counselor._config = MagicMock()
        counselor._config.trust_delta_threshold = 0.15
        counselor._config.alert_on_red = True
        counselor._config.alert_on_yellow = False
````
REPLACE:
````python
        # BF-924 (#1654): ``_config`` was never a Counselor attribute (nothing read it). The Counselor's
        # config is ``_counselor_config``, set by ``__init__``, which this builder skips.
        from probos.config import CounselorConfig
        counselor._counselor_config = CounselorConfig()
````

### 7.20 New file: `tests/test_bf924_trust_inputs.py` (M2)

````python
"""BF-924 (#1654) M2: trust history, /grant list and the Counselor's config read APIs that exist.

Each repair is driven through its production caller: the profile route and the avatar telemetry for
``TrustNetwork.get_history``, the real ``/grant`` command for the grant list, and real Counselors
(one on a booted runtime) for ``CounselorConfig``.
"""

from __future__ import annotations

import importlib
import inspect
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.llm_client import BaseLLMClient
from probos.config import CounselorConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.substrate.registry import AgentRegistry
from tests.test_api_profile import mock_agent, mock_runtime  # noqa: F401  (fixtures)


# --- F04: TrustNetwork.get_history ----------------------------------------------------------------


def test_get_history_returns_the_agents_scores_oldest_first() -> None:
    trust = TrustNetwork()
    for success in (True, False, True):
        trust.record_outcome("agent-a", success=success, weight=1.0)
    trust.record_outcome("agent-b", success=True, weight=1.0)
    scores = [event.new_score for event in trust.get_events_for_agent("agent-a")]
    assert len(scores) == 3 and len(set(scores)) > 1  # premise: three readings, not all equal

    assert trust.get_history("agent-a", limit=2) == scores[-2:]
    assert trust.get_history("agent-a") == scores
    assert trust.get_history("agent-unknown") == []


def test_get_history_with_no_limit_is_empty() -> None:
    trust = TrustNetwork()
    trust.record_outcome("agent-a", success=True, weight=1.0)

    assert trust.get_history("agent-a", limit=0) == []


def test_the_profile_route_returns_the_trust_history(mock_runtime) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    from probos.api import create_app

    trust = TrustNetwork()
    trust.record_outcome("agent-123", success=True, weight=1.0)
    trust.record_outcome("agent-123", success=False, weight=1.0)
    # Replaces the fixture's MagicMock, which invented get_history (and so hid that it did not exist).
    mock_runtime.trust_network = trust
    expected = [event.new_score for event in trust.get_events_for_agent("agent-123")]
    assert len(expected) == 2

    data = TestClient(create_app(mock_runtime)).get("/api/agent/agent-123/profile").json()

    assert data["trustHistory"] == expected
    assert all(0.0 <= score <= 1.0 for score in data["trustHistory"])  # what useProfileResource.ts:54 admits


@pytest.mark.asyncio
async def test_the_avatar_trust_delta_is_the_last_trust_change() -> None:
    from probos.avatars.telemetry import build_telemetry_snapshot
    from tests.test_ad722_avatar_telemetry import _crew_with_full_dsl, _make_runtime

    runtime = _make_runtime(crew=_crew_with_full_dsl())
    trust = TrustNetwork()
    trust.record_outcome("agent-007", success=True, weight=1.0)
    trust.record_outcome("agent-007", success=False, weight=3.0)
    runtime.trust_network = trust  # the real network in place of the module's _FakeTrustNetwork
    events = trust.get_events_for_agent("agent-007")
    expected = events[-1].new_score - events[-2].new_score
    assert expected != 0.0  # premise

    snap = await build_telemetry_snapshot("agent-007", runtime)

    assert snap.current_signals.trust_delta == pytest.approx(expected)
    assert "insufficient_trust_history" not in snap.degraded_reasons


_TRUST_DOUBLES = (
    ("tests.test_ad722_avatar_telemetry", "_FakeTrustNetwork"),
    ("tests.test_ad722b4_fleet_telemetry", "_FakeTrustNetwork"),
    ("tests.test_ad722b_websocket_push", "_FakeTrustNetwork"),
    ("tests.test_ad1260_wellness_domain", "_FakeTrust"),
)


def _parameters(fn) -> list[tuple[str, object]]:
    return [(p.name, p.kind) for p in list(inspect.signature(fn).parameters.values())[1:]]


@pytest.mark.parametrize(("module_name", "class_name"), _TRUST_DOUBLES)
def test_the_trust_network_doubles_match_the_real_class(module_name: str, class_name: str) -> None:
    """The seam: a double that stands for TrustNetwork on these paths has only its methods, by name and kind."""
    double = getattr(importlib.import_module(module_name), class_name)
    methods = [name for name, value in vars(double).items() if callable(value) and not name.startswith("_")]
    assert methods

    for name in methods:
        real = getattr(TrustNetwork, name, None)
        assert real is not None, f"{name} is not a TrustNetwork method ({module_name}.{class_name})"
        assert _parameters(getattr(double, name)) == _parameters(real), name


# --- F05: /grant list -----------------------------------------------------------------------------


async def _grant_then_list(tmp_path, *, with_identity: bool):
    """Issue a grant and list grants through the real command, on real stores and registries."""
    from rich.console import Console

    from probos.clearance_grants import ClearanceGrantStore
    from probos.crew_profile import CallsignRegistry
    from probos.experience.commands.commands_clearance import cmd_grant
    from probos.identity import AgentIdentityRegistry

    identity = AgentIdentityRegistry(data_dir=tmp_path)
    await identity.start()
    store = ClearanceGrantStore(db_path=str(tmp_path / "grants.db"))
    await store.start()
    try:
        slot = "scout_scout_0_bf924"
        cert = await identity.resolve_or_issue(
            slot_id=slot, agent_type="scout", callsign="Wesley", instance_id="bf924",
            vessel_name="ProbOS", department="science", post_id="scout", baseline_version="v0",
        )
        agents = AgentRegistry()
        # Stands in for the scout: resolve() and register() read only id, agent_type, pool and is_alive.
        await agents.register(SimpleNamespace(id=slot, agent_type="scout", pool="scout", is_alive=True))
        callsigns = CallsignRegistry()
        callsigns.set_callsign("scout", "Crusher")  # a naming ceremony replaced the birth callsign
        callsigns.bind_registry(agents)
        runtime = SimpleNamespace(
            clearance_grant_store=store, callsign_registry=callsigns,
            identity_registry=identity if with_identity else None,
        )
        out = StringIO()
        console = Console(file=out, width=240)
        await cmd_grant(runtime, console, "issue Crusher full")
        grants = await store.list_grants()
        await cmd_grant(runtime, console, "list")
    finally:
        await store.stop()
        await identity.stop()
    return slot, cert, grants, out.getvalue().split("Clearance Grants", 1)[1]


@pytest.mark.asyncio
async def test_grant_list_names_the_target_by_its_live_callsign(tmp_path) -> None:
    slot, cert, grants, table = await _grant_then_list(tmp_path, with_identity=True)

    assert [grant.target_agent_id for grant in grants] == [cert.agent_uuid]  # _grant_issue stores the sovereign id
    assert cert.agent_uuid != slot
    assert "Crusher" in table
    assert "Wesley" not in table


@pytest.mark.asyncio
async def test_grant_list_without_an_identity_registry_shows_the_target_id(tmp_path) -> None:
    slot, _cert, grants, table = await _grant_then_list(tmp_path, with_identity=False)

    assert [grant.target_agent_id for grant in grants] == [slot]
    assert slot[:12] in table


# --- F10: CounselorConfig -------------------------------------------------------------------------


def _counselor(**config: object) -> CounselorAgent:
    return CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient), counselor_config=CounselorConfig(**config))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("threshold", "new_score", "assessments"),
    [(0.3, 0.7, 0), (0.1, 0.62, 1)],
    ids=["a-0.2-move-under-a-0.3-threshold", "a-0.12-move-over-a-0.1-threshold"],
)
async def test_the_trust_update_threshold_comes_from_the_config(threshold, new_score, assessments) -> None:
    """Through the Counselor's event listener; the move is measured from the default baseline (0.5)."""
    counselor = _counselor(trust_delta_threshold=threshold)
    await counselor.initialize(trust_network=TrustNetwork())
    counselor.get_or_create_profile("agent-1")  # _on_trust_update reassesses only a known agent

    await counselor._on_event_async({
        "type": EventType.TRUST_UPDATE.value, "data": {"agent_id": "agent-1", "new_score": new_score},
    })

    assert len(counselor.get_profile("agent-1").assessments) == assessments


@pytest.mark.asyncio
async def test_the_sweep_bound_comes_from_the_config() -> None:
    """Through act(), the wellness-report intent, which passes no bound."""
    counselor = _counselor(sweep_max_agents=2)
    registry = AgentRegistry()
    for i in range(3):
        # Crew stand-ins: the sweep reads id, tier, callsign and agent_type; the gather reads confidence.
        await registry.register(SimpleNamespace(
            id=f"agent-{i}", agent_type="crew", pool="crew", tier="crew", callsign=f"Crew{i}", confidence=0.8,
        ))
    await counselor.initialize(registry=registry)

    result = await counselor.act({"intent": "counselor_wellness_report"})

    assert result["result"]["total_assessed"] == 2


@pytest.mark.asyncio
async def test_the_booted_counselor_takes_the_operators_config(tmp_path) -> None:
    """The seam: startup gives the Counselor the operator's CounselorConfig."""
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(config=SystemConfig(counselor=CounselorConfig(sweep_max_agents=2)), data_dir=tmp_path)
    await rt.start()
    try:
        [counselor] = rt.registry.get_by_pool("counselor")
        assert isinstance(counselor, CounselorAgent)
        eligible = [
            agent for agent in rt.registry.all()
            if agent.id != counselor.id and getattr(agent, "tier", "") in ("", "domain", "crew")
        ]
        assert len(eligible) > 2  # premise: the bound, not the crew size, limits the sweep
        result = await counselor.act({"intent": "counselor_wellness_report"})
    finally:
        await rt.stop()

    assert result["result"]["total_assessed"] == 2


def test_the_removed_counselor_fields_are_gone_and_old_configs_still_load() -> None:
    assert set(CounselorConfig.model_fields) == {"trust_delta_threshold", "sweep_max_agents"}

    cfg = SystemConfig.model_validate({"counselor": {
        "enabled": False, "profile_retention_days": 7, "alert_on_red": False, "alert_on_yellow": True,
        "sweep_max_agents": 9,
    }})

    assert cfg.counselor.sweep_max_agents == 9
    assert cfg.counselor.trust_delta_threshold == 0.15
````

### 7.21 `tests/test_counselor_therapeutic.py` (M2, A1-2: the `__new__` builder that reaches `_on_trust_update`)

SEARCH:
````python
    agent._add_event_listener_fn = None
    agent._profile_store = None
````
REPLACE:
````python
    agent._add_event_listener_fn = None
    agent._profile_store = None
    # BF-924 (#1654): __init__ sets the Counselor's CounselorConfig, which _on_trust_update and
    # _run_wellness_sweep read; this builder skips __init__, so it sets the default config itself.
    from probos.config import CounselorConfig

    agent._counselor_config = CounselorConfig()
````

### 7.22 `tests/test_ad1270e1_config_facade.py` (M2, A1-3: the measured field count)

SEARCH:
````python
    # BF-918 adds attachments.tts_audio_retention_seconds (1879 -> 1880).
    assert counts["field_definitions"] == 1880  # AD-1206 intentionally adds github_repository.
````
REPLACE:
````python
    # BF-918 adds attachments.tts_audio_retention_seconds (1879 -> 1880).
    # BF-924 (#1654) removes CounselorConfig's four unread fields: enabled, profile_retention_days,
    # alert_on_red and alert_on_yellow (1880 -> 1876).
    assert counts["field_definitions"] == 1876  # AD-1206 intentionally adds github_repository.
````

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)`. The entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
````markdown
# ProbOS Progress
````
REPLACE:
````markdown
# ProbOS Progress

**BF-924 (2026-10-25), #1654 -- trust inputs are read through APIs that exist.** The AD-535/536 procedure-compilation clamp read a `_trust_score` attribute nothing sets, so every agent counted as a Lieutenant; it now reads the agent's live trust (`TrustNetwork.get_score`, as Rank does): Ensigns run stored Level 3 and 4 procedures as Guided (Level 2), a Commander's approved procedure can be promoted to Level 5, and an unreadable trust is held to Level 2 with a WARNING. `TrustNetwork.get_history` now exists, so the Captain's profile shows trust history and the avatar's `trust_delta` is real; both `hasattr` guards that hid its absence are removed. `/grant list` raised for any grant (`CallsignRegistry.list_all` never existed); it names a target through its birth certificate and live callsign. The Counselor takes `CounselorConfig` by constructor injection and reads `trust_delta_threshold` and `sweep_max_agents` (defaults unchanged); `enabled`, `profile_retention_days`, `alert_on_red` and `alert_on_yellow` had no reader and are removed. New: `tests/test_bf924_compilation_trust.py`, `tests/test_bf924_trust_inputs.py`. The contract is `prompts/bf-924-trust-inputs-through-real-apis.md`.
````

**`DECISIONS.md`:**

SEARCH:
````markdown
### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)
````
REPLACE:
````markdown
### BF-924 -- Trust inputs read through APIs that exist (2026-10-25, #1654)

- *Compilation clamp.* AD-535/536 read the agent's live trust through `get_score`, the gauge that already sets Rank and agency; no BF-921 D3 hold, because the gauge is already the live one and the clamp only restricts Ensigns and opens AD-536's designed Level 5 path. An unreadable trust is held to Level 2 (fail closed) with a WARNING. Rejected: the chain-only `observation["_trust_score"]`, and a cached copy of the score.
- *Trust history.* `TrustNetwork.get_history` maps the in-memory event log to scores, one owner of the mapping; the callers' `hasattr` guards, which hid its absence, are removed. Its consumers are displays and a voice pitch; the avatar divergence's trust write does not depend on it.
- *Grant list.* A grant's target is a sovereign id, so the list names it through the birth certificate and the live callsign, not a callsign list.
- *Counselor config.* Two fields are read, with defaults equal to the constants they replace; the four unread fields are removed rather than wired. Today's Bridge alerts follow no single red/yellow rule, so wiring `alert_on_*` would either silence alerts or invent them; an alert-silencing switch is the Captain's call. Unknown keys are ignored, so old configs load.
- *Reversal.* Revert the commits; the clamp returns to 0.5 for every agent, the history to empty, the grant list to raising and the config to unread.

### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)
````

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916, BF-921 and BF-923 precedent).

**#1654 checklist text** (the orchestrator records it on the issue):
- [ ] (F02) The clamp and the promotion step read live trust; Ensign capped at Level 2, Commander reaches Level 5, an unreadable trust held to Level 2 (M1).
- [ ] (F02) The read-only count before the build posted (D4).
- [ ] (F04) `TrustNetwork.get_history`; profile history and avatar `trust_delta` real; the doubles pinned by a seam test (M2).
- [ ] (F05) `/grant list` works with grants present, through the real registries (M2).
- [ ] (F10) `trust_delta_threshold` and `sweep_max_agents` read; four fields removed; config reference and facade baseline regenerated (M2).
- [ ] First live session after merge: section 16's counts recorded on #1654.

## 9. What this does NOT change

- `_max_compilation_level_for_trust`, `_max_compilation_level_for_promoted`, the compilation thresholds (`config.py:266-275`), the dispatch levels, the demotion rule, the procedure store and dreaming are unchanged.
- The other live-trust reads in `CognitiveAgent` (`:2870`, `:3351`, `:6042`, `:6230`, `:9123`, `:11455`) are not consolidated (R1).
- `TrustNetwork`'s event log, its size and its persistence are unchanged; `get_events_for_agent` and `standing_interests.py:701` are unchanged.
- The avatar modulation rules, thresholds and divergence logic are unchanged; no `ui/` file is touched.
- `CallsignRegistry`, the identity registry and `_grant_issue`/`_grant_revoke` are unchanged.
- `_gather_agent_metrics`, its BF-921 D3 hold, `trust_observations`, `observed_baseline`, `profile.baseline`, `assess_agent`, `_alert_bridge` and every handler but the threshold line are unchanged (BF-923 D4, D8).

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7)

Run each row on the applied tree after an unmutated baseline run passes; restore each file before the next row. M1 (HIGH) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_compilation_trust.py tests/test_graduated_compilation.py tests/test_level_5_dispatch.py -n 0 -x -q
```

M2 (STANDARD) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_trust_inputs.py tests/test_ad622_clearance_grants.py tests/test_counselor_activation.py -n 0 -x -q
```

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| R1 | 1 | `src/probos/cognitive/cognitive_agent.py` | `trust_score = self._compilation_trust_score()` | `trust_score = 0.5` | `test_an_ensign_runs_a_stored_level_4_procedure_as_guided`, `test_clamping_applied_in_check_procedural_memory` |
| R2 | 1 | `src/probos/cognitive/cognitive_agent.py` | `_ts = self._compilation_trust_score()  # BF-924 (#1654): the live trust, as in the clamp` | `_ts = 0.5` | `test_a_commanders_approved_procedure_is_promoted_to_level_5`, `test_an_ensigns_successes_do_not_promote_it_past_level_2` |
| R3 | 1 | `src/probos/cognitive/cognitive_agent.py` | `return float(trust_network.get_score(self.id))` | `return 0.5` | the Ensign and Commander tests |
| R4 | 1 | `src/probos/cognitive/cognitive_agent.py` | `return 0.0  # BF-924: unknown trust takes the Ensign cap (Level 2)` | `return 0.5` | `test_an_unreadable_trust_is_held_to_level_2_and_warned[raises]`, `[absent]` |
| R5 | 1 | `src/probos/cognitive/cognitive_agent.py` | `logger.warning("BF-924 (#1654): trust read failed for %s; procedure compilation held to Level 2", self.id, exc_info=True)` | the same with `logger.debug` | `test_an_unreadable_trust_is_held_to_level_2_and_warned` |
| R6 | 2 | `src/probos/consensus/trust.py` | `return [event.new_score for event in self.get_events_for_agent(agent_id, n=limit)]` | `return []` | `test_get_history_returns_the_agents_scores_oldest_first`, the route and telemetry tests |
| R7 | 2 | `src/probos/consensus/trust.py` | `if limit <= 0:` | `if False:` | `test_get_history_with_no_limit_is_empty` |
| R8 | 2 | `src/probos/routers/agents.py` | `trust_history = runtime.trust_network.get_history(agent.id, limit=20)  # BF-924 (#1654): the guard here hid that the method did not exist` | `trust_history = []` | `test_the_profile_route_returns_the_trust_history` |
| R9 | 2 | `src/probos/avatars/telemetry.py` | `if trust_network is not None:` | `if False:` | `test_the_avatar_trust_delta_is_the_last_trust_change` |
| R10 | 2 | `src/probos/experience/commands/commands_clearance.py` | `agent_display = _grant_target_callsign(runtime, g.target_agent_id) or g.target_agent_id[:12]` | `agent_display = g.target_agent_id[:12]` | `test_grant_list_names_the_target_by_its_live_callsign` |
| R11 | 2 | `src/probos/experience/commands/commands_clearance.py` | `cert = identity_reg.get_by_uuid(target_agent_id) or identity_reg.get_by_slot(target_agent_id)` | `cert = identity_reg.get_by_slot(target_agent_id)` | `test_grant_list_names_the_target_by_its_live_callsign` |
| R12 | 2 | `src/probos/experience/commands/commands_clearance.py` | `return runtime.callsign_registry.get_callsign(cert.agent_type) or cert.callsign` | `return cert.callsign` | `test_grant_list_names_the_target_by_its_live_callsign` |
| R13 | 2 | `src/probos/cognitive/counselor.py` | `if delta < self._counselor_config.trust_delta_threshold:` | `if delta < 0.15:` | `test_the_trust_update_threshold_comes_from_the_config` (both cases) |
| R14 | 2 | `src/probos/cognitive/counselor.py` | `max_agents = self._counselor_config.sweep_max_agents` | `max_agents = 50` | `test_the_sweep_bound_comes_from_the_config` |
| R15 | 2 | `src/probos/cognitive/counselor.py` | `self._counselor_config: CounselorConfig = kwargs.pop("counselor_config", None) or CounselorConfig()` | `self._counselor_config: CounselorConfig = CounselorConfig()` | `test_the_sweep_bound_comes_from_the_config`, the threshold tests |
| R16 | 2 | `src/probos/startup/agent_fleet.py` | `counselor_config=config.counselor,  # BF-924 (#1654): the operator's CounselorConfig` | `counselor_config=None,` | `test_the_booted_counselor_takes_the_operators_config` (outside the M2 command: run it alone, `tests/test_bf924_trust_inputs.py::test_the_booted_counselor_takes_the_operators_config`) |

The removed `hasattr` guards and the removed config fields cannot be mutated back in one line; R8, R9 and `test_the_removed_counselor_fields_are_gone_and_old_configs_still_load` pin them.

A1 adds no source line, so no mutation row. Its three pins are checked by deletion instead (run each alone on the applied, regenerated tree, restore after): delete `, crew_only: bool = False` from §7.15's `all_scores` (expect `test_the_trust_network_doubles_match_the_real_class[tests.test_ad1260_wellness_domain-_FakeTrust]` to fail on `all_scores`); delete `agent._counselor_config = CounselorConfig()` from §7.21 (expect `test_trust_update_sends_dm_when_unfit` to fail with `AttributeError`); set the census header's `default_false` back to 226 (expect `test_the_measured_census_matches_the_manifest_header`). Command: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_trust_inputs.py tests/test_counselor_therapeutic.py tests/test_ad1185_config_profiles.py -n 0 -x -q`.

## 11. Verified Against Codebase (2026-10-25, worktree `bf924-draft` at `ba45c61f`)

```
git log --oneline -1                                  -> ba45c61f BF-923 ledger: regenerate the AD and BF ledger (part of #1652)
grep -n "_trust_score" src/probos/cognitive/cognitive_agent.py
  1852 trust_score = getattr(self, "_trust_score", 0.5); 5975 observation.get("_trust_score", 0.5); 6043, 6231 observation["_trust_score"] = _trust; 7768 _ts = getattr(self, "_trust_score", 0.5)
read cognitive_agent.py:1722-1889  -> _check_procedural_memory: store via _procedure_store (:1716-1720, runtime.procedure_store); selection :1831; applied :1847; clamp :1851-1861; dispatch :1864-1877; Level>=4 diagnosis :1884-1889
read cognitive_agent.py:2663-2684  -> _max_compilation_level_for_trust (<0.5 -> 2 else 4); _max_compilation_level_for_promoted (approved and >= TRUST_COMMANDER -> 5)
read cognitive_agent.py:3328-3353  -> runtime = getattr(self, "_runtime", None); live_trust = trust_net.get_score(self.id)
read cognitive_agent.py:7729-7801  -> cached record :7732-7741; guided record :7744-7753; promotion :7755-7785; demotion :7786-7801
read cognitive_agent.py:6564-6586  -> act(): success True unless action == "error"
grep -n "^logger = " cognitive_agent.py -> 63 logging.getLogger(__name__)
grep -n "^TRUST_COMMANDER|^TRUST_LIEUTENANT|^COMPILATION_" src/probos/config.py -> 217 0.7; 218 0.5; 266 THRESHOLD 3; 267 DEMOTION 2; 268 MAX 5; 271 LEVEL_3_MIN 0.5
grep -n "def get_score|def get_events_for_agent|def create_with_prior|def record_outcome|_event_log:" src/probos/consensus/trust.py -> 1017; 1033; 358; 372; 265 deque(maxlen=500)
read trust.py:97-99 (score = alpha/(alpha+beta)); :32-37 (trust_scores schema); :116-129 (TrustEvent.new_score)
grep -n "trust.db" src/probos/runtime.py -> 764
grep -n "get_history" routers/agents.py avatars/telemetry.py -> agents.py 259-260; telemetry.py 16, 358, 723, 725
grep -n "trustHistory" -> routers/agents.py:383; ui/src/hooks/useProfileResource.ts:54; ui/src/components/profile/ProfileHealthTab.tsx:41-44; ui/src/store/types.ts:509
grep -n "trust_delta" src/probos/avatars -> telemetry.py 242-243, 289, 296, 452-457, 720-738, 778; telemetry_frames.py 161-176
read divergence_detector.py:271-354, :390-633; telemetry.py:436-513; modulation_manifest.json:3-9, :19-26
grep -n "inject_into_agent_context" -> config.py:2023 (False); config/system.yaml:1631 (true); cognitive_agent.py:6890
read records_writer.py:87-122; self_perception.py:106-129
grep -n "class _FakeTrustNetwork|def get_history" tests/test_ad722*.py -> test_ad722_avatar_telemetry.py 71/75, 82 (NoHistoryMethod); test_ad722b4_fleet_telemetry.py 38/39; test_ad722b_websocket_push.py 219/223
grep -n "get_history" tests/test_bf711_*.py tests/test_ad566c_*.py -> bf711:114 (class _Store :110); ad566c:78 (class MockQualificationStore :54)
grep -n "get_history.return_value = \[\]" tests -> 13 files: test_ad1052a:131, ad1052b:357, ad1052c:275, ad1161:371, ad706a:153, ad718a:160, ad718:155, ad720d_2_1:64, ad721d:68, ad721g:121, ad721:124, ad722b_1:54, ad982a:155; test_api_profile uses an unconfigured MagicMock (:42)
read tests/test_ad573_memory_budget.py:157-164 (monkeypatches _check_procedural_memory whole)
read tests/test_ad1260_wellness_domain.py:45-59, :555 (_FakeTrust; agents.agent_profile(_SUBJECT, runtime=domain_runtime))
read tests/test_ad1259_one_source_of_truth.py:70-85, :227-238, :321-348 (agent_profile runtimes carry no trust_network)
read tests/test_api_profile.py:17-99 (mock_agent, mock_runtime, create_app + TestClient)
read commands_clearance.py:39-103 (_grant_issue: resolve -> resolve_sovereign_id_from_slot), :141-195 (_grant_list)
grep -n "def list_all" src/probos -> 0
read crew_profile.py:660-767 (CallsignRegistry: resolve, get_callsign, all_callsigns, live_callsign_map, set_callsign, bind_registry)
grep -n "def get_by_uuid|def get_by_slot|async def resolve_or_issue|async def start|async def stop" src/probos/identity.py -> 773, 787, 1004, 560, 678
read identity.py:174-177 (agent_uuid, did, agent_type, callsign), :458-463 (slot_mappings), :569 (identity.db)
grep -n "self.callsign_registry =|self.identity_registry|self.clearance_grant_store" runtime.py -> 747; 1235, 2810; 1103, 3329
grep -n "async def start|async def issue_grant|async def list_grants" src/probos/clearance_grants.py -> 62; 105; 163 (list_grants needs a db)
read substrate/registry.py:24-77 (register, get, get_by_pool, all)
grep -n "CounselorConfig|config.counselor" src tests scripts docs -> config.py:163, :3973; config_models/__init__.py:157, :241; emergence.py:251; tests: test_ad1270e2h (63, 95, 129, 202-207, 461), test_counselor_activation (621-638); docs/development/config-reference.md:1283-1294; config-facade-baseline.yaml:1322-1334; config-profiles.yaml:758
grep -n "trust_delta_threshold|sweep_max_agents|alert_on_red|alert_on_yellow|profile_retention_days" src -> emergence.py:255-259 only
grep -n "counselor" config/node-*.yaml config/profiles/*.yaml -> 0
grep -n "model_config|extra" src/probos/config_models/emergence.py -> only the module docstring (:3)
read config.py:4139-4149 (load_config: SystemConfig.model_validate(raw))
read counselor.py:13-31 (imports), :560-590 (__init__), :658-733 (initialize), :969-1049 (_run_wellness_sweep), :1053-1059 (TRUST_UPDATE -> _on_trust_update), :1725-1760 (_on_trust_update), :2211-2224, :2282-2296 (_alert_bridge), :2870-2886 (act, counselor_wellness_report)
grep -n "_alert_bridge(" counselor.py -> 1263, 1751, 1794, 2006 (+ def 2282)
grep -n "_run_wellness_sweep(" src -> counselor.py:969 (def), :2878; routers/counselor.py:199
read startup/agent_fleet.py:178-193; startup/finalize.py:6119-6139 (initialize call, config in scope)
read substrate/pool.py:42-70, :210, :304-308 (spawn kwargs kept for respawn)
read runtime.py:2577-2657 (create_pool forwards **spawn_kwargs)
read substrate/agent.py:41 (BaseAgent.__init__(pool, **kwargs)); cognitive_agent.py:1320-1327
grep -n "unclassified_flags|stale" scripts/check_config_profiles.py -> 699-731
read scripts/check_config_facade.py:237-272 (--update-baseline header); scripts/gen_config_reference.py:10-12 (--check, test_config_reference_current.py)
read tests/test_ad1270e2h_emergence_models.py:122-150 (bound counts: CounselorConfig 0), :154, :202-207, :446-455, :503-525, :619-644
read tests/test_ad642_communication_benchmarks.py:505-535; tests/test_counselor_activation.py:328-345, :621-638; tests/test_ad622_clearance_grants.py:312-332
read tests/test_replay_dispatch.py:28-107, :425-445; tests/test_fallback_learning.py:28-115, :215-243
read tests/test_graduated_compilation.py:70-101, :146-189, :612-669; tests/test_level_5_dispatch.py:68-99, :157-229
grep -n "approved" (the seven procedure test files) -> test_level_5_dispatch.py 135-196; test_teaching_protocol.py 112, 156-157 only
grep -n "procedure_records|procedures.db|find_matching" src/probos/cognitive/procedure_store.py -> 98-124; 207; 925-958 (no agent filter)
read procedures.py:289-320; dreaming.py:1295-1320, :1863-1886, :2138-2160, :2449-2472
grep -n "class MockLLMClient|def call_count" src/probos/cognitive/llm_client.py -> 2684; 3082
grep -n "^PROGRESS|# ProbOS Progress" PROGRESS.md -> 1 (once); grep -n "^### BF-92" DECISIONS.md -> 709, 739 (BF-923), 751, 762
pytest --collect-only (M1 nine files) -> 270; run -> 270 passed (see section 17 on which src it imported)
pytest --collect-only (M2 eighteen files) -> 1015
A1 (2026-10-25):
read logs/bf924r1/oracle-union-evidence.txt:1-60 -> 4 failures (seam all_scores; _counselor_config AttributeError at counselor.py:1744; 1876 == 1880; 226 == 225)
read logs/bf924r1/generated-config-diff.txt -> the hunks listed in section 6
read tests/test_ad1260_wellness_domain.py:45-62 -> _FakeTrust: get_score, get_record, get_events_for_agent(n=5), all_scores(self)
grep -n "def get_score|def get_record|def get_events_for_agent|def all_scores" consensus/trust.py -> 1017; 1024; 1033 (n=20); 1077 all_scores(self, crew_only: bool = False)
grep -n "\.all_scores\(" src/probos -> 8 calls, none passes an argument (section 3, A1-1)
grep -n "class _FakeTrustNetwork|    def " tests/test_ad722*.py -> ad722b4:38-43 and ad722b:219-229 and ad722:71-79 define get_history, get_score only
read counselor.py:494-590 -> class body constants only (:504-558); every instance attribute set in __init__ (:562-590)
read tests/test_counselor_therapeutic.py:12-16, :38-69 (_make_counselor), :254-277 (reaches _on_trust_update)
read tests/test_bf206_confab_feedback.py:345-358 (__new__ fixture sets _suppression_history: the BF-921 precedent)
read tests/test_ad1270e1_config_facade.py:1530-1559 -> 1555-1556 the pin; names 309, models 229
read docs/development/config-profiles.yaml:14-23 (census); tests/test_ad1185_config_profiles.py:857-859; scripts/check_config_profiles.py:60-62 (inserts its tree's src), :148-174 (default_false_flags)
probe logs/bf924r1/test_census_probe.py (gitignored scratch; imported D:\ProbOS-worktrees\bf924-draft\src\probos) ->
  base  boolean 452, default_false 226 (= checker), default_true 226, armed 85, never_armed 141
  after boolean 449, default_false 225, default_true 224, armed 85, never_armed 140 (counselor booleans: enabled True, alert_on_red True, alert_on_yellow False)
git rev-parse HEAD -> ba45c61f5550e110aab4b00441d78f3f590ba513
```

## 12. Absence Verified (2026-10-25)

```
CLAIM: nothing assigns the _trust_score attribute
RUN:   Grep "\._trust_score\s*=|\"_trust_score\"\)|'_trust_score'" src/
FOUND: sub_task.py:721 trust_score=context.get("_trust_score") (a dict key)
HOLDS: yes (0 attribute writes)

CLAIM: TrustNetwork has no get_history; nothing defines list_all
RUN:   Grep "def get_history|def list_all" src/probos
FOUND: governance/compensation.py:156, knowledge/records_store.py:1003, cognitive/qualification.py:255 (none in consensus/trust.py); list_all: 0
HOLDS: yes. Callers of list_all: commands_clearance.py:171; episodic_procedural_bridge.py:84 behind hasattr (R5)

CLAIM: no CounselorConfig field has a reader; the Counselor never receives the config
RUN:   Grep "trust_delta_threshold|sweep_max_agents|alert_on_red|alert_on_yellow|profile_retention_days" src; Grep "config\.counselor|cfg\.counselor" src; Grep "self\._config\b" counselor.py
FOUND: emergence.py:255-259 only; config.py:3973 (the declaration) only; 0
HOLDS: yes

CLAIM: the agent's _teach_procedure and project_self_perception have no caller
RUN:   Grep "\._teach_procedure\(|project_self_perception\(" src/probos
FOUND: self_perception.py:74 (the def) only
HOLDS: yes

CLAIM: _check_procedural_memory has one production caller
RUN:   Grep "_check_procedural_memory\(" src
FOUND: cognitive_agent.py:1722 (def), :3743 (decide)
HOLDS: yes

CLAIM: nothing reads the dispatch level after the clamp except the dispatch and the promotion step
RUN:   Grep "guided_by_procedure|get\(\"cached\"" src/probos; Grep "TEACHING_MIN_COMPILATION_LEVEL|compilation_level\s*(>=|==|>)\s*[345]" src/probos
FOUND: cognitive_agent.py:2468, 7732, 7744, 7805, 7842 (used_procedure in a journal dict); tiered_knowledge.py:306 (its own kwarg); level reads: 1855, 2100, 2850 (_teach_procedure), commands_procedure.py:412, routers/procedures.py:167
HOLDS: yes

CLAIM: no counselor key in the node configs or profiles
RUN:   Grep "counselor" config/node-*.yaml config/profiles/*.yaml
FOUND: 0
HOLDS: yes

CLAIM: the new names are new
RUN:   Grep "_compilation_trust_score|_grant_target_callsign|_counselor_config|counselor_config" src tests; Grep "limit <= 0|new_score for" consensus/trust.py
FOUND: tests/test_ad659c_optimization_counselor.py (a local ChainOptimizerCounselorConfig variable) only; 0
HOLDS: yes; every mutation-row line is new or occurs once (telemetry.py "if trust_network is not None" occurs once, at :723, before the edit)

CLAIM (A1-2): of the Counselors built without __init__, only test_counselor_therapeutic's _make_counselor reaches a reader of _counselor_config
RUN:   Grep "class \w+\(CounselorAgent\)|__new__\(\w*Counselor" src tests; Grep "_on_trust_update|_run_wellness_sweep|counselor_wellness_report|TRUST_UPDATE" tests (count); Grep "_on_event|\.act\(|handle_intent|trust_update|wellness_report|_counselor_config" over the 17 __new__ files plus test_ad1229_message_receipts.py; Grep "from tests\.(<the __new__ files>) import" tests
FOUND: 22 CounselorAgent __new__ sites in 17 files, no subclass; readers appear in 14 files, of which only test_counselor_therapeutic builds by __new__ (its :276 calls _on_trust_update; :143-146 calls _build_therapeutic_message only); in the others, bf206:365 routes CONFABULATION_SUPPRESSED (not TRUST_UPDATE), test_ad642's handle_intent hits are AsyncMock replacements, test_ad568e:5 is a docstring; one cross-file import, test_ad1229_message_receipts.py:90 (_make_counselor from the e2e file; no reader in either)
HOLDS: yes, for the readers this contract adds; the broad gate is the last check

CLAIM (A1-3): no other place pins the facade's measured numbers or hashes
RUN:   Grep "\b(1880|1891|1876|1887)\b|fc24f1a1|291ee4ff|ba3ec2db" over the tree (logs excluded); Grep "field_definitions|canonical_dump_leaves|canonical_dump_sha256" scripts tests docs src
FOUND: config-facade-baseline.yaml:50, :51, :56, :1327, :3418 (regenerated); tests/test_ad1270e1_config_facade.py:1555-1556 (§7.22); every other hit is a line number, a test-suite total or a historical prompt (DECISIONS.md:2563 and PROGRESS.md:519 "UI full 1891 passed"; prompts/bf-918-*:1706-1707 the archived BF-918 pin; docs/research/communication-discipline-skill-research.md:192, :622 the year 1876); the facade tests compare canonical_dump_sha256 against a computed digest (:252, :1180), not a literal
HOLDS: yes

CLAIM (A1-4): only default_false in the census block is pinned, and nothing else states these counts as current
RUN:   Grep "measured_at_commit|\"census\"|'census'" scripts tests src; Grep "\b(173|172|226|225|445|136|85)\b" config-profiles.yaml, test_ad1185, check_config_profiles.py; Grep "22[56] default|frozen=17[23]" docs tests scripts
FOUND: test_ad1185_config_profiles.py:859 only; config-profiles.yaml:19-23 only; docs/development/agentic-event-correlation.md:165 (a dated, historical 429 / 204 / 225 census, not a pin)
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- Bug fix in ProbOS plumbing (dead reads behind `getattr` defaults and `hasattr` guards); no outside analogue, so no external search, and `docs/research/reference-projects.md` was not consulted. Internal: AD-535/536/537 (compilation levels, promotion, teaching), BF-263 (trust by `self.id`), BF-907 (slot keys), AD-722/722a (avatar telemetry, divergence), AD-622 (grants), AD-503 (Counselor config), BF-921 D3 and BF-923 D8.
- Blind spots addressed: the grant target's id form (D5; a callsign list could never match); the avatar's crew-visible pitch and rule text (E6, which the issue's "Captain-facing" missed: `system.yaml:1631` turns interoception on); the divergence trust write, shown independent of `trust_delta` (5b); the Level 2 path's counters, shown identical to the replay path's (5a); `float(MagicMock())` running the masked tests at Senior trust (section 6); the Counselor's non-uniform alert paths (D7); the profile manifest's frozen flag row and the two generated docs (D7).
- Considered, deferred: consolidating the six live-trust reads (R1); a persisted trust history (R6); config bounds (R4).

## 14. Diff Reviewer: properties to verify

1. Both trust reads of the compilation clamp (the dispatch cap and the promotion cap) come from one helper that returns `float(get_score(self.id))` from the runtime's trust network, and 0.0 with one WARNING when the network is absent or the read raises. No other site's behaviour changes.
2. For trust below 0.5, no stored procedure is dispatched above Level 2 and no promotion goes above Level 2; for trust from 0.5, dispatch and promotion are as before except that an `approved` procedure with trust from 0.7 can be promoted to Level 5. The clamp writes no stored level.
3. `TrustNetwork.get_history(agent_id, limit)` returns the agent's last `limit` event scores oldest first, `[]` for a non-positive limit or an unknown agent, and reads only the event log.
4. The profile route and the avatar telemetry call `get_history` unguarded; telemetry still never raises.
5. Every test double that stands for `TrustNetwork` on the two `get_history` paths has only `TrustNetwork` methods, with the same parameter names and kinds, and a test fails if one drifts; `_FakeTrust.all_scores` returns the same scores with or without `crew_only` (A1-1).
6. `/grant list` never raises for a stored grant; it shows the live callsign of a target whose certificate resolves by uuid or slot, else the id prefix as before.
7. The Counselor's trust-update threshold and default sweep bound come from the `CounselorConfig` startup passes; with the default config every result is as before; an explicit `max_agents` still wins. Nothing else in `counselor.py` changes, BF-923's gather hold included.
8. `CounselorConfig` has exactly the two read fields; a config with the removed keys loads; the tracked `system.yaml`, the profile manifest (its frozen rows and its `census:` header), the facade baseline and the config reference agree with the model; the generated diffs are exactly section 6's hunks; the field-count pin is 1876.
9. Every replaced test double or pin says inline what it masked or why it changed; no test was deleted.
10. No production line was added for Counselors built without `__init__` (no class-level default, no `getattr` fallback); the one test builder that reaches a reader sets `_counselor_config` itself (A1-2).

## 15. Acceptance criteria

- Through `decide` on a real agent with a real `TrustNetwork`: an Ensign runs a stored Level 4 procedure as Guided, a Lieutenant replays it, and an unreadable trust is held to Level 2 with a WARNING. Through `handle_intent`: a Commander's approved Level 4 procedure is promoted to Level 5; an Ensign's successes do not promote a Level 2 procedure.
- Through the real route and telemetry, profile trust history and avatar `trust_delta` come from `TrustNetwork.get_history`; the four doubles are pinned to the real class.
- Through the real `/grant` command and registries, `/grant list` names a grant's target with grants present, with and without an identity registry.
- Through real Counselors (one on a booted runtime), `trust_delta_threshold` and `sweep_max_agents` come from the config; the removed fields are gone and old configs load; the config reference and facade baseline are regenerated and checked.
- The count in D4 is posted on #1654 before the build.
- Before editing, the tests that pin current behaviour were grepped, and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance (read-only)

- **Before the build:** D4's count, posted on #1654.
- **After the first session on the merged build**, from `%LOCALAPPDATA%\ProbOS\data` and the vessel log, record on #1654:
  - the count of `BF-924 (#1654): trust read failed` lines (expected 0);
  - the count of `insufficient_trust_history` warnings against the issue's 74 (expected fewer once agents have two trust events);
  - from `procedures/procedures.db`, D4(a) again, and any procedure now at Level 5 (expected only `approved` ones of Commander+ executors);
  - the count of `Procedure '...' promoted to Level` log lines for Level 3 against earlier sessions (E2 expects fewer, from Ensigns);
  - one `/grant list` with a grant present (expected a table naming the target).

## 17. Not verified

- **Which source the tests import.** The focused baseline run here (`270 passed`) imported `D:\ProbOS\src` (the warning path in its output), not this worktree's `src`: the venv's editable install points at the main checkout. The orchestrator must run every focused check, tests-first run and mutation row against the scratch tree's `src` (e.g. `PYTHONPATH` set to it), or the counts above prove nothing about this tree.
- D4's numbers: read by the orchestrator and posted on #1654 (A1): no active procedure is at Level 3 or above, so M1 changes no live dispatch of a stored procedure today.
- That `float(MagicMock())` is 1.0 (CPython `unittest.mock` documents `__float__: 1.0`; read, not run here). Section 6's census rests on it; the tests-first run shows it (no other test of the seven files may fail).
- The new tests were written in a read-only consult and not run. In particular: that `test_fallback_learning.py`'s `object.__new__` agent completes a Guided decision through `handle_intent` with a `MockLLMClient` (`test_an_ensigns_successes_do_not_promote_it_past_level_2`; its `record_completion` premise fails rather than passes if it does not); that `ReplayTestAgent`'s `decide` reaches the LLM with a real `TrustNetwork` on the `MagicMock` runtime as it does with a `MagicMock` one; that a default `SystemConfig()` boot registers one Counselor and more than two sweep-eligible agents; that `_first_mutable_free_field` and `_perturb` in `test_ad1270e2h_*` handle `CounselorConfig`'s new first field, a float; that Rich renders the grant table within 240 columns without truncating "Crusher".
- ~~That `check_config_facade.py --update-baseline` changes only the `CounselorConfig` row~~ (A1: wrong; the oracle's run gives section 6's hunks, and its `--check` passed with no review metadata).
- A1: the four repaired cases and the rest of the union were not rerun here (this was an edit-only run); the census figures were measured here by a scratch probe on this tree's `src` (section 11), not by the oracle.
- That the operator's local `config/system.yaml` on the Captain's machine is not customised in the counselor block; if it is, the merge conflicts there, and either result loads (unknown keys are ignored).

## 18. For the register (found here, not fixed by this change)

- **R1.** Six live-trust reads in `CognitiveAgent` (`:2870`, `:3351`, `:6042`, `:6230`, `:9123`, `:11455`) each guard and read `get_score(self.id)` their own way; `_compilation_trust_score` is a seventh. One helper is a DRY refactor with its own consumer list.
- **R2.** AD-503's assessment retention (`profile_retention_days`, `_cleanup_old_assessments`, `prompts/archive/ad-503-counselor-activation.md:879`) was never built: the `assessments` table grows without bound (BF-923 D7 bounds only the profile).
- **R3.** An operator Bridge-alert policy for the Counselor (which paths alert at which severity) would be new design and would include alert-silencing switches: the Captain's call.
- **R4.** `trust_delta_threshold` and `sweep_max_agents` carry no bounds (a negative bound silently disables the sweep). Adding them changes three pinned AD-1270e2 tables (`test_ad1270e2h_*:122-150`, `:564-575`).
- **R5.** `episodic_procedural_bridge.py:84` guards `store.list_all()`, which no procedure store defines; its fallback (`list_active` plus `get`) always runs. Same shape as F05, inert.
- **R6.** Trust history is the in-memory event log (500 events ship-wide, empty at boot), so a quiet agent's profile history is short or evicted. A persisted history is design work.
- **R8 (A1).** `docs/development/config-profiles.yaml`'s `census:` header had drifted before this change (445 / 225 / 136 written, 452 / 226 / 141 measured at the base): only `default_false` is pinned (`test_ad1185_*:859`), so the other figures go stale whenever a boolean is added. Pinning the whole block to the instrument (or generating it) is a separate change.
- **R7.** `tests/test_teaching_protocol.py:93` still sets the dead `_trust_score`; `tests/test_ad1259_one_source_of_truth.py:70` `_FakeTrustNetwork` lacks `get_history` but reaches neither caller. The procedure tests' `MagicMock` runtimes run the clamp at trust 1.0 (section 6): a future test that asserts rank-dependent dispatch must give its runtime `trust_network_at(...)`.
