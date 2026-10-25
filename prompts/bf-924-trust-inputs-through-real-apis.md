# BF-924: trust inputs are read through APIs that exist (#1654): the procedure-compilation clamp reads the agent's live trust, profile trust history and avatar trust delta come from `TrustNetwork.get_history`, `/grant list` names a target by certificate, and `CounselorConfig` is read or removed

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A1, after the oracle run)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A2, after review round 1 of M1 and M2)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A4, after review round 3 of M1 and M2: the round-three brake, continue)

**Status:** build-ready. One BF, two milestones, one PR, one gate; #1654 closes with it. **BF number:** BF-924 (#1654); this contract allocates nothing. **Tier:** M1 **HIGH** (the AD-535/536 trust clamp: it decides how much an agent may replay without the LLM, and its failure mode is fail-closed by design); M2 **STANDARD** (no safety property: every wired value defaults to the constant it replaces, F05 is Captain-only, F04's effect is the Captain's profile history and, in the backend avatar projection and the crew context, a pitch factor and a rule name, which the Captain's Self Image tab shows; the Captain's voice playback and VRM do not read it, A2 D13, A3 D19). Review the batch at HIGH because M1 is: use the Copilot `Diff Reviewer`. **Base:** written against `ba45c61f` (BF-923's branch head on `origin/main` `7808d182`); BF-923 merges first as a merge commit with this tree; the orchestrator re-verifies every SEARCH on the merge SHA, and a changed REPLACE returns to the Architect. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf924_compilation_trust.py` (M1: 18 functions, 26 cases; A2 corrects the original count, 5 functions and 6 cases, and adds 6 functions and 10 cases; A3 adds 7 functions and 10 cases).
- A3 updated pins (M1): `tests/test_graduated_compilation.py` (seven validator tests whose doubles invented `generate` now use a `BaseLLMClient`-specced double and assert the call reached `complete`; one new case), `tests/test_ad1326_dreaming_challenger.py` and `tests/test_ad1326_challenger_e2e.py` (comments on the Records setter). M2: `tests/test_bf924_trust_inputs.py`'s list helper requires the printed table.
- A4 (M1): 5 functions and 6 cases appended to `tests/test_bf924_compilation_trust.py` (the compound replay lifecycle through a real `IntentBus`, `AgentRegistry` and target agent, and a Level 3 NO through `handle_intent`); no other test file changes.
- New `tests/test_bf924_trust_inputs.py` (M2: 13 functions, 20 cases; A2 adds 2 functions and 5 cases).
- A2 updated pins (M1): `tests/test_graduated_compilation.py` (`test_promote_compilation_level` asserts the level `get` returns), `tests/test_ad1326_procedure_ledger.py` (a restore test built its premise through the column-only demote).
- Updated pins, M1: `tests/test_graduated_compilation.py` (factory and two inline sites set `_trust_score` by hand), `tests/test_level_5_dispatch.py` (factory). M2: `tests/test_ad722_avatar_telemetry.py` (docstring of the no-method double), `tests/test_ad1260_wellness_domain.py` (`_FakeTrust` gains `get_history`), `tests/test_ad622_clearance_grants.py` (`list_all` invented by a `MagicMock`), `tests/test_counselor_activation.py` (defaults of removed fields), `tests/test_ad1270e2h_emergence_models.py` (the pre-move dump of `CounselorConfig`), `tests/test_ad642_communication_benchmarks.py` (a hand-set `_config` nothing reads), `tests/test_counselor_therapeutic.py` (A1: its `__new__` builder sets `_counselor_config`), `tests/test_ad1270e1_config_facade.py` (A1: the field-count pin, 1880 to 1876).

**Amendment A1 (2026-10-25, after the oracle run on `8f9fd379`: 32 labels applied, the union of the focused lists 4 failed / 1,302 passed).** Every original pair stands; A1 changes only:
1. §7.15 also gives `_FakeTrust.all_scores` the real `crew_only` parameter (the seam test's `all_scores` failure); the seam test stays whole (decision A1-1, section 3).
2. New §7.21: `tests/test_counselor_therapeutic.py`'s `_make_counselor` (`object.__new__`) sets `_counselor_config`, as BF-921 set `_suppression_history` in the same shape of builder (decision A1-2). No production line changes.
3. New §7.22: `tests/test_ad1270e1_config_facade.py`'s `field_definitions` pin, 1880 to 1876, with its comment line.
4. §7.13 gains a second pair: the manifest's `census:` header, re-measured on this tree (decision A1-4).
5. Section 6's expected generated diff is corrected to the exact hunks the oracle produced; the tests-first list gains the field-count pin (19 cases); the collected counts are the oracle's.
6. D4 records the live count (posted on #1654): no active procedure is at Level 3 or above, so F02 restricts no stored procedure today.

**Amendment A2 (2026-10-25, after review round 1: M1 NOT READY on four P2, M2 NOT READY on one P2 and two P3; `logs/bf924r1/review-m1-r1.md`, `review-m2-r1.md`).** Every earlier pair stands except the helper body in §7.1 Pair 2. A2:
1. D11 (findings 3, 4): the helper reads the trust network inside its `try` and refuses a value outside [0, 1] (NaN, an infinity) with the same WARNING and 0.0.
2. D10 (finding 2, pre-existing): `ProcedureStore.promote_compilation_level` and `demote_compilation_level` write the level to the JSON snapshot `get` reads, in the same statement as the column (new §7.4a); `get` is unchanged. **E8:** promotions and demotions take effect for dispatch.
3. D9 (finding 1): the completion event is unchanged; §5a's "no evolution by itself" is corrected; **E9** discloses that an Ensign's Guided run enters AD-532e's reactive check as every stored Level 2 run does; a producer-to-consumer test pins it.
4. D12 (G1): `/grant list` degrades per row for a time the platform cannot show; `/grant issue` refuses such a duration (§7.8 Pairs 3 to 6).
5. D13 (G2): E6 no longer names the Captain's playback as a consumer. D14 (G3): `scripts/gen_config_reference.py` anchors to its own `src` (new §7.23).
6. Tests: 10 new M1 cases and 5 new M2 cases; two updated pins (§7.3 Pair 5, new §7.4b); section 6's census of the two inline compound tests is corrected; the M1 focused list gains four files. No generated file, hash or field-count pin changes.

**Amendment A3 (2026-10-25, after review round 2: M1 NOT READY on three P2 with ordinary reach, a whole review; M2 NOT READY on two P3 repair regressions, a delta review; `logs/bf924r2/review-bf924-m1-r2.md`, `review-bf924-m2-r2.md`).** Every earlier pair stands except §7.3 Pair 1's REPLACE (two imports added). A3:
1. D15 (M1 finding 1): both Level 3 validators call the client's `complete(LLMRequest)` and read `LLMResponse.content`; they called `generate`, which no client has, and passed every replay unvalidated. A failed call still passes by default (AD-535), now with a WARNING in both; an error reply counts as a failed call (E10). The doubles that invented `generate` are pinned to `BaseLLMClient`.
2. D16 (found here, on the path D10 opened): AD-536's promotion request is posted as the agent (`self.id`, its callsign), not as `_agent_id` / `_callsign`, which no agent has; E11 discloses the request; its approver routing is R17.
3. D17 (M1 finding 2, pre-existing): AD-532b's 72 h window is claimed in the step that checks it, before the first `await`, on the reactive, proactive and both dream-time paths (new §7.4c), so E9's bound holds under overlapping completions (E12).
4. D18 (M1 finding 3, pre-existing): `DreamingEngine` creates its fallback queue and observed-thread set in its constructor, so they no longer depend on Ship's Records, and `set_records_store` resets neither (E13).
5. D19 (M2): E6's Captain-visible effect on the Self Image tab is disclosed and R11 narrowed to the voice playback and VRM (finding 1); the positive grant-list tests require the printed table (finding 2, R24); finding 3 is R14.
6. Tests: 11 new M1 cases (10 in `tests/test_bf924_compilation_trust.py`, 1 in `tests/test_graduated_compilation.py`), seven strengthened validator tests, the D9 test's comment and two AD-1326 test comments corrected (§7.4d, §7.4e); no new M2 case. Mutation rows R24 to R36; the M1 focused list gains seven files. No generated file, hash, field-count pin, event payload or persisted schema changes.

**Amendment A4 (2026-10-25, after review round 3: M1 NOT READY on two P2 with ordinary reach and one P3 text, a whole review; M2 no defect, a delta review; `logs/bf924r3/review-bf924-m1-r3.md`, `review-bf924-m2-r3.md`; the round-three brake: continue).** Every earlier pair stands; A4 only adds pairs (new §7.4f; §7.2's imports and five appended functions). A4:
1. D20 (M1 finding 1, a regression in effect): a compound step the Level 3 validator rejects is a failed replay: no `act()` on the cached decision; it takes the cached-failure path (`record_fallback`, AD-535's demotion, AD-534b's recovery, an `execution_failure` event naming the step) (E14).
2. D21 (M1 finding 2, pre-existing): AD-535's promotion and demotion step moves unchanged into `_record_compilation_outcome`, which a dispatched compound replay now calls once before its early return, so compound procedures graduate (E15).
3. D22 (found by A4's sweep, pre-existing, reachable since D15): a Level 3 overall NO demotes the procedure to Level 2 and resets its count, as AD-535 specifies for any failure; the LLM still serves the intent (E16).
4. D23 (M1 finding 3, text): the configured chiefs exist; R17's defect is that the approver's name is used as its agent id. D16, E11, section 12 and R17 are corrected.
5. The result paths of the Level 3 to 5 replay and validation chain are enumerated in section 3 (16 rows), each with what the lifecycle did and does; four rows (three defects) were wrong, all at the handoff from a replay result to the accounting.
6. Tests: 5 functions and 6 cases appended to the new M1 file. Mutation rows R37 to R42. No generated file, hash, field-count pin, event payload shape or persisted schema changes; M2 is unchanged.

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

- **M1.** One helper, `CognitiveAgent._compilation_trust_score()`, reads `self._runtime.trust_network.get_score(self.id)` as the rank read does (`:3351`); both sites use it. A failed or impossible read logs a WARNING and returns 0.0, which takes the Ensign cap (Level 2). No hold (D3). Two test factories that hand-set `_trust_score` now give their runtime a real `TrustNetwork` at that score. A2: a value that is not a score in [0, 1] is a failed read too (D11), and `promote_compilation_level` / `demote_compilation_level` write the level to the snapshot `get` reads as well as to the column (D10).
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
   - **(c), A2 (D10), read-only, before the merge:** in `procedures/procedures.db`, `SELECT compilation_level, json_extract(content_snapshot, '$.compilation_level') AS snapshot_level, COUNT(*) FROM procedure_records WHERE is_active = 1 AND compilation_level IS NOT json_extract(content_snapshot, '$.compilation_level') GROUP BY 1, 2`: the active rows whose column and snapshot already disagree (dispatch reads the snapshot; the counts above read the column). Post on #1654. It is R10's evidence and does not block the merge: D10 repairs no existing row.

**D5, the F05 repair.** Ranked: (1, chosen) one helper, `_grant_target_callsign`, resolving the stored id by certificate (`get_by_uuid`, else `get_by_slot`: `_grant_issue` stores the sovereign id, or the slot id when no identity registry is bound) and naming it with `callsign_registry.get_callsign(cert.agent_type)`, the live callsign, falling back to the birth callsign; the id prefix as before when nothing resolves; (2) add `CallsignRegistry.list_all()`: a new API for one caller that would still compare slot ids with a sovereign id and never match; (3) iterate `all_callsigns()` and `resolve()` each: per-grant O(n) and the same id-form mismatch.

**D6, the F04 repair.** Ranked: (1, chosen) add `TrustNetwork.get_history(agent_id, limit=20) -> list[float]`, the `new_score` of `get_events_for_agent(agent_id, n=limit)`, oldest first, `[]` for `limit <= 0` (`filtered[-0:]` would return all): one owner of the mapping; the callers' contract (`limit`, a list of floats the UI validates in [0, 1], `useProfileResource.ts:54`) holds unchanged; the three avatar doubles already have this signature; the 13 `runtime.trust_network.get_history.return_value = []` fixtures stay meaningful. Both `hasattr` guards are removed: they are what hid the defect; telemetry keeps its `try` (its never-raise contract, `telemetry.py:7-11`). (2) Call `get_events_for_agent` in both callers: the mapping three times (`standing_interests.py:701` already does it), and the doubles and fixtures would pin a dead name. (3) A persisted history: scope (R6).
**Doubles audit (5 files named by the issue, plus one found):** the three avatar `_FakeTrustNetwork`s match the new method; `test_bf711_*:110 _Store.get_history(agent_id, test_name, limit)` and `test_ad566c_*:54 MockQualificationStore.get_history` double the qualification store (`qualification.py:255`) and are out of scope; `test_ad1260_*:45 _FakeTrust` reaches the route and gains the method, and its `all_scores` gains `crew_only` (A1-1); `test_ad1259_*:70 _FakeTrustNetwork` never reaches either caller (its two `agent_profile` calls, `:238`, `:348`, use runtimes without a trust network) and is unchanged. A seam test pins the four doubles that stand for `TrustNetwork` on these paths: every public method each defines exists on `TrustNetwork` with the same parameter names and kinds (defaults are not compared: callers pass them). **Effect:** no hold (A2, D13; A3, D19: the Captain's profile history plus, in the backend avatar projection, the Captain's Self Image tab and the crew context, a ±3 % voice pitch and a rule name; the Captain's voice playback and VRM do not read it; section 5b).

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

**D9 (A2), review round 1 finding 1: an Ensign's Guided run and AD-532e's reactive trigger.** `TASK_EXECUTION_COMPLETE` (`cognitive_agent.py:7852-7859` on the candidate) reports `used_procedure` from `cached`, and `dreaming.py:2121` skips the reactive check only when it is true. A Guided decision is not cached because the LLM ran (AD-535 Part 8, `prompts/archive/ad-535-graduated-compilation.md:480`), and AD-532e defines the event as a task "via LLM path" with `used_procedure` "True if procedural replay was used (no reactive needed)" (`events.py:1054`, `:1060`; `prompts/archive/ad-532e-reactive-proactive-triggers.md:90-96`, `:138`). Every Guided run therefore already enters the check, and every stored Level 2 run does today (Level 2 is the highest level of any active procedure on the vessel, D4). The clamp turns an Ensign's run of a stored Level 3 or 4 procedure into a Guided run; the reviewer measured exactly that (equal counters, `used_procedure` False at 0.3 and True at 0.5, one reactive attempt and one confirmation call at 0.3). Ranked: (1, chosen) keep the field and its rule, disclose E9, correct §5a, and pin with a producer-to-consumer test that the clamped run reaches the check as a stored Level 2 run does and a replay does not (§7.2); (2) make `used_procedure` true for `guided_by_procedure` too: it changes today's behaviour for every Level 2 run, removes the reactive trigger from every live procedure, changes a payload read outside its module, and decides an AD-532e question outside this issue (R9); (3) a new payload field with a consumer decision: new contract surface with no consumer need; (4) set `used_procedure` only when the clamp lowered the level (the base's event in every case): puts a trust-dependent meaning into a field that means "a replay was used", through a new decision key. Cost bound (E9): only a successful run; at most once per agent per 60 s (`REACTIVE_COOLDOWN_SECONDS`, `config.py:254`); only for a matched procedure with at least 5 selections and an unhealthy diagnosis (`dreaming.py:2147-2155`); at most one attempt per procedure per 72 h (`EVOLUTION_COOLDOWN_SECONDS`, `config.py:251`), shared with dream-time evolution through `_addressed_degradations` (`:2013-2015`; A3, D17: claimed in the step that checks it, before the first `await`, on every path that reads it, so overlapping deliveries share it too); each attempt one LLM confirmation call (`:2018-2030`), and if confirmed the evolution calls that the dream cycle's Step 7b (`_evolve_degraded_procedures`, `:1863-1979`, called at `:694`) makes for the same diagnosis without confirmation. No control is weakened.

**D10 (A2), review round 1 finding 2 (pre-existing): promotion and demotion reach `get`.** `promote_compilation_level` and `demote_compilation_level` (`procedure_store.py:1105-1133`) update only the `compilation_level` column; `get` (`:814-832`) rebuilds the procedure from `content_snapshot`. So the dispatch (`cognitive_agent.py:1837`, `:1855`, `:1861`), the next promotion step (`:7781`, `:7787`), the demotion check (`:7804-7805`), both teaching gates (`commands_procedure.py:412`, `routers/procedures.py:167`), an evolved procedure's inherited level (`procedures.py:842`, `:925-940`, `:1357`), the diagnostic context (`diagnostic_context.py:329`) and the index entry `sync_routing_index` rewrites from `get` (`procedure_store.py:785-791`) never saw a promotion or a demotion. Measured through the real `handle_intent` on a real store: promoted to index 5, loaded 4, teaching refused; and five failures at trust 0.5 left the index at 2 while every run replayed at Level 4 with no LLM call (`logs/bf924r1/orchestrator-rerun-lifecycle.txt:24`, `:41`). AD-535 specified the in-memory update (`prompts/archive/ad-535-graduated-compilation.md:99`); decay (`:1623-1639`), `deactivate` (`:1271-1287`), archive and restore write the snapshot with the column. AD-1326 D14 rejected merging the column into `get` (40 callers) and named this a legacy defect outside its issue (`prompts/ad-1326-procedure-challenger-champion.md:235`); it was never filed (section 12). Why here: M1's E2, E3 and §5a's demotion row are claims about promotion, and without this the Level 5 that M1 makes reachable is a column no consumer reads. Ranked: (1, chosen) both methods write the snapshot's level in the same UPDATE (`json_set`, inside BF-891's `_index_write`, so a failure rolls both back; no read-modify-write, no swallowed failure, no re-save through `INSERT OR REPLACE`, counters untouched), `get` unchanged (D14 stands); (2) `get` takes the level from the column: changes what about 40 callers see for every row ever promoted, demoted or migrated, and leaves the snapshot and the index rebuild (`_rebuild_chroma_from_sqlite`, from the snapshot) stale; (3) a separate issue: the defect is reached through M1's own Level 5 and the fix is two statements in the methods M1's step calls; (4) register only: leaves E3 false. The index's metadata level is not written: `find_matching` uses it only as the `min_compilation_level` filter (`:945-948`) and returns SQLite's columns (`:974-979`), and production promotes from at least 2 and demotes to 2, so the filter's answer cannot change. Rows that already differ and `_migrate_qualifying_procedures` (`:1208`, column only) are R10. **E8.** Within the envelope: it restores AD-535's design, makes the demotion valve effective and rewrites no data at merge.

**D11 (A2), findings 3 and 4: the helper's guard.** `float(nan)` does not raise and fails both comparisons, so NaN took the Level 4 cap with no WARNING; `+inf` passed `>= TRUST_COMMANDER` and promoted an approved procedure to Level 5; the `trust_network` attribute was read before the `try`, so a raising attribute failed `decide`. Chosen: read `self._runtime.trust_network.get_score(self.id)` inside the `try` and refuse a value with `not 0.0 <= score <= 1.0` (true for NaN) through the same WARNING and 0.0. Out of range is refused, not clamped: `get_score` is `alpha / (alpha + beta)` (`trust.py:97-99`, `:1017-1022`), in [0, 1] for every record the network writes; a value outside comes from a corrupt record (`create_with_prior` does not validate, `:358-370`) or a double, and clamping 1.5 to 1.0 would give it the Commander's Level 5, against D2. No range check at all leaves 2.0 unlocking Level 5. `float(MagicMock())` is 1.0, in range, so section 6's masked tests are unaffected. The WARNING text is unchanged (E4, R5); its traceback names the value.

**D12 (A2), review round 1 M2 G1: `/grant list` and a time the platform cannot show.** `datetime.fromtimestamp` raises OverflowError for an infinity and OSError (Windows) or ValueError for a finite time outside the platform's range; `_grant_list` formatted every row unguarded, so one such row made the command raise and the shell print an error instead of the table (`experience/shell.py:326`, `:343`); `_grant_issue` admitted `inf` and any huge duration, and `nan` (`nan > 0` is False) became a grant until revoked. Chosen: one helper, `_grant_time`, for both cells; a time it cannot show reads "out of range" in its own row; the Status keeps reading the raw value (`inf` is Active, as `get_active_grants_sync`, `clearance_grants.py:95-103`, and the store's `expires_at > ?`, `:88`, `:175`, treat it); and `/grant issue` refuses a non-finite duration or one whose expiry `_grant_time` cannot show ("Invalid duration", nothing stored). No fixed maximum in hours: the representable range is the platform's, and one function decides both admission and display, so what is admitted can always be listed on that host. SQLite stores `inf` as REAL and returns it; a bound NaN is stored as NULL. The grant check and `list_grants(active_only)` compare numbers and are unchanged; `_grant_issue` is the only writer of this store's expiry (section 12). Inside M2: it is F05's acceptance and section 14 property 6. The admission check strengthens an access control.

**D13 (A2; corrected by A3, D19), review round 1 M2 G2: E6's consumers.** The Captain's voice playback and VRM are not among them: `deriveAgentSignals` (`ui/src/components/profile/avatarSignals.ts:44-46`) hardcodes `trust_delta = 0`, and that is what `voiceModulation.ts:109-111` and `CrewVRM.tsx:159-162` read. The Captain's Self Image tab is one (A3: A2 counted `SelfImageTab.tsx:455` among the readers of that zero; it is not one): it fetches the backend avatar telemetry (`SelfImageTab.tsx:100`, the stream `:138`) and renders its `current_signals.trust_delta` (`:277` to `:455`) and its `applied_modulation` pitch factor and fired rules (`:278` to `:484`, `:488`). The backend projection (`telemetry.py:720-738`, `apply_voice_modulation` `:452-457`), the Self Image tab and the crew context (interoception, on in `config/system.yaml:1631`) carry the new pitch factor and rule name. E6 is corrected in the header, D6, §5b, the PR text and both tracker entries; wiring the voice playback and VRM is UI work (R11), not claimed.

**D14 (A2), review round 1 M2 G3: the generator's import.** `scripts/gen_config_reference.py:177` imports `probos.config` with no anchor, so in a worktree with no `PYTHONPATH` the venv's editable install supplies another checkout's models; its siblings insert their own `src` (`check_config_profiles.py:60-62`, `check_config_facade.py`). Chosen: the same lines in the generator (§7.23), and section 6's commands are run with `PYTHONPATH` pinned. Under the gate's environment the path is already first, so the output is byte-identical and `tests/test_config_reference_current.py` (a subprocess with the inherited environment) is unaffected. Of the six scripts that import `probos`, four already anchor; `gen_capability_truth.py` is not run by this change (R12).

**D15 (A3), review round 2 M1 finding 1: Level 3 validation reaches the client.** `_validate_replay_postconditions` and `_validate_step_postcondition` (`cognitive_agent.py:2592`, `:2632` on the candidate) called `llm_client.generate(prompt, max_tokens=...)`. Every client implements `complete(LLMRequest, *, priority) -> LLMResponse` (`BaseLLMClient`, `llm_client.py:243-247`; `OpenAICompatibleClient` `:265`, `:1458`; `MockLLMClient` `:2684`, `:2907`), and no LLM client defines `generate` (section 12). The `AttributeError` was caught as "passing by default", so every Level 3 replay reported `validated=True` with no request (reviewer: `complete_calls 0` once the ladder reached Level 3). The phantom call is in AD-535's own text (`prompts/archive/ad-535-graduated-compilation.md:351`); D10 made it ordinary execution (E8). Ranked: (1, chosen) both validators build `LLMRequest(prompt=..., tier=self._resolve_tier(), max_tokens=100)` (50 for a step) and call `complete(request, priority=Priority.NORMAL)`, reading `LLMResponse.content`, as the agent's own helper calls do (`:7150-7157`, `:7377-7384`, `:12680-12686`) and AD-532e's confirmation gate does (`procedures.py:232-241`); `agent_id` and `work_item_id` stay None, as in `decide`'s own requests (`:4485-4508`; AD-1324's armed-only fields); the prompts, the timeout and the token limits are unchanged; (2) hold Level 3 until a validator is real (D10 caps the ladder at 2, or Level 3 is dispatched Guided): a dispatch rule AD-535 does not have, and the ladder D10 restores would stop at its first step; (3) a separate issue: the ladder BF-924 makes reachable would treat an unvalidated replay as validated from the merge. **Failure semantics.** Ranked: (1, chosen) keep AD-535's fail-open for a failed call (`prompts/archive/ad-535-graduated-compilation.md:363`, acceptance `:666`): a call that raises, times out or returns an error reply (the client returns `LLMResponse(error=...)` rather than raising, `llm_client.py:1532-1535`, `:2092-2098`) passes by default, with a WARNING in both validators (the step validator passed silently, which is how the defect stayed hidden); an answer that is not YES fails validation and the intent goes to the LLM (AD-535's NO path, a `validation_failure` near-miss; A4: the overall validator's NO also demotes the procedure, D22, and a compound step's NO is a failed replay, D20). Fail-open weakens no control: after three more successes Level 4 replays the same procedure with no validation at all, and the decision's `validated` key has no reader (section 12); (2) fall back to the LLM on a failed call: a second call to the provider that just failed, a `validation_failure` near-miss (and evolution evidence) made of infrastructure noise, and a change to AD-535's acceptance. **Doubles.** The `AsyncMock().generate` doubles exist only in `test_graduated_compilation.py` (section 12); they become `MagicMock(spec=BaseLLMClient)` with `complete`, and each asserts that the request reached `complete` (§7.3 Pairs 6 to 8); the end-to-end cases use a real `OpenAICompatibleClient` with only `complete` replaced (§7.2). A suite-wide seam test over every LLM-client double, as §7.20's for `TrustNetwork`, is R20. **Enumeration:** every other method called on the Level 3 to 5 dispatch and post-execution path exists on its object (19 definitions, section 12); two attribute reads do not (D16). **E10.**

**D16 (A3), found here on the path D10 opened: the promotion request's author.** `_announce_promotion_request` (`cognitive_agent.py:2757-2838`) posts as `getattr(self, "_agent_id", agent_type)` and `getattr(self, "_callsign", agent_type)` (`:2786-2787`); no agent has either attribute (section 12), so the thread and the DM channel named the agent type. Before D10 no run reached it: the promotion step read the snapshot's Level 2, so `next_level >= PROMOTION_MIN_COMPILATION_LEVEL` (4, `config.py:275`) never held. With D10 a Lieutenant's procedure reaches Level 4 after six successes, and one with at least 10 completions at an effective rate of at least 0.7 (`config.py:276-277`) is marked `pending` and announced (E11). No test reaches either method (section 12). Ranked: (1, chosen) `self.id` and `self.callsign or agent_type` (BaseAgent's own fields, `substrate/agent.py:39`), and disclose the request (E11); (2) register only: from the merge, the Ward Room shows promotion requests authored by an agent type; (3) also route the department-chief approver: `_DEPARTMENT_CHIEFS` (`:2708-2715`) maps a department to a lowercase name, which `_announce_promotion_request` passes to `get_or_create_dm_channel` as the approver's agent id, so the chief's registered agent is not a member of the DM; the chiefs exist (`config/ontology/organization.yaml:393`, `:405`, `:421`) and the ontology resolves them (`get_post_for_agent(agent_type).reports_to`, then `get_agents_for_post`, `ontology/service.py:165`, `:177`): resolver work in AD-536's routing, R17 (A4, D23, corrects A3's "names chiefs no agent is" and "no chief lookup"). Within the envelope: AD-536's designed request; approval stays with `procedure approve`.

**D17 (A3), review round 2 M1 finding 2 (pre-existing): AD-532b's 72 h window is claimed where it is checked.** `_attempt_procedure_evolution` checks `_addressed_degradations` (`dreaming.py:2013-2015`) and records it after the confirmation `await` (`:2025-2030`); Step 7b checks at `:1885-1887` and records after the parent load and the recall (`:1911`, `:1919`, `:1936`); Step 7d checks at `:2220-2223` and records after them (`:2265`, `:2280`). The local event dispatch runs each listener as its own task (`runtime.py:1987`), so two agents' completions, each past its own 60 s cooldown, both passed the check: two confirmation calls (review round 2; the same on the base). E9 states the 72 h bound, so BF-924 enforces it. Ranked: (1, chosen) one synchronous helper, `_claim_evolution_attempt(proc_id, now)`, checks the window and writes the claim with no `await` between, called by Step 7b and by `_attempt_procedure_evolution` (the reactive trigger and the proactive scan); Step 7d keeps its read-only check, so a `negative_veto` inside the window is still counted as skipped and flags nothing, and claims with the same write right after it, with no `await` between; the state stays `_addressed_degradations` (per engine, in memory, as today); the proactive scan's pre-check (`:2471-2474`) stays read-only, since `_attempt_procedure_evolution` claims. Every exit that recorded before still records (a negative or failed confirmation `:2029`, no evidence `:2047`, a refused challenger plan `:2055`, an evolution `:2073`, and Step 7b's and 7d's equivalents); an attempt that raises keeps its claim (before: unrecorded and retried at the next trigger), and Step 7b's missing-parent exit keeps it (E12). AD-532e's and AD-534's existing tests: 17 reads and writes of `_addressed_degradations` in 7 test files, none asserting an entry is absent (section 12); their presence and `>= before` assertions hold, since the claim writes the same `now` the early exits write. (2) a per-procedure `asyncio.Lock` held across the confirmation: correct, but holds a lock across an LLM call and adds state the window already expresses; (3) narrow E9 to serial deliveries: leaves an ordinary-reach finding unfixed; (4) a separate issue: E9 is BF-924's own disclosure, and the fix is in the methods E9 names.

**D18 (A3), review round 2 M1 finding 3 (pre-existing): the fallback queue does not need Ship's Records.** `DreamingEngine.__init__` (`dreaming.py:121-168`) did not create `_fallback_learning_queue` or `_observed_threads`; `set_records_store` did (`:182-187`), and startup calls it only when a records store exists (`startup/finalize.py:5417-5418`). With `records.enabled: false` the ProcedureStore still starts, and a real fallback (reviewer: the replay failed, the LLM recovered, the procedure was demoted) was dropped by the handler with `AttributeError`, logged at DEBUG; Step 7d raised on the missing queue and Step 7e on the missing thread set. Why here: E8 makes replays, and so replay failures and their fallback events, reachable. Ranked: (1, chosen) the constructor creates both, and the setter binds the store and resets nothing (its docstring's "no-op if already set" now holds for the whole method); the four `__new__` factories that set the fields themselves are unchanged, and the two AD-1326 factories that call the setter keep the call, with their comments corrected (§7.4d, §7.4e); (2) startup always calls the setter: the queue stays coupled to an unrelated dependency; (3) a separate issue: two lines in the file D17 already changes. **E13.**

**D19 (A3), review round 2 M2: the Self Image tab, the list test, a zero expiry.** Finding 1 (P3, a repair regression in the disclosure): D13 counted the Self Image tab among the readers of `deriveAgentSignals`' zero, but it renders the backend snapshot (D13 as corrected), so E6 has a Captain-visible effect: the tab shows the real delta, the modulated pitch and the rule name. No code changes; the text is corrected wherever it appears (the header, D6, D13, §5b, §4's PR text, both tracker entries, §9, §12, §13, property 14, R11). Finding 2 (P3, a repair regression in a test): A2's `[-1]` split let the positive list test read the issue command's own confirmation as the table; the helper now returns the whole output, the tests that expect a table take it through `_listed_table`, which fails when none printed, and the refused-issue tests read the whole output as before (R24). Ranked for finding 2: (1, chosen) separate the output from the table and assert the table where one is expected; (2) restore `[1]` and catch `IndexError` in the refused cases: an exception as control flow in a test helper; (3) assert the title inline in each positive test: the same check three times. Finding 3 (P3, injected only, not a regression): a stored `expires_at == 0` reads as permanent and Active in `/grant list` while both active-grant readers exclude it; only a hand-written row stores 0 (`/grant issue ... 0` stores None): R14.

**D20 (A4), review round 3 M1 finding 1 (P2, ordinary, a regression in effect): a rejected compound step is a failed replay.** `_execute_compound_replay` returns `compound_aborted` when a Level 3 step's validator answers NO (`cognitive_agent.py:2099-2109` on the candidate); the lifecycle reads only `compound_dispatched` (`:7624`), so the abort took the degradation branch (`:7659-7661`), ran `act()` on the unchanged cached decision (`:7667`), reported success, recorded a completion and counted it toward promotion: three rejections reached Level 4, where validation stops (reviewer: levels `2, 2, 3, 3, 3, 4`, no recovery call). D15 made the NO reachable. AD-535 aborts the compound replay on a step NO (`prompts/archive/ad-535-graduated-compilation.md:383`) and demotes on any failure (`:37`, `:53`). Ranked: (1, chosen) the abort is a failed cached replay: the lifecycle skips `act()` and takes the existing cached-failure path with a failure result naming the step: `record_fallback` (`:7772`), AD-535's demotion (`:7819-7834`), AD-534b's service recovery (`:7836-7862`) and, when recovered, the `execution_failure` learning event, whose `rejection_reason` names the step (`:7854-7859`). Other agents already ran the earlier steps, which is why it is an execution failure and not a near-miss (AD-534b's split, `dreaming.py:2317-2319`). The abort result now says `success: False` and carries `failed_step`; (2) treat it as a near-miss on the LLM path, as a Level 3 overall NO is: the compound replay runs in the lifecycle after `decide` returned, so there is no LLM path to fall back to without a second decision site, and steps were executed, which a near-miss denies; (3) set the result's `success` to False only: the caller never read it (reviewer, finding 1). **E14.**

**D21 (A4), review round 3 M1 finding 2 (P2, ordinary, pre-existing, exposed by D10 and D15): a dispatched compound replay reaches AD-535's accounting once.** The compound branch records the completion, emits its event and returns (`:7624-7658`) before the post-execution promotion step (`:7788-7834`), so no compound procedure ever counted a success: at Level 3 it stayed there, paying one 100-token call and one 50-token call per validated step every run (reviewer: six Level 3 completions, count 0), and at Level 4 it never reached Level 5. Ranked: (1, chosen) move the post-execution step unchanged into `_record_compilation_outcome(procedure_id, success)` and call it from its old site, from the compound branch after its completion write (once: the branch returns) and from D22's NO path; the compound branch's completion write, event and result are unchanged (pinned by `test_multi_agent_replay_dispatch.py:799-856`); (2) let the compound success fall through the shared post-execution path: it changes the compound event's payload (`compound_dispatched`, `steps_dispatched`, pinned at `:855`), writes the completion twice unless the branch's write goes, and adds episode, working-memory and Ward Room effects to a path that has none (R21); (3) a second copy of the step in the branch: two copies of the ladder. A step whose dispatch failed is replaced by its text and counts, as AD-534c designed and as the completion already counted it (`:2084-2097`, R23); at Level 3 the step validator judges that text. **E15.**

**D22 (A4), found by the sweep (pre-existing, reachable since D15): a Level 3 NO is a failure for the ladder.** The overall validator's NO returns `None` (`:2510-2522`), so the intent takes the LLM path with no `procedure_id` and the post-execution step never sees the procedure: the count was neither reset nor the level demoted, and three YES answers that were not consecutive still promoted the procedure. AD-535 resets the count on any failure and demotes to Level 2 (`ad-535-graduated-compilation.md:37`, `:53`) and specified the NO as a fall-through through service recovery (`:263`). Ranked: (1, chosen) `_build_validated_decision` calls `_record_compilation_outcome(procedure.id, False)` before returning `None`: the stored Level 3 procedure (an effective Level 3 is a stored Level 3: the caps are 2, 4 and 5) is demoted to Level 2 with its count reset; the LLM still serves the intent; the `validation_failure` near-miss, its learning event and `used_procedure: False` (D9) are unchanged; a failed validation call still passes by default (D15) and touches nothing; (2) reset the count and keep Level 3: a procedure the validator keeps rejecting pays a validation call and an LLM decision every run, against AD-535's rule; (3) register it: the ladder D10 activates would promote on non-consecutive successes. **E16.**

**D23 (A4), review round 3 M1 finding 3 (P3, text): R17's premise.** D16 option (3), E11, section 12 and R17 said the configured chiefs do not exist (a case-sensitive search for `laforge` in `config/`). They exist: `config/ontology/organization.yaml:393`, `:405`, `:421` assign LaForge, Bones and Worf, and the ontology resolves a chief through `get_post_for_agent(agent_type).reports_to` and `get_agents_for_post(post_id)` (`ontology/service.py:165`, `:177`). The defect is the addressing: `_DEPARTMENT_CHIEFS` (`cognitive_agent.py:2723-2730` on the candidate) holds lowercase names, and `_announce_promotion_request` passes that name to `get_or_create_dm_channel` as the approver's agent id (`:2838-2841`), so the DM's member is the literal `laforge`, which the chief's registered agent is not (reviewer: real configuration, ontology, registry and Ward Room). Text only; the routing stays R17 (corrected).

**The result paths of the Level 3 to 5 replay and validation chain (A4).** Lines are the candidate's (`cb201c20`). "Accounting" is the post-execution step, `_record_compilation_outcome` after A4.

| # | Path | Where | Lifecycle on the candidate | After A4 |
|---|---|---|---|---|
| 1 | Level 2 Guided (stored 2, or clamped), success | `:1869-1871`, `:2449-2472`; `:7777-7786`; `:7788-7818` | `act()` on the LLM decision; completion; count; promotion to 3 within the cap; `used_procedure: False` (D9) | unchanged |
| 2 | Level 2 Guided, failure | `:7783-7784`; `:7819-7834` | fallback; demotion of a stored level above 2 (a clamped run), else reset; no recovery (not cached) | unchanged |
| 3 | Level 3, overall NO | `:2510-2522` | `None`; `validation_failure` near-miss; LLM decision; no procedure accounting; count untouched | **D22**: demoted to 2 with the count reset, once; the rest unchanged |
| 4 | Level 3, overall call raised, timed out or returned an error reply | `:2599-2610` | passes by default with a WARNING: row 5 or 7 to 11 | unchanged |
| 5 | Level 3 single-step, overall YES, `act()` succeeds | `:2524-2541`; `:7667`; `:7764-7818` | completion; count; promotion to 4 | unchanged |
| 6 | Level 3, 4 or 5 cached replay whose `act()` fails (an override, or `action: error`) | `:6599-6600`; `:7769-7772`; `:7819-7834`; `:7836-7862` | fallback; demotion; recovery; `execution_failure` event when recovered; `used_procedure: True` | unchanged |
| 7 | Level 3 compound, degraded (no bus or registry `:2027-2029`; a role unresolved `:2042-2056`) | `:7659-7661` | text through `act()`: row 5's accounting; an unresolved role also emits `compound_agent_unavailable` | unchanged (AD-534c's single-agent text replay, validated by the overall check as row 5 is) |
| 8 | Level 3 compound, a step NO | `:2099-2109`; `:7659-7667` | `compound_aborted` ignored; `act()` on the cached decision; success; completion; count; promotion (Level 4 after three) | **D20**: row 6's path with no `act()` on the replay; the reason names the step |
| 9 | Level 3 compound, a step's dispatch failed or raised | `:2082-2097` | the step text is substituted and validated: row 8 or rows 10 and 11 | unchanged |
| 10 | Level 3 compound, a step validation call failed | `:2643-2652` | passes by default with a WARNING; the replay continues | unchanged |
| 11 | Level 3 compound, every step accepted | `:2111-2117`; `:7624-7658` | completion; compound event; return before the count: never promoted, validation calls every run | **D21**: accounting once, before the return |
| 12 | Level 4 or 5 single-step, success | `:1877-1912`; `:7764-7818` | completion; count; Level 5 for approved and Commander; AD-536 request on reaching 4 | unchanged |
| 13 | Level 4 or 5 compound, dispatched (failed steps substituted, AD-534c) | `:1896-1910`; `:7624-7658` | completion; return before the count: never reaches 5 | **D21**: accounting once |
| 14 | Level 4 or 5 compound, degraded | `:7659-7661` | row 12 | unchanged |
| 15 | Level 4 or above, formatting raised | `:1914-1928` | `format_exception` near-miss; LLM decision; no accounting | unchanged (a near-miss: no replay was formed) |
| 16 | A raise in the accounting | `:7817-7818`, `:7833-7834` | swallowed (metrics never block the intent) | unchanged (the same `except` in the helper) |

No row calls the accounting twice in one intent: row 11 and row 13 return after their call; row 3 hands the intent to an LLM decision that carries no `procedure_id`; every other row reaches only the shared site.

## 4. Interaction with the queue

- **BF-923 (#1652)** is this base. Its Counselor changes (sections 3, 5(c), 7.8 of `prompts/bf-923-episodic-recall-callers-and-counselor-assessment-inputs.md`) are in this tree; this contract's `counselor.py` pairs anchor on the import block, `__init__`, `_run_wellness_sweep`'s head and `_on_trust_update`'s threshold, none of which BF-923 changed. No pair touches `_gather_agent_metrics`, `_record_trust_observation`, `CognitiveProfile`, `behavioral_*`, `orientation.py`, `proactive.py`, `runtime.py`, `startup/finalize.py` or `ward_room/channels.py`.
- **#1626 M6+M7** edits `ui/` only. No pair here is in `ui/`; the UI readers of `trustHistory` and `trust_delta` are read, not changed.
- **Tracker anchors:** `PROGRESS.md`'s title line (once) and `DECISIONS.md`'s heading `### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)` (line 739, once).
- **PR text, BF-924's part:** "BF-924 (#1654). Trust inputs were read through APIs that don't exist. The AD-535/536 procedure-compilation clamp read an attribute nothing sets, so every agent counted as a Lieutenant; it now reads the agent's live trust (`get_score`, as Rank does): Ensigns are held to Guided (Level 2), a Commander's approved procedure can reach Level 5, and an unreadable trust (a failed read, or a value that is not a score in [0, 1]) is held to Level 2 with a WARNING. Promotion and demotion now write the level `ProcedureStore.get` reads, so they take effect: they had moved only an index column, and dispatch, the next promotion step and the teaching gate never saw them. With the ladder working, Level 3 validation now calls the LLM client's real interface: it called a method no client has, so every Level 3 replay passed unvalidated (a failed call still passes by default, now with a WARNING). A Lieutenant's procedure that reaches Level 4 now requests institutional promotion, posted as the agent. Overlapping completions make at most one evolution attempt per procedure per 72 h, and fallback evidence reaches the dream cycle when Ship's Records is disabled. Compound procedures now graduate: a dispatched compound replay counts toward promotion; a compound step the Level 3 validator rejects is a failed replay that the LLM recovers, with the procedure demoted to Guided; and a Level 3 NO demotes the procedure too, as AD-535 specifies. `TrustNetwork.get_history` now exists, so the Captain's profile shows trust history and the avatar telemetry's trust delta is real: the Captain's Self Image tab shows it with the modulated pitch and rule (the HXI's own voice playback and VRM do not read it yet). `/grant list` no longer raises, names a grant's target by its live callsign and shows every row even when one time cannot be shown as a date; `/grant issue` refuses a duration that is not finite or whose expiry cannot be shown. The Counselor reads `trust_delta_threshold` and `sweep_max_agents` from its config (defaults unchanged); the four `CounselorConfig` fields nothing read are removed."

## 5. Consumers of every value this changes

**(a) F02: the clamp's trust value and every dispatch that follows it.** States of the read: *measured* (a float), *errored* (`get_score`, the runtime or its `trust_network` attribute raised), *invalid* (A2, D11: not a score in [0, 1]: NaN, an infinity, a corrupt record) and *absent* (no runtime or trust network) → 0.0 with a WARNING; *timed out* does not occur (an in-memory dict read, `trust.py:1017-1022`); *skipped* does not occur (read whenever a procedure is loaded).

| Reader | Effect of a real score |
|---|---|
| `_max_compilation_level_for_trust` (`:1853`) | trust < 0.5 → 2; else 4 (unchanged function) |
| `_max_compilation_level_for_promoted` (`:1858`, only for a stored Level ≥ 5) | 5 only for `approved` and trust ≥ 0.7 |
| dispatch `:1864-1877` | ≤1 None; 2 `_build_guided_decision` (LLM with hints, `:2449-2472`); 3 validated replay; ≥4 zero-token replay. **E1:** an Ensign executing a stored Level 3 or 4 procedure now runs Guided: an LLM call with the procedure as hints, its output LLM-written, its tokens spent. Level 5 dispatch equals Level 4 (`test_level_5_dispatch.py:159-179`), so a Commander's dispatch is unchanged |
| promotion `:7768-7783` | **E2:** an Ensign's consecutive successes no longer promote a procedure above Level 2 (`next_level <= min(max_allowed, 5)`, `:7773`), and Ensigns no longer reach Level 4, so they no longer request institutional promotion (`:7782-7783`). **E3:** a Commander's (≥ 0.7) `approved` Level 4 procedure is promoted to Level 5 after `COMPILATION_PROMOTION_THRESHOLD` (3) successes; Level 5 makes the Captain's `/procedure teach` and the teach route available (`commands_procedure.py:412`, `routers/procedures.py:167`); the agent's own `_teach_procedure` has no caller (section 12). A2 (D10): the promoted level is the level `get` returns, so dispatch and both teaching gates see it; before, only the index column moved (E8) |
| demotion `:7786-7799` | unchanged rule: any failure of a procedure-associated decision demotes a stored level above 2 to 2, a Guided run's failure as a replay's did before. The clamp itself writes no level. A2 (D10): the demotion now reaches `get`, so the demoted procedure is dispatched Guided; before, only the index column moved and it kept replaying (E8) |
| **E4** | a failed read, or a value that is not a score in [0, 1] (A2), logs `BF-924 (#1654): trust read failed for <id>; procedure compilation held to Level 2` at WARNING with its traceback, once per trust read: once per procedure match, twice when the promotion step also reads (review round 1: 1, 1, 2, 2, 2 records over five intents; no throttle, R13) |
| **E8 (A2, D10)** | from the merge, a promotion or a demotion changes the level `get` returns, so dispatch follows it. A Lieutenant's (trust from 0.5) Guided procedure is dispatched as Level 3 (deterministic replay plus one LLM validation call, `:2495-2538`; A3, D15: that call was never made until A3, E10) after 3 consecutive successes and as Level 4 (zero-token replay) after 3 more; a Commander's approved Level 4 procedure reaches Level 5 and can be taught; any failure demotes a procedure above Level 2 to Guided for real. Ensigns stay at Level 2 (M1). Live: no active procedure is at Level 3 or above by column (D4); a row whose snapshot already differs from its column keeps its snapshot's level until its next promotion or demotion (R10, D4(c)) |
| **E9 (A2, D9; A3, D17)** | an Ensign's successful Guided run of a matched procedure emits `used_procedure: False`, as every stored Level 2 run does, so AD-532e's reactive check may run for it: at most once per agent per 60 s, only for an unhealthy diagnosis with at least 5 selections, at most one evolution attempt per procedure per 72 h shared with the dream cycle, each attempt one LLM confirmation call (review round 1: one attempt and one call for a degraded procedure). A3: the 72 h bound holds under overlapping deliveries too (each listener runs as its own task, `runtime.py:1987`): the window is claimed in the step that checks it, before the first `await`; review round 2 measured two confirmation calls for two agents' overlapping completions without the claim |
| **E10 (A3, D15)** | a Level 3 dispatch makes its validation call: one LLM request (`max_tokens=100`, the agent's tier) per Level 3 replay of a procedure with a postcondition, a step expected output or an invariant, and one (`max_tokens=50`) per expected output of a compound Level 3 step. YES replays; any other answer sends the intent to the LLM path with a `validation_failure` near-miss (a fallback learning event when that run succeeds, AD-534b) and, since A4, demotes the procedure to Level 2 (E16); a compound step's non-YES answer is a failed replay instead (E14); a call that raises, times out or returns an error reply passes by default with a WARNING (AD-535). Before, no request was made and every replay passed. A procedure with none of the three is replayed without a call, as before. Live: no active procedure is at Level 3 today (D4) |
| **E11 (A3, D16)** | a Lieutenant's procedure that D10 promotes to Level 4 now requests AD-536 institutional promotion (`cognitive_agent.py:7797-7801`), which no run reached before: with at least 10 completions at an effective rate of at least 0.7, its status becomes `pending` (`procedure_store.py:1395-1403`) and a promotion-request thread is posted in the Ward Room (All Hands for high or critical criticality, else the department's channel, else the first channel), with a DM to the routed approver; approval stays with `procedure approve`. The thread's author is now the agent (`self.id`, its callsign); it was the agent type. The DM to a department chief is addressed with the chief's lowercase name as its agent id, so the chief's registered agent is not its member (A4, D23: the chiefs exist; R17) |
| **E12 (A3, D17)** | the 72 h window is claimed before the first `await`: an attempt that raises keeps its claim (before: unrecorded, and retried at the next trigger, at most once per agent per 60 s), and Step 7b's missing-parent exit keeps it; every recorded outcome (a negative or failed confirmation, no evidence, a refused challenger plan, an evolution) records as before |
| **E13 (A3, D18)** | with Ship's Records disabled (`records.enabled: false`), a fallback learning event reaches Step 7d and Step 7e scans threads; before, the handler dropped the event with `AttributeError` and Step 7e raised on its first thread. With Records enabled nothing changes (the setter no longer resets the queue; startup calls it once) |
| **E14 (A4, D20)** | a compound Level 3 step that the validator answers with anything but YES (a failed call still passes) is a failed replay: no action on the rejected replay; one `record_fallback`; the procedure is demoted to Level 2 (count reset); AD-534b's recovery makes one LLM decision, whose answer is returned; the completion event reports `used_procedure: True` and the recovered success; when recovered, an `execution_failure` learning event names the step, and Step 7d answers it as any execution failure (with AD-1326's challenger built, `startup/dreaming.py:168`, a challenger plan; without one, a FIX evolution and the parent's deactivation, `dreaming.py:2317-2325`). With no recovery the intent fails with the step named. Before: success with the unvalidated text, a completion and promotion (Level 4 after three rejections). Live: no active procedure is at Level 3 (D4) |
| **E15 (A4, D21)** | a dispatched compound replay counts toward promotion once per run: a Level 3 compound procedure reaches Level 4 after three dispatched successes, which ends its validation calls (E10); a Commander's approved Level 4 one reaches Level 5; reaching Level 4 can request AD-536 promotion (E11). A step whose dispatch failed still degrades to its text and counts (AD-534c; at Level 3 the step validator judges that text; R23). The compound branch's completion write, event and result are unchanged. Before: no compound procedure ever counted a success |
| **E16 (A4, D22)** | a Level 3 overall NO demotes the procedure to Level 2 and resets its count; the LLM serves the intent, and the `validation_failure` near-miss, its learning event and `used_procedure: False` (D9) are unchanged. Before (since D15): the count was untouched, so three YES answers that were not consecutive promoted it |

**The Level 2 path and AD-534 / dream-time evolution (enumerated).** Writers of the four counters (`procedure_store.py:1052-1074`): selection and applied are recorded before the clamp (`cognitive_agent.py:1831`, `:1847`), unchanged; completion or fallback is recorded once per decision, by the cached branch (`:7732-7741`) or the guided branch (`:7744-7753`), the same counters. So the clamp changes which branch records, not what is recorded: one selection, one applied and one completion-or-fallback per run, either way. Readers of those counters: `diagnose_procedure_health` (`procedures.py:289-320`, thresholds on the four rates), called by the agent at `:1817` (the quality gate, before the clamp, unchanged) and `:1887` (Level ≥ 4 only: an Ensign's run no longer reaches it, so fewer AD-534 WARNING lines; log-only, `:2639-2646`), and by dreaming at `dreaming.py:1880` (`_evolve_degraded_procedures`), `:2151` (reactive), `:2464` (sweep), plus the gap predictor's own rule at `dreaming.py:1303-1310` and `gap_predictor.py:580`. All read `get_quality_metrics` (`procedure_store.py:1135-1162`) only; none reads the dispatch level, `cached` or `guided_by_procedure` (`guided_by_procedure` has two readers, both in `cognitive_agent.py`: `:2468` writes it, `:7744` reads it). So the counters move only with the outcomes of the Guided runs. **Corrected (A2, review round 1 finding 1):** the completion event differs. `TASK_EXECUTION_COMPLETE` reports `used_procedure` from `cached` (`:7852-7859`), which a Guided decision does not set, and AD-532e's reactive check (`dreaming.py:2117-2164`) runs for a run that used no replay. An Ensign's Guided run therefore enters that check, as every stored Level 2 run already does (E9, D9); the earlier "no evolution by itself" compared the counters, not the event. Two behaviours differ for an Ensign's run: the AD-534b service recovery (`:7805`) runs only for a failed *cached* replay, and `:1887`'s log-only diagnosis does not run.

**(b) F04: `get_history` and the values it makes real.** States: *measured* (≥ 2 events); *fewer than 2 events* → `insufficient_trust_history` as today (the event log is in memory, 500 events ship-wide, empty at boot: `trust.py:265`); *errored* → telemetry's `except` gives `[]` (degraded as today); the route does not catch (as for `get_score` today).

| Value | Reader | Effect |
|---|---|---|
| `trustHistory` (`routers/agents.py:383`) | `ui/src/hooks/useProfileResource.ts:54` (validates floats in [0, 1]: `new_score` is a Beta mean), `ui/src/components/profile/ProfileHealthTab.tsx:41-44` (sparkline when more than one) | **E5:** the Captain's profile shows the last 20 trust scores |
| `trust_delta` (`telemetry.py:734`) | `apply_voice_modulation` (`:452-457`, ±0.2 from `ui/src/audio/modulation_manifest.json:3-4`; factors 1.03 / 0.97, `:8-9`); the Captain's Self Image tab (`ui/src/components/profile/SelfImageTab.tsx:100` fetch, `:138` stream, `:277` to `:455`; A3, D19) | **E6:** in the backend projection (A2, D13), when the last two scores differ by more than 0.2, the pitch moves 3 % and `high_trust_pitch` or `low_trust_pitch` enters `fired_rules`; the Captain's Self Image tab shows that delta, factor and rule (A3, D19) |
| `applied_modulation` | the backend avatar projection, which the Captain's Self Image tab displays (`SelfImageTab.tsx:278` to `:484` `pitch_factor`, `:488` `fired_rules`; A3, D19), not the Captain's voice playback or VRM, whose `deriveAgentSignals` hardcodes `trust_delta = 0` (`ui/src/components/profile/avatarSignals.ts:44-46`; A2, D13); the agent's interoception `pitch=` (`cognitive_agent.py:6903-6905`, gated by `avatar_telemetry.inject_into_agent_context`, default False `config.py:2023`, **true** in `config/system.yaml:1631`); the divergence note (`:6950-6956`) lists the applied rules | **E6 (crew- and Captain-visible):** an agent can read its pitch factor and a rule name `low_trust_pitch` / `high_trust_pitch` in its own context, and the Captain's Self Image tab shows the same factor and rule (A3); a factual display of a qualified gauge, no action |
| divergence (`divergence_detector.py:390-633`) | `compute_divergence` scores only `intent_*` rules (`:320-334`); `_applied_direction` uses operational rules only when no intent rule fired (`:281-301`), and a parsed intent always fires its rule (`telemetry.py:470-495`; every v1 emotion has one, `modulation_manifest.json:19-26`) | sign, magnitude, the trust write (`:589-612`) and the Hebbian update (`:624-631`) unchanged |
| `records_writer._classify` (`records_writer.py:87-122`) | reads divergence magnitude, working state, silence | unchanged |
| `SelfPerceptionProjection.modulation_pitch_factor` (`self_perception.py:125`) | `project_self_perception` has no caller (section 12) | none |
| frames (`telemetry_frames.py:161-176`) | `trust_delta` must be finite in [-1, 1] | a difference of two [0, 1] scores is |
| `degraded_reasons` | `insufficient_trust_history` (`telemetry.py:730-731`, logged through `_warn`) | fewer such warnings (74 in the issue's live log) |

**(c) F05.** One reader: the table's Agent column. A failure of the lookup shows the id prefix as before.

**(d) F10.** `trust_delta_threshold`: one reader (`_on_trust_update`); `sweep_max_agents`: one reader (`_run_wellness_sweep`'s default) reached by `act` and the API. Every result state of both handlers is as today with the defaults. **E7:** an operator value now changes behaviour: a lower threshold reassesses more trust updates (each can DM on today's live inputs, BF-923 D8), a lower sweep bound assesses fewer crew. Writers of the fields: `config/system.yaml:1179-1180` (same values as the defaults); no profile under `config/profiles/` and neither node config sets a counselor key (section 11).

## 6. Milestones and tests

**M1 (HIGH), §7.1 to §7.4.** First heading: `### 7.1 \`src/probos/cognitive/cognitive_agent.py\` (M1)`. Commit "BF-924 M1: the procedure-compilation trust clamp reads the agent's live trust (part of #1654)", body ending "AD-535/536 read a _trust_score attribute nothing sets, so every agent counted as 0.5. The clamp and the promotion step now read TrustNetwork.get_score(self.id), as the rank read does; an unreadable trust logs a WARNING and takes the Ensign cap (Level 2). Ensigns run stored Level 3 and 4 procedures as Guided; a Commander's approved procedure can reach Level 5. Level 3 validation calls the LLM client's complete(), which it never reached; the 72 h evolution window is claimed before its first await; the dreaming fallback queue no longer depends on Ship's Records; a promotion request is posted as the agent. Every replay outcome reaches AD-535's promotion step once: a dispatched compound replay counts, a rejected compound step is a failed replay the LLM recovers, and a Level 3 NO demotes."

Before editing, grep the pins: `grep -rn "_trust_score\|_max_compilation_level_for\|_check_procedural_memory\|promote_compilation_level" tests/`. The hand-set `_trust_score` in `test_graduated_compilation.py` and `test_level_5_dispatch.py` is replaced (§7.3, §7.4). `test_teaching_protocol.py:93` also sets it, but none of its tests reaches the clamp (it does not call `_check_procedural_memory`); it is left, now dead (R7).

**Named doubles and what they mask (M1).** `test_ad573_memory_budget.py:157-164` replaces `_check_procedural_memory` whole, so it never reaches the clamp. `MagicMock` runtimes in `test_replay_dispatch.py`, `test_multi_agent_replay_dispatch.py`, `test_fallback_learning.py` and the `_check_procedural_memory` callers of `test_graduated_compilation.py` that assign their own runtime: `runtime.trust_network.get_score(...)` returns a `MagicMock`, which `float()` reads as 1.0, so each such test now runs the clamp at Senior trust. (A2 correction, review round 1 property 4: the two inline sites named here before, `test_graduated_compilation.py:545` and `:573` at the base, are `test_compound_level_3_step_validation` and `test_compound_level_3_step_failure_aborts`; they call `_execute_compound_replay` directly and never reach the clamp. The reviewer gave the masked runtimes real networks: at 0.5 all 219 tests pass; at 0.3, 26 fail, each a replay, compound-dispatch or recovery expectation turning Guided, and none needs the mock's Senior score. A2's range check keeps 1.0 in range.) It masks nothing they assert: each dispatches a non-`approved` procedure, where every trust ≥ 0.5 caps at 4 (the grep `approved` over these files finds only `test_level_5_dispatch.py`, whose factory §7.4 repairs, and `test_teaching_protocol.py`). `ReplayTestAgent`, `_make_store_mock` and `_make_runtime_with_store` (`test_replay_dispatch.py:28`, `:63`, `:87`) and the lifecycle helpers of `test_fallback_learning.py:28-115` are reused: the store doubles return chosen procedures (they mask the semantic match, not the clamp); `_recall_relevant_memories` and `_store_action_episode` are patched as `test_fallback_learning.py:237-239` does (memory recall and episode storage, not on the changed path). `_UnreadableTrustNetwork` stands for a failing store. In the two failure cases `_build_guided_decision` is a spy: it replaces only the Guided LLM call, so the only trust read is the clamp's.

Tests first: with §7.2 to §7.4 applied and §7.1 not, exactly 6 cases fail:
- `test_an_ensign_runs_a_stored_level_4_procedure_as_guided`: `assert None is True` on `guided_by_procedure` (a cached replay);
- `test_an_unreadable_trust_is_held_to_level_2_and_warned[raises]`, `[absent]`: `Expected '_build_guided_decision' to have been awaited once. Awaited 0 times.`;
- `test_a_commanders_approved_procedure_is_promoted_to_level_5`: `promote_compilation_level` awaited 0 times;
- `test_an_ensigns_successes_do_not_promote_it_past_level_2`: `Expected 'promote_compilation_level' to not have been awaited. Awaited 1 times.`;
- `TestTrustClamping::test_clamping_applied_in_check_procedural_memory` (`test_graduated_compilation.py:146`): its factory no longer sets `_trust_score`, so the base reads 0.5: `assert None is True`.

`test_a_lieutenant_still_replays_a_stored_level_4_procedure` passes on both sides (the premise). A failure for another reason (an exception before the asserted line) is a hard stop for the Architect. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_compilation_trust.py tests/test_graduated_compilation.py tests/test_level_5_dispatch.py tests/test_replay_dispatch.py tests/test_multi_agent_replay_dispatch.py tests/test_fallback_learning.py tests/test_ad573_memory_budget.py tests/test_teaching_protocol.py tests/test_promotion_approval.py tests/test_promotion_integration.py tests/test_procedure_store.py tests/test_ad1326_procedure_ledger.py tests/test_bf891_procedure_store_lock.py tests/test_reactive_proactive_triggers.py tests/test_procedure_evolution.py tests/test_bf106_dreaming_di.py tests/test_ad1326_dreaming_challenger.py tests/test_ad1326_challenger_e2e.py tests/test_dream_step_7e.py tests/test_dream_step_7f.py tests/test_ad541c_retrieval_practice.py -n 0 -q
```

(Collected on `ba45c61f` without the new file: 270, all passing. Expect 277 passed. A1: the orchestrator's measured counts supersede this line; A1 adds and removes no M1 case.) A2: the oracle measured 276 for the ten original files (the new file had 5 functions and 6 cases, not 6 and 7); A2 adds 10 cases, so expect 286 for those ten, plus the four files A2 adds (`test_procedure_store.py`, `test_ad1326_procedure_ledger.py`, `test_bf891_procedure_store_lock.py`, `test_reactive_proactive_triggers.py`: the consumers of the two store methods and of the completion event), whose collected count the orchestrator measures. A3: the orchestrator measured 540 for these fourteen files on the M1 candidate; A3 adds 11 cases there (10 in the new file, 1 in `test_graduated_compilation.py`), so expect 551, plus the seven files A3 adds (`test_procedure_evolution.py`, `test_bf106_dreaming_di.py`, `test_ad1326_dreaming_challenger.py`, `test_ad1326_challenger_e2e.py`, `test_dream_step_7e.py`, `test_dream_step_7f.py`, `test_ad541c_retrieval_practice.py`: the readers of the evolution window, the Records setter's callers and the `__new__` factories that set the two moved fields), whose collected count the orchestrator measured: 125, so the 21-file M1 list collects 676 and all of them pass. A4 appends 6 cases to the new file: expect 682 collected and passed for the 21-file list; the M2 list is unchanged (1,035).

**A2 tests first.** On the candidate's source (`cad8396f`), with only A2's test changes applied (§7.2's additions, §7.3 Pair 5, §7.4b, §7.20's additions), exactly 13 of the new and changed cases fail:
- M1 (8): `test_a_trust_that_is_not_a_score_is_held_to_level_2_and_warned[nan]`, `[above-one]`, `[inf]` (`assert None is True` on `guided_by_procedure`: a Level 4 replay); `test_an_infinite_trust_does_not_promote_an_approved_procedure_to_level_5` (`[5] == [4]`); `test_a_runtime_whose_trust_network_cannot_be_read_is_held_to_level_2_and_warned` (`RuntimeError: trust network unavailable` raised by `decide`: the defect itself, so the expected failure, not a hard stop); `test_a_commanders_promotion_to_level_5_reaches_get_and_the_teaching_route` (`4 == 5` on the level `get` returns); `test_a_demoted_procedure_is_dispatched_at_its_demoted_level` (`4 == 2` on the level `get` returns); `TestConsecutiveSuccessTracking::test_promote_compilation_level` (`2 == 3`).
- M2 (5): `test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown[inf]` (`OverflowError` from `_grant_list`) and `[past-time_t]` (`OSError: [Errno 22] Invalid argument` on Windows, `ValueError` or `OverflowError` elsewhere); `test_grant_issue_refuses_a_duration_that_cannot_be_an_expiry[nan]` (`assert [ClearanceGrant(...)] == []`), `[inf]` (`OverflowError`) and `[1e13]` (`OSError` on Windows), the last two from the listing after the admitted grant.

Pass on both sides: the three cases of `test_a_clamped_guided_run_reaches_the_reactive_trigger_as_a_stored_level_2_run_does` (D9 pins today's event), `test_restore_with_a_refused_snapshot_publishes_no_active_entry_at_a_stale_level` (its premise is now set directly) and the two existing grant tests. On the base, for the oracle's staged run: the M1 stage (§7.1 and §7.4a not applied) fails 14 cases (the original 6; the M1 cases above except the infinite-trust promotion test, which passes because the base never reaches Level 5; the Commander teaching test fails at its column premise `[4] == [5]`; and `[ensign-clamped-to-guided]`, which the base serves as a replay); the M2 stage fails 24 (the original 19 and the 5 above, each on `list_all`).

**A3 tests first.** On the candidate's source (`09fe39fc`), with only A3's test changes applied (§7.2's import pair, comment and additions; §7.3 Pairs 1 and 6 to 8; §7.4d; §7.4e; §7.20's helper and three callers), exactly 18 cases fail, all in M1:
- `test_bf924_compilation_trust.py` (10): `test_a_level_3_replay_is_validated_through_the_client_interface[yes]` (`assert 0 == 1` on `complete.await_count`) and `[no]` (`assert 0 == 2`); `test_a_failed_level_3_validation_call_passes_by_default_and_warns[raises]` and `[error-reply]` (`assert 0 == 1`); `test_a_lieutenants_promotion_to_level_4_requests_institutional_promotion_as_the_agent` (`('test_replay', 'test_replay') == (<agent id>, 'Wesley')`); `test_overlapping_completions_of_one_procedure_make_one_evolution_attempt` (`assert 2 == 1`); `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7b]` (`assert 1 == 0`) and `[7d]` (`TimeoutError` at the parent-load wait after 10 s: on the candidate the queue does not exist, so Step 7d raises before its load; with §7.4c Pair 1 alone applied it fails `assert 1 == 0`); `test_a_fallback_reaches_step_7d_when_ships_records_is_disabled` (`AttributeError: 'DreamingEngine' object has no attribute '_fallback_learning_queue'`, from `_process_fallback_learning`) and `test_step_7e_runs_when_ships_records_is_disabled` (the same for `'_observed_threads'`): the defect itself, the expected failure, not a hard stop.
- `test_graduated_compilation.py` (8): `test_validation_timeout_passes`, `test_validation_includes_postconditions`, `test_validation_includes_step_expected_outputs`, `test_validation_includes_invariants`, `test_validate_step_postcondition_passes`, `test_validate_step_postcondition_fails`, `test_validate_step_llm_failure_passes` and `test_validate_step_error_reply_passes`, each `assert 0 == 1` on `complete.await_count` (the candidate calls `generate`, which the `BaseLLMClient`-specced double does not have).

No M2 case fails on the candidate (the table is printed); R24 checks the strengthened helper. Every other case of these files passes on both sides; a failure for another reason is a hard stop for the Architect. On the base, for the oracle's staged run: the M1 stage fails 31 (A2's 14 and 17 of these 18, each the same way: `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7b]` passes on the base, where an Ensign's replay reports `used_procedure=True` and the reactive check never runs); the M2 stage fails 24, as before (the orchestrator measured 31 of 676 and 24 of 1,035).

**A4 tests first.** On the candidate's source (`cb201c20`; M2 changes neither `cognitive_agent.py` nor the new test file), with only A4's test changes applied (§7.2's import pair and five appended functions), exactly 6 cases fail, all in `tests/test_bf924_compilation_trust.py`:
- `test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers`: `assert 0 == 1` on `run.ordinary` (the candidate acts on the rejected replay and makes no recovery call);
- `test_a_rejected_compound_step_without_recovery_fails_and_never_acts_on_the_replay`: `assert 1 == 0` on `act.await_count`;
- `test_dispatched_compound_replays_count_toward_promotion_once_per_run[yes]` and `[error-reply]`: `[(3, 0), (3, 0), (3, 0), (3, 0)] == [(3, 1), (3, 2), (4, 0), (4, 1)]`;
- `test_a_commanders_approved_compound_procedure_reaches_level_5`: `[4, 4, 4] == [4, 4, 5]`;
- `test_a_level_3_no_demotes_the_procedure_and_resets_its_count`: `(3, 2) == (2, 0)`.

Every premise assertion passes on the candidate (step 1 delivered and rejected; every step delivered with no ordinary call; Level 4 makes no validation call; the validation request, then the LLM decision); a failure at a premise, or any other case of the 21 files failing, is a hard stop for the Architect. On the base, for the oracle's staged run: the M1 stage fails 37 (A3's 31 and these 6: the two rejection cases and the Level 3 NO case at their premise, because the base's validators call `generate` and make no request; the two counting cases at the same assertion as on the candidate; the Commander case at `[4, 4, 4] == [4, 4, 5]`, because the base reads trust 0.5); the M2 stage fails 24, as before.

**M2 (STANDARD), §7.5 to §7.22.** First heading: `### 7.5 \`src/probos/consensus/trust.py\` (M2)`. After applying §7.5 to §7.22, regenerate and check, in this order:

```
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
```

The regenerated `docs/development/config-reference.md` and `docs/development/config-facade-baseline.yaml` go in M2's commit (A2, D14: run all four from the scratch tree with `PYTHONPATH` set to its `src`, as every focused run here is; §7.23 also anchors `gen_config_reference.py` to its own `src`, as its two siblings already are; A2 changes no generated file). Their diff is exactly these hunks (A1: measured by the oracle on the applied tree, `logs/bf924r1/generated-config-diff.txt`):
- `config-facade-baseline.yaml`, `surface_counts` (at `:50-51`): `canonical_dump_leaves` 1891 to 1887 and `field_definitions` 1880 to 1876; `aliased_fields` 1, `incidental` 13, `own_models` 228, `owned` 296 and `public_names` 309 unchanged;
- the same file, `canonical_dump_sha256` (`:56`): `fc24f1a1...` to `bbf47ad58a4316e1906cd1efff1ec25594b81c66dd6ff5b096a9fbd18aa16969`;
- the same file, the `CounselorConfig` row (`:1322-1334`): `schema_sha256` `291ee4ff...` to `49520476ec22781ac072400fab49280779d5bd5dbf85a49bab5d9656e0705abc`, and the four field lines `enabled`, `profile_retention_days`, `alert_on_red`, `alert_on_yellow` deleted; `trust_delta_threshold` and `sweep_max_agents` unchanged;
- the same file, the `SystemConfig` row (`:3418`, the model that contains `CounselorConfig`): `schema_sha256` `ba3ec2db...` to `dc10c4795616d785b6c6860834ef150fab29c53abd48d9052f3950c44abc82aa`, nothing else;
- `config-reference.md`, the `counselor` section (`:1289-1294`): the four rows of the removed fields deleted; the description line ("Counselor cognitive wellness configuration (AD-503).", the docstring's first line) and the two remaining rows unchanged.

The three hashes are the values for §7.11 applied byte for byte (the schema includes the docstring). Any other file, hunk or value, or a `--check` failure, is a hard stop for the Architect. Commit "BF-924 M2: trust history, /grant list and the Counselor's config read real APIs (part of #1654)", body ending "TrustNetwork.get_history returns the agent's last trust scores, so profile trust history and the avatar trust delta are real; both hasattr guards are removed. /grant list names a target through its birth certificate and live callsign. The Counselor takes CounselorConfig by constructor injection and reads trust_delta_threshold and sweep_max_agents (defaults unchanged); enabled, profile_retention_days, alert_on_red and alert_on_yellow had no reader and are removed." The tracker entries (section 8) go in the tracker commit that follows M2's, with the regenerated AD ledger (the orchestrator applies them by tool and commits them separately, as for BF-921 to BF-923).

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

(Collected on `ba45c61f` without the new file: 1,015; not run here. Expect 1,030 collected; the orchestrator computes the pass and skip counts by tool. A1: the oracle collected 1,306 for the union of both lists (29 files); A1 adds and removes no case, so expect 1,306 collected and 1,306 passed for the union. A2: the oracle measured 1,030 for this list; A2 adds 5 cases, so expect 1,035; the union becomes 1,321 plus the four files A2 adds to the M1 list. A3 adds no M2 case: expect 1,035.)

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
        A read that fails (the runtime, its ``trust_network`` attribute or ``get_score``), or a value
        that is not a score in [0, 1] (NaN, an infinity, a corrupt record), logs a WARNING and returns
        0.0: an unknown trust takes the Ensign cap (Level 2) and never unlocks replay or Level 5.
        """
        try:
            score = float(self._runtime.trust_network.get_score(self.id))
            if not 0.0 <= score <= 1.0:  # BF-924 (#1654): NaN fails both bounds, so it is refused too
                raise ValueError(f"trust score {score!r} is not in [0, 1]")
            return score
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

Pair 4 (A3, D15: the replay validator calls the client's interface; mirrors A3-1):

SEARCH:
````python
        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True

            response = await asyncio.wait_for(
                llm_client.generate(validation_prompt, max_tokens=100),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )

            answer = response.strip().upper()
            return answer.startswith("YES")

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Level 3 validation call failed for procedure %s: %s — passing by default",
                procedure.name, exc,
            )
            return True
````
REPLACE:
````python
        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True

            # BF-924 (#1654): the client's interface is complete(LLMRequest) -> LLMResponse, as the agent's other
            # helper calls use it. generate() exists on no client: the AttributeError was caught below as
            # "passing by default", so every Level 3 replay passed with no request made.
            validation_request = LLMRequest(prompt=validation_prompt, tier=self._resolve_tier(), max_tokens=100)
            response = await asyncio.wait_for(
                llm_client.complete(validation_request, priority=Priority.NORMAL),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )
            if response.error is not None:  # BF-924 (#1654): an error reply is a failed call; AD-535 passes it by default
                raise RuntimeError(response.error)

            answer = response.content.strip().upper()
            return answer.startswith("YES")

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Level 3 validation call failed for procedure %s: %s — passing by default",
                procedure.name, exc,
            )
            return True
````

Pair 5 (A3, D15: the step validator calls the client's interface; mirrors A3-2):

SEARCH:
````python
        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True
            response = await asyncio.wait_for(
                llm_client.generate(prompt, max_tokens=50),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )
            return response.strip().upper().startswith("YES")
        except Exception:
            return True  # Fail-open
````
REPLACE:
````python
        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True
            # BF-924 (#1654): complete(LLMRequest), the client's interface; generate() exists on no client
            step_request = LLMRequest(prompt=prompt, tier=self._resolve_tier(), max_tokens=50)
            response = await asyncio.wait_for(
                llm_client.complete(step_request, priority=Priority.NORMAL),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )
            if response.error is not None:  # BF-924 (#1654): an error reply is a failed step call; AD-535 passes it by default
                raise RuntimeError(response.error)
            return response.content.strip().upper().startswith("YES")
        except Exception as exc:
            # BF-924 (#1654): said at WARNING, as the replay validator does; the silent pass hid the defect
            logger.warning(
                "Level 3 step validation call failed for step %s: %s — passing by default",
                step.step_number, exc,
            )
            return True  # Fail-open (AD-535)
````

Pair 6 (A3, D16: the promotion request is posted as the agent; mirrors A3-3):

SEARCH:
````python
            agent_type = getattr(self, "agent_type", "")
            agent_id = getattr(self, "_agent_id", agent_type)
            callsign = getattr(self, "_callsign", agent_type)

            # Post to appropriate channel
````
REPLACE:
````python
            agent_type = getattr(self, "agent_type", "")
            agent_id = self.id  # BF-924 (#1654): the author is the agent; no agent has an _agent_id attribute
            callsign = self.callsign or agent_type  # BF-924 (#1654): no agent has a _callsign attribute

            # Post to appropriate channel
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

import asyncio
import logging
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient, OpenAICompatibleClient
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import ProcedureStep
from probos.config import COMPILATION_PROMOTION_THRESHOLD, TRUST_COMMANDER, DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.procedures import TeachRequest, teach_procedure
from probos.substrate.registry import AgentRegistry
from probos.types import AgentState, LLMRequest, LLMResponse, Priority
from tests.test_fallback_learning import _make_cognitive_agent as _make_lifecycle_agent
from tests.test_fallback_learning import _make_dreaming_engine, _make_intent, _make_procedure
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


# --- A2 (review round 1): a real ProcedureStore, the trust guard and the completion event ----------------


class _KnownMatchStore(ProcedureStore):
    """A real ``ProcedureStore`` whose semantic ranking is fixed: every active procedure matches at 0.9.

    Only ChromaDB is left out (``_init_chroma`` opens nothing, ``find_matching`` ranks from SQLite);
    persistence, ``get``, the counters, promotion and the promotion status are the real store's.
    """

    async def _init_chroma(self) -> None:
        return None

    async def find_matching(self, query, *, n_results=5, min_compilation_level=0, exclude_negative=True):
        if not exclude_negative:
            return []  # the negative-procedure check: no anti-pattern is stored
        entries = await self.list_active(min_compilation_level=min_compilation_level)
        return [{**entry, "score": 0.9} for entry in entries][:n_results]


async def _store_rig(tmp_path, score: float, level: int, *, approved: bool = False) -> SimpleNamespace:
    """A ``ReplayTestAgent`` at trust ``score`` whose runtime holds a real store with one procedure at ``level``."""
    store = _KnownMatchStore(tmp_path / "procedures")
    await store.start()
    proc = _make_procedure(id="proc-bf924-store", compilation_level=level)
    await store.save(proc)
    if approved:
        await store.approve_promotion(proc.id, "captain", "directive-bf924")
    events: list[tuple] = []
    runtime = SimpleNamespace(
        procedure_store=store, trust_network=TrustNetwork(), cognitive_journal=None, episodic_memory=None,
        emit_event=lambda *args, **kwargs: events.append(args),
        ward_room=SimpleNamespace(
            get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-bf924")),
            create_thread=AsyncMock(),
        ),
    )
    llm = MockLLMClient()
    agent = ReplayTestAgent(llm_client=llm, runtime=runtime)
    runtime.trust_network = trust_network_at(agent.id, score)
    return SimpleNamespace(store=store, proc=proc, agent=agent, runtime=runtime, llm=llm, events=events)


async def _handle_on_store(agent, *, succeed: bool = True):
    """One matched intent through ``handle_intent``; ``succeed=False`` makes the action fail and skips the recovery."""
    intent = _make_intent(target_agent_id=agent.id)
    with patch.object(
        agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda _intent, observation: observation),
    ), patch.object(agent, "_store_action_episode", new=AsyncMock()):
        if succeed:
            return await agent.handle_intent(intent)
        with patch.object(agent, "act", new=AsyncMock(return_value={"success": False, "error": "chosen failure"})), \
                patch.object(agent, "_run_llm_fallback", new=AsyncMock(return_value=None)):
            return await agent.handle_intent(intent)


class _FixedScoreTrustNetwork:
    """Returns one score for every agent: a Beta mean is never infinite, so an infinity can only come from a double."""

    def __init__(self, score: float) -> None:
        self._score = score

    def get_score(self, agent_id: str) -> float:
        return self._score


class _RuntimeWithUnreadableTrustNetwork:
    """A runtime whose ``trust_network`` attribute read raises; every other attribute is the wrapped runtime's."""

    def __init__(self, inner: SimpleNamespace) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    @property
    def trust_network(self):
        raise RuntimeError("trust network unavailable")


def _warned(caplog) -> bool:
    return any(record.levelno == logging.WARNING and "BF-924" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [float("nan"), 2.0, math.inf], ids=["nan", "above-one", "inf"])
async def test_a_trust_that_is_not_a_score_is_held_to_level_2_and_warned(tmp_path, score, caplog) -> None:
    """Finding 3 (review round 1): NaN failed both comparisons and took the Level 4 cap; 2.0 and infinity passed."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        # A real TrustNetwork holds the finite cases (a corrupt Beta record); a Beta mean is never infinite.
        r.runtime.trust_network = (
            _FixedScoreTrustNetwork(score) if math.isinf(score) else trust_network_at(r.agent.id, score)
        )
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("compilation_level") == 2
        assert decision.get("cached") is not True
        assert _warned(caplog)
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_an_infinite_trust_does_not_promote_an_approved_procedure_to_level_5(tmp_path) -> None:
    """Finding 3 (review round 1): ``inf >= TRUST_COMMANDER`` promoted an approved Level 4 procedure to Level 5."""
    r = await _store_rig(tmp_path, 0.8, 4, approved=True)
    try:
        r.runtime.trust_network = _FixedScoreTrustNetwork(math.inf)
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all(result is not None and result.success is True for result in results)  # premise: the step ran
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [4]
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_runtime_whose_trust_network_cannot_be_read_is_held_to_level_2_and_warned(tmp_path, caplog) -> None:
    """Finding 4 (review round 1): the attribute was read before the ``try``, so its failure failed ``decide``."""
    r = await _store_rig(tmp_path, 0.6, 4)
    try:
        r.agent._runtime = _RuntimeWithUnreadableTrustNetwork(r.runtime)
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("cached") is not True
        assert _warned(caplog)
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_commanders_promotion_to_level_5_reaches_get_and_the_teaching_route(tmp_path) -> None:
    """D10 (review round 1, finding 2): a promotion moved only the index column; ``get`` and teaching read the snapshot."""
    r = await _store_rig(tmp_path, 0.7, 4, approved=True)
    try:
        assert r.runtime.trust_network.get_score(r.agent.id) >= TRUST_COMMANDER  # premise: Commander trust, exactly
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]
        assert all(result is not None and result.success is True for result in results)
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [5]  # premise: the column

        loaded = await r.store.get(r.proc.id)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        reply = await teach_procedure(
            TeachRequest(procedure_id=r.proc.id, target_callsign="Learner"), runtime=r.runtime,
        )

        assert loaded is not None and loaded.compilation_level == 5
        assert (metrics["total_completions"], metrics["consecutive_successes"]) == (3, 0)  # counters kept
        assert reply.get("success") is True, reply
        r.runtime.ward_room.create_thread.assert_awaited_once()
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_demoted_procedure_is_dispatched_at_its_demoted_level(tmp_path) -> None:
    """D10 (review round 1, finding 2): a failure demoted only the index column, so the procedure kept replaying."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        failed = await _handle_on_store(r.agent, succeed=False)
        assert failed is not None and failed.success is False  # premise: the failure branch ran
        loaded = await r.store.get(r.proc.id)
        assert loaded is not None and loaded.compilation_level == 2

        decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("cached") is not True
    finally:
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "stored_level", "used_procedure", "attempts"),
    [(0.3, 4, False, 1), (0.5, 2, False, 1), (0.5, 4, True, 0)],
    ids=["ensign-clamped-to-guided", "lieutenant-stored-guided", "lieutenant-replay"],
)
async def test_a_clamped_guided_run_reaches_the_reactive_trigger_as_a_stored_level_2_run_does(
    tmp_path, score, stored_level, used_procedure, attempts,
) -> None:
    """D9 (review round 1, finding 1): AD-532e's reactive check takes a Guided run, clamped or stored, as an LLM run.

    The completion event reports ``used_procedure`` from ``cached`` (AD-532e), and a Guided decision is not cached
    because the LLM ran (AD-535). Producer and consumer are real; the store is real but for its ranking.
    """
    r = await _store_rig(tmp_path, score, stored_level)
    try:
        # Degraded (effective rate 0.4) yet above the dispatch gate (0.3), so the reactive check diagnoses it.
        for n in range(10):
            await r.store.record_selection(r.proc.id)
            await r.store.record_applied(r.proc.id)
            await (r.store.record_completion if n < 4 else r.store.record_fallback)(r.proc.id)

        result = await _handle_on_store(r.agent)
        assert result is not None and result.success is True
        payloads = [args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE]
        assert len(payloads) == 1  # premise: the real lifecycle emitted one completion

        engine = _make_dreaming_engine(procedure_store=r.store, llm_client=MockLLMClient())
        # Never reached: the mock's confirmation is not YES, so the attempt stops at the gate (review round 2 measured
        # one confirmation call and no recall). Kept so that a YES would still find no evidence.
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])
        attempt = AsyncMock(wraps=engine._attempt_procedure_evolution)
        engine._attempt_procedure_evolution = attempt
        await engine.on_task_execution_complete(payloads[0])

        assert payloads[0]["used_procedure"] is used_procedure
        assert attempt.await_count == attempts
    finally:
        await r.store.stop()


# --- A3 (review round 2): Level 3 validation, the promotion request, the evolution window, Records off --------


def _replies(*first: LLMResponse | BaseException):
    """``complete``'s side effect: ``first`` in order (an exception is raised), then an ordinary LLM decision."""
    queue = list(first)

    async def reply(request: LLMRequest, **_kwargs: object) -> LLMResponse:
        item = queue.pop(0) if queue else LLMResponse(content="an LLM decision")
        if isinstance(item, BaseException):
            raise item
        return item

    return reply


async def _level_3_rig(tmp_path, *replies: LLMResponse | BaseException):
    """A Lieutenant's stored Level 3 procedure with a postcondition, validated through a real ``OpenAICompatibleClient``.

    Only the client's ``complete`` is replaced, as the reviewer's probe did (review round 2): a call to any other
    name fails as in production. The client is never contacted.
    """
    r = await _store_rig(tmp_path, 0.5, 3)
    r.proc.postconditions = ["the boundary result was checked"]
    await r.store.save(r.proc)
    client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    r.agent._llm_client = client  # replaced after construction, as the reviewer's probe did
    return r, client, AsyncMock(side_effect=_replies(*replies))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "calls", "replayed"),
    [("YES, the result was checked", 1, True), ("NO: nothing was checked", 2, False)],
    ids=["yes", "no"],
)
async def test_a_level_3_replay_is_validated_through_the_client_interface(tmp_path, answer, calls, replayed) -> None:
    """Finding 1 (review round 2): the validator called ``generate``, which no client has; the ``AttributeError``
    was caught as "passing by default", so every Level 3 replay was cached as validated with no request made.
    A NO now sends the intent to the LLM (its second request), as AD-535 specifies."""
    r, client, complete = await _level_3_rig(tmp_path, LLMResponse(content=answer))
    try:
        with patch.object(client, "complete", complete):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert complete.await_count == calls
        validation = complete.await_args_list[0].args[0]
        assert isinstance(validation, LLMRequest) and "the boundary result was checked" in validation.prompt
        assert bool(decision.get("cached")) is replayed
        assert (decision.get("compilation_level") == 3) is replayed
    finally:
        await client.close()
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("provider down"), LLMResponse(content="", error="All LLM tiers unavailable")],
    ids=["raises", "error-reply"],
)
async def test_a_failed_level_3_validation_call_passes_by_default_and_warns(tmp_path, failure, caplog) -> None:
    """AD-535 (Part 5 and its acceptance): a validation call that fails passes by default. A3 keeps that rule and
    counts an error reply, which the client returns instead of raising (``llm_client.py:2092``), as a failed call."""
    r, client, complete = await _level_3_rig(tmp_path, failure)
    try:
        with patch.object(client, "complete", complete), \
                caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert complete.await_count == 1  # the validation request, and no LLM decision after it
        assert decision.get("cached") is True and decision.get("compilation_level") == 3
        assert any("Level 3 validation call failed" in record.getMessage() for record in caplog.records)
    finally:
        await client.close()
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_lieutenants_promotion_to_level_4_requests_institutional_promotion_as_the_agent(tmp_path) -> None:
    """E11 (A3, D16): with D10 a Lieutenant's procedure reaches Level 4, and AD-536 requests institutional
    promotion, which no run reached before. The request was posted as ``getattr(self, "_agent_id", agent_type)``
    and ``_callsign``, attributes no agent has, so its author was the agent type."""
    r = await _store_rig(tmp_path, 0.5, 3)
    try:
        r.agent.callsign = "Wesley"
        r.runtime.ontology = None
        r.runtime.ward_room.list_channels = AsyncMock(return_value=[SimpleNamespace(id="all-hands", name="All Hands")])
        for _ in range(10):  # AD-536's floor: 10 completions at an effective rate of at least 0.7
            await r.store.record_selection(r.proc.id)
            await r.store.record_applied(r.proc.id)
            await r.store.record_completion(r.proc.id)
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all(result is not None and result.success is True for result in results)
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [4]  # premise: promoted
        assert await r.store.get_promotion_status(r.proc.id) == "pending"  # premise: AD-536's request ran (E11)
        thread = r.runtime.ward_room.create_thread.await_args_list[0].kwargs
        assert (thread["author_id"], thread["author_callsign"]) == (r.agent.id, "Wesley")
        assert r.runtime.ward_room.get_or_create_dm_channel.await_args.args[0] == r.agent.id
    finally:
        await r.store.stop()


class _ConfirmationLLM(BaseLLMClient):
    """A real ``BaseLLMClient`` that answers NO; with ``hold`` each call stays in flight until ``release`` is set."""

    def __init__(self, *, hold: bool = False) -> None:
        self.requests: list[LLMRequest] = []
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        await self.release.wait()
        return LLMResponse(content="NO")

    def confirmations(self) -> int:
        """AD-532e's confirmation gate calls (``confirm_evolution_with_llm``'s question), not evolution rewrites."""
        return sum("Should this procedure be evolved?" in request.prompt for request in self.requests)


def _constructed_dreaming_engine(r, llm: BaseLLMClient) -> DreamingEngine:
    """A ``DreamingEngine`` built by its constructor alone: startup leaves it so when Ship's Records is disabled."""
    return DreamingEngine(
        router=SimpleNamespace(), trust_network=r.runtime.trust_network,
        episodic_memory=SimpleNamespace(recall_by_intent=AsyncMock(return_value=[])),
        config=DreamingConfig(), llm_client=llm, procedure_store=r.store,
    )


async def _degrade(r) -> None:
    """Effective rate 0.4 over 10 selections: unhealthy for AD-534, yet above the dispatch gate (0.3)."""
    for n in range(10):
        await r.store.record_selection(r.proc.id)
        await r.store.record_applied(r.proc.id)
        await (r.store.record_completion if n < 4 else r.store.record_fallback)(r.proc.id)


async def _guided_completion(r, agent) -> dict:
    """One successful run through ``handle_intent``; returns its ``TASK_EXECUTION_COMPLETE`` payload."""
    result = await _handle_on_store(agent)
    assert result is not None and result.success is True
    return [args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE][-1]


def _hold_first_load(store):
    """Holds the first ``store.get`` (a dream step's parent load) until released; later loads pass through."""
    original = store.get
    entered, release = asyncio.Event(), asyncio.Event()
    loads = 0

    async def get(procedure_id):
        nonlocal loads
        loads += 1
        if loads == 1:
            entered.set()
            await release.wait()
        return await original(procedure_id)

    return get, entered, release


@pytest.mark.asyncio
async def test_overlapping_completions_of_one_procedure_make_one_evolution_attempt(tmp_path) -> None:
    """Finding 2 (review round 2): the 72 h window was checked before the confirmation ``await`` and recorded after
    it, so two agents' overlapping completions both passed it (two confirmation calls; ``runtime.py:1987`` runs
    each listener as its own task). E9's bound is now enforced."""
    r = await _store_rig(tmp_path, 0.3, 4)
    try:
        await _degrade(r)
        second = ReplayTestAgent(llm_client=MockLLMClient(), runtime=r.runtime)
        r.runtime.trust_network.create_with_prior(second.id, alpha=3.0, beta=7.0)
        payloads = [await _guided_completion(r, r.agent), await _guided_completion(r, second)]
        assert {payload["agent_id"] for payload in payloads} == {r.agent.id, second.id}  # premise: two cooldowns
        llm = _ConfirmationLLM(hold=True)
        engine = _constructed_dreaming_engine(r, llm)

        tasks = [asyncio.create_task(engine.on_task_execution_complete(payload)) for payload in payloads]

        async def settled() -> None:  # one attempt in flight and the other refused, or both in flight
            while not (sum(task.done() for task in tasks) == 1 or llm.confirmations() == 2):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(settled(), timeout=10)
        llm.release.set()
        await asyncio.gather(*tasks)

        assert llm.confirmations() == 1
    finally:
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["7b", "7d"])
async def test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again(tmp_path, step) -> None:
    """Finding 2 (review round 2): Step 7b (``_evolve_degraded_procedures``) and Step 7d
    (``_process_fallback_learning``) checked the window, then awaited the parent load before recording it, so a
    completion delivered meanwhile passed the same check. They now claim it first, as the reactive path does."""
    r = await _store_rig(tmp_path, 0.3, 4)
    try:
        await _degrade(r)
        payload = await _guided_completion(r, r.agent)
        llm = _ConfirmationLLM()
        engine = _constructed_dreaming_engine(r, llm)
        get, entered, release = _hold_first_load(r.store)
        with patch.object(r.store, "get", new=get):
            if step == "7b":
                dream = asyncio.create_task(engine._evolve_degraded_procedures([], []))
            else:
                await engine.on_procedure_fallback_learning({
                    "procedure_id": r.proc.id, "fallback_type": "execution_failure", "intent_type": "test_intent",
                    "llm_response": "recovered", "rejection_reason": "chosen failure", "correlation_id": "",
                })
                dream = asyncio.create_task(engine._process_fallback_learning())
            await asyncio.wait_for(entered.wait(), timeout=10)  # the dream step passed the window and is loading
            await engine.on_task_execution_complete(payload)
            release.set()
            await asyncio.wait_for(dream, timeout=10)

        assert llm.confirmations() == 0
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_fallback_reaches_step_7d_when_ships_records_is_disabled(tmp_path) -> None:
    """Finding 3 (review round 2): the fallback queue was created in ``set_records_store``, which startup skips when
    Ship's Records is disabled (``startup/finalize.py:5417-5418``), so a real fallback was dropped with
    ``AttributeError``. The engine here is built by its constructor alone, as startup leaves it then."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        intent = _make_intent(target_agent_id=r.agent.id)
        actions = AsyncMock(side_effect=[
            {"success": False, "error": "chosen replay failure"}, {"success": True, "result": "recovered"},
        ])
        with patch.object(
            r.agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda _intent, observation: observation),
        ), patch.object(r.agent, "_store_action_episode", new=AsyncMock()), \
                patch.object(r.agent, "act", new=actions), \
                patch.object(r.agent, "_run_llm_fallback", new=AsyncMock(return_value={"action": "execute", "llm_output": "recovered"})):
            result = await r.agent.handle_intent(intent)
        assert result is not None and result.success is True  # premise: the replay failed and the LLM recovered
        payloads = [args[1] for args in r.events if args[0] is EventType.PROCEDURE_FALLBACK_LEARNING]
        assert [payload["fallback_type"] for payload in payloads] == ["execution_failure"]
        engine = _constructed_dreaming_engine(r, _ConfirmationLLM())

        await engine.on_procedure_fallback_learning(payloads[0])
        stats = await engine._process_fallback_learning()

        assert stats["processed"] == 1
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_step_7e_runs_when_ships_records_is_disabled() -> None:
    """Finding 3 (review round 2): the observed-thread set was created in the same setter, so Step 7e raised
    ``AttributeError`` on its first thread when Ship's Records is disabled."""
    engine = DreamingEngine(
        router=SimpleNamespace(), trust_network=TrustNetwork(), episodic_memory=SimpleNamespace(),
        config=DreamingConfig(), llm_client=_ConfirmationLLM(), procedure_store=SimpleNamespace(),
        ward_room=SimpleNamespace(browse_threads=AsyncMock(
            return_value=[SimpleNamespace(id="thread-bf924", channel_name="dm:captain")],
        )),
        agent_id="observer-bf924",
    )

    stats = await engine._process_observational_learning()

    assert stats == {"observed": 0, "scanned": 1}  # a DM thread is scanned and skipped (the teaching path)


# --- A4 (review round 3): every result of a Level 3 to 5 replay reaches AD-535's accounting once -----------

_STEP_POOL = "bf924-step-worker"


async def _compound_rig(
    tmp_path, level: int, step_reply: LLMResponse, *, score: float = 0.5, approved: bool = False,
) -> SimpleNamespace:
    """A stored two-step compound procedure at ``level`` whose steps reach a real target agent through a real
    ``IntentBus`` and ``AgentRegistry``, as the reviewer's probe built it (review round 3).

    Only the agent's ``OpenAICompatibleClient.complete`` is replaced (by ``_compound_run``): the overall validation
    (100 tokens) answers YES, each step validation (50 tokens) gets ``step_reply``, and any other request (a Guided
    or recovery decision) is an ordinary LLM decision. The client is never contacted.
    """
    r = await _store_rig(tmp_path, score, level)
    r.client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    r.agent._llm_client = r.client  # replaced after construction, as the probe did
    r.bus, registry = IntentBus(SignalManager()), AgentRegistry()
    r.runtime.intent_bus, r.runtime.registry = r.bus, registry
    r.target = ReplayTestAgent(llm_client=MockLLMClient(), runtime=r.runtime, pool=_STEP_POOL)
    r.target.state = AgentState.ACTIVE
    await registry.register(r.target)
    r.bus.subscribe(r.target.id, r.target.handle_intent, intent_names=["compound_step_replay"])
    r.proc.steps = [
        ProcedureStep(
            step_number=n, action=f"perform operation {n}", expected_output=f"operation {n} complete",
            agent_role=_STEP_POOL, resolved_agent_type=_STEP_POOL,
        )
        for n in (1, 2)
    ]
    await r.store.save(r.proc)
    if approved:  # after the re-save, as the Captain approves a stored procedure
        await r.store.approve_promotion(r.proc.id, "captain", "directive-bf924")
    r.requests, r.delivered = [], []
    send_original = r.bus.send

    async def send(intent, **kwargs):
        r.delivered.append(intent)
        return await send_original(intent, **kwargs)

    async def complete(request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        r.requests.append(request)
        if request.max_tokens == 50:
            return step_reply
        if request.max_tokens == 100:
            return LLMResponse(content="YES")
        return LLMResponse(content="an LLM decision")

    r.send, r.complete = send, complete
    return r


async def _compound_run(r) -> SimpleNamespace:
    """One matched intent through ``handle_intent``, and what the client, the bus, the store and the events saw."""
    calls, deliveries = len(r.requests), len(r.delivered)
    with patch.object(r.client, "complete", new=r.complete), patch.object(r.bus, "send", new=r.send):
        result = await _handle_on_store(r.agent)
    turn = r.requests[calls:]
    metrics = await r.store.get_quality_metrics(r.proc.id)
    loaded = await r.store.get(r.proc.id)
    return SimpleNamespace(
        result=result, level=loaded.compilation_level, consecutive=metrics["consecutive_successes"],
        completions=metrics["total_completions"], fallbacks=metrics["total_fallbacks"],
        delivered=len(r.delivered) - deliveries,
        validations=[request.max_tokens for request in turn if request.max_tokens in (50, 100)],
        ordinary=sum(request.max_tokens not in (50, 100) for request in turn),
        event=[args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE][-1],
    )


def _fallback_events(r) -> list[dict]:
    return [args[1] for args in r.events if args[0] is EventType.PROCEDURE_FALLBACK_LEARNING]


async def _close_compound_rig(r) -> None:
    r.bus.unsubscribe(r.target.id)
    await r.client.close()
    await r.store.stop()


@pytest.mark.asyncio
async def test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers(tmp_path) -> None:
    """Finding 1 (review round 3): the step validator's NO returned ``compound_aborted``, which the lifecycle
    ignored: it ran ``act()`` on the unchanged cached decision, reported success and counted it toward promotion
    (three rejections reached Level 4). A rejected step is now a failed replay: no ``act()`` on the replay,
    ``record_fallback``, AD-535's demotion and AD-534b's service recovery, whose event names the step."""
    r = await _compound_rig(tmp_path, 3, LLMResponse(content="NO"))
    try:
        run = await _compound_run(r)

        assert (run.delivered, run.validations) == (1, [100, 50])  # premise: step 1 ran and its validator said NO
        assert run.ordinary == 1  # the service recovery's LLM decision
        assert run.result is not None and run.result.success is True
        assert "[Procedure Replay" not in str(run.result.result)  # the recovered answer, not the rejected replay
        assert (run.completions, run.fallbacks) == (0, 1)
        assert (run.level, run.consecutive) == (2, 0)
        assert (run.event["used_procedure"], run.event["success"]) == (True, True)
        assert [
            (event["fallback_type"], event["procedure_id"], event["rejection_reason"]) for event in _fallback_events(r)
        ] == [("execution_failure", r.proc.id, "Compound step 1 output failed Level 3 validation")]
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_rejected_compound_step_without_recovery_fails_and_never_acts_on_the_replay(tmp_path) -> None:
    """Finding 1 (review round 3): when the recovery yields no decision, the intent fails with the step named, and
    ``act()`` never runs on the rejected replay (it ran once, and reported success, before A4)."""
    r = await _compound_rig(tmp_path, 3, LLMResponse(content="NO"))
    try:
        act = AsyncMock(wraps=r.agent.act)
        with patch.object(r.agent, "act", new=act), \
                patch.object(r.agent, "_run_llm_fallback", new=AsyncMock(return_value=None)):
            run = await _compound_run(r)

        assert (run.delivered, run.validations) == (1, [100, 50])  # premise: step 1 ran and its validator said NO
        assert act.await_count == 0
        assert run.result is not None and run.result.success is False
        assert run.result.error == "Compound step 1 output failed Level 3 validation"
        assert (run.completions, run.fallbacks, run.level) == (0, 1, 2)
        assert (run.event["used_procedure"], run.event["success"]) == (True, False)
        assert _fallback_events(r) == []  # AD-534b emits the learning event only for a recovered run
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step_reply",
    [LLMResponse(content="YES"), LLMResponse(content="", error="All LLM tiers unavailable")],
    ids=["yes", "error-reply"],
)
async def test_dispatched_compound_replays_count_toward_promotion_once_per_run(tmp_path, step_reply) -> None:
    """Finding 2 (review round 3): a dispatched compound replay recorded its completion and returned before
    AD-535's promotion step, so it never counted a success: the procedure stayed at Level 3, paying three
    validation calls a run. A failed step-validation call passes by default (AD-535), so it counts as YES does."""
    r = await _compound_rig(tmp_path, 3, step_reply)
    try:
        runs = [await _compound_run(r) for _ in range(COMPILATION_PROMOTION_THRESHOLD + 1)]

        assert all((run.delivered, run.ordinary) == (2, 0) for run in runs)  # premise: every step dispatched
        assert all(run.result is not None and run.result.success is True for run in runs)
        assert [(run.level, run.consecutive) for run in runs] == [(3, 1), (3, 2), (4, 0), (4, 1)]
        assert [run.validations for run in runs] == [[100, 50, 50]] * 3 + [[]]  # Level 4 makes no validation call
        assert [run.completions for run in runs] == [1, 2, 3, 4]  # the compound branch's own write, once a run
        assert sum(args[0] is EventType.TASK_EXECUTION_COMPLETE for args in r.events) == 4
        assert all(run.event.get("compound_dispatched") is True for run in runs)
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_commanders_approved_compound_procedure_reaches_level_5(tmp_path) -> None:
    """Finding 2 at Level 4 (review round 3): the same early return kept an approved compound procedure from
    AD-536's Level 5, which a single-step procedure reaches after three successes."""
    r = await _compound_rig(tmp_path, 4, LLMResponse(content="YES"), score=0.7, approved=True)
    try:
        assert r.runtime.trust_network.get_score(r.agent.id) >= TRUST_COMMANDER  # premise: Commander trust
        runs = [await _compound_run(r) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all((run.delivered, run.validations, run.ordinary) == (2, [], 0) for run in runs)  # premise: Level 4
        assert [run.level for run in runs] == [4, 4, 5]
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_level_3_no_demotes_the_procedure_and_resets_its_count(tmp_path) -> None:
    """D22 (A4): a NO hands the intent to the LLM (D15) and left the count untouched, so three YES answers that
    were not consecutive still promoted. AD-535 demotes on any failure and resets the count; the near-miss event
    and the completion event's ``used_procedure`` (D9) are unchanged."""
    r, client, complete = await _level_3_rig(tmp_path, LLMResponse(content="NO: nothing was checked"))
    try:
        for _ in range(COMPILATION_PROMOTION_THRESHOLD - 1):
            await r.store.record_consecutive_success(r.proc.id)
        with patch.object(client, "complete", complete):
            result = await _handle_on_store(r.agent)

        assert result is not None and result.success is True  # the LLM served the intent
        assert complete.await_count == 2  # premise: the validation request, then the LLM decision
        loaded = await r.store.get(r.proc.id)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert (loaded.compilation_level, metrics["consecutive_successes"]) == (2, 0)
        assert [
            args[1]["used_procedure"] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE
        ] == [False]
        assert [event["fallback_type"] for event in _fallback_events(r)] == ["validation_failure"]
    finally:
        await client.close()
        await r.store.stop()
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

from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.types import LLMResponse
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

Pair 5 (A2, D10: the level `get` returns after a promotion):

SEARCH:
````python
        await store.promote_compilation_level(proc_id, 3)
        proc = await store.get(proc_id)
        # Note: promote updates DB, not the cached Procedure object in get()
        # Check DB directly
        metrics = await store.get_quality_metrics(proc_id)
````
REPLACE:
````python
        await store.promote_compilation_level(proc_id, 3)
        proc = await store.get(proc_id)
        # BF-924 (#1654): promote writes the snapshot get() rebuilds from as well as the column. It wrote only the
        # column (the note here said so), so dispatch, the next promotion step and the teaching gate never saw it.
        assert proc is not None and proc.compilation_level == 3
        metrics = await store.get_quality_metrics(proc_id)
````

Pair 6 (A3, D15: the validator double has the real interface; mirrors A3-10):

SEARCH:
````python
# ===========================================================================
# TestLevel3Validated (10 tests)
````
REPLACE:
````python
def _validator_client(**complete: Any) -> MagicMock:
    """BF-924 (#1654): an LLM client double with the real interface only (``spec=BaseLLMClient``).

    The validators called ``generate``, which no client has; the ``AsyncMock`` doubles here invented it, so
    every validation test passed while production passed every Level 3 replay unvalidated. ``complete`` is
    the client's method; any other name raises ``AttributeError`` as it does in production.
    """
    client = MagicMock(spec=BaseLLMClient)
    client.complete = AsyncMock(**complete)
    return client


# ===========================================================================
# TestLevel3Validated (10 tests)
````

Pair 7 (A3, D15: the replay validator tests use the real interface; mirrors A3-11):

SEARCH:
````python
    @pytest.mark.asyncio
    async def test_validation_timeout_passes(self):
        """Timeout → passes by default (fail-open)."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=asyncio.TimeoutError())
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["something"])
        result = await agent._validate_replay_postconditions(proc, "output", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_validation_includes_postconditions(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES looks good")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["all widgets created"])
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "all widgets created" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_step_expected_outputs(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, expected_output="file exists")]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "file exists" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_invariants(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, invariants=["no data loss"])]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "no data loss" in prompt
````
REPLACE:
````python
    @pytest.mark.asyncio
    async def test_validation_timeout_passes(self):
        """Timeout → passes by default (fail-open)."""
        llm_client = _validator_client(side_effect=asyncio.TimeoutError())
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["something"])
        result = await agent._validate_replay_postconditions(proc, "output", {})
        assert llm_client.complete.await_count == 1  # BF-924: the call reached the client's real interface
        assert result is True

    @pytest.mark.asyncio
    async def test_validation_includes_postconditions(self):
        llm_client = _validator_client(return_value=LLMResponse(content="YES looks good"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["all widgets created"])
        await agent._validate_replay_postconditions(proc, "output", {})
        assert llm_client.complete.await_count == 1
        prompt = llm_client.complete.await_args.args[0].prompt
        assert "all widgets created" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_step_expected_outputs(self):
        llm_client = _validator_client(return_value=LLMResponse(content="YES"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, expected_output="file exists")]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        assert llm_client.complete.await_count == 1
        prompt = llm_client.complete.await_args.args[0].prompt
        assert "file exists" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_invariants(self):
        llm_client = _validator_client(return_value=LLMResponse(content="YES"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, invariants=["no data loss"])]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        assert llm_client.complete.await_count == 1
        prompt = llm_client.complete.await_args.args[0].prompt
        assert "no data loss" in prompt
````

Pair 8 (A3, D15: the step validator tests use the real interface; an error reply; mirrors A3-12):

SEARCH:
````python
    @pytest.mark.asyncio
    async def test_validate_step_postcondition_passes(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES matches")
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "data processed successfully")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_postcondition_fails(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="NO doesn't match")
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "error occurred")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_step_no_expected_output(self):
        agent = _make_cognitive_agent()
        step = _FakeStep(expected_output="")
        result = await agent._validate_step_postcondition(step, "anything")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_llm_failure_passes(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=Exception("LLM down"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="something")
        result = await agent._validate_step_postcondition(step, "output")
        assert result is True  # Fail-open
````
REPLACE:
````python
    @pytest.mark.asyncio
    async def test_validate_step_postcondition_passes(self):
        llm_client = _validator_client(return_value=LLMResponse(content="YES matches"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "data processed successfully")
        assert llm_client.complete.await_count == 1  # BF-924: the call reached the client's real interface
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_postcondition_fails(self):
        llm_client = _validator_client(return_value=LLMResponse(content="NO doesn't match"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "error occurred")
        assert llm_client.complete.await_count == 1
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_step_no_expected_output(self):
        agent = _make_cognitive_agent()
        step = _FakeStep(expected_output="")
        result = await agent._validate_step_postcondition(step, "anything")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_llm_failure_passes(self):
        llm_client = _validator_client(side_effect=Exception("LLM down"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="something")
        result = await agent._validate_step_postcondition(step, "output")
        assert llm_client.complete.await_count == 1
        assert result is True  # Fail-open

    @pytest.mark.asyncio
    async def test_validate_step_error_reply_passes(self):
        """BF-924 (#1654): the client returns an error reply rather than raising (``llm_client.py:2092``); AD-535
        passes a failed validation call by default, so an error reply is not a NO."""
        llm_client = _validator_client(return_value=LLMResponse(content="", error="All LLM tiers unavailable"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="something")
        result = await agent._validate_step_postcondition(step, "output")
        assert llm_client.complete.await_count == 1
        assert result is True  # Fail-open
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

### 7.4a `src/probos/cognitive/procedure_store.py` (M1, A2, D10: promotion and demotion reach `get`)

Pair 1 (promotion):

SEARCH:
````python
    async def promote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Promote procedure to a higher compilation level. Reset consecutive_successes."""
        if not self._db:
            return
        async with self._index_write():
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "updated_at = ? WHERE id = ?",
                (new_level, time.time(), procedure_id),
            )
````
REPLACE:
````python
    async def promote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Promote procedure to a higher compilation level. Reset consecutive_successes.

        BF-924 (#1654): the level goes to the column and to the JSON snapshot in one statement, as
        ``decay_stale_procedures`` writes both. ``get`` rebuilds a procedure from the snapshot, and the
        dispatch, the next promotion step and the teaching gate read its level: the column-only write
        left every promotion invisible to them. The other counters are not touched (no re-save).
        """
        if not self._db:
            return
        async with self._index_write():
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "content_snapshot = json_set(content_snapshot, '$.compilation_level', ?), "  # BF-924: promote
                "updated_at = ? WHERE id = ?",
                (new_level, new_level, time.time(), procedure_id),
            )
````

Pair 2 (demotion):

SEARCH:
````python
    async def demote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Demote procedure to a lower compilation level. Reset consecutive_successes."""
        if not self._db:
            return
        async with self._index_write():
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "updated_at = ? WHERE id = ?",
                (new_level, time.time(), procedure_id),
            )
````
REPLACE:
````python
    async def demote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Demote procedure to a lower compilation level. Reset consecutive_successes.

        BF-924 (#1654): the level goes to the column and to the JSON snapshot in one statement, as
        ``decay_stale_procedures`` writes both. ``get`` rebuilds a procedure from the snapshot and the
        dispatch reads its level: the column-only write left a demoted procedure dispatched at its old
        level. The other counters are not touched (no re-save).
        """
        if not self._db:
            return
        async with self._index_write():
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "content_snapshot = json_set(content_snapshot, '$.compilation_level', ?), "  # BF-924: demote
                "updated_at = ? WHERE id = ?",
                (new_level, new_level, time.time(), procedure_id),
            )
````

### 7.4b `tests/test_ad1326_procedure_ledger.py` (M1, A2, D10: a premise built through the column-only demote)

Pair 1 (the helper's docstring):

SEARCH:
````python
    An independent reader of ``procedures.db``. ``restore_procedure`` commits the columns and swallows a refused
    ``content_snapshot`` UPDATE, and ``demote_compilation_level`` writes the column only; both leave the snapshot that
    ``ProcedureStore.get`` rebuilds a procedure from apart from the columns.
````
REPLACE:
````python
    An independent reader of ``procedures.db``. ``restore_procedure`` commits the columns and swallows a refused
    ``content_snapshot`` UPDATE, which leaves the snapshot that ``ProcedureStore.get`` rebuilds a procedure from
    apart from the columns. (``demote_compilation_level`` wrote the column only until BF-924 made it write both.)
````

Pair 2 (the premise):

SEARCH:
````python
        await store.demote_compilation_level("p", 1)  # the column only: the snapshot keeps saying level 4
````
REPLACE:
````python
        # BF-924 (#1654): demote_compilation_level now writes the snapshot too, so the premise is set as a row demoted
        # before BF-924 left it: the column at Level 1, the snapshot still at Level 4.
        await store._db.execute("UPDATE procedure_records SET compilation_level = 1 WHERE id = ?", ("p",))
        await store._db.commit()
````

### 7.4c `src/probos/cognitive/dreaming.py` (M1, A3, D17 and D18: the evolution window is claimed where it is checked; the fallback queue is the constructor's)

Pair 1 (D18: the constructor creates the fallback queue and the thread set; mirrors A3-4):

SEARCH:
````python
        self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check
````
REPLACE:
````python
        self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check
        # BF-924 (#1654): created here, not in set_records_store(), which startup skips when Ship's Records is
        # disabled (startup/finalize.py:5417-5418); neither the fallback queue nor Step 7e's thread set needs Records.
        self._fallback_learning_queue: list[dict[str, Any]] = []  # AD-534b: fallback evidence for dream-time processing
        self._observed_threads: set[str] = set()  # AD-537: already-observed thread IDs
````

Pair 2 (D18: the Records setter resets nothing; mirrors A3-5):

SEARCH:
````python
        if self._records_store is None:
            self._records_store = records_store
        self._fallback_learning_queue: list[dict[str, Any]] = []  # AD-534b: fallback evidence for dream-time processing
        self._observed_threads: set[str] = set()  # AD-537: already-observed thread IDs
````
REPLACE:
````python
        if self._records_store is None:
            self._records_store = records_store
````

Pair 3 (D17: Step 7b claims the window; mirrors A3-6):

SEARCH:
````python
            # Anti-loop guard: skip if addressed recently
            last_attempt = self._addressed_degradations.get(proc_id, 0.0)
            if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
                continue
````
REPLACE:
````python
            # Anti-loop guard: skip if addressed recently (BF-924: claimed before the parent load awaits)
            if not self._claim_evolution_attempt(proc_id, now):  # BF-924 (#1654): Step 7b
                continue
````

Pair 4 (D17: the claim helper; the reactive and proactive paths claim; mirrors A3-7):

SEARCH:
````python
    async def _attempt_procedure_evolution(
        self,
        parent: Any,  # Procedure
        diagnosis: str,
        metrics: dict[str, Any],
        require_confirmation: bool = False,
    ) -> bool:
        """Shared diagnosis+evolve logic for Step 7b and proactive scan.

        Returns True if evolution succeeded.
        """
        proc_id = parent.id
        now = time.time()

        # Anti-loop guard
        last_attempt = self._addressed_degradations.get(proc_id, 0.0)
        if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
            return False

        # LLM confirmation gate (proactive only)
````
REPLACE:
````python
    def _claim_evolution_attempt(self, proc_id: str, now: float) -> bool:
        """BF-924 (#1654): AD-532b's 72 h anti-loop window, checked and claimed in one step.

        No ``await`` separates the check from the claim, so two triggers that overlap (two agents' completions,
        each its own listener task, or a completion during the dream cycle) cannot both pass it. The exits after
        the claim record the attempt as before; an attempt that raises keeps the claim.
        """
        if now - self._addressed_degradations.get(proc_id, 0.0) < EVOLUTION_COOLDOWN_SECONDS:
            return False
        self._addressed_degradations[proc_id] = now  # BF-924 (#1654): claimed in the step that checked it
        return True

    async def _attempt_procedure_evolution(
        self,
        parent: Any,  # Procedure
        diagnosis: str,
        metrics: dict[str, Any],
        require_confirmation: bool = False,
    ) -> bool:
        """Shared diagnosis+evolve logic for Step 7b and proactive scan.

        Returns True if evolution succeeded.
        """
        proc_id = parent.id
        now = time.time()

        # Anti-loop guard (BF-924: claimed before the confirmation awaits)
        if not self._claim_evolution_attempt(proc_id, now):  # BF-924 (#1654): the reactive and proactive paths
            return False

        # LLM confirmation gate (proactive only)
````

Pair 5 (D17: Step 7d claims the window after its read-only check; mirrors A3-8):

SEARCH:
````python
                    continue

                # Load procedure
                parent = await self._procedure_store.get(proc_id)
                if not parent or not parent.is_active:
                    continue
````
REPLACE:
````python
                    continue

                # BF-924 (#1654): claim the window before the first await. The check above stays read-only, so a
                # negative_veto inside the window is still counted as skipped and flags nothing, as before.
                self._addressed_degradations[proc_id] = now  # BF-924 (#1654): Step 7d claims it before its first await

                # Load procedure
                parent = await self._procedure_store.get(proc_id)
                if not parent or not parent.is_active:
                    continue
````

### 7.4d `tests/test_ad1326_dreaming_challenger.py` (M1, A3, D18: the Records setter comment)

Pair 1 (mirrors A3-16):

SEARCH:
````python
    engine = DreamingEngine(router, trust, memory, config, **kwargs)
    # Startup binds the records store late (startup/finalize.py), and the fallback-learning queue and the
    # observed-thread set are created inside that setter, not in ``__init__``: a bare engine has no queue for
    # Step 7d to drain. Binding it the way startup does keeps the engine as production builds it.
    engine.set_records_store(None)
````
REPLACE:
````python
    engine = DreamingEngine(router, trust, memory, config, **kwargs)
    # Startup binds the records store late (startup/finalize.py) when Ship's Records is enabled. BF-924 (#1654): the
    # fallback-learning queue and the observed-thread set are the constructor's now, not that setter's (startup
    # skipped it with Records disabled, and Step 7d then had no queue); binding it keeps the engine as startup does.
    engine.set_records_store(None)
````

### 7.4e `tests/test_ad1326_challenger_e2e.py` (M1, A3, D18: the Records setter comment)

Pair 1 (mirrors A3-17):

SEARCH:
````python
    w.engine.set_records_store(None)  # startup binds it, and with it the fallback queue that Step 7d drains
````
REPLACE:
````python
    w.engine.set_records_store(None)  # startup binds it with Records on; the queue Step 7d drains is the constructor's (BF-924)
````

### 7.4f `src/probos/cognitive/cognitive_agent.py` (M1, A4, D20 to D22: every replay outcome reaches AD-535's accounting once)

Pair 1 (D20: the abort result says what happened; mirrors A4-1):

SEARCH:
````python
                if not step_valid:
                    logger.info(
                        "Compound step %d validation failed — aborting compound replay",
                        step.step_number,
                    )
                    return {"success": True, "result": text_fallback, "compound_dispatched": False, "compound_aborted": True}
````
REPLACE:
````python
                if not step_valid:
                    logger.info(
                        "Compound step %d validation failed — aborting compound replay",
                        step.step_number,
                    )
                    # BF-924 (#1654): a rejected step is a failed replay; the lifecycle reads compound_aborted and
                    # failed_step (it never read this result's success, which said True).
                    return {
                        "success": False, "result": text_fallback, "compound_dispatched": False,
                        "compound_aborted": True, "failed_step": step.step_number,
                    }
````

Pair 2 (D22: a Level 3 NO demotes; mirrors A4-2):

SEARCH:
````python
            logger.info(
                "Level 3 validation failed for procedure %s — falling back to LLM",
                procedure.name,
            )
            return None
````
REPLACE:
````python
            logger.info(
                "Level 3 validation failed for procedure %s — falling back to LLM",
                procedure.name,
            )
            # BF-924 (#1654): a NO is a failed replay. AD-535 demotes on any failure and resets the count; the LLM
            # still serves the intent. Unreachable until D15: the validator never answered.
            await self._record_compilation_outcome(procedure.id, False)
            return None
````

Pair 3 (D21: the promotion step as one helper; mirrors A4-3):

SEARCH:
````python
        if promotion_status == "approved" and trust_score >= TRUST_COMMANDER:
            return 5  # Expert level unlocked for promoted procedures
        return base
````
REPLACE:
````python
        if promotion_status == "approved" and trust_score >= TRUST_COMMANDER:
            return 5  # Expert level unlocked for promoted procedures
        return base

    async def _record_compilation_outcome(self, procedure_id: str | None, success: bool) -> None:
        """AD-535: count a success toward promotion, or demote (else reset the count) on a failure.

        BF-924 (#1654): moved unchanged from ``handle_intent``'s post-execution step so that every replay outcome
        reaches it exactly once: that step, a dispatched compound replay (which returns before it) and a Level 3
        validation that answered NO (which hands the intent to the LLM, so no procedure reaches that step).
        """
        _proc_id_for_promo = procedure_id
        if _proc_id_for_promo and self._procedure_store:
            _store = self._procedure_store
            if success:
                try:
                    new_count = await _store.record_consecutive_success(_proc_id_for_promo)
                    from probos.config import (
                        COMPILATION_PROMOTION_THRESHOLD,
                        COMPILATION_MAX_LEVEL,
                    )
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = self._compilation_trust_score()  # BF-924 (#1654): the live trust, as in the clamp
                        # AD-536: Check if promoted procedure can reach Level 5
                        _promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                        max_allowed = self._max_compilation_level_for_promoted(_ts, _promo_status)
                        next_level = proc.compilation_level + 1
                        if next_level <= min(max_allowed, COMPILATION_MAX_LEVEL):
                            await _store.promote_compilation_level(_proc_id_for_promo, next_level)
                            logger.info(
                                "Procedure '%s' promoted to Level %d after %d consecutive successes",
                                proc.name, next_level, new_count,
                            )
                            # AD-536: Check if procedure is eligible for institutional promotion
                            from probos.config import PROMOTION_MIN_COMPILATION_LEVEL
                            promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                            if next_level >= PROMOTION_MIN_COMPILATION_LEVEL and promo_status == "private":
                                await self._request_procedure_promotion(_proc_id_for_promo)
                except Exception:
                    pass
            else:
                try:
                    from probos.config import COMPILATION_DEMOTION_LEVEL
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and proc.compilation_level > COMPILATION_DEMOTION_LEVEL:
                        await _store.demote_compilation_level(
                            _proc_id_for_promo, COMPILATION_DEMOTION_LEVEL
                        )
                        logger.info(
                            "Procedure '%s' demoted to Level %d after failure",
                            proc.name, COMPILATION_DEMOTION_LEVEL,
                        )
                    else:
                        await _store.reset_consecutive_successes(_proc_id_for_promo)
                except Exception:
                    pass
````

Pair 4 (D21: the post-execution step calls the helper; mirrors A4-4):

SEARCH:
````python
        # AD-535: Compilation level promotion/demotion
        _proc_id_for_promo = decision.get("procedure_id")
        if _proc_id_for_promo and self._procedure_store:
            _store = self._procedure_store
            if success:
                try:
                    new_count = await _store.record_consecutive_success(_proc_id_for_promo)
                    from probos.config import (
                        COMPILATION_PROMOTION_THRESHOLD,
                        COMPILATION_MAX_LEVEL,
                    )
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = self._compilation_trust_score()  # BF-924 (#1654): the live trust, as in the clamp
                        # AD-536: Check if promoted procedure can reach Level 5
                        _promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                        max_allowed = self._max_compilation_level_for_promoted(_ts, _promo_status)
                        next_level = proc.compilation_level + 1
                        if next_level <= min(max_allowed, COMPILATION_MAX_LEVEL):
                            await _store.promote_compilation_level(_proc_id_for_promo, next_level)
                            logger.info(
                                "Procedure '%s' promoted to Level %d after %d consecutive successes",
                                proc.name, next_level, new_count,
                            )
                            # AD-536: Check if procedure is eligible for institutional promotion
                            from probos.config import PROMOTION_MIN_COMPILATION_LEVEL
                            promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                            if next_level >= PROMOTION_MIN_COMPILATION_LEVEL and promo_status == "private":
                                await self._request_procedure_promotion(_proc_id_for_promo)
                except Exception:
                    pass
            else:
                try:
                    from probos.config import COMPILATION_DEMOTION_LEVEL
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and proc.compilation_level > COMPILATION_DEMOTION_LEVEL:
                        await _store.demote_compilation_level(
                            _proc_id_for_promo, COMPILATION_DEMOTION_LEVEL
                        )
                        logger.info(
                            "Procedure '%s' demoted to Level %d after failure",
                            proc.name, COMPILATION_DEMOTION_LEVEL,
                        )
                    else:
                        await _store.reset_consecutive_successes(_proc_id_for_promo)
                except Exception:
                    pass

        # AD-534b: Service recovery — re-run LLM on cached execution failure
````
REPLACE:
````python
        # AD-535: Compilation level promotion/demotion (BF-924 (#1654): one helper, shared with the compound and NO paths)
        await self._record_compilation_outcome(decision.get("procedure_id"), success)

        # AD-534b: Service recovery — re-run LLM on cached execution failure
````

Pair 5 (D21: a dispatched compound replay counts once; mirrors A4-5):

SEARCH:
````python
        # AD-534c: compound procedure dispatch
        if decision.get("compound") and decision.get("procedure"):
            compound_result = await self._execute_compound_replay(
                decision["procedure"], decision.get("llm_output", ""),
                compilation_level=decision.get("compilation_level", 4),
            )

            if compound_result.get("compound_dispatched"):
                # Record procedure completion (AD-534b metrics)
                _store = self._procedure_store
                if _store:
                    try:
                        await _store.record_completion(decision["procedure_id"])
                    except Exception:
                        pass
````
REPLACE:
````python
        # AD-534c: compound procedure dispatch
        _replay_failure: dict[str, Any] | None = None  # BF-924 (#1654): set when a compound step was rejected
        if decision.get("compound") and decision.get("procedure"):
            compound_result = await self._execute_compound_replay(
                decision["procedure"], decision.get("llm_output", ""),
                compilation_level=decision.get("compilation_level", 4),
            )

            if compound_result.get("compound_dispatched"):
                # Record procedure completion (AD-534b metrics)
                _store = self._procedure_store
                if _store:
                    try:
                        await _store.record_completion(decision["procedure_id"])
                    except Exception:
                        pass
                # BF-924 (#1654): the shared AD-535 accounting, which this early return skipped, so a compound
                # procedure never counted a success: it stalled at Level 3, paying its validation calls every run.
                await self._record_compilation_outcome(decision["procedure_id"], True)
````

Pair 6 (D20: a rejected step takes the cached-failure path, with no act(); mirrors A4-6):

SEARCH:
````python
            # Degradation: compound_dispatched=False — use text fallback in normal act() flow
            decision["llm_output"] = compound_result["result"]
            decision["compound"] = False  # prevent re-entry

        action_decision = (
            {**decision, "intent": "proactive_think"}
            if recreation_turn is not None else decision
        )
        result = await self.act(action_decision)
````
REPLACE:
````python
            if compound_result.get("compound_aborted"):
                # BF-924 (#1654): a step the Level 3 validator rejected is a failed replay, not a degradation: no
                # act() on the unchanged cached decision. The failure takes the cached-failure path below
                # (record_fallback, demotion, AD-534b's service recovery and its execution_failure event).
                _replay_failure = {
                    "success": False,
                    "error": f"Compound step {compound_result.get('failed_step')} output failed Level 3 validation",
                }
            # Degradation: compound_dispatched=False — use text fallback in normal act() flow
            decision["llm_output"] = compound_result["result"]
            decision["compound"] = False  # prevent re-entry

        action_decision = (
            {**decision, "intent": "proactive_think"}
            if recreation_turn is not None else decision
        )
        result = _replay_failure if _replay_failure is not None else await self.act(action_decision)
````

Pair 7 (D20: the learning event names the rejected step; mirrors A4-7):

SEARCH:
````python
                        self._last_fallback_info = {
                            "type": "execution_failure",
                            "procedure_id": _proc_id,
                            "procedure_name": _proc_name,
                            "reason": "Procedure replay succeeded in formatting but failed in execution",
                        }
````
REPLACE:
````python
                        self._last_fallback_info = {
                            "type": "execution_failure",
                            "procedure_id": _proc_id,
                            "procedure_name": _proc_name,
                            # BF-924 (#1654): a rejected compound step names itself; Step 7d's rewrite quotes the reason
                            "reason": (_replay_failure or {}).get("error") or "Procedure replay succeeded in formatting but failed in execution",
                        }
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

Pair 3 (A2, D12: import):

SEARCH:
````python
import logging
import time
from datetime import datetime, timezone
````
REPLACE:
````python
import logging
import math
import time
from datetime import datetime, timezone
````

Pair 4 (A2, D12: one formatter for grant times):

SEARCH:
````python
async def _grant_issue(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Issue a clearance grant: <callsign> <tier> [scope] [duration_hours] [reason...]."""
````
REPLACE:
````python
def _grant_time(timestamp: float) -> str | None:
    """BF-924 (#1654): a grant time as ``MM-DD HH:MM`` (UTC), or None when the platform cannot represent it.

    ``datetime.fromtimestamp`` raises OverflowError for an infinity and OSError (Windows) or ValueError for a
    finite time outside the platform's range; one such row made ``/grant list`` raise and hide every grant.
    """
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return None


async def _grant_issue(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Issue a clearance grant: <callsign> <tier> [scope] [duration_hours] [reason...]."""
````

Pair 5 (A2, D12: refuse a duration that cannot be an expiry):

SEARCH:
````python
    # Parse duration
    try:
        duration_hours = float(duration_hours_str)
    except ValueError:
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return
    expires_at = (time.time() + duration_hours * 3600) if duration_hours > 0 else None
````
REPLACE:
````python
    # Parse duration (BF-924: a duration that is not finite, or whose expiry cannot be shown as a date, is refused;
    # "nan" became a grant until revoked, and "inf" or a huge number stored an expiry that made /grant list raise)
    try:
        duration_hours = float(duration_hours_str)
    except ValueError:
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return
    expires_at = (time.time() + duration_hours * 3600) if duration_hours > 0 else None
    if not math.isfinite(duration_hours) or (expires_at is not None and _grant_time(expires_at) is None):
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return
````

Pair 6 (A2, D12: a row degrades on its own):

SEARCH:
````python
        issued_str = datetime.fromtimestamp(g.issued_at, tz=timezone.utc).strftime("%m-%d %H:%M")
        if g.expires_at:
            expires_str = datetime.fromtimestamp(g.expires_at, tz=timezone.utc).strftime("%m-%d %H:%M")
        else:
            expires_str = "—"
````
REPLACE:
````python
        # BF-924: a time the platform cannot show degrades in its own row; the status still reads the raw value
        issued_str = _grant_time(g.issued_at) or "out of range"
        if g.expires_at:
            expires_str = _grant_time(g.expires_at) or "out of range"
        else:
            expires_str = "—"
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
import math
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


async def _grant_then_list(
    tmp_path, *, with_identity: bool, issue: str = "issue Crusher full", stored_expiry: float | None = None,
):
    """Issue a grant and list grants through the real command, on real stores and registries.

    ``issue`` is the issue command's arguments. ``stored_expiry`` adds a second grant to the same target
    through the store itself, standing for a row stored before BF-924's duration check (A2, D12).
    """
    from rich.console import Console

    from probos.clearance_grants import ClearanceGrantStore
    from probos.crew_profile import CallsignRegistry
    from probos.earned_agency import RecallTier
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
        await cmd_grant(runtime, console, issue)
        if stored_expiry is not None:
            await store.issue_grant(
                target_agent_id=cert.agent_uuid, recall_tier=RecallTier.BASIC, expires_at=stored_expiry,
            )
        grants = await store.list_grants()
        await cmd_grant(runtime, console, "list")
    finally:
        await store.stop()
        await identity.stop()
    return slot, cert, grants, out.getvalue()


def _listed_table(output: str) -> str:
    """The grant table ``/grant list`` printed after the issue command's output; it must have printed one.

    A3 (review round 2, M2 finding 2): A2 split at the title with ``[-1]`` so the refused-issue cases, which print
    no table, would not raise; with no table that returned the issue command's own confirmation, which names the
    target too, so the live-callsign test passed with the table's print removed.
    """
    _before, title, table = output.partition("Clearance Grants")
    assert title, "/grant list printed no grant table"
    return table


@pytest.mark.asyncio
async def test_grant_list_names_the_target_by_its_live_callsign(tmp_path) -> None:
    slot, cert, grants, output = await _grant_then_list(tmp_path, with_identity=True)
    table = _listed_table(output)

    assert [grant.target_agent_id for grant in grants] == [cert.agent_uuid]  # _grant_issue stores the sovereign id
    assert cert.agent_uuid != slot
    assert "Crusher" in table
    assert "Wesley" not in table


@pytest.mark.asyncio
async def test_grant_list_without_an_identity_registry_shows_the_target_id(tmp_path) -> None:
    slot, _cert, grants, output = await _grant_then_list(tmp_path, with_identity=False)
    table = _listed_table(output)

    assert [grant.target_agent_id for grant in grants] == [slot]
    assert slot[:12] in table


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_expiry", [math.inf, 3.6e13], ids=["inf", "past-time_t"])
async def test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown(tmp_path, stored_expiry) -> None:
    """G1 (review round 1): one expiry ``datetime.fromtimestamp`` cannot convert made ``/grant list`` raise and
    hide every grant. The status still reads the raw value, so an infinite expiry is Active."""
    _slot, _cert, grants, output = await _grant_then_list(tmp_path, with_identity=True, stored_expiry=stored_expiry)
    table = _listed_table(output)

    assert len(grants) == 2  # premise: the command's grant and the stored one are both active
    assert "Crusher" in table
    assert "out of range" in table
    assert table.count("Active") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", ["inf", "nan", "1e13"])
async def test_grant_issue_refuses_a_duration_that_cannot_be_an_expiry(tmp_path, duration) -> None:
    """G1 (review round 1): ``inf`` and ``1e13`` hours stored an expiry the list could not show; ``nan`` (``nan > 0``
    is False) stored a grant until revoked."""
    _slot, _cert, grants, output = await _grant_then_list(
        tmp_path, with_identity=True, issue=f"issue Crusher full general {duration}",
    )

    assert grants == []
    assert f"Invalid duration: {duration}" in output


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

### 7.23 `scripts/gen_config_reference.py` (M2, A2, D14: import this checkout's models)

SEARCH:
````python
_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "development" / "config-reference.md"
````
REPLACE:
````python
_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "development" / "config-reference.md"
# BF-924 (#1654): document this checkout's models, as check_config_facade.py and check_config_profiles.py
# do. In a worktree, the venv's editable install otherwise resolves ``probos`` to another checkout.
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
````

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)`. The entries go in the tracker commit that follows M2's (the orchestrator applies them by tool, then regenerates the ledger). Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
````markdown
# ProbOS Progress
````
REPLACE:
````markdown
# ProbOS Progress

**BF-924 (2026-10-25), #1654 -- trust inputs are read through APIs that exist.** The AD-535/536 procedure-compilation clamp read a `_trust_score` attribute nothing sets, so every agent counted as a Lieutenant; it now reads the agent's live trust (`TrustNetwork.get_score`, as Rank does): Ensigns run stored Level 3 and 4 procedures as Guided (Level 2), a Commander's approved procedure can be promoted to Level 5, and an unreadable trust (a failed read, or a value that is not a score in [0, 1]) is held to Level 2 with a WARNING. Promotion and demotion now write the level `ProcedureStore.get` reads: they had moved only an index column, so dispatch, the next promotion step and the teaching gate never saw them. With the ladder working, Level 3 validation calls the LLM client's real interface (it called a method no client has, so every Level 3 replay passed unvalidated; a failed call still passes by default, now with a WARNING), a Lieutenant's procedure that reaches Level 4 requests institutional promotion posted as the agent itself, overlapping completions make at most one evolution attempt per procedure per 72 h, and fallback evidence reaches the dream cycle with Ship's Records disabled. Compound procedures graduate too: a dispatched compound replay counts toward promotion; a compound step the Level 3 validator rejects is a failed replay that the LLM recovers, with the procedure demoted to Guided; and a Level 3 NO demotes the procedure, as AD-535 specifies. `TrustNetwork.get_history` now exists, so the Captain's profile shows trust history and the avatar telemetry's `trust_delta` is real (the Captain's Self Image tab shows it with the modulated pitch and rule; the HXI's voice playback and VRM do not read it yet); both `hasattr` guards that hid its absence are removed. `/grant list` raised for any grant (`CallsignRegistry.list_all` never existed); it names a target through its birth certificate and live callsign and shows every row even when one time cannot be shown as a date; `/grant issue` refuses a duration that is not finite or whose expiry cannot be shown. The Counselor takes `CounselorConfig` by constructor injection and reads `trust_delta_threshold` and `sweep_max_agents` (defaults unchanged); `enabled`, `profile_retention_days`, `alert_on_red` and `alert_on_yellow` had no reader and are removed. New: `tests/test_bf924_compilation_trust.py`, `tests/test_bf924_trust_inputs.py`. The contract is `prompts/bf-924-trust-inputs-through-real-apis.md`.
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
- *Compilation levels persist where they are read.* `promote_compilation_level` and `demote_compilation_level` write the JSON snapshot `get` rebuilds a procedure from, in the same statement as the column, as decay already did; `get` is unchanged (AD-1326 D14). Before, promotions and demotions moved only the column, so AD-535's ladder and its demotion valve never changed dispatch. The completion event's `used_procedure` keeps its AD-532e meaning (a replay was used): a Guided run, clamped or stored, is an LLM run and enters the reactive check.
- *Level 3 validation and the evolution window.* Both validators call `complete(LLMRequest)` and read `LLMResponse.content`; they called `generate`, which no client has, so every Level 3 replay passed with no request. A failed call or an error reply still passes by default (AD-535), now with a WARNING: Level 4 replays the same procedure with no validation at all, and falling back would call the provider that just failed. AD-532b's 72 h window is claimed in the step that checks it, before the first `await`, on every path that reads it, so overlapping completions make one attempt; the dreaming engine creates its fallback queue and observed-thread set itself rather than in the Records setter. A promotion request is posted as the agent; routing it to a department chief is left to its own change.
- *Every replay outcome reaches the ladder once.* AD-535's promotion and demotion step is one helper with three callers: the post-execution step, a dispatched compound replay (which returns before that step) and a Level 3 NO (which hands the intent to the LLM). A compound step the validator rejects is a failed replay (`record_fallback`, demotion, AD-534b's recovery, an `execution_failure` event naming the step), not a degradation: other agents already ran the earlier steps. A step whose dispatch failed still degrades to its text and counts, as AD-534c designed. Rejected: letting the compound success fall through the shared path (it changes the compound event and adds episode and Ward Room effects); resetting the count without demoting on a NO (AD-535 demotes on any failure).
- *Trust history.* `TrustNetwork.get_history` maps the in-memory event log to scores, one owner of the mapping; the callers' `hasattr` guards, which hid its absence, are removed. Its consumers are the Captain's profile history, the backend avatar projection (which the Captain's Self Image tab displays: the delta, the pitch factor and the rule) and the crew context; the HXI's voice playback and VRM still use their own zero trust delta. The avatar divergence's trust write does not depend on it.
- *Grant list.* A grant's target is a sovereign id, so the list names it through the birth certificate and the live callsign, not a callsign list. A time the platform cannot show as a date degrades to "out of range" in its own row, and the issue command refuses a duration that would store one.
- *Counselor config.* Two fields are read, with defaults equal to the constants they replace; the four unread fields are removed rather than wired. Today's Bridge alerts follow no single red/yellow rule, so wiring `alert_on_*` would either silence alerts or invent them; an alert-silencing switch is the Captain's call. Unknown keys are ignored, so old configs load.
- *Reversal.* Revert the commits; the clamp returns to 0.5 for every agent, the history to empty, the grant list to raising, promotion and demotion to the column only, Level 3 validation to passing unvalidated, the evolution window to check-then-record, the fallback queue to the Records setter, compound replays to uncounted successes and accepted step rejections, a Level 3 NO to no demotion, and the config to unread.

### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)
````

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916, BF-921 and BF-923 precedent).

**#1654 checklist text** (the orchestrator records it on the issue):
- [ ] (F02) The clamp and the promotion step read live trust; Ensign capped at Level 2, Commander reaches Level 5, an unreadable trust held to Level 2 (M1). A2: a value outside [0, 1] counts as unreadable; promotion and demotion reach `ProcedureStore.get` (D10). A3: Level 3 validation calls the real client (D15); a promotion request is posted as the agent (D16); one evolution attempt per procedure per 72 h under overlapping completions (D17); fallback evidence kept with Records off (D18). A4: compound replays reach the AD-535 accounting (a rejected step is a failed replay; a dispatched success counts), and a Level 3 NO demotes (D20 to D22).
- [ ] (F02) The read-only count before the build posted (D4).
- [ ] (F04) `TrustNetwork.get_history`; profile history and avatar `trust_delta` real; the doubles pinned by a seam test (M2).
- [ ] (F05) `/grant list` works with grants present, through the real registries (M2). A2: every row, including a stored expiry the platform cannot show; `/grant issue` refuses such a duration.
- [ ] (F10) `trust_delta_threshold` and `sweep_max_agents` read; four fields removed; config reference and facade baseline regenerated (M2).
- [ ] First live session after merge: section 16's counts recorded on #1654.

## 9. What this does NOT change

- `_max_compilation_level_for_trust`, `_max_compilation_level_for_promoted`, the compilation thresholds (`config.py:266-275`), the dispatch levels and the demotion rule are unchanged. The procedure store changes only in `promote_compilation_level` and `demote_compilation_level`, which also write the snapshot's level (A2, D10); `get`, `save`, the semantic index, `_migrate_qualifying_procedures` and the rows whose column and snapshot already differ are unchanged (R10). The `TASK_EXECUTION_COMPLETE` payload is unchanged (D9). Dreaming changes only in claiming AD-532b's window in the step that checks it (D17) and in creating its fallback queue and observed-thread set in its constructor (D18); the cooldowns, the confirmation gate, the evolution functions and every recorded outcome are unchanged. The Level 3 validators change only their call (D15): the prompts, the timeout, the token limits and AD-535's fail-open rule are unchanged. AD-536's approver routing, the promotion eligibility rules and `_teach_procedure` are unchanged (R17, R18). A4: the promotion and demotion step moves unchanged into `_record_compilation_outcome` (three callers; the demotion rule is unchanged and now also applies to a Level 3 NO, D22); `_execute_compound_replay`'s resolution, dispatch, degradation and validation, both validators, the thresholds, AD-534b's recovery, the compound branch's completion write, event and result, and every event payload's shape are unchanged; the abort result now says `success: False` and carries `failed_step`.
- The other live-trust reads in `CognitiveAgent` (`:2870`, `:3351`, `:6042`, `:6230`, `:9123`, `:11455`) are not consolidated (R1).
- `TrustNetwork`'s event log, its size and its persistence are unchanged; `get_events_for_agent` and `standing_interests.py:701` are unchanged.
- The avatar modulation rules, thresholds and divergence logic are unchanged; no `ui/` file is touched (A2, A3: the HXI's voice playback and VRM keep their own zero trust delta, R11; the Self Image tab already renders the backend snapshot, D13 as corrected).
- `CallsignRegistry`, the identity registry, `ClearanceGrantStore` and `_grant_revoke` are unchanged; `_grant_issue` changes only in refusing a duration that is not finite or whose expiry cannot be shown (A2, D12).
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
| R3 | 1 | `src/probos/cognitive/cognitive_agent.py` | `score = float(self._runtime.trust_network.get_score(self.id))` (A2) | `score = 0.5` | the Ensign and Commander tests |
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
| R17 | 1 | `src/probos/cognitive/cognitive_agent.py` | `if not 0.0 <= score <= 1.0:  # BF-924 (#1654): NaN fails both bounds, so it is refused too` | `if False:` | `test_a_trust_that_is_not_a_score_is_held_to_level_2_and_warned` (3 cases), `test_an_infinite_trust_does_not_promote_an_approved_procedure_to_level_5` |
| R18 | 1 | `src/probos/cognitive/procedure_store.py` | `"content_snapshot = json_set(content_snapshot, '$.compilation_level', ?), "  # BF-924: promote` | `"content_snapshot = json_set(content_snapshot, '$.bf924_mutant', ?), "  # BF-924: promote` | `test_a_commanders_promotion_to_level_5_reaches_get_and_the_teaching_route`, `TestConsecutiveSuccessTracking::test_promote_compilation_level` |
| R19 | 1 | `src/probos/cognitive/procedure_store.py` | `"content_snapshot = json_set(content_snapshot, '$.compilation_level', ?), "  # BF-924: demote` | `"content_snapshot = json_set(content_snapshot, '$.bf924_mutant', ?), "  # BF-924: demote` | `test_a_demoted_procedure_is_dispatched_at_its_demoted_level` |
| R20 | 1 | `src/probos/cognitive/cognitive_agent.py` | `"used_procedure": decision.get("cached", False),` | `"used_procedure": decision.get("cached", False) or decision.get("guided_by_procedure", False),` | `test_a_clamped_guided_run_reaches_the_reactive_trigger_as_a_stored_level_2_run_does[ensign-clamped-to-guided]`, `[lieutenant-stored-guided]` |
| R21 | 2 | `src/probos/experience/commands/commands_clearance.py` | `except (OverflowError, OSError, ValueError):` | `except ZeroDivisionError:` | `test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown` (both cases) |
| R22 | 2 | `src/probos/experience/commands/commands_clearance.py` | `if not math.isfinite(duration_hours) or (expires_at is not None and _grant_time(expires_at) is None):` | `if False:` | `test_grant_issue_refuses_a_duration_that_cannot_be_an_expiry` (3 cases) |
| R23 | 2 | `src/probos/experience/commands/commands_clearance.py` | `expires_str = _grant_time(g.expires_at) or "out of range"` | `expires_str = datetime.fromtimestamp(g.expires_at, tz=timezone.utc).strftime("%m-%d %H:%M")` | `test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown` (both cases) |
| R24 | 2 | `src/probos/experience/commands/commands_clearance.py` | `console.print(table)` | `pass` | `test_grant_list_names_the_target_by_its_live_callsign`, `test_grant_list_without_an_identity_registry_shows_the_target_id`, `test_grant_list_shows_every_row_when_one_expiry_cannot_be_shown[inf]`, `[past-time_t]` |
| R25 | 1 | `src/probos/cognitive/cognitive_agent.py` | `llm_client.complete(validation_request, priority=Priority.NORMAL),` | `llm_client.generate(validation_prompt, max_tokens=100),` | `test_a_level_3_replay_is_validated_through_the_client_interface[yes]`, `[no]`, `test_a_failed_level_3_validation_call_passes_by_default_and_warns[raises]`, `[error-reply]`, `test_validation_includes_postconditions` |
| R26 | 1 | `src/probos/cognitive/cognitive_agent.py` | `if response.error is not None:  # BF-924 (#1654): an error reply is a failed call; AD-535 passes it by default` | `if False:` | `test_a_failed_level_3_validation_call_passes_by_default_and_warns[error-reply]` |
| R27 | 1 | `src/probos/cognitive/cognitive_agent.py` | `llm_client.complete(step_request, priority=Priority.NORMAL),` | `llm_client.generate(prompt, max_tokens=50),` | `test_validate_step_postcondition_passes`, `test_validate_step_postcondition_fails`, `test_validate_step_llm_failure_passes`, `test_validate_step_error_reply_passes` |
| R28 | 1 | `src/probos/cognitive/cognitive_agent.py` | `if response.error is not None:  # BF-924 (#1654): an error reply is a failed step call; AD-535 passes it by default` | `if False:` | `test_validate_step_error_reply_passes` |
| R29 | 1 | `src/probos/cognitive/cognitive_agent.py` | `agent_id = self.id  # BF-924 (#1654): the author is the agent; no agent has an _agent_id attribute` | `agent_id = getattr(self, "_agent_id", agent_type)` | `test_a_lieutenants_promotion_to_level_4_requests_institutional_promotion_as_the_agent` |
| R30 | 1 | `src/probos/cognitive/cognitive_agent.py` | `callsign = self.callsign or agent_type  # BF-924 (#1654): no agent has a _callsign attribute` | `callsign = getattr(self, "_callsign", agent_type)` | `test_a_lieutenants_promotion_to_level_4_requests_institutional_promotion_as_the_agent` |
| R31 | 1 | `src/probos/cognitive/dreaming.py` | `self._addressed_degradations[proc_id] = now  # BF-924 (#1654): claimed in the step that checked it` | `pass` | `test_overlapping_completions_of_one_procedure_make_one_evolution_attempt`, `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7b]` |
| R32 | 1 | `src/probos/cognitive/dreaming.py` | `if not self._claim_evolution_attempt(proc_id, now):  # BF-924 (#1654): Step 7b` | `if False:` | `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7b]` |
| R33 | 1 | `src/probos/cognitive/dreaming.py` | `if not self._claim_evolution_attempt(proc_id, now):  # BF-924 (#1654): the reactive and proactive paths` | `if False:` | `test_overlapping_completions_of_one_procedure_make_one_evolution_attempt` |
| R34 | 1 | `src/probos/cognitive/dreaming.py` | `self._addressed_degradations[proc_id] = now  # BF-924 (#1654): Step 7d claims it before its first await` | `pass` | `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7d]` |
| R35 | 1 | `src/probos/cognitive/dreaming.py` | `self._fallback_learning_queue: list[dict[str, Any]] = []  # AD-534b: fallback evidence for dream-time processing` | `self._bf924_mutant_queue: list[dict[str, Any]] = []` | `test_a_fallback_reaches_step_7d_when_ships_records_is_disabled`, `test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again[7d]` |
| R36 | 1 | `src/probos/cognitive/dreaming.py` | `self._observed_threads: set[str] = set()  # AD-537: already-observed thread IDs` | `self._bf924_mutant_threads: set[str] = set()` | `test_step_7e_runs_when_ships_records_is_disabled` |
| R37 | 1 | `src/probos/cognitive/cognitive_agent.py` | `await self._record_compilation_outcome(decision["procedure_id"], True)` | `pass` | `test_dispatched_compound_replays_count_toward_promotion_once_per_run[yes]`, `[error-reply]`, `test_a_commanders_approved_compound_procedure_reaches_level_5` |
| R38 | 1 | `src/probos/cognitive/cognitive_agent.py` | `result = _replay_failure if _replay_failure is not None else await self.act(action_decision)` | `result = await self.act(action_decision)` | `test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers`, `test_a_rejected_compound_step_without_recovery_fails_and_never_acts_on_the_replay` |
| R39 | 1 | `src/probos/cognitive/cognitive_agent.py` | `if compound_result.get("compound_aborted"):` | `if False:` | `test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers`, `test_a_rejected_compound_step_without_recovery_fails_and_never_acts_on_the_replay` |
| R40 | 1 | `src/probos/cognitive/cognitive_agent.py` | `await self._record_compilation_outcome(procedure.id, False)` | `pass` | `test_a_level_3_no_demotes_the_procedure_and_resets_its_count` |
| R41 | 1 | `src/probos/cognitive/cognitive_agent.py` | `await self._record_compilation_outcome(decision.get("procedure_id"), success)` | `pass` | `test_a_demoted_procedure_is_dispatched_at_its_demoted_level`, `test_a_commanders_approved_procedure_is_promoted_to_level_5`, `test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers` |
| R42 | 1 | `src/probos/cognitive/cognitive_agent.py` | `"reason": (_replay_failure or {}).get("error") or "Procedure replay succeeded in formatting but failed in execution",` | `"reason": "Procedure replay succeeded in formatting but failed in execution",` | `test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers` |

The removed `hasattr` guards and the removed config fields cannot be mutated back in one line; R8, R9 and `test_the_removed_counselor_fields_are_gone_and_old_configs_still_load` pin them.

A1 adds no source line, so no mutation row. Its three pins are checked by deletion instead (run each alone on the applied, regenerated tree, restore after): delete `, crew_only: bool = False` from §7.15's `all_scores` (expect `test_the_trust_network_doubles_match_the_real_class[tests.test_ad1260_wellness_domain-_FakeTrust]` to fail on `all_scores`); delete `agent._counselor_config = CounselorConfig()` from §7.21 (expect `test_trust_update_sends_dm_when_unfit` to fail with `AttributeError`); set the census header's `default_false` back to 226 (expect `test_the_measured_census_matches_the_manifest_header`). Command: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf924_trust_inputs.py tests/test_counselor_therapeutic.py tests/test_ad1185_config_profiles.py -n 0 -x -q`.

A2: rows R17 to R20 run with the M1 command and R21 to R23 with the M2 command, as above. Finding 4 (the attribute read inside the `try`) cannot be mutated back in one line; `test_a_runtime_whose_trust_network_cannot_be_read_is_held_to_level_2_and_warned` pins it. R20 mutates a line BF-924 does not change: it checks that D9's test fails if the completion event's rule changes. D14 is checked once, not mutated: from the oracle tree with `PYTHONPATH` unset, `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py --check` reports the reference current; with §7.23's four added lines deleted it reports it stale (it then documents `D:\ProbOS\src`'s models, which still carry the four removed fields); restore after.

A3: R24 runs with the M2 command; R25 to R36 run with the M1 command. R25 and R27 put the defect itself back (`generate`). R32 and R33 replace a claim's check with `if False:`, so that path neither checks nor claims the window; R31 keeps the check and drops the claim; R34 drops Step 7d's claim. R35 and R36 rename a constructor attribute, as if only the Records setter still created it. Not mutated: the step validator's WARNING (a log line no test reads) and Step 7d's read-only check before the `negative_veto` branch (unchanged code; property 17).

A4: R37 to R42 run with the M1 command. R37 puts finding 2 back; R38 and R39 put finding 1 back (the abort acts on the cached decision); R40 removes D22; R41 removes the shared site's call, so no single-step outcome reaches the ladder; R42 restores the generic recovery reason. R2's line moved into `_record_compilation_outcome` unchanged and still occurs once: rerun R2. Not mutated: the abort result's `"success": False` (no reader; it was True and unread) and the helper's moved body, which R2's and R41's killers exercise.

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
A2 (2026-10-25, worktree bf924-consult; git rev-parse HEAD HEAD^{tree} -> cad8396f27baeadb0947d8fabde28192fa5744fd, c1c33802ed61d50b04754d5fed6f485fbed82025):
read logs/bf924r1/review-m1-r1.md, review-m2-r1.md, probe-test_event_boundary.py, probe-test_lifecycle.py, probe-test_boundary.py, probe-test_cost_and_faults.py, orchestrator-rerun-event.txt, orchestrator-rerun-lifecycle.txt
read cognitive_agent.py:2663-2700 (helper: getattr before the try), :1804-1871 (gate, selection, get, clamp, dispatch), :2449-2538 (Guided sets no "cached"; Validated sets it), :7744-7861 (counters; promotion :7781-7798; demotion :7802-7816; event :7852-7859 "used_procedure": decision.get("cached", False))
grep -n "used_procedure" src -> events.py:1060; cognitive_agent.py:7624, :7857; dreaming.py:2121 (4; one reader)
grep -n "TASK_EXECUTION_COMPLETE|on_task_execution_complete" src -> 8 (events 190, 1055; event_persistence 417; cognitive_agent 7619, 7852; dreaming 2117; startup/dreaming 341, 347)
read dreaming.py:2117-2167 (reactive trigger), :1998-2077 (anti-loop guard, confirmation), :1863-1979 (dream-time scan, called :694)
grep -n "^REACTIVE_COOLDOWN_SECONDS|^EVOLUTION_COOLDOWN_SECONDS|^PROCEDURE_MIN_SELECTIONS|^TEACHING_MIN_COMPILATION_LEVEL" config.py -> 254 (60); 251 (259200); 245 (5); 289 (5)
read prompts/archive/ad-532e-reactive-proactive-triggers.md:80-149; prompts/archive/ad-535-graduated-compilation.md:80-105, :476-493
read procedure_store.py:28-50, :168-201 (_index_write rolls back), :629-812 (save, chroma payload, sync_routing_index, routing_state), :814-832 (get), :925-986 (find_matching), :1076-1133 (promote, demote: column only), :1261-1297 (deactivate), :1588-1662 (decay: column, snapshot, chroma)
grep -n "\.(promote|demote)_compilation_level\(" src -> cognitive_agent.py:7789, :7806 (2)
grep -n "compilation_level" commands_procedure.py routers/procedures.py procedures.py diagnostic_context.py -> 412; 167; 842, 925, 940, 1357; 329
read prompts/ad-1326-procedure-challenger-champion.md:229-236, :4139-4145 (D14)
grep -n "promote_compilation_level|demote_compilation_level" tests -> 22 hits; real-store calls in test_graduated_compilation.py (236, 246, 706, 727, 750-751, 763), test_bf891_procedure_store_lock.py:572-573, test_ad1326_procedure_ledger.py:2735
read tests/test_ad1326_procedure_ledger.py:2640-2758; tests/test_graduated_compilation.py:33-43, :200-249, :686-770; tests/test_bf891_procedure_store_lock.py:560-589, :859-867; tests/test_fallback_learning.py:27-150; tests/test_replay_dispatch.py:25-107
read routers/procedures.py:1-30, :150-218 (teach route); clearance_grants.py:78-176; commands_clearance.py:1-200; git diff 82e795b0 cad8396f -- commands_clearance.py (M2 changed only the helper and the Agent column)
grep -n "cmd_grant|except Exception" experience/shell.py -> 326; 343
read ui/src/components/profile/avatarSignals.ts:30-54; grep -n "trust_delta|trustDelta" ui/src (tests excluded) -> 17 hits, one assignment (avatarSignals.ts:46)
read scripts/gen_config_reference.py:1-40, :168-186; scripts/check_config_profiles.py:50-64
grep -n "json_set\(|json_extract\(" src -> json_set 0; json_extract in semantic_store.py, workforce.py, profile_qualification_store.py
read trust.py:88-112, :358-370, :1017-1035
A3 (2026-10-25, consult worktree `bf924-consult` at the M2 candidate `09fe39fc`, parent `de0751e4`):
git diff --stat 990390c9 09fe39fc -> 27 files; dreaming.py and the two AD-1326 test files unchanged by M1 and M2; git diff -U0 for cognitive_agent.py and test_graduated_compilation.py: neither touches the validators or their tests
grep -n "\.generate\(" src/probos -> 3 (device_pairing.py:37, a key; cognitive_agent.py:2592, :2632)
read cognitive_agent.py:1800-1928 (Level 3-5 dispatch), :1943-2117 (replay format, compound replay), :2495-2637 (validators), :2663-2838 (clamp, promotion request, announcement), :7596-7617 (compound dispatch), :7690-7889 (post-execution), :8668-8745 (AD-594 consultation), :12756-12760 (_resolve_tier)
read types.py:306-360 (LLMRequest, LLMResponse); llm_client.py:243-267, :2084-2098, :2907-2966; grep "return LLMResponse\(" llm_client.py -> error replies at :1532, :2022, :2040, :2056, :2092
read prompts/archive/ad-535-graduated-compilation.md:340-365; grep of its validation lines -> :351 (generate), :363 (fail-open), :580-596 (tests), :666 (acceptance)
read procedures.py:215-253 (confirm_evolution_with_llm); procedure_store.py:1052-1093 (counters), :1316-1427 (request_promotion); config.py:251, :254, :266-277
read dreaming.py:100-200 (constructor, setters), :1846-2167 (Step 7b, the attempt, the reactive trigger), :2169-2326 (Step 7d), :2328-2437 (Step 7e), :2440-2494 (proactive scan); startup/dreaming.py:339-355; runtime.py:1960-1998; startup/finalize.py:5410-5419
read tests/test_graduated_compilation.py:1-100, :340-600; tests/test_bf924_compilation_trust.py:1-400; tests/test_bf924_trust_inputs.py:112-215; tests/test_fallback_learning.py:65-160; tests/test_bf106_dreaming_di.py:1-90; tests/test_replay_dispatch.py:28-57; tests/test_ad622_clearance_grants.py:312-335
read commands_clearance.py:176-224; grep -n "expires_at" clearance_grants.py -> readers :88, :100, :175
read ui/src/components/profile/SelfImageTab.tsx:270-281, :440-459; grep -n "avatar-telemetry|trust_delta|applied_modulation|pitch|fired_rules" SelfImageTab.tsx -> :100 (fetch), :138 (stream), :277-278 (backend snapshot to the panels), :455, :484, :488
read logs/bf924r2/test_validation_interface.py, test_event_cost.py, test_fallback_initialization.py (the reviewer's probes)
A4 (2026-10-25, consult worktree `bf924-consult` at the M2 candidate `e941b868`, parent the M1 candidate `cb201c20`):
git diff --stat cb201c20 e941b868 -- src/probos/cognitive/cognitive_agent.py tests/test_bf924_compilation_trust.py -> empty (M2 touches neither)
read logs/bf924r3/review-bf924-m1-r3.md, test_compound_reach.py, orchestrator-rerun-compound.txt (all-YES levels 2,2,3,3,3,3,3,3,3 with count 0 at Level 3; all-NO 2,2,3,3,3,4,4,4,4 with no ordinary call)
read cognitive_agent.py:1722-1928 (dispatch), :2012-2117 (compound replay; abort :2109), :2495-2652 (validated decision, NO :2510-2522; validators), :2711-2717, :6597-6623 (act, report), :7617-7667 (compound branch, degradation, act), :7764-7905 (accounting, recovery, events)
grep -n "compound_aborted" src tests -> cognitive_agent.py:2109 (the write); test_graduated_compilation.py:608 (2)
grep -n "\.(record_consecutive_success|promote_compilation_level|demote_compilation_level|reset_consecutive_successes)\(" src/probos -> cognitive_agent.py:7794, :7807, :7824, :7832 (4, the ladder's only writes, all in the post-execution step)
grep -n "_execute_compound_replay\(|_build_validated_decision\(" src/probos -> one caller each (:7619, :1875)
grep -n "used_procedure|fallback_type|execution_failure" dreaming.py -> :2133 (reactive skip), :2229-2238, :2317-2325 (execution_failure deactivates the parent when no challenger plan); startup/dreaming.py:168 (build_procedure_challenger)
grep -n "^COMPILATION_|^PROMOTION_MIN" config.py -> :266-277 (threshold 3, demotion level 2, max 5, Level 3 minimum 0.5, promotion request from Level 4)
grep -n "callsign: \"(LaForge|Bones|Worf)\"" config/ontology/organization.yaml -> :393, :405, :421
grep -n "def get_post_for_agent|def get_agents_for_post" src/probos/ontology/service.py -> :165, :177
read cognitive_agent.py:2723-2730 (_DEPARTMENT_CHIEFS), :2764-2770 (routing), :2829-2841 (the DM: the approver's name passed as its agent id)
read prompts/archive/ad-535-graduated-compilation.md :37, :53 (any failure demotes and resets), :263 (the NO falls through via service recovery), :383 (a step NO aborts)
read tests/test_multi_agent_replay_dispatch.py:93-166, :764-946, :1046-1155 (compound handle_intent pins: one completion :824; one event with compound_dispatched :852-856); tests/test_graduated_compilation.py:73-98, :395-438, :505-610; tests/test_bf924_compilation_trust.py:1-678
read tests/test_ad1343_stop_seam_inventory.py:84-111 (public coroutines only; a new private helper is outside it)
grep -n "_record_compilation_outcome|_replay_failure|failed_step" src -> 0
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

CLAIM (A2): promote and demote have two production callers, both in the post-execution step
RUN:   Grep "\.(promote|demote)_compilation_level\(" src
FOUND: cognitive_agent.py:7789, :7806
HOLDS: yes

CLAIM (A2): no issue tracks the column-only promote/demote
RUN:   gh issue list --state all --search "promote_compilation_level OR demote_compilation_level OR \"content_snapshot\""; Grep "promote_compilation|demote_compilation|promotion.{0,40}(inert|never take)" over #1523's comments
FOUND: #1523 only; 0 matches in it (its F-29 and F-46 concern deactivate's swallowed snapshot UPDATE)
HOLDS: yes

CLAIM (A2): apart from A2's tests, no test drives handle_intent on a real ProcedureStore, and only two tests touch the column-only write
RUN:   Grep "ProcedureStore\(" tests (22 files); Grep "handle_intent\(" over them (ad1326_*, ad572, ad579c, ad657, bf921, procedure_*, promotion_*, graduated, bf891); Grep "snapshot.{0,60}compilation_level|compilation_level.{0,60}snapshot|not the cached Procedure" tests
FOUND: 0 handle_intent; test_ad1326_procedure_ledger.py:2650 (docstring) and :2735 (premise), test_graduated_compilation.py:238 (a comment): §7.4b, §7.3 Pair 5
HOLDS: yes

CLAIM (A2): dreaming.py:2121 is the only reader of used_procedure
RUN:   Grep "used_procedure" src
FOUND: events.py:1060 (field); cognitive_agent.py:7624, :7857 (writers); dreaming.py:2121
HOLDS: yes

CLAIM (A2): _grant_issue is the only writer of a clearance-grant expiry; only _grant_list formats one
RUN:   Grep "issue_grant\(|expires_at" over clearance_grants.py, routers/*.py, commands_clearance.py; Grep "clearance_grant_store|ClearanceGrantStore" src
FOUND: commands_clearance.py:90 is the only issue_grant through the clearance store (the routers' calls go to the tool-permission, skill, intent, department and MCP stores); readers compare numbers (clearance_grants.py:88, :100, :175); the formatting is commands_clearance.py:187-189
HOLDS: yes

CLAIM (A2, narrowed by A3): the HXI's voice playback and VRM never receive the backend trust_delta
RUN:   Grep "trust_delta|trustDelta" ui/src (tests excluded); A3: read SelfImageTab.tsx:100, :138, :277-278, :440-459, :484-488
FOUND: one assignment, avatarSignals.ts:46 (const trust_delta = 0); its readers voiceModulation.ts:109-111 and CrewVRM.tsx:159-162. A3 correction: SelfImageTab.tsx:455 reads the backend snapshot's current_signals (fetched :100, streamed :138, passed :277), not deriveAgentSignals; A2 counted it wrongly
HOLDS: yes for the voice playback and VRM; the Self Image tab shows the backend value (review round 2, M2 finding 1)

CLAIM (A2): two of the six scripts that import probos have no anchor to their own src
RUN:   Grep "^\s*(from probos|import probos)" scripts; Grep "sys\.path\.insert" scripts
FOUND: 6 files; 4 anchor (check_config_facade, check_config_profiles, diagnose_llm, tts_audio_inventory); gen_config_reference.py (§7.23) and gen_capability_truth.py (R12) do not
HOLDS: yes

CLAIM (A2): no json_set call exists yet
RUN:   Grep "json_set\(|json_extract\(" src
FOUND: json_set 0; json_extract in knowledge/semantic_store.py:333-384, workforce.py, profile_qualification_store.py:124-169
HOLDS: yes (json_set's availability: section 17)

CLAIM (A3): no LLM client defines generate; the two validators are its only callers on an LLM client
RUN:   Grep "\.generate\(" src/probos; Grep "async def (complete|generate)" src/probos
FOUND: .generate( 3 (device_pairing.py:37, Ed25519PrivateKey.generate; cognitive_agent.py:2592, :2632); complete defined at llm_client.py:247 (BaseLLMClient), :1458, :2907; no LLM client defines generate (only generate_* methods elsewhere: rhubarb_backend, captains_log, plan_of_day, workforce, routers/avatars)
HOLDS: yes

CLAIM (A3): only test_graduated_compilation.py invents generate on an LLM double
RUN:   Grep "\.generate\s*=|generate=AsyncMock|\"generate\"" tests
FOUND: 1 file; assignments :436, :445, :455, :467, :499, :508, :524 and call_args reads :449, :461, :473
HOLDS: yes

CLAIM (A3): every other method called on the Level 3-5 dispatch and post-execution path exists on its object; two attribute reads do not
RUN:   Grep the definition of each callee of cognitive_agent.py:1800-1928, :2012-2117, :2495-2637, :2717-2838, :7749-7889
FOUND: 19 definitions: ProcedureStore get :814, record_selection :1052, record_applied :1064, record_completion :1068, record_fallback :1072, record_consecutive_success :1076, reset_consecutive_successes :1094, promote_compilation_level :1105, demote_compilation_level :1127, get_quality_metrics :1149, request_promotion :1316, get_promotion_status :1514; AgentRegistry get_by_pool :61, get_by_capability :64 (substrate/registry.py); IntentBus.send (mesh/intent.py:1133); WardRoomService list_channels :293, get_or_create_dm_channel :306, create_thread :413 (ward_room/service.py); get_agent_department (ontology/service.py:159). LLMRequest and Priority are imported (cognitive_agent.py:37, :39). Attribute reads: getattr(self, "_agent_id" | "_callsign", agent_type) at :2786-2787 and :2906-2907; Grep "self\._agent_id\s*=|self\._callsign\s*=" src -> 18 hits, none in an agent class (Grep over substrate/agent.py, cognitive_agent.py, crew_profile.py -> 0)
HOLDS: methods yes; the attribute reads are D16 (:2786-2787) and R18 (:2906-2907, no production caller)

CLAIM (A3): no test reaches the promotion request or its announcement
RUN:   Grep "_announce_promotion_request|_request_procedure_promotion" tests
FOUND: 0
HOLDS: yes

CLAIM (A3): the chief names in _DEPARTMENT_CHIEFS are no agent's, and the ontology has no chief lookup
RUN:   Grep "\b(laforge|number_one|obrien)\b" config; Grep "laforge" src; Grep "def \w*chief\w*\(" src/probos/ontology; gh issue list --state all --search "_announce_promotion_request OR DEPARTMENT_CHIEFS OR \"promotion request\" approver"
FOUND: config 0; src 2 (cognitive_agent.py, the map; security/autonomy_boundaries.py:98, a regex); ontology 0; no issue (3 unrelated results)
HOLDS: no (corrected by A4, D23): the search was case-sensitive; see the A4 claim at the end of this section (R17 corrected)

CLAIM (A3): the 72 h window is checked at four sites and written at nine; no test asserts an entry is absent
RUN:   Grep "_addressed_degradations" src; Grep "_addressed_degradations" tests
FOUND: checks dreaming.py:1885, :2013, :2220, :2471; writes :1911, :1919, :1936, :2029, :2047, :2055, :2073, :2265, :2280; tests 17 occurrences in 7 files (ad1326_dreaming_challenger 2, ad541c_retrieval_practice 1, dream_step_7e 1, dream_step_7f 1, fallback_learning 3, procedure_evolution 4, reactive_proactive_triggers 5), none an absence assertion
HOLDS: yes

CLAIM (A3): the fallback queue and the observed-thread set were created only in set_records_store, and startup calls it only with a records store
RUN:   Grep "_observed_threads|set_records_store\(|_fallback_learning_queue" src, tests
FOUND: creation dreaming.py:186, :187; readers :2178-2201, :2363-2436; production call startup/finalize.py:5418, under :5417; tests set the fields in four __new__ factories (fallback_learning.py:142, :147; ad541c_retrieval_practice.py:443-444; dream_step_7f.py:59, :64; dream_step_7e.py:98, :103) and call the setter at ad1326_challenger_e2e.py:489, ad1326_dreaming_challenger.py:198, bf106_dreaming_di.py:52, :79
HOLDS: yes

CLAIM (A3): the Level 3 decision's "validated" key has no reader
RUN:   Grep "get\(\"validated\"|\[\"validated\"\]" src
FOUND: 0
HOLDS: yes

CLAIM (A3): console.print(table) is one line in commands_clearance.py
RUN:   Grep "console\.print\(table\)" commands_clearance.py
FOUND: :223
HOLDS: yes

CLAIM (A3): LLMRequest has no user_message field and its prompt has no default, so AD-594's consultation request raises (R19)
RUN:   read types.py:306-332; Grep "handle_consultation_request" src; gh issue list --state all --search "consultation LLMRequest user_message"
FOUND: fields prompt (no default), system_prompt, tier, temperature, top_p, max_tokens, id, tools, tool_choice, messages, agent_id, work_item_id, min_tier, tier_choice_reason, exact_tier; cognitive_agent.py:8723-8727 passes user_message and no prompt; the handler is registered at :1666; no issue
HOLDS: yes

CLAIM (A4, corrects A3): the chiefs exist and the ontology resolves them; _DEPARTMENT_CHIEFS addresses them by a lowercase name used as an agent id
RUN:   Grep "callsign: \"(LaForge|Bones|Worf)\"" config/ontology/organization.yaml; Grep "def get_post_for_agent|def get_agents_for_post" src/probos/ontology/service.py; read cognitive_agent.py:2723-2730, :2829-2841
FOUND: :393 LaForge, :405 Bones, :421 Worf; service.py:165, :177; the map's values are lowercase names, passed to get_or_create_dm_channel(agent_id, approver_id, ...) as approver_id
HOLDS: yes (D23, R17)

CLAIM (A4): only one test reads compound_aborted; the lifecycle reads only compound_dispatched
RUN:   Grep "compound_aborted" src, tests; read cognitive_agent.py:7617-7661
FOUND: src 1 (cognitive_agent.py:2109, the write); tests 1 (test_graduated_compilation.py:608); the lifecycle tests compound_result.get("compound_dispatched") only (:7624)
HOLDS: yes (D20)

CLAIM (A4): the ladder's four writes have one site, which no compound path and no Level 3 NO reaches
RUN:   Grep "\.(record_consecutive_success|promote_compilation_level|demote_compilation_level|reset_consecutive_successes)\(" src/probos
FOUND: 4, all at cognitive_agent.py:7794-7832, after the compound branch's return (:7652-7658); the NO path's LLM decision carries no procedure_id (:2510-2522)
HOLDS: yes (D21, D22)

CLAIM (A4): no test drives a compound replay through handle_intent at Level 3, or reads the ladder after a compound replay
RUN:   Grep "compilation_level=3" tests; Grep "_make_compound_procedure\([^)]" tests; read test_multi_agent_replay_dispatch.py:93-122, :764-946
FOUND: compilation_level=3 in tests: test_graduated_compilation.py :404-:433 (_build_validated_decision called directly), :579, :607 (_execute_compound_replay called directly), and files off the dispatch path; no _make_compound_procedure override (its factory is Level 4); the handle_intent compound tests use a mock store
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- Bug fix in ProbOS plumbing (dead reads behind `getattr` defaults and `hasattr` guards); no outside analogue, so no external search, and `docs/research/reference-projects.md` was not consulted. Internal: AD-535/536/537 (compilation levels, promotion, teaching), BF-263 (trust by `self.id`), BF-907 (slot keys), AD-722/722a (avatar telemetry, divergence), AD-622 (grants), AD-503 (Counselor config), BF-921 D3 and BF-923 D8.
- Blind spots addressed: the grant target's id form (D5; a callsign list could never match); the avatar's crew-visible pitch and rule text (E6, which the issue's "Captain-facing" missed: `system.yaml:1631` turns interoception on); the divergence trust write, shown independent of `trust_delta` (5b); the Level 2 path's counters, shown identical to the replay path's (5a); `float(MagicMock())` running the masked tests at Senior trust (section 6); the Counselor's non-uniform alert paths (D7); the profile manifest's frozen flag row and the two generated docs (D7).
- Considered, deferred: consolidating the six live-trust reads (R1); a persisted trust history (R6); config bounds (R4).
- A2 (review round 1): the column and snapshot copies of a procedure's level (D10; AD-1326 D14 had seen it and kept `get`); the completion event's meaning for a Guided run (D9; AD-535 Part 8, AD-532e's event); `float()` accepting NaN and infinities (D11); a time the platform cannot show (D12); the HXI's own zero trust delta (D13); a generator resolving `probos` through the editable install (D14). No external search: ProbOS plumbing. Considered, deferred: R9 to R13.
- A3 (review round 2): AD-535's own text named `generate` (Part 5), so the defect was in the spec; AD-536's promotion request and its approver routing, newly reachable through D10; the check-then-act gap in AD-532b's guard (asyncio switches tasks only at an `await`, so a check and a write with none between cannot interleave); the Records setter as a hidden initialiser; the Self Image tab's direct read of the backend snapshot. No external search: ProbOS plumbing; `docs/research/reference-projects.md` not consulted (judged 2026-10-25). Considered, deferred: R14 to R20.
- A4 (review round 3): the result side of the path D10 opened, enumerated (the result paths, section 3). AD-535's abort and any-failure rules and AD-534b's split between execution failure and near-miss decide each row. No external search: ProbOS plumbing; `docs/research/reference-projects.md` not consulted (judged 2026-10-25). Considered, deferred: R21 to R24.

## 14. Diff Reviewer: properties to verify

1. Both trust reads of the compilation clamp (the dispatch cap and the promotion cap) come from one helper that returns `float(get_score(self.id))` read through `self._runtime.trust_network` inside its `try`, and 0.0 with one WARNING when the runtime, its trust network or `get_score` fails or the value is not in [0, 1] (NaN, an infinity, a corrupt record; A2). No other site's behaviour changes.
2. For trust below 0.5, no stored procedure is dispatched above Level 2 and no promotion goes above Level 2; for trust from 0.5, dispatch and promotion are as before except that an `approved` procedure with trust from 0.7 can be promoted to Level 5. The clamp writes no stored level.
3. `TrustNetwork.get_history(agent_id, limit)` returns the agent's last `limit` event scores oldest first, `[]` for a non-positive limit or an unknown agent, and reads only the event log.
4. The profile route and the avatar telemetry call `get_history` unguarded; telemetry still never raises.
5. Every test double that stands for `TrustNetwork` on the two `get_history` paths has only `TrustNetwork` methods, with the same parameter names and kinds, and a test fails if one drifts; `_FakeTrust.all_scores` returns the same scores with or without `crew_only` (A1-1).
6. `/grant list` never raises for a stored grant: a time the platform cannot show reads "out of range" in its own row and the Status reads the raw value (A2); it shows the live callsign of a target whose certificate resolves by uuid or slot, else the id prefix as before. `/grant issue` refuses a duration that is not finite or whose expiry cannot be shown, and stores nothing (A2).
7. The Counselor's trust-update threshold and default sweep bound come from the `CounselorConfig` startup passes; with the default config every result is as before; an explicit `max_agents` still wins. Nothing else in `counselor.py` changes, BF-923's gather hold included.
8. `CounselorConfig` has exactly the two read fields; a config with the removed keys loads; the tracked `system.yaml`, the profile manifest (its frozen rows and its `census:` header), the facade baseline and the config reference agree with the model; the generated diffs are exactly section 6's hunks; the field-count pin is 1876.
9. Every replaced test double or pin says inline what it masked or why it changed; no test was deleted.
10. No production line was added for Counselors built without `__init__` (no class-level default, no `getattr` fallback); the one test builder that reaches a reader sets `_counselor_config` itself (A1-2).
11. (A2, D10) `promote_compilation_level` and `demote_compilation_level` write the level to the column and to the JSON snapshot in one statement under `_index_write`; afterwards `get` returns the new level; counters other than `consecutive_successes` and every other snapshot field are unchanged; `get`, `save`, the semantic index and `_migrate_qualifying_procedures` are unchanged. Every consumer of `get`'s level (dispatch, the promotion step, the demotion check, both teaching gates, evolution's inherited level, the diagnostic context, `sync_routing_index`) now follows promotions and demotions, and none relied on the column-only write except AD-1326's restore test, whose premise is now set directly.
12. (A2, D9) The `TASK_EXECUTION_COMPLETE` payload is unchanged: an Ensign's clamped Guided run emits `used_procedure: False` and reaches AD-532e's reactive check exactly as a stored Level 2 Guided run does; a replay emits `True` and does not; the check's cost is bounded as E9 states, under overlapping deliveries too (A3, D17).
13. (A2, D14) `gen_config_reference.py` imports its own checkout's `src`; under the canonical environment its output is byte-identical; no generated file changes.
14. (A2, D13; A3, D19) No text claims the Captain's voice playback or VRM receives the backend trust delta, and no text claims the Self Image tab does not show it.
15. (A3, D15) Both Level 3 validators call `complete(LLMRequest(...), priority=Priority.NORMAL)` and read `LLMResponse.content`; YES passes and any other answer fails; a call that raises, times out or returns an error reply passes by default with one WARNING; the prompts, the timeout and the token limits are unchanged; no `generate` call remains. Every validator test double has only `BaseLLMClient`'s interface, and each asserts that the request reached `complete`.
16. (A3, D16) The promotion request's thread and DM name the agent (`self.id`, `self.callsign or agent_type`); nothing else in `_announce_promotion_request` or `_request_procedure_promotion` changes; `_teach_procedure` is unchanged (R18).
17. (A3, D17) On every path that reads AD-532b's window (Step 7b; `_attempt_procedure_evolution`, for the reactive trigger and the proactive scan; Step 7d), no `await` separates the check from the claim; a `negative_veto` inside the window is still counted as skipped and flags nothing; every exit that recorded before records as before; two overlapping triggers for one procedure make one attempt.
18. (A3, D18) A constructor-built `DreamingEngine` has its fallback queue and observed-thread set; `set_records_store` binds only the store and resets nothing; no `__new__` factory needed a change.
19. (A3, D19) Each positive `/grant list` test fails when no table printed; the refused-issue tests still read the whole output.
20. (A4, D20) A compound Level 3 step that the validator answers with anything but YES: no `act()` on the cached decision; one `record_fallback` and no `record_completion`; demotion to Level 2 (count reset); AD-534b's recovery runs once; recovered: success with the LLM's answer and one `execution_failure` event whose reason names the step; not recovered: the intent fails with that reason and no learning event; `used_procedure: True` either way. A failed step-validation call still passes by default.
21. (A4, D21) A dispatched compound replay (Level 3 with every step accepted or passed by default; Level 4; Level 5) records its completion once (the branch's existing write) and reaches the AD-535 accounting exactly once: the count, promotion at the threshold within the trust caps, AD-536's request on reaching Level 4; the compound event and result are unchanged; the degradation paths are unchanged.
22. (A4, D22) A Level 3 overall NO demotes the stored procedure to Level 2 and resets its count, once; the LLM still serves the intent; the `validation_failure` near-miss, its learning event and `used_procedure: False` are unchanged; a failed overall validation call passes by default and touches no counter.
23. (A4) `_record_compilation_outcome` is the post-execution block moved unchanged (stripped lines equal, the `_proc_id_for_promo` assignment aside); it has exactly three callers; no intent calls it twice; each row of section 3's result-path table matches the code.
24. (A4, D23) No text claims the configured chiefs do not exist; R17 names the name-as-agent-id addressing and the ontology queries that resolve a chief.

## 15. Acceptance criteria

- Through `decide` on a real agent with a real `TrustNetwork`: an Ensign runs a stored Level 4 procedure as Guided, a Lieutenant replays it, and an unreadable trust is held to Level 2 with a WARNING. Through `handle_intent`: a Commander's approved Level 4 procedure is promoted to Level 5; an Ensign's successes do not promote a Level 2 procedure. A2: a NaN, infinite or out-of-range trust and an unreadable `trust_network` attribute are held to Level 2 with a WARNING, and an infinite trust promotes nothing; on a real `ProcedureStore`, a Commander's promotion to Level 5 is what `get` returns and the teaching route accepts, a demoted procedure is dispatched Guided, and an Ensign's Guided completion reaches AD-532e's reactive check as a stored Level 2 run's does.
- Through the real route and telemetry, profile trust history and avatar `trust_delta` come from `TrustNetwork.get_history`; the four doubles are pinned to the real class.
- Through the real `/grant` command and registries, `/grant list` names a grant's target with grants present, with and without an identity registry, and shows every row when one stored expiry cannot be shown as a date; `/grant issue` refuses such a duration (A2).
- Through real Counselors (one on a booted runtime), `trust_delta_threshold` and `sweep_max_agents` come from the config; the removed fields are gone and old configs load; the config reference and facade baseline are regenerated and checked.
- A3: through `decide` on a real store and a real `OpenAICompatibleClient` (only `complete` replaced), a Level 3 replay makes its validation request: YES replays, NO goes to the LLM, and a failed call or an error reply passes by default with a WARNING. Through `handle_intent`, a Lieutenant's promotion to Level 4 requests institutional promotion authored by the agent. Two agents' overlapping completions, and a completion during Step 7b or 7d, make one evolution attempt per procedure. With no Records setter, a real fallback reaches Step 7d and Step 7e scans. Every positive `/grant list` test requires the printed table.
- A4: through `handle_intent` with a real `IntentBus`, `AgentRegistry` and target agent, a real store and a real `OpenAICompatibleClient` (only `complete` replaced): a compound step the Level 3 validator rejects is a failed replay (no action on the replay, one fallback, demotion to Level 2, the LLM's recovered answer and an `execution_failure` event naming the step; with no recovery the intent fails naming the step); dispatched compound replays count once a run and promote at the threshold (Level 3 to 4, and a Commander's approved Level 4 to 5); a Level 3 NO demotes the procedure to Level 2 and resets its count while the LLM serves the intent.
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
  - A2: D4(c)'s count again; the count of `Procedure '...' demoted to Level 2` lines, and for one demoted procedure that its next dispatch made an LLM call (Guided) rather than a cached replay (E8); the count of `Procedure evolved` lines against earlier sessions (E9).
  - A3: the count of `Level 3 validation call failed` and `Level 3 step validation call failed` WARNINGs (expected 0 with a healthy provider); the count of `[Promotion Request]` threads and of `pending` procedures (E11); with Records disabled only, the count of `Fallback learning handler failed` lines (expected 0).
  - A4: the count of `Compound step ... validation failed — aborting compound replay` lines and of `Level 3 validation failed for procedure` lines, each followed by a `Procedure '...' demoted to Level 2 after failure` line for the same procedure (expected 0 of each while no active procedure is at Level 3, D4).

## 17. Not verified

- **Which source the tests import.** The focused baseline run here (`270 passed`) imported `D:\ProbOS\src` (the warning path in its output), not this worktree's `src`: the venv's editable install points at the main checkout. The orchestrator must run every focused check, tests-first run and mutation row against the scratch tree's `src` (e.g. `PYTHONPATH` set to it), or the counts above prove nothing about this tree.
- D4's numbers: read by the orchestrator and posted on #1654 (A1): no active procedure is at Level 3 or above, so M1 changes no live dispatch of a stored procedure today.
- That `float(MagicMock())` is 1.0 (CPython `unittest.mock` documents `__float__: 1.0`; read, not run here). Section 6's census rests on it; the tests-first run shows it (no other test of the seven files may fail).
- The new tests were written in a read-only consult and not run. In particular: that `test_fallback_learning.py`'s `object.__new__` agent completes a Guided decision through `handle_intent` with a `MockLLMClient` (`test_an_ensigns_successes_do_not_promote_it_past_level_2`; its `record_completion` premise fails rather than passes if it does not); that `ReplayTestAgent`'s `decide` reaches the LLM with a real `TrustNetwork` on the `MagicMock` runtime as it does with a `MagicMock` one; that a default `SystemConfig()` boot registers one Counselor and more than two sweep-eligible agents; that `_first_mutable_free_field` and `_perturb` in `test_ad1270e2h_*` handle `CounselorConfig`'s new first field, a float; that Rich renders the grant table within 240 columns without truncating "Crusher".
- ~~That `check_config_facade.py --update-baseline` changes only the `CounselorConfig` row~~ (A1: wrong; the oracle's run gives section 6's hunks, and its `--check` passed with no review metadata).
- A1: the four repaired cases and the rest of the union were not rerun here (this was an edit-only run); the census figures were measured here by a scratch probe on this tree's `src` (section 11), not by the oracle.
- That the operator's local `config/system.yaml` on the Captain's machine is not customised in the counselor block; if it is, the merge conflicts there, and either result loads (unknown keys are ignored).
- A2: written in a read-only consult and not run: the 10 new M1 cases, the 5 new M2 cases, the changed promote test and the AD-1326 premise. In particular: that `json_set` is available in the venv's SQLite (the JSON1 functions are in use, `json_extract`, but this tree has no `json_set` call); that `ReplayTestAgent` completes `handle_intent` on a `SimpleNamespace` runtime with a real store (the reviewer's probes did, `logs/bf924r1/probe-test_lifecycle.py`); that `decide` tolerates trust 2.0 at the other six trust reads (it tolerated `None` and `"x"` in round 1); that Rich prints `out of range` and `Invalid duration: <value>` unwrapped at width 240; that the AD-1326 test's direct write through `store._db` needs no lock; that `10.0 * 0.7` gives a network score of exactly 0.7 (the test asserts it as a premise).
- A2: section 6's census of the 219 masked tests is the reviewer's measurement, not rerun; A2's range check keeps `float(MagicMock()) == 1.0` in range (read, not run).
- A3: written in a read-only consult and not run: the 11 new M1 cases, the seven strengthened validator tests, the two comment-only test edits and the M2 helper. In particular: that `decide` completes its LLM path with a real `OpenAICompatibleClient` whose `complete` alone is replaced (the `[no]` case; the reviewer's probe took only the replay branch); that `OpenAICompatibleClient(base_url=...)` opens no connection before `complete` (the probe constructed and closed one); that re-saving a stored procedure keeps it matchable; that `classify_criticality` rates the test procedure below high (the thread goes to All Hands either way, the DM to `captain`); that `evolve_fix_from_fallback` with no episodes and a NO reply does not raise out of Step 7d; that a dream step's first `store.get` is its parent load (read: `list_active` and `get_quality_metrics` do not call `get`); that `MagicMock(spec=BaseLLMClient)` is truthy (the validators return early on a falsy client).
- A3: the new Level 3 traffic's provider behaviour (which tier answers, token use) and the WARNING volume under a provider outage were not measured; E10 rests on the code. CI's SQLite build is still unread (A2).
- A4: written in a read-only consult and not run: the 6 new cases and the seven code pairs. In particular: that AD-534b's recovery makes exactly one `complete` call through `_decide_via_llm` and returns a decision whose `act()` succeeds (the probe measured one ordinary call per Guided run, `logs/bf924r3/orchestrator-rerun-compound.txt`); that the recovered answer does not contain `[Procedure Replay`; that `patch.object(agent, "act", AsyncMock(wraps=agent.act))` passes every other call through; that patching `IntentBus.send` again for each run keeps the subscription; that `request_promotion` at three completions posts nothing in `_store_rig`'s Ward Room double (if it raises, the helper's `except` swallows it, as before); that approving after the re-save keeps the procedure matchable; and how a real provider answers the step prompt.

## 18. For the register (found here, not fixed by this change)

- **R1.** Six live-trust reads in `CognitiveAgent` (`:2870`, `:3351`, `:6042`, `:6230`, `:9123`, `:11455`) each guard and read `get_score(self.id)` their own way; `_compilation_trust_score` is a seventh. One helper is a DRY refactor with its own consumer list.
- **R2.** AD-503's assessment retention (`profile_retention_days`, `_cleanup_old_assessments`, `prompts/archive/ad-503-counselor-activation.md:879`) was never built: the `assessments` table grows without bound (BF-923 D7 bounds only the profile).
- **R3.** An operator Bridge-alert policy for the Counselor (which paths alert at which severity) would be new design and would include alert-silencing switches: the Captain's call.
- **R4.** `trust_delta_threshold` and `sweep_max_agents` carry no bounds (a negative bound silently disables the sweep). Adding them changes three pinned AD-1270e2 tables (`test_ad1270e2h_*:122-150`, `:564-575`).
- **R5.** `episodic_procedural_bridge.py:84` guards `store.list_all()`, which no procedure store defines; its fallback (`list_active` plus `get`) always runs. Same shape as F05, inert.
- **R6.** Trust history is the in-memory event log (500 events ship-wide, empty at boot), so a quiet agent's profile history is short or evicted. A persisted history is design work.
- **R8 (A1).** `docs/development/config-profiles.yaml`'s `census:` header had drifted before this change (445 / 225 / 136 written, 452 / 226 / 141 measured at the base): only `default_false` is pinned (`test_ad1185_*:859`), so the other figures go stale whenever a boolean is added. Pinning the whole block to the instrument (or generating it) is a separate change.
- **R7.** `tests/test_teaching_protocol.py:93` still sets the dead `_trust_score`; `tests/test_ad1259_one_source_of_truth.py:70` `_FakeTrustNetwork` lacks `get_history` but reaches neither caller. The procedure tests' `MagicMock` runtimes run the clamp at trust 1.0 (section 6): a future test that asserts rank-dependent dispatch must give its runtime `trust_network_at(...)`.
- **R9 (A2).** AD-532e's reactive trigger predates AD-535's Guided level; whether a Guided run (stored at Level 2, or clamped) should be exempt from the reactive check, as a replay is, is an AD-532e design question. BF-924 keeps today's rule (D9); changing it changes every Level 2 run.
- **R10 (A2).** `ProcedureStore._migrate_qualifying_procedures` (`procedure_store.py:1198-1219`) raises Level 1 to 2 in the column only, and the semantic index keeps metadata level 1, so a migrated procedure is never matched by `min_compilation_level=2` (`:945-948`) and `get` reports Level 1 (read). Rows promoted or demoted before BF-924 keep a snapshot level that differs from their column (D4(c) counts them). A one-time repair and the migration fix are a data change with their own review.
- **R11 (A2; narrowed by A3).** The HXI's voice playback and VRM take `trust_delta` from `deriveAgentSignals` (`ui/src/components/profile/avatarSignals.ts:44-46`), which hardcodes 0, so the Captain's voice pitch and the VRM expression never move with trust; the backend projection carries the real value since BF-924, and the Self Image tab already shows it (it renders the backend snapshot, D13 as corrected). Wiring the playback and VRM is UI work.
- **R12 (A2).** `scripts/gen_capability_truth.py` imports `probos` with no anchor to its own `src` (`:43-45`, `:54`, `:82`), the gap §7.23 closes in `gen_config_reference.py`.
- **R13 (A2).** A persistent trust-read fault logs one WARNING with a traceback per trust read (once per procedure match, twice when the promotion step also reads); there is no throttle (review round 1, property 5). Live expectation 0 (section 16); a throttle is warranted only if it fires.
- **R14 (A3).** A stored `expires_at == 0` reads as permanent (`—`) and Active in `/grant list` (`commands_clearance.py:206`, `:213` test truthiness), while both active-grant readers compare numbers and exclude it (`clearance_grants.py:100`, `:175`). Injected only (`/grant issue ... 0` stores None) and byte-identical to before A2 (review round 2, M2 finding 3). Fix: `is not None` in both display tests.
- **R15 (A3).** `_compilation_trust_score` is range-checked float coercion, as D11 specified: an injected `True`, `"0.8"` or `MagicMock()` reads as 1.0, 0.8 and 1.0 with no WARNING (review round 2, property 1). `TrustNetwork.get_score` returns a float on every path, so only an injected double reaches it.
- **R16 (A3).** A `content_snapshot` that is a JSON array, string or null survives D10's `json_set` with no exception; the column changes and `get` stays None (review round 2, property 2). Corrupt rows only.
- **R17 (A3).** AD-536's approver routing: `_DEPARTMENT_CHIEFS` (`cognitive_agent.py:2708-2715`) maps a department to a lowercase name (`laforge`, `bones`, `worf`, ...) that `_announce_promotion_request` passes to `get_or_create_dm_channel` as the approver's agent id (`:2838-2841` on the candidate), so a low- or medium-criticality request opens a DM whose member is that literal name, not the chief's registered agent; the department channel is matched by department id against channel names. The chiefs exist (`config/ontology/organization.yaml:393`, `:405`, `:421`; A3's case-sensitive search missed them, A4 D23), and the ontology resolves them: `get_post_for_agent(agent_type).reports_to`, then `get_agents_for_post(post_id)` (`ontology/service.py:165`, `:177`), as review round 3 executed. Newly reachable through D10 (E11). A chief resolver is AD-536 design work: file it when the discovery budget allows.
- **R18 (A3).** `_teach_procedure` (`cognitive_agent.py:2906-2907`) reads the same `_callsign` / `_agent_id` attributes no agent has; it has no production caller (section 12).
- **R19 (A3).** AD-594's `handle_consultation_request` builds `LLMRequest(system_prompt=..., user_message=..., tier="fast")` (`cognitive_agent.py:8723-8727`); `LLMRequest` has no `user_message` and its `prompt` has no default (`types.py:307-331`), so every consultation raises `TypeError`, logs "AD-594: LLM call failed" and returns the fallback answer. The handler is registered (`:1666`). An independently reachable production defect off BF-924's path: file it now (filing policy).
- **R20 (A3).** A suite-wide seam test that pins every LLM-client double to `BaseLLMClient`, as §7.20's does for `TrustNetwork`: the `AsyncMock()` clients outside this change are not on the Level 3 path; D15 pins the validator doubles by `spec`.
- **R21 (A4).** A dispatched compound replay returns before the shared tail (`cognitive_agent.py:7652-7658` against `:7685-7932` on the candidate): no action episode, working-memory record, conclusion, AD-492 correlation clear, result metadata or Ward Room self-post. Pre-existing AD-534c shape; A4 adds only the ladder (D21); the compound event and result are pinned (`test_multi_agent_replay_dispatch.py:799-856`).
- **R22 (A4).** Compound detection differs by level: Level 3 by `resolved_agent_type` with at least two steps (`:2524-2526`), Level 4 and 5 by `agent_role` (`:1897-1899`), dispatch by `agent_role` (`:2036`). A procedure with one field and not the other changes shape between levels (resolved types without roles is compound at Level 3 and dispatches nothing). Every combination reaches the ladder once after A4; one rule is AD-534c/535 design.
- **R23 (A4).** At Level 4 and 5 a step whose dispatch failed or raised is replaced by its text and the replay counts as dispatched (`:2084-2097`); A4 makes it count toward promotion, as it already counted as a completion. Treating a failed dispatch as a failed replay is AD-534c design.
- **R24 (A4).** Agents whose `report` override drops `success` (`integrations/m365_connector.py:277`, `:376`, `:540`, `:639`, `:738` return `{"agent", "result"}`) make every cached replay a failure for the ladder (`report.get("success", False)`, `cognitive_agent.py:7762`): demoted, never promoted. Read, not run; whether those agents hold procedures is unmeasured.
