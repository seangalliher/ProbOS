# BF-923: the behavioral-metric and orientation callers read the episodic store through APIs it has (#1652); the Counselor reads real trust, records it with a captured baseline and a bounded history, and keeps every crew-facing result held (BF-921 D3)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25

**Status:** build-ready. One BF, two milestones (M1 STANDARD, M2 HIGH), one gate; #1652 closes after both. **BF number:** BF-923 (#1652); this contract allocates nothing. **Tier:** M1 **STANDARD** (three read paths to the episodic store; one crew-facing text, AD-567g's stasis line, appears with a true value; one ship-level metric becomes non-zero); M2 **HIGH** (the Counselor's wellness gate decides DMs and Bridge alerts for every crew member; M2's only safety property is a hold, and a defect in the hold releases an unqualified gauge onto the crew). Review the batch at HIGH: use the Copilot `Diff Reviewer`. Never lower a tier without the Captain. **Base:** written against `origin/main` `471d3f7e` (BF-921 merge, PR #1651). BF-922 (#1639) merges first; it touches none of this contract's files (section 4); the orchestrator re-verifies every SEARCH on the new base. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf923_episodic_recall_callers.py` (M1, 9 functions).
- New `tests/test_bf923_counselor_assessment_inputs.py` (M2, 9 functions, 10 cases).
- Updated pins: `tests/test_behavioral_metrics.py` (M1: the two unrestricted `AsyncMock` stores), `tests/test_counselor_activation.py` (M2: three `TestGatherAgentMetrics` tests that pinned `score` and `get_weights_for`), `tests/test_peer_repetition_credits.py` (M2: three `MagicMock` trust networks with `score`).

**Text repairs after the first oracle run (the orchestrator, 2026-10-25; the Architect's other text is unchanged).** The contract applied by tool passed all its pairs, and its tests passed except one: `test_the_booted_runtime_reads_crew_authors_episodes` (section 17's unverified premise). Section 7.7's test now passes a real `EpisodicMemory` to the runtime (a default boot has none) and selects crew by `did` (utility agents hold asset tags that `get_by_slot` cannot resolve); no stub. Section 17 records the premise as verified by run.

## 0. Premise: what is present on this tree

| Claim of #1652 | On `471d3f7e` | Holds |
|---|---|---|
| `EpisodicMemory.recall(query, k=5, *, include_self_contradicted=False)` at `episodic.py:3415` | same | yes |
| Callers pass `agent_id`: `behavioral_metrics.py:584-588`, `proactive.py:1784`, `startup/finalize.py:6296` | `:584-588`, `:1784`, `:6298` (the `recall` line; `:6296` is its `try:`) | yes; exactly three (section 12) |
| `recall_for_agent` `:3875`, `count_for_agent` `:4261` | same | yes |
| Counselor `score` call `:770`, `get_weights_for` `:779`, swallowed `:768-783` | `:771`, `:780`, `:768-784` | yes (moved by one) |
| `set_baseline` `:735`, no production caller | `:736`; 0 callers in `src/` | yes |
| `_on_trust_update` `:1773-1806` | `:1686-1719` | yes (moved by BF-921) |
| Wellness formula `:2827-2840` | `:2774-2787` | yes (moved) |
| Masking doubles `test_behavioral_metrics.py:579`, `test_peer_repetition_credits.py:545` | `:579-581` and `:627-628`; `:544-545`, `:569-570`, `:596-597` | yes; five, and three more pins in `test_counselor_activation.py:213-252` |
| **New, found here:** Ward Room posts carry the author's slot id, episodes the sovereign id | `proactive.py:2994` (`author_id=agent.id`), `ward_room/threads.py:579` and `:588` (`agent_ids=[sovereign_id]`) | the metric stays 0 with any agent-scoped read unless the id is resolved (D1) |

## 1. Problem

**Item 1 (F-446).** Three callers pass `agent_id` to `EpisodicMemory.recall`, which takes none (`episodic.py:3415-3421`); each `TypeError` is swallowed (`behavioral_metrics.py:602-607` at DEBUG without the exception; `proactive.py:1786-1787` and `finalize.py:6300-6301` `except Exception: pass`).
- `BehavioralMetricsEngine._compute_anchor_grounded_emergence` therefore returns `grounded_rate` 0.0, `independence_score` 0.0 and `analyzed_threads` 0 on every dream. Verifying the fix found a second defect on the same path: the thread's `unique_authors` are Ward Room `author_id`s, which are slot ids (`proactive.py:2994`), while the authors' episodes are stored under the sovereign id (`ward_room/threads.py:579`, `:588`; `messages.py:341`). An agent-scoped read by the slot id finds nothing, so a signature fix alone would leave the metric at 0. The engine has no identity registry.
- The two orientation callers pass `episodic_memory_count=0` for every crew member. Effect, now verified (the issue left it open): `render_warm_boot_orientation` prints "You have N episodic memories from before stasis." only when the count is above 0 (`orientation.py:413-416`), so at every stasis recovery no crew member has been told it has memories. The proactive supplement renders no count (`orientation.py` reads `episodic_memory_count` only at `:348`, `:354`, `:413`; the proactive renderers start at `:441`), so the proactive caller's count has no visible effect.

**Item 2 (F-461, R12 of BF-921).** `_gather_agent_metrics` (`counselor.py:755-805`) calls `self._trust_network.score(agent_id)`; `TrustNetwork` has `get_score` (`consensus/trust.py:1017`), and `score` is `TrustRecord`'s property (`trust.py:97`). It calls `self._hebbian_router.get_weights_for(agent_id)`, which no class defines. Both fail at DEBUG, so every production assessment has `current_trust = TRUST_DEFAULT` and `hebbian_avg = 0.0`; with the never-captured baseline (`CognitiveBaseline()` defaults: trust `TRUST_DEFAULT`, Hebbian 0.0), the trust drift and the Hebbian drift are always 0.0. `CognitiveProfile.assessments` is unbounded and the whole list is rewritten into `profile_json` on every assessment (`counselor.py:182`, `:228`, `:382`).

**What a naive repair would do.** `assess_agent` turns a trust drift below -0.2 into a concern, subtracts 1.5 times the drop from wellness and marks the agent unfit below 0.3 (`counselor.py:2740-2744`, `:2776`, `:2789`). Fourteen handlers gather and assess (`counselor.py:957`, `:1078`, `:1132`, `:1176`, `:1271`, `:1311`, `:1359`, `:1414`, `:1461`, `:1484`, `:1606`, `:1699`, `:1743`, `:1919`) plus the API (`routers/counselor.py:167`); their results send DMs (`_maybe_send_therapeutic_dm`, `:2402-2413`, below 0.5 or unfit) and Bridge alerts (`_alert_bridge`, unfit), and the agent reads its own `wellness_score`, `trust_drift`, `hebbian_drift`, `concerns`, `fit_for_duty`, `alert_level` and `trust_drift_trend` through its introspective telemetry (`self_telemetry_domains.py:81-104`, `introspective_telemetry.py:275-279`). Real trust readings against any baseline would make all of these live for the first time. BF-921's D3 holds that no unqualified gauge drives a crew-facing action.

## 2. Solution overview

- **M1.** The anchor metric reads each author's recent episodes with `recent_for_agent` after resolving the Ward Room slot id to the sovereign id through an identity registry the runtime late-binds (`set_identity_registry`, the engine's existing late-bind pattern). Failures are counted and reported once per computation at WARNING. One helper, `count_agent_episodes(episodic_memory, agent)` in `cognitive/orientation.py`, gives both orientation callers the agent's own count through `count_for_agent` (as `proactive.py:2699` already does). The warm-boot block moves unchanged into `_orient_crew_after_stasis(*, runtime)` in `startup/finalize.py` so the count is tested through the caller.
- **M2.** `_gather_agent_metrics` reads trust with `get_score` and records each reading on the profile (`trust_observations`, bounded), with the first reading as the captured baseline (`observed_baseline`). The values it returns to the assessment stay exactly what production has always used (`TRUST_DEFAULT`, Hebbian 0.0), so `assess_agent`, its DMs, its Bridge alerts and the agent's own wellness view are unchanged: the hold sits at the one seam where real values enter, and the assessment's math is untouched for every explicit caller. The Hebbian read is removed (no per-agent reading is defined). The profile keeps the latest 50 assessments and readings. The measurement that must precede any action becomes an unchecked entry on #1523 (section 18).

## 3. Decisions (for #1652)

**D1, the anchor metric's read.** Ranked: (1, chosen) `recent_for_agent(owner_id, k=10)` with `owner_id = resolve_sovereign_id_from_slot(author_id, identity_registry)`: AD-569's own comment says "Retrieve recent episodes for these agents" (`prompts/archive/ad-569-behavioral-metrics.md:686`), `recent_for_agent` applies no relevance threshold (`episodic.py:4109-4116`) and `MockEpisodicMemory` has the same method (`episodic_mock.py:215`); (2) `recall_for_agent(owner_id, "", 10)`, the issue's suggestion: a semantic search for an empty query, cut by the agent relevance threshold (`episodic.py:3928-3972`; the mock returns nothing for an empty query, `episodic_mock.py:195-198`), so it measures whatever happens to pass the threshold; (3) `recall_for_agent(owner_id, thread title, 10)`: thread-relevant, arguably the better measure, but it changes what AD-569 measures, which is design work (R5). The resolution is required by any agent-scoped read (section 0). Wiring: a late-bind setter called by the runtime right after it takes the engine (`runtime.py:3177`), where `self.identity_registry` is already set (`runtime.py:2810`, before `init_dreaming` at `:3147`); constructor injection would change `init_dreaming`'s signature for one argument. Failures are counted and logged once per computation at WARNING (a per-thread WARNING could repeat 100 times a dream; DEBUG is what hid this defect).

**D2, the orientation count.** Ranked: (1, chosen) one helper, `count_agent_episodes`, using `count_for_agent(sovereign_id or slot id)`, the call `proactive.py:2699-2701` already makes every proactive cycle, so its cost is known; (2) remove the proactive read, whose count no renderer prints: leaves the orientation context holding a false 0 for the next renderer that prints it; (3) `recall_for_agent(..., k=1)`: a semantic query that can return 0 for an agent with memories, and the warm-boot text prints the number. The warm-boot block is moved verbatim into `_orient_crew_after_stasis(*, runtime) -> int`, so a test drives the caller on a real store (the only existing test of the block copies its logic inline: `tests/test_bf235_stale_identity_cache.py:197-225`). The gate condition stays in `finalize_startup`.

**D3, where the masking doubles belong.** The three `test_peer_repetition_credits.py` doubles (`:544-545`, `:569-570`, `:596-597`) double the Counselor's trust read, not the episodic store, so they are rewritten in M2 with `TrustNetwork`'s autospec. M1 rewrites the two `test_behavioral_metrics.py` stores.

**D4, the hold (BF-921 D3), and where it sits.** Ranked: (1, chosen) at the gather seam: `_gather_agent_metrics` reads and records, and returns `TRUST_DEFAULT` and Hebbian 0.0 as before; `assess_agent` is unchanged. Every production assessment gets exactly today's inputs, so wellness, concerns, fit-for-duty, alert level, DMs, Bridge alerts and the agent's wellness view are unchanged by construction, and the readings are on record for the measurement. (2) A hold inside `assess_agent` (drop the trust and Hebbian terms): changes the math for 19 explicit test callers that pin trust concerns and promotion fitness (`tests/test_counselor.py:126-170`, `tests/test_ad642_communication_benchmarks.py:543-639`, `tests/test_counselor_activation.py:591-594`) and for the LLM `act` path (`counselor.py:2858-2868`), and it would still need the real baseline kept out of `profile.baseline`. (3) Pass `observed_trust=` at each of the 15 call sites into a new `assess_agent` keyword: the same record, but a missed site fails silently and the 15 added lines are identical, so no mutation row can pin them. This hold weakens no control (it keeps today's behaviour), so it is in the envelope.

**D5, the Hebbian input.** Ranked: (1, chosen) not read; `hebbian_avg` stays 0.0 and the router stays injected and unread (R3). AD-503 specified a method that never existed (`prompts/archive/ad-503-counselor-activation.md:383`) and named no relation. (2) `REL_INTENT` weights into the agent via `get_all_weights()`, as `drift_detector.py:216-219` reads them: a plausible "routing health" signal, but its edges key on slot ids while several Counselor events carry other id forms, and choosing it is defining a new gauge; (3) `get_agent_weights` (`routing.py:289-295`): `REL_AGENT` edges are written only by `record_verification` (`routing.py:234-249`, one caller `runtime.py:4632`), so most crew have none.

**D6, the baseline.** Captured as `profile.observed_baseline` at the first trust reading (trust, and the confidence and success rate gathered with it), never overwritten. `profile.baseline`, which `assess_agent` reads, and `set_baseline` are unchanged: capturing into `profile.baseline` would change the confidence drift, which is live today (`counselor.py:2733`, `:2777`; confidence comes from the agent, `:789-792`), and so wellness, which D4 holds. `set_baseline` keeps its zero production callers until the qualifying issue promotes the observed baseline.

**D7, the bound.** `COUNSELOR_PROFILE_HISTORY_LIMIT = 50` in `counselor.py`, applied on append (`add_assessment`, `_record_trust_observation`) and on load (`CognitiveProfile.from_dict`, so the first save after the build shrinks an old profile). Readers take at most the last 3 (`counselor.py:200`), 5 (`drift_trend` default, `:215-221`) or 10 (`routers/counselor.py:213`, user-set); the full history stays in the `assessments` table (`counselor.py:292-301`, read by `routers/counselor.py:81-84`). A module constant, not config: it bounds storage, it is not an operator setting, and the neighbouring `COUNSELOR_*` thresholds are module constants too (`config.py:233-238`).

**D8, `_on_trust_update`'s trigger.** Unchanged: it still compares `new_score` with `profile.baseline.trust_score` (`counselor.py:1695-1698`), the default. Moving it to the captured baseline would end R12's churn but can also add reassessments where none happen today (an agent captured at 0.8 that falls to 0.6: today 0.1 from the default, no reassessment; against the capture 0.2, a reassessment), and each reassessment can DM on today's live inputs (confidence, personality drift, communication quality). D3 puts that in the measurement (section 18). The churn's storage cost is bounded by D7.

**D9, scope.** One contract, two milestones, one gate (the Architect's consult of 2026-10-25 00:44Z). In scope because they are on the paths being repaired: the slot-to-sovereign resolution (without it M1 fixes nothing), the failure logging at each repaired read (the DEBUG swallows hid both defects), and the warm-boot extraction (the only way to test the caller). Not in scope, registered: the AD-583f verifier wiring that never reaches the engine (R1), the Counselor's success-rate input (R2).

## 4. Interaction with the queue

**BF-922 (#1639) merges first.** It changes `cognitive_agent.py`, `sub_tasks/compose.py`, `sub_tasks/evaluate.py`, `sub_tasks/query.py`, `llm_client.py`, `types.py`, `output_grounding.py` (new) and some tests. This contract edits none of them: its files are `cognitive/behavioral_metrics.py`, `runtime.py`, `cognitive/orientation.py`, `proactive.py`, `startup/finalize.py`, `cognitive/counselor.py`, three existing tests, two new tests, `PROGRESS.md` and `DECISIONS.md`. The new tests import `Episode` from `probos.types` (an import only). If BF-922's merge moved any SEARCH text here, the orchestrator re-verifies and re-anchors without changing a REPLACE; a changed REPLACE returns to the Architect.

**Tracker anchors.** `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)` (line 739 on this tree) both stay unique whatever BF-922 inserts.

**PR text, BF-923's part:** "BF-923 (#1652). Three callers passed `agent_id` to `EpisodicMemory.recall`, which takes none, and swallowed the `TypeError`: the behavioral metrics' anchor-grounded emergence was 0 on every dream and every crew orientation counted 0 memories. The metric now reads each author's recent episodes by the sovereign id its episodes carry (Ward Room authors are slot ids; the runtime late-binds the identity registry), and both orientation callers count the agent's own episodes, so at stasis recovery each crew member is told how many memories it has (AD-567g's line, never printed before). The Counselor read trust with a method `TrustNetwork` lacks and Hebbian weights with one nothing defines; it now reads trust with `get_score` and records each reading and the first as a captured baseline, while every assessment, DM, Bridge alert and the agent's own wellness view stay exactly as before until the trust gauge is qualified (BF-921 D3; the measurement is on #1523). The Hebbian read is removed, and a profile keeps its latest 50 assessments."

## 5. Consumers of every value this changes

**(a) The anchor metric** (`anchor_grounded_rate`, `anchor_independence_score`, `anchor_analyzed_threads`), from its one producer call (`dreaming.py:1663`; `compute_behavioral_metrics` has no other caller, section 12):
- `BehavioralSnapshot` → `behavioral_quality_score`, the mean of four or five terms of which `anchor_grounded_rate` is one (`behavioral_metrics.py:202-213`): it rises when threads are grounded.
- `dreaming.py:1668-1682` (a DEBUG line), `:1704` → `_step_15_reflection_promotion` → `[Reflection] Dream cycle emergence snapshot: ... behavioral_quality=<x>.` episode text with no owner (`dreaming.py:2976-2986`), and the dream report (`:1803-1807`, `types.py:914-918`).
- `routers/system.py:682-708` (`/behavioral-metrics` and its history): Captain-facing.
- `AnchorGroundedEmergenceProbe` (`behavioral_probes.py:229-250`), a Tier 3 collective test for `__crew__` with `passed=True` always and the grounded rate as score, run weekly by the drift scheduler (`drift_detector.py:345-357`; `drift_check_tiers` default `[1, 2, 3]`, `config.py:3619`). After a history of zeros, the first non-zero score has |z| = √n for n earlier samples (window 20, `config.py:3617`): `warning` from n = 4 (the Counselor logs only, `counselor.py:1503-1507`), `critical` from n = 9 (`config.py:3615`): the Counselor assesses `__crew__` once on default inputs (no agent: confidence 0.8, every drift 0, wellness 1.0), so `_maybe_send_therapeutic_dm` returns at its first line (`counselor.py:2410-2411`). No crew member is messaged. Disclosed effect E1.
- `BEHAVIORAL_METRICS_UPDATED`: emitted only when `emit_event_fn` is passed (`behavioral_metrics.py:247-260`); the dream path passes none (`dreaming.py:1663-1667`). Unchanged.

**(b) The orientation count** (`episodic_memory_count`): `build_orientation` copies it into `OrientationContext` (`orientation.py:220`); `render_warm_boot_orientation` prints it when above 0 (`:413-416`): **disclosed effect E2**, at stasis recovery each crew member with episodes reads "You have N episodic memories from before stasis." for the first time, a true statement about its own memory (AD-567g's design; not a judgement, so no hold). The cold-start renderer (`:348-354`) receives its count from `agent_onboarding.py:393`, not from these callers. The proactive renderers print no count: no visible change (E3).

**(c) The Counselor's inputs and the profile's lists.**
- `_gather_agent_metrics`' returned dict: the 14 handlers and the API listed in section 1 pass its five keys to `assess_agent`. Values unchanged (D4).
- `trust_observations`, `observed_baseline`: written by `_record_trust_observation`, read by nothing in `src/` but `to_dict`/`from_dict` (new). They reach `profile_json` (`counselor.py:382`), so `/profile/{agent_id}` (`routers/counselor.py:48-64`, clinical access) shows them: the agent's trust, already shown in the clinical trust stream (AD-903). The self-telemetry whitelist (`self_telemetry_domains.py:81-104`) reads neither: crew-facing view unchanged.
- `assessments` (bounded): `add_assessment`'s AD-506b check (`counselor.py:200`), `latest_assessment` (`:213`), `drift_trend` (`:215-221`; read by `self_telemetry_domains.py:104` and `routers/counselor.py:644`), `routers/counselor.py:646` (`[-assess_n:]`, default 10). Each reads at most the last 10 by default.
- `_on_trust_update`'s reassessment loop (`counselor.py:1686-1719`): trigger unchanged (D8); each reassessment now also records one trust reading.

## 6. Milestones and tests

**M1 (STANDARD), §7.1 to §7.7.** First heading: `### 7.1 \`src/probos/cognitive/behavioral_metrics.py\` (M1)`. Commit "BF-923 M1: the anchor metric and the orientation counts read the episodic store through APIs it has", body ending "Ward Room authors are slot ids and episodes carry sovereign ids, so the runtime late-binds the identity registry into the behavioral metrics engine. At stasis recovery each crew member is told its own episode count (AD-567g's line, printed for the first time)."

Before editing, grep the pins: `grep -rn "_compute_anchor_grounded_emergence\|mock_memory.recall\|episodic_memory_count\|Warm boot orientation\|render_warm_boot_orientation" tests/`.

Tests first: with §7.6 and §7.7 applied and §7.1 to §7.5 not, exactly these 9 fail: `test_the_anchor_metric_reads_each_authors_recent_episodes` (`assert 0 == 1` on `analyzed_threads`), `test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry` (`AttributeError: ... 'set_identity_registry'`), `test_a_failing_store_is_reported_once_at_warning` (no WARNING record), `test_the_booted_runtime_reads_crew_authors_episodes` (`assert 0 == 1`), `test_count_agent_episodes_counts_the_agents_own_episodes` and `test_a_failing_count_is_logged_at_warning_and_reports_none` (`ImportError: count_agent_episodes`), `test_the_proactive_supplement_is_built_with_the_agents_episode_count` (`assert 0 == 2`), `test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count` (`ImportError: _orient_crew_after_stasis`), and `TestAnchorGroundedEmergence`'s `test_anchor_analysis_with_memory` in `test_behavioral_metrics.py` (the autospec rejects `recall(query=, agent_id=, limit=)`, which is swallowed: `assert 0 == 1`). `test_the_old_call_is_rejected_by_the_real_recall` (the issue's reproduction) and `test_anchor_insufficient_episodes` pass on both sides. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf923_episodic_recall_callers.py tests/test_behavioral_metrics.py tests/test_orientation.py tests/test_ad576_llm_unavailability.py tests/test_bf235_stale_identity_cache.py tests/test_proactive.py tests/test_dreaming.py tests/test_bf138_sovereign_id_completion.py -n 0 -q
```

(`TestAnchorGroundedEmergence` is the class at `tests/test_behavioral_metrics.py:559`.)

**M2 (HIGH), §7.8 to §7.11.** First heading: `### 7.8 \`src/probos/cognitive/counselor.py\` (M2)`. Commit "BF-923 M2: the Counselor reads trust with get_score and records it; its assessment stays held (BF-921 D3)", body ending "Each trust reading is recorded on the profile with the first as the captured baseline; the assessment keeps TRUST_DEFAULT and the default baseline, so no wellness, DM or Bridge alert follows a reading until the gauge is qualified (measurement on #1523). The Hebbian read is removed. A profile keeps its latest 50 assessments and readings." The tracker entries (section 8) go in this commit.

Before editing, grep the pins: `grep -rn "_trust_network.score\|get_weights_for\|_gather_agent_metrics\|trust_observations\|observed_baseline\|COUNSELOR_PROFILE_HISTORY_LIMIT" tests/`. The 14 `_gather_agent_metrics = MagicMock(...)` replacements (section 11) replace the gather whole and drive the downstream DM logic with chosen inputs; they stay.

Tests first: with §7.9 to §7.11 applied and §7.8 not, exactly these 10 fail: `test_the_trust_reading_uses_get_score_and_is_recorded_not_assessed` (`profile` is None), `test_the_baseline_is_captured_at_the_first_reading_only` (same), `test_a_real_trust_drop_moves_no_assessment_dm_alert_or_wellness_view[trust_update]` and `[qualification_drift]` (`AttributeError: ... 'trust_observations'`; the hold assertions before it pass on the base, which never reads trust), `test_a_failing_trust_read_is_logged_at_warning_and_records_nothing` (no WARNING), `test_the_assessment_list_keeps_the_latest_entries`, `test_a_profile_saved_before_the_bound_loads_its_latest_assessments` and `test_trust_observations_keep_the_latest_readings` (`ImportError: COUNSELOR_PROFILE_HISTORY_LIMIT`), `test_the_readings_survive_the_profile_store` (`AttributeError`), and `TestGatherAgentMetrics::test_trust_from_network` (`profile` is None). `test_the_hebbian_router_is_not_read`, `TestGatherAgentMetrics::test_hebbian_from_router`, `::test_graceful_on_exception` and the three `test_peer_repetition_credits.py` tests pass on both sides. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf923_counselor_assessment_inputs.py tests/test_counselor.py tests/test_counselor_activation.py tests/test_counselor_therapeutic.py tests/test_peer_repetition_credits.py tests/test_bf921_counselor_event_delivery.py tests/test_ad1260_wellness_domain.py tests/test_ad642_communication_benchmarks.py tests/test_ad566c_drift_detection.py tests/test_ad567c_anchor_quality.py tests/test_graduated_zones.py tests/test_ad552_notebook_self_repetition.py tests/test_ad529_contagion_firewall.py tests/test_ad576_llm_unavailability.py -n 0 -q
```

A test elsewhere that fails because a DM, a Bridge alert or a wellness value moved is a breach of the hold: stop and send it to the Architect; never change its assertion to pass.

**The broad gate is run once for #1652 by the main session, not by the Builder.**

## 7. The contract

### 7.1 `src/probos/cognitive/behavioral_metrics.py` (M1)

Pair 1:

SEARCH:
```python
        self._config = config or BehavioralMetricsConfig()
        self._snapshots: deque[BehavioralSnapshot] = deque(maxlen=self._config.max_snapshots)
        self._verifier = observable_state_verifier

    def set_observable_verifier(self, verifier: Any) -> None:
        """AD-583f: Late-bind observable state verifier."""
        self._verifier = verifier
```
REPLACE:
```python
        self._config = config or BehavioralMetricsConfig()
        self._snapshots: deque[BehavioralSnapshot] = deque(maxlen=self._config.max_snapshots)
        self._verifier = observable_state_verifier
        self._identity_registry: Any = None  # BF-923 (#1652): slot id -> sovereign id for episode reads

    def set_observable_verifier(self, verifier: Any) -> None:
        """AD-583f: Late-bind observable state verifier."""
        self._verifier = verifier

    def set_identity_registry(self, identity_registry: Any) -> None:
        """BF-923 (#1652): late-bind the registry that maps a Ward Room author's slot id to the
        sovereign id its episodes carry (BF-138). Without one, each author is read by its own id."""
        self._identity_registry = identity_registry
```

Pair 2:

SEARCH:
```python
        independence_scores: list[float] = []
        grounded_count = 0
        analyzed = 0

        for thread in threads:
            agent_ids = list(thread["unique_authors"])
            if len(agent_ids) < 2:
                continue

            try:
                all_episodes: list[Any] = []
                for agent_id in agent_ids[:5]:
                    eps = await episodic_memory.recall(
                        query="",
                        agent_id=agent_id,
                        limit=10,
                    )
                    if eps:
                        all_episodes.extend(eps)

                if len(all_episodes) < cfg.anchor_independence_min_episodes:
                    continue

                independence = compute_anchor_independence(all_episodes)
                independence_scores.append(independence)
                analyzed += 1

                if independence > 0.3:
                    grounded_count += 1

            except Exception:
                logger.debug(
                    "AD-569: Anchor analysis failed for thread %s",
                    thread.get("thread_id"),
                )
                continue

        mean_independence = (
```
REPLACE:
```python
        from probos.cognitive.episodic import resolve_sovereign_id_from_slot

        independence_scores: list[float] = []
        grounded_count = 0
        analyzed = 0
        failures = 0

        for thread in threads:
            agent_ids = list(thread["unique_authors"])
            if len(agent_ids) < 2:
                continue

            try:
                all_episodes: list[Any] = []
                for agent_id in agent_ids[:5]:
                    # BF-923 (#1652): AD-569's "recent episodes". recall() takes no agent_id (every
                    # call raised), and a Ward Room author is a slot id while its episodes carry
                    # the sovereign id.
                    owner_id = resolve_sovereign_id_from_slot(agent_id, self._identity_registry)
                    eps = await episodic_memory.recent_for_agent(owner_id, k=10)
                    if eps:
                        all_episodes.extend(eps)

                if len(all_episodes) < cfg.anchor_independence_min_episodes:
                    continue

                independence = compute_anchor_independence(all_episodes)
                independence_scores.append(independence)
                analyzed += 1

                if independence > 0.3:
                    grounded_count += 1

            except Exception:
                failures += 1  # BF-923: counted, reported once below
                logger.debug(
                    "AD-569: Anchor analysis failed for thread %s",
                    thread.get("thread_id"),
                    exc_info=True,
                )
                continue

        if failures:
            logger.warning(
                "BF-923 (#1652): anchor analysis failed for %d of %d threads; the anchor metric covers the rest",
                failures,
                len(threads),
            )

        mean_independence = (
```

### 7.2 `src/probos/runtime.py` (M1)

SEARCH:
```python
        self._behavioral_metrics_engine = dream_result.behavioral_metrics_engine  # AD-569
        self.task_scheduler = dream_result.task_scheduler
```
REPLACE:
```python
        self._behavioral_metrics_engine = dream_result.behavioral_metrics_engine  # AD-569
        if self._behavioral_metrics_engine is not None:
            # BF-923 (#1652): Ward Room authors are slot ids; their episodes carry sovereign ids.
            self._behavioral_metrics_engine.set_identity_registry(self.identity_registry)
        self.task_scheduler = dream_result.task_scheduler
```

### 7.3 `src/probos/cognitive/orientation.py` (M1)

SEARCH:
```python
    else:
        return "first"


class OrientationService:
    """Builds structured orientation context for agent cognitive grounding."""
```
REPLACE:
```python
    else:
        return "first"


async def count_agent_episodes(episodic_memory: Any, agent: Any) -> int:
    """BF-923 (#1652): how many episodes the agent owns, for its orientation (0 when unknown).

    Episodes carry the agent's sovereign id (AD-441, BF-138); an agent without one is counted by
    its slot id, as the orientation callers always resolved it. Before BF-923 both callers passed
    ``agent_id`` to ``EpisodicMemory.recall``, which takes none, and swallowed the ``TypeError``,
    so every count was 0.
    """
    if not episodic_memory:
        return 0
    owner_id = getattr(agent, "sovereign_id", None) or agent.id
    try:
        return await episodic_memory.count_for_agent(owner_id)
    except Exception:
        logger.warning(
            "BF-923: episode count failed for %s; the orientation reports none",
            owner_id,
            exc_info=True,
        )
        return 0


class OrientationService:
    """Builds structured orientation context for agent cognitive grounding."""
```

### 7.4 `src/probos/proactive.py` (M1)

Pair 1:

SEARCH:
```python
from probos.cognitive.orientation import OrientationContext, derive_watch_section
```
REPLACE:
```python
from probos.cognitive.orientation import OrientationContext, count_agent_episodes, derive_watch_section
```

Pair 2:

SEARCH:
```python
                        _ep_count = 0
                        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
                            try:
                                _sid = getattr(agent, 'sovereign_id', None) or agent.id
                                _eps = await rt.episodic_memory.recall("", agent_id=_sid, k=1)
                                _ep_count = len(_eps) if _eps else 0
                            except Exception:
                                pass
                        _ctx = self._orientation_service.build_orientation(
```
REPLACE:
```python
                        # BF-923 (#1652): the agent's own count; recall() takes no agent_id, so it was always 0.
                        _ep_count = await count_agent_episodes(getattr(rt, 'episodic_memory', None), agent)
                        _ctx = self._orientation_service.build_orientation(
```

### 7.5 `src/probos/startup/finalize.py` (M1)

Pair 1 (the extracted function, before `finalize_startup`):

SEARCH:
```python
    return True


async def finalize_startup(
    *,
    runtime: Any,  # ProbOSRuntime — passed as Any to avoid circular import
```
REPLACE:
```python
    return True


async def _orient_crew_after_stasis(*, runtime: Any) -> int:
    """AD-567g: warm-boot orientation for each crew agent after stasis; returns how many were set.

    BF-923 (#1652): moved out of ``finalize_startup`` unchanged except for the episode count, which
    is now the agent's own (``count_agent_episodes``). Before BF-923 the count came from
    ``EpisodicMemory.recall(..., agent_id=...)``, which takes no ``agent_id``; the ``TypeError`` was
    swallowed, so every count was 0 and no crew member read "You have N episodic memories from
    before stasis."
    """
    from probos.cognitive.orientation import count_agent_episodes

    oriented = 0
    try:
        # AD-513: Build crew names lookup for orientation
        _all_crew_names: dict[str, str] = {}
        if hasattr(runtime, 'callsign_registry') and runtime.callsign_registry:
            _all_crew_names = runtime.callsign_registry.all_callsigns()

        # BF-144: Compute authoritative stasis timestamps (once, before agent loop)
        _shutdown_str = ""
        _resume_str = ""
        if runtime._previous_session and "shutdown_time_utc" in runtime._previous_session:
            _shutdown_str = datetime.fromtimestamp(
                runtime._previous_session["shutdown_time_utc"], tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
            _resume_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        for agent in runtime.registry.all():
            if is_crew_agent(agent, runtime.ontology):
                _ep_count = await count_agent_episodes(runtime.episodic_memory, agent)  # BF-923 (#1652)
                _trust = 0.5
                if runtime.trust_network:
                    try:
                        _trust = runtime.trust_network.get_score(agent.id)
                    except Exception:
                        pass
                # AD-513: Crew names excluding self
                _crew_names = sorted(
                    cs for at, cs in _all_crew_names.items()
                    if cs and at != agent.agent_type
                )
                _ctx = runtime._orientation_service.build_orientation(
                    agent,
                    lifecycle_state="stasis_recovery",
                    stasis_duration=runtime._stasis_duration,
                    stasis_shutdown_utc=_shutdown_str,       # BF-144
                    stasis_resume_utc=_resume_str,           # BF-144
                    episodic_memory_count=_ep_count,
                    trust_score=_trust,
                    crew_names=_crew_names,
                )
                _rendered = runtime._orientation_service.render_warm_boot_orientation(_ctx)
                agent.set_orientation(_rendered, _ctx)
                oriented += 1  # BF-923: one per crew agent oriented
                logger.debug(
                    "BF-235: %s orientation set — callsign=%s",
                    agent.agent_type,
                    getattr(agent, 'callsign', '?'),
                )
        logger.info("AD-567g: Warm boot orientation set for crew agents")
    except Exception:
        logger.debug("AD-567g: Warm boot orientation failed", exc_info=True)
    return oriented


async def finalize_startup(
    *,
    runtime: Any,  # ProbOSRuntime — passed as Any to avoid circular import
```

Pair 2 (the call site):

SEARCH:
```python
    # AD-567g: Warm boot orientation for stasis recovery
    if (hasattr(runtime, '_orientation_service') and runtime._orientation_service
            and runtime._lifecycle_state == "stasis_recovery"
            and config.orientation.warm_boot_orientation):
        try:
            # AD-513: Build crew names lookup for orientation
            _all_crew_names: dict[str, str] = {}
            if hasattr(runtime, 'callsign_registry') and runtime.callsign_registry:
                _all_crew_names = runtime.callsign_registry.all_callsigns()

            # BF-144: Compute authoritative stasis timestamps (once, before agent loop)
            _shutdown_str = ""
            _resume_str = ""
            if runtime._previous_session and "shutdown_time_utc" in runtime._previous_session:
                _shutdown_str = datetime.fromtimestamp(
                    runtime._previous_session["shutdown_time_utc"], tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
                _resume_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            for agent in runtime.registry.all():
                if is_crew_agent(agent, runtime.ontology):
                    _ep_count = 0
                    if runtime.episodic_memory:
                        try:
                            _sid = getattr(agent, 'sovereign_id', None) or agent.id
                            _eps = await runtime.episodic_memory.recall("", agent_id=_sid, k=1)
                            _ep_count = len(_eps) if _eps else 0
                        except Exception:
                            pass
                    _trust = 0.5
                    if runtime.trust_network:
                        try:
                            _trust = runtime.trust_network.get_score(agent.id)
                        except Exception:
                            pass
                    # AD-513: Crew names excluding self
                    _crew_names = sorted(
                        cs for at, cs in _all_crew_names.items()
                        if cs and at != agent.agent_type
                    )
                    _ctx = runtime._orientation_service.build_orientation(
                        agent,
                        lifecycle_state="stasis_recovery",
                        stasis_duration=runtime._stasis_duration,
                        stasis_shutdown_utc=_shutdown_str,       # BF-144
                        stasis_resume_utc=_resume_str,           # BF-144
                        episodic_memory_count=_ep_count,
                        trust_score=_trust,
                        crew_names=_crew_names,
                    )
                    _rendered = runtime._orientation_service.render_warm_boot_orientation(_ctx)
                    agent.set_orientation(_rendered, _ctx)
                    logger.debug(
                        "BF-235: %s orientation set — callsign=%s",
                        agent.agent_type,
                        getattr(agent, 'callsign', '?'),
                    )
            logger.info("AD-567g: Warm boot orientation set for crew agents")
        except Exception:
            logger.debug("AD-567g: Warm boot orientation failed", exc_info=True)
```
REPLACE:
```python
    # AD-567g: Warm boot orientation for stasis recovery
    if (hasattr(runtime, '_orientation_service') and runtime._orientation_service
            and runtime._lifecycle_state == "stasis_recovery"
            and config.orientation.warm_boot_orientation):
        await _orient_crew_after_stasis(runtime=runtime)  # BF-923 (#1652): extracted, count repaired
```

### 7.6 `tests/test_behavioral_metrics.py` (M1: the two unrestricted stores)

Pair 1:

SEARCH:
```python
from unittest.mock import AsyncMock, MagicMock, patch
```
REPLACE:
```python
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
```

Pair 2:

SEARCH:
```python
from probos.config import BehavioralMetricsConfig, SystemConfig
```
REPLACE:
```python
from probos.cognitive.episodic import EpisodicMemory
from probos.config import BehavioralMetricsConfig, SystemConfig
```

Pair 3:

SEARCH:
```python
        mock_memory = AsyncMock()
        mock_ep = MagicMock()
        mock_memory.recall = AsyncMock(return_value=[mock_ep, mock_ep])

        with patch(
            "probos.cognitive.social_verification.compute_anchor_independence",
            return_value=0.6,
        ):
            result = await engine._compute_anchor_grounded_emergence(threads, mock_memory)
            assert result["analyzed_threads"] == 1
            assert result["independence_score"] == 0.6
            assert result["grounded_rate"] == 1.0
```
REPLACE:
```python
        # BF-923 (#1652): built from EpisodicMemory, so a call the store does not accept fails here.
        # The unrestricted AsyncMock this replaces accepted recall(query=, agent_id=, limit=), which
        # raises TypeError on the real store; that is how the metric stayed 0 with this test green.
        mock_memory = create_autospec(EpisodicMemory, instance=True)
        mock_ep = MagicMock()
        mock_memory.recent_for_agent.return_value = [mock_ep, mock_ep]

        with patch(
            "probos.cognitive.social_verification.compute_anchor_independence",
            return_value=0.6,
        ):
            result = await engine._compute_anchor_grounded_emergence(threads, mock_memory)
            assert result["analyzed_threads"] == 1
            assert result["independence_score"] == 0.6
            assert result["grounded_rate"] == 1.0
        mock_memory.recent_for_agent.assert_any_await("a1", k=10)
        mock_memory.recent_for_agent.assert_any_await("a2", k=10)
```

Pair 4:

SEARCH:
```python
        mock_memory = AsyncMock()
        mock_memory.recall = AsyncMock(return_value=[MagicMock()])  # Only 1 episode per agent = 2 total < 5
```
REPLACE:
```python
        # BF-923 (#1652): built from EpisodicMemory (the AsyncMock accepted a recall() call that raises).
        mock_memory = create_autospec(EpisodicMemory, instance=True)
        mock_memory.recent_for_agent.return_value = [MagicMock()]  # Only 1 episode per agent = 2 total < 5
```

### 7.7 New file: `tests/test_bf923_episodic_recall_callers.py` (M1)

```python
"""BF-923 (#1652) M1: the behavioral-metric and orientation callers read the episodic store through APIs it has.

Every store here is a real ``EpisodicMemory`` unless a test is about a failing store, where the double is
``create_autospec(EpisodicMemory, instance=True)`` (signatures checked; results set by the test).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.config import BehavioralMetricsConfig, SystemConfig
from probos.types import Episode


async def _store(tmp_path: Path, owners: dict[str, int]) -> EpisodicMemory:
    """A started real store holding ``n`` distinct episodes for each owner id."""
    memory = EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db"))
    await memory.start()
    now = time.time()
    for owner, count in owners.items():
        for i in range(count):
            await memory.store(
                Episode(
                    user_input=f"[BF-923] {owner} observation {i}",
                    timestamp=now - 60.0 * (i + 1),
                    agent_ids=[owner],
                    source="direct",
                )
            )
    return memory


def _thread(*authors: str, thread_id: str = "bf923-t1") -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "posts": [{"author_id": author, "body": f"post by {author}"} for author in authors],
        "unique_authors": set(authors),
        "channel_id": "ch-1",
        "channel_name": "science",
        "title": "BF-923 thread",
    }


# --- the reproduction ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_old_call_is_rejected_by_the_real_recall(tmp_path) -> None:
    """#1652's reproduction: ``recall`` takes no ``agent_id``. Passes before and after BF-923."""
    memory = await _store(tmp_path, {"sov-a": 1})
    try:
        with pytest.raises(TypeError, match="agent_id"):
            await memory.recall("", agent_id="sov-a", k=1)
    finally:
        await memory.stop()


# --- the anchor metric -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_anchor_metric_reads_each_authors_recent_episodes(tmp_path) -> None:
    """Four episodes are needed, so both authors' two must be read."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
        result = await engine._compute_anchor_grounded_emergence([_thread("author-a", "author-b")], memory)
    finally:
        await memory.stop()

    assert result["analyzed_threads"] == 1
    assert 0.0 <= result["independence_score"] <= 1.0


@pytest.mark.asyncio
async def test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry(tmp_path) -> None:
    """Ward Room posts carry slot ids; episodes carry the sovereign id the identity registry issued."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.identity import AgentIdentityRegistry

    registry = AgentIdentityRegistry(data_dir=tmp_path)
    await registry.start()
    try:
        slots = ("scout_0_bf923", "scout_1_bf923")
        certs = [
            await registry.resolve_or_issue(
                slot_id=slot,
                agent_type="scout",
                callsign=callsign,
                instance_id="bf923",
                vessel_name="ProbOS",
                department="science",
                post_id="scout",
                baseline_version="v0",
            )
            for slot, callsign in zip(slots, ("Wesley", "Reyes"))
        ]
        assert all(cert.agent_uuid not in slots for cert in certs)
        memory = await _store(tmp_path, {cert.agent_uuid: 2 for cert in certs})
        try:
            engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
            engine.set_identity_registry(registry)
            result = await engine._compute_anchor_grounded_emergence([_thread(*slots)], memory)
        finally:
            await memory.stop()
    finally:
        await registry.stop()

    assert result["analyzed_threads"] == 1


@pytest.mark.asyncio
async def test_a_failing_store_is_reported_once_at_warning(caplog) -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    memory.recent_for_agent.side_effect = RuntimeError("store offline")
    threads = [_thread("a1", "a2"), _thread("a3", "a4", thread_id="bf923-t2")]

    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.behavioral_metrics"):
        result = await engine._compute_anchor_grounded_emergence(threads, memory)

    assert result["analyzed_threads"] == 0
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "anchor analysis failed for 2 of 2 threads" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_booted_runtime_reads_crew_authors_episodes(tmp_path) -> None:
    """The seam: the engine the runtime built, with the identity registry the runtime bound, on the
    runtime's own store, for crew agents whose sovereign ids startup issued."""
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(
        config=SystemConfig(),
        data_dir=tmp_path,
        episodic_memory=EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db")),  # a default boot has none
    )
    await rt.start()
    try:
        crew = [
            agent for agent in rt.registry.all()
            if isinstance(agent, CognitiveAgent)
            and getattr(agent, "did", "")  # crew carry a birth certificate; utility agents hold asset tags
            and getattr(agent, "sovereign_id", "")
            and agent.sovereign_id != agent.id
        ][:2]
        assert len(crew) == 2  # a shortfall is a hard stop for the Architect (section 17), not a reason to stub
        assert rt.episodic_memory is not None
        assert rt._behavioral_metrics_engine is not None
        for agent in crew:
            for i in range(2):
                await rt.episodic_memory.store(
                    Episode(
                        user_input=f"[BF-923] {agent.id} booted observation {i}",
                        timestamp=time.time() - 60.0 * (i + 1),
                        agent_ids=[agent.sovereign_id],
                        source="direct",
                    )
                )
        result = await rt._behavioral_metrics_engine._compute_anchor_grounded_emergence(
            [_thread(crew[0].id, crew[1].id)], rt.episodic_memory,
        )
    finally:
        await rt.stop()

    assert result["analyzed_threads"] == 1


# --- the orientation count ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_agent_episodes_counts_the_agents_own_episodes(tmp_path) -> None:
    from probos.cognitive.orientation import count_agent_episodes

    memory = await _store(tmp_path, {"sov-a": 3, "slot-b": 1})
    try:
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-a", sovereign_id="sov-a")) == 3
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-b", sovereign_id=None)) == 1
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-c", sovereign_id="sov-c")) == 0
        assert await count_agent_episodes(None, SimpleNamespace(id="slot-a", sovereign_id="sov-a")) == 0
    finally:
        await memory.stop()


@pytest.mark.asyncio
async def test_a_failing_count_is_logged_at_warning_and_reports_none(caplog) -> None:
    from probos.cognitive.orientation import count_agent_episodes

    memory = create_autospec(EpisodicMemory, instance=True)
    memory.count_for_agent.side_effect = RuntimeError("store offline")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.orientation"):
        count = await count_agent_episodes(memory, SimpleNamespace(id="slot-a", sovereign_id="sov-a"))

    assert count == 0
    assert "BF-923: episode count failed for sov-a" in caplog.text


def _proactive_loop() -> tuple[Any, Any]:
    """The runtime shape ``tests/test_ad576_llm_unavailability.py::_make_loop`` builds."""
    from probos.consensus.trust import TrustNetwork
    from probos.crew_profile import CallsignRegistry
    from probos.knowledge.records_store import RecordsStore
    from probos.proactive import ProactiveCognitiveLoop
    from probos.runtime import ProbOSRuntime
    from probos.substrate.registry import AgentRegistry
    from probos.ward_room import WardRoomService
    from probos.ward_room_router import WardRoomRouter

    loop = ProactiveCognitiveLoop(interval=60, cooldown=60)
    rt = MagicMock(spec=ProbOSRuntime)
    rt.ward_room = MagicMock(spec=WardRoomService)
    rt.ward_room.list_channels = AsyncMock(return_value=[])
    rt.ward_room.create_thread = AsyncMock()
    rt.ward_room.get_thread = AsyncMock(return_value=None)
    rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_score = MagicMock(return_value=0.6)
    rt.trust_network.record_outcome = MagicMock(return_value=0.6)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)
    rt.ward_room_router.extract_endorsements = MagicMock(return_value=("", []))
    rt.ward_room_router.deliver_bridge_alert = AsyncMock()
    rt._records_store = AsyncMock(spec=RecordsStore)
    rt._records_store.write_notebook = AsyncMock()
    rt.ontology = None
    rt.callsign_registry = MagicMock(spec=CallsignRegistry)
    rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")
    rt.config = SystemConfig()
    rt.episodic_memory = None
    rt.bridge_alerts = MagicMock()
    rt.event_log = None
    rt.skill_service = None
    rt.hebbian_router = None
    rt.acm = None
    rt.registry = MagicMock(spec=AgentRegistry)
    loop.set_runtime(rt)
    return loop, rt


@pytest.mark.asyncio
async def test_the_proactive_supplement_is_built_with_the_agents_episode_count(tmp_path) -> None:
    """The caller: ``ProactiveCognitiveLoop._gather_context`` on a real store, for an agent inside its
    orientation window (the default ``orientation`` config: supplement on, 600 s window)."""
    from probos.cognitive.orientation import OrientationContext, OrientationService
    from probos.substrate.agent import BaseAgent

    loop, rt = _proactive_loop()
    memory = await _store(tmp_path, {"sov-a": 2})
    rt.episodic_memory = memory
    service = create_autospec(OrientationService, instance=True)
    service.build_orientation.return_value = OrientationContext()
    service.render_proactive_orientation.return_value = "ORIENTATION: ground claims in evidence."
    loop._orientation_service = service
    loop._config = MagicMock()
    agent = MagicMock(spec=BaseAgent)
    agent.id = "slot-a"
    agent.agent_type = "scout"
    agent.is_alive = True
    agent.sovereign_id = "sov-a"
    agent._birth_timestamp = time.time() - 60

    try:
        context = await loop._gather_context(agent, 0.6)
    finally:
        await memory.stop()

    assert service.build_orientation.call_args.kwargs["episodic_memory_count"] == 2
    assert context["orientation_supplement"] == "ORIENTATION: ground claims in evidence."


class _StasisCrewMember:
    """A crew agent as the warm-boot loop reads it: identity fields and ``set_orientation``."""

    def __init__(self, agent_type: str, slot_id: str, sovereign_id: str | None, callsign: str) -> None:
        self.agent_type = agent_type
        self.id = slot_id
        self.sovereign_id = sovereign_id
        self.callsign = callsign
        self.orientation_text = ""

    def set_orientation(self, rendered: str, ctx: Any) -> None:
        self.orientation_text = rendered


@pytest.mark.asyncio
async def test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count(tmp_path) -> None:
    """The caller: finalize's stasis-recovery orientation, with the real OrientationService."""
    from probos.cognitive.orientation import OrientationService
    from probos.startup.finalize import _orient_crew_after_stasis

    memory = await _store(tmp_path, {"sov-scout": 3, "counselor-0": 1})
    scout = _StasisCrewMember("scout", "scout-0", "sov-scout", "Wesley")
    counselor = _StasisCrewMember("counselor", "counselor-0", None, "Troi")
    architect = _StasisCrewMember("architect", "architect-0", "sov-architect", "Number One")
    runtime = SimpleNamespace(
        _orientation_service=OrientationService(config=SystemConfig()),
        registry=SimpleNamespace(all=lambda: [scout, counselor, architect]),
        ontology=None,
        episodic_memory=memory,
        trust_network=None,
        callsign_registry=None,
        _previous_session=None,
        _stasis_duration=3600.0,
    )
    try:
        oriented = await _orient_crew_after_stasis(runtime=runtime)
    finally:
        await memory.stop()

    assert oriented == 3
    assert "You have 3 episodic memories from before stasis." in scout.orientation_text
    assert "You have 1 episodic memories from before stasis." in counselor.orientation_text
    assert "STASIS RECORD" in architect.orientation_text
    assert "episodic memories from before stasis" not in architect.orientation_text
```

### 7.8 `src/probos/cognitive/counselor.py` (M2)

Pair 1 (the bound):

SEARCH:
```python
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cognitive Profile — the Counselor's assessment record per agent
```
REPLACE:
```python
logger = logging.getLogger(__name__)

#: BF-923 (#1652): the most assessments and trust readings a profile keeps. The profile is rewritten
#: whole on every assessment (``CounselorProfileStore.save_profile``); the full history stays in the
#: ``assessments`` table. Readers take the last 3 (AD-506b), 5 (``drift_trend``) or 10 (AD-903).
COUNSELOR_PROFILE_HISTORY_LIMIT = 50


# ---------------------------------------------------------------------------
# Cognitive Profile — the Counselor's assessment record per agent
```

Pair 2 (the profile's readings and the bounded append):

SEARCH:
```python
    # AD-567c: Anchor quality
    anchor_quality: float = 0.0             # Mean anchor confidence from latest AnchorProfile
    weakest_anchor_dimension: str = ""      # For targeted metacognitive coaching

    def add_assessment(self, assessment: CounselorAssessment) -> None:
        """Append an assessment and update alert level."""
        self.assessments.append(assessment)
        self.last_assessed = assessment.timestamp
```
REPLACE:
```python
    # AD-567c: Anchor quality
    anchor_quality: float = 0.0             # Mean anchor confidence from latest AnchorProfile
    weakest_anchor_dimension: str = ""      # For targeted metacognitive coaching
    # BF-923 (#1652): trust readings, recorded and not assessed until the gauge is qualified (#1523)
    observed_baseline: CognitiveBaseline | None = None  # the first reading
    trust_observations: list[list[float]] = field(default_factory=list)  # [timestamp, score], latest last

    def add_assessment(self, assessment: CounselorAssessment) -> None:
        """Append an assessment and update alert level (BF-923: the latest ``COUNSELOR_PROFILE_HISTORY_LIMIT`` are kept)."""
        self.assessments.append(assessment)
        del self.assessments[:-COUNSELOR_PROFILE_HISTORY_LIMIT]
        self.last_assessed = assessment.timestamp
```

Pair 3 (`to_dict`):

SEARCH:
```python
            "anchor_quality": self.anchor_quality,
            "weakest_anchor_dimension": self.weakest_anchor_dimension,
        }
```
REPLACE:
```python
            "anchor_quality": self.anchor_quality,
            "weakest_anchor_dimension": self.weakest_anchor_dimension,
            "observed_baseline": self.observed_baseline.to_dict() if self.observed_baseline else None,
            "trust_observations": [list(entry) for entry in self.trust_observations],
        }
```

Pair 4 (`from_dict`):

SEARCH:
```python
        if "baseline" in data:
            profile.baseline = CognitiveBaseline.from_dict(data["baseline"])
        if "assessments" in data:
            profile.assessments = [CounselorAssessment.from_dict(a) for a in data["assessments"]]
        return profile
```
REPLACE:
```python
        if "baseline" in data:
            profile.baseline = CognitiveBaseline.from_dict(data["baseline"])
        if "assessments" in data:
            # BF-923 (#1652): a profile saved before the bound loads its latest entries only.
            recent = data["assessments"][-COUNSELOR_PROFILE_HISTORY_LIMIT:]
            profile.assessments = [CounselorAssessment.from_dict(a) for a in recent]
        if data.get("observed_baseline"):
            profile.observed_baseline = CognitiveBaseline.from_dict(data["observed_baseline"])
        profile.trust_observations = [
            [float(when), float(score)]
            for when, score in (data.get("trust_observations") or [])[-COUNSELOR_PROFILE_HISTORY_LIMIT:]
        ]
        return profile
```

Pair 5 (the reads):

SEARCH:
```python
    def _gather_agent_metrics(self, agent_id: str) -> dict[str, float]:
        """Pull metrics from runtime services for an agent.

        Gracefully degrades — returns sensible defaults when services unavailable.
        """
        metrics: dict[str, float] = {
            "trust_score": TRUST_DEFAULT,
            "confidence": 0.8,
            "hebbian_avg": 0.0,
            "success_rate": 0.0,
            "personality_drift": 0.0,
        }

        # Trust score
        if self._trust_network:
            try:
                score = self._trust_network.score(agent_id)
                if score is not None:
                    metrics["trust_score"] = score
            except Exception:
                logger.debug("Failed to get trust for %s", agent_id, exc_info=True)

        # Hebbian average weight
        if self._hebbian_router:
            try:
                weights = self._hebbian_router.get_weights_for(agent_id)
                if weights:
                    metrics["hebbian_avg"] = sum(weights.values()) / len(weights)
            except Exception:
                logger.debug("Failed to get Hebbian for %s", agent_id, exc_info=True)
```
REPLACE:
```python
    def _gather_agent_metrics(self, agent_id: str) -> dict[str, float]:
        """Pull metrics from runtime services for an agent.

        Gracefully degrades — returns sensible defaults when services unavailable.

        BF-923 (#1652): trust is read with ``TrustNetwork.get_score`` (the ``score`` called before is
        ``TrustRecord``'s property, not the network's, so every read failed) and each reading is
        recorded on the profile (``_record_trust_observation``). The returned ``trust_score`` stays
        ``TRUST_DEFAULT``, as every production assessment has had it, so no wellness change, DM or
        Bridge alert follows a reading until the trust gauge is qualified (BF-921 D3; the measurement
        is on #1523). ``hebbian_avg`` stays 0.0 and the Hebbian router is not read: no per-agent
        Hebbian reading is defined (the ``get_weights_for`` called before never existed).
        """
        metrics: dict[str, float] = {
            "trust_score": TRUST_DEFAULT,  # BF-923: held until the trust gauge is qualified (#1523)
            "confidence": 0.8,
            "hebbian_avg": 0.0,  # BF-923: not read (no per-agent Hebbian reading is defined)
            "success_rate": 0.0,
            "personality_drift": 0.0,
        }

        # Trust score: read and recorded, not assessed (BF-923)
        observed_trust: float | None = None
        if self._trust_network:
            try:
                observed_trust = float(self._trust_network.get_score(agent_id))
            except Exception:
                logger.warning("BF-923: trust read failed for %s; nothing recorded", agent_id, exc_info=True)
```

Pair 6 (the record, after the remaining reads):

SEARCH:
```python
                    metrics["personality_drift"] = getattr(cp, "personality_drift", 0.0)
            except Exception:
                logger.debug("Failed to get crew profile for %s", agent_id, exc_info=True)

        return metrics

    # -- AD-503: Wellness sweep --
```
REPLACE:
```python
                    metrics["personality_drift"] = getattr(cp, "personality_drift", 0.0)
            except Exception:
                logger.debug("Failed to get crew profile for %s", agent_id, exc_info=True)

        if observed_trust is not None:
            self._record_trust_observation(agent_id, observed_trust, metrics)
        return metrics

    def _record_trust_observation(
        self, agent_id: str, observed_trust: float, metrics: dict[str, float],
    ) -> None:
        """BF-923 (#1652): record one trust reading; the first one is the captured baseline.

        A record only: ``assess_agent`` reads ``profile.baseline`` and the held metrics, never these,
        so an assessment, its DM and its Bridge alert are as before until the gauge is qualified.
        """
        profile = self.get_or_create_profile(agent_id)
        now = time.time()
        if profile.observed_baseline is None:
            profile.observed_baseline = CognitiveBaseline(
                trust_score=observed_trust,
                confidence=metrics["confidence"],
                success_rate=metrics["success_rate"],
                captured_at=now,
            )
        profile.trust_observations.append([now, observed_trust])
        del profile.trust_observations[:-COUNSELOR_PROFILE_HISTORY_LIMIT]

    # -- AD-503: Wellness sweep --
```

### 7.9 `tests/test_counselor_activation.py` (M2: the pins of `score` and `get_weights_for`)

Pair 1:

SEARCH:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.llm_client import BaseLLMClient
```
REPLACE:
```python
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest

from probos.cognitive.llm_client import BaseLLMClient
```

Pair 2:

SEARCH:
```python
    def test_trust_from_network(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = MagicMock()
        trust.score.return_value = 0.85
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["trust_score"] == 0.85

    def test_hebbian_from_router(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        router = MagicMock()
        router.get_weights_for.return_value = {"a": 0.4, "b": 0.6}
        agent._hebbian_router = router
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["hebbian_avg"] == pytest.approx(0.5)
```
REPLACE:
```python
    def test_trust_from_network(self) -> None:
        # BF-923 (#1652): this pinned TrustNetwork.score, which the network lacks (it is TrustRecord's
        # property), through a MagicMock that accepted it; production read nothing. The read is now
        # get_score on a real network; the reading is recorded on the profile, and the returned
        # trust_score stays TRUST_DEFAULT until the gauge is qualified (BF-921 D3).
        from probos.cognitive.counselor import CounselorAgent
        from probos.consensus.trust import TrustNetwork
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = TrustNetwork()
        trust.create_with_prior("agent-1", alpha=8.5, beta=1.5)
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["trust_score"] == 0.5
        profile = agent.get_profile("agent-1")
        assert profile.trust_observations[-1][1] == pytest.approx(0.85)
        assert profile.observed_baseline.trust_score == pytest.approx(0.85)

    def test_hebbian_from_router(self) -> None:
        # BF-923 (#1652): this pinned HebbianRouter.get_weights_for, which never existed, through a
        # MagicMock that accepted it. No per-agent Hebbian reading is defined, so none is taken.
        from probos.cognitive.counselor import CounselorAgent
        from probos.mesh.routing import HebbianRouter
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        router = create_autospec(HebbianRouter, instance=True)
        agent._hebbian_router = router
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["hebbian_avg"] == 0.0
        assert router.mock_calls == []
```

Pair 3:

SEARCH:
```python
    def test_graceful_on_exception(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = MagicMock()
        trust.score.side_effect = RuntimeError("boom")
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        # Should fall back to default
        assert metrics["trust_score"] == 0.5
```
REPLACE:
```python
    def test_graceful_on_exception(self) -> None:
        # BF-923 (#1652): the double now has TrustNetwork's signature (get_score), not the absent score.
        from probos.cognitive.counselor import CounselorAgent
        from probos.consensus.trust import TrustNetwork
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = create_autospec(TrustNetwork, instance=True)
        trust.get_score.side_effect = RuntimeError("boom")
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        # Should fall back to default, and record nothing
        assert metrics["trust_score"] == 0.5
        assert agent.get_profile("agent-1") is None
```

### 7.10 `tests/test_peer_repetition_credits.py` (M2: the three trust doubles)

Pair 1:

SEARCH:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from probos.cognitive.llm_client import BaseLLMClient
from probos.events import EventType
```
REPLACE:
```python
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
import pytest_asyncio

from probos.cognitive.llm_client import BaseLLMClient
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
```

Pair 2:

SEARCH:
```python
    async def test_amber_to_green_gets_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
```
REPLACE:
```python
    async def test_amber_to_green_gets_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # BF-923 (#1652): TrustNetwork's signature; the MagicMock's score was an API the network lacks.
        agent._trust_network = create_autospec(TrustNetwork, instance=True)
        agent._trust_network.get_score.return_value = 0.7
```

Pair 3:

SEARCH:
```python
    async def test_red_to_amber_no_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
```
REPLACE:
```python
    async def test_red_to_amber_no_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # BF-923 (#1652): TrustNetwork's signature; the MagicMock's score was an API the network lacks.
        agent._trust_network = create_autospec(TrustNetwork, instance=True)
        agent._trust_network.get_score.return_value = 0.7
```

Pair 4:

SEARCH:
```python
    async def test_peer_catches_incremented(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
```
REPLACE:
```python
    async def test_peer_catches_incremented(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # BF-923 (#1652): TrustNetwork's signature; the MagicMock's score was an API the network lacks.
        agent._trust_network = create_autospec(TrustNetwork, instance=True)
        agent._trust_network.get_score.return_value = 0.7
```

### 7.11 New file: `tests/test_bf923_counselor_assessment_inputs.py` (M2)

```python
"""BF-923 (#1652) M2: the Counselor reads real trust and records it; its assessment stays held (BF-921 D3).

Every trust network here is a real ``TrustNetwork`` unless a test is about a failing read, where the double
is ``create_autospec(TrustNetwork, instance=True)``.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from probos.cognitive.llm_client import BaseLLMClient
from probos.config import TRUST_DEFAULT
from probos.consensus.trust import TrustNetwork


def _counselor(trust: Any = None) -> Any:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = trust
    return counselor


class _OneCounselorPool:
    """Stands in for ``AgentRegistry.get_by_pool`` (``self_telemetry_domains.CounselorRegistry``)."""

    def __init__(self, counselor: Any) -> None:
        self._counselor = counselor

    def get_by_pool(self, pool_name: str) -> list[Any]:
        return [self._counselor] if pool_name == "counselor" else []


def test_the_trust_reading_uses_get_score_and_is_recorded_not_assessed() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)

    metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["trust_score"] == TRUST_DEFAULT  # held: the assessment input is unchanged (BF-921 D3)
    profile = counselor.get_profile("agent-a")
    assert profile.observed_baseline is not None
    assert profile.observed_baseline.trust_score == pytest.approx(0.8)
    assert [score for _, score in profile.trust_observations] == [pytest.approx(0.8)]


def test_the_baseline_is_captured_at_the_first_reading_only() -> None:
    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)

    counselor._gather_agent_metrics("agent-a")
    trust.record_outcome("agent-a", success=False, weight=5.0)
    later = trust.get_score("agent-a")
    counselor._gather_agent_metrics("agent-a")

    assert later < 0.8
    profile = counselor.get_profile("agent-a")
    assert profile.observed_baseline.trust_score == pytest.approx(0.8)
    assert [score for _, score in profile.trust_observations] == [pytest.approx(0.8), pytest.approx(later)]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["trust_update", "qualification_drift"])
async def test_a_real_trust_drop_moves_no_assessment_dm_alert_or_wellness_view(path: str, monkeypatch) -> None:
    """BF-921 D3's hold. A trust of 0.02 against TRUST_DEFAULT would be a -0.48 drift (wellness 0.28: unfit,
    a DM, and on the trust-update path a Bridge alert) if it were assessed. Held, the Counselor that reads it
    assesses exactly as one with no trust network, and the agent's own wellness view is the same."""
    from probos.cognitive.self_telemetry_domains import collect_wellness_state

    trust = TrustNetwork()
    trust.create_with_prior("agent-low", alpha=1.0, beta=49.0)
    held, control = _counselor(trust), _counselor(None)
    sent: dict[str, AsyncMock] = {}
    alerts: dict[str, MagicMock] = {}
    for name, counselor in (("held", held), ("control", control)):
        counselor.get_or_create_profile("agent-low")  # the trust-update handler skips an agent with no profile
        sent[name] = AsyncMock(return_value=True)
        alerts[name] = MagicMock()
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", sent[name])
        monkeypatch.setattr(counselor, "_alert_bridge", alerts[name])
        if path == "trust_update":
            await counselor._on_trust_update({"agent_id": "agent-low", "new_score": trust.get_score("agent-low")})
        else:
            await counselor._on_qualification_drift({
                "agent_id": "agent-low", "severity": "critical", "test_name": "bf923_probe",
                "drift_type": "unclassified", "z_score": 3.5,
            })

    held_profile = held.get_profile("agent-low")
    control_profile = control.get_profile("agent-low")
    assert len(held_profile.assessments) == len(control_profile.assessments) == 1

    def without_time(assessment: Any) -> dict[str, Any]:
        return {k: v for k, v in assessment.to_dict().items() if k != "timestamp"}

    assert without_time(held_profile.assessments[0]) == without_time(control_profile.assessments[0])
    assert held_profile.assessments[0].trust_drift == 0.0
    for name in ("held", "control"):
        sent[name].assert_not_called()
        alerts[name].assert_not_called()

    def wellness_view(counselor: Any) -> dict[str, Any]:
        view = collect_wellness_state("agent-low", registry=_OneCounselorPool(counselor))
        view.pop("assessed_at", None)
        return view

    assert wellness_view(held)
    assert wellness_view(held) == wellness_view(control)
    # The reading is real and on record.
    assert held_profile.trust_observations[-1][1] == pytest.approx(0.02)
    assert held_profile.observed_baseline.trust_score == pytest.approx(0.02)


def test_a_failing_trust_read_is_logged_at_warning_and_records_nothing(caplog) -> None:
    trust = create_autospec(TrustNetwork, instance=True)
    trust.get_score.side_effect = RuntimeError("trust store offline")
    counselor = _counselor(trust)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["trust_score"] == TRUST_DEFAULT
    assert counselor.get_profile("agent-a") is None
    assert any(
        record.levelno == logging.WARNING and "BF-923: trust read failed for agent-a" in record.getMessage()
        for record in caplog.records
    )


def test_the_hebbian_router_is_not_read() -> None:
    from probos.mesh.routing import HebbianRouter

    counselor = _counselor(None)
    router = create_autospec(HebbianRouter, instance=True)
    counselor._hebbian_router = router

    metrics = counselor._gather_agent_metrics("agent-a")

    assert metrics["hebbian_avg"] == 0.0
    assert router.mock_calls == []


def test_the_assessment_list_keeps_the_latest_entries() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT, CognitiveProfile, CounselorAssessment

    profile = CognitiveProfile(agent_id="agent-a")
    for i in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 5):
        profile.add_assessment(CounselorAssessment(timestamp=float(i), agent_id="agent-a"))

    assert len(profile.assessments) == COUNSELOR_PROFILE_HISTORY_LIMIT
    assert profile.assessments[0].timestamp == 5.0
    assert profile.assessments[-1].timestamp == float(COUNSELOR_PROFILE_HISTORY_LIMIT + 4)
    assert profile.last_assessed == float(COUNSELOR_PROFILE_HISTORY_LIMIT + 4)


def test_a_profile_saved_before_the_bound_loads_its_latest_assessments() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT, CognitiveProfile, CounselorAssessment

    data = CognitiveProfile(agent_id="agent-a").to_dict()
    data["assessments"] = [
        CounselorAssessment(timestamp=float(i), agent_id="agent-a").to_dict()
        for i in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 10)
    ]

    loaded = CognitiveProfile.from_dict(data)

    assert [a.timestamp for a in loaded.assessments] == [
        float(i) for i in range(10, COUNSELOR_PROFILE_HISTORY_LIMIT + 10)
    ]


def test_trust_observations_keep_the_latest_readings() -> None:
    from probos.cognitive.counselor import COUNSELOR_PROFILE_HISTORY_LIMIT

    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)
    for _ in range(COUNSELOR_PROFILE_HISTORY_LIMIT + 3):
        counselor._gather_agent_metrics("agent-a")

    profile = counselor.get_profile("agent-a")
    assert len(profile.trust_observations) == COUNSELOR_PROFILE_HISTORY_LIMIT
    times = [when for when, _ in profile.trust_observations]
    assert times == sorted(times)


@pytest.mark.asyncio
async def test_the_readings_survive_the_profile_store(tmp_path) -> None:
    from probos.cognitive.counselor import CounselorProfileStore

    trust = TrustNetwork()
    trust.create_with_prior("agent-a", alpha=8.0, beta=2.0)
    counselor = _counselor(trust)
    counselor._gather_agent_metrics("agent-a")
    counselor._gather_agent_metrics("agent-a")
    profile = counselor.get_profile("agent-a")

    store = CounselorProfileStore(data_dir=tmp_path)
    await store.start()
    try:
        await store.save_profile(profile)
        loaded = await store.load_profile("agent-a")
    finally:
        await store.stop()

    assert loaded is not None
    assert loaded.observed_baseline is not None
    assert loaded.observed_baseline.to_dict() == profile.observed_baseline.to_dict()
    assert loaded.trust_observations == profile.trust_observations
```

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and the `DECISIONS.md` heading `### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)` (line 739 on this tree). The entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-923 (2026-10-25), #1652 -- the episodic recall callers and the Counselor's assessment inputs read APIs their dependencies have.** Three callers passed `agent_id` to `EpisodicMemory.recall`, which takes none, and swallowed the `TypeError`. The behavioral metrics' anchor-grounded emergence now reads each Ward Room author's recent episodes (`recent_for_agent`) by the sovereign id its episodes carry (the runtime late-binds the identity registry: authors are slot ids), and reports failures once at WARNING. Both orientation callers count the agent's own episodes (`count_agent_episodes`, `count_for_agent`); the stasis-recovery orientation moved into `_orient_crew_after_stasis` and now tells each crew member its episode count, a line AD-567g designed and no one had seen. The Counselor read trust with `TrustNetwork.score` (absent) and Hebbian weights with `get_weights_for` (never defined): it now reads trust with `get_score` and records each reading on the profile (`trust_observations`) with the first as the captured baseline (`observed_baseline`), while every assessment keeps `TRUST_DEFAULT` and the default baseline, so no wellness change, DM, Bridge alert or wellness-view change follows a reading until the gauge is qualified (BF-921 D3; the measurement is on #1523). The Hebbian read is removed. A profile keeps its latest 50 assessments and readings. New: `tests/test_bf923_episodic_recall_callers.py`, `tests/test_bf923_counselor_assessment_inputs.py`. The contract is `prompts/bf-923-episodic-recall-callers-and-counselor-assessment-inputs.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)
```
REPLACE:
```markdown
### BF-923 -- Episodic recall callers and the Counselor's assessment inputs (2026-10-25, #1652)

- *Anchor metric.* AD-569's "recent episodes" are read with `recent_for_agent`, not a semantic recall of an empty query, and by the sovereign id: Ward Room authors are slot ids, episodes carry sovereign ids, so the behavioral metrics engine takes the identity registry by late binding. Whether thread-relevant episodes measure grounding better is a metric design question, registered.
- *Orientation count.* One helper (`count_agent_episodes`) counts the agent's own episodes for both callers; the warm-boot block is a function so the caller is tested on a real store. At stasis recovery the crew is told its own episode count (a fact, not a gauge: no hold).
- *Counselor trust: recorded, held.* `get_score` is read at the one gather seam and recorded on the profile with the first reading as the captured baseline; the values the assessment receives are unchanged (`TRUST_DEFAULT`, Hebbian 0.0, the default baseline), so `assess_agent`, its DMs, its Bridge alerts and the agent's wellness view are unchanged by construction (BF-921 D3). Rejected: a hold inside `assess_agent` (changes the math for explicit callers) and a per-call-site record (fifteen identical lines, a missed one silent). `_on_trust_update` still compares with the default baseline; the measurement on #1523 decides it with the gauge.
- *Hebbian.* Not read: no per-agent Hebbian reading is defined; choosing one is a new gauge.
- *Bound.* A profile keeps its latest 50 assessments and readings (on append and on load); the full history stays in the `assessments` table.
- *Reversal.* Revert the commits; the metric and the counts return to 0 and the Counselor stops recording readings.

### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916 and BF-921 precedent).

**#1652 checklist text** (the orchestrator records it on the issue):
- [ ] (1) The anchor metric reads each author's recent episodes by sovereign id; failures reported at WARNING (M1).
- [ ] (1b) Both orientation callers count the agent's own episodes; the stasis orientation states it (M1).
- [ ] (2) The Counselor reads trust with `get_score` and records it with a captured baseline; every assessment, DM, Bridge alert and wellness view held (M2).
- [ ] (2b) The Hebbian read removed; a profile keeps its latest 50 assessments and readings (M2).
- [ ] (2c) The measurement before any action: posted on #1523 (section 18, R0).
- [ ] First live session after merge: section 16's counts recorded on #1652.

## 9. What this does NOT change

- `EpisodicMemory`, `MockEpisodicMemory`, the Ward Room and the identity registry are not edited. `compute_anchor_independence` and the other four behavioral metrics are unchanged; `BEHAVIORAL_METRICS_UPDATED` is still not emitted on the dream path.
- `OrientationService`, its renderers and their texts are unchanged; the warm-boot block's behaviour is unchanged except for the count (its gate stays in `finalize_startup`; its failure still logs at DEBUG).
- `assess_agent`, `profile.baseline`, `set_baseline`, `CounselorAssessment`, the wellness formula, the thresholds (`config.py:233-238`), `_maybe_send_therapeutic_dm`, `_alert_bridge`, every handler and its trigger (D8), the self-telemetry whitelist and `TrustNetwork` are unchanged. `_hebbian_router` stays injected (R3).
- The `assessments` table and `CounselorProfileStore` are unchanged.
- AD-583f's verifier wiring (R1) and the Counselor's success-rate input (R2) are not changed.

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7)

Run each row on the applied tree after an unmutated baseline run passes; restore each file before the next row. M1 (STANDARD) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf923_episodic_recall_callers.py tests/test_behavioral_metrics.py -n 0 -x -q
```

M2 (HIGH) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf923_counselor_assessment_inputs.py tests/test_counselor_activation.py tests/test_peer_repetition_credits.py -n 0 -x -q
```

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| R1 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `owner_id = resolve_sovereign_id_from_slot(agent_id, self._identity_registry)` | `owner_id = agent_id` | `test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry`, `test_the_booted_runtime_reads_crew_authors_episodes` |
| R2 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `eps = await episodic_memory.recent_for_agent(owner_id, k=10)` | `eps = await episodic_memory.recall(query="", agent_id=owner_id, limit=10)` | `test_the_anchor_metric_reads_each_authors_recent_episodes`, `test_anchor_analysis_with_memory` |
| R3 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `self._identity_registry = identity_registry` | `pass` | `test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry` |
| R4 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `failures += 1  # BF-923: counted, reported once below` | `pass` | `test_a_failing_store_is_reported_once_at_warning` |
| R5 | 1 | `src/probos/runtime.py` | `self._behavioral_metrics_engine.set_identity_registry(self.identity_registry)` | `pass` | `test_the_booted_runtime_reads_crew_authors_episodes` |
| R6 | 1 | `src/probos/cognitive/orientation.py` | `owner_id = getattr(agent, "sovereign_id", None) or agent.id` | `owner_id = agent.id` | `test_count_agent_episodes_counts_the_agents_own_episodes`, the warm-boot test |
| R7 | 1 | `src/probos/cognitive/orientation.py` | `return await episodic_memory.count_for_agent(owner_id)` | `return 0` | `test_count_agent_episodes_counts_the_agents_own_episodes`, the proactive and warm-boot tests |
| R8 | 1 | `src/probos/cognitive/orientation.py` | `"BF-923: episode count failed for %s; the orientation reports none",` | `"episode count failed for %s",` | `test_a_failing_count_is_logged_at_warning_and_reports_none` |
| R9 | 1 | `src/probos/proactive.py` | `_ep_count = await count_agent_episodes(getattr(rt, 'episodic_memory', None), agent)` | `_ep_count = 0` | `test_the_proactive_supplement_is_built_with_the_agents_episode_count` |
| R10 | 1 | `src/probos/startup/finalize.py` | `_ep_count = await count_agent_episodes(runtime.episodic_memory, agent)  # BF-923 (#1652)` | `_ep_count = 0` | `test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count` |
| R11 | 1 | `src/probos/startup/finalize.py` | `oriented += 1  # BF-923: one per crew agent oriented` | `pass` | `test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count` |
| R12 | 2 | `src/probos/cognitive/counselor.py` | `observed_trust = float(self._trust_network.get_score(agent_id))` | `observed_trust = float(self._trust_network.score(agent_id))` | `test_the_trust_reading_uses_get_score_and_is_recorded_not_assessed`, the hold test, `TestGatherAgentMetrics::test_trust_from_network` |
| R13 | 2 | `src/probos/cognitive/counselor.py` | `self._record_trust_observation(agent_id, observed_trust, metrics)` | `metrics["trust_score"] = observed_trust; self._record_trust_observation(agent_id, observed_trust, metrics)` (the hold lifted) | `test_a_real_trust_drop_moves_no_assessment_dm_alert_or_wellness_view[trust_update]`, `[qualification_drift]` |
| R14 | 2 | `src/probos/cognitive/counselor.py` | `self._record_trust_observation(agent_id, observed_trust, metrics)` | `pass` | `test_the_trust_reading_uses_get_score_and_is_recorded_not_assessed` |
| R15 | 2 | `src/probos/cognitive/counselor.py` | `if profile.observed_baseline is None:` | `if True:` | `test_the_baseline_is_captured_at_the_first_reading_only` |
| R16 | 2 | `src/probos/cognitive/counselor.py` | `del profile.trust_observations[:-COUNSELOR_PROFILE_HISTORY_LIMIT]` | `pass` | `test_trust_observations_keep_the_latest_readings` |
| R17 | 2 | `src/probos/cognitive/counselor.py` | `del self.assessments[:-COUNSELOR_PROFILE_HISTORY_LIMIT]` | `pass` | `test_the_assessment_list_keeps_the_latest_entries` |
| R18 | 2 | `src/probos/cognitive/counselor.py` | `recent = data["assessments"][-COUNSELOR_PROFILE_HISTORY_LIMIT:]` | `recent = data["assessments"]` | `test_a_profile_saved_before_the_bound_loads_its_latest_assessments` |
| R19 | 2 | `src/probos/cognitive/counselor.py` | `"trust_observations": [list(entry) for entry in self.trust_observations],` | `"trust_observations": [],` | `test_the_readings_survive_the_profile_store` |
| R20 | 2 | `src/probos/cognitive/counselor.py` | `profile.observed_baseline = CognitiveBaseline.from_dict(data["observed_baseline"])` | `pass` | `test_the_readings_survive_the_profile_store` |
| R21 | 2 | `src/probos/cognitive/counselor.py` | `logger.warning("BF-923: trust read failed for %s; nothing recorded", agent_id, exc_info=True)` | `logger.debug("BF-923: trust read failed for %s; nothing recorded", agent_id, exc_info=True)` | `test_a_failing_trust_read_is_logged_at_warning_and_records_nothing` |

R13 and R14 mutate the same line; run them as separate rows. The removed Hebbian read cannot be mutated back in one line; `test_the_hebbian_router_is_not_read` and `TestGatherAgentMetrics::test_hebbian_from_router` pin it (an autospec router raises on `get_weights_for`, and `mock_calls` would show any real read).

## 11. Verified Against Codebase (2026-10-25, worktree `bf923-draft` at `origin/main` `471d3f7e`)

```
git log -1 --format="%H %s"
  471d3f7eefd27bcb3711f8c90b7f5ee3bb870a59 Merge pull request #1651 from seangalliher/fix/bf921-20261024-f7f52a78
grep -n "async def recall\b|recall_for_agent\b|count_for_agent\b" src/probos/cognitive/episodic.py
  3415 recall(self, query, k=5, *, include_self_contradicted=False); 3875 recall_for_agent(self, agent_id, query, k=5, *, ...); 4261 count_for_agent(self, agent_id) -> int
grep -n "async def recent_for_agent" src/probos/cognitive/episodic.py
  4109: recent_for_agent(self, agent_id, k=5, *, include_self_contradicted=False) -- "No relevance threshold"
grep -n "def resolve_sovereign_id_from_slot" src/probos/cognitive/episodic.py
  472: (slot_id, identity_registry) -> str; returns slot_id when registry is None or unmapped
grep -n "recent_for_agent|count_for_agent|recall_for_agent" src/probos/cognitive/episodic_mock.py
  195, 215, 220 (same names and argument order)
read src/probos/cognitive/behavioral_metrics.py:88-99, 113-262, 552-620
  set_observable_verifier late-bind; composite includes anchor_result["grounded_rate"] (:202-213); recall(query="", agent_id=, limit=10) :584-588; except at DEBUG without exc_info :602-607
read src/probos/cognitive/dreaming.py:1655-1684, 2925-2986
  compute_behavioral_metrics(ward_room=, episodic_memory=, get_department=) -- no emit_event_fn; behavioral_quality in the reflection text
grep -n "author_id=agent.id" src/probos/proactive.py      -> 2994, 3581, 3664, 4076, 4168, 4772, 4887, 4936
grep -n "agent_ids=\[" src/probos/ward_room              -> threads.py:588, :636; messages.py:341, :389 ([sovereign_id])
read src/probos/ward_room/threads.py:574-588              -> sovereign_id = resolve_sovereign_id_from_slot(author_id, self._identity_registry)
grep -n "self.identity_registry = infra|init_dreaming\(" src/probos/runtime.py -> 2810, 3147
read src/probos/runtime.py:3172-3180                      -> self._behavioral_metrics_engine = dream_result.behavioral_metrics_engine  # AD-569
read src/probos/proactive.py:1772-1804, 2696-2705         -> orientation recall at :1784; count_for_agent(getattr(agent,'sovereign_id', agent.id)) at :2699
grep -n "from probos.cognitive.orientation import" src/probos/proactive.py -> 43: OrientationContext, derive_watch_section
read src/probos/startup/finalize.py:6273-6332, 3978-3994  -> warm-boot block; `return True` then `async def finalize_startup(`
grep -n "^from datetime|^from probos.crew_utils" src/probos/startup/finalize.py -> 13: datetime, timezone; 20: is_crew_agent
grep -n "episodic_memory_count" src/probos               -> orientation.py:49, 145, 220, 348, 354, 413, 415; proactive.py:1791; finalize.py:6319; agent_onboarding.py:393
read src/probos/cognitive/orientation.py:101-229, 394-457 -> derive_watch_section ends `return "first"`; OrientationService(*, config, ontology=None); warm-boot line :413-416
grep -n "proactive_supplement|orientation_window_seconds|warm_boot_orientation" src/probos/config_models/knowledge.py -> 369 600.0, 371 True, 372 True
read src/probos/crew_utils.py:58-76                       -> _WARD_ROOM_CREW includes "architect", "scout", "counselor"
read src/probos/cognitive/counselor.py:43-60, 146-275, 541-560, 715-805, 1429-1507, 1686-1719, 2172-2185, 2402-2421, 2710-2819
  CognitiveBaseline defaults; CognitiveProfile fields and add_assessment; _gather_agent_metrics :755-805 (score :771, get_weights_for :780); assess_agent formula :2732-2796
grep -n "def get_score|def score|def create_with_prior|def record_outcome|def _canonical_key" src/probos/consensus/trust.py
  97 (TrustRecord property), 358, 372, 311, 1017
grep -n "def get_agent_weights|def record_verification|def get_all_weights" src/probos/mesh/routing.py -> 289, 234, 408
read src/probos/cognitive/self_telemetry_domains.py:68-118 -> whitelist: alert_level, confabulation_rate, memory_integrity_score, wellness_score, trust_drift, confidence_drift, hebbian_drift, fit_for_duty, concerns, trust_drift_trend, assessed_at
read src/probos/routers/counselor.py:48-84, 150-183, 637-652
grep -n "drift_check_tiers|drift_critical_sigma|drift_history_window|drift_min_samples" src/probos/config.py -> 3619 [1,2,3], 3615 3.0, 3617 20, 3616 3
read src/probos/cognitive/drift_detector.py:150-203, 345-359, 461-497
read src/probos/cognitive/behavioral_probes.py:210-250   -> AnchorGroundedEmergenceProbe score = anchor_grounded_rate
read tests/test_behavioral_metrics.py:561-631; tests/test_peer_repetition_credits.py:1-16, 536-611; tests/test_counselor_activation.py:1-16, 200-252
read tests/test_ad576_llm_unavailability.py:1-58, 413-449; tests/test_bf235_stale_identity_cache.py:166-229
read tests/test_agent_identity.py:139-140, 191-209      -> AgentIdentityRegistry(data_dir=tmp_path); start(); resolve_or_issue(slot_id=..., baseline_version=...)
read tests/test_ad1038_remember_know_render.py:263-287  -> real EpisodicMemory(db_path=...) store/stop pattern
grep -n "^### BF-92" DECISIONS.md                        -> 709 BF-920, 739 BF-921
grep -n "^# ProbOS Progress" PROGRESS.md                 -> 1
```

**Doubles audit (every test that touches a changed caller).**

| Test | Double | Masks | After |
|---|---|---|---|
| `test_behavioral_metrics.py:579-581` | `AsyncMock()` store, `recall = AsyncMock(...)` | signature (accepted `agent_id`, `limit`) and result shape (`MagicMock` episodes) | autospec: signature checked; episodes stay `MagicMock` (the test patches `compute_anchor_independence`); the real shape is covered by the real-store tests |
| `test_behavioral_metrics.py:627-628` | same | same | same |
| `test_ad576_llm_unavailability.py:419-426` | `MagicMock()` orientation service | `build_orientation` signature | unchanged; its `rt.episodic_memory` is None, so the helper returns 0 as before |
| `test_bf235_stale_identity_cache.py:197-225` | none: copies the warm-boot logic inline | the whole caller | unchanged; the new warm-boot test drives the extracted function (R6 of section 18) |
| `test_bf235_stale_identity_cache.py:88-128` | `MagicMock` runtime through `finalize_startup` | the caller (warm boot off) | unchanged; never reaches the block |
| `test_peer_repetition_credits.py:544-545`, `:569-570`, `:596-597` | `MagicMock()` trust, `score = MagicMock(0.7)` | signature (an API the network lacks) | autospec, `get_score.return_value = 0.7`; the assessment now gets `TRUST_DEFAULT` (held); no assertion reads trust |
| `test_counselor_activation.py:216-217`, `:225-226`, `:247-248` | `MagicMock()` trust and router | signature (`score`, `get_weights_for`) | real `TrustNetwork`; autospec router; autospec trust |
| `test_counselor_activation.py:234-238` (`test_registry_meta`) | `MagicMock` agent with `success_rate` | result shape: real agents have no `success_rate` (R2) | unchanged (out of scope) |
| 14 `_gather_agent_metrics = MagicMock(return_value=...)` (`test_ad529:450`, `test_ad552:230`, `:261`, `test_ad566c:656`, `:692`, `test_ad567c:506`, `:532`, `test_ad576:352`, `:373`, `test_counselor_therapeutic:167`, `:191`, `:213`, `:244`, `:257`, `:616`, `:681`, `test_graduated_zones:470`, `:492`, `:537`, `:557`) | replace the gather | the gather's dict shape, not a dependency signature | unchanged: they test the DM logic downstream of chosen inputs and record no reading |
| `test_ad642_communication_benchmarks.py:521` | `_hebbian_router = MagicMock()` | the absent `get_weights_for` | unchanged; the router is no longer read |

`create_autospec` checks call signatures, not result shapes; each changed caller has a real-store or real-network test for the shape.

## 12. Absence Verified (2026-10-25)

```
CLAIM: exactly three callers pass agent_id (or limit) to .recall(
RUN:   multiline grep "\.recall\(\s*[^)]*\b(limit|agent_id)=" src/
FOUND: behavioral_metrics.py:584, proactive.py:1784, startup/finalize.py:6298 (3)
HOLDS: yes

CLAIM: compute_behavioral_metrics has one caller
RUN:   grep "compute_behavioral_metrics" src/
FOUND: behavioral_metrics.py:113 (def), dreaming.py:1663
HOLDS: yes

CLAIM: the runtime has no public behavioral_metrics_engine, so finalize.py:5955 never wires the AD-583f verifier (R1)
RUN:   grep "behavioral_metrics_engine" src/
FOUND: runtime.py:1395, :3177 (both _behavioral_metrics_engine); finalize.py:5955 getattr(runtime, 'behavioral_metrics_engine', None); others are dreaming/startup/probes/router uses of the private name or the local
HOLDS: yes (getattr on the real runtime returns None)

CLAIM: no definition of get_weights_for in src/
RUN:   grep "    def (get_weight|get_all_weights|get_weights|weights_for|get_preferred_targets|all_weights|get_agent_weights)\w*" src/
FOUND: routing.py:251 get_weight, :261, :289 get_agent_weights, :351, :361, :408; federation/hebbian_map.py:131; knowledge/quality_router.py:66; ward_room_hebbian/router.py:75 -- no get_weights_for
HOLDS: yes

CLAIM: set_baseline has no production caller
RUN:   grep "\.set_baseline\(" src/
FOUND: 0
HOLDS: yes (unchanged by this contract)

CLAIM: no agent class defines success_rate, so the Counselor's success-rate input is always 0.0 (R2)
RUN:   grep "self\.success_rate\s*[:=]|def success_rate\(" src/probos/
FOUND: crew_development/discovery/strength_map.py:50, :91 (methods with arguments, other classes); duty_schedule.py:260 (same)
HOLDS: yes for registry agents (getattr(meta, "success_rate", 0.0) at counselor.py:792)

CLAIM: fit_for_promotion has no reader in src/ beyond the assessment itself
RUN:   grep "fit_for_promotion" src/
FOUND: counselor.py:87, :109, :537 (prompt text), :2790, :2814
HOLDS: yes

CLAIM: only orientation.py:348/:354/:413 render episodic_memory_count; the proactive renderers do not
RUN:   grep "episodic_memory_count" src/probos
FOUND: orientation.py:49, 145, 220 (fields/copy), 348, 354, 413, 415 (render); proactive.py:1791; finalize.py:6319; agent_onboarding.py:393
HOLDS: yes

CLAIM: REL_AGENT Hebbian edges are written only through record_verification
RUN:   grep "record_verification\(|rel_type=REL_AGENT" src/
FOUND: routing.py:234 (def), :248; runtime.py:4632 (one caller)
HOLDS: yes

CLAIM: no test pins the old recall call or the old count
RUN:   grep "agent_id=_sid|recall\(\"\", agent_id" tests/
FOUND: 0 (count_for_agent hits are other features' doubles)
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- Bug fix; the external review was one search, on the hold's pattern. **Absorbed:** shadow mode, a new signal run on live inputs and logged but never acted on, promoted only on explicit criteria ([AWS SageMaker shadow variants](https://docs.aws.amazon.com/sagemaker/latest/dg/model-shadow-deployment.html); [Atlan, shadow deployment](https://atlan.com/know/shadow-deployment-for-ml-models/)). M2 is that: readings recorded, decisions on today's inputs, and section 18's entry names the promotion criteria. **Absorbed as a stated limit:** shadow evaluation measures what the gauge would have done, not how the crew would respond ([Qwak](https://www.qwak.com/post/shadow-deployment-vs-canary-release-of-machine-learning-models)); a later staged release is the qualifying issue's choice. `docs/research/reference-projects.md`: not consulted (ProbOS plumbing; no project there covers it).
- Internal: AD-503 (gather), AD-495 (trust-update reassessment), AD-505 (DMs), AD-566c/e (drift), AD-567g (orientation), AD-569 (metrics), AD-441/BF-138 (sovereign ids), BF-907 (trust key form), BF-921 D3.
- Blind spots addressed: the slot/sovereign id mismatch (D1); the drift detector's `__crew__` reaction to a metric leaving zero (E1); the confidence baseline that a naive capture would make live (D6); the trust-update trigger that a captured baseline would widen (D8). Considered, deferred: thread-relevant anchor episodes (R5); a batched episode count (R7).

## 14. Diff Reviewer: properties to verify

1. No production caller passes `agent_id` or `limit` to `EpisodicMemory.recall`.
2. The anchor metric reads each author through `recent_for_agent` by the id `resolve_sovereign_id_from_slot` returns for the engine's identity registry; the booted runtime binds its `identity_registry` into the engine it holds; with no registry an author is read by its own id. A computation with failures logs exactly one WARNING naming the count.
3. Both orientation callers obtain the count from `count_agent_episodes`, which counts the sovereign id, else the slot id, through `count_for_agent`, and returns 0 with a WARNING on failure. The extracted warm-boot function differs from the removed block only in the count, the counter and the return value; its gate is unchanged.
4. The values `_gather_agent_metrics` returns are, for every input, the values the base returned in production (`trust_score` `TRUST_DEFAULT`, `hebbian_avg` 0.0, confidence, success rate and personality drift read as before). Nothing reads `trust_observations` or `observed_baseline` except the record helper, `to_dict` and `from_dict`. `assess_agent`, `profile.baseline`, every handler, `_maybe_send_therapeutic_dm`, `_alert_bridge` and the self-telemetry whitelist are unchanged.
5. A trust reading is recorded only when `get_score` returned; the first recorded reading is never overwritten; a failed read logs a WARNING and records nothing and creates no profile.
6. A profile never holds more than `COUNSELOR_PROFILE_HISTORY_LIMIT` assessments or readings, after append or after load, and keeps the latest; a profile saved before the build loads.
7. The hold test compares a Counselor with a real low trust reading against one with no trust network on two gathering paths, with only the DM sender and the Bridge alert replaced by spies, and compares the agent's own wellness view.
8. Every replaced double says inline what it used to accept and why; no test was deleted.

## 15. Acceptance criteria

- On a real store, the anchor metric analyses a thread whose authors' episodes exist, including when the authors are slot ids mapped by a real identity registry, and through the booted runtime's engine and store.
- On a real store, both orientation callers pass the agent's own episode count; at stasis recovery an agent with episodes is told the count.
- The Counselor reads trust with `get_score` on a real `TrustNetwork`, records it with a captured baseline, and, with a reading that would make the agent unfit, produces the same assessment, no DM, no Bridge alert and the same wellness view as a Counselor with no trust network.
- The Hebbian router is not read. A profile keeps at most 50 assessments and readings.
- The measurement entry is posted on #1523 before #1652 closes.
- Before editing, the tests that pin current behaviour were grepped, and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what is read after the first session (read-only)

From `%LOCALAPPDATA%\ProbOS\data` after the first vessel session on the merged build, record on #1652:
- (M1) after the first dream: the `/behavioral-metrics` snapshot's `anchor_analyzed_threads` and `anchor_grounded_rate` (expected above 0 when qualifying threads exist); the count of `BF-923 (#1652): anchor analysis failed` and `BF-923: episode count failed` lines (expected 0).
- (M1) at the next drift check: any `AD-566c: Warning qualification drift for __crew__ on anchor_grounded_emergence` or `AD-567c: Critical drift for __crew__ on anchor_grounded_emergence` line (E1; expected at most one, no DM).
- (M1) the first stasis recovery's boot time against the previous one (E4, R7).
- (M2) the count of `BF-923: trust read failed` lines (expected 0); read-only from `counselor.db` `cognitive_profiles.profile_json`: the number of profiles with `observed_baseline` set and their `trust_observations` lengths; the `AD-505: Sent therapeutic DM to` count against BF-921's first-session count (expected no change attributable to BF-923).

## 17. Not verified

- That `create_autospec(EpisodicMemory, instance=True)` gives awaitable, signature-checked methods whose `return_value`/`side_effect` set the awaited result (read from the CPython 3.12 `unittest.mock` documentation; BF-921 relied on the same). The tests-first run shows it: `test_anchor_analysis_with_memory` fails on the base only if the autospec rejects `recall(agent_id=...)`.
- Verified by run (the orchestrator, 2026-10-25, after the first oracle run; this was the premise this bullet named): a default `SystemConfig()` boot has no episodic store (`ProbOSRuntime`'s `episodic_memory` argument defaults to `None`; `__main__` passes one), so `test_the_booted_runtime_reads_crew_authors_episodes` now passes a real `EpisodicMemory`, which the runtime starts and stops (`startup/cognitive_services.py:292`, `startup/shutdown.py:1286`). The runtime's engine exists and has the registry bound (`runtime.py:3177-3180`). 16 `CognitiveAgent`s carry a birth certificate and a DID (crew) and resolve through `get_by_slot(agent.id)`; 20 other `CognitiveAgent`s (utility agents such as `web_search`) hold asset tags (`agent_onboarding.py:464-476`) that `get_by_slot` does not know, so the test selects crew by `did`: the first oracle run failed at `rt.episodic_memory is not None`, and, with the store passed, at `analyzed_threads == 1` because the first two agents with a differing `sovereign_id` were `web_search` assets (evidence `bf923-oracle-a-union`, `bf923-probe-boot`, `bf923-probe-classify`).
- That `ProactiveCognitiveLoop._gather_context` reaches the orientation block with a real store and the `_make_loop` runtime shape (the block is at `proactive.py:1773`, before the first store read at `:1807`; read, not run).
- That `EpisodicMemory.store` accepts the test episodes (no anchors, `source="direct"`; the same shape as `tests/test_ad1038_remember_know_render.py:269-276` plus no anchors) and that two stores in one test directory do not collide (the identity registry and the store use different file names under `tmp_path`).
- That `TrustNetwork().record_outcome(..., success=False, weight=5.0)` lowers the score below 0.8 with default dampening (read from `trust.py:372-410`; the test asserts it).
- The boot-time cost of one `count_for_agent` scan per crew agent at stasis recovery on a large store (E4); section 16 reads it.
- The live volume of trust readings per profile (bounded at 50).

## 18. For the register (found here, not fixed by this change)

- **R0 (post on #1523 now, unchecked; the orchestrator assigns the F-number).** "BF-923 M2 (#1652): **measure the Counselor's trust gauge before any action follows it.** BF-923 reads trust with `get_score` and records each reading on the profile (`trust_observations`, latest 50) with the first as the captured baseline (`observed_baseline`); `assess_agent` still receives `TRUST_DEFAULT`, Hebbian 0.0 and the default baseline, so no wellness change, DM, Bridge alert or wellness-view change follows a reading (BF-921 D3). Before the hold is lifted, over at least five vessel sessions, read-only from `counselor.db`: (1) per agent and per trigger, the trust drift from the captured baseline at each reading, and the wellness, concerns and fit-for-duty `assess_agent` would have produced with it; (2) how many DMs (wellness below 0.5 or unfit) and Bridge alerts (unfit) that would have added, against the AD-505 DMs actually sent; (3) the `trust_update` reassessment rate per agent (R12's churn, still on the default baseline) and the rate it would have with the captured baseline (D8). Promotion criteria, decided by the issue that lifts the hold: whether trust drift enters wellness, at what weight and threshold; whether `_on_trust_update` compares with the captured baseline; whether `observed_baseline` becomes `profile.baseline` (through `set_baseline`); the Hebbian reading (R3). Shadow measurement shows what the gauge would have done, not how the crew would respond."
- **R1.** AD-583f's observable-state verifier never reaches the behavioral metrics engine: `finalize.py:5955` reads `getattr(runtime, 'behavioral_metrics_engine', None)`, but the runtime holds `_behavioral_metrics_engine` (`runtime.py:1395`, `:3177`), so the getattr returns None and Metric 4 (convergence correctness) never verifies. Same shape as this BF (built, wired by name, inert). Fixing it makes a second metric real and changes the composite: its own slice, with this contract's consumer list (section 5a).
- **R2.** The Counselor's success-rate input reads `getattr(meta, "success_rate", 0.0)` from registry agents (`counselor.py:789-792`), which define no `success_rate` (section 12): the input is always 0.0, so `fit_for_promotion` is always False on gathered paths and the low-success concern never fires. `test_counselor_activation.py:234-238` masks it with a `MagicMock` agent. A real reading is a new gauge input: measure under the same hold as R0.
- **R3.** No per-agent Hebbian reading is defined; `_hebbian_router` stays injected and unread (D5). Choosing the relation (and its id form) belongs to R0's qualifying issue.
- **R4.** `_on_trust_update` still reassesses every trust outcome of an agent whose trust sits 0.15 or more from `TRUST_DEFAULT` (BF-921 R12). Storage is now bounded in the profile; the `assessments` table still gains a row per reassessment. R0 measures and decides it.
- **R5.** The anchor metric reads each author's ten most recent episodes, not the episodes relevant to the thread (AD-569's wording). Whether thread-relevant episodes (`recall_for_agent(owner, title, k)`) measure grounding better is a metric design question.
- **R6.** `tests/test_bf235_stale_identity_cache.py:197-225` copies the warm-boot loop inline instead of calling it; it can now call `_orient_crew_after_stasis`.
- **R7.** `count_for_agent` scans every episode's metadata (`episodic.py:4261-4280`). The proactive loop already calls it each cycle (`proactive.py:2699`); BF-923 adds one call per cycle inside the orientation window and one per crew agent at stasis recovery. If section 16 shows a slower stasis boot, a batched per-agent count is the fix.
