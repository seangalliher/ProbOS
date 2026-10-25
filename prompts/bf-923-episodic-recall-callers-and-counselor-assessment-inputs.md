# BF-923: the behavioral-metric and orientation callers read the episodic store through APIs it has (#1652); the Counselor reads real trust, records it with a captured baseline and a bounded history, and keeps every crew-facing result held (BF-921 D3)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A1, after review round 1)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25 (Amendment A2, after review round 2)

**Status:** build-ready. One BF, two milestones (M1 STANDARD, M2 HIGH), one gate; #1652 closes after both. **BF number:** BF-923 (#1652); this contract allocates nothing. **Tier:** M1 **HIGH** (raised from STANDARD by Amendment A1: three read paths to the episodic store and the producer's Ward Room scope; one crew-facing text, AD-567g's stasis line, appears with a true value; the ship-level behavioral metrics become non-zero, and the five Tier 3 probes that read them are held from drift, a safety property: a defect in the hold releases an unqualified gauge onto VitalsMonitor's medical alert); M2 **HIGH** (the Counselor's wellness gate decides DMs and Bridge alerts for every crew member; M2's only safety property is a hold, and a defect in the hold releases an unqualified gauge onto the crew). Review the batch at HIGH: use the Copilot `Diff Reviewer`. Never lower a tier without the Captain. **Base:** written against `origin/main` `471d3f7e` (BF-921 merge, PR #1651). BF-922 (#1639) merges first; it touches none of this contract's files (section 4); the orchestrator re-verifies every SEARCH on the new base. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf923_episodic_recall_callers.py` (M1, 18 functions, 23 cases: the original 9 functions, 8 functions with 12 cases added by Amendment A1, and 1 function with 2 cases added by Amendment A2).
- New `tests/test_bf923_counselor_assessment_inputs.py` (M2, 9 functions, 10 cases).
- Updated pins: `tests/test_behavioral_metrics.py` (M1: the two unrestricted `AsyncMock` stores, and A1: `MockWardRoom.list_channels`), `tests/test_counselor_activation.py` (M2: three `TestGatherAgentMetrics` tests that pinned `score` and `get_weights_for`), `tests/test_peer_repetition_credits.py` (M2: three `MagicMock` trust networks with `score`).

**Text repairs after the first oracle run (the orchestrator, 2026-10-25; the Architect's other text is unchanged).** The contract applied by tool passed all its pairs, and its tests passed except one: `test_the_booted_runtime_reads_crew_authors_episodes` (section 17's unverified premise). Section 7.7's test now passes a real `EpisodicMemory` to the runtime (a default boot has none) and selects crew by `did` (utility agents hold asset tags that `get_by_slot` cannot resolve); no stub. Section 17 records the premise as verified by run.

**Amendment A1 (`claude-architect`, 2026-10-25, after review round 1).** M1's review found three things: the producer never reached the repaired read (`browse_threads(agent_id="", channels=None)` lists no thread); per-thread author reads stall the event loop once it does; and fresh crew never enter the proactive orientation window. A1 adds:
- D10 to D12: the crew-channel scope without DMs, the Tier 3 hold, and the cost;
- sections 7.7a to 7.7d, and new tests in 7.7;
- M1 raised to HIGH;
- three filings in section 18: the fresh-crew defect, the emergence engine's twin, and the department lookup by slot id.

M2's code and tests are unchanged; section 8's tracker text, which M2's commit carries, gains A1's sentences.

**Amendment A2 (`claude-architect`, 2026-10-25, after review round 2).** Round 2 found one gap in D11 (F4, P3): a probe with no engine, or no snapshot since boot, returns `_skip_result`, which was stored conclusive (score 0.0, `inconclusive` False). A2 holds it: `_skip_result` sets `inconclusive=True` (BF-711's meaning, independent of `HELD_FROM_DRIFT`), with one test through the real harness and store (section 7.7; section 7.7c Pair 7; R32). It also discloses E7 (the `/qualify` displays, and the reflection text in the NL planner's recall) and defines E4 and E5. M2's code, tests and section 8 are unchanged.

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
| **New, found in review round 1:** the producer's thread read | `behavioral_metrics.py:132-137` on M1's candidate: `browse_threads(agent_id="", channels=None, limit=100, since=since)`; `ward_room/threads.py:332-341` reads `channels=None` as that agent's memberships | no thread reaches any of the five metrics; fixed by D10 |

## 1. Problem

**Item 1 (F-446).** Three callers pass `agent_id` to `EpisodicMemory.recall`, which takes none (`episodic.py:3415-3421`); each `TypeError` is swallowed (`behavioral_metrics.py:602-607` at DEBUG without the exception; `proactive.py:1786-1787` and `finalize.py:6300-6301` `except Exception: pass`).
- `BehavioralMetricsEngine._compute_anchor_grounded_emergence` therefore returns `grounded_rate` 0.0, `independence_score` 0.0 and `analyzed_threads` 0 on every dream. Verifying the fix found a second defect on the same path: the thread's `unique_authors` are Ward Room `author_id`s, which are slot ids (`proactive.py:2994`), while the authors' episodes are stored under the sovereign id (`ward_room/threads.py:579`, `:588`; `messages.py:341`). An agent-scoped read by the slot id finds nothing, so a signature fix alone would leave the metric at 0. The engine has no identity registry.
- The two orientation callers pass `episodic_memory_count=0` for every crew member. Effect, now verified (the issue left it open): `render_warm_boot_orientation` prints "You have N episodic memories from before stasis." only when the count is above 0 (`orientation.py:413-416`), so at every stasis recovery no crew member has been told it has memories. The proactive supplement renders no count (`orientation.py` reads `episodic_memory_count` only at `:348`, `:354`, `:413`; the proactive renderers start at `:441`), so the proactive caller's count has no visible effect.

**Item 1b (review round 1; reproduced on the base).** The production producer never reaches the read.
- `compute_behavioral_metrics` calls `ward_room.browse_threads(agent_id="", channels=None, limit=100, since=since)`, and `browse_threads` reads `channels=None` as that agent's memberships (`ward_room/threads.py:332-341`). So it returns `[]`, and the engine returns its empty snapshot (`behavioral_metrics.py:193`) before any of the five metrics runs.
- The live qualification store holds 289 runs of the collective behavioral tests (2026-04-07 to 2026-04-13) with 0 threads analysed in every one (the orchestrator's read-only count).
- The issue's premise ("0 because the call raises") was incomplete; this BF fixes both (D10).
- `emergence_metrics.py:390` makes the same call (R10).

**Item 2 (F-461, R12 of BF-921).** `_gather_agent_metrics` (`counselor.py:755-805`) calls `self._trust_network.score(agent_id)`; `TrustNetwork` has `get_score` (`consensus/trust.py:1017`), and `score` is `TrustRecord`'s property (`trust.py:97`). It calls `self._hebbian_router.get_weights_for(agent_id)`, which no class defines. Both fail at DEBUG, so every production assessment has `current_trust = TRUST_DEFAULT` and `hebbian_avg = 0.0`; with the never-captured baseline (`CognitiveBaseline()` defaults: trust `TRUST_DEFAULT`, Hebbian 0.0), the trust drift and the Hebbian drift are always 0.0. `CognitiveProfile.assessments` is unbounded and the whole list is rewritten into `profile_json` on every assessment (`counselor.py:182`, `:228`, `:382`).

**What a naive repair would do.** `assess_agent` turns a trust drift below -0.2 into a concern, subtracts 1.5 times the drop from wellness and marks the agent unfit below 0.3 (`counselor.py:2740-2744`, `:2776`, `:2789`). Fourteen handlers gather and assess (`counselor.py:957`, `:1078`, `:1132`, `:1176`, `:1271`, `:1311`, `:1359`, `:1414`, `:1461`, `:1484`, `:1606`, `:1699`, `:1743`, `:1919`) plus the API (`routers/counselor.py:167`); their results send DMs (`_maybe_send_therapeutic_dm`, `:2402-2413`, below 0.5 or unfit) and Bridge alerts (`_alert_bridge`, unfit), and the agent reads its own `wellness_score`, `trust_drift`, `hebbian_drift`, `concerns`, `fit_for_duty`, `alert_level` and `trust_drift_trend` through its introspective telemetry (`self_telemetry_domains.py:81-104`, `introspective_telemetry.py:275-279`). Real trust readings against any baseline would make all of these live for the first time. BF-921's D3 holds that no unqualified gauge drives a crew-facing action.

## 2. Solution overview

- **M1.** The anchor metric reads each author's recent episodes with `recent_for_agent` after resolving the Ward Room slot id to the sovereign id through an identity registry the runtime late-binds (`set_identity_registry`, the engine's existing late-bind pattern). Failures are counted and reported once per computation at WARNING. One helper, `count_agent_episodes(episodic_memory, agent)` in `cognitive/orientation.py`, gives both orientation callers the agent's own count through `count_for_agent` (as `proactive.py:2699` already does). The warm-boot block moves unchanged into `_orient_crew_after_stasis(*, runtime)` in `startup/finalize.py` so the count is tested through the caller. Amendment A1 adds three changes:
- The producer reads the crew channels explicitly: `list_channels()` filtered by `crew_channel_ids`, no DMs (D10).
- The five Tier 3 behavioral probes keep their scores and are held from drift (D11); Amendment A2 holds a skipped run too.
- Each owner's episodes are read once per computation, with a yield between reads, and synthesis and convergence detection embed in a worker thread (D12).
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

**D9, scope.** One contract, two milestones, one gate (the Architect's consult of 2026-10-25 00:44Z). In scope because they are on the paths being repaired: the slot-to-sovereign resolution (without it M1 fixes nothing), the failure logging at each repaired read (the DEBUG swallows hid both defects), and the warm-boot extraction (the only way to test the caller). Not in scope, registered: the AD-583f verifier wiring that never reaches the engine (R1), the Counselor's success-rate input (R2). Amendment A1 adds D10 to D12 to the scope: without D10 the milestone changes nothing in production, and D11 and D12 are the hold and the cost of what D10 activates. Filed, not fixed: the emergence engine's twin (R10), fresh crew outside the proactive orientation window (R11), and the department lookup by slot id (R12).

**D10, the producer's thread scope (Amendment A1).**
- **Ranked options:**
  1. **Chosen.** List the channels through the public `list_channels()` (the admin view, `ward_room/channels.py:129-133`) and pass the crew channels to `browse_threads(channels=...)`, as `routers/wardroom.py:444-450` does for an all-channel browse. The filter is one pure function, `crew_channel_ids`, in `ward_room/channels.py` beside the DM-name helpers, so the emergence engine's fix (R10) can reuse it.
  2. A new `WardRoomService.browse_crew_threads`: one owner for the privacy rule, but a new method on the shared service seam beside its BF-903 visitor checks, for two callers. R10 may promote the helper.
  3. A synthetic membership in every channel: manufactures an identity and writes to the Ward Room.
- **Scope:** ship, department and custom channels; never `dm`.
  - A DM channel is private to its two parties: crew pairs and every Captain DM, all created with `channel_type="dm"` (`channels.py:251`, `capability_request_notifier.py:119`, `proactive.py:4875`, `task_completion_notifier.py:132`; section 12).
  - AD-569 measures crew-wide collaboration ("observable collaboration quality", `prompts/archive/ad-569-behavioral-metrics.md:11`).
  - The Ward Room has no private custom channel (section 12).
  - Archived channels are read: they carry no privacy, and the 72 h lookback bounds them.
- **Why this is within the envelope:** no private content is read, so no privacy control is weakened.
- **Unchanged:** `limit=100` and `since` (`thread_lookback_hours`) stay as in AD-569.
- **Failure:** a failed list or browse logs one WARNING and raises. The dream's step 13 catches it (`cognitive/dreaming.py:1683-1684`) and the dream continues. No zero snapshot is recorded, because a failed read is not a zero measurement.

**D11, the Tier 3 hold (Amendment A1; BF-921 D3).**
- **The premise.** With D10 the snapshot carries real values for the first time. The five probes (`behavioral_probes.py`) are collective tests for `__crew__`, run weekly by the drift scheduler and on demand. Every stored result so far is 0, so the first real score has |z| = √19 ≈ 4.36 in the default window of 20: critical drift for `__crew__`.
- **What a critical `__crew__` report reaches:**
  - the Counselor's `_on_qualification_drift`, which assesses `__crew__` on default inputs: wellness 1.0, no DM (executed by the reviewer for the anchor test; the handler reads `test_name` only for its log line);
  - **VitalsMonitor**, which counts every critical report in the drift scheduler's `latest_reports` (`agents/medical/vitals_monitor.py:184-188`) and broadcasts a `medical_alert` intent on every 5 s heartbeat (`:49`, `:345-367`; no cooldown) until the next weekly drift run replaces the report. The Diagnostician (`diagnostician.py:59`), a crew agent, handles each alert with an LLM diagnosis.
- **Ranked options:**
  1. **Chosen.** Hold at the probe seam. Each result keeps its score and is stored with `inconclusive=HELD_FROM_DRIFT` (True). The drift detector filters inconclusive results before its statistics (`drift_detector.py:150`), so no signal, event, Counselor assessment or medical alert follows these five tests. The scores stay in the qualification store for the measurement, and `error` stays None, so baselines are set as before (`qualification.py:548`). It stretches BF-711's flag from "measured nothing" to "not a verdict yet"; the comment says so. **Amendment A2:** a skipped run (no engine, or no snapshot since boot) measured nothing, so `_skip_result` sets `inconclusive=True` under BF-711's own meaning, not `HELD_FROM_DRIFT`: lifting the hold must never return a skip's 0.0 to the statistics, where each boot would then read as a decline. Its `error` stays None, so a skip still sets the first baseline as before (`qualification.py:444`, `:548`); the baseline sets only the reported direction (`drift_detector.py:186-193`), and R14 decides whether to re-capture it. Ranked: (1) chosen, `True`; (2) `HELD_FROM_DRIFT`: identical today, but a lifted hold returns skips to drift; (3) setting `error` on the skip: also stops it becoming a baseline, a change the finding did not ask for.
  2. Hold `__crew__` reports at the drift scheduler: also silences the emergence engine's collective tests, and changes a shared seam.
  3. Reset the five tests' history: a live-data migration, and week-to-week variation of an unqualified gauge would still drive the alert.
- **Why this is within the envelope:** a flat history has a standard deviation of 0, so z is 0 (`drift_detector.py:181-182`). No drift has ever fired on these tests, so the hold removes no alert and weakens no control. Lifting it is R14's call.

**D12, the cost of the activated path (Amendment A1).**
- **Changes:**
  1. One `recent_for_agent` read per resolved owner per computation. A failed read is kept, so it fails each of that owner's threads without a second read, and the aggregate WARNING is unchanged.
  2. `await asyncio.sleep(0)` after each owner read, so the loop runs between whole-collection scans and its longest pause is one fetch. The reviewer's reuse run still showed a 1.35 s gap without it: an awaited synchronous body does not yield.
  3. Synthesis detection and the convergence loop (`_count_convergence_events`, the moved loop) run in a worker thread through `asyncio.to_thread`.
- **Rejected:**
  - a batched read: a new episodic API (R13);
  - a bound on authors: changes AD-569's measure;
  - offloading inside `recent_for_agent`: `episodic.py`, every caller (R13).
- **Remaining cost:** one whole-collection fetch per distinct author per dream, about 0.67 s per 3,000 episodes (reviewer-measured) and linear in store size. The proactive loop already makes such reads each cycle (`proactive.py:1837`, `:1962`, `:2693`).
- **On the loop:** frame diversity and the trigger metric stay on the loop. They embed only for authors whose department resolves, and none does (R12).

## 4. Interaction with the queue

**BF-922 (#1639) merges first.** It changes `cognitive_agent.py`, `sub_tasks/compose.py`, `sub_tasks/evaluate.py`, `sub_tasks/query.py`, `llm_client.py`, `types.py`, `output_grounding.py` (new) and some tests. This contract edits none of them: its files are `cognitive/behavioral_metrics.py`, `cognitive/behavioral_probes.py` (A1), `ward_room/channels.py` (A1), `runtime.py`, `cognitive/orientation.py`, `proactive.py`, `startup/finalize.py`, `cognitive/counselor.py`, three existing tests, two new tests, `PROGRESS.md` and `DECISIONS.md`. The new tests import `Episode` from `probos.types` (an import only). If BF-922's merge moved any SEARCH text here, the orchestrator re-verifies and re-anchors without changing a REPLACE; a changed REPLACE returns to the Architect.

**Tracker anchors.** `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)` (line 739 on this tree) both stay unique whatever BF-922 inserts.

**PR text, BF-923's part:** "BF-923 (#1652). Three callers passed `agent_id` to `EpisodicMemory.recall`, which takes none, and swallowed the `TypeError`: the behavioral metrics' anchor-grounded emergence was 0 on every dream and every crew orientation counted 0 memories. The metric now reads each author's recent episodes by the sovereign id its episodes carry (Ward Room authors are slot ids; the runtime late-binds the identity registry), and both orientation callers count the agent's own episodes, so at stasis recovery each crew member is told how many memories it has (AD-567g's line, never printed before). The behavioral metrics had listed no Ward Room thread at all (`browse_threads` reads `channels=None` as one agent's memberships); they now read the crew channels, never DMs, each author once per computation and with embeddings off the event loop, and the five Tier 3 probes that read them keep their scores but are held from drift until qualified, a skipped run included (BF-921 D3). The Counselor read trust with a method `TrustNetwork` lacks and Hebbian weights with one nothing defines; it now reads trust with `get_score` and records each reading and the first as a captured baseline, while every assessment, DM, Bridge alert and the agent's own wellness view stay exactly as before until the trust gauge is qualified (BF-921 D3; the measurement is on #1523). The Hebbian read is removed, and a profile keeps its latest 50 assessments."

## 5. Consumers of every value this changes

**(a) The behavioral snapshot** (Amendment A1: D10 gives the producer real threads, so every metric below the empty-snapshot return at `behavioral_metrics.py:193` now runs). It comes from one producer call (`dreaming.py:1663`; `compute_behavioral_metrics` has no other caller, section 12). The anchor metric is `anchor_grounded_rate`, `anchor_independence_score` and `anchor_analyzed_threads`.
- **What moves:** synthesis (`synthesis_rate`, `synthesis_threads`), the anchor metric, `convergence_events` and `unverified`, `threads_analyzed`, and the composite.
- **What stays:** frame diversity and the trigger rate stay 0 (their department lookup receives slot ids, R12); convergence correctness stays None (no verifier, R1).
- **Readers:**
- `BehavioralSnapshot` → `behavioral_quality_score`, the mean of four or five terms of which `anchor_grounded_rate` is one (`behavioral_metrics.py:202-213`): it rises when threads are grounded.
- `dreaming.py:1668-1682` (a DEBUG line), `:1704` → `_step_15_reflection_promotion` → `[Reflection] Dream cycle emergence snapshot: ... behavioral_quality=<x>.` episode text with no owner (`dreaming.py:2976-2986`), and the dream report (`:1803-1807`, `types.py:914-918`).
- `routers/system.py:682-708` (`/behavioral-metrics` and its history): Captain-facing.
- **The five Tier 3 probes** (`behavioral_probes.py`: `frame_diversity`, `synthesis_detection`, `cross_dept_trigger_rate`, `convergence_correctness`, `anchor_grounded_emergence`). Each is a collective test for `__crew__` with `passed=True` always, run weekly by the drift scheduler (`drift_detector.py:345-357`; `drift_check_tiers` default `[1, 2, 3]`, `config.py:3619`) and on demand (`run_now`, `:402-414`).
  - **Without a hold:** after a history of zeros, the first non-zero score has |z| = √n for n earlier samples (window 20, `config.py:3617`), so it is critical from n = 9 (`config.py:3615`); the live history is all zeros. A critical `__crew__` report reaches:
    1. the Counselor's `_on_qualification_drift` (`counselor.py:1468-1542`), which assesses `__crew__` on default inputs (no agent: wellness 1.0), so `_maybe_send_therapeutic_dm` returns at its first line (`counselor.py:2449-2450`) and no Bridge alert is on that path. This holds for all five tests: the handler reads `test_name` only to log.
    2. VitalsMonitor, which counts critical reports (`vitals_monitor.py:184-188`) and broadcasts `medical_alert` on every 5 s heartbeat (`:49`, `:345-367`) to the Diagnostician (`diagnostician.py:59`): an LLM diagnosis each time, until the next weekly drift run. Its recommended treatment is not dispatched (section 12).
  - **D11 holds all five.** Each result is stored with its score and `inconclusive=True`, which `drift_detector.py:150` drops before its statistics, so neither path follows. **A skipped run is held too (Amendment A2):** with no engine, or no snapshot since boot (the engine keeps snapshots in memory only, `behavioral_metrics.py:95`, `:209`, `:265`, so every drift run between a boot and the first dream skips), each probe returns `_skip_result` (10 sites), stored with score 0.0, `error` None, `details.skipped` and `inconclusive=True`. The harness's other results for these names are its exception wrapper (`qualification.py:429-441`, `:534-545`: `inconclusive=True`, `error` set) and its timeout wrapper (`:418-428`, `:523-533`: conclusive), which these probes cannot reach (their `run` has no `await`, so `wait_for` returns before a positive timeout). The store has no other writer (`save_result` is called only at `qualification.py:458` and `:551`). The flag's one behavioural reader is `drift_detector.py:150`.
  - **Disclosed effect E1 (revised by A1):** the scores appear in the qualification store and in the snapshot's display readers (dream report, reflection text, `/behavioral-metrics`, the HXI panel `BehavioralMetricsPanel.tsx`). No drift event, assessment, DM, Bridge alert or medical alert follows them.
  - **Disclosed effect E7 (Amendment A2; display and retrieval, not actions):** (1) `/qualify run` and `/qualify baselines` (`experience/commands/commands_qualification.py:111-188`, `:231-264`) print the stored scores and baselines with no `inconclusive` column (the file has no `inconclusive` reference), so the Captain sees held scores as plain numbers; (2) the dream's ownerless reflection text (`dreaming.py:2978`, `behavioral_quality=<x>`) can be returned by global recall (`runtime.py:5700`, `:6086`, `episodic_memory.recall(text, k=3)`) into the NL planner's `## PAST EXPERIENCE` section (`cognitive/decomposer.py:352`); sovereign `recent_for_agent` does not return it (round-2 reviewer, executed). Both paths existed before BF-923 and carried 0, and neither is a crew-facing action, so D11 does not hold them: D11 controls the automatic drift actions (drift signal, Counselor assessment, medical alert), not every display or retrieval of the number.
- **Cost (disclosed effect E6, A1).** Step 13 now reads threads and episodes. It makes one whole-collection fetch per distinct author per dream (about 0.67 s per 3,000 episodes, reviewer-measured, linear in store size), with the loop running between fetches; synthesis and convergence embeddings run in a worker thread (D12). The dream's wall time grows by both.
- `BEHAVIORAL_METRICS_UPDATED`: emitted only when `emit_event_fn` is passed (`behavioral_metrics.py:247-260`); the dream path passes none (`dreaming.py:1663-1667`). Unchanged.

**(b) The orientation count** (`episodic_memory_count`): `build_orientation` copies it into `OrientationContext` (`orientation.py:220`); `render_warm_boot_orientation` prints it when above 0 (`:413-416`): **disclosed effect E2**, at stasis recovery each crew member with episodes reads "You have N episodic memories from before stasis." for the first time, a true statement about its own memory (AD-567g's design; not a judgement, so no hold). The cold-start renderer (`:348-354`) receives its count from `agent_onboarding.py:393`, not from these callers. The proactive renderers print no count: no visible change (E3). **Disclosed effect E4 (cost):** at stasis recovery `_orient_crew_after_stasis` (`startup/finalize.py:3990`) makes one `count_for_agent` scan per crew agent (`:4019`; `episodic.py:4261`, a whole-collection metadata scan), where the base's call raised at once; not measured on a large store (section 17), read at the first stasis recovery (section 16, R7).

**(c) The Counselor's inputs and the profile's lists.**
- `_gather_agent_metrics`' returned dict: the 14 handlers and the API listed in section 1 pass its five keys to `assess_agent`. Values unchanged (D4).
- `trust_observations`, `observed_baseline`: written by `_record_trust_observation`, read by nothing in `src/` but `to_dict`/`from_dict` (new). They reach `profile_json` (`counselor.py:382`), so `/profile/{agent_id}` (`routers/counselor.py:48-64`, clinical access) shows them: the agent's trust, already shown in the clinical trust stream (AD-903). The self-telemetry whitelist (`self_telemetry_domains.py:81-104`) reads neither: crew-facing view unchanged. This is **disclosed effect E5**: `/profile/{agent_id}` gains `observed_baseline` and `trust_observations` under clinical access; the crew's own wellness view is unchanged (both fields appear only in `cognitive/counselor.py`).
- `assessments` (bounded): `add_assessment`'s AD-506b check (`counselor.py:200`), `latest_assessment` (`:213`), `drift_trend` (`:215-221`; read by `self_telemetry_domains.py:104` and `routers/counselor.py:644`), `routers/counselor.py:646` (`[-assess_n:]`, default 10). Each reads at most the last 10 by default.
- `_on_trust_update`'s reassessment loop (`counselor.py:1686-1719`): trigger unchanged (D8); each reassessment now also records one trust reading.

## 6. Milestones and tests

**M1 (HIGH: raised from STANDARD by Amendment A1, whose D11 hold is a safety property), §7.1 to §7.7d.** First heading: `### 7.1 \`src/probos/cognitive/behavioral_metrics.py\` (M1)`. Commit "BF-923 M1: the behavioral metrics read the crew's threads and their authors' episodes; the orientation counts read the episodic store through APIs it has", body ending "The producer listed no thread (browse_threads reads channels=None as one agent's memberships); it now reads the crew channels, never DMs. Ward Room authors are slot ids and episodes carry sovereign ids, so the runtime late-binds the identity registry into the behavioral metrics engine; each author is read once per computation, and synthesis and convergence embed off the event loop. Every result of the five Tier 3 behavioral probes, a skipped run included, is held from drift until qualified and keeps its score (BF-921 D3). At stasis recovery each crew member is told its own episode count (AD-567g's line, printed for the first time)."

Before editing, grep the pins: `grep -rn "_compute_anchor_grounded_emergence\|mock_memory.recall\|episodic_memory_count\|Warm boot orientation\|render_warm_boot_orientation\|browse_threads\|list_channels\|_compute_convergence_correctness\|inconclusive" tests/`.

Tests first: with §7.6, §7.7 and §7.7d applied and §7.1 to §7.5 and §7.7a to §7.7c not, exactly 23 cases fail: Amendment A1's 12 and Amendment A2's 2 (after this list) and these 9: `test_the_anchor_metric_reads_each_authors_recent_episodes` (`assert 0 == 1` on `analyzed_threads`), `test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry` (`AttributeError: ... 'set_identity_registry'`), `test_a_failing_store_is_reported_once_at_warning` (no WARNING record), `test_the_booted_runtime_reads_crew_authors_episodes` (`assert 0 == 1`), `test_count_agent_episodes_counts_the_agents_own_episodes` and `test_a_failing_count_is_logged_at_warning_and_reports_none` (`ImportError: count_agent_episodes`), `test_the_proactive_supplement_is_built_with_the_agents_episode_count` (`assert 0 == 2`), `test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count` (`ImportError: _orient_crew_after_stasis`), and `TestAnchorGroundedEmergence`'s `test_anchor_analysis_with_memory` in `test_behavioral_metrics.py` (the autospec rejects `recall(query=, agent_id=, limit=)`, which is swallowed: `assert 0 == 1`). `test_the_old_call_is_rejected_by_the_real_recall` (the issue's reproduction) and `test_anchor_insufficient_episodes` pass on both sides. Amendment A1's 12 cases fail on the base and on M1's round-1 candidate:
- `test_the_dream_metrics_read_the_crew_channels_and_not_dms`: no thread is fetched.
- `test_a_failing_ward_room_read_is_logged_at_warning_and_raised`: `DID NOT RAISE`.
- `test_each_author_is_read_once_per_computation`: base, `analyzed_threads` 0; candidate, 20 reads.
- `test_a_failing_author_fails_only_its_threads_and_is_read_once`: base, `analyzed_threads` 0; candidate, two reads of `a-bad`.
- `test_the_author_reads_yield_to_the_event_loop`: no new loop turn between reads.
- `test_synthesis_embeds_off_the_event_loop` and `test_convergence_embeds_off_the_event_loop`: `seen[-1] > seen[0]`.
- `test_the_behavioral_probes_are_held_from_drift`, 5 cases: `inconclusive is True`.
- Amendment A2's `test_a_skipped_probe_run_is_held_from_drift`, 2 cases: `row.inconclusive is True` (fails on the base, on M1's round-1 candidate and on the round-2 candidate).

`TestComputeBehavioralMetrics`' three tests pass on both sides (their `MockWardRoom` ignores `channels`). Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf923_episodic_recall_callers.py tests/test_behavioral_metrics.py tests/test_orientation.py tests/test_ad576_llm_unavailability.py tests/test_bf235_stale_identity_cache.py tests/test_proactive.py tests/test_dreaming.py tests/test_bf138_sovereign_id_completion.py tests/test_ad583f_observable_state.py tests/test_ad566c_drift_detection.py tests/test_ad566e_collective_tests.py tests/test_ward_room.py tests/test_ward_room_dms.py -n 0 -q
```

(Round 1: 291 passed without the five added files; after Amendment A1, 524 passed. Amendment A2 adds 2 cases to `test_bf923_episodic_recall_callers.py`: expect 526 passed. A2's tests first: with A2's test (section 7.7) on the round-2 candidate and section 7.7c Pair 7 not applied, exactly 2 cases fail, `test_a_skipped_probe_run_is_held_from_drift[no-engine]` and `[no-snapshot-since-boot]` at `row.inconclusive is True`, and 524 pass.)

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
        # BF-923 (#1652): one read per owner per computation. recent_for_agent fetches the whole
        # collection, so reading per thread repeated that fetch for every thread an author posted in.
        # A failed read is kept too, so it fails each of that owner's threads without a second read.
        owner_reads: dict[str, Any] = {}

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
                    if owner_id not in owner_reads:
                        try:
                            owner_reads[owner_id] = await episodic_memory.recent_for_agent(owner_id, k=10)
                        except Exception as exc:
                            owner_reads[owner_id] = exc
                        await asyncio.sleep(0)  # BF-923: each read is a synchronous full scan; let the loop run between reads
                    eps = owner_reads[owner_id]
                    if isinstance(eps, Exception):
                        raise eps
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

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

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
    agent._birth_timestamp = time.time() - 60  # set by hand: fresh runtime crew lack it (filed, section 18 R11); this tests the count inside the window

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


# --- Amendment A1: the producer's thread read, its cost, and the Tier 3 hold ---------------------------


class _Ticker:
    """Counts event-loop turns. Work that holds the loop shows as no new turns while it runs."""

    def __init__(self) -> None:
        self.ticks = 0
        self._task: asyncio.Task[None] | None = None

    async def _spin(self) -> None:
        while True:
            self.ticks += 1
            await asyncio.sleep(0)

    async def __aenter__(self) -> _Ticker:
        self._task = asyncio.create_task(self._spin())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._task is not None
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


@pytest.mark.asyncio
async def test_the_dream_metrics_read_the_crew_channels_and_not_dms(tmp_path) -> None:
    """The producer on a real Ward Room. ``browse_threads`` reads ``channels=None`` as the given agent's
    memberships, so ``agent_id=""`` read no thread and no metric ran. A DM is private to its two parties."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService

    ward = WardRoomService(db_path=str(tmp_path / "ward.db"))
    await ward.start()
    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        crew_channel = next(c for c in await ward.list_channels() if c.channel_type == "ship")
        dm_channel = await ward.get_or_create_dm_channel("author-a", "author-b")
        thread_ids: dict[str, str] = {}
        for label, channel in (("crew", crew_channel), ("dm", dm_channel)):
            thread = await ward.create_thread(channel.id, "author-a", f"BF-923 {label} thread", "An opening observation.")
            await ward.create_post(thread.id, "author-b", f"{label}: a second observation.")
            await ward.create_post(thread.id, "author-a", f"{label}: a third observation.")
            await ward.create_post(thread.id, "author-b", f"{label}: a fourth observation.")
            thread_ids[label] = thread.id
        engine = BehavioralMetricsEngine()
        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5), \
                patch.object(ward, "get_thread", wraps=ward.get_thread) as get_thread:
            snapshot = await engine.compute_behavioral_metrics(ward_room=ward, episodic_memory=memory)
    finally:
        await memory.stop()
        await ward.stop()

    read = {call.args[0] for call in get_thread.await_args_list}
    assert thread_ids["crew"] in read
    assert thread_ids["dm"] not in read  # never fetched, so never analysed
    assert snapshot.threads_analyzed == 1
    assert snapshot.anchor_analyzed_threads == 1


@pytest.mark.asyncio
async def test_a_failing_ward_room_read_is_logged_at_warning_and_raised(caplog) -> None:
    """The dream's step 13 catches it and continues (cognitive/dreaming.py:1683); no zero snapshot is kept."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService

    ward = create_autospec(WardRoomService, instance=True)
    ward.list_channels.side_effect = RuntimeError("ward room offline")
    engine = BehavioralMetricsEngine()

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.behavioral_metrics"):
        with pytest.raises(RuntimeError, match="ward room offline"):
            await engine.compute_behavioral_metrics(ward_room=ward)

    assert "BF-923 (#1652): the Ward Room read failed" in caplog.text
    assert engine.latest_snapshot is None


@pytest.mark.asyncio
async def test_each_author_is_read_once_per_computation(tmp_path) -> None:
    """``recent_for_agent`` fetches the whole collection; a read per thread repeated it for every thread an
    author posted in (13.4 s for 10 threads on a 3,000-episode store, review round 1)."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
        threads = [_thread("author-a", "author-b", thread_id=f"bf923-t{i}") for i in range(10)]
        with patch.object(memory, "recent_for_agent", wraps=memory.recent_for_agent) as read:
            result = await engine._compute_anchor_grounded_emergence(threads, memory)
    finally:
        await memory.stop()

    assert result["analyzed_threads"] == 10
    assert sorted(call.args[0] for call in read.await_args_list) == ["author-a", "author-b"]


@pytest.mark.asyncio
async def test_a_failing_author_fails_only_its_threads_and_is_read_once(caplog) -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    def read(owner_id: str, k: int = 5, **_: Any) -> list[Any]:
        if owner_id == "a-bad":
            raise RuntimeError("shard offline")
        return [MagicMock(), MagicMock()]

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    memory.recent_for_agent.side_effect = read
    threads = [
        _thread("a1", "a2", thread_id="bf923-ok"),
        _thread("a1", "a-bad", thread_id="bf923-bad-1"),
        _thread("a2", "a-bad", thread_id="bf923-bad-2"),
    ]

    with patch("probos.cognitive.social_verification.compute_anchor_independence", return_value=0.6), \
            caplog.at_level(logging.WARNING, logger="probos.cognitive.behavioral_metrics"):
        result = await engine._compute_anchor_grounded_emergence(threads, memory)

    assert result["analyzed_threads"] == 1
    assert [call.args[0] for call in memory.recent_for_agent.await_args_list].count("a-bad") == 1
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "anchor analysis failed for 2 of 3 threads" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_author_reads_yield_to_the_event_loop() -> None:
    """Each read is a synchronous full scan; the loop runs between reads, so its longest pause is one read."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    seen: list[int] = []
    async with _Ticker() as ticker:
        def read(owner_id: str, k: int = 5, **_: Any) -> list[Any]:
            seen.append(ticker.ticks)
            return [MagicMock(), MagicMock()]

        memory.recent_for_agent.side_effect = read
        with patch("probos.cognitive.social_verification.compute_anchor_independence", return_value=0.6):
            result = await engine._compute_anchor_grounded_emergence([_thread("a1", "a2")], memory)

    assert result["analyzed_threads"] == 1
    assert len(seen) == 2
    assert seen[1] > seen[0]


@pytest.mark.asyncio
async def test_synthesis_embeds_off_the_event_loop() -> None:
    """Synthesis embeds the thread and every post with the synchronous embedder; the loop keeps running."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService
    from probos.ward_room.models import WardRoomChannel

    now = time.time()
    ward = create_autospec(WardRoomService, instance=True)
    ward.list_channels.return_value = [
        WardRoomChannel(id="ch-1", name="All Hands", channel_type="ship", department="", created_by="system", created_at=now),
    ]
    ward.browse_threads.return_value = [
        SimpleNamespace(id="bf923-t1", channel_id="ch-1", channel_name="All Hands", title="BF-923 thread"),
    ]
    ward.get_thread.return_value = {"posts": [
        {"id": f"p{i}", "author_id": f"a{i % 2}", "author_callsign": "", "body": f"observation {i}", "created_at": now - 10.0 * i}
        for i in range(4)
    ]}
    engine = BehavioralMetricsEngine()
    seen: list[int] = []
    async with _Ticker() as ticker:
        def slow_embed(text: str) -> list[float]:
            seen.append(ticker.ticks)
            time.sleep(0.02)
            return [0.5] * 10

        with patch("probos.cognitive.behavioral_metrics.embed_text", side_effect=slow_embed), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5), \
                patch.object(engine, "_compute_convergence_correctness", AsyncMock(return_value={
                    "total": 0, "correct": 0, "incorrect": 0, "unverified": 0, "correctness_rate": None,
                })):
            snapshot = await engine.compute_behavioral_metrics(ward_room=ward)

    assert snapshot.threads_analyzed == 1
    assert len(seen) == 5  # the thread and its four posts
    assert seen[-1] > seen[0]


@pytest.mark.asyncio
async def test_convergence_embeds_off_the_event_loop() -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine()
    seen: list[int] = []
    async with _Ticker() as ticker:
        def slow_embed(text: str) -> list[float]:
            seen.append(ticker.ticks)
            time.sleep(0.02)
            return [0.5] * 10

        with patch("probos.cognitive.behavioral_metrics.embed_text", side_effect=slow_embed), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.9):
            result = await engine._compute_convergence_correctness([_thread("a1", "a2", "a3")])

    assert result["total"] == 1
    assert len(seen) == 3  # one post per author
    assert seen[-1] > seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe_class",
    [
        "FrameDiversityProbe",
        "SynthesisDetectionProbe",
        "CrossDeptTriggerProbe",
        "ConvergenceCorrectnessProbe",
        "AnchorGroundedEmergenceProbe",
    ],
)
async def test_the_behavioral_probes_are_held_from_drift(tmp_path, probe_class: str) -> None:
    """BF-921 D3: each probe's history is a run of zeros, so a first real score would read as critical drift
    for ``__crew__`` (a Counselor assessment, VitalsMonitor's medical alert). The score is kept; drift skips it."""
    import dataclasses

    from probos.cognitive import behavioral_probes
    from probos.cognitive.behavioral_metrics import BehavioralSnapshot
    from probos.cognitive.drift_detector import DriftDetector
    from probos.cognitive.qualification import QualificationStore, TestResult
    from probos.config import QualificationConfig

    probe = getattr(behavioral_probes, probe_class)()
    snapshot = BehavioralSnapshot(
        timestamp=time.time(),
        threads_analyzed=4,
        frame_diversity_score=0.6,
        synthesis_rate=0.6,
        cross_dept_trigger_rate=0.6,
        convergence_correctness_rate=0.6,
        anchor_grounded_rate=0.6,
    )
    runtime = SimpleNamespace(_behavioral_metrics_engine=SimpleNamespace(latest_snapshot=snapshot))
    result = await probe.run("__crew__", runtime)
    assert result.score == 0.6
    assert result.inconclusive is True

    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        now = time.time()
        for subject in ("__crew__", "bf923-control"):
            for i in range(19):  # the live history: every run scored 0
                await store.save_result(TestResult(
                    agent_id=subject, test_name=probe.name, tier=3, score=0.0, passed=True,
                    timestamp=now - 3600.0 * (i + 1), duration_ms=0.0,
                ))
        await store.save_result(result)
        await store.save_result(dataclasses.replace(result, agent_id="bf923-control", inconclusive=False))
        detector = DriftDetector(store, QualificationConfig())
        held = await detector.analyze_agent("__crew__", [probe.name])
        unheld = await detector.analyze_agent("bf923-control", [probe.name])
    finally:
        await store.stop()

    assert unheld.overall_severity == "critical"  # the premise: what the first real score would raise
    assert held.overall_severity == "normal"
    assert not held.drift_detected


# --- Amendment A2: a skipped probe run is held too -----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["no-engine", "no-snapshot-since-boot"])
async def test_a_skipped_probe_run_is_held_from_drift(tmp_path, state: str) -> None:
    """BF-711, BF-921 D3: with no engine, or no snapshot since boot (the engine keeps snapshots in memory only),
    each probe returns a skip result that measured nothing. Through the real harness and store it is stored
    inconclusive, enters no drift statistics, and still sets the first baseline (its error stays None)."""
    from probos.cognitive import behavioral_probes
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.cognitive.drift_detector import DriftDetector
    from probos.cognitive.qualification import QualificationHarness, QualificationStore
    from probos.config import QualificationConfig

    engine = None if state == "no-engine" else BehavioralMetricsEngine()
    runtime = SimpleNamespace(_behavioral_metrics_engine=engine)
    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        harness = QualificationHarness(store)
        for probe_class in (
            behavioral_probes.FrameDiversityProbe,
            behavioral_probes.SynthesisDetectionProbe,
            behavioral_probes.CrossDeptTriggerProbe,
            behavioral_probes.ConvergenceCorrectnessProbe,
            behavioral_probes.AnchorGroundedEmergenceProbe,
        ):
            harness.register_test(probe_class())
        results = await harness.run_collective(3, runtime)
        names = [r.test_name for r in results]
        stored = [await store.get_latest("__crew__", name) for name in names]
        report = await DriftDetector(store, QualificationConfig()).analyze_agent("__crew__", names)
    finally:
        await store.stop()

    assert len(names) == 5
    for row in stored:
        assert row is not None
        assert row.details.get("skipped") is True  # the skip path, not a measured score
        assert row.score == 0.0
        assert row.error is None
        assert row.inconclusive is True  # BF-923 A2: the skip is held
        assert row.is_baseline is True  # unchanged: a skip with no error still sets the first baseline
    assert [signal.sample_count for signal in report.signals] == [0] * 5
    assert not report.drift_detected
```

### 7.7a `src/probos/cognitive/behavioral_metrics.py` (M1, Amendment A1: the crew-channel scope; synthesis and convergence off the event loop)

These pairs are disjoint from §7.1's. The one-read-per-owner change is in §7.1's pair 2.

Pair 1:

SEARCH:
```python
import logging
import time
from collections import defaultdict, deque
```
REPLACE:
```python
import asyncio
import logging
import time
from collections import defaultdict, deque
```

Pair 2:

SEARCH:
```python
        # 1. Retrieve qualifying threads
        since = now - (cfg.thread_lookback_hours * 3600)
        threads = await ward_room.browse_threads(
            agent_id="",
            channels=None,
            limit=100,
            since=since,
        )
```
REPLACE:
```python
        # 1. Retrieve qualifying threads
        since = now - (cfg.thread_lookback_hours * 3600)
        # BF-923 (#1652): browse_threads reads channels=None as the given agent's memberships, so
        # agent_id="" read no thread and every metric stayed 0. Read the crew channels explicitly;
        # a DM is private to its two parties and stays out (crew_channel_ids).
        from probos.ward_room.channels import crew_channel_ids

        try:
            channel_ids = crew_channel_ids(await ward_room.list_channels())
            threads = await ward_room.browse_threads(
                agent_id="",
                channels=channel_ids,
                limit=100,
                since=since,
            )
        except Exception:
            logger.warning(
                "BF-923 (#1652): the Ward Room read failed; no behavioral snapshot this cycle",
                exc_info=True,
            )
            raise  # BF-923: the dream logs it and skips step 13 (cognitive/dreaming.py:1683)
```

Pair 3:

SEARCH:
```python
        frame_result = self._compute_frame_diversity(qualifying_threads, get_department)
        synthesis_result = self._compute_synthesis_detection(qualifying_threads)
        trigger_result = self._compute_cross_dept_triggers(qualifying_threads, get_department)
```
REPLACE:
```python
        frame_result = self._compute_frame_diversity(qualifying_threads, get_department)
        # BF-923 (#1652): synthesis embeds every post synchronously (ONNX); run it off the event loop.
        synthesis_result = await asyncio.to_thread(self._compute_synthesis_detection, qualifying_threads)
        trigger_result = self._compute_cross_dept_triggers(qualifying_threads, get_department)
```

Pair 4:

SEARCH:
```python
    async def _compute_convergence_correctness(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 4: Convergence Correctness.

        Detect convergence (multiple agents saying similar things) and track
        whether converged conclusions have verifiable outcomes. AD-583f
        populates correctness via ObservableStateVerifier (satisfies AD-569d).
        """
        cfg = self._config
        convergence_events = 0

        for thread in threads:
            posts = thread["posts"]
            if len(posts) < cfg.convergence_min_agreeing + 1:
                continue

            # Group posts by author and embed
            author_embeddings: dict[str, list[float]] = {}
            for post in posts:
                author = post.get("author_id", "")
                body = post.get("body", "")
                if not author or not body or author in author_embeddings:
                    continue
                author_embeddings[author] = embed_text(body[:1000])

            if len(author_embeddings) < cfg.convergence_min_agreeing:
                continue

            # Check for pairwise convergence
            authors = list(author_embeddings.keys())
            agreeing_pairs = 0
            total_pairs = 0
            for i in range(len(authors)):
                for j in range(i + 1, len(authors)):
                    sim = _cosine_similarity(
                        author_embeddings[authors[i]],
                        author_embeddings[authors[j]],
                    )
                    total_pairs += 1
                    if sim >= cfg.convergence_similarity_threshold:
                        agreeing_pairs += 1

            if total_pairs > 0 and agreeing_pairs / total_pairs >= 0.5:
                convergence_events += 1

        # AD-583f: Verify converging claims against observable state
```
REPLACE:
```python
    def _count_convergence_events(self, threads: list[dict[str, Any]]) -> int:
        """Metric 4's detection: threads in which most pairs of authors post similar text.

        BF-923 (#1652): the loop moved unchanged out of ``_compute_convergence_correctness``. It embeds
        one post per author per thread synchronously (ONNX), so that method runs it in a worker thread.
        """
        cfg = self._config
        convergence_events = 0

        for thread in threads:
            posts = thread["posts"]
            if len(posts) < cfg.convergence_min_agreeing + 1:
                continue

            # Group posts by author and embed
            author_embeddings: dict[str, list[float]] = {}
            for post in posts:
                author = post.get("author_id", "")
                body = post.get("body", "")
                if not author or not body or author in author_embeddings:
                    continue
                author_embeddings[author] = embed_text(body[:1000])

            if len(author_embeddings) < cfg.convergence_min_agreeing:
                continue

            # Check for pairwise convergence
            authors = list(author_embeddings.keys())
            agreeing_pairs = 0
            total_pairs = 0
            for i in range(len(authors)):
                for j in range(i + 1, len(authors)):
                    sim = _cosine_similarity(
                        author_embeddings[authors[i]],
                        author_embeddings[authors[j]],
                    )
                    total_pairs += 1
                    if sim >= cfg.convergence_similarity_threshold:
                        agreeing_pairs += 1

            if total_pairs > 0 and agreeing_pairs / total_pairs >= 0.5:
                convergence_events += 1

        return convergence_events

    async def _compute_convergence_correctness(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 4: Convergence Correctness.

        Detect convergence (multiple agents saying similar things) and track
        whether converged conclusions have verifiable outcomes. AD-583f
        populates correctness via ObservableStateVerifier (satisfies AD-569d).
        """
        # BF-923 (#1652): the detection embeds synchronously; run it off the event loop.
        convergence_events = await asyncio.to_thread(self._count_convergence_events, threads)

        # AD-583f: Verify converging claims against observable state
```

### 7.7b `src/probos/ward_room/channels.py` (M1, Amendment A1: the crew channels)

Pair 1:

SEARCH:
```python
from typing import Any, Callable, Awaitable
```
REPLACE:
```python
from typing import Any, Callable, Awaitable, Iterable
```

Pair 2:

SEARCH:
```python
def dm_channel_keys(name: str) -> tuple[str, str] | None:
    """AD-1229: the two keys of a ``dm-<key>-<key>`` channel name, or None for any other name."""
    parts = name.split("-")
    if len(parts) != 3 or parts[0] != "dm" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]
```
REPLACE:
```python
def dm_channel_keys(name: str) -> tuple[str, str] | None:
    """AD-1229: the two keys of a ``dm-<key>-<key>`` channel name, or None for any other name."""
    parts = name.split("-")
    if len(parts) != 3 or parts[0] != "dm" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def crew_channel_ids(channels: Iterable[WardRoomChannel]) -> list[str]:
    """BF-923 (#1652): the ids of the channels a ship-level measurement may read: every type but ``dm``.

    Ship, department and custom channels are open to the crew. A DM channel (between two crew members,
    or a crew member and the Captain) is private to its two parties; every writer creates it with
    ``channel_type="dm"`` (``get_or_create_dm_channel`` and the three Captain-DM writers).
    """
    return [channel.id for channel in channels if channel.channel_type != "dm"]
```

### 7.7c `src/probos/cognitive/behavioral_probes.py` (M1, Amendment A1: the hold, D11)

Pair 1:

SEARCH:
```python
CREW_AGENT_ID = "__crew__"
```
REPLACE:
```python
CREW_AGENT_ID = "__crew__"

# BF-923 (#1652), BF-921 D3: the five behavioral gauges were 0 on every run until BF-923 gave the
# engine its threads, so their history is a run of zeros and the first real score reads as critical
# drift for ``__crew__``, which reaches the Counselor and VitalsMonitor's medical alert. Until the
# gauges are qualified, each result is stored with its score but marked inconclusive, which the drift
# detector excludes (drift_detector.py:150). This stretches BF-711's flag from "measured nothing" to
# "not a verdict yet". Lifting the hold is the qualifying issue's call.
HELD_FROM_DRIFT = True
```

Pair 2:

SEARCH:
```python
            tier=3,
            score=snapshot.frame_diversity_score,
            passed=True,
```
REPLACE:
```python
            tier=3,
            score=snapshot.frame_diversity_score,
            passed=True,
            inconclusive=HELD_FROM_DRIFT,  # BF-923 (#1652): held from drift until qualified
```

Pair 3:

SEARCH:
```python
            tier=3,
            score=snapshot.synthesis_rate,
            passed=True,
```
REPLACE:
```python
            tier=3,
            score=snapshot.synthesis_rate,
            passed=True,
            inconclusive=HELD_FROM_DRIFT,  # BF-923 (#1652): held from drift until qualified
```

Pair 4:

SEARCH:
```python
            tier=3,
            score=snapshot.cross_dept_trigger_rate,
            passed=True,
```
REPLACE:
```python
            tier=3,
            score=snapshot.cross_dept_trigger_rate,
            passed=True,
            inconclusive=HELD_FROM_DRIFT,  # BF-923 (#1652): held from drift until qualified
```

Pair 5:

SEARCH:
```python
            tier=3,
            score=score,
            passed=True,
```
REPLACE:
```python
            tier=3,
            score=score,
            passed=True,
            inconclusive=HELD_FROM_DRIFT,  # BF-923 (#1652): held from drift until qualified
```

Pair 6:

SEARCH:
```python
            tier=3,
            score=snapshot.anchor_grounded_rate,
            passed=True,
```
REPLACE:
```python
            tier=3,
            score=snapshot.anchor_grounded_rate,
            passed=True,
            inconclusive=HELD_FROM_DRIFT,  # BF-923 (#1652): held from drift until qualified
```

Pair 7:

SEARCH:
```python
        tier=3,
        score=0.0,
        passed=True,
```
REPLACE:
```python
        tier=3,
        score=0.0,
        passed=True,
        # BF-923 A2 (#1652): a skip measured nothing (BF-711), so it stays out of drift whatever
        # HELD_FROM_DRIFT says; its error stays None, so it still sets the first baseline.
        inconclusive=True,
```

### 7.7d `tests/test_behavioral_metrics.py` (M1, Amendment A1: the Ward Room double lists its channels)

Pair 1:

SEARCH:
```python
from probos.events import EventType
```
REPLACE:
```python
from probos.events import EventType
from probos.ward_room.models import WardRoomChannel
```

Pair 2:

SEARCH:
```python
class MockWardRoom:
    def __init__(self, threads_data: list[dict]):
        self._threads = threads_data

    async def browse_threads(self, agent_id="", channels=None, limit=50, since=0.0):
        return [td["thread"] for td in self._threads]
```
REPLACE:
```python
class MockWardRoom:
    def __init__(self, threads_data: list[dict]):
        self._threads = threads_data

    async def list_channels(self, agent_id=None):
        # BF-923 (#1652): the engine lists the channels and browses the crew ones explicitly
        # (browse_threads reads channels=None as one agent's memberships).
        return [WardRoomChannel(id="ch-1", name="Engineering", channel_type="department",
                                department="engineering", created_by="system", created_at=0.0)]

    async def browse_threads(self, agent_id="", channels=None, limit=50, since=0.0):
        return [td["thread"] for td in self._threads]
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

**BF-923 (2026-10-25), #1652 -- the episodic recall callers and the Counselor's assessment inputs read APIs their dependencies have.** Three callers passed `agent_id` to `EpisodicMemory.recall`, which takes none, and swallowed the `TypeError`. The behavioral metrics' anchor-grounded emergence now reads each Ward Room author's recent episodes (`recent_for_agent`) by the sovereign id its episodes carry (the runtime late-binds the identity registry: authors are slot ids), and reports failures once at WARNING. Both orientation callers count the agent's own episodes (`count_agent_episodes`, `count_for_agent`); the stasis-recovery orientation moved into `_orient_crew_after_stasis` and now tells each crew member its episode count, a line AD-567g designed and no one had seen. The Counselor read trust with `TrustNetwork.score` (absent) and Hebbian weights with `get_weights_for` (never defined): it now reads trust with `get_score` and records each reading on the profile (`trust_observations`) with the first as the captured baseline (`observed_baseline`), while every assessment keeps `TRUST_DEFAULT` and the default baseline, so no wellness change, DM, Bridge alert or wellness-view change follows a reading until the gauge is qualified (BF-921 D3; the measurement is on #1523). The Hebbian read is removed. A profile keeps its latest 50 assessments and readings. Amendment A1: the producer had listed no thread (`browse_threads` reads `channels=None` as one agent's memberships), so every behavioral metric was 0 whatever the read. It now reads the crew channels (never DMs, `crew_channel_ids`) and each author once per computation, with synthesis and convergence embedding off the event loop. The five Tier 3 behavioral probes keep their scores but are held from drift until the gauges are qualified (BF-921 D3), so no Counselor assessment or medical alert follows them. New: `tests/test_bf923_episodic_recall_callers.py`, `tests/test_bf923_counselor_assessment_inputs.py`. The contract is `prompts/bf-923-episodic-recall-callers-and-counselor-assessment-inputs.md`.
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
- *Thread scope (A1).* The behavioral metrics read the crew channels through `list_channels()` and `browse_threads(channels=...)`. DM channels are private to their two parties and are not read (`crew_channel_ids`). A failed read raises to the dream, which skips the step; no zero snapshot is recorded.
- *Tier 3 hold (A1).* The five behavioral probes store their scores marked inconclusive, which drift statistics exclude. Their history is all zeros, so a first real score would read as critical drift for `__crew__` and reach VitalsMonitor's medical alert. Lifting the hold is the qualifying issue's call.
- *Cost (A1).* One episode read per owner per computation, yielding between reads; synthesis and convergence detection embed in a worker thread.
- *Reversal.* Revert the commits; the metrics, the counts and the probe scores return to 0 and the Counselor stops recording readings.

### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916 and BF-921 precedent).

**#1652 checklist text** (the orchestrator records it on the issue):
- [ ] (1) The anchor metric reads each author's recent episodes by sovereign id; failures reported at WARNING (M1).
- [ ] (1b) Both orientation callers count the agent's own episodes; the stasis orientation states it (M1).
- [ ] (1c) The behavioral metrics read the crew channels (no DMs); each author is read once per computation; the five Tier 3 probes are held from drift (M1, Amendment A1).
- [ ] (1d) Filed: the emergence engine's twin scope defect (R10), fresh crew outside the proactive orientation window (R11), the department lookup by slot id (R12).
- [ ] (2) The Counselor reads trust with `get_score` and records it with a captured baseline; every assessment, DM, Bridge alert and wellness view held (M2).
- [ ] (2b) The Hebbian read removed; a profile keeps its latest 50 assessments and readings (M2).
- [ ] (2c) The measurement before any action: posted on #1523 (section 18, R0).
- [ ] First live session after merge: section 16's counts recorded on #1652.

## 9. What this does NOT change

- `EpisodicMemory`, `MockEpisodicMemory` and the identity registry are not edited. The Ward Room gains one pure function (`crew_channel_ids`) and no service change.
- The five metrics' formulas and `compute_anchor_independence` are unchanged. Synthesis and convergence detection run the same code in a worker thread (`_count_convergence_events` is the moved loop). `BEHAVIORAL_METRICS_UPDATED` is still not emitted on the dream path.
- The drift detector, the qualification store, the Counselor's drift handler and VitalsMonitor are unchanged (D11 sits in the probes).
- The emergence engine (`emergence_metrics.py:390`) keeps its defect (R10).
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
| R2 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `owner_reads[owner_id] = await episodic_memory.recent_for_agent(owner_id, k=10)` | `owner_reads[owner_id] = await episodic_memory.recall(query="", agent_id=owner_id, limit=10)` | `test_the_anchor_metric_reads_each_authors_recent_episodes`, `test_anchor_analysis_with_memory` |
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
| R22 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `channels=channel_ids,` | `channels=None,` | `test_the_dream_metrics_read_the_crew_channels_and_not_dms` |
| R23 | 1 | `src/probos/ward_room/channels.py` | `return [channel.id for channel in channels if channel.channel_type != "dm"]` | `return [channel.id for channel in channels]` | `test_the_dream_metrics_read_the_crew_channels_and_not_dms` |
| R24 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `raise  # BF-923: the dream logs it and skips step 13 (cognitive/dreaming.py:1683)` | `return BehavioralSnapshot(timestamp=now, threads_analyzed=0)` | `test_a_failing_ward_room_read_is_logged_at_warning_and_raised` |
| R25 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `"BF-923 (#1652): the Ward Room read failed; no behavioral snapshot this cycle",` | `"the Ward Room read failed",` | `test_a_failing_ward_room_read_is_logged_at_warning_and_raised` |
| R26 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `if owner_id not in owner_reads:` | `if True:` | `test_each_author_is_read_once_per_computation`, `test_a_failing_author_fails_only_its_threads_and_is_read_once` |
| R27 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `owner_reads[owner_id] = exc` | `raise` | `test_a_failing_author_fails_only_its_threads_and_is_read_once` |
| R28 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `await asyncio.sleep(0)  # BF-923: each read is a synchronous full scan; let the loop run between reads` | `pass` | `test_the_author_reads_yield_to_the_event_loop` |
| R29 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `synthesis_result = await asyncio.to_thread(self._compute_synthesis_detection, qualifying_threads)` | `synthesis_result = self._compute_synthesis_detection(qualifying_threads)` | `test_synthesis_embeds_off_the_event_loop` |
| R30 | 1 | `src/probos/cognitive/behavioral_metrics.py` | `convergence_events = await asyncio.to_thread(self._count_convergence_events, threads)` | `convergence_events = self._count_convergence_events(threads)` | `test_convergence_embeds_off_the_event_loop` |
| R31 | 1 | `src/probos/cognitive/behavioral_probes.py` | `HELD_FROM_DRIFT = True` | `HELD_FROM_DRIFT = False` | `test_the_behavioral_probes_are_held_from_drift` |
| R32 | 1 | `src/probos/cognitive/behavioral_probes.py` | `inconclusive=True,` | `inconclusive=False,` | `test_a_skipped_probe_run_is_held_from_drift` |

R22 to R31 are Amendment A1's; R32 is Amendment A2's (R31 does not release a skip, by design: the skip is held whatever `HELD_FROM_DRIFT` says). They run under the M1 command above, now at HIGH. The five `inconclusive=HELD_FROM_DRIFT,` lines are identical, so no row targets one of them; the parametrized hold test fails for any probe that loses its line.

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

**Amendment A1 (2026-10-25, worktree `bf923-consult1` at M2's candidate `a0620929`, tree `eea1b487`).**

```
read src/probos/ward_room/threads.py:319-373        -> browse_threads: channels=None -> SELECT channel_id FROM memberships WHERE agent_id = ?; [] when none
read src/probos/ward_room/service.py:267-295, 390-396 -> list_channels(agent_id=None) admin view; browse_threads(agent_id, channels, ...) after _require_visitor
read src/probos/ward_room/channels.py:1-41, 58-163  -> dm_channel_name/dm_channel_keys module helpers; default channels; list_channels(None) returns every channel
grep -n "channel_type" src/probos/ward_room/models.py -> 17: "ship" | "department" | "custom" | "dm"
read src/probos/routers/wardroom.py:444-450          -> list_channels() then browse_threads("_anonymous", channels=all_ch_ids, ...)
read src/probos/cognitive/emergence_metrics.py:388-395 -> browse_threads(agent_id="", channels=None, limit=50, since=since) (R10)
read src/probos/cognitive/dreaming.py:1655-1684       -> step 13 catches any exception at DEBUG and continues
read src/probos/cognitive/behavioral_metrics.py:18-31, 119-268, 274-470, 475-552, 558-640 -> imports (no asyncio); scope; metrics; convergence loop; anchor loop
read src/probos/cognitive/episodic.py:4109-4157, 4261-4280 -> recent_for_agent / count_for_agent: _collection.get(...) of the whole collection, synchronous
read src/probos/cognitive/behavioral_probes.py:1-251   -> CREW_AGENT_ID; five probes build TestResult(..., tier=3, score=..., passed=True, ...)
read src/probos/cognitive/qualification.py:70-92, 162-268, 496-575 -> TestResult.inconclusive (BF-711); save_result writes it; get_history newest first; baseline when error is None
read src/probos/cognitive/drift_detector.py:80-245, 330-370, 461-491 -> inconclusive filtered after get_history; std 0 -> z 0; collective reports emit QUALIFICATION_DRIFT_DETECTED
read src/probos/agents/medical/vitals_monitor.py:49, 176-189, 345-367 -> interval 5.0; critical drift reports counted; medical_alert broadcast each heartbeat
read src/probos/agents/medical/diagnostician.py:14-59 -> handles medical_alert with an LLM diagnosis
read src/probos/cognitive/counselor.py:1468-1542, 2441-2452 -> drift handler; DM only when unfit or wellness below yellow
read src/probos/startup/finalize.py:5404-5413          -> set_get_department(lambda aid: runtime.ontology.get_agent_department(aid)) (R12)
read src/probos/ontology/departments.py:65-73, 91-105; src/probos/substrate/identity.py:17-20 -> keyed by agent_type; slot id {agent_type}_{pool_name}_{index}_{hash8}
read src/probos/config_models/emergence.py:325-352     -> lookback 72 h, contributors 2, posts 3, synthesis posts 4, convergence min 2, anchor min 3
read src/probos/config.py:3596-3619                    -> QualificationConfig: weekly interval, warning 2.0, critical 3.0, min samples 3, window 20
read tests/test_behavioral_metrics.py:1-80, 555-713    -> MockWardRoom without list_channels; three compute tests; probe tests assert no inconclusive
read tests/test_ad583f_observable_state.py:342-363     -> engine._compute_convergence_correctness(threads) under asyncio.run (unchanged signature)
read logs/bf923r1/reviewer_m1_test_thread_scope.py     -> real WardRoomService(db_path=...) thread and post pattern
```

**Amendment A2 (2026-10-25, worktree `bf923-consult1` at `4bfee423`, tree `6c057fd5`):**

```
grep -n "_skip_result\|inconclusive" src/probos/cognitive/behavioral_probes.py
  29: def _skip_result(test_name: str, reason: str) -> TestResult:   (lines 31-40 set no inconclusive)
  65, 68, 109, 112, 153, 156, 197, 200, 244, 247: return _skip_result(...)   (10 sites)
  76, 120, 164, 209, 255: inconclusive=HELD_FROM_DRIFT   (the five measured returns)
grep -c "await " src/probos/cognitive/behavioral_probes.py
  0
grep -n "Test timed out\|inconclusive=True\|result.error is None\|save_result(result)" src/probos/cognitive/qualification.py
  427, 532: error="Test timed out"   (timeout wrappers, conclusive)
  440, 544: inconclusive=True   (exception wrappers)
  444, 548: result.error is None   (auto-capture in run_test; forced baseline in run_baseline)
  458, 551: await self._store.save_result(result)
grep -n "_snapshots.append" src/probos/cognitive/behavioral_metrics.py
  209, 265
grep -n "similar_episodes = await" src/probos/runtime.py
  5700, 6086
grep -n "PAST EXPERIENCE" src/probos/cognitive/decomposer.py
  352: prompt_parts.append("## PAST EXPERIENCE")
grep -n "Dream cycle emergence snapshot" src/probos/cognitive/dreaming.py
  2978
grep -n "async def _run\|async def _baselines\|run_all(" src/probos/experience/commands/commands_qualification.py
  111, 121, 231
grep -n "_orient_crew_after_stasis\|count_agent_episodes(" src/probos/startup/finalize.py
  3990, 4019, 6342
grep -n "async def count_for_agent" src/probos/cognitive/episodic.py
  4261
```

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

CLAIM (A1): every DM channel is created with channel_type "dm"
RUN:   grep 'channel_type="dm"' src/probos
FOUND: capability_request_notifier.py:119, proactive.py:4875, ward_room/channels.py:251, task_completion_notifier.py:132 (4); create_channel's other callers assignment.py:190 and routers/wardroom.py:260 pass "custom"
HOLDS: yes

CLAIM (A1): the Ward Room has no read-restricted non-DM channel
RUN:   grep -i "private|restricted|invite" src/probos/ward_room
FOUND: messages.py:188, threads.py:459, both "Author is restricted from posting" (2)
HOLDS: yes

CLAIM (A1): only the drift detector reads TestResult.inconclusive, and the HXI shows none
RUN:   grep "inconclusive" src/probos ; grep "inconclusive" ui/src
FOUND: reader drift_detector.py:150; definitions and writers qualification.py:92, 348, 366, 440, 544; communication_benchmarks.py (its own field); ui/src 0
HOLDS: yes

CLAIM (A1): the snapshot's fields have no reader beyond dreaming, the probes and the API
RUN:   grep "behavioral_quality|synthesis_rate|anchor_grounded" src/probos ; grep "_behavioral_metrics_engine|latest_snapshot" src/probos
FOUND: types.py, dreaming.py, behavioral_metrics.py, behavioral_probes.py (4 files); routers/system.py:685-708; collective_tests.py and vitals_monitor.py read other engines
HOLDS: yes

CLAIM (A1): QUALIFICATION_DRIFT_DETECTED has one handler, and the Diagnostician's treatment is not dispatched
RUN:   grep "QUALIFICATION_DRIFT" src/probos ; grep "treatment_intent" src/probos
FOUND: events.py:215, event_persistence.py:360, counselor.py:719, :1082, drift_detector.py:462, :482; treatment_intent diagnostician.py:30 (prompt), experience/panels.py:693 (display)
HOLDS: yes

CLAIM (A1): compute_behavioral_metrics has one production caller and three test calls
RUN:   grep -c "compute_behavioral_metrics" in *.py
FOUND: behavioral_metrics.py 1 (def), dreaming.py 1, tests/test_behavioral_metrics.py 3
HOLDS: yes

CLAIM (A1): the proactive loop already makes whole-collection reads each cycle
RUN:   grep "count_for_agent\(|recent_for_agent\(" src/probos/proactive.py
FOUND: 1837, 1962, 2693 (3)
HOLDS: yes
```

**Amendment A2:**

```
CLAIM: no other TestResult is built in behavioral_probes.py
RUN:   rg -n "TestResult\(" src/probos/cognitive/behavioral_probes.py
FOUND: 31 (_skip_result), 70, 114, 158, 203, 249
HOLDS: yes

CLAIM: nothing but the harness writes qualification results
RUN:   rg -n "\.save_result\(" src/
FOUND: qualification.py:458, :551
HOLDS: yes

CLAIM: run_baseline has no caller
RUN:   rg -n "run_baseline" --glob "*.py" .
FOUND: qualification.py:511 (definition)
HOLDS: yes

CLAIM: only the drift detector acts on TestResult.inconclusive
RUN:   rg -n "\.inconclusive|inconclusive=" src/
FOUND: drift_detector.py:150; qualification.py:348, :366, :440, :544; behavioral_probes.py x5; communication_benchmarks.py:309, :319 (its own CommunicationScore, which then sets the TestResult flag)
HOLDS: yes

CLAIM: the /qualify displays show no inconclusive flag
RUN:   rg -n "inconclusive" src/probos/experience/commands/commands_qualification.py
FOUND: none
HOLDS: yes

CLAIM: no test pins a behavioral probe's skip result
RUN:   rg -l "behavioral_probes|FrameDiversityProbe|AnchorGroundedEmergenceProbe" tests/ ; rg -n "skipped|inconclusive" tests/test_behavioral_metrics.py
FOUND: tests/test_bf923_episodic_recall_callers.py, tests/test_behavioral_metrics.py; in the latter only :624 (anchor episodes, not a probe)
HOLDS: yes

CLAIM: A2 touches no other skip helper
RUN:   rg -n "^def _skip_result|^def _make_skip_result" src/probos/cognitive
FOUND: behavioral_probes.py:29, collective_tests.py:48, domain_tests.py:50, memory_probes.py:192
HOLDS: yes (only behavioral_probes.py:29 changes)
```

## 13. Prior Art and Blind Spots

- Bug fix; the external review was one search, on the hold's pattern. **Absorbed:** shadow mode, a new signal run on live inputs and logged but never acted on, promoted only on explicit criteria ([AWS SageMaker shadow variants](https://docs.aws.amazon.com/sagemaker/latest/dg/model-shadow-deployment.html); [Atlan, shadow deployment](https://atlan.com/know/shadow-deployment-for-ml-models/)). M2 is that: readings recorded, decisions on today's inputs, and section 18's entry names the promotion criteria. **Absorbed as a stated limit:** shadow evaluation measures what the gauge would have done, not how the crew would respond ([Qwak](https://www.qwak.com/post/shadow-deployment-vs-canary-release-of-machine-learning-models)); a later staged release is the qualifying issue's choice. `docs/research/reference-projects.md`: not consulted (ProbOS plumbing; no project there covers it).
- Internal: AD-503 (gather), AD-495 (trust-update reassessment), AD-505 (DMs), AD-566c/e (drift), AD-567g (orientation), AD-569 (metrics), AD-441/BF-138 (sovereign ids), BF-907 (trust key form), BF-921 D3.
- Blind spots addressed: the slot/sovereign id mismatch (D1); the drift detector's `__crew__` reaction to a metric leaving zero (E1); the confidence baseline that a naive capture would make live (D6); the trust-update trigger that a captured baseline would widen (D8). Considered, deferred: thread-relevant anchor episodes (R5); a batched episode count (R7).
- Amendment A1 addresses blind spots found in review and in the A1 pass:
  - the producer's thread scope (D10; the issue's premise was incomplete);
  - the VitalsMonitor medical-alert path that a critical `__crew__` drift reaches, which section 5 had missed (D11);
  - the activated cost: per-thread author reads and synchronous embeddings (D12);
  - the department lookup by slot id (R12).

  No external search: this is ProbOS plumbing with no outside analogue, and `docs/research/reference-projects.md` was not consulted for the same reason.

## 14. Diff Reviewer: properties to verify

1. No production caller passes `agent_id` or `limit` to `EpisodicMemory.recall`.
2. The anchor metric reads each author through `recent_for_agent` by the id `resolve_sovereign_id_from_slot` returns for the engine's identity registry; the booted runtime binds its `identity_registry` into the engine it holds; with no registry an author is read by its own id. A computation with failures logs exactly one WARNING naming the count.
3. Both orientation callers obtain the count from `count_agent_episodes`, which counts the sovereign id, else the slot id, through `count_for_agent`, and returns 0 with a WARNING on failure. The extracted warm-boot function differs from the removed block only in the count, the counter and the return value; its gate is unchanged.
4. The values `_gather_agent_metrics` returns are, for every input, the values the base returned in production (`trust_score` `TRUST_DEFAULT`, `hebbian_avg` 0.0, confidence, success rate and personality drift read as before). Nothing reads `trust_observations` or `observed_baseline` except the record helper, `to_dict` and `from_dict`. `assess_agent`, `profile.baseline`, every handler, `_maybe_send_therapeutic_dm`, `_alert_bridge` and the self-telemetry whitelist are unchanged.
5. A trust reading is recorded only when `get_score` returned; the first recorded reading is never overwritten; a failed read logs a WARNING and records nothing and creates no profile.
6. A profile never holds more than `COUNSELOR_PROFILE_HISTORY_LIMIT` assessments or readings, after append or after load, and keeps the latest; a profile saved before the build loads.
7. The hold test compares a Counselor with a real low trust reading against one with no trust network on two gathering paths, with only the DM sender and the Bridge alert replaced by spies, and compares the agent's own wellness view.
8. Every replaced double says inline what it used to accept and why; no test was deleted.
9. (A1) The producer lists channels with `list_channels()` and browses exactly the ids `crew_channel_ids` returns. No `dm` channel's thread is fetched. A failed list or browse logs one WARNING, raises, and records no snapshot.
10. (A1) Each resolved owner is read at most once per computation. A failed read fails each of that owner's threads without a second read, and the aggregate WARNING counts failed threads as before. The loop runs between owner reads.
11. (A1) Synthesis detection and the convergence loop run in a worker thread and touch no state but their arguments and the engine's config. Their results equal the base's for equal inputs. `_count_convergence_events` is the removed loop, unchanged.
12. (A1, A2) Every result of the five behavioral probes carries `inconclusive=True`: a measured result with the score it carried before; a skipped result (no engine, or no snapshot) with score 0.0, `error` None and `details.skipped`, held whatever `HELD_FROM_DRIFT` says, and still captured as the first baseline. With a history of zeros, a held non-zero result raises no drift signal; the same result unheld is critical (the premise). Through the real harness and store, a skipped run enters no drift statistics (sample count 0).
13. (A1) M2's files (`cognitive/counselor.py` and its three test files) are byte-identical to round 1; only section 8's tracker text changed in M2's commit.
14. (A2) Stored results for the five test names have exactly these producers: the probes' returns (five measured sites; ten skip sites through `_skip_result`), the harness's exception wrapper (held) and its timeout wrapper (unreachable: no `await` in a probe's `run`); `save_result` has no other caller. `_skip_result` in `collective_tests.py` and `domain_tests.py` and `_make_skip_result` in `memory_probes.py` are unchanged. A2 changes no M2 file and no section 8 text.

## 15. Acceptance criteria

- On a real store, the anchor metric analyses a thread whose authors' episodes exist, including when the authors are slot ids mapped by a real identity registry, and through the booted runtime's engine and store.
- On a real store, both orientation callers pass the agent's own episode count; at stasis recovery an agent with episodes is told the count.
- The Counselor reads trust with `get_score` on a real `TrustNetwork`, records it with a captured baseline, and, with a reading that would make the agent unfit, produces the same assessment, no DM, no Bridge alert and the same wellness view as a Counselor with no trust network.
- The Hebbian router is not read. A profile keeps at most 50 assessments and readings.
- (A1) Through `compute_behavioral_metrics` on a real Ward Room, a crew-channel thread is analysed and a DM thread is not fetched; a failed Ward Room read is logged at WARNING and records no snapshot.
- (A1) Each author is read once per computation; synthesis and convergence detection do not hold the event loop.
- (A1) The five Tier 3 behavioral probes keep their scores and raise no drift against a history of zeros.
- (A2) A skipped probe run (no engine, or no snapshot since boot), through the real harness and store, is stored inconclusive, enters no drift statistics and still sets the first baseline.
- The measurement entry is posted on #1523 before #1652 closes.
- Before editing, the tests that pin current behaviour were grepped, and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what is read after the first session (read-only)

From `%LOCALAPPDATA%\ProbOS\data` after the first vessel session on the merged build, record on #1652:
- (M1) After the first dream:
  - the `/behavioral-metrics` snapshot's `threads_analyzed`, `synthesis_rate`, `convergence_events`, `anchor_analyzed_threads` and `anchor_grounded_rate` (expected above 0 when qualifying crew threads exist; `frame_diversity_score` and `cross_dept_trigger_rate` expected 0, R12);
  - the count of `BF-923 (#1652): anchor analysis failed`, `BF-923 (#1652): the Ward Room read failed` and `BF-923: episode count failed` lines (expected 0);
  - the dream's duration against the previous dreams (E6).
- (M1) At the next drift check:
  - the five behavioral tests' newest rows in `qualification_results.db` (expected non-zero scores with `inconclusive` 1; a drift run before the first dream after a boot stores skipped rows, score 0 and `details` reason "No behavioral snapshot available", also with `inconclusive` 1, A2);
  - no `drift for __crew__ on` line for any of them, and no `qualification_drift` medical alert attributable to them (D11; expected 0).
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
- (A1) The added cost on a real vessel. The reviewer measured one whole fetch at about 0.67 s for 3,000 episodes. The live store size and the synthesis/convergence embedding time are not measured (about one embedding per post, plus one per author, per qualifying thread, for up to 100 threads). Section 16 reads the dream duration.
- (A1) That ONNX embedding calls from the worker thread and from the loop's thread can overlap safely. ONNX Runtime documents `InferenceSession.run` as thread-safe; this was read, not run. The worker runs one computation at a time.
- (A1) That SQLite accepts `channel_id IN ()` when a Ward Room has no crew channel. SQLite allows an empty IN list; not run here. A started Ward Room always has its default channels (`channels.py:58-127`).
- (A1) The new tests were written in a read-only consult and not run; the Builder's tests-first run is their first execution. The VitalsMonitor and Diagnostician path of D11 was traced by reading, not executed.
- (A2) The new test was written in a read-only consult and not run; it follows the round-2 reviewer's executed probe through the same harness and store, whose final assertion fails on `4bfee423` (the orchestrator's confirmation). That a `test_timeout_seconds` of 0 or below would time out every probe was read from CPython's `asyncio.wait_for`, not run. Round 2 executed D11's VitalsMonitor and Diagnostician path: an unheld critical `__crew__` report gave two `medical_alert` broadcasts on two scans.

## 18. For the register (found here, not fixed by this change)

- **R0 (post on #1523 now, unchecked; the orchestrator assigns the F-number).** "BF-923 M2 (#1652): **measure the Counselor's trust gauge before any action follows it.** BF-923 reads trust with `get_score` and records each reading on the profile (`trust_observations`, latest 50) with the first as the captured baseline (`observed_baseline`); `assess_agent` still receives `TRUST_DEFAULT`, Hebbian 0.0 and the default baseline, so no wellness change, DM, Bridge alert or wellness-view change follows a reading (BF-921 D3). Before the hold is lifted, over at least five vessel sessions, read-only from `counselor.db`: (1) per agent and per trigger, the trust drift from the captured baseline at each reading, and the wellness, concerns and fit-for-duty `assess_agent` would have produced with it; (2) how many DMs (wellness below 0.5 or unfit) and Bridge alerts (unfit) that would have added, against the AD-505 DMs actually sent; (3) the `trust_update` reassessment rate per agent (R12's churn, still on the default baseline) and the rate it would have with the captured baseline (D8). Promotion criteria, decided by the issue that lifts the hold: whether trust drift enters wellness, at what weight and threshold; whether `_on_trust_update` compares with the captured baseline; whether `observed_baseline` becomes `profile.baseline` (through `set_baseline`); the Hebbian reading (R3). Shadow measurement shows what the gauge would have done, not how the crew would respond."
- **R1.** AD-583f's observable-state verifier never reaches the behavioral metrics engine: `finalize.py:5955` reads `getattr(runtime, 'behavioral_metrics_engine', None)`, but the runtime holds `_behavioral_metrics_engine` (`runtime.py:1395`, `:3177`), so the getattr returns None and Metric 4 (convergence correctness) never verifies. Same shape as this BF (built, wired by name, inert). Fixing it makes a second metric real and changes the composite: its own slice, with this contract's consumer list (section 5a).
- **R2.** The Counselor's success-rate input reads `getattr(meta, "success_rate", 0.0)` from registry agents (`counselor.py:789-792`), which define no `success_rate` (section 12): the input is always 0.0, so `fit_for_promotion` is always False on gathered paths and the low-success concern never fires. `test_counselor_activation.py:234-238` masks it with a `MagicMock` agent. A real reading is a new gauge input: measure under the same hold as R0.
- **R3.** No per-agent Hebbian reading is defined; `_hebbian_router` stays injected and unread (D5). Choosing the relation (and its id form) belongs to R0's qualifying issue.
- **R4.** `_on_trust_update` still reassesses every trust outcome of an agent whose trust sits 0.15 or more from `TRUST_DEFAULT` (BF-921 R12). Storage is now bounded in the profile; the `assessments` table still gains a row per reassessment. R0 measures and decides it.
- **R5.** The anchor metric reads each author's ten most recent episodes, not the episodes relevant to the thread (AD-569's wording). Whether thread-relevant episodes (`recall_for_agent(owner, title, k)`) measure grounding better is a metric design question.
- **R6.** `tests/test_bf235_stale_identity_cache.py:197-225` copies the warm-boot loop inline instead of calling it; it can now call `_orient_crew_after_stasis`.
- **R7.** `count_for_agent` scans every episode's metadata (`episodic.py:4261-4280`). The proactive loop already calls it each cycle (`proactive.py:2699`); BF-923 adds one call per cycle inside the orientation window and one per crew agent at stasis recovery. If section 16 shows a slower stasis boot, a batched per-agent count is the fix.
- **R8 (review round 1, M2, P3, injected-only).** The Hebbian "not read" pins (`tests/test_bf923_counselor_assessment_inputs.py:136-146`, `tests/test_counselor_activation.py:230-240`) assert `mock_calls == []` on a `create_autospec(HebbianRouter)`. The autospec raises `AttributeError` for `get_weights_for`, the old guarded lookup would catch it, and a failed lookup never enters `mock_calls`, so reintroducing the old lookup passes both. Fix: record attribute lookups and assert `get_weights_for` is never requested.
- **R9 (review round 1, M2, P3, injected-only).** `test_trust_observations_keep_the_latest_readings` (`:178-190`) asserts length 50 and sorted timestamps, so keeping the first 50 passes. Fix: a controlled clock and the exact final 50 entries.
- **R10 (file as a new BF; the orchestrator files and numbers it).** The emergence engine has the same scope defect: `emergence_metrics.py:390` calls `browse_threads(agent_id="", channels=None, limit=50, since=since)`, so its metrics see no thread (live: `convergence_rate` 0 threads in all 319 runs). Its consumers include groupthink and fragmentation warnings that drive Counselor and Bridge actions, so the fix needs its own BF-921 D3 analysis and hold. It can reuse `crew_channel_ids`.
- **R11 (file as a new BF).** Fresh crew never enter the proactive orientation window. Their certificate is attached late (`startup/communication.py:910-921`), which sets `sovereign_id` but not `_birth_timestamp`; the non-deferred path sets it (`agent_onboarding.py:446-460`). So `proactive.py:1777-1781` computes an infinite age and skips the orientation supplement for every first-boot crew member (16 of 16 on the reviewer's fresh boot). Reviewer's design: hydrate temporal context from the certificate when it is attached (`set_temporal_context`), with a fresh-runtime caller test. Disclose that first-boot crew then see the proactive orientation supplement.
- **R12 (file as a new BF).** The dream's department lookup receives slot ids. `startup/finalize.py:5411-5413` binds `runtime.ontology.get_agent_department(aid)`, keyed by agent type (`ontology/departments.py:65-73`), but the behavioral engine passes Ward Room `author_id`s, which are slot ids (`{agent_type}_{pool}_{index}_{hash8}`, `substrate/identity.py:20`). Every lookup returns None, so frame diversity and the cross-department trigger rate stay 0; `dreaming.py:1032-1034` passes callsigns to the same lookup. Fixing it activates two more held gauges and their on-loop embeddings (move them off the loop as D12 does).
- **R13 (register; joins R7).** Each remaining whole-collection read (`recent_for_agent`, `count_for_agent`, `episodic.py:4124`, `:4268`) holds the loop for one fetch: about 0.67 s per 3,000 episodes, linear in store size. A batched or indexed per-owner read in `EpisodicMemory`, or a paged `to_thread` fetch (`_iter_collection_pages`, `episodic.py:361-409`), is the fix for every caller.
- **R14 (post on #1523, unchecked; the orchestrator assigns the F-number).** "BF-923 A1 (#1652): **qualify the five behavioral gauges before drift acts on them.** Their results are stored with real scores and `inconclusive=True` (`behavioral_probes.py` `HELD_FROM_DRIFT`), so no drift signal, Counselor assessment or medical alert follows them. Before the hold is lifted, over at least five weeks of dreams, read-only: each gauge's distribution and week-to-week variation; what a held run would have produced in drift (z, severity) and in VitalsMonitor alerts. Promotion criteria, decided by the issue that lifts the hold: whether the April zero history is reset or marked inconclusive first; whether each test's baseline, captured from a zero or skipped run (`qualification.py:444`), is re-captured from a qualified run; whether `__crew__` drift reaches VitalsMonitor at all; thresholds per gauge."
