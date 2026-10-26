# BF-925: silent-fallback guards name APIs that exist (#1655): the Insights report reads real sources or says "not available", @mention Hebbian links are recorded, the Chiefs see their subordinates' stats, the procedural bridge loses its dead branch, episode anchors count the real EventLog window (held out of scoring), and a guard test keeps the class from coming back

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25

**Status:** build-ready. One BF, two milestones, one PR, one gate; #1655 closes with it. **BF number:** BF-925 (#1655); this contract allocates nothing. **Tiers:** M1 **STANDARD** (F06, F11, F18, F13 and the guard test: Captain-facing report content, a social-graph write and a Chief's prompt context; no safety, trust or authority property); M2 **HIGH** (F12: it edits the scoring function behind every recall's anchor confidence and the AD-607 recall anomaly map, and starts writing a new value into a persisted episode field; the property it must keep, "no score or verdict moves", fails silently, so the census in section 10 carries it). Review M2 with the Copilot `Diff Reviewer`. **Base:** `72fae2dd` (BF-924 final plus BF-926+927, both by tool); after BF-926+927 merges the orchestrator re-verifies every SEARCH on the merge SHA, and a changed REPLACE returns to the Architect. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF. **No config field changes**, so no generated file changes.

**Tests:**
- New (M1): `tests/test_bf925_silent_guards.py` (13 functions, 13 cases), `tests/test_bf925_guard_names.py` (6 functions, 14 cases), `tests/fixtures/guard_name_allowlist.txt` (23 entries).
- Updated pins (M1): `tests/test_ad810_insights.py` (fakes of methods nothing defines), `tests/test_ad630_leadership_feedback.py` (sets `ward_room_service` and `agent_pool`, which no runtime has).
- New (M2): `tests/test_bf925_event_log_window.py` (10 functions, 11 cases).
- Updated pins (M2): `tests/test_orientation.py` (a MagicMock's `recent`), `tests/test_ad567c_anchor_quality.py` (two scores from a fixture window no producer stores), `tests/test_ad567b_anchor_recall.py` (three, same reason).

**Amendment A1 (2026-10-25, `claude-architect`, on the orchestrator's controls over the M2 oracle `a8148c5e`):** the M2 focused check found one pin that section 5 called unchanged. `test_ad567b_anchor_recall.py::TestConfigWeights::test_custom_weights_affect_score` (`:452`) expects a fully filled anchor to score 1.0 under custom weights (anchor weight 0.10) at a 1e-9 tolerance. With the window held out, the anchor scores 0.95 and the composite moves by 0.005 (0.865 against 0.870). A1 adds pair 3 to §7.16 and updates the header, §5's Tests row, §6's M2 tests-first count (14 → 15), §10 M2-13's kill list, §11, §12 (a census of every test fixture that sets a window) and §17. No source line changes, and no REPLACE in §7.1 to §7.15 or §7.17.

## 0. Premise: what is present on this tree

| Claim of #1655 (anchors on `7808d182`) | On `72fae2dd` | Holds |
|---|---|---|
| F06 guards `insights.py:226,234,248-249,257-258,283` | same lines; **found here:** a sixth, `self_mod_pipeline.pending_proposals()` (`:267-269`): `SelfModificationPipeline` defines no `pending_proposals` (section 12; the name is a *list attribute* of `ChainOptimizer`, `chain_optimizer.py:246`) | yes, and one more |
| F06 consumers `commands_insights.py:34`, `routers/insights.py:21` | same; no `ui/` reader (section 12) | yes |
| F11 `messages.py:440-442` guards `_resolve_callsign_to_id` | same; measured on a real `WardRoomService`: a post "@Bones ..." records the reply link (0.05) and no mention link (0.0) | yes |
| F12 `proactive.py:1424`, `:1684` call `rt.event_log.recent`; `EventLog` has no `recent` | same | yes |
| F12 effect "every proactive episode scores lower" | **does not hold.** No stored episode ever carries this anchor: the no-response episode (`:1405-1429`) is discarded by `EpisodicMemory.should_store` (`episodic.py:1937-1939`); the thought episode (`:1619-1695`) is stored only when no Ward Room runs (`:1622-1623`), and the loop does not run without one (`_run_cycle`, `:1006-1007`; `_post_to_ward_room` dereferences it first, `:1502`, `:2951`). What does hold: the window reads 0.0 on **every** episode (no producer sets it, section 12), so every episode's evidential dimension is at most 1/2 | partly (D5) |
| F12 `anchor_quality.py:44`, `memory_security.py:135` | `:44`; `memory_security.py:136` (post-BF-926 text) | yes |
| F13 `episodic_procedural_bridge.py:79-88` calls `list_all` | same; **measured** through a real `ProcedureStore`: `hasattr(store, "list_all")` False, the `list_active`+`get` fallback loads the saved procedure, a covered cluster is merged, not bridged | premise of the defect does not reproduce (as the Captain found) |
| **Found here (F13):** the merge is never persisted | `_merge_cross_cycle` (`:72-77`) mutates a loaded copy; `scan_for_procedures` returns only new procedures and `dreaming.py:1223-1235` saves only those; measured: provenance and `success_count` unchanged in the store after a merge | register R2 |
| F18 `proactive.py:2377-2381` guards `rt.ward_room_service`, `rt.agent_pool` | `:2371-2383`; **found here:** it also reads the subordinate's `sovereign_id` first (`:2377`), and posts are keyed by `agent.id` (the 14 Ward Room writes that name an author pass `author_id=agent.id` or `self.id`, section 11); measured: `get_agent_comm_stats` by agent id 1 post, by another id 0 | yes, and the id form (D4) |

## 1. Problem

- **F06.** Every Insights section is guarded on a method no production class defines, so `/insights` and `GET /api/insights` always read "No activity recorded".
- **F11.** @mentions never reach the Hebbian social graph.
- **F12.** `event_log_window` is 0.0 on every anchor; the scorer counts it as an evidential field that can never be filled.
- **F13.** A branch for a method no store has; harmless, but it hid that the fallback was the only path.
- **F18.** No Chief has ever seen subordinate communication stats.

## 2. Solution overview

- **M1.** Insights: three sections read real stores (Bridge alerts, the Captain's capability and skill request queues, completed persistent tasks); topics and crew are reported "not available" with a reason; a source that is down or fails is reported "not available" in its own section. Ward Room mentions resolve through the `CallsignRegistry` the dispatcher already binds (it reads the live `AgentRegistry`) and record one social reinforcement per mentioned agent per post. The Chiefs' stats read `runtime.ward_room` and `runtime.registry`, by `agent.id`. The bridge drops its `list_all` branch. A guard test (AST, no imports) fails on a production `hasattr`/`getattr`-with-default guard whose name no production code defines, against a 23-entry allow-list.
- **M2.** `EventLog.count_since(since, *, cap=1000)`; both proactive anchor sites read the 60 s window through one helper; `anchor_quality` holds the window out (it counts as unfilled, exactly as 0.0 did); `memory_security` drops the window from its mismatch map. A measurement row goes on #1523.

## 3. Decisions (for #1655)

**D1, F06 per section** (sources enumerated by grep, section 11; cost per `/insights` call or API request, on demand only).

| Section | Candidates (owner, call, cost) | Chosen | Reason |
|---|---|---|---|
| Top topics | `EpisodicMemory`: no recall-frequency record (`cluster_recall_counts`: 0 definitions); `WorkspaceOntologyRegistry.top_terms(k)` (`workspace_ontology.py:61`): manually registered terms, not window-scoped, not on the runtime | **drop**: "not available (no store records recall frequency by topic)" | no source answers "topics recalled in the window"; a term register is a different measure (R7) |
| Top crew | AD-810 says "DM/session message volume"; `ChatThreadStore.list_threads` (`threads/__init__.py:329`) has no per-crew message count; `WardRoomService.get_agent_comm_stats` (`service.py:358`) counts Ward Room posts, not DMs/sessions, and has no last-active time | **drop**: "not available (no store counts DM or session messages per crew member)" | wiring Ward Room posts would relabel a different measure; design (R7) |
| Scheduled tasks completed | `TaskScheduler` (`task_scheduler.py:22-84`): monotonic times, no completion time, in-session only; `PersistentTaskStore.list_tasks(status, limit)` (`persistent_tasks.py:262`), `last_run_at` wall-clock (`:47`), one SQLite read | **wire** `runtime.persistent_task_store.list_tasks(status="completed", limit=200)`, kept when `last_run_at >= since` | the only store with completion times; a task completes on its final run (`:536-567`); recurring runs that leave it pending are not counted (disclosed) |
| Pending decisions | `CapabilityRequestStore.list_pending()` (`capability_request.py:1142`, cache read), `SkillRequestStore.list_pending()` (`skill_request.py:356`, cache read), both the Captain's approval queues; others (`permission_card.py:93`, `delegated_approvals.py:396`, `approval_gate.py:62`, `chain_optimizer.py:318`, pairing) | **wire** the capability and skill queues, oldest first, at most 20 each, `source` `capability_request` / `skill_request` | the two queues AD-853/AD-907 built for Captain decisions; adding every approval-like queue is scope (R7) |
| Anomaly windows | `BridgeAlertService.get_recent_alerts(limit)` (`bridge_alerts.py:837`): in-memory, newest 200 since boot (`:83-84`, `:111-113`), `timestamp` wall-clock, `severity` info/advisory/alert (`:24-28`) | **wire**, alerts with `timestamp >= since`, newest first, at most 20; severity `alert`→`critical`, `advisory`→`warning`, `info`→`info` | the ship's alert record; a window reaching before boot shows this session's alerts (disclosed) |

Ranked for the section set: (1, chosen) wire three, drop two, each with its reason in the report; (2) drop all five: the report would say nothing although three real sources exist; (3) wire Ward Room post counts as "crew": a different measure under AD-810's label.

**D2, F06 report shape and isolation.** `InsightsReport` gains `unavailable: dict[str, str]` (section → reason: the two no-source reasons, `service not running`, `failed (<ExceptionType>)`). `to_json` keeps every key (`top_topics`, `top_crew` stay, always `[]`) and adds `unavailable`; `to_markdown` drops the topics and crew renderings, and adds one `_Not available: …_` line (after "No activity recorded" when empty); the fast-tier summary drops the topics and crew lines. One section failing logs a WARNING and marks that section only. Ranked: (1, chosen) additive key: no consumer breaks (the API's only readers are tests; no `ui/` reader); (2) remove `top_topics`/`top_crew` from JSON: a shape migration for no gain; (3) `None` sections: changes types readers iterate.

| Consumer | Today | After |
|---|---|---|
| `/insights` (`commands_insights.py:32-40`, prints `to_markdown`) | "No activity recorded" always | the three wired sections when they have rows; one "Not available: …" line naming topics and crew and any section down or failing |
| `GET /api/insights` (`routers/insights.py:15-25`, returns `to_json`) | all lists `[]` | same keys plus `unavailable`; `top_topics`/`top_crew` `[]` |
| `ui/` | no reader (section 12) | none |
| AD-810 narrative (`insights.py:211-219`, `_summarize`) | never ran (report always empty) | **E1b:** one fast-tier call (≤1024 tokens) per `/insights` or API call when a wired section has rows |
| `tests/test_ad810_insights.py` | fakes of `cluster_recall_counts` / `recent_threads_by_crew` | fakes by the real names, pinned to the real classes (§7.2, §7.7) |
| Docs `docs/getting-started/shell.md:53` | generic | unchanged |

**D3, F11 resolver, link and bound.** Ranked: (1, chosen) `self._callsign_registry.resolve(callsign)`: the resolver the same method already uses for the mention's TaskEvent (`messages.py:255-259`), bound by `attach_dispatcher` (`startup/finalize.py:5590`, `runtime.callsign_registry`), and itself an `AgentRegistry` resolution (`crew_profile.py:726-731`: the first live agent of the callsign's type, case-insensitive); one id per mention for both the TaskEvent and the link; (2) BF-921's resolver, `CounselorAgent._resolve_agent_id_from_callsign` (`counselor.py:1583-1601`, 4 callers, scans `AgentRegistry.all()` for `agent.callsign ==`): private to the Counselor, case-sensitive, and would need an `AgentRegistry` injected into `MessageStore` as a second resolver that can disagree with the TaskEvent's; (3) promote BF-921's scan to `AgentRegistry`: touches `counselor.py`, in BF-924's review (R10). The issue's "the AgentRegistry resolution BF-921 introduced" is met in substance: resolution goes through the live `AgentRegistry`. **Link:** `record_interaction(source=author_id, target=<agent.id>, success=True, rel_type=REL_SOCIAL)`, the AD-453 reply link's call; ids are `agent.id` on both sides, as the reply link's (`create_post` callers pass `author_id=agent.id`). **Bound (E2):** at most one reinforcement per (author, mentioned agent) per post (repeated mentions count once; the thread author already has this post's reply link); weight `w·0.995 + 0.05`, clamped to 1.0 (`routing.py:177-213`; `config/system.yaml:14-17`); no link for a self-mention, an unknown callsign or an agent that is not alive; none when no dispatcher is attached (then no TaskEvent either).

| Reader of social weights | Effect |
|---|---|
| Cross-agent recall escalation: `cognitive_agent.py:12065-12072` (peers ranked by `get_weight(self.id, a.id, REL_SOCIAL)`, a peer asked only when > 0), `cross_agent_recall.py:141-143` | **E3:** a peer an agent mentions can become its most-associated peer, so whom it asks can change |
| `emergent_detector.py:490`, `:1124`; `emergence_metrics.py:605`; `working_memory.py:289`; `drift_detector.py:216` | more social edges in clusters, entropy and drift inputs |
| Displays: `routers/agents.py:264`, `agents/introspect.py:567`, `:645`, `commands_introspection.py:20`, `experience/panels.py:393` | show the edges |
| Persistence and dream: `runtime.py:2390`, `:2433`; `dream_adapter.py:326`; `startup/shutdown.py:2025`; `hebbian_weights.db` (`runtime.py:712`) | stored and decayed as reply links are |
| Untyped `get_weight(s, t)` (`routing.py:212`, `:257-259`; `proactive.py:4952`; `builder.py:1250-1253`) | the pair's last-written weight, as for reply and DM links today |
| `HEBBIAN_UPDATE` (`messages.py:448-453`, when `format_trust_fn` is set) | one event per new mention link |

**D4, F18 attributes and id.** `rt.ward_room` (`runtime.py:1091`, set `:3266`) and `rt.registry` (`runtime.py:684`); the subordinate is the first live agent whose `agent_type` matches (`registry.all()`, `substrate/registry.py:71`; `BaseAgent.is_alive`, `substrate/agent.py:108`); stats are read by `agent.id`, the id posts and credibility carry. Ranked: (1, chosen) as stated; (2) keep the sovereign id: measured 0 posts, so the section stays empty; (3) `CallsignRegistry.resolve`: the code has the type, not a callsign. **E4:** the agents filling posts with direct reports (`config/ontology/organization.yaml`: `first_officer` `:39` (5), `chief_engineer` `:109` (2), `chief_science` `:153` (4), `chief_medical` `:259` (3)) get a `<subordinate_activity>` block, one line per subordinate with at least 3 posts since boot (≤5 lines, ~100 characters each), in the one-shot proactive prompt (`cognitive_agent.py:11108-11120`) and the chain's situation sensorium (`:1265-1270`, `:9557-9571`, read by `sub_tasks/analyze.py:293`, `compose.py:558`). Cost: ≤5 × 4 SQLite reads per Chief per proactive gather.

**D5, F12.** (a) **Source.** Ranked: (1, chosen) new `EventLog.count_since(since, *, cap=1000)`: one `COUNT(*)` over the newest `cap` rows by primary key; no row transfer; (2) `query(limit=1000)` and a client-side filter (`event_log.py:820`): transfers and JSON-decodes up to 1000 rows per think; (3) `query_governed` (`:915`): the audited agent-tool read, with redaction and a 200-row cap (`:30`); using it for an internal count blurs that surface; (4) `count(category)` (`:1176`): no time filter. `EventLog` is the only production implementation (section 12); `EventLogProtocol` (`protocols.py:188-205`) declares `log`/`start`/`stop` only and is not extended; no test double needs `count_since`: the helper turns any failure into 0.0 (the value every anchor had) with a WARNING the first time per loop. (b) **Hold.** `_compute_dimension_scores` counts the window as an unfilled field (a constant 0.0 in its place), so every score equals the score that field gave at 0.0; `memory_security._ATTR_DIMENSION` drops `event_log_window`. Ranked: (1, chosen) unfilled placeholder: every live score unchanged by construction; (2) remove it from the evidential list (one field of one): raises every episode with a `thread_id` from 0.5 to 1.0 evidential, +0.05 confidence ship-wide; (3) score the real value: the measurement has not happened. Readers: section 5. (c) **Fill**, as the Captain decided: both sites call one helper. Disclosed (E5): on the shipped configuration neither site's episode reaches storage (section 0), so the stored value stays 0.0; the measurement row is written so that this is its first finding. Ranked: (1, chosen) fill both sites (the Captain's decision; one bounded count per no-response think; the stored shape is unchanged); (2) remove the guarded expressions (the issue's alternative, "or the field is dropped"): contrary to the Captain's "fill the real value"; (3) also fill the Ward Room thread and post episodes, where a proactive post's episode is made: a new producer for most episodes and an `EventLog` injection into `WardRoomService`; widens the issue, so it is the measurement's decision (R5). Not a Captain condition: no control is weakened (no score or verdict moves), nothing is widened. **Why HIGH:** the hold edits the confidence scorer behind recall ranking (`episodic.py:4754`, weight 0.15), the anchor-confidence gate and social verification (`social_verification.py:337`, `:529`), and the AD-607 mismatch map; a wrong placeholder or a dropped field moves every score silently. Rows M2-11 to M2-13 and the identical-score tests carry it.

**D6, the guard test.** *Guard:* `hasattr(obj, "name")`, or `getattr(obj, "name", default)` with three arguments, the name a string literal, inside a function, whose receiver's root (through attributes, subscripts and nested `getattr`) is `self`, `cls`, `rt` or `runtime`, or a local name assigned in an enclosing function from such an expression (`x = self._store`, `x = getattr(self._runtime, "y", None)`, `x = a or b` by its first operand, to a fixed point). Two-argument `getattr` (raises), `callable(getattr(...))` without a default, `try/except AttributeError`, dunder names and module-level guards are out. *Defined:* a `def`/`async def` or class name; a module- or class-level assignment target (class attributes, dataclass and pydantic fields, enum members); any attribute assignment target anywhere (`self.x =`, `runtime.x =`); a `__slots__` string; a `setattr(obj, "x", …)` literal; a module-level import name; an argparse `dest=` or first long option. Production = `src/probos/**/*.py` of this checkout; AST only; deterministic (sorted walk, sets); about 9 s for 1,067 files. *Allow-list:* `tests/fixtures/guard_name_allowlist.txt`, `path | name | kind | reason`, kind `duck` (third-party, optional by design) or `finding` (registered on #1523, untriaged); keyed by (path, name), so line moves do not matter. The test fails on a hit not listed and on an entry that is no longer a hit (its name is now defined, or no longer guarded in that file). *Measured* (section 12, scratch probes): name-only, every receiver: 109 hits (argparse namespaces, `os`, exceptions, Playwright pages): not reviewable. Receiver-scoped (chosen): 39 hits, 36 (path, name) pairs: the 13 of the five items plus 23 others, 7 `duck` and 16 `finding`. Ranked: (1, chosen) receiver-scoped; (2) name-only, about 95 allow-list hits; (3) name-only plus statically excluded receivers (non-`probos` module roots, `except`-bound names): 72 hits, 65 pairs, 52 entries. *Gives up / cannot see:* a guard on a parameter or a local not derived from those roots; a name an unrelated production class happens to define (**F12's `recent` is defined by 5 other classes, and `pending_proposals` by `ChainOptimizer`: neither would have been caught**); dynamic names; `__getattr__`; third-party attributes on owned receivers (allow-listed). Both blind spots are R9.

**D7, F13.** The `list_all` branch never ran (no procedure store defines it; `inspect.isawaitable` dances served it); it fed `existing` and nothing else. Removed with the `hasattr` checks on `list_active`/`get` (the bridge is built only with the runtime's `ProcedureStore` or None, `startup/dreaming.py:115-121`) and the `inspect` import. Behaviour is unchanged (premise measured). The merge it feeds is never saved: R2, not fixed (dream-time writes to stored procedures are design).

**D8, milestones.** M1 (STANDARD) §7.1 to §7.9; M2 (HIGH) §7.10 to §7.17. Each M2 pair applies on the M1 tree (M2's `proactive.py` pairs are at the anchor sites and before `_gather_context`; M1's is inside it). The guard test passes at both stages: M2 adds no guard and defines no allow-listed name.

## 4. Interaction with the queue

- **BF-924** (in review) may still change `cognitive_agent.py`, `counselor.py`, `procedure_store.py`, `trust.py`, `commands_clearance.py`, `config_models/emergence.py`: no pair here is in them. Three allow-list entries are in two of them (`cognitive_agent.py` `_callsign`, `get_by_intent`; `counselor.py` `model_dump`): if a BF-924 repair moves those guards, the guard test names the entry on the merge SHA; the orchestrator runs it there, and a changed entry returns to the Architect.
- **BF-926+927** changed `memory_security.py`; §7.13 anchors on this tree's `score_anchor_mismatch` (`:134-137`), which BF-926+927 did not touch (`enforce_leak_guard` is a config field, `config_models/crew.py:122`).
- **#1658, #1659:** paused; nothing here.
- **Tracker anchors:** `PROGRESS.md`'s title line; `DECISIONS.md`'s `### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)` (line 739, once).
- **PR text, BF-925's part:** "BF-925 (#1655). Guards on methods nothing defines made features silently empty. The Insights report now shows Bridge alerts, the Captain's pending capability and skill requests and completed scheduled tasks, and says which sections have no source (topics, crew) or whose source is down. Ward Room @mentions now strengthen the Hebbian social link to the mentioned agent, once per post. Department Chiefs now see their subordinates' Ward Room activity (it read attributes no runtime has, and the wrong id). The AD-572 bridge loses a branch that could never run. Episode anchors count the EventLog's last 60 s, held out of anchor-confidence and memory-security scoring until measured (#1523); no score or verdict changes. A new test fails when a production `hasattr`/`getattr` guard names an attribute no production code defines."

## 5. Consumers of every value this changes (F12)

States of the window read: *measured* (an int ≤ 1000); *failed* (the runtime has no `event_log`, the log is not started → 0 by design, or the query raises) → 0.0, WARNING once per loop then DEBUG; *timed out* does not occur (one local SQLite read).

| Reader of `event_log_window` | Outcome |
|---|---|
| `anchor_quality._compute_dimension_scores` (`:39-51`) → `compute_anchor_confidence` (`:54-80`) → recall `score_recall` (`episodic.py:4754`), the confidence gate, `social_verification.py:337`, `:529`; `build_anchor_profile` (`:103-172`, no production caller) | unchanged: the window counts as unfilled, as 0.0 did on every stored episode |
| `memory_security.score_anchor_mismatch` (`:93-163`) via `validate_recall_result` (`:166-204`), `EpisodicMemory._security_anomaly_drop` (`episodic.py:1520-1549`) | unchanged in production: the only production query, `_AnchorQueryView` (`episodic.py:333-352`, built at `:5028`, `:5251`), has no `event_log_window`; after the change no query can make it count |
| Persisted shape: `anchors_json` (`episodic.py:4364`), loaders `:4502`, `:923`; `knowledge/store.py:178`; `knowledge/erasure.py:57` | shape unchanged; a stored 0.0 and a missing key both load as 0.0 (pinned) |
| Proactive anchor sites (`proactive.py:1418-1425`, `:1678-1689`) | the real count; neither episode is stored on a running loop (section 0), E5 |
| UI, export, API | no reader (section 12) |
| Tests | `test_orientation.py:289-301` (mock `recent`), `test_ad567c_anchor_quality.py:84-89`, `:228-244`, `test_ad567b_anchor_recall.py:93-111`, `:158-164`, `:451-453` (custom weights, anchor weight 0.10: a 0.005 shift at a 1e-9 tolerance, A1): fixtures set a window no producer stores; updated (§7.14 to §7.16). Others with a fixture window (`test_ad567d_*:54`, `test_ad584c_*:50`, `test_ad590_*:52`, `test_ad591_*:51`, `test_ad567c_*:329`) assert orderings, tolerances ≥ 0.01 or floors with a margin above the composite shift (0.15 × 0.05 = 0.0075 at default weights): unchanged, measured by the M2 focused check on the oracle (2026-10-25); `test_ad567a_*:41` and `test_ad577_*:50` only construct a frame (§12) |

**Disclosed effects.** **E1** (F06) the report content in D2's table; **E1b** the narrative LLM call; **E2** mention links; **E3** recall peer choice; **E4** Chiefs' context; **E5** (F12) one bounded count per proactive no-response think, nothing stored on the shipped configuration, no score moves; **E6** (F13) none.

## 6. Milestones and tests

**M1 (STANDARD), §7.1 to §7.9.** First heading: `### 7.1 \`src/probos/cognitive/insights.py\` (M1, F06)`. Commit "BF-925 M1: the Insights report, @mention links, Chiefs' stats and the procedural bridge read APIs that exist (part of #1655)", body ending "Each guard named a method no production class defines. Insights reads Bridge alerts, the capability and skill request queues and completed persistent tasks, and reports topics and crew as not available; mentions resolve through the CallsignRegistry and reinforce one social link per mentioned agent per post; Chiefs read runtime.ward_room and runtime.registry by agent.id; the bridge drops its list_all branch. A guard test pins the class."

Before editing, grep the pins: `grep -rn "ward_room_service\|agent_pool\|cluster_recall_counts\|recent_threads_by_crew\|_resolve_callsign_to_id\|list_all\|subordinate_stats" tests/`. `test_proactive.py:150` and `test_ad635f_clinical_proactive_context.py:40-41` set the dead attributes on MagicMock runtimes whose ontology names no subordinate; left (R11).

**Named doubles (M1).** `_FakeAlerts`, `_FakeRequests` (`test_ad810`): stand for the stores by their real method names, pinned to the real signatures (§7.7 `test_the_insights_doubles_match_the_real_classes`); the alert and request objects are the real dataclasses. `_AcceptingDispatcher`: masks only the mention TaskEvent's delivery (unchanged). F18's runtime is a MagicMock for the context sources F18 does not touch, with the real `WardRoomService` and `AgentRegistry` set; a MagicMock would invent any attribute name, so `test_the_attributes_these_paths_read_exist_on_the_runtime` pins the names on a real `ProbOSRuntime`. Crew are `SimpleNamespace`s with the attributes `AgentRegistry.register` and `CallsignRegistry.resolve` read. Every store is real (tmp-path SQLite); the task store's tick loop sleeps an hour and the test runs its tick body (`_execute_due_tasks`), as `test_bf877_unapproved_design_is_refused.py:637` does.

Tests first: with §7.2, §7.5, §7.7 to §7.9 applied and §7.1, §7.3, §7.4, §7.6 not, exactly 13 cases fail:
- `test_bf925_silent_guards.py` (7): `test_the_report_reads_alerts_requests_and_completed_tasks` (`[] == [('critical', 'trust_network')]`), `test_a_source_that_is_not_running_reports_not_available`, `test_the_report_json_keeps_its_keys_and_adds_unavailable` (`AttributeError: 'InsightsReport' object has no attribute 'unavailable'` / the key set), `test_alerts_outside_the_window_are_left_out` (`[] == [...]`), `test_a_mention_records_a_social_link_to_the_mentioned_agent` and `test_one_post_reinforces_each_mentioned_agent_once` (`0.0 == approx(0.05)` for `bones-1`), `test_a_chief_sees_a_subordinates_ward_room_stats` (`KeyError: 'subordinate_stats'`);
- `test_bf925_guard_names.py::test_production_guards_name_attributes_production_code_defines` (the 13 pairs of section 12, listed as new);
- `test_ad810_insights.py` (4): the happy path (`[] == [...]`), the empty state ("Not available" missing), the failing source (`AttributeError ... 'unavailable'`), the narrative (`'' == 'Operator activity was steady this week.'`);
- `test_ad630_leadership_feedback.py::TestChiefContextInjection::test_chief_gets_subordinate_stats`.

Pass on both sides: the F11 negative case, the F18 not-alive case and runtime-attribute pin, both F13 cases (the premise), the doubles pin, the five scanner self-tests, `test_parse_days_*`, `test_api_endpoint_returns_json_shape`, the other `test_ad630` cases. Another failure, or an exception before the asserted line, is a hard stop for the Architect. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf925_silent_guards.py tests/test_bf925_guard_names.py tests/test_ad810_insights.py tests/test_ad630_leadership_feedback.py tests/test_ad635f_clinical_proactive_context.py tests/test_proactive.py tests/test_ad572_procedural_bridge.py tests/test_hebbian_social.py tests/test_ward_room.py tests/test_bf467_directed_mention.py tests/test_ad1036_exogenous_mention.py tests/test_bf157_mention_response.py tests/test_procedure_store.py -n 0 -q
```

(The orchestrator computes the collected and passing counts by tool; the new files add 27 cases.)

**M2 (HIGH), §7.10 to §7.17.** First heading: `### 7.10 \`src/probos/substrate/event_log.py\` (M2, F12)`. Commit "BF-925 M2: episode anchors count the EventLog window, held out of scoring (part of #1655)", body ending "EventLog never had recent, so every anchor's event_log_window was 0.0. EventLog.count_since counts the newest rows in a window; both proactive anchor sites read the last 60 s through one helper. Anchor confidence counts the window as unfilled and memory security no longer maps it, so no score or verdict moves until it is measured (#1523)." The tracker entries (section 8) go in this commit.

Before editing, grep the pins: `grep -rn "event_log_window\|\.recent(\|compute_anchor_confidence\|score_anchor_mismatch" tests/`.

**Named doubles (M2).** `_Episodes` records `store` (and answers `count_for_agent`); `EpisodicMemory.should_store` is opened in the site test because it discards no-response episodes, which is why production never stores this anchor (said inline). `_BrokenLog` stands for a failing `EventLog` with the real `count_since` signature. `_write_at` writes a backdated row directly (`log()` stamps the current time). The runtime is a `SimpleNamespace`, as `test_ad1228_standing_interests.py:1320-1328` uses for `_think_for_agent`.

Tests first: with §7.14 to §7.17 applied and §7.10 to §7.13 not, exactly 15 cases fail:
- the new file's 9: the three `count_since` tests and `test_a_failed_window_read_records_zero_and_warns_once` (`AttributeError`: no `count_since` / no `_event_log_window`), `test_a_proactive_episode_anchor_records_the_window` (`[0.0] == [2.0]`), `test_both_proactive_anchor_sites_read_the_window_through_the_helper` (the two `float(len(...))` expressions), `test_the_confidence_is_the_same_with_a_zero_and_a_real_window[with-thread]` (`1.0 == 0.95`) and `[without-thread]` (`0.95 == 0.9`), `test_the_memory_security_verdict_is_the_same_with_a_zero_and_a_real_window` (`[(0.1, False), (0.0, True)]`);
- the pins' 6: `test_orientation.py::...::test_event_log_window_populated` (`AttributeError: ... 'count_since'`), `test_ad567c_*::TestAnchorConfidenceScoring::test_all_fields_filled` (`abs(1.0 - 0.95) < 1e-9`), `test_ad567c_*::TestAnchorProfiles::test_mean_median_confidence`, `test_ad567b_*::TestRecallScoreComputation::test_composite_score_formula`, `test_ad567b_*::TestAnchorCompleteness::test_all_filled`, `test_ad567b_*::TestConfigWeights::test_custom_weights_affect_score` (`abs(0.870 - 0.865) < 1e-9`, A1).

Pass on both sides: `test_holding_out_keeps_every_score_as_before` and `test_an_episode_stored_with_or_without_a_window_loads` (premises). Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf925_event_log_window.py tests/test_bf925_guard_names.py tests/test_event_log.py tests/test_bf873_event_log_chain_concurrency.py tests/test_orientation.py tests/test_ad567a_anchor_metadata.py tests/test_ad567b_anchor_recall.py tests/test_ad567c_anchor_quality.py tests/test_ad567d_dream_provenance.py tests/test_ad577_temporal_sequence.py tests/test_ad584c_scoring_rebalance.py tests/test_ad590_composite_score_floor.py tests/test_ad591_quality_aware_budget.py tests/test_ad607_memory_security.py tests/test_proactive.py tests/test_ad1228_standing_interests.py -n 0 -q
```

(The new file adds 11 cases; the orchestrator computes the counts.) Run every focused check, tests-first run and mutation row with `PYTHONPATH` set to the scratch tree's `src` (BF-924 section 17: the venv's editable install points at `D:\ProbOS\src`). **The broad gate is run once for #1655 by the main session, not by the Builder.**

## 7. The contract

### 7.1 `src/probos/cognitive/insights.py` (M1, F06)

Pair 1 (module docstring):

SEARCH:
````python
"""AD-810: operator-facing recent-activity summary.

Pure aggregation service. Reads from existing stores (journal, dream
scheduler, thread namer, vision telemetry). No new persistence.
"""
````
REPLACE:
````python
"""AD-810: operator-facing recent-activity summary.

Pure aggregation service. No new persistence. BF-925 (#1655): every section
named a method no production class defines, so the report was always empty.
Three sections read real sources (Bridge alerts, the Captain's capability and
skill request queues, completed persistent tasks); topics and crew have no
source, and the report says "not available" for them.
"""
````

Pair 2 (module constants):

SEARCH:
````python
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicCount:
````
REPLACE:
````python
logger = logging.getLogger(__name__)

# BF-925 (#1655): the sections with no source. Each named a method no production class defines
# (an episodic ``cluster_recall_counts``; a runtime ``thread_store`` with ``recent_threads_by_crew``).
_NO_SOURCE: dict[str, str] = {
    "top_topics": "no store records recall frequency by topic",
    "top_crew": "no store counts DM or session messages per crew member",
}
_SECTION_LABELS: dict[str, str] = {
    "top_topics": "top topics",
    "top_crew": "top crew interactions",
    "scheduled_tasks_completed": "scheduled tasks",
    "pending_decisions": "pending decisions",
    "anomaly_windows": "anomaly windows",
}
_SEVERITY: dict[str, str] = {"info": "info", "advisory": "warning", "alert": "critical"}  # AlertSeverity values
_MAX_COMPLETED_TASKS = 200
_MAX_PER_QUEUE = 20
_ALERT_LOG_READ = 200  # BridgeAlertService keeps its newest 200 alerts
_MAX_ANOMALIES = 20


@dataclass(frozen=True)
class TopicCount:
````

Pair 3 (the `source` values):

SEARCH:
````python
    source: str  # "consensus" | "self_mod" | "qualification" | "gap"
````
REPLACE:
````python
    source: str  # "capability_request" | "skill_request" (BF-925)
````

Pair 4 (the report: `unavailable`, Markdown):

SEARCH:
````python
    top_topics: list[TopicCount] = field(default_factory=list)
    top_crew: list[CrewInteraction] = field(default_factory=list)
    scheduled_tasks_completed: list[ScheduledTask] = field(default_factory=list)
    pending_decisions: list[PendingDecision] = field(default_factory=list)
    anomaly_windows: list[AnomalyWindow] = field(default_factory=list)
    narrative_summary: str = ""  # Fast-tier LLM rendering; empty on honest-degrade.
````
REPLACE:
````python
    top_topics: list[TopicCount] = field(default_factory=list)  # BF-925: no source; always empty
    top_crew: list[CrewInteraction] = field(default_factory=list)  # BF-925: no source; always empty
    scheduled_tasks_completed: list[ScheduledTask] = field(default_factory=list)
    pending_decisions: list[PendingDecision] = field(default_factory=list)
    anomaly_windows: list[AnomalyWindow] = field(default_factory=list)
    narrative_summary: str = ""  # Fast-tier LLM rendering; empty on honest-degrade.
    # BF-925 (#1655): section name -> why it is not available (no source, not running, failed).
    unavailable: dict[str, str] = field(default_factory=dict)
````

Pair 5:

SEARCH:
````python
    def to_markdown(self) -> str:
        """Render as channel-agnostic Markdown."""
        if self.is_empty():
            return f"## Insights — last {self.window_days} day(s)\n\n_No activity recorded in this window._\n"

        lines: list[str] = [f"## Insights — last {self.window_days} day(s)\n"]

        if self.narrative_summary:
            lines.append(self.narrative_summary)
            lines.append("")

        if self.top_topics:
            lines.append("**Top topics**")
            for t in self.top_topics:
                lines.append(f"- {t.label} ({t.count} recalls)")
            lines.append("")

        if self.top_crew:
            lines.append("**Top crew interactions**")
            for c in self.top_crew:
                lines.append(f"- {c.callsign}: {c.message_count} message(s)")
            lines.append("")

        if self.scheduled_tasks_completed:
````
REPLACE:
````python
    def _not_available_line(self) -> str:
        """BF-925 (#1655): one line naming each section that is not available, with its reason."""
        if not self.unavailable:
            return ""
        parts = "; ".join(f"{_SECTION_LABELS[name]} ({reason})" for name, reason in self.unavailable.items())
        return f"_Not available: {parts}._\n"

    def to_markdown(self) -> str:
        """Render as channel-agnostic Markdown."""
        if self.is_empty():
            empty = f"## Insights — last {self.window_days} day(s)\n\n_No activity recorded in this window._\n"
            not_available = self._not_available_line()
            return empty + ("\n" + not_available if not_available else "")

        lines: list[str] = [f"## Insights — last {self.window_days} day(s)\n"]

        if self.narrative_summary:
            lines.append(self.narrative_summary)
            lines.append("")

        if self.scheduled_tasks_completed:
````

Pair 6:

SEARCH:
````python
        if self.anomaly_windows:
            lines.append("**Anomaly windows**")
            for a in self.anomaly_windows:
                lines.append(f"- [{a.severity}] {a.label}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
````
REPLACE:
````python
        if self.anomaly_windows:
            lines.append("**Anomaly windows**")
            for a in self.anomaly_windows:
                lines.append(f"- [{a.severity}] {a.label}")
            lines.append("")

        if self.unavailable:
            lines.append(self._not_available_line())

        return "\n".join(lines).rstrip() + "\n"
````

Pair 7 (JSON):

SEARCH:
````python
            "narrative_summary": self.narrative_summary,
        }
````
REPLACE:
````python
            "narrative_summary": self.narrative_summary,
            "unavailable": dict(self.unavailable),  # BF-925 (#1655): additive; every other key is unchanged
        }
````

Pair 8 (the service's docstring):

SEARCH:
````python
    Pure read-side; uses ``hasattr`` guards on every source so missing
    upstream APIs honest-degrade to an empty section rather than blank
    the whole report.
    """
````
REPLACE:
````python
    Pure read-side. BF-925 (#1655): the ``hasattr`` guards this used named
    methods nothing defines, so every section was silently empty. Sources are
    read directly; one that is down or fails is reported as not available in
    its own section and never blanks the report.
    """
````

Pair 9 (the sections):

SEARCH:
````python
        # Each section uses log-and-degrade per the engineering principles —
        # one missing store should not blank the whole report.
        try:
            report.top_topics = await self._top_topics(since)
        except Exception as exc:
            logger.warning(
                "Insights: top_topics aggregation failed (%s); section will be empty in report", exc
            )

        try:
            report.top_crew = await self._top_crew(since)
        except Exception as exc:
            logger.warning(
                "Insights: top_crew aggregation failed (%s); section will be empty in report", exc
            )

        try:
            report.scheduled_tasks_completed = await self._scheduled_tasks_completed(since)
        except Exception as exc:
            logger.warning(
                "Insights: scheduled_tasks_completed aggregation failed (%s); section will be empty in report",
                exc,
            )

        try:
            report.pending_decisions = await self._pending_decisions(now)
        except Exception as exc:
            logger.warning(
                "Insights: pending_decisions aggregation failed (%s); section will be empty in report",
                exc,
            )

        try:
            report.anomaly_windows = await self._anomaly_windows(since)
        except Exception as exc:
            logger.warning(
                "Insights: anomaly_windows aggregation failed (%s); section will be empty in report",
                exc,
            )
````
REPLACE:
````python
        # Each section uses log-and-degrade per the engineering principles —
        # one missing store should not blank the whole report. BF-925 (#1655): a section
        # whose source is down or fails says so in ``unavailable`` instead of reading empty.
        report.unavailable.update(_NO_SOURCE)
        for name, gather, bound in (
            ("scheduled_tasks_completed", self._scheduled_tasks_completed, since),
            ("pending_decisions", self._pending_decisions, now),
            ("anomaly_windows", self._anomaly_windows, since),
        ):
            try:
                rows = await gather(bound)
            except Exception as exc:
                logger.warning(
                    "Insights: %s aggregation failed (%s); the report shows it as not available", name, exc,
                )
                report.unavailable[name] = f"failed ({type(exc).__name__})"
                continue
            if rows is None:
                report.unavailable[name] = "service not running"
            else:
                setattr(report, name, rows)
````

Pair 10 (the readers):

SEARCH:
````python
    async def _top_topics(self, since: float) -> list[TopicCount]:
        """Top topics by episodic recall frequency in the window."""
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None or not hasattr(episodic, "cluster_recall_counts"):
            return []
        candidates = await episodic.cluster_recall_counts(since=since)
        return [TopicCount(label=label, count=count) for label, count in candidates[:10]]

    async def _top_crew(self, since: float) -> list[CrewInteraction]:
        """Most-active crew callsigns by DM/session message volume in window."""
        threads_store = getattr(self._runtime, "thread_store", None)
        if threads_store is None or not hasattr(threads_store, "recent_threads_by_crew"):
            return []
        records = await threads_store.recent_threads_by_crew(since=since)
        return [
            CrewInteraction(
                callsign=r["callsign"],
                message_count=r["count"],
                last_active_ts=r["last_ts"],
            )
            for r in records[:10]
        ]

    async def _scheduled_tasks_completed(self, since: float) -> list[ScheduledTask]:
        """Watch-bill / scheduled-task completions in window."""
        watch = getattr(self._runtime, "watch_bill", None)
        if watch is None or not hasattr(watch, "completed_since"):
            return []
        records = await watch.completed_since(since)
        return [ScheduledTask(description=r["description"], completed_at=r["ts"]) for r in records]

    async def _pending_decisions(self, now: float) -> list[PendingDecision]:
        """Cross-source pending operator decisions (unresolved at ``now``)."""
        out: list[PendingDecision] = []
        consensus = getattr(self._runtime, "consensus_manager", None)
        if consensus is not None and hasattr(consensus, "pending_votes"):
            for v in await consensus.pending_votes():
                out.append(
                    PendingDecision(
                        summary=v["summary"],
                        age_hours=(now - v["created_at"]) / 3600.0,
                        source="consensus",
                    )
                )
        self_mod = getattr(self._runtime, "self_mod_pipeline", None)
        if self_mod is not None and hasattr(self_mod, "pending_proposals"):
            for p in await self_mod.pending_proposals():
                out.append(
                    PendingDecision(
                        summary=p["title"],
                        age_hours=(now - p["created_at"]) / 3600.0,
                        source="self_mod",
                    )
                )
        return out

    async def _anomaly_windows(self, since: float) -> list[AnomalyWindow]:
        """Anomaly-detector triggers (vision-budget breaches, gap reports, etc.)."""
        out: list[AnomalyWindow] = []
        vision_budget = getattr(self._runtime, "vision_budget", None)
        if vision_budget is not None and hasattr(vision_budget, "recent_breaches"):
            for b in await vision_budget.recent_breaches(since=since):
                out.append(
                    AnomalyWindow(
                        label=f"vision budget: {b['kind']}",
                        triggered_at=b["ts"],
                        severity=b.get("severity", "warning"),
                    )
                )
        return out
````
REPLACE:
````python
    async def _scheduled_tasks_completed(self, since: float) -> list[ScheduledTask] | None:
        """Persistent tasks that completed in the window; ``None`` when the store is not running.

        BF-925 (#1655): ``watch_bill.completed_since`` never existed. A task completes on its final
        run (``once``, or ``max_runs`` reached); a recurring task stays pending and is not counted.
        Reads the newest ``_MAX_COMPLETED_TASKS`` completed tasks by creation time.
        """
        store = self._runtime.persistent_task_store
        if store is None:
            return None
        tasks = await store.list_tasks(status="completed", limit=_MAX_COMPLETED_TASKS)
        return [
            ScheduledTask(description=t.name, completed_at=t.last_run_at)
            for t in tasks
            if t.last_run_at is not None and t.last_run_at >= since
        ]

    async def _pending_decisions(self, now: float) -> list[PendingDecision] | None:
        """Requests awaiting the Captain: capability and skill requests, oldest first.

        BF-925 (#1655): ``consensus_manager.pending_votes`` and ``self_mod_pipeline.pending_proposals``
        never existed. At most ``_MAX_PER_QUEUE`` per queue; ``None`` when neither queue is running.
        """
        capability = self._runtime.capability_request_store
        skills = self._runtime.skill_request_store
        if capability is None and skills is None:
            return None
        out: list[PendingDecision] = []
        if capability is not None:
            for req in sorted(await capability.list_pending(), key=lambda r: r.created_at)[:_MAX_PER_QUEUE]:
                out.append(PendingDecision(
                    summary=f"{req.kind} {req.target}",
                    age_hours=(now - req.created_at) / 3600.0,
                    source="capability_request",
                ))
        if skills is not None:
            for req in sorted(await skills.list_pending(), key=lambda r: r.created_at)[:_MAX_PER_QUEUE]:
                out.append(PendingDecision(
                    summary=f"skill {req.skill_label or req.skill_id}",
                    age_hours=(now - req.created_at) / 3600.0,
                    source="skill_request",
                ))
        return out

    async def _anomaly_windows(self, since: float) -> list[AnomalyWindow] | None:
        """Bridge alerts raised in the window, newest first; ``None`` when the service is not running.

        BF-925 (#1655): ``vision_budget.recent_breaches`` never existed. The alert log is in memory
        (the newest 200 since boot), so a window that reaches before boot shows this session's
        alerts. At most ``_MAX_ANOMALIES``.
        """
        alerts = self._runtime.bridge_alerts
        if alerts is None:
            return None
        recent = [a for a in alerts.get_recent_alerts(limit=_ALERT_LOG_READ) if a.timestamp >= since]
        return [
            AnomalyWindow(label=f"{a.source}: {a.title}", triggered_at=a.timestamp, severity=_SEVERITY[a.severity.value])
            for a in reversed(recent[-_MAX_ANOMALIES:])
        ]
````

Pair 11 (the summary):

SEARCH:
````python
        sections: list[str] = []
        if report.top_topics:
            sections.append(
                "Top topics: " + ", ".join(f"{t.label}({t.count})" for t in report.top_topics[:5])
            )
        if report.top_crew:
            sections.append(
                "Top crew: " + ", ".join(f"{c.callsign}({c.message_count})" for c in report.top_crew[:5])
            )
        if report.scheduled_tasks_completed:
````
REPLACE:
````python
        sections: list[str] = []  # BF-925 (#1655): topics and crew have no source, so no line
        if report.scheduled_tasks_completed:
````

### 7.2 `tests/test_ad810_insights.py` (M1, F06: fakes of methods nothing defines)

Pair 1:

SEARCH:
````python
@dataclass
class _FakeEpisodic:
    counts: list[tuple[str, int]]

    async def cluster_recall_counts(self, since: float) -> list[tuple[str, int]]:
        return self.counts


@dataclass
class _FakeThreadStore:
    records: list[dict[str, Any]]

    async def recent_threads_by_crew(self, since: float) -> list[dict[str, Any]]:
        return self.records


class _FakeRuntime:
    def __init__(
        self,
        *,
        episodic: Any = None,
        thread_store: Any = None,
        watch_bill: Any = None,
        consensus_manager: Any = None,
        self_mod_pipeline: Any = None,
        vision_budget: Any = None,
    ) -> None:
        self.episodic_memory = episodic
        self.thread_store = thread_store
        self.watch_bill = watch_bill
        self.consensus_manager = consensus_manager
        self.self_mod_pipeline = self_mod_pipeline
        self.vision_budget = vision_budget
````
REPLACE:
````python
from probos.bridge_alerts import AlertSeverity, BridgeAlert
from probos.capability_request import CapabilityRequest

# BF-925 (#1655): these fakes used to define ``cluster_recall_counts`` and ``recent_threads_by_crew``,
# which no production class defines, so the tests passed while the report was always empty. They now
# stand for the real stores by the real method names; tests/test_bf925_silent_guards.py pins each
# signature to its class, and the alert and request objects are the real dataclasses.


@dataclass
class _FakeAlerts:
    alerts: list[Any]

    def get_recent_alerts(self, limit: int = 50) -> list[Any]:
        return self.alerts[-limit:]


@dataclass
class _FakeRequests:
    requests: list[Any]

    async def list_pending(self) -> list[Any]:
        return list(self.requests)


def _alert(source: str, title: str, timestamp: float, severity: AlertSeverity) -> BridgeAlert:
    return BridgeAlert(
        id="alert-1", severity=severity, source=source, alert_type="test", title=title,
        detail="", department=None, dedup_key="test", timestamp=timestamp,
    )


def _request(target: str, created_at: float, kind: str = "grant") -> CapabilityRequest:
    return CapabilityRequest(id=f"req-{target}", agent_id="agent-1", kind=kind, target=target, created_at=created_at)


class _FakeRuntime:
    """The four runtime attributes InsightService reads (ProbOSRuntime declares each, default None)."""

    def __init__(
        self,
        *,
        bridge_alerts: Any = None,
        capability_request_store: Any = None,
        skill_request_store: Any = None,
        persistent_task_store: Any = None,
    ) -> None:
        self.bridge_alerts = bridge_alerts
        self.capability_request_store = capability_request_store
        self.skill_request_store = skill_request_store
        self.persistent_task_store = persistent_task_store
````

Pair 2:

SEARCH:
````python
async def test_build_report_happy_path_aggregates_all_sources():
    """Top topics + top crew + pending decisions all aggregate in one report."""
    now = time.time()
    runtime = _FakeRuntime(
        episodic=_FakeEpisodic(counts=[("memory-architecture", 12), ("vision-pipeline", 7)]),
        thread_store=_FakeThreadStore(
            records=[
                {"callsign": "Tucker", "count": 18, "last_ts": now - 3600},
                {"callsign": "Ezri", "count": 11, "last_ts": now - 7200},
            ]
        ),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.window_days == 7
    assert [t.label for t in report.top_topics] == ["memory-architecture", "vision-pipeline"]
    assert [c.callsign for c in report.top_crew] == ["Tucker", "Ezri"]
    assert report.narrative_summary == ""  # honest-degrade without llm_client
````
REPLACE:
````python
async def test_build_report_happy_path_aggregates_all_sources():
    """Anomalies (Bridge alerts) and pending decisions (capability requests) aggregate in one report.

    BF-925 (#1655): topics and crew have no source and say so; this test used to pin both from fakes
    of methods nothing defines.
    """
    now = time.time()
    runtime = _FakeRuntime(
        bridge_alerts=_FakeAlerts(alerts=[_alert("trust_network", "Trust Drop", now - 60, AlertSeverity.ALERT)]),
        capability_request_store=_FakeRequests(requests=[_request("shell", now - 7200)]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.window_days == 7
    assert [(a.label, a.severity) for a in report.anomaly_windows] == [("trust_network: Trust Drop", "critical")]
    assert [(d.source, d.summary) for d in report.pending_decisions] == [("capability_request", "grant shell")]
    assert report.pending_decisions[0].age_hours == pytest.approx(2.0, abs=0.01)
    assert set(report.unavailable) == {"top_topics", "top_crew", "scheduled_tasks_completed"}
    assert report.narrative_summary == ""  # honest-degrade without llm_client
````

Pair 3:

SEARCH:
````python
    """Empty runtime returns empty report; Markdown indicates the empty window."""
    runtime = _FakeRuntime()
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=14)
    assert report.is_empty()
    md = report.to_markdown()
    assert "last 14 day(s)" in md
    assert "No activity recorded" in md
````
REPLACE:
````python
    """No source running: the report is empty and names each section that is not available."""
    runtime = _FakeRuntime()
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=14)
    assert report.is_empty()
    md = report.to_markdown()
    assert "last 14 day(s)" in md
    assert "No activity recorded" in md
    assert "Not available: top topics (no store records recall frequency by topic)" in md  # BF-925
    assert "anomaly windows (service not running)" in md
````

Pair 4:

SEARCH:
````python
    """One section raising leaves the others intact (log-and-degrade)."""

    class _BrokenEpisodic:
        async def cluster_recall_counts(self, since: float):
            raise RuntimeError("boom")

    runtime = _FakeRuntime(
        episodic=_BrokenEpisodic(),
        thread_store=_FakeThreadStore(
            records=[{"callsign": "Tucker", "count": 5, "last_ts": time.time()}]
        ),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.top_topics == []
    assert len(report.top_crew) == 1
    assert report.top_crew[0].callsign == "Tucker"
````
REPLACE:
````python
    """One section raising is reported not available; the others stay intact (log-and-degrade)."""

    class _BrokenAlerts:
        def get_recent_alerts(self, limit: int = 50):
            raise RuntimeError("boom")

    runtime = _FakeRuntime(
        bridge_alerts=_BrokenAlerts(),
        capability_request_store=_FakeRequests(requests=[_request("shell", time.time())]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.anomaly_windows == []
    assert report.unavailable["anomaly_windows"] == "failed (RuntimeError)"  # BF-925: not silently empty
    assert len(report.pending_decisions) == 1
````

Pair 5:

SEARCH:
````python
    runtime = _FakeRuntime(
        episodic=_FakeEpisodic(counts=[("memory-architecture", 12)]),
    )
    service = InsightService(runtime=runtime, llm_client=_FakeLLM())
    report = await service.build_report(days=7)
    assert report.narrative_summary == "Operator activity was steady this week."
    assert _FakeLLM.captured["tier"] == "fast"
    assert "memory-architecture" in _FakeLLM.captured["prompt"]
````
REPLACE:
````python
    runtime = _FakeRuntime(
        capability_request_store=_FakeRequests(requests=[_request("weather tool", time.time(), kind="build")]),
    )
    service = InsightService(runtime=runtime, llm_client=_FakeLLM())
    report = await service.build_report(days=7)
    assert report.narrative_summary == "Operator activity was steady this week."
    assert _FakeLLM.captured["tier"] == "fast"
    assert "Pending decisions: 1" in _FakeLLM.captured["prompt"]
````

### 7.3 `src/probos/ward_room/messages.py` (M1, F11)

SEARCH:
````python
                # @mention connections
                mentions = extract_mentions(body)
                if mentions and hasattr(self, '_resolve_callsign_to_id'):
                    for callsign in mentions:
                        mid = self._resolve_callsign_to_id(callsign)
                        if mid and mid != author_id:
                            self._hebbian_router.record_interaction(
````
REPLACE:
````python
                # @mention connections
                # BF-925 (#1655): resolved through the CallsignRegistry attach_dispatcher binds, which reads
                # the live AgentRegistry, as the mention TaskEvent above is. The guarded
                # _resolve_callsign_to_id never existed, so no mention was ever recorded. One reinforcement
                # per mentioned agent per post (the thread author already has the reply link); a
                # self-mention, an unknown callsign or an agent that is not alive records nothing.
                mentions = extract_mentions(body)
                if mentions and self._callsign_registry is not None:
                    reinforced = {trow[0]} if trow and trow[0] and trow[0] != author_id else set()
                    for callsign in mentions:
                        resolved = self._callsign_registry.resolve(callsign)
                        mid = resolved.get("agent_id") if resolved else None
                        if mid and mid != author_id and mid not in reinforced:
                            reinforced.add(mid)
                            self._hebbian_router.record_interaction(
````

### 7.4 `src/probos/proactive.py` (M1, F18)

SEARCH:
````python
                if subordinate_types and hasattr(rt, 'ward_room_service') and rt.ward_room_service:
                    sub_stats: dict = {}
                    since = getattr(rt, '_start_time_wall', None)
                    for sub_type in subordinate_types:
                        sub_agent = rt.agent_pool.get(sub_type) if hasattr(rt, 'agent_pool') else None
                        if sub_agent:
                            sub_id = getattr(sub_agent, 'sovereign_id', None) or sub_agent.id
                            stats = await rt.ward_room_service.get_agent_comm_stats(
                                sub_id, since=since
                            )
                            if stats.get("posts_total", 0) >= 3:
                                callsign = getattr(sub_agent, 'callsign', sub_type)
                                sub_stats[callsign] = stats
````
REPLACE:
````python
                # BF-925 (#1655): the live attributes. ``ward_room_service`` and ``agent_pool`` exist on no
                # runtime, so no Chief ever saw these stats.
                if subordinate_types and rt.ward_room is not None:
                    sub_stats: dict = {}
                    since = getattr(rt, '_start_time_wall', None)
                    live = [a for a in rt.registry.all() if a.is_alive]
                    for sub_type in subordinate_types:
                        sub_agent = next((a for a in live if a.agent_type == sub_type), None)
                        if sub_agent:
                            # BF-925: posts and credibility carry the author's agent.id (every Ward Room
                            # write passes it), so the sovereign id read before counted no posts.
                            stats = await rt.ward_room.get_agent_comm_stats(sub_agent.id, since=since)
                            if stats.get("posts_total", 0) >= 3:
                                callsign = sub_agent.callsign or sub_type
                                sub_stats[callsign] = stats
````

### 7.5 `tests/test_ad630_leadership_feedback.py` (M1, F18: the dead attributes)

Pair 1:

SEARCH:
````python
        rt.ward_room_service = AsyncMock()
        if comm_stats is not None:
            rt.ward_room_service.get_agent_comm_stats = AsyncMock(
                return_value=comm_stats
            )
        rt.agent_pool = sub_agents or {}
        rt._start_time_wall = 1000.0
````
REPLACE:
````python
        # BF-925 (#1655): the runtime has ``ward_room`` and ``registry``. ``ward_room_service`` and
        # ``agent_pool``, which this helper set, exist on no runtime: the MagicMock invented them.
        rt.ward_room = AsyncMock()
        if comm_stats is not None:
            rt.ward_room.get_agent_comm_stats = AsyncMock(
                return_value=comm_stats
            )
        for agent_type, sub in (sub_agents or {}).items():
            sub.agent_type = agent_type
            sub.is_alive = True
        rt.registry.all = MagicMock(return_value=list((sub_agents or {}).values()))
        rt._start_time_wall = 1000.0
````

Pair 2:

SEARCH:
````python
        assert "subordinate_stats" in context
        assert "Forge" in context["subordinate_stats"]
        stats = context["subordinate_stats"]["Forge"]
        assert stats["posts_total"] == 5
````
REPLACE:
````python
        assert "subordinate_stats" in context
        assert "Forge" in context["subordinate_stats"]
        stats = context["subordinate_stats"]["Forge"]
        assert stats["posts_total"] == 5
        rt.ward_room.get_agent_comm_stats.assert_awaited_once_with("sub-id", since=1000.0)  # BF-925: agent.id
````

### 7.6 `src/probos/cognitive/episodic_procedural_bridge.py` (M1, F13)

Pair 1:

SEARCH:
````python
import inspect
import logging
````
REPLACE:
````python
import logging
````

Pair 2:

SEARCH:
````python
        store = self._procedure_store
        if store is None:
            return []

        if hasattr(store, "list_all"):
            result = store.list_all()
            if inspect.isawaitable(result):
                result = await result
            return [proc for proc in result if isinstance(proc, Procedure)]

        if not hasattr(store, "list_active") or not hasattr(store, "get"):
            return []

        active = store.list_active()
        if inspect.isawaitable(active):
            active = await active

        procedures: list[Procedure] = []
        for entry in active or []:
            procedure_id = entry.get("id", "") if isinstance(entry, dict) else getattr(entry, "id", "")
            if not procedure_id:
                continue
            procedure = store.get(procedure_id)
            if inspect.isawaitable(procedure):
                procedure = await procedure
            if isinstance(procedure, Procedure):
                procedures.append(procedure)
        return procedures
````
REPLACE:
````python
        store = self._procedure_store
        if store is None:
            return []

        # BF-925 (#1655): every active procedure through ProcedureStore.list_active and get. No store
        # defines list_all; the branch that asked for it never ran, and this was always the path.
        procedures: list[Procedure] = []
        for entry in await store.list_active():
            procedure = await store.get(entry["id"])
            if isinstance(procedure, Procedure):
                procedures.append(procedure)
        return procedures
````

### 7.7 New file: `tests/test_bf925_silent_guards.py` (M1)

````python
"""BF-925 (#1655) M1: guards on methods nothing defines, driven through the real classes.

F06 the Insights report, F11 Ward Room @mention Hebbian links, F18 the Chiefs' subordinate stats,
F13 the AD-572 bridge. Each test runs the production path on the real object, so it fails if the
method it reaches disappears again: no guard is left to hide it.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.bridge_alerts import BridgeAlertService
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.insights import InsightService
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure
from probos.config import BridgeConfig, SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.mesh.routing import REL_SOCIAL, HebbianRouter
from probos.persistent_tasks import PersistentTaskStore
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.skill_request import SkillRequestStore
from probos.substrate.registry import AgentRegistry
from probos.ward_room.service import WardRoomService


# --- F06: the Insights report -------------------------------------------------------------------

async def _completed_run(text: str, **_kwargs: Any) -> dict[str, Any]:
    """The task store's process_fn: a run that succeeds, so a once task completes."""
    return {"success": True, "text": text}


@pytest.fixture
async def insights_runtime(tmp_path: Path):
    """A real ProbOSRuntime (not started) holding the four real stores its start() attaches.

    start() sets bridge_alerts, capability_request_store, skill_request_store and
    persistent_task_store from the communication services; the test sets them because it boots no
    vessel. The task store's tick loop sleeps an hour, so only the test fires tasks.
    """
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    runtime.bridge_alerts = BridgeAlertService()
    runtime.capability_request_store = CapabilityRequestStore(db_path=str(tmp_path / "capability.db"))
    runtime.skill_request_store = SkillRequestStore(db_path=str(tmp_path / "skill.db"))
    runtime.persistent_task_store = PersistentTaskStore(
        db_path=str(tmp_path / "tasks.db"), process_fn=_completed_run, tick_interval=3600.0,
    )
    stores = (runtime.capability_request_store, runtime.skill_request_store, runtime.persistent_task_store)
    for store in stores:
        await store.start()
    try:
        yield runtime
    finally:
        for store in reversed(stores):
            await store.stop()


async def test_the_report_reads_alerts_requests_and_completed_tasks(insights_runtime: Any) -> None:
    runtime = insights_runtime
    assert runtime.bridge_alerts.check_trust_change("agent-x", 0.9, 0.3) is not None  # premise: one ALERT
    await runtime.capability_request_store.file_request("agent-x", "grant", "shell")
    await runtime.skill_request_store.file_request("agent-y", "skill-1", skill_label="Triage")
    task = await runtime.persistent_task_store.create_task(
        "run diagnostics", name="Diagnostics", execute_at=time.time() - 1.0,
    )
    await runtime.persistent_task_store._execute_due_tasks()  # the tick loop's body, as BF-877's tests run it
    assert (await runtime.persistent_task_store.get_task(task.id)).status == "completed"  # premise

    report = await InsightService(runtime=runtime).build_report(days=7)

    assert [(a.severity, a.label.split(":")[0]) for a in report.anomaly_windows] == [("critical", "trust_network")]
    assert sorted((d.source, d.summary) for d in report.pending_decisions) == [
        ("capability_request", "grant shell"),
        ("skill_request", "skill Triage"),
    ]
    assert [t.description for t in report.scheduled_tasks_completed] == ["Diagnostics"]
    assert set(report.unavailable) == {"top_topics", "top_crew"}
    assert "Not available: top topics" in report.to_markdown()


async def test_a_source_that_is_not_running_reports_not_available(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")  # not started: no store attached
    report = await InsightService(runtime=runtime).build_report(days=3)
    assert report.is_empty()
    assert report.unavailable == {
        "top_topics": "no store records recall frequency by topic",
        "top_crew": "no store counts DM or session messages per crew member",
        "scheduled_tasks_completed": "service not running",
        "pending_decisions": "service not running",
        "anomaly_windows": "service not running",
    }
    markdown = report.to_markdown()
    assert "_No activity recorded in this window._" in markdown
    assert "scheduled tasks (service not running)" in markdown


async def test_the_report_json_keeps_its_keys_and_adds_unavailable(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    data = (await InsightService(runtime=runtime).build_report(days=7)).to_json()
    assert set(data) == {
        "window_days", "generated_at", "top_topics", "top_crew", "scheduled_tasks_completed",
        "pending_decisions", "anomaly_windows", "narrative_summary", "unavailable",
    }
    assert data["top_topics"] == [] and data["top_crew"] == []  # no source; the keys stay for API readers
    assert data["unavailable"]["anomaly_windows"] == "service not running"


async def test_alerts_outside_the_window_are_left_out(insights_runtime: Any) -> None:
    runtime = insights_runtime
    old = runtime.bridge_alerts.check_trust_change("agent-old", 0.9, 0.3)
    new = runtime.bridge_alerts.check_trust_change("agent-new", 0.9, 0.7)  # an ADVISORY
    old.timestamp = time.time() - 8 * 86400.0  # the service stamps alerts when raised; this one is moved back
    report = await InsightService(runtime=runtime).build_report(days=7)
    assert [(a.label, a.severity) for a in report.anomaly_windows] == [(f"trust_network: {new.title}", "warning")]


def test_the_insights_doubles_match_the_real_classes() -> None:
    """tests/test_ad810_insights.py's fakes stand for these stores; each keeps the real parameters."""
    from tests.test_ad810_insights import _FakeAlerts, _FakeRequests

    for double, real, name in (
        (_FakeAlerts, BridgeAlertService, "get_recent_alerts"),
        (_FakeRequests, CapabilityRequestStore, "list_pending"),
        (_FakeRequests, SkillRequestStore, "list_pending"),
    ):
        assert list(inspect.signature(getattr(double, name)).parameters) == list(
            inspect.signature(getattr(real, name)).parameters
        ), f"{double.__name__}.{name} drifted from {real.__name__}.{name}"


# --- F11: Ward Room @mention Hebbian links ------------------------------------------------------

class _AcceptingDispatcher:
    """Stands for AD-654d's dispatcher, which attach_dispatcher binds with the CallsignRegistry.

    It masks only the mention TaskEvent's delivery, which BF-925 does not change; the Hebbian write
    F11 adds does not pass through it.
    """

    async def dispatch(self, event: Any) -> Any:
        return SimpleNamespace(accepted=True, rejected=0, unroutable=0)


_CREW = (  # (agent id, agent type, callsign, alive)
    ("bones-1", "medical_officer", "Bones", True),
    ("thea-1", "science_officer", "Thea", True),
    ("ghost-1", "ghost_officer", "Ghost", False),
)


@pytest.fixture
async def ward_room(tmp_path: Path):
    """A started WardRoomService with a real HebbianRouter, AgentRegistry and CallsignRegistry.

    Crew are SimpleNamespaces with the attributes AgentRegistry.register and CallsignRegistry.resolve
    read. Thea opens the thread every test posts in.
    """
    router = HebbianRouter()
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"), hebbian_router=router)
    await service.start()
    registry = AgentRegistry()
    callsigns = CallsignRegistry()
    callsigns.bind_registry(registry)
    for agent_id, agent_type, callsign, alive in _CREW:
        await registry.register(SimpleNamespace(id=agent_id, agent_type=agent_type, pool=agent_type, is_alive=alive))
        callsigns.set_callsign(agent_type, callsign)
    service.attach_dispatcher(_AcceptingDispatcher(), callsigns)  # as startup/finalize.py does
    channel_id = (await service.list_channels())[0].id
    thread = await service.create_thread(channel_id, "thea-1", "Survey", "Opening the survey.", author_callsign="Thea")
    try:
        yield SimpleNamespace(service=service, router=router, thread_id=thread.id)
    finally:
        await service.stop()


def _social(router: HebbianRouter, source: str, target: str) -> float:
    return router.get_weight(source, target, rel_type=REL_SOCIAL)


async def test_a_mention_records_a_social_link_to_the_mentioned_agent(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones please check the scan", author_callsign="Avery")
    assert _social(ward_room.router, "author-1", "bones-1") == pytest.approx(0.05)  # one reinforcement (reward 0.05)
    assert _social(ward_room.router, "author-1", "thea-1") == pytest.approx(0.05)  # premise: the AD-453 reply link


async def test_one_post_reinforces_each_mentioned_agent_once(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones @bones and @Thea", author_callsign="Avery")
    assert _social(ward_room.router, "author-1", "bones-1") == pytest.approx(0.05)  # not 0.05 * 0.995 + 0.05
    assert _social(ward_room.router, "author-1", "thea-1") == pytest.approx(0.05)  # the reply link already counts Thea


async def test_no_link_for_oneself_an_unknown_callsign_or_an_agent_that_is_not_alive(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "bones-1", "@Bones @Nobody @Ghost", author_callsign="Bones")
    social = {key for key in ward_room.router.all_weights_typed() if key[2] == REL_SOCIAL}
    assert social == {("bones-1", "thea-1", REL_SOCIAL)}  # only the reply link


# --- F18: the Chiefs' subordinate communication stats -------------------------------------------

def _chief_loop(service: WardRoomService, registry: AgentRegistry) -> ProactiveCognitiveLoop:
    """A proactive loop whose runtime holds the real Ward Room and AgentRegistry F18 reads.

    The runtime is a MagicMock for the context sources F18 does not touch, as
    test_ad630_leadership_feedback.py's helper is; ward_room, registry and the ontology's answer are
    set explicitly. A MagicMock invents any attribute, so
    test_the_attributes_these_paths_read_exist_on_the_runtime pins the names on a real runtime.
    """
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    runtime = MagicMock()
    runtime.ontology.get_subordinate_agent_types = MagicMock(return_value=["engineering_officer"])
    runtime.ontology.get_crew_context = MagicMock(return_value=None)
    runtime.ward_room = service
    runtime.registry = registry
    runtime._start_time_wall = 0.0
    runtime.trust_network = AsyncMock()
    runtime.trust_network.get_score = AsyncMock(return_value=0.5)
    runtime.skill_service = None
    runtime._introspective_telemetry = None
    runtime.conn_manager = None
    runtime.cognitive_skill_catalog = None
    loop.set_runtime(runtime)
    loop._build_self_monitoring_context = AsyncMock(return_value=None)
    return loop


def _chief() -> MagicMock:
    chief = MagicMock()
    chief.agent_type = "chief_engineer"
    chief.id = "chief-1"
    chief.sovereign_id = "uuid-chief"
    chief.callsign = "LaForge"
    return chief


async def _subordinate_context(tmp_path: Path, *, alive: bool) -> dict[str, Any]:
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    await service.start()
    try:
        registry = AgentRegistry()
        await registry.register(SimpleNamespace(
            id="forge-1", agent_type="engineering_officer", pool="engineering_officer",
            is_alive=alive, callsign="Forge", sovereign_id="uuid-forge",
        ))
        channel_id = (await service.list_channels())[0].id
        thread = await service.create_thread(channel_id, "ops-1", "Status", "Status thread.", author_callsign="Ops")
        for index in range(3):  # posts carry agent.id, as every create_post caller passes
            await service.create_post(thread.id, "forge-1", f"Report {index}.", author_callsign="Forge")
        return await _chief_loop(service, registry)._gather_context(_chief(), 0.5)
    finally:
        await service.stop()


async def test_a_chief_sees_a_subordinates_ward_room_stats(tmp_path: Path) -> None:
    context = await _subordinate_context(tmp_path, alive=True)
    assert context["subordinate_stats"]["Forge"]["posts_total"] == 3  # by agent.id; the sovereign id counts 0


async def test_a_subordinate_with_no_live_agent_is_skipped(tmp_path: Path) -> None:
    context = await _subordinate_context(tmp_path, alive=False)
    assert "subordinate_stats" not in context


def test_the_attributes_these_paths_read_exist_on_the_runtime(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    names = {
        "ward_room", "registry", "ontology", "bridge_alerts", "capability_request_store",
        "skill_request_store", "persistent_task_store", "event_log",
    }
    assert names <= set(vars(runtime)), sorted(names - set(vars(runtime)))


# --- F13: the AD-572 episodic-procedural bridge -------------------------------------------------

def _cluster(cluster_id: str, episode_ids: list[str]) -> EpisodeCluster:
    return EpisodeCluster(
        cluster_id=cluster_id, episode_ids=episode_ids, episode_count=len(episode_ids),
        centroid=[1.0, 0.0], variance=0.0, success_rate=1.0, is_success_dominant=True,
        is_failure_dominant=False, participating_agents=["agent-a"], intent_types=["diagnose"],
        first_occurrence=1.0, last_occurrence=2.0,
    )


@pytest.fixture
async def procedure_store(tmp_path: Path):
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    try:
        await store.save(Procedure(
            id="p-1", name="Diagnose", intent_types=["diagnose"], provenance=["ep-0", "ep-1", "ep-2", "ep-3"],
        ))
        yield store
    finally:
        await store.stop()


async def test_the_bridge_merges_a_cluster_a_stored_procedure_covers(procedure_store: ProcedureStore) -> None:
    """The stored procedure loads through list_active and get, so a covered cluster is not new."""
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=procedure_store)
    assert await bridge.bridge_episodes_to_procedures([], [_cluster("c-1", [f"ep-{i}" for i in range(5)])]) == []


async def test_the_bridge_still_bridges_a_novel_cluster(procedure_store: ProcedureStore) -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=procedure_store)
    bridged = await bridge.bridge_episodes_to_procedures([], [_cluster("c-2", [f"new-{i}" for i in range(5)])])
    assert [procedure.origin_cluster_id for procedure in bridged] == ["c-2"]
````

### 7.8 New file: `tests/test_bf925_guard_names.py` (M1)

````python
"""BF-925 (#1655): a production hasattr/getattr guard must name an attribute production code defines.

The defect class: a guard on a name nothing defines turns a missing API into a silent empty result
(#1655: the Insights report, @mention links, the procedural bridge, the Chiefs' stats).

A *guard* is ``hasattr(obj, "name")`` or ``getattr(obj, "name", default)`` (a string literal), inside
a function, whose receiver's root is ``self``, ``cls``, ``rt`` or ``runtime``, or a local name
assigned in an enclosing function from such an expression (to a fixed point). A name is *defined*
when production code under src/probos has it as a def or class name, a module- or class-level
assignment target (class attributes, dataclass and pydantic fields, enum members), any attribute
assignment target (``self.x = ...``), a ``__slots__`` string, a ``setattr`` literal, a module-level
import name, or an argparse ``dest`` or first long option. Dunder names are skipped. AST only:
nothing is imported, and this checkout's src is scanned.

It cannot see: a guard on a parameter or a local not derived from those roots; a name an unrelated
production class happens to define (F12's ``recent``; ``pending_proposals``); dynamic names;
``try/except AttributeError``; module-level guards; ``__getattr__``. Third-party attributes on owned
receivers are allow-listed as ``duck`` in tests/fixtures/guard_name_allowlist.txt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_ALLOW_LIST = Path(__file__).resolve().parent / "fixtures" / "guard_name_allowlist.txt"
_OWNED = frozenset({"self", "cls", "rt", "runtime"})
_KINDS = frozenset({"duck", "finding"})


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _add_call_definitions(call: ast.Call, names: set[str]) -> None:
    func = call.func
    called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    if called == "setattr" and len(call.args) >= 2 and _literal(call.args[1]) is not None:
        names.add(_literal(call.args[1]))
    for keyword in call.keywords:
        if keyword.arg == "dest" and _literal(keyword.value) is not None:
            names.add(_literal(keyword.value))
    if called == "add_argument":
        options = [option for option in (_literal(arg) for arg in call.args) if option is not None]
        longs = [option for option in options if option.startswith("--")]
        chosen = longs[0] if longs else (options[0] if options else "")
        if chosen:
            names.add(chosen.lstrip("-").replace("-", "_"))


def _defined_names(trees: list[ast.AST]) -> set[str]:
    names: set[str] = set()

    def add_target(target: ast.AST, scoped: bool) -> None:
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name) and scoped:
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                add_target(element, scoped)
        elif isinstance(target, ast.Starred):
            add_target(target.value, scoped)

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(child.name)
                visit(child, "function")
                continue
            if isinstance(child, ast.ClassDef):
                names.add(child.name)
                visit(child, "class")
                continue
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    add_target(target, scope in ("module", "class"))
                    if isinstance(target, ast.Name) and target.id == "__slots__" and child.value is not None:
                        names.update(
                            item for item in (_literal(n) for n in ast.walk(child.value)) if item is not None
                        )
            if isinstance(child, (ast.Import, ast.ImportFrom)) and scope == "module":
                names.update((alias.asname or alias.name).split(".")[0] for alias in child.names)
            if isinstance(child, ast.Call):
                _add_call_definitions(child, names)
            visit(child, scope)

    for tree in trees:
        visit(tree, "module")
    return names


def _root(expr: ast.AST) -> str:
    while True:
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        elif isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name) and expr.func.id == "getattr" and expr.args:
                expr = expr.args[0]
            else:
                expr = expr.func
        else:
            return expr.id if isinstance(expr, ast.Name) else ""


def _value_root(value: ast.AST) -> str:
    if isinstance(value, ast.BoolOp) and value.values:
        return _value_root(value.values[0])
    if isinstance(value, ast.IfExp):
        return _value_root(value.body)
    if isinstance(value, ast.Await):
        return _value_root(value.value)
    return _root(value)


def _owned_names(function: ast.AST) -> set[str]:
    owned = set(_OWNED)
    assigns = [
        node for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if _value_root(node.value) not in owned:
                continue
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and target.id not in owned:
                    owned.add(target.id)
                    changed = True
    return owned


def _guarded_name(node: ast.AST) -> str | None:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    arity = {"hasattr": 2, "getattr": 3}.get(node.func.id)
    if arity is None or len(node.args) != arity:
        return None
    return _literal(node.args[1])


def unresolved_guards(sources: dict[str, str]) -> set[tuple[str, str]]:
    """(path, name) of every owned guard whose non-dunder name no source defines."""
    trees = {path: ast.parse(text, filename=path) for path, text in sources.items()}
    defined = _defined_names(list(trees.values()))
    found: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            owned = _owned_names(function)
            for node in ast.walk(function):
                name = _guarded_name(node)
                if name is None or (name.startswith("__") and name.endswith("__")) or name in defined:
                    continue
                if _root(node.args[0]) in owned:
                    found.add((path, name))
    return found


def load_allow_list(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    entries: dict[tuple[str, str], tuple[str, str]] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [part.strip() for part in line.split("|")]
        if len(fields) != 4 or not all(fields) or fields[2] not in _KINDS:
            raise ValueError(f"{path.name}:{number}: expected 'path | name | duck|finding | reason': {raw!r}")
        key = (fields[0], fields[1])
        if key in entries:
            raise ValueError(f"{path.name}:{number}: duplicate entry {key}")
        entries[key] = (fields[2], fields[3])
    return entries


def compare(hits: set[tuple[str, str]], allowed: set[tuple[str, str]]) -> tuple[list, list]:
    """(guards not allow-listed, allow-list entries that are no longer a hit)."""
    return sorted(hits - allowed), sorted(allowed - hits)


def _production_sources() -> dict[str, str]:
    return {path.relative_to(_REPO).as_posix(): path.read_text(encoding="utf-8") for path in sorted(_SRC.rglob("*.py"))}


def test_production_guards_name_attributes_production_code_defines() -> None:
    new, stale = compare(unresolved_guards(_production_sources()), set(load_allow_list(_ALLOW_LIST)))
    assert new == [], f"guards on names no production code defines (wire the real API, or allow-list with a reason): {new}"
    assert stale == [], f"allow-list entries whose name is now defined or no longer guarded in that file: {stale}"


def test_a_guard_on_an_undefined_name_is_reported() -> None:
    source = (
        "class A:\n"
        "    def run(self, rt):\n"
        "        store = self._store\n"
        "        return hasattr(store, 'list_all') or getattr(rt, 'agent_pool', None)\n"
    )
    assert unresolved_guards({"pkg/a.py": source}) == {("pkg/a.py", "list_all"), ("pkg/a.py", "agent_pool")}


_GUARD = "class A:\n    def run(self):\n        return hasattr(self, 'target')\n"


@pytest.mark.parametrize("definition", [
    "class B:\n    def target(self):\n        return 1\n",
    "class B:\n    target: int = 0\n",
    "import enum\nclass B(enum.Enum):\n    target = 1\n",
    "class B:\n    def __init__(self):\n        self.target = 1\n",
    "class B:\n    __slots__ = ('target',)\n",
    "def f(o):\n    setattr(o, 'target', 1)\n",
    "def f(parser):\n    parser.add_argument('--target')\n",
], ids=["def", "field", "enum-member", "self-assign", "slots", "setattr", "argparse"])
def test_a_name_defined_by_production_code_is_not_reported(definition: str) -> None:
    assert unresolved_guards({"pkg/a.py": _GUARD, "pkg/b.py": definition}) == set()


@pytest.mark.parametrize("source", [
    "def f(page):\n    return getattr(page, 'mouse', None)\n",
    "class A:\n    def f(self):\n        return hasattr(self, '__aiter__')\n",
    "class A:\n    def f(self):\n        return getattr(self, 'missing')\n",
], ids=["parameter-receiver", "dunder", "two-argument-getattr"])
def test_guards_this_scan_does_not_own_are_not_reported(source: str) -> None:
    assert unresolved_guards({"pkg/a.py": source}) == set()


def test_a_stale_allow_list_entry_is_reported(tmp_path: Path) -> None:
    allow_list = tmp_path / "allow.txt"
    allow_list.write_text(
        "pkg/a.py | list_all | finding | defined now\npkg/a.py | gone_name | duck | no longer guarded\n",
        encoding="utf-8",
    )
    guard = "class A:\n    def run(self):\n        return hasattr(self._store, 'list_all')\n"
    definition = "class Store:\n    def list_all(self):\n        return []\n"
    hits = unresolved_guards({"pkg/a.py": guard, "pkg/store.py": definition})
    new, stale = compare(hits, set(load_allow_list(allow_list)))
    assert (new, stale) == ([], [("pkg/a.py", "gone_name"), ("pkg/a.py", "list_all")])


def test_the_allow_list_has_one_reason_per_entry() -> None:
    entries = load_allow_list(_ALLOW_LIST)  # raises on a malformed line or a duplicate
    assert entries, "the allow-list is empty: delete it with this test's checks, or restore it"
    for (path, _name), (_kind, reason) in entries.items():
        assert (_REPO / path).is_file(), f"{path} does not exist"
        assert len(reason) >= 10, f"{path}: the reason is too short to review"
````

### 7.9 New file: `tests/fixtures/guard_name_allowlist.txt` (M1)

````text
# BF-925 (#1655): production guards that name an attribute no production code defines, accepted on
# purpose. tests/test_bf925_guard_names.py checks both directions: a guard not listed here fails the
# test, and so does an entry whose name is now defined or no longer guarded in that file.
# Format: path | name | kind | reason.
#   duck     a third-party or version-dependent attribute, optional by design
#   finding  a dead-guard candidate BF-925's scan found, registered on #1523 (R1), not yet triaged
# Measured 2026-10-25 on 72fae2dd with BF-925 M1 applied.
src/probos/channels/base.py | pairing_service | finding | self.runtime.pairing_service has no production definition
src/probos/channels/discord_adapter.py | http | duck | discord.py Bot.http on the adapter's bot
src/probos/channels/discord_adapter.py | _HTTPClient__session | duck | discord.py HTTPClient's private session; version-dependent
src/probos/cognitive/captain_engagement.py | captain_dm_queue_depth | finding | ward_room.captain_dm_queue_depth has no production definition
src/probos/cognitive/cognitive_agent.py | _callsign | finding | self._callsign has no production definition (agents define callsign)
src/probos/cognitive/cognitive_agent.py | get_by_intent | finding | self._procedure_store.get_by_intent has no production definition
src/probos/cognitive/communication_benchmarks.py | _callsign | finding | agent._callsign has no production definition (agents define callsign)
src/probos/cognitive/counselor.py | model_dump | duck | pydantic v2 BaseModel.model_dump on a model-or-dict value
src/probos/cognitive/dm/reply_pipeline.py | action_dispatcher | finding | self.ctx.runtime.action_dispatcher has no production definition
src/probos/cognitive/dreaming.py | _agent_type | finding | self._agent_type has no production definition
src/probos/cognitive/gap_remediation.py | qualification_service | finding | runtime.qualification_service has no production definition
src/probos/cognitive/peer_observation_training.py | crew_profile | finding | agent.crew_profile has no production definition
src/probos/cognitive/scout.py | channel_adapters | finding | self._runtime.channel_adapters has no production definition
src/probos/cognitive/swe_harness/tools.py | system_self_model | finding | self._runtime.system_self_model has no production definition
src/probos/cognitive/swe_harness/tools.py | list_pools | finding | spawner.list_pools has no production definition
src/probos/experience/commands/commands_status.py | memory_security_registry | finding | runtime.memory_security_registry has no production definition
src/probos/mesh/nats_bus.py | reconnected_count | duck | nats-py client attribute; version-dependent
src/probos/routers/agent_actions.py | action_dispatcher | finding | runtime.action_dispatcher has no production definition
src/probos/routers/teams_webhook.py | teams_adapter | finding | runtime.teams_adapter has no production definition
src/probos/tools/browser/llm_classifier.py | complete_sync | finding | llm.complete_sync has no production definition
src/probos/tools/browser/session.py | viewport_size | duck | Playwright Page.viewport_size
src/probos/tools/browser/session.py | mouse | duck | Playwright Page.mouse
src/probos/tools/browser/session.py | keyboard | duck | Playwright Page.keyboard
````

### 7.10 `src/probos/substrate/event_log.py` (M2, F12)

SEARCH:
````python
    async def count_all(self) -> int:
        """Total event count."""
        return await self.count()
````
REPLACE:
````python
    async def count_all(self) -> int:
        """Total event count."""
        return await self.count()

    async def count_since(self, since: float, *, cap: int = 1000) -> int:
        """BF-925 (#1655): how many of the newest ``cap`` events were logged at or after ``since``.

        ``since`` is Unix seconds. Only the newest ``cap`` rows by id (the primary key) are read, so
        the cost is bounded whatever the table's size; a non-positive ``cap`` counts nothing (SQLite
        reads ``LIMIT -1`` as no limit). Timestamps are stored as UTC ISO text, as ``prune`` compares.
        """
        if not self._db or cap <= 0:
            return 0
        cutoff = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()
        async with self._db.execute(
            "SELECT COUNT(*) FROM (SELECT timestamp FROM events ORDER BY id DESC LIMIT ?) WHERE timestamp >= ?",
            (cap, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
````

### 7.11 `src/probos/proactive.py` (M2, F12)

Pair 1 (the no-response anchor):

SEARCH:
````python
                            watch_section=derive_watch_section(),
                            event_log_window=float(len(rt.event_log.recent(seconds=60))) if hasattr(rt, 'event_log') and hasattr(rt.event_log, 'recent') else 0.0,
                        ),
````
REPLACE:
````python
                            watch_section=derive_watch_section(),
                            event_log_window=await self._event_log_window(rt),  # BF-925 (#1655): no-response episode
                        ),
````

Pair 2 (the thought anchor):

SEARCH:
````python
                        event_log_window=float(len(rt.event_log.recent(seconds=60))) if hasattr(rt, 'event_log') and hasattr(rt.event_log, 'recent') else 0.0,
                        source_timestamp=_earliest_source_ts,  # AD-577
````
REPLACE:
````python
                        event_log_window=await self._event_log_window(rt),  # BF-925 (#1655): thought episode
                        source_timestamp=_earliest_source_ts,  # AD-577
````

Pair 3 (the helper):

SEARCH:
````python
    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
        """Gather recent context for the agent's proactive review."""
````
REPLACE:
````python
    # BF-925 (#1655): the window an episode anchor counts, and whether a failed read has warned.
    _EVENT_LOG_WINDOW_SECONDS = 60.0
    _event_log_window_warned = False

    async def _event_log_window(self, rt: Any) -> float:
        """BF-925 (#1655): events the ship's EventLog recorded in the last 60 s, for an episode anchor.

        EventLog never had the ``recent`` both anchor sites guarded on, so every anchor recorded 0.0.
        The value is held out of anchor-confidence scoring until it is measured (#1523). A failed
        read records 0.0, the value every anchor had before; the first failure per loop warns.
        """
        try:
            return float(await rt.event_log.count_since(time.time() - self._EVENT_LOG_WINDOW_SECONDS))
        except Exception:
            if not self._event_log_window_warned:
                self._event_log_window_warned = True
                logger.warning("BF-925 (#1655): EventLog window read failed; episode anchors record 0.0 (later failures log at DEBUG)", exc_info=True)
            else:
                logger.debug("BF-925: EventLog window read failed again", exc_info=True)
            return 0.0

    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
        """Gather recent context for the agent's proactive review."""
````

### 7.12 `src/probos/cognitive/anchor_quality.py` (M2, F12)

Pair 1:

SEARCH:
````python
    "evidential": 0.10, # Corroboration — supplementary
}
````
REPLACE:
````python
    "evidential": 0.10, # Corroboration — supplementary
}

# BF-925 (#1655): ``event_log_window`` is held out of scoring until it is measured (#1523). No
# producer ever stored a non-zero window, so it counts as one unfilled evidential field, exactly as
# 0.0 did: every confidence score, profile fill rate and recall gate is unchanged.
_EVENT_LOG_WINDOW_HELD_OUT = 0.0
````

Pair 2:

SEARCH:
````python
    evidential_fields = [anchors.thread_id, anchors.event_log_window]
````
REPLACE:
````python
    evidential_fields = [anchors.thread_id, _EVENT_LOG_WINDOW_HELD_OUT]  # BF-925: the window is held out
````

### 7.13 `src/probos/cognitive/memory_security.py` (M2, F12)

SEARCH:
````python
        # evidential
        "thread_id": "evidential",
        "event_log_window": "evidential",
        "evidential": "evidential",
````
REPLACE:
````python
        # evidential (BF-925, #1655: event_log_window is held out until measured, #1523; the
        # production query, episodic._AnchorQueryView, never set it, so no verdict changes)
        "thread_id": "evidential",
        "evidential": "evidential",
````

### 7.14 `tests/test_orientation.py` (M2: a MagicMock's `recent`)

SEARCH:
````python
    def test_event_log_window_populated(self) -> None:
        """AnchorFrame construction in proactive.py includes event_log_window."""
        from probos.types import AnchorFrame
        # Simulate event log with 5 recent events
        mock_el = MagicMock()
        mock_el.recent.return_value = [1, 2, 3, 4, 5]
        anchor = AnchorFrame(
            channel="duty_report",
            event_log_window=float(len(mock_el.recent(seconds=60))),
            watch_section=derive_watch_section(14),
        )
        assert anchor.event_log_window == 5.0
        assert anchor.watch_section == "afternoon"
````
REPLACE:
````python
    async def test_event_log_window_populated(self, tmp_path) -> None:
        """AnchorFrame construction in proactive.py includes event_log_window.

        BF-925 (#1655): this used a MagicMock's ``recent``, which EventLog never had, so it passed
        while every anchor recorded 0.0. It now counts through the real EventLog.
        """
        from probos.substrate.event_log import EventLog
        from probos.types import AnchorFrame
        event_log = EventLog(db_path=tmp_path / "events.db")
        await event_log.start()
        try:
            for index in range(5):
                await event_log.log("test", f"event-{index}")
            anchor = AnchorFrame(
                channel="duty_report",
                event_log_window=float(await event_log.count_since(time.time() - 60.0)),
                watch_section=derive_watch_section(14),
            )
        finally:
            await event_log.stop()
        assert anchor.event_log_window == 5.0
        assert anchor.watch_section == "afternoon"
````

### 7.15 `tests/test_ad567c_anchor_quality.py` (M2: a fixture window no producer stores)

Pair 1:

SEARCH:
````python
    def test_all_fields_filled(self):
        """Test 1: All 10 fields filled → confidence ≈ 1.0."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(_full_anchor())
        assert abs(conf - 1.0) < 1e-9
````
REPLACE:
````python
    def test_all_fields_filled(self):
        """Test 1: All 10 fields filled → confidence ≈ 0.95.

        BF-925 (#1655): event_log_window is held out of scoring and counts as unfilled, so the
        evidential dimension is at most 1/2 (0.10 * 0.5). No producer ever stored a non-zero
        window, so no stored episode's score moves; this fixture's 1000.0 did.
        """
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(_full_anchor())
        assert abs(conf - 0.95) < 1e-9
````

Pair 2:

SEARCH:
````python
            _make_episode(anchors=_full_anchor()),       # conf = 1.0
            _make_episode(anchors=AnchorFrame()),         # conf = 0.0
            _make_episode(anchors=_temporal_only_anchor()),  # conf = 0.25
        ])

        profile = await build_anchor_profile("agent-001", mock_em)
        assert profile.total_episodes == 3
        # mean = (1.0 + 0.0 + 0.25) / 3 ≈ 0.4167
        assert abs(profile.mean_confidence - (1.0 + 0.0 + 0.25) / 3) < 1e-4
````
REPLACE:
````python
            _make_episode(anchors=_full_anchor()),       # conf = 0.95 (BF-925: the window is held out)
            _make_episode(anchors=AnchorFrame()),         # conf = 0.0
            _make_episode(anchors=_temporal_only_anchor()),  # conf = 0.25
        ])

        profile = await build_anchor_profile("agent-001", mock_em)
        assert profile.total_episodes == 3
        # mean = (0.95 + 0.0 + 0.25) / 3 = 0.4
        assert abs(profile.mean_confidence - (0.95 + 0.0 + 0.25) / 3) < 1e-4
````

### 7.16 `tests/test_ad567b_anchor_recall.py` (M2: a fixture window no producer stores)

Pair 1:

SEARCH:
````python
        # = 0.35*0.8 + 0.20*1.0 + 0.10*0.9 + 0.05*0.7 + 0.15*0.6 + 0.15*1.0 + 0.10
        expected = 0.35 * 0.8 + 0.20 * 1.0 + 0.10 * 0.9 + 0.05 * 0.7 + 0.15 * 0.6 + 0.15 * 1.0 + 0.10
        assert abs(rs.composite_score - expected) < 1e-9
        assert rs.anchor_confidence == 1.0
````
REPLACE:
````python
        # BF-925 (#1655): event_log_window is held out of anchor scoring, so this fixture's 1000.0 (a
        # value no producer ever stored) counts as unfilled: anchor confidence 0.95.
        # = 0.35*0.8 + 0.20*1.0 + 0.10*0.9 + 0.05*0.7 + 0.15*0.6 + 0.15*0.95 + 0.10
        expected = 0.35 * 0.8 + 0.20 * 1.0 + 0.10 * 0.9 + 0.05 * 0.7 + 0.15 * 0.6 + 0.15 * 0.95 + 0.10
        assert abs(rs.composite_score - expected) < 1e-9
        assert rs.anchor_confidence == pytest.approx(0.95)
````

Pair 2:

SEARCH:
````python
        """10/10 fields = 1.0."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(anchors=_full_anchor())
        rs = EpisodicMemory.score_recall(ep, semantic_similarity=0.5)
        assert rs.anchor_confidence == 1.0
````
REPLACE:
````python
        """10/10 fields filled = 0.95: BF-925 (#1655) holds event_log_window out (scored as unfilled)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(anchors=_full_anchor())
        rs = EpisodicMemory.score_recall(ep, semantic_similarity=0.5)
        assert rs.anchor_confidence == pytest.approx(0.95)
````

Pair 3 (A1):

SEARCH:
````python
        # Trust dominates: 0.80 * 0.9 = 0.72 for trust alone
        expected_custom = 0.80 * 0.9 + 0.10 * 0.5 + 0.10 * 1.0
````
REPLACE:
````python
        # Trust dominates: 0.80 * 0.9 = 0.72 for trust alone. BF-925 (#1655): event_log_window is held
        # out of anchor scoring, so this fully filled fixture scores 0.95, not 1.0.
        expected_custom = 0.80 * 0.9 + 0.10 * 0.5 + 0.10 * 0.95
````

### 7.17 New file: `tests/test_bf925_event_log_window.py` (M2)

````python
"""BF-925 (#1655) M2: episode anchors count the real EventLog window; scoring holds it out (F12)."""

from __future__ import annotations

import ast
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.anchor_quality import compute_anchor_confidence
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import score_anchor_mismatch, validate_recall_result
from probos.crew_profile import Rank
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.event_log import EventLog
from probos.types import AnchorFrame, Episode, IntentResult

_PROACTIVE = Path(__file__).resolve().parents[1] / "src" / "probos" / "proactive.py"


@pytest.fixture
async def event_log(tmp_path: Path):
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _write_at(log: EventLog, when: float) -> None:
    """One row stamped ``when``. log() stamps the current time, so a past row is written to the table
    directly; its hash-chain columns keep their defaults, which nothing here reads."""
    await log._db.execute(
        "INSERT INTO events (timestamp, category, event) VALUES (?, 'test', 'backdated')",
        (datetime.fromtimestamp(when, tz=timezone.utc).isoformat(),),
    )
    await log._db.commit()


async def test_count_since_counts_the_events_logged_in_the_window(event_log: EventLog) -> None:
    await _write_at(event_log, time.time() - 120.0)
    await event_log.log("test", "now-1")
    await event_log.log("test", "now-2")
    assert await event_log.count_since(time.time() - 60.0) == 2
    assert await event_log.count_since(time.time() - 300.0) == 3
    assert await event_log.count_since(time.time() + 60.0) == 0


async def test_count_since_reads_at_most_cap_rows(event_log: EventLog) -> None:
    for index in range(3):
        await event_log.log("test", f"event-{index}")
    assert await event_log.count_since(0.0, cap=2) == 2
    assert await event_log.count_since(0.0, cap=-1) == 0  # SQLite reads LIMIT -1 as no limit; refused


async def test_count_since_on_an_unstarted_log_is_zero(tmp_path: Path) -> None:
    assert await EventLog(db_path=tmp_path / "events.db").count_since(0.0) == 0


class _Episodes:
    """Stands for EpisodicMemory on the runtime: records what the loop stores. The loop's other
    episodic reads for the context degrade inside their own try blocks."""

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)

    async def count_for_agent(self, agent_id: str) -> int:
        return len(self.stored)


def _silent_agent() -> SimpleNamespace:
    async def handle_intent(intent: Any) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id="agent-bf925", success=True, result="[NO_RESPONSE]")

    return SimpleNamespace(id="agent-bf925", agent_type="counselor", callsign="Troi", handle_intent=handle_intent)


async def test_a_proactive_episode_anchor_records_the_window(event_log: EventLog, monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the real _think_for_agent no-response path and a real EventLog.

    EpisodicMemory.should_store discards no-response episodes, which is why production never stores
    this anchor; the test opens that gate to read the frame the site builds. The runtime is a
    SimpleNamespace, as in test_ad1228_standing_interests.py.
    """
    monkeypatch.setattr(EpisodicMemory, "should_store", staticmethod(lambda episode: True))
    await _write_at(event_log, time.time() - 120.0)  # outside the 60 s window
    await event_log.log("test", "now-1")
    await event_log.log("test", "now-2")
    episodes = _Episodes()
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    loop.set_runtime(SimpleNamespace(episodic_memory=episodes, event_log=event_log))
    await loop._think_for_agent(_silent_agent(), Rank.LIEUTENANT, 0.6)
    assert [episode.anchors.event_log_window for episode in episodes.stored] == [2.0]


async def test_a_failed_window_read_records_zero_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenLog:  # stands for an EventLog whose read fails; the real count_since signature
        async def count_since(self, since: float, *, cap: int = 1000) -> int:
            raise RuntimeError("events.db is locked")

    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    runtime = SimpleNamespace(event_log=_BrokenLog())
    with caplog.at_level(logging.DEBUG, logger="probos.proactive"):
        assert await loop._event_log_window(runtime) == 0.0
        assert await loop._event_log_window(runtime) == 0.0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "BF-925" in r.getMessage()]
    assert len(warnings) == 1


def test_both_proactive_anchor_sites_read_the_window_through_the_helper() -> None:
    """A source pin, with its limit: the thought-episode site stores only without a Ward Room, and the
    loop does not run without one, so no behavioural test reaches it; the no-response site is driven above."""
    tree = ast.parse(_PROACTIVE.read_text(encoding="utf-8"))
    values = [
        ast.unparse(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AnchorFrame"
        for keyword in node.keywords
        if keyword.arg == "event_log_window"
    ]
    assert values == ["await self._event_log_window(rt)"] * 2


def _frame(window: float, thread_id: str = "thread-1") -> AnchorFrame:
    return AnchorFrame(
        duty_cycle_id="duty-1", watch_section="alpha", channel="ward_room", channel_id="ch-1",
        department="science", participants=["Atlas"], trigger_agent="Atlas", trigger_type="duty_cycle",
        thread_id=thread_id, event_log_window=window,
    )


@pytest.mark.parametrize("thread_id", ["thread-1", ""], ids=["with-thread", "without-thread"])
def test_the_confidence_is_the_same_with_a_zero_and_a_real_window(thread_id: str) -> None:
    assert compute_anchor_confidence(_frame(37.0, thread_id)) == compute_anchor_confidence(_frame(0.0, thread_id))


def test_holding_out_keeps_every_score_as_before() -> None:
    """Every stored episode has window 0.0, so its score is the pre-BF-925 formula's: the window was one
    unfilled evidential field of two."""
    assert compute_anchor_confidence(_frame(0.0)) == pytest.approx(0.25 + 0.25 + 0.25 + 0.15 + 0.10 * 0.5)
    assert compute_anchor_confidence(AnchorFrame(thread_id="thread-1")) == pytest.approx(0.10 * 0.5)
    assert compute_anchor_confidence(AnchorFrame()) == 0.0


def test_the_memory_security_verdict_is_the_same_with_a_zero_and_a_real_window() -> None:
    """The mismatch score ignores the window, so the AD-607 verdict cannot depend on it.

    The production query (episodic._AnchorQueryView) has no event_log_window; this query sets one to
    show the gate ignores it even when asked. The 0.05 threshold makes one evidential mismatch (weight
    0.10) an anomaly, as it was before BF-925.
    """
    query = SimpleNamespace(thread_id="thread-1", event_log_window=37.0)
    config = SimpleNamespace(anchor_mismatch_threshold=0.05)
    verdicts = []
    for window in (0.0, 37.0):
        episode = Episode(
            user_input="x", agent_ids=["agent-1"], source="direct", correlation_id="corr-1",
            anchors=AnchorFrame(thread_id="thread-1", event_log_window=window),
        )
        verdicts.append((
            score_anchor_mismatch(episode, query),
            validate_recall_result(episode, anchor_query=query, config=config).allowed,
        ))
    assert verdicts == [(0.0, True), (0.0, True)]


def test_an_episode_stored_with_or_without_a_window_loads() -> None:
    """Through EpisodicMemory's stored shape (anchors_json) and its loader: a real window round-trips,
    and an anchors_json without the key (written before AD-567g) loads with 0.0."""
    episode = Episode(
        user_input="[Proactive thought] Troi: steady", timestamp=time.time(), agent_ids=["agent-1"],
        source="direct", anchors=AnchorFrame(channel="duty_report", event_log_window=4.0),
    )
    metadata = EpisodicMemory._episode_to_metadata(episode)
    assert EpisodicMemory._metadata_to_episode("ep-1", episode.user_input, metadata).anchors.event_log_window == 4.0
    legacy = json.loads(metadata["anchors_json"])
    del legacy["event_log_window"]
    metadata["anchors_json"] = json.dumps(legacy)
    assert EpisodicMemory._metadata_to_episode("ep-1", episode.user_input, metadata).anchors.event_log_window == 0.0
````

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)`. The entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
````markdown
# ProbOS Progress
````
REPLACE:
````markdown
# ProbOS Progress

**BF-925 (2026-10-25), #1655 -- silent-fallback guards name APIs that exist.** Guards on methods no production class defines made features silently empty. The Insights report (`/insights`, `GET /api/insights`) now shows Bridge alerts, the Captain's pending capability and skill requests and completed persistent tasks, and says which sections have no source (topics, crew) or whose source is down (`unavailable`, an additive JSON key). Ward Room @mentions now reinforce the Hebbian social link to the mentioned agent once per post, resolved through the `CallsignRegistry` and the live `AgentRegistry`. Department Chiefs now see subordinates' Ward Room activity (`runtime.ward_room`, `runtime.registry`, by `agent.id`). The AD-572 bridge loses a `list_all` branch that could never run. `EventLog.count_since` counts the newest events in a window; both proactive anchor sites record the last 60 s, held out of anchor-confidence and memory-security scoring until measured (#1523), so no score or verdict changes. A new test fails when a production `hasattr`/`getattr` guard names an attribute no production code defines (allow-list `tests/fixtures/guard_name_allowlist.txt`). New: `tests/test_bf925_silent_guards.py`, `tests/test_bf925_guard_names.py`, `tests/test_bf925_event_log_window.py`. The contract is `prompts/bf-925-silent-fallback-guards.md`.
````

**`DECISIONS.md`:**

SEARCH:
````markdown
### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
````
REPLACE:
````markdown
### BF-925 -- Silent-fallback guards name APIs that exist (2026-10-25, #1655)

- *Insights.* A section reads a real source or says "not available" with its reason; a source that is down or fails says so in its own section. Three are wired (Bridge alerts, the capability and skill request queues, completed persistent tasks); topics and crew are dropped because no store measures what AD-810 named, and relabelling Ward Room post counts as "crew" would report a different measure. The JSON keeps its keys and adds `unavailable`.
- *Mentions.* Resolved through the `CallsignRegistry` the dispatcher binds, the resolver the mention's TaskEvent already uses (it reads the live `AgentRegistry`), not a second resolver; one reinforcement per mentioned agent per post.
- *Chiefs' stats.* Read by `agent.id`, the id posts carry; the sovereign id counted nothing.
- *Event log window.* Filled from the `EventLog` and held out of scoring as an unfilled field, so no score or verdict moves; on the shipped configuration no stored episode carries the anchor (the no-response episode is not stored, the thought episode only without a Ward Room), which is the measurement's first finding (#1523).
- *Guard test.* Receiver-scoped (`self`, `cls`, `rt`, `runtime` and their local aliases) because a name-only rule over every receiver gave 109 hits; it cannot see a name an unrelated class defines (F12's `recent` would have passed). The allow-list holds third-party attributes and registered, untriaged findings.
- *Reversal.* Revert the commits; the report, mention links, Chiefs' stats and window return to empty, and the guard test goes.

### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
````

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-921, BF-923, BF-924 precedent).

**#1655 checklist text** (the orchestrator records it on the issue):
- [ ] (F06) Insights: Bridge alerts, capability and skill requests, completed persistent tasks wired; topics and crew "not available"; a down or failing source "not available"; JSON adds `unavailable` (M1).
- [ ] (F11) @mentions reinforce one social link per mentioned agent per post, through the `CallsignRegistry` and live `AgentRegistry` (M1).
- [ ] (F18) Chiefs read `runtime.ward_room` and `runtime.registry` by `agent.id` (M1).
- [ ] (F13) The `list_all` branch removed; `list_active` plus `get` is the path; seam test on a real `ProcedureStore` (M1).
- [ ] Guard test and allow-list (23 entries: 7 duck, 16 findings registered on #1523) (M1).
- [ ] (F12) `EventLog.count_since`; both anchor sites read it; held out of anchor confidence and memory security; no score or verdict moves (M2).
- [ ] (F12) Measurement row and R1 to R11 posted on #1523.
- [ ] First live session after merge: section 16 recorded on #1655.

## 9. What this does NOT change

- `CounselorAgent._resolve_agent_id_from_callsign`, `CallsignRegistry`, `AgentRegistry`, the AD-654d mention TaskEvent, `threads.py`'s thread-body mentions (no Hebbian link there, R8) and the reply and DM links.
- `WardRoomService.get_agent_comm_stats`, the 3-post threshold, the sensorium and prompt renderers of `subordinate_stats`.
- `BridgeAlertService`, `CapabilityRequestStore`, `SkillRequestStore`, `PersistentTaskStore`, `TaskScheduler`; `commands_insights.py`, `routers/insights.py`; `ui/`.
- `EpisodicProceduralBridge`'s matching, merge and creation (the merge stays unsaved, R2); `dreaming.py`.
- `AnchorFrame`, its persisted shape, `should_store`, the recall weights, the anchor-confidence gate, `_AnchorQueryView`, `validate_provenance`, `OrientationConfig` (its `populate_*` flags stay unread, R6).
- No config field, generated file or count pin.

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7)

Run each row on the applied tree after an unmutated baseline run passes; restore each file before the next row. M1 (STANDARD) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf925_silent_guards.py tests/test_bf925_guard_names.py tests/test_ad810_insights.py tests/test_ad630_leadership_feedback.py -n 0 -x -q
```

M2 (HIGH) command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf925_event_log_window.py tests/test_ad567c_anchor_quality.py tests/test_ad567b_anchor_recall.py tests/test_orientation.py -n 0 -x -q
```

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| M1-1 | 1 | `src/probos/cognitive/insights.py` | `summary=f"{req.kind} {req.target}",` | `summary=req.target,` | `test_the_report_reads_alerts_requests_and_completed_tasks`, `test_build_report_happy_path_aggregates_all_sources` |
| M1-2 | 1 | `src/probos/cognitive/insights.py` | `recent = [a for a in alerts.get_recent_alerts(limit=_ALERT_LOG_READ) if a.timestamp >= since]` | `recent = list(alerts.get_recent_alerts(limit=_ALERT_LOG_READ))` | `test_alerts_outside_the_window_are_left_out` |
| M1-3 | 1 | `src/probos/cognitive/insights.py` | `report.unavailable[name] = "service not running"` | `pass` | `test_a_source_that_is_not_running_reports_not_available`, `test_build_report_empty_state_renders_no_activity_marker` |
| M1-4 | 1 | `src/probos/cognitive/insights.py` | `report.unavailable[name] = f"failed ({type(exc).__name__})"` | `pass` | `test_build_report_failing_source_does_not_blank_other_sources` |
| M1-5 | 1 | `src/probos/cognitive/insights.py` | `report.unavailable.update(_NO_SOURCE)` | `pass` | `test_a_source_that_is_not_running_reports_not_available` |
| M1-6 | 1 | `src/probos/ward_room/messages.py` | `mid = resolved.get("agent_id") if resolved else None` | `mid = None` | `test_a_mention_records_a_social_link_to_the_mentioned_agent` |
| M1-7 | 1 | `src/probos/ward_room/messages.py` | `if mid and mid != author_id and mid not in reinforced:` | `if mid and mid != author_id:` | `test_one_post_reinforces_each_mentioned_agent_once` |
| M1-8 | 1 | `src/probos/ward_room/messages.py` | `reinforced.add(mid)` | `pass` | `test_one_post_reinforces_each_mentioned_agent_once` |
| M1-9 | 1 | `src/probos/proactive.py` | `stats = await rt.ward_room.get_agent_comm_stats(sub_agent.id, since=since)` | `stats = await rt.ward_room.get_agent_comm_stats(sub_agent.sovereign_id or sub_agent.id, since=since)` | `test_a_chief_sees_a_subordinates_ward_room_stats`, `test_chief_gets_subordinate_stats` |
| M1-10 | 1 | `src/probos/proactive.py` | `live = [a for a in rt.registry.all() if a.is_alive]` | `live = list(rt.registry.all())` | `test_a_subordinate_with_no_live_agent_is_skipped` |
| M1-11 | 1 | `src/probos/cognitive/episodic_procedural_bridge.py` | `procedure = await store.get(entry["id"])` | `procedure = None` | `test_the_bridge_merges_a_cluster_a_stored_procedure_covers` |
| M1-12 | 1 | `tests/test_bf925_guard_names.py` | `_OWNED = frozenset({"self", "cls", "rt", "runtime"})` | `_OWNED = frozenset({"self", "cls"})` | `test_a_guard_on_an_undefined_name_is_reported`, `test_production_guards_name_attributes_production_code_defines` (stale `runtime` entries) |
| M2-1 | 2 | `src/probos/substrate/event_log.py` | `"SELECT COUNT(*) FROM (SELECT timestamp FROM events ORDER BY id DESC LIMIT ?) WHERE timestamp >= ?",` | `"SELECT COUNT(*) FROM (SELECT timestamp FROM events ORDER BY id DESC LIMIT ?) WHERE timestamp >= ? OR 1",` | `test_count_since_counts_the_events_logged_in_the_window` |
| M2-2 | 2 | `src/probos/substrate/event_log.py` | `if not self._db or cap <= 0:` | `if not self._db:` | `test_count_since_reads_at_most_cap_rows` |
| M2-3 | 2 | `src/probos/substrate/event_log.py` | `cutoff = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()` | `cutoff = datetime.fromtimestamp(since - 3600.0, tz=timezone.utc).isoformat()` | `test_count_since_counts_the_events_logged_in_the_window` |
| M2-4 | 2 | `src/probos/substrate/event_log.py` | `(cap, cutoff),` | `(cap * 10, cutoff),` | `test_count_since_reads_at_most_cap_rows` |
| M2-5 | 2 | `src/probos/proactive.py` | `return float(await rt.event_log.count_since(time.time() - self._EVENT_LOG_WINDOW_SECONDS))` | `return 0.0` | `test_a_proactive_episode_anchor_records_the_window` |
| M2-6 | 2 | `src/probos/proactive.py` | `_EVENT_LOG_WINDOW_SECONDS = 60.0` | `_EVENT_LOG_WINDOW_SECONDS = 3600.0` | `test_a_proactive_episode_anchor_records_the_window` (`[3.0]`) |
| M2-7 | 2 | `src/probos/proactive.py` | `if not self._event_log_window_warned:` | `if True:` | `test_a_failed_window_read_records_zero_and_warns_once` |
| M2-8 | 2 | `src/probos/proactive.py` | `self._event_log_window_warned = True` | `pass` | `test_a_failed_window_read_records_zero_and_warns_once` |
| M2-9 | 2 | `src/probos/proactive.py` | `logger.warning("BF-925 (#1655): EventLog window read failed; episode anchors record 0.0 (later failures log at DEBUG)", exc_info=True)` | the same with `logger.debug` | `test_a_failed_window_read_records_zero_and_warns_once` |
| M2-10 | 2 | `src/probos/proactive.py` | `event_log_window=await self._event_log_window(rt),  # BF-925 (#1655): no-response episode` | `event_log_window=0.0,` | `test_a_proactive_episode_anchor_records_the_window`, `test_both_proactive_anchor_sites_read_the_window_through_the_helper` |
| M2-11 | 2 | `src/probos/proactive.py` | `event_log_window=await self._event_log_window(rt),  # BF-925 (#1655): thought episode` | `event_log_window=0.0,` | `test_both_proactive_anchor_sites_read_the_window_through_the_helper` |
| M2-12 | 2 | `src/probos/cognitive/anchor_quality.py` | `_EVENT_LOG_WINDOW_HELD_OUT = 0.0` | `_EVENT_LOG_WINDOW_HELD_OUT = 1.0` | `test_holding_out_keeps_every_score_as_before`, `test_all_fields_filled` |
| M2-13 | 2 | `src/probos/cognitive/anchor_quality.py` | `evidential_fields = [anchors.thread_id, _EVENT_LOG_WINDOW_HELD_OUT]  # BF-925: the window is held out` | `evidential_fields = [anchors.thread_id, anchors.event_log_window]` | `test_the_confidence_is_the_same_with_a_zero_and_a_real_window` (2 cases), the five 567b/567c pins |
| M2-14 | 2 | `src/probos/cognitive/memory_security.py` | `"evidential": "evidential",` | `"event_log_window": "evidential",` | `test_the_memory_security_verdict_is_the_same_with_a_zero_and_a_real_window` |

M2-14 re-adds the removed mapping in one line (and drops the generic `evidential` key, which no production query sets). The removed guards cannot be mutated back in one line; the seam tests pin them (no guard is left, so a renamed method raises). M2 is HIGH: every changed M2 line but the docstrings, the comments and the helper's `except`/`else`/`logger.debug` lines has a row.

## 11. Verified Against Codebase (2026-10-25, worktree `bf925-draft` at `72fae2dd`)

```
git log --oneline -1   -> 72fae2dd scratch: predicted BF-925 draft base (BF-924 final oracle state plus the BF-926/927 oracle delta; never pushed)
read insights.py:1-330 -> guards :225-228, :233-236, :248-251, :257-259, :267-269, :282-284; build_report :165-221; _summarize :294-329; to_json :117-140
read commands_insights.py:32-40; routers/insights.py:15-25; runtime.py:3185-3190 (InsightService constructed in start)
grep -n "self\.(bridge_alerts|capability_request_store|skill_request_store|persistent_task_store|ward_room|registry|event_log) *[:=]" runtime.py
  684 registry; 725 event_log; 1091 ward_room; 1100 bridge_alerts; 1120 capability_request_store; 1124 skill_request_store; 1156 persistent_task_store; set 3264, 3266, 3328, 3331, 3335
bridge_alerts.py: 24-28 AlertSeverity; 31-44 BridgeAlert (timestamp time.time); 61-84 __init__ (_max_log 200); 310-347 check_trust_change; 837-839 get_recent_alerts
capability_request.py: 537-555 CapabilityRequest; 686-719 __init__/start; 736-805 file_request (created_at time.time() :777); 1142-1144 list_pending
skill_request.py: 66-82 SkillRequest; 99-126; 148-167 file_request; 356-358 list_pending
persistent_tasks.py: 33-54 PersistentTask; 104-155 __init__/start (tick loop :152-154); 176-244 create_task; 262-281 list_tasks; 441-455 _execute_due_tasks; 536-567 completion
task_scheduler.py: 22-34 ScheduledTask (monotonic), 82-84 list_tasks
messages.py: 21-51 MessageStore (_callsign_registry :42, attach_dispatcher :48-51); 254-289 mention TaskEvent via _callsign_registry.resolve; 417-455 Hebbian block (trow :423-427)
crew_profile.py: 705-707 bind_registry; 709-732 resolve (lowercase, get_by_pool, is_alive); runtime.py:747-749; finalize.py:5589-5590
routing.py: 53-64 defaults (reward 0.05); 177-213 record_interaction; 251-259 get_weight; 361 all_weights_typed
grep -n "author_id=(self\.id|agent\.id)" src/probos -> 14 sites (counselor :2351, cognitive_agent :2269, ward_room_router :833 :894 :1097, ward_room_pipeline :389, proactive :2988 :3575 :3658 :4070 :4162 :4766 :4881 :4930)
proactive.py: 1003-1007 _run_cycle; 1361-1434 no-response path (should_store :1428); 1502 _post_to_ward_room; 1619-1695 thought episode (:1622-1623); 1714 _gather_context; 2365-2387 AD-630 block; 2941-2951 _post_to_ward_room
ontology/service.py:181-201 get_subordinate_agent_types; substrate/registry.py:58-74 get/get_by_pool/all; substrate/agent.py:39 callsign, :44 sovereign_id, :108 is_alive
cognitive_agent.py: 1265-1270 sensorium entry; 9557-9571 renderer; 11108-11120 prompt; sub_tasks/analyze.py:293, compose.py:558
episodic.py: 333-352 _AnchorQueryView; 1520-1549 _security_anomaly_drop; 1907-1958 should_store (:1937-1939); 4323-4365 _episode_to_metadata (anchors_json :4364); 4496-4502 _metadata_to_episode; 4746-4765 score_recall
anchor_quality.py:19-25, :39-51; memory_security.py:52-55, :93-163 (event_log_window :136), :166-204
event_log.py: 30-31 caps; 476 class EventLog; 820-913 query/query_structured; 915-1063 query_governed; 1176-1192 count/count_all; 1233-1260 prune (ISO compare)
episodic_procedural_bridge.py:1-150; procedure_store.py:814 get, :834-883 list_active; startup/dreaming.py:115-121; dreaming.py:1215-1238
tests: test_ad810_insights.py:1-189; test_ad630_leadership_feedback.py:442-547; test_orientation.py:289-301; test_ad567c_*:37-50, :84-89, :228-244; test_ad567b_*:61-74, :93-111, :157-164, :428-453 (A1, on `0bd72a46`); test_ad1228_*:1308-1328; test_bf877_*:622-644
probes (scratch, logs/architect/bf925/, gitignored; this worktree's src first on sys.path, PROBOS_FILE confirmed):
  F13: HAS_LIST_ALL False; LOADED [('p-1', [...], ['diagnose'])]; BRIDGED 0; STORED_AFTER_MERGE provenance unchanged, success_count 0
  F11: resolve('Bones') and ('bones') -> bones-1, ('Nobody') -> None; reply link 0.05; mention link 0.0; '@Bones ... @Bones' dispatched 2 TaskEvents
  F18: get_agent_comm_stats('author-1') posts_total 1; by another id 0
  EventLog: COUNT over newest 1000 with ISO cutoff -> 3 of 3 recent; future cutoff -> 0
  ProbOSRuntime(config=SystemConfig(), data_dir=tmp) unstarted: ward_room/bridge_alerts/capability/skill/persistent/ontology None; registry AgentRegistry; event_log EventLog
  guard scan: 1,067 files, 5,369 guards; name-only 109 hits; + module/except exclusions 72 hits; receiver-scoped 39 hits, 36 (path, name) pairs, ~10 s
```

## 12. Absence Verified (2026-10-25)

```
CLAIM: the issue's names have no production definition
RUN:   rg -n "def (cluster_recall_counts|recent_threads_by_crew|watch_bill|completed_since|consensus_manager|pending_votes|recent_breaches|_resolve_callsign_to_id|recent|list_all|ward_room_service|agent_pool|pending_proposals)\b" src
FOUND: recent only: circuit_breaker_history_store.py:107, clinical_audit_store.py:95, episodic.py:4202, episodic_mock.py:233, self_similarity_history.py:60 (none on EventLog)
RUN:   rg -n "\b(cluster_recall_counts|recent_threads_by_crew|watch_bill|completed_since|consensus_manager|pending_votes|recent_breaches|_resolve_callsign_to_id|ward_room_service|agent_pool|vision_budget)\b" src
FOUND: insights.py:226-284 (each name), messages.py:440,442, proactive.py:2371,2375,2378: callers only
RUN:   rg -n "(runtime|rt|self)\.(vision_budget|thread_store|watch_bill|consensus_manager) *=" src  -> 0
RUN:   rg -n "pending_proposals|^class SelfModificationPipeline" src/probos/cognitive/self_mod.py -> 69 (class line only); pending_proposals is ChainOptimizer's list (chain_optimizer.py:246)
HOLDS: yes; every reader is a guard or a call behind one

CLAIM: EventLog is the only production event log class; no production code sets event_log_window
RUN:   rg -n "class \w*EventLog\w*" src -> event_log.py:476 EventLog; protocols.py:110-188 (spec, row, batch, audit, reader and EventLogProtocol: log/start/stop); config_models/core.py:146 EventLogConfig; tools/event_log_query_tool.py:342 EventLogQueryTool
RUN:   rg -n "event_log_window" src -> types.py:544 (field), proactive.py:1424,1684, anchor_quality.py:44, memory_security.py:136
RUN:   rg -n "event_log_window|eventLogWindow" ui -> 0
HOLDS: yes

CLAIM: no ui/ reader of the Insights report
RUN:   rg -n -i "insights|top_topics|anomaly_windows|pending_decisions|scheduled_tasks_completed" ui/src -> BehavioralMetricsPanel.tsx:37,56 (the word "insights" in two metric descriptions)
RUN:   rg -l "insight_service|InsightService|InsightsReport|commands_insights|/api/insights|cmd_insights" (repo, excluding prompts/archive) -> tests/test_ad810_insights.py, runtime.py, routers/insights.py, shell.py, commands_insights.py, insights.py
HOLDS: yes

CLAIM: no procedure store defines list_all; the bridge's only store is ProcedureStore or None
RUN:   rg -n "list_all" src -> episodic_procedural_bridge.py:84,85; commands_clearance.py:201 (a BF-924 comment)
RUN:   rg -n "EpisodicProceduralBridge\(" src -> startup/dreaming.py:117 (procedure_store=procedure_store)
HOLDS: yes

CLAIM: the proactive thought episode block cannot store on a running loop
RUN:   read proactive.py:1003-1007 (_run_cycle returns without rt.ward_room), :1622-1623 (stores only when not wr_available), :1502 + :2941-2951 (_post_to_ward_room calls rt.ward_room.list_channels() before it)
HOLDS: yes (direct _think_for_agent calls without a Ward Room raise at :2951 first)

CLAIM: the OrientationConfig populate_* flags have no reader
RUN:   rg -n "populate_\w+" src/probos -> config_models/knowledge.py:373-375 (definitions); no reader (other hits are unrelated names)
HOLDS: yes (R6)

CLAIM (A1): every test that sets a non-zero event_log_window is in the M2 focused list, so that run measures every expectation the hold-out could move
RUN:   rg -n "event_log_window" tests -> test_ad567a_*:41 (construction; :51 reads the field), test_ad567b_*:73, test_ad567c_*:49, :329, test_ad567d_*:54, test_ad577_*:50 (construction only), test_ad584c_*:50, test_ad590_*:52, test_ad591_*:51, test_orientation.py:297; test_ad1270e2f_*:199 is the populate_event_log_window config key (R6), not an anchor
RUN:   rg -l "_full_anchor|full_anchor" tests -> also test_ad605_enhanced_embedding.py:35 (sets no window), test_ad663_*:195 (a local name, no score)
RUN:   (orchestrator, 2026-10-25, M2 oracle a8148c5e) the 16-file focused list -> 1 failed (test_ad567b_*:452), 520 passed, 0 skipped
HOLDS: yes after A1; :452 was the only exact expectation the shift moved

CLAIM: guard-scan hits on this tree (receiver-scoped rule, D6), 36 (path, name) pairs
FOUND (the five items, 13): insights.py cluster_recall_counts, thread_store, recent_threads_by_crew, watch_bill, completed_since, consensus_manager, pending_votes, vision_budget, recent_breaches; episodic_procedural_bridge.py list_all; proactive.py ward_room_service, agent_pool; ward_room/messages.py _resolve_callsign_to_id
FOUND (allow-list, 23): §7.9, 7 duck and 16 finding
HOLDS: yes; M1 removes the 13, M2 adds no guard
```

## 13. Prior Art and Blind Spots

- Bug fix in ProbOS plumbing; no external search, `docs/research/reference-projects.md` not consulted. The guard test's analogues were weighed on the merits: a type checker's attribute checks (the guarded seams are typed `Any`, so they see nothing here) and dead-code finders such as vulture (they find unused definitions, not guards on missing ones); an AST name scan fits. Internal: AD-810, AD-453, AD-630, AD-567a/c/g, AD-572, AD-607, AD-654d, BF-921 (resolver), BF-039 (the thought episode), BF-877 (the task tick in tests).
- Blind spots addressed: the sixth Insights guard (`pending_proposals`); the narrative LLM call that starts running (E1b); the subordinate id form (D4); the proactive anchors that never reach storage (section 0, D5); the merge that is never saved (R2); a scanner rule that would have missed F12 itself (D6, R9); the MagicMock that invents attribute names (the runtime-attribute pin).
- Considered, deferred: a crew-activity and a topics source (R7); filling the window on Ward Room episodes (R5); one callsign resolver (R10).

## 14. Diff Reviewer: properties to verify

1. Every Insights section either has rows from a real store or an entry in `unavailable` with its reason; a source that raises marks only its own section and logs one WARNING; `to_json` has every earlier key plus `unavailable`; topics and crew are always `[]` with their no-source reasons.
2. The wired sections are bounded: at most 20 alerts (from the newest 200, inside the window, newest first), 20 requests per queue (oldest first), and completed tasks from the newest 200 inside the window; nothing is written.
3. A Ward Room post reinforces at most one social link per mentioned live agent, never the author, never an unknown callsign, never the thread author twice; the resolver is the one the mention's TaskEvent uses; nothing else in `create_post` changes.
4. A Chief's subordinate stats are read from `runtime.ward_room` for the first live agent of each subordinate type, by `agent.id`; the threshold and rendering are unchanged.
5. The bridge loads procedures only through `list_active` and `get`; matching, merging and creation are unchanged.
6. The guard test scans this checkout's `src` by AST, imports nothing, fails on a guard not allow-listed and on a stale entry, and every allow-list line has a path, a name, a kind and a reason.
7. `EventLog.count_since` reads at most `cap` newest rows, counts those at or after `since`, returns 0 before start and for a non-positive cap, and writes nothing.
8. Both proactive anchor sites read the window through one helper that never raises: 0.0 on failure, one WARNING per loop then DEBUG.
9. For every `AnchorFrame`, `compute_anchor_confidence` and the AD-607 verdict are identical for any `event_log_window`, and equal to their values at 0.0 before this change.
10. The persisted episode shape is unchanged; a stored 0.0 and a missing key both load.
11. Every replaced double or pin says inline what it masked; no test was deleted; no config field, generated file or count pin changed.

## 15. Acceptance criteria

- Through the real `InsightService` on a real `ProbOSRuntime` with real stores: alerts, requests and completed tasks appear; topics and crew read "not available"; a stopped or failing source reads "not available".
- Through a real `WardRoomService`, `HebbianRouter`, `AgentRegistry` and `CallsignRegistry`: a mention records one social link; repeats, self-mentions, unknown callsigns and agents that are not alive record none.
- Through `_gather_context` with a real `WardRoomService` and `AgentRegistry`: a Chief sees a subordinate's post count by `agent.id`; the attribute names exist on a real `ProbOSRuntime`.
- Through a real `ProcedureStore`: a covered cluster is merged, a novel one bridged.
- The guard test passes at the M1 and M2 stages and fails in both directions.
- Through a real `EventLog` and `_think_for_agent`: the anchor records the 60 s count; confidence and the AD-607 verdict are identical for a zero and a real window; stored episodes load.
- Before editing, the pins were grepped, and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance (read-only)

After the first session on the merged build, record on #1655: one `/insights` output (expected the wired sections, and the "Not available" line); the count of `BF-925 (#1655): EventLog window read failed` lines (expected 0); from `hebbian_weights.db` (read-only), the count of `social` rows against the last session before the merge (expected higher); from the vessel log, one Chief's proactive context containing `<subordinate_activity>` if any subordinate posted 3 times. Then the #1523 measurement row's first reading: the count of stored episodes whose `anchors_json` has `event_log_window > 0` (expected 0).

## 17. Not verified

- **The new tests were written in a drafting run and not run.** Measured by scratch probes (section 11): the scan counts, the F13 premise, the F11 base weights, the post id form, the EventLog comparison, the unstarted runtime's attributes. Not measured: that `_gather_context` completes on a MagicMock runtime holding a real `WardRoomService` (its Ward Room activity section now reaches the real service); that `_think_for_agent` on `SimpleNamespace(episodic_memory, event_log)` reaches the no-response store with `should_store` opened; that the task store's first tick runs before the test creates its task (the fixture's later awaits yield to it); that `log()` chains correctly after a backdated row with an empty `row_hash`; that no other proactive test that reaches the no-response site with a MagicMock runtime asserts there is no WARNING (the helper warns once).
- (Measured 2026-10-25: section 5's "expected unchanged" row held except `test_ad567b_*:452`, now pinned by A1.)
- The 16 `finding` entries are untriaged: each is "no production definition" by the scan's rule, not a confirmed defect. The `duck` reasons are not verified against the third-party packages.
- **Which source the tests import:** run with `PYTHONPATH` set to the scratch tree's `src` (the venv's editable install points at `D:\ProbOS\src`).
- Live: that `ward_room.enabled` is true in the Captain's operator `system.yaml` (tracked `config/system.yaml:913-914`; the model default is False, `config_models/crew.py:279`).

## 18. For the register (#1523; found here, not fixed by this change)

- **R1.** 16 production guards name an attribute no production code defines (the `finding` lines of `tests/fixtures/guard_name_allowlist.txt`); each needs triage: wire, remove, or reclassify as duck typing (and edit the allow-list).
- **R2.** AD-572's cross-cycle merge is never persisted: `_merge_cross_cycle` (`episodic_procedural_bridge.py:72-77`) mutates a loaded copy; only new procedures are saved (`dreaming.py:1223-1235`). Measured. Saving merged provenance is a dream-time write with its own review.
- **R3.** `proactive.py:1619-1695` (the thought episode) cannot store on a running loop (section 12).
- **R4.** `proactive.py:1405-1429` builds a no-response episode that `should_store` always discards (`episodic.py:1937-1939`); since BF-925 it also costs one bounded `EventLog` count per no-response think.
- **R5 (measurement, F12).** `AnchorFrame.event_log_window` is counted from the EventLog at both proactive anchor sites and held out of anchor-confidence and memory-security scoring. *Measure*, read-only, after one live session: the count of stored episodes whose `anchors_json` has `event_log_window > 0`, by channel (expected 0: neither site's episode is stored, R3, R4; Ward Room episodes, where a proactive post's episode is made, do not set it). *Decision it enables:* if 0, wire a persisting producer (the Ward Room thread and post episodes, which needs the EventLog in `WardRoomService`) or drop the field; if above 0, compare its distribution between the episodes recall keeps and drops, then decide whether to score it.
- **R6.** `OrientationConfig.populate_watch_section`, `populate_ward_room_department`, `populate_event_log_window` (`config_models/knowledge.py:373-375`) have no reader (for BF-926+927's reader report if it does not list them).
- **R7.** Insights topics and crew have no source; a crew-activity source (Ward Room posts per author, chat-session volume) and a topic source are design. Other approval queues (permission cards, delegated approvals, self-improvement proposals) are not in "pending decisions".
- **R8.** Thread-body @mentions (`ward_room/threads.py:512-534`) dispatch TaskEvents but record no Hebbian link; a callsign repeated in one post dispatches one TaskEvent per repeat (measured: 2).
- **R9.** The guard test's rule cannot see a guard whose name an unrelated production class defines (F12's `recent`; `pending_proposals`) or a guard on a parameter; a typed check would need annotations at these seams.
- **R10.** Two callsign resolvers: `CounselorAgent._resolve_agent_id_from_callsign` (case-sensitive `agent.callsign` scan, 4 callers) and `CallsignRegistry.resolve` (case-insensitive type map). One resolver is a DRY refactor.
- **R11.** `tests/test_proactive.py:150` and `tests/test_ad635f_clinical_proactive_context.py:40-41` still set `ward_room_service` / `agent_pool` on MagicMock runtimes; harmless and dead.
