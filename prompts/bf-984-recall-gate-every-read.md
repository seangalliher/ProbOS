# BF-984 (#1830): AD-607's recall verdict runs on every public read of episodic memory but eight exempt ones, and `probos rebuild-episodic` binds the memory gates as startup does

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Verified by:** the orchestrator, 2026-11-20: every pair and every check of section 15 was run on an oracle tree before the Builder started (section 16). The orchestrator added pair RP1 (7.10), the one-row update of `docs/research/reference-projects.md` that the Architect's answer left to the caller; that file joins the file list of section 10 and the M3 milestone.

**Status:** build-ready, pending the orchestrator's checks on an oracle tree (section 15). Issue #1830. The PR body says `Refs #1830`. The number BF-984 is the one in the issue title, and AV7 shows no collision. The number appears only in REPLACE text, new-file text, new-file paths and tracker text. It appears in no SEARCH block except the tracker substrings in TR2, TR4 and TR5, which quote text that already names #1830.

**Base:** `d57631f6`, the merge of PR #1842 (BF-991). Its tree is `6042baae`. Build on `origin/main`. If main has moved, check first that every SEARCH block below still matches exactly once (check O2).

**Line endings:** the working copies are CRLF (`git ls-files --eol` gives `i/lf w/crlf` for `episodic.py`, `cognitive_services.py`, `__main__.py`, `tests/test_ad819_rebuild_episodic.py`, `PROGRESS.md` and `DECISIONS.md`). The SEARCH blocks below are LF. Match and write each file in its own line endings. Write the two new test files with LF.

**Milestones** (each is one Builder delegation of at most about 150 tool calls and one local commit, in order; **the Builder does not commit**; the orchestrator commits by plumbing; no commit subject in the PR carries an `AD-` or `BF-` token):
- **M1** (tier HIGH; **the shared-contract change**: a gate on every read path of `EpisodicMemory`, security class):
  1. Write `tests/test_bf984_recall_gate_coverage.py` (7.1) on its own, run it, and record the base column of section 6.
  2. Apply EP1 to EP7 (`episodic.py`).
  3. Run the M1 focused gate.

  Review plan: the full Diff Reviewer plus the Copilot GPT Diff Reviewer, because this is a security change. A repair round that changes the helper, its placement or `_EXEMPT` re-reviews the whole M1 diff.
- **M2** (tier MEDIUM: startup's binding moves into a helper with the same behaviour, and an operator command gains its gates):
  1. Write `tests/test_bf984_rebuild_binding.py` (7.2) and record its column.
  2. Apply CS1 and CS2, MN1 to MN3, then TA1.
  3. Run the M2 focused gate.
- **M3** (tier LOW): the trackers TR1 to TR5, the reference-projects row RP1 (7.10), then the ledger (7.9).

Suggested subjects:
- M1: `Apply the memory recall check on every episode read, with the exempt reads listed and tested`
- M2: `Bind the rebuild command's memory gates through the helper startup uses`
- M3: `Record the recall check coverage in the status and decisions entries`

After M3, run one broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-984-1830 --receipt logs/gates/bf-984-1830.receipt.json`.

**Captain:** no Captain condition applies. The change strengthens a security control. No `enforce_*` default changes, and by default the verdict only reports. It adds no spend path, schema, boundary or flag, and it reverts by reverting its commits. Decided in consult `54da016e` and recorded on #1830.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| The verdict returns `False` when no config is bound. It emits `MEMORY_RECALL_ANOMALY` and then `MEMORY_PROVENANCE_GAP`. It drops on `enforce_provenance`, emits `MEMORY_ANCHOR_MISMATCH`, drops on `enforce_recall`, and fails open at DEBUG | `src/probos/cognitive/episodic.py:1534`, `:1545-1547`, `:1561`, `:1569`, `:1573-1574`, `:1576-1580`, `:1582-1584`, `:1585-1587` |
| Its four call sites | `:3540` (`recall_with_confidence`'s dense loop), `:3631` (`_fuse_dense_sparse` hydration), `:5057` (`recall_weighted`, after budgeting), `:5280-5281` (`recall_by_anchor`) |
| `_emit_security_event` has no dedupe, and its failure is swallowed | `:1516-1532` |
| `validate_recall_result` never reads `query`. Anomalies come from provenance, plus an anchor mismatch only when an anchor view is passed | `src/probos/cognitive/memory_security.py:188-226` (read whole) |
| The config, gate and emitter are initialised to `None`. The setters are at the second citation | `episodic.py:1477-1479`; `:1496-1514` |
| AD-1293's shared exclusion is applied at the end of each evidence read and classified by call site | `:3401-3432` |
| `recall_for_agent` is a shim. `recall_for_agent_with_confidence` has a dense loop with no verdict, sovereign fusion, then AD-1293's exclusion and a band reset | `:3898-3913`; `:3971-4007`, `:4050-4053`, `:4055-4060` |
| Sovereign fusion hydrates sparse-only ids unfiltered | `:4105-4108` |
| `recent_for_agent` filters after the k-cap; `recall_by_intent`; `recent` | `:4132-4180` (`:4177-4180`); `:4182-4223`; `:4225-4253` |
| `retrieve_contrastive_episodes`: its exclusion, then the `CONTRASTIVE_RECALL` emit | `:3684-3749` (`:3729-3733`, `:3735-3748`) |
| `get_by_ids`: the bare call is unfiltered (history); `for_evidence=True` applies the exclusion | `:2371-2421` (`:2419-2421`) |
| Evidence callers pass `for_evidence=True` | `proactive.py:2194-2197`, `diagnostic_context.py:311-313`, `procedure_challenger.py:614` |
| `recall_weighted` gets its dense pool from `recall_for_agent_scored` (`:4866`) and gates after budgeting (`:5049-5062`). Nine test files replace `recall_for_agent_scored` with a stub | `tests/test_ad590*`, `test_ad591*`, `test_bf155*`, `test_ad579b*`, `test_ad584c*` and others (grep) |
| The exempt candidates' own docstrings | `list_episodes` `:2298-2305` (AD-689 backfill); `iter_live_episodes` `:2331-2334` ("a service read, not a recall surface"); `iter_archived_episodes` `:3021-3024`; lookups `:3056-3078` ("Not a recall surface"); `restore_from_archive` `:3080-3098`; `score_recall` `:4741-4742` (`@staticmethod`) |
| Startup binds AD-610 only `if config.storage_gate.enabled` (wrapped), and AD-607 unconditionally (not wrapped) | `src/probos/startup/cognitive_services.py:313-328`, `:330-340` |
| The only production setter calls | `cognitive_services.py:322`, `:337-339` (AV1) |
| The rebuild command builds its memory at `:2299-2308` and starts it at `:2309`. Its comment says the gates fire. Its config comes from `_load_config_with_fallback` | `src/probos/__main__.py:2217`, `:2290-2294`, `:2298`; `:516-519` |
| The runtime's memory is built inside `_boot_runtime` | `__main__.py:567`, `:619` |
| `StorageGate(config, emit_event_fn=None)`; `StorageGateConfig.enabled` defaults to `True` | `cognitive/storage_gate.py:37-42`; `config_models/cognition.py:359` |
| Every `enforce_*` flag defaults to `False` | `config_models/crew.py:155-159` |
| Rebuilt episodes carry `source="wardroom_import"` and stable ids. `episodes_written` counts store calls | `maintenance/rebuild_episodic.py:140-146`, `:158-164`; `:226-228` |
| The prompt recall (`_recall_relevant_memories`): its crew check, tier resolution, weighted branch, basic branch, fallbacks, and the observation key `recent_memories`, inside the BF-138 `except` | `cognitive_agent.py:11579`, `:11596-11598`, `:11724-11752`, `:11814-11841`, `:11842-11849`, `:11876-11883`, `:12132`, `:12149-12151` |
| Basic tier `use_salience_weights=False`; rank from trust; ensign maps to `BASIC`, lieutenant to `ENHANCED`; `TRUST_LIEUTENANT = 0.5` | `episodic.py:1212`, `config.py:1112-1119`; `crew_profile.py:38-47`; `earned_agency.py:61-68`, `:111`; `config.py:218` |
| Anchor recall runs only on an anchor signal; `scout` is crew without an ontology | `cognitive_agent.py:12464-12466`; `crew_utils.py:58-59`, `:69-76` |
| BF-938's R1 asserts exactly one `[_FORGED]` per event type for one weighted read | `tests/test_bf938_ad607_recall_gate.py:121-122` |
| BF-938's B4 AST guard looks for calls on a receiver named `episodic_memory` anywhere in `cognitive_services.py` | `tests/test_bf938_ad607_binding.py:170-181` |
| The AD-607 events are grandfathered without a persistence class | `event_persistence.py:298-302`; BF-938 G4 |
| **Measured (the orchestrator's probe `probe_b984_premise.py`, premises asserted)** | Bound with `enforce_provenance` armed, the forged episode is returned with no event by `recall_for_agent`, `recall_for_agent_with_confidence`, `recall_for_agent_scored`, `recall_by_intent`, `recent_for_agent`, `recent`, `list_episodes`, `get_by_ids` and `iter_live_episodes`. `recall`, `recall_with_confidence`, `recall_with_control` and `recall_weighted` drop it with 2 events each. The rows for `recall_by_anchor(_scored)`, `retrieve_contrastive_episodes` and `iter_archived_episodes` were inconclusive (an empty result even unbound), and `recall_valid_at` was skipped. The orchestrator's AST call graph found 21 public episode-, score- or outcome-returning methods, 7 of which reach the verdict |

## 1. Problem

**G8.** AD-607's recall verdict (`_security_anomaly_drop`) runs in semantic, weighted and anchor recall only.
- With `enforce_provenance` armed, these reads return an episode whose source ProbOS never writes, with no event:
  - per-agent recall (`recall_for_agent`, `recall_for_agent_with_confidence`);
  - the recency reads (`recent_for_agent`, `recent`);
  - intent recall (`recall_by_intent`);
  - contrastive recall;
  - an evidence caller's `get_by_ids(for_evidence=True)`.
- The probe measured this for each of those it could reach (section 0). The others are measured by section 6's base column.
- The crew's prompt recall uses `recall_for_agent` at the basic tier (`cognitive_agent.py:11842-11849`). When weighted recall returns nothing, it falls back to `recall_for_agent` and then to `recent_for_agent` (`:11876-11883`). So an episode the weighted gate dropped comes back through the fallback.
- The dream cycle reads through `recent` and `recall_by_intent` (`dreaming.py:248`, `:388`, `:475`, `:1424`, `:1876`).

**G1.** `probos rebuild-episodic` builds its own `EpisodicMemory` and calls no setter (`__main__.py:2299-2309`). Its comment says the AD-610 and AD-607h gates fire (`:2290-2294`). A rebuilt Ward Room post that matches an injection pattern is therefore stored even with `enforce_store` armed.

**Why the tests passed.**
- BF-938's tests cover the weighted and semantic reads and the startup binding.
- Nothing enumerated the reads or the constructions.

## 2. Solution overview

1. **One list filter**, `EpisodicMemory._drop_security_anomalies(episodes, *, query="", anchor_query=None)`, sits next to the verdict.
   - Unbound, it returns the list unchanged.
   - Bound, it keeps each episode the existing per-episode verdict does not drop.
   - Six reads call it once, on the list they are about to return, after AD-1293's exclusion: `recall_for_agent_with_confidence` (and through it `recall_for_agent`), `recent_for_agent`, `recent`, `recall_by_intent`, `retrieve_contrastive_episodes`, and `get_by_ids` on its `for_evidence=True` branch.
   - The seven reads that already reach the verdict are unchanged.
2. **An allowlist with reasons** lives in the new test file. An **AST enumeration** fails on any public method whose return annotation names `Episode`, `RecallScore` or `ArchiveLookupResult` and that neither reaches the verdict through `self` calls nor is on the allowlist. It also fails on a stale allowlist entry.
3. **G1:** `bind_episodic_memory_gates(episodic_memory, config, emit_event_fn)` in `startup/cognitive_services.py` holds startup's two binding blocks unchanged.
   - `init_cognitive_services` calls it.
   - The rebuild command calls it inside its `try`, passing `_log_rebuild_memory_event`, which logs each event's type and episode id at WARNING.
   - The rebuild's comment is corrected.

**Heavier designs, rejected:**
- *The verdict inside `_metadata_to_episode`.* It would also filter erasure, export and the Captain's audited reads, which must see every row.
- *Checks only at the prompt recall and the dream cycle.* A new caller would bypass them again.
- *A ChromaDB `where` predicate on the source.* A predicate in the query would refill the result. But the default mode must report an episode and keep it, which a query predicate cannot do, and `missing_agent_ids` sits inside a JSON field.
- *Gating `recall_for_agent_scored` itself.* `recall_weighted` would then report each anomalous episode twice, which breaks BF-938's R1 (exactly one report per read). Making the step private would break the stubs in nine test files.
- *A per-process event dedupe.* See D3.

## 3. Decisions

**D1. The helper's shape.**

| Rank | Option | Verdict |
|---|---|---|
| 1 (chosen) | One private list filter over the existing per-episode verdict, a method next to `_security_anomaly_drop`. It takes `query`/`anchor_query` keyword arguments and passes them through. It is called once per read, on the final list | Every gated read returns `list[Episode]` (or a tuple whose list is that). The exempt reads cover the iterator, single-episode, pair and score shapes, so no second helper is needed |
| 2 | One helper per return shape (list, tuple, iterator, single episode) | Three of the four would have no caller |
| 3 | Per-candidate calls inside each loop, as BF-938 did | Two sites per read where fusion hydrates. It also needs its own band recompute in agent recall |

- **Placement.** The filter goes after `_drop_self_contradicted`, so it checks only what the read returns. In agent recall it goes before the band reset (`if _pre_exclusion and not episodes`), so an enforced drop that empties the recall reports band `none`, as AD-1293's exclusion already does. In contrastive recall it goes before the `CONTRASTIVE_RECALL` report.
- **Arguments.** `query` is passed where the read has one. It changes no verdict today (`memory_security.py:188-226`), and is passed for the day it does. No read here passes an anchor view, so the new reads judge provenance only.
- **Unchanged.** `store` and the seven reads that already reach the verdict keep their code. No `enforce_*` default changes. `getattr(self, "_security_config", None)` is used because test modules build the memory with `__new__` (`:3423-3426`).

**D2. The allowlist.** Classification of the 22 public reads (the orchestrator's 21, minus `store`, plus the two archive lookups, whose return type `ArchiveLookupResult` carries episodes; `episode_archive.py:236-247`):

| Read | Class | Reason |
|---|---|---|
| `recall`, `recall_with_confidence`, `recall_with_control`, `recall_weighted`, `recall_valid_at`, `recall_by_anchor`, `recall_by_anchor_scored` | gated (already) | BF-938 |
| `recall_for_agent` (through `recall_for_agent_with_confidence`), `recall_for_agent_with_confidence`, `recent_for_agent`, `recent`, `recall_by_intent`, `retrieve_contrastive_episodes` | **gated (new)** | They feed prompts, the dream cycle and decisions |
| `get_by_ids` | **gated on `for_evidence=True`** | AD-1293's call-site rule. The bare call is history: erasure (`erasure.py:594`), a liveness check (`continuous_promotion.py:52`), and the fusion tails, which gate what they hydrate |
| `list_episodes` | exempt | Maintenance: AD-689's edge backfill walks every row once (#1820 bf-984 F1) |
| `iter_live_episodes`, `iter_archived_episodes` | exempt | Erasure must see every row |
| `lookup_archived_by_id`, `lookup_archived_by_agent` | exempt | The Captain's audited archive reads (AD-1340 S2a) |
| `restore_from_archive` | exempt | The Captain's audited restore of one row; every later read of it is gated |
| `score_recall` | exempt | A pure scorer of an episode its caller holds |
| `recall_for_agent_scored` | exempt | An internal step. `recall_weighted` gates its merged, budgeted pool. A4 asserts that `recall_weighted` is its only production caller |

`store` returns `EpisodeStoreOutcome`, so the predicate does not select it: it is a write, gated by AD-610 and AD-607h.

What the enumeration asserts (A1 to A4):
- (a) It parses the `EpisodicMemory` class in `episodic.py`.
- (b) A *read* is a public method whose return annotation (an AST walk, including string annotations) names `Episode`, `RecallScore` or `ArchiveLookupResult`.
- (c) A read is *gated* if a breadth-first walk over `self.<name>(...)` calls reaches `_security_anomaly_drop`.
- (d) Each read is gated xor in `_EXEMPT`.
- (e) Every `_EXEMPT` key is a read and every reason is non-empty.
- (f) Controls: `recall` reaches the verdict through its delegate and `recall_weighted` directly; `list_episodes` does not; `store`, `get_episode_metadata` and `keyword_search` are not selected; and no public method lacks a return annotation.

It is keyed by method names, never by line numbers.

**D3. The event policy for the newly gated frequent reads.**

| Rank | Option | Price |
|---|---|---|
| 1 (chosen) | **Keep BF-938's behaviour: report on every read.** The filter runs on the returned, k-capped list, so a read reports only episodes it returns: at most two events per returned anomalous episode, since no anchor view is passed | Volume is reads x flagged episodes returned. BF-938 measured 14,766 events in the busiest hour when 1,224 of 1,227 episodes were flagged, through the three gated paths, against `SYSTEM_EVENTS`' 50,000-message window (`DECISIONS.md:2133`). It measured 0 once `wardroom_import` was admitted |
| 2 | Dedupe by (episode id, event type) per process, with a bounded LRU | It changes the event contract the seven gated reads already have and the counts AD-607j would take; it adds state and mutation rows; restarts re-emit |
| 3 | Gate before the k-cap (full scan) | Volume per read grows with the store size, not with k |

Why option 1:
- The realistic way to flag many episodes at once is a producer writing an unadmitted source, and CI already blocks that: `tests/test_bf938_episode_source_guard.py` fails on any `Episode(` construction with an unknown source.
- What remains is injected or peer episodes, which are rare by design.
- R4 pins the per-read bound.
- **What would change this decision:** a census, on a copy of the live store, with flagged episodes, or AD-607j's counter showing the recency reads near the window. Item bf-984 F4 holds that trigger.

**D4. G1: the shared binding.**
- `bind_episodic_memory_gates(episodic_memory: Any, config: SystemConfig, emit_event_fn: Callable[..., Any] | None) -> None` goes in `startup/cognitive_services.py`, next to `wire_erasure_sidecar_paths`, the same kind of helper.
- It binds AD-610's `StorageGate` only when `config.storage_gate.enabled`, wrapped (log-and-degrade, as now). It binds AD-607's config, `MemorySecurityGate` and emitter unconditionally and unwrapped (BF-938 D5).
- Its parameter is named `episodic_memory`, so BF-938's B4 guard still finds the setters.
- **The emitter for the rebuild:**
  1. (chosen) `_log_rebuild_memory_event`, a module function in `__main__`, logs `rebuild-episodic: <event> for episode <id>` at WARNING. It never logs the text, the matched pattern or the reason. It is module-level so B4 can replace it with a recorder.
  2. `None`: the AD-607h REJECT already logs a WARNING (`episodic.py:2131-2135`), but report-only events would be silent.
  3. A counted line in the report: it changes `render_report`, which is out of scope.
- **Consequence, disclosed:** with the default config (`storage_gate.enabled=True`), the AD-610 gate now runs on rebuilt episodes, as the comment always said. The report still counts a skipped episode as written (#1820 bf-984 F5).

**D5. The seam test.**
- **Construction:** a real `CognitiveAgent` through `_recall_relevant_memories`, built as `tests/test_ad1357_context_manifest.py:135-144` builds it, with a `SimpleNamespace` runtime holding a real `SystemConfig` and a real ChromaDB-backed memory.
- The tier comes from the production BF-263 path: a one-score trust stub, where 0.1 gives an ensign (`BASIC`) and `TRUST_LIEUTENANT` gives a lieutenant (`ENHANCED`). The private function is not extracted, because extracting it is what hid the half-chain.
- **Premise lines:**
  - the trust score gives the expected rank;
  - the query has no anchor signal, so no anchor recall runs;
  - unbound, the forged memory reaches `recent_memories`;
  - the basic tier makes no `recall_weighted` call and the enhanced tier does.
- **What it pins:**
  - bound and armed, `recent_memories` is absent;
  - the last fallback, `recent_for_agent`, ran exactly once;
  - the verdict reported the forged id;
  - no BF-138 warning was logged, so recall did not fail.

**D6. Contrastive recall in the tests.** AD-655's band is a similarity of [0.4, 0.65] (`:3712-3720`). A proxy over the real collection sets every query distance to 0.5. The episodes, the metadata and the verdict stay real. The probe's empty row came from that band.

**D7. Roadmap: no row.** The Bug Tracker lists only open bugs that are filed and deliberately not fixed (`docs/development/roadmap.md:1139`).

**D8. Ledger: the offline generator** (`-P scripts/gen_ad_ledger.py`), as in BF-987, BF-990 and BF-991.

## 4. Milestones and focused gates

**M1 focused gate:**
`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf984_recall_gate_coverage.py tests/test_bf938_ad607_recall_gate.py tests/test_bf938_ad607_binding.py tests/test_bf938_mock_episodic_binding.py tests/test_bf938_episode_source_guard.py tests/test_ad607_memory_security.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_ad1357_context_manifest.py tests/test_ad981a_recall_fok_logging.py tests/test_ad981b_recall_confidence_gating.py tests/test_ad981c_sovereign_hybrid.py tests/test_ad979a_recall_confidence.py tests/test_ad657_trace_exemplars.py tests/test_ad689_edge_backfill.py tests/test_bf905_erasure_live_scan.py -q -n 0`

**M2 focused gate:**
`d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf984_rebuild_binding.py tests/test_ad819_rebuild_episodic.py tests/test_bf938_ad607_binding.py tests/test_bf938_mock_episodic_binding.py tests/test_bf938_episode_source_guard.py tests/test_ad610_storage_gating.py tests/test_storage_gate_owner_scope.py tests/test_ad1341_s1_promotion.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_store_census.py -q -n 0`

**M3:** after TR1 to TR5, run 7.9's generator, then `--check`, then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

## 5. Consumers of every value this changes

| Changed | Consumer | Expectation |
|---|---|---|
| EP2: agent recall | The prompt recall (`cognitive_agent.py:11844`, `:11881`); `proactive.py:2071`, `:2087`; `recall_for_agent` callers (9 sites in 7 files); the AD-979d probe (`_recall_confidence_probe`) | Unbound or report-only: the same list (R3). Armed: the forged episode is left out, and band `none` when the recall is emptied (R5) |
| EP3/EP5: `recent_for_agent`, `recent` | The dream cycle (`dreaming.py:248`, `:388`, `:475`, `:1424`); the proactive loop (`proactive.py:2122`); `/memory` (`commands_memory.py:34`); the memory graph (`routers/memory_graph.py:198`, `:205`); SIF (`sif.py:426`); federation (`representative_queries.py:85`); captain's log; stand-down; after-action; qualification tests | Unchanged unless a flag is armed. Armed: a provenance-gap episode is left out, shortening the result (bf-984 F3). The Captain's views are among them (F2) |
| EP4: `recall_by_intent` | `dreaming.py:1876` (procedure evolution) | The same |
| EP6: contrastive | `sub_tasks/evaluate.py:452` | The same. `CONTRASTIVE_RECALL` names only what is returned |
| EP7: `get_by_ids(for_evidence=True)` | `proactive.py:2194`, `diagnostic_context.py:311`, `procedure_challenger.py:614` | The same. Armed, the challenger's `_contexts` returns `None` when every comparison episode is forged ("unreadable this cycle", `:622-623`); the challenger then expires after `procedure_challenger_max_pending_cycles` (`:605-607`) |
| CS1/CS2: the startup binding | `init_cognitive_services`; `MockEpisodicMemory` boots | Same calls, order and exception tiers. BF-938's B1 to B6 and B7 stay green |
| MN1 to MN3: the rebuild | Operators; `tests/test_ad819_rebuild_episodic.py::TestShutdownMarkerReset` | `_FakeEM` gains the setters (TA1). By default AD-610 now runs on rebuilt episodes (F5) |

## 6. Tests

**`tests/test_bf984_recall_gate_coverage.py`** (40 cases):

| # | Name | Asserts |
|---|---|---|
| A1 | `test_the_enumeration_finds_the_reads_it_must_classify` | The verdict exists. No public method lacks a return annotation. The controls of D2 (f) hold |
| A2 | `test_every_public_read_is_gated_or_exempt_with_a_reason` | Gated xor exempt, for every read |
| A3 | `test_every_exemption_names_a_public_read_and_gives_a_reason` | No stale or empty entry |
| A4 | `test_weighted_recall_is_the_only_production_caller_of_its_internal_step` | The callers of `recall_for_agent_scored` under `src/probos` are `{("cognitive/episodic.py", "EpisodicMemory.recall_weighted")}` |
| R1 x14 | `test_each_gated_read_leaves_out_a_forged_source_only_when_armed[<read>]` | Premise: unbound, the read returns all four. Armed: `_KEPT`. Both event types report `{_FORGED}` |
| R2 x4 | `test_an_exempt_read_returns_every_episode_when_armed[get_by_ids, iter_live_episodes, list_episodes, recall_for_agent_scored]` | With both flags armed: all four, no event |
| R3 x14 | `test_with_every_flag_false_binding_changes_no_read[<read>]` | The same ordered ids as unbound. The forged episode is reported |
| R4 | `test_a_recency_read_reports_only_the_episodes_it_returns` | `recent(k=1)` over two forged episodes reports only the newer one: 2 events |
| R5 | `test_an_enforced_drop_that_empties_agent_recall_reports_band_none` | Premise: unbound `[forged]` with band not `none`. Armed: `[]` and band `none` |
| S1 x2 | `test_the_prompt_recall_gives_nothing_from_a_store_holding_only_a_forged_memory[basic_tier, weighted_then_fallback]` | D5 |

The 14 reads are: `get_by_ids_for_evidence`, `recall`, `recall_by_anchor`, `recall_by_anchor_scored`, `recall_by_intent`, `recall_for_agent`, `recall_for_agent_with_confidence`, `recall_valid_at`, `recall_weighted`, `recall_with_confidence`, `recall_with_control`, `recent`, `recent_for_agent`, `retrieve_contrastive_episodes`.

**`tests/test_bf984_rebuild_binding.py`** (6 cases):

| # | Name | Asserts |
|---|---|---|
| B1 | `test_every_production_episodic_memory_is_bound` | Every `EpisodicMemory(` construction under `src/probos` either calls `bind_episodic_memory_gates` in the same function, or is listed as bound by startup with its reason. `init_cognitive_services` calls the helper. No stale entry. Controls: `_boot_runtime` is found, and there are at least two constructions |
| B2 x2 | `test_the_shared_binding_binds_the_storage_gate_only_when_enabled[off, on]` | `StorageGate` is bound iff enabled. The three AD-607 values are bound |
| B3 x2 | `test_the_shared_binding_gates_a_rebuilt_episode[off, on]` | A real memory, the helper and the real `rebuild_from_wardroom`: the clean post is persisted (premise); the injected post is persisted iff not armed; the recorder sees `memory_injection_suspected` for it |
| B4 | `test_rebuild_episodic_stores_through_the_bound_gates` | The real `_cmd_rebuild_episodic`, with `enforce_store` armed (config replaced via `_load_config_with_fallback`) and the emitter replaced by a recorder: rc 0; persisted `[clean]`; the recorder sees the injected id |

**Predicted red and green:**

| Case | Base (7.1 only) | After M1 |
|---|---|---|
| A1, A3, A4 | green | green |
| A2 | red: 7 unclassified (`get_by_ids`, `recall_by_intent`, `recall_for_agent`, `recall_for_agent_with_confidence`, `recent`, `recent_for_agent`, `retrieve_contrastive_episodes`) | green |
| R1, R3: `recall`, `recall_with_confidence`, `recall_with_control`, `recall_weighted`, `recall_valid_at`, `recall_by_anchor`, `recall_by_anchor_scored` (7 each) | green (BF-938) | green |
| R1: the 7 new reads | red: the forged id is in the result | green |
| R3: the 7 new reads | red: no `memory_provenance_gap` | green |
| R2 x4 | green | green |
| R4 | red: no event | green |
| R5 | red: `[forged]` returned | green |
| S1 x2 | red: `recent_memories` holds the forged memory | green |

Base: 19 red, 21 green. After M1: 40 green.

| Case | M1 tree (7.2 added) | After M2 pairs without TA1 | After M2 |
|---|---|---|---|
| B1 | red: `[("__main__.py", "_cmd_rebuild_episodic._run")]` unbound, and `init_cognitive_services` makes no call | green | green |
| B2 x2, B3 x2 | red: `ImportError: bind_episodic_memory_gates` | green | green |
| B4 | red: the injected id is persisted, and the recorder is empty | green | green |
| `test_ad819_rebuild_episodic.py::TestShutdownMarkerReset::test_successful_rebuild_resets_marker` | green | **red: `AttributeError: '_FakeEM' object has no attribute 'set_security_config'`** | green |

The three BF-938 test files, BF-938's mock test and the callers' tests in section 4 stay green in every column.

## 7. The contract

### 7.1 New file: `tests/test_bf984_recall_gate_coverage.py` (M1, written first)

```python
"""BF-984 (#1830): AD-607's recall verdict on every public read of EpisodicMemory, and the reads exempt from it.

Before BF-984 the verdict ran in semantic, weighted and anchor recall only. With ``enforce_provenance`` armed, per-agent
recall, the recency reads, intent recall, contrastive recall and an evidence caller's ``get_by_ids`` returned a
forged-source episode with no event, and the crew's prompt recall used and fell back to them. These tests run on a real
ChromaDB-backed EpisodicMemory under tmp_path (tests/test_bf938_ad607_recall_gate.py's setup) and a real CognitiveAgent
(tests/test_ad1357_context_manifest.py's construction); each asserts its premise first. The AST tests classify every
public method whose return annotation names an episode, a recall score or an archive lookup: gated (it reaches
``_security_anomaly_drop`` through ``self`` calls) or listed in ``_EXEMPT`` with a reason. No line numbers.
"""

from __future__ import annotations

import ast
import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.source_governance import parse_anchor_query
from probos.config import TRUST_LIEUTENANT, MemorySecurityConfig, SystemConfig
from probos.crew_profile import Rank
from probos.events import EventType
from probos.types import AnchorFrame, Episode, IntentMessage
from tests import test_bf938_ad607_recall_gate as gate

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "probos"
_EPISODIC = _SRC / "cognitive" / "episodic.py"
_GATE = "_security_anomaly_drop"
# A public method is a read to classify when its return annotation names one of these.
_EPISODE_BEARING = frozenset({"Episode", "RecallScore", "ArchiveLookupResult"})

# The public reads that return episodes WITHOUT AD-607's recall verdict, each with its reason (BF-984, #1830).
# Every other read reaches the verdict. An entry that is gated, no longer exists or no longer returns episodes fails.
_EXEMPT: dict[str, str] = {
    "list_episodes": "maintenance: AD-689's edge backfill walks every row once (knowledge/backfill.py); "
    "whether a provenance-gap row may seed an edge is #1820 bf-984 F1",
    "iter_live_episodes": "erasure: BF-905's cascade must see every live row to erase it (knowledge/erasure.py)",
    "iter_archived_episodes": "erasure: AD-1340's cascade must see every archived row to erase it (knowledge/erasure.py)",
    "lookup_archived_by_id": "the Captain's audited archive read (AD-1340 S2a, routers/security.py); "
    "each returned row has an access row",
    "lookup_archived_by_agent": "the Captain's audited archive read (AD-1340 S2a, routers/security.py); "
    "each returned row has an access row",
    "restore_from_archive": "maintenance: the Captain's audited restore of one archived row to the live store; "
    "every later read of it is gated",
    "score_recall": "a pure scorer of an episode its caller already holds; it reads nothing from the store",
    "recall_for_agent_scored": "an internal step: recall_weighted gates its merged, budgeted pool (BF-938); "
    "recall_weighted is its only production caller (test_weighted_recall_is_the_only_production_caller...)",
}


# --- the AST helpers (tests/test_bf984_rebuild_binding.py imports calls_named) ----------------------------------------


def _class_methods() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_EPISODIC.read_text(encoding="utf-8"))
    (cls,) = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EpisodicMemory"]
    return {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _public(methods: dict[str, Any]) -> dict[str, Any]:
    return {name: node for name, node in methods.items() if not name.startswith("_")}


def _annotation_names(node: ast.expr) -> set[str]:
    names: set[str] = set()
    for part in ast.walk(node):
        if isinstance(part, ast.Name):
            names.add(part.id)
        elif isinstance(part, ast.Attribute):
            names.add(part.attr)
        elif isinstance(part, ast.Constant) and isinstance(part.value, str):
            names |= _annotation_names(ast.parse(part.value, mode="eval").body)
    return names


def _reads(methods: dict[str, Any]) -> set[str]:
    return {
        name for name, node in _public(methods).items()
        if node.returns is not None and _annotation_names(node.returns) & _EPISODE_BEARING
    }


def _self_calls(node: ast.AST) -> set[str]:
    return {
        call.func.attr for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
    }


def _reaches_gate(methods: dict[str, Any], name: str) -> bool:
    seen: set[str] = set()
    todo = [name]
    while todo:
        current = todo.pop()
        if current == _GATE:
            return True
        if current in seen or current not in methods:
            continue
        seen.add(current)
        todo.extend(_self_calls(methods[current]))
    return False


class _Calls(ast.NodeVisitor):
    """The qualified scope (classes and functions, innermost last) of each call to a callee named ``name``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.scope: list[str] = []
        self.found: list[str] = []

    def _scoped(self, node: ast.AST, label: str) -> None:
        self.scope.append(label)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if callee == self.name:
            self.found.append(".".join(self.scope))
        self.generic_visit(node)


@functools.lru_cache(maxsize=1)
def _source_trees() -> tuple[tuple[str, ast.Module], ...]:
    return tuple(
        (path.relative_to(_SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(_SRC.rglob("*.py"))
    )


def calls_named(name: str) -> set[tuple[str, str]]:
    """(path under src/probos, qualified scope) of every production call to a callee named ``name``."""
    found: set[tuple[str, str]] = set()
    for path, tree in _source_trees():
        visitor = _Calls(name)
        visitor.visit(tree)
        found |= {(path, scope) for scope in visitor.found}
    return found


# --- A1 to A4: the enumeration -------------------------------------------------------------------------------------


def test_the_enumeration_finds_the_reads_it_must_classify() -> None:
    methods = _class_methods()
    assert _GATE in methods  # premise: the verdict this file looks for
    assert sorted(name for name, node in _public(methods).items() if node.returns is None) == []  # unclassifiable
    reads = _reads(methods)
    assert {"recall", "recall_weighted", "recall_by_anchor", "lookup_archived_by_id", "iter_live_episodes"} <= reads
    assert {"store", "get_episode_metadata", "keyword_search"}.isdisjoint(reads)  # an outcome, a metadata dict, ids
    assert _reaches_gate(methods, "recall")  # control: through its delegate
    assert _reaches_gate(methods, "recall_weighted")  # control: directly
    assert not _reaches_gate(methods, "list_episodes")  # control: a read that does not


def test_every_public_read_is_gated_or_exempt_with_a_reason() -> None:
    methods = _class_methods()
    problems = []
    for name in sorted(_reads(methods)):
        gated, exempt = _reaches_gate(methods, name), name in _EXEMPT
        if gated and exempt:
            problems.append(f"{name}: reaches the verdict and is exempt; drop the exemption")
        elif not gated and not exempt:
            problems.append(f"{name}: neither reaches the verdict nor is exempt")
    assert problems == []


def test_every_exemption_names_a_public_read_and_gives_a_reason() -> None:
    reads = _reads(_class_methods())
    assert sorted(name for name in _EXEMPT if name not in reads) == []
    assert [name for name, reason in _EXEMPT.items() if not reason.strip()] == []


def test_weighted_recall_is_the_only_production_caller_of_its_internal_step() -> None:
    assert calls_named("recall_for_agent_scored") == {("cognitive/episodic.py", "EpisodicMemory.recall_weighted")}


# --- the reads, on a real store ------------------------------------------------------------------------------------

_ANCHOR = AnchorFrame(
    watch_section="first_watch", trigger_type="direct_message", trigger_agent="captain", department="engineering",
)
_VALID_AT = gate._T0 + 3_600.0


def _store() -> list[Episode]:
    """BF-938's four (two clean, a reflection, one forged source), each anchored in engineering for anchor recall."""
    return [replace(episode, anchors=_ANCHOR) for episode in gate._standard()]


async def _ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode in await read]


async def _first_ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode in (await read)[0]]


async def _score_ids(read: Awaitable[Any]) -> list[str]:
    return [score.episode.id for score in await read]


async def _pair_ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode, _similarity in await read]


async def _live_ids(em: EpisodicMemory) -> list[str]:
    return [episode.id async for episode in em.iter_live_episodes()]


class _MidBand:
    """The real collection, with every query distance set to 0.5: AD-655's contrastive band is [0.4, 0.65]."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def count(self) -> int:
        return self._collection.count()

    def query(self, **kwargs: Any) -> Any:
        result = self._collection.query(**kwargs)
        result["distances"] = [[0.5] * len(ids) for ids in result["ids"]]
        return result


async def _contrastive_ids(em: EpisodicMemory) -> list[str]:
    real = em._collection
    em._collection = _MidBand(real)
    try:
        return await _ids(em.retrieve_contrastive_episodes(gate._QUERY, k=5))
    finally:
        em._collection = real


_Read = Callable[[EpisodicMemory], Awaitable[list[str]]]

_GATED: dict[str, _Read] = {
    "recall": lambda em: _ids(em.recall(gate._QUERY, k=5)),
    "recall_with_confidence": lambda em: _first_ids(em.recall_with_confidence(gate._QUERY, k=5)),
    "recall_with_control": lambda em: _first_ids(em.recall_with_control(gate._QUERY, k=5)),
    "recall_weighted": lambda em: _score_ids(em.recall_weighted(gate._AGENT, gate._QUERY, k=5)),
    "recall_valid_at": lambda em: _score_ids(em.recall_valid_at(_VALID_AT, gate._AGENT, gate._QUERY, k=5)),
    "recall_by_anchor": lambda em: _ids(em.recall_by_anchor(department="engineering", agent_id=gate._AGENT)),
    "recall_by_anchor_scored": lambda em: _score_ids(
        em.recall_by_anchor_scored(department="engineering", agent_id=gate._AGENT)
    ),
    "recall_for_agent": lambda em: _ids(em.recall_for_agent(gate._AGENT, gate._QUERY, k=5)),
    "recall_for_agent_with_confidence": lambda em: _first_ids(
        em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
    ),
    "recent_for_agent": lambda em: _ids(em.recent_for_agent(gate._AGENT, k=5)),
    "recent": lambda em: _ids(em.recent(k=5)),
    "recall_by_intent": lambda em: _ids(em.recall_by_intent("report", k=5)),
    "retrieve_contrastive_episodes": _contrastive_ids,
    "get_by_ids_for_evidence": lambda em: _ids(em.get_by_ids(sorted(gate._ALL), for_evidence=True)),
}

_EXEMPT_READS: dict[str, _Read] = {
    "get_by_ids": lambda em: _ids(em.get_by_ids(sorted(gate._ALL))),  # the bare call is history (AD-1293)
    "list_episodes": lambda em: _ids(em.list_episodes()),
    "iter_live_episodes": _live_ids,
    "recall_for_agent_scored": lambda em: _pair_ids(em.recall_for_agent_scored(gate._AGENT, gate._QUERY, k=5)),
}


@pytest.mark.parametrize("name", sorted(_GATED))
async def test_each_gated_read_leaves_out_a_forged_source_only_when_armed(tmp_path: Path, name: str) -> None:
    read = _GATED[name]
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        assert set(await read(em)) == gate._ALL  # premise: unbound, the read returns all four
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        assert set(await read(em)) == gate._KEPT
    assert set(recorder.ids(EventType.MEMORY_RECALL_ANOMALY)) == {gate._FORGED}
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {gate._FORGED}


@pytest.mark.parametrize("name", sorted(_EXEMPT_READS))
async def test_an_exempt_read_returns_every_episode_when_armed(tmp_path: Path, name: str) -> None:
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True, enforce_recall=True))
        em.set_security_event_emitter(recorder)
        assert set(await _EXEMPT_READS[name](em)) == gate._ALL
    assert recorder.events == []


@pytest.mark.parametrize("name", sorted(_GATED))
async def test_with_every_flag_false_binding_changes_no_read(tmp_path: Path, name: str) -> None:
    read = _GATED[name]
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        unbound = await read(em)
        assert set(unbound) == gate._ALL  # premise: the forged episode is among them
        em.set_security_config(MemorySecurityConfig())
        em.set_security_event_emitter(recorder)
        assert await read(em) == unbound
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {gate._FORGED}  # reported, never dropped


async def test_a_recency_read_reports_only_the_episodes_it_returns(tmp_path: Path) -> None:
    older = gate._episode("bf984-forged-older", 0, source="forged_source")
    newer = gate._episode("bf984-forged-newer", 1, source="forged_source")
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, [older, newer]) as em:
        assert [episode.id for episode in await em.recent(k=2)] == [newer.id, older.id]  # premise: newest first
        em.set_security_config(MemorySecurityConfig())
        em.set_security_event_emitter(recorder)
        assert [episode.id for episode in await em.recent(k=1)] == [newer.id]
    assert recorder.ids(EventType.MEMORY_RECALL_ANOMALY) == [newer.id]
    assert recorder.ids(EventType.MEMORY_PROVENANCE_GAP) == [newer.id]
    assert len(recorder.events) == 2


async def test_an_enforced_drop_that_empties_agent_recall_reports_band_none(tmp_path: Path) -> None:
    forged = gate._episode(gate._FORGED, 0, source="forged_source")
    async with gate._memory(tmp_path, [forged]) as em:
        episodes, confidence = await em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
        assert [episode.id for episode in episodes] == [forged.id]  # premise: unbound, it is recalled
        assert confidence.band != "none"  # premise: with a band the reset can change
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        episodes, confidence = await em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
    assert episodes == []
    assert confidence.band == "none"


# --- S1: the seam, the crew's prompt recall over the real memory -----------------------------------------------------

_FORGED_MEMORY = "the coolant loop pressure held steady through the shift"
_ASK = "What do you recall about the coolant loop pressure?"


class _Trust:
    """A trust network with one score: Rank.from_trust gives the agent's rank, and so its recall tier (BF-263)."""

    def __init__(self, score: float) -> None:
        self.score = score

    def get_score(self, _agent_id: str) -> float:
        return self.score


def _counted(calls: dict[str, int], name: str, original: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    async def counted(*args: Any, **kwargs: Any) -> Any:
        calls[name] = calls.get(name, 0) + 1
        return await original(*args, **kwargs)

    return counted


async def _prompt_recall(agent: CognitiveAgent, params: dict[str, Any]) -> dict[str, Any]:
    """``_run_cognitive_lifecycle``'s recall step for a Captain's direct message (test_ad1357's ``_turn``, recall only)."""
    intent = IntentMessage(intent="direct_message", params=params)
    observation = {"intent": "direct_message", "intent_id": intent.id, "params": params}
    return await agent._recall_relevant_memories(intent, observation)


@pytest.mark.parametrize(
    ("trust", "rank"),
    [(0.1, Rank.ENSIGN), (TRUST_LIEUTENANT, Rank.LIEUTENANT)],
    ids=["basic_tier", "weighted_then_fallback"],
)
async def test_the_prompt_recall_gives_nothing_from_a_store_holding_only_a_forged_memory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, trust: float, rank: Rank,
) -> None:
    assert Rank.from_trust(trust) is rank  # premise: an ensign recalls at BASIC, a lieutenant at ENHANCED
    assert not parse_anchor_query(_ASK, known_callsigns=[]).has_anchor_signal  # premise: no anchor recall runs
    agent = CognitiveAgent(agent_id="bf984-agent", instructions="You are Ezri.")
    agent.agent_type = "scout"
    agent.callsign = "Ezri"
    mem_id = agent.sovereign_id or agent.id
    forged = Episode(
        id="bf984-forged", timestamp=gate._T0, user_input=_FORGED_MEMORY, agent_ids=[mem_id],
        source="forged_source", correlation_id="corr-bf984-forged", outcomes=[{"intent": "report", "success": True}],
    )
    params = {"text": _ASK, "captain_message": _ASK}
    calls: dict[str, int] = {}
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, [forged]) as em:
        agent._runtime = SimpleNamespace(
            config=SystemConfig(), cognitive_journal=None, episodic_memory=em, ontology=None, trust_network=_Trust(trust),
        )
        for name in ("recall_weighted", "recall_for_agent", "recent_for_agent"):
            setattr(em, name, _counted(calls, name, getattr(em, name)))
        unbound = await _prompt_recall(agent, params)
        assert [memory["input"] for memory in unbound.get("recent_memories", [])] == [_FORGED_MEMORY]  # premise
        assert ("recall_weighted" in calls) is (rank is Rank.LIEUTENANT)  # premise: the basic tier skips it
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        calls.clear()
        with caplog.at_level(logging.WARNING):
            bound = await _prompt_recall(agent, params)
    assert "recent_memories" not in bound
    assert calls.get("recent_for_agent") == 1  # the turn fell through to the last fallback, which returned nothing
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {forged.id}  # the verdict left it out
    assert not [record for record in caplog.records if "BF-138" in record.getMessage()]  # recall did not fail
```

### 7.2 New file: `tests/test_bf984_rebuild_binding.py` (M2, written first)

```python
"""BF-984 (#1830) G1: ``probos rebuild-episodic`` binds its memory's gates through the helper startup uses.

Before BF-984 the rebuild command built its own EpisodicMemory and called no setter, while its comment said the gates
fire. ``bind_episodic_memory_gates`` is now shared with ``init_cognitive_services``. These tests run a real
EpisodicMemory under tmp_path over a real ward_room.db (tests/test_ad819_rebuild_episodic.py's fixture plus one post
that matches an AD-607h injection pattern), and the real command; the AST guard fails on any production construction
of EpisodicMemory that is not bound. Names the change adds are imported inside the tests, so the file collects on the
base.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

import pytest

import probos.__main__ as cli
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import MemorySecurityGate
from probos.cognitive.storage_gate import StorageGate
from probos.config import SystemConfig
from probos.events import EventType
from probos.maintenance.rebuild_episodic import _stable_episode_id, rebuild_from_wardroom
from probos.types import Episode
from tests import test_bf938_ad607_binding as binding
from tests.test_ad819_rebuild_episodic import _build_wardroom_fixture
from tests.test_bf984_recall_gate_coverage import calls_named

_CLEAN_ID = _stable_episode_id(source="wardroom_rebuild_post", source_id="p1")
_INJECTED_ID = _stable_episode_id(source="wardroom_rebuild_post", source_id="p9")
# The constructions startup binds, with the reason. Every other construction calls the helper in the same function.
_BOUND_BY_STARTUP: dict[tuple[str, str], str] = {
    ("__main__.py", "_boot_runtime"): "the runtime's memory: init_cognitive_services binds it through "
    "bind_episodic_memory_gates (tests/test_bf938_ad607_binding.py)",
}


def _wardroom(root: Path) -> Path:
    """test_ad819's ward room, plus post p9, whose body matches an AD-607h injection pattern."""
    db = root / "ward_room.db"
    _build_wardroom_fixture(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("p9", "t1", None, "agent-E", binding._INJECTED, 1030.0, None, 0, "", "", 0, "Crusher"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _config(*, armed: bool, storage_gate: bool = False) -> SystemConfig:
    config = SystemConfig()
    config.storage_gate.enabled = storage_gate  # AD-610's utility gate is under test only in B2; AD-607h runs after it
    config.security.memory.enforce_store = armed
    return config


async def _persisted(db_path: Path, ids: list[str]) -> list[str]:
    em = EpisodicMemory(db_path=str(db_path), relevance_threshold=0.0)
    await em.start()
    try:
        return sorted(em._collection.get(ids=ids)["ids"])
    finally:
        await em.stop()


def test_every_production_episodic_memory_is_bound() -> None:
    constructions = calls_named("EpisodicMemory")
    binders = calls_named("bind_episodic_memory_gates")
    assert ("__main__.py", "_boot_runtime") in constructions  # control: the runtime's construction is found
    assert len(constructions) >= 2  # control: and the rebuild command's
    assert sorted(site for site in constructions if site not in binders and site not in _BOUND_BY_STARTUP) == []
    assert ("startup/cognitive_services.py", "init_cognitive_services") in binders
    assert set(_BOUND_BY_STARTUP) <= constructions  # no stale entry


@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_the_shared_binding_binds_the_storage_gate_only_when_enabled(tmp_path: Path, enabled: bool) -> None:
    from probos.startup.cognitive_services import bind_episodic_memory_gates

    config = _config(armed=False, storage_gate=enabled)
    emit = binding._Recorder()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))  # never started: binding needs no open store
    bind_episodic_memory_gates(em, config, emit)
    assert isinstance(em._storage_gate, StorageGate) is enabled
    assert em._security_config is config.security.memory
    assert isinstance(em._security_gate, MemorySecurityGate)
    assert em._security_event_emitter is emit


@pytest.mark.parametrize("armed", [False, True], ids=["off", "on"])
async def test_the_shared_binding_gates_a_rebuilt_episode(tmp_path: Path, armed: bool) -> None:
    from probos.startup.cognitive_services import bind_episodic_memory_gates

    db = _wardroom(tmp_path)
    recorder = binding._Recorder()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        bind_episodic_memory_gates(em, _config(armed=armed), recorder)

        async def _store(kwargs: dict) -> None:
            await em.store(Episode(**kwargs))

        report = await rebuild_from_wardroom(wardroom_db=db, store_episode=_store)
        assert report.errors == []  # premise: every row reached store()
        persisted = sorted(em._collection.get(ids=[_CLEAN_ID, _INJECTED_ID])["ids"])
    finally:
        await em.stop()
    assert persisted == sorted([_CLEAN_ID] if armed else [_CLEAN_ID, _INJECTED_ID])
    assert recorder.ids(EventType.MEMORY_INJECTION_SUSPECTED) == [_INJECTED_ID]


def test_rebuild_episodic_stores_through_the_bound_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _wardroom(data_dir)
    recorder = binding._Recorder()
    monkeypatch.setattr(cli, "_load_config_with_fallback", lambda _path: (_config(armed=True), None))
    monkeypatch.setattr(cli, "_log_rebuild_memory_event", recorder, raising=False)  # absent on the base
    args = argparse.Namespace(data_dir=data_dir, config=None, since=None, dry_run=False)
    assert cli._cmd_rebuild_episodic(args) == 0
    assert asyncio.run(_persisted(data_dir / "episodic.db", [_CLEAN_ID, _INJECTED_ID])) == [_CLEAN_ID]
    assert recorder.ids(EventType.MEMORY_INJECTION_SUSPECTED) == [_INJECTED_ID]
```

### 7.3 `src/probos/cognitive/episodic.py` (M1)

**EP1: the helper** (SEARCH occurs once; `:1585-1589`)

SEARCH:
```python
        except Exception:
            logger.debug("AD-607: recall anomaly gate failed", exc_info=True)
            return False

    def set_retroactive_evolver(self, evolver: Any) -> None:
```
REPLACE:
```python
        except Exception:
            logger.debug("AD-607: recall anomaly gate failed", exc_info=True)
            return False

    def _drop_security_anomalies(
        self,
        episodes: list[Episode],
        *,
        query: str = "",
        anchor_query: Any = None,
    ) -> list[Episode]:
        """BF-984 (#1830): AD-607's recall verdict over the episodes a read is about to return.

        The shared filter of the public reads that build their result without the per-candidate verdict
        (``recall_for_agent_with_confidence``, ``recent_for_agent``, ``recent``, ``recall_by_intent``,
        ``retrieve_contrastive_episodes`` and ``get_by_ids(for_evidence=True)``). Applied to the final list, after
        AD-1293's exclusion, so it checks only what the read returns, and an enforced drop shortens the result rather
        than promoting another episode. Unbound (no config) the list is returned unchanged; with every ``enforce_*``
        flag false every episode is kept and an anomaly is reported. The public reads that return episodes without
        the verdict, and why, are listed in tests/test_bf984_recall_gate_coverage.py, which fails on any public read
        that is neither gated nor listed. ``getattr``: test modules build an EpisodicMemory with ``__new__``.
        """
        if getattr(self, "_security_config", None) is None:
            return episodes
        return [
            episode for episode in episodes
            if not self._security_anomaly_drop(episode, query=query, anchor_query=anchor_query)
        ]

    def set_retroactive_evolver(self, evolver: Any) -> None:
```

**EP2: agent recall** (`:4055-4060`; "sovereign fusion" makes the block unique)

SEARCH:
```python
        # AD-1293 (#1200): exclude after sovereign fusion, for the same reason
        # as the global path -- the fusion tail re-hydrates ids via get_by_ids.
        _pre_exclusion = episodes
        episodes = self._drop_self_contradicted(episodes, include_self_contradicted)
        if _pre_exclusion and not episodes:
            confidence = dataclasses.replace(confidence, band="none")
```
REPLACE:
```python
        # AD-1293 (#1200): exclude after sovereign fusion, for the same reason
        # as the global path -- the fusion tail re-hydrates ids via get_by_ids.
        # BF-984 (#1830): AD-607's recall verdict at the same point, for the same reason (it also covers the
        # sparse-hydrated ids), and before the band reset, so an enforced drop that empties the recall reports "none".
        _pre_exclusion = episodes
        episodes = self._drop_self_contradicted(episodes, include_self_contradicted)
        episodes = self._drop_security_anomalies(episodes, query=query)
        if _pre_exclusion and not episodes:
            confidence = dataclasses.replace(confidence, band="none")
```

**EP3: `recent_for_agent`** (`:4177-4180`)

SEARCH:
```python
        # AD-1293 (#1200): after the k-cap, so an excluded episode shortens the
        # result rather than promoting an older one -- the safe direction, and
        # it keeps the single-pass scan this fallback exists to be.
        return self._drop_self_contradicted(episodes, include_self_contradicted)
```
REPLACE:
```python
        # AD-1293 (#1200): after the k-cap, so an excluded episode shortens the
        # result rather than promoting an older one -- the safe direction, and
        # it keeps the single-pass scan this fallback exists to be.
        # BF-984 (#1830): AD-607's recall verdict, after the exclusion and for the same reason. No query or anchor
        # view: a recency read is judged on provenance.
        return self._drop_security_anomalies(
            self._drop_self_contradicted(episodes, include_self_contradicted)
        )
```

**EP4: `recall_by_intent`** (`:4214-4223`)

SEARCH:
```python
        for doc_id, metadata, document in paired[:k]:
            # Double-check intent filter for manual fallback
            if metadata.get("intent_type") != intent_type:
                continue
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        return self._drop_self_contradicted(episodes, include_self_contradicted)  # AD-1293
```
REPLACE:
```python
        for doc_id, metadata, document in paired[:k]:
            # Double-check intent filter for manual fallback
            if metadata.get("intent_type") != intent_type:
                continue
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        # BF-984 (#1830): AD-607's recall verdict, after the exclusion; no anchor view (provenance only).
        return self._drop_security_anomalies(
            self._drop_self_contradicted(episodes, include_self_contradicted)  # AD-1293
        )
```

**EP5: `recent`** (`:4247-4253`)

SEARCH:
```python
        return self._drop_self_contradicted(  # AD-1293 (#1200)
            [
                self._metadata_to_episode(doc_id, document, metadata)
                for doc_id, metadata, document in paired[:k]
            ],
            include_self_contradicted,
        )
```
REPLACE:
```python
        return self._drop_security_anomalies(  # BF-984 (#1830): AD-607's recall verdict, after the exclusion
            self._drop_self_contradicted(  # AD-1293 (#1200)
                [
                    self._metadata_to_episode(doc_id, document, metadata)
                    for doc_id, metadata, document in paired[:k]
                ],
                include_self_contradicted,
            )
        )
```

**EP6: contrastive** (`:3729-3733`)

SEARCH:
```python
        # AD-1293 (#1200): contrastive hits feed decision-making, so they are
        # EVIDENCE and are excluded on the same predicate as every other.
        contrastive = self._drop_self_contradicted(
            contrastive, include_self_contradicted
        )
```
REPLACE:
```python
        # AD-1293 (#1200): contrastive hits feed decision-making, so they are
        # EVIDENCE and are excluded on the same predicate as every other.
        contrastive = self._drop_self_contradicted(
            contrastive, include_self_contradicted
        )
        # BF-984 (#1830): AD-607's recall verdict, before the CONTRASTIVE_RECALL report, which names what is returned.
        contrastive = self._drop_security_anomalies(contrastive, query=query)
```

**EP7: `get_by_ids`** (`:2418-2421`)

SEARCH:
```python
        ordered = [by_id[eid] for eid in episode_ids if eid in by_id]
        if not for_evidence:
            return ordered
        return self._drop_self_contradicted(ordered, False)  # AD-1293 (#1200)
```
REPLACE:
```python
        ordered = [by_id[eid] for eid in episode_ids if eid in by_id]
        if not for_evidence:
            return ordered
        # BF-984 (#1830): an evidence caller also gets AD-607's recall verdict. The bare call stays unfiltered
        # (history: erasure resolves through it, and the fusion tails gate what they hydrate).
        return self._drop_security_anomalies(self._drop_self_contradicted(ordered, False))  # AD-1293 (#1200)
```

### 7.4 `src/probos/startup/cognitive_services.py` (M2)

**CS1: the helper** (`:48-54`)

SEARCH:
```python
    episodic_memory.set_erasure_sidecar_paths(
        activation_db_path=str(data_dir / ACTIVATION_TRACKER_DB),
        participant_index_db_path=str(data_dir / PARTICIPANT_INDEX_DB),
    )


async def _run_one_migration(
```
REPLACE:
```python
    episodic_memory.set_erasure_sidecar_paths(
        activation_db_path=str(data_dir / ACTIVATION_TRACKER_DB),
        participant_index_db_path=str(data_dir / PARTICIPANT_INDEX_DB),
    )


def bind_episodic_memory_gates(
    episodic_memory: Any,
    config: "SystemConfig",
    emit_event_fn: Callable[..., Any] | None,
) -> None:
    """BF-984 (#1830): bind the store-time gates and AD-607's recall config to an EpisodicMemory.

    The one binding shared by startup (``init_cognitive_services``) and ``probos rebuild-episodic``, which builds its
    own memory. AD-610's storage gate only when ``config.storage_gate.enabled``; a gate that fails to construct is
    logged and the memory stores without it (log-and-degrade, as startup did). AD-607 (BF-938, #1680): the security
    config, the store gate and the event emitter, unconditionally and not wrapped, because an armed control that
    silently fails to bind is BF-938's defect. Every ``enforce_*`` flag defaults to False, so by default the recall
    verdict and the store gate only report (MEMORY_* events).
    """
    if config.storage_gate.enabled:
        try:
            from probos.cognitive.storage_gate import StorageGate as _StorageGate

            storage_gate = _StorageGate(
                config=config.storage_gate,
                emit_event_fn=emit_event_fn,
            )
            episodic_memory.set_storage_gate(storage_gate)
            logger.info("AD-610: StorageGate initialized and wired to EpisodicMemory")
        except Exception as exc:
            logger.warning(
                "AD-610: StorageGate failed to start: %s; continuing without write-time storage gating",
                exc,
            )

    from probos.cognitive.memory_security import MemorySecurityGate

    episodic_memory.set_security_config(config.security.memory)
    episodic_memory.set_security_gate(MemorySecurityGate(config.security.memory))
    episodic_memory.set_security_event_emitter(emit_event_fn)
    logger.info("AD-607: memory security config, store gate and event emitter bound to EpisodicMemory (BF-938)")


async def _run_one_migration(
```

**CS2: startup calls it** (`:313-340`)

SEARCH:
```python
    # AD-610: Storage gate for episodic memory
    if episodic_memory and config.storage_gate.enabled:
        try:
            from probos.cognitive.storage_gate import StorageGate as _StorageGate

            storage_gate = _StorageGate(
                config=config.storage_gate,
                emit_event_fn=emit_event_fn,
            )
            episodic_memory.set_storage_gate(storage_gate)
            logger.info("AD-610: StorageGate initialized and wired to EpisodicMemory")
        except Exception as exc:
            logger.warning(
                "AD-610: StorageGate failed to start: %s; continuing without write-time storage gating",
                exc,
            )

    # AD-607 (BF-938, #1680): the memory security framework. Every enforce_* flag defaults to False, so by default
    # the recall validator and the store gate only report (MEMORY_* events); recall and store results change only
    # when the operator's config or a profile arms a flag. Not wrapped: an armed control that silently fails to
    # bind is the defect this fixes.
    if episodic_memory:
        from probos.cognitive.memory_security import MemorySecurityGate

        episodic_memory.set_security_config(config.security.memory)
        episodic_memory.set_security_gate(MemorySecurityGate(config.security.memory))
        episodic_memory.set_security_event_emitter(emit_event_fn)
        logger.info("AD-607: memory security config, store gate and event emitter bound to EpisodicMemory (BF-938)")
```
REPLACE:
```python
    # AD-610's storage gate and AD-607 (BF-938, #1680), bound through the helper the rebuild command shares (BF-984).
    if episodic_memory:
        bind_episodic_memory_gates(episodic_memory, config, emit_event_fn)
```

### 7.5 `src/probos/__main__.py` (M2)

**MN1: the emitter** (`:2217-2218`)

SEARCH:
```python
def _cmd_rebuild_episodic(args: argparse.Namespace) -> int:
    """Handle ``probos rebuild-episodic`` (AD-819).
```
REPLACE:
```python
def _log_rebuild_memory_event(event_type: object, data: dict | None = None) -> None:
    """BF-984 (#1830): the memory gates' event emitter for ``probos rebuild-episodic``, which has no event bus.

    Logs each event's type and episode id at WARNING; never the episode's text, the matched pattern or the reason.
    """
    logging.getLogger(__name__).warning(
        "rebuild-episodic: %s for episode %s",
        getattr(event_type, "value", event_type),
        (data or {}).get("episode_id", ""),
    )


def _cmd_rebuild_episodic(args: argparse.Namespace) -> int:
    """Handle ``probos rebuild-episodic`` (AD-819).
```

**MN2: the comment and the import** (`:2290-2296`)

SEARCH:
```python
        # Real rebuild: stand up an EpisodicMemory bound to the same
        # ChromaDB the runtime would use, then store synthesized
        # episodes through its public ``store(Episode)`` API so all the
        # gates fire normally (AD-610 storage gate, AD-607h security
        # gate, content-hash computation, etc.).
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode
```
REPLACE:
```python
        # Real rebuild: stand up an EpisodicMemory bound to the same
        # ChromaDB the runtime would use, bind its gates as startup does
        # (BF-984, #1830: ``bind_episodic_memory_gates``, shared with
        # ``init_cognitive_services``), then store synthesized episodes
        # through its public ``store(Episode)`` API, so the AD-610 storage
        # gate (when ``storage_gate.enabled``) and the AD-607h store gate run
        # on every rebuilt episode. With no event bus here, the gates' events
        # are logged at WARNING (``_log_rebuild_memory_event``).
        from probos.cognitive.episodic import EpisodicMemory
        from probos.startup.cognitive_services import bind_episodic_memory_gates
        from probos.types import Episode
```

**MN3: bind inside the `try`** (`:2309-2312`)

SEARCH:
```python
        await em.start()

        try:
            # Snapshot existing episode ids so re-runs are fast-skip.
```
REPLACE:
```python
        await em.start()

        try:
            # BF-984 (#1830): inside the try, so a binding that raises still stops the memory.
            bind_episodic_memory_gates(em, cfg, _log_rebuild_memory_event)
            # Snapshot existing episode ids so re-runs are fast-skip.
```

### 7.6 `tests/test_ad819_rebuild_episodic.py` (M2, TA1; `:406-417`)

SEARCH:
```python
        class _FakeEM:
            def __init__(self, *a, **kw):
                self._collection = None

            async def start(self):
                return None
```
REPLACE:
```python
        class _FakeEM:
            def __init__(self, *a, **kw):
                self._collection = None

            # BF-984 (#1830): the rebuild binds its gates through bind_episodic_memory_gates.
            def set_storage_gate(self, _gate):
                return None

            def set_security_config(self, _config):
                return None

            def set_security_gate(self, _gate):
                return None

            def set_security_event_emitter(self, _emitter):
                return None

            async def start(self):
                return None
```

### 7.7 `PROGRESS.md` (M3)

**TR1: the new entry.** SEARCH (the whole line `:1`, once): `# ProbOS Progress`. REPLACE:

```markdown
# ProbOS Progress

**BF-984 (2026-11-20), #1830 -- AD-607's recall verdict runs on every public read of episodic memory except eight exempt reads, and `probos rebuild-episodic` binds the memory gates as startup does.** With `enforce_provenance` armed, per-agent recall, `recent_for_agent`, `recent`, `recall_by_intent`, contrastive recall and an evidence caller's `get_by_ids(for_evidence=True)` returned a forged-source episode with no event, and the crew's prompt recall used per-agent recall at the basic tier and fell back to it and to `recent_for_agent` when weighted recall returned nothing. Each of those reads now passes the list it returns through one shared filter, `EpisodicMemory._drop_security_anomalies`, after AD-1293's exclusion; agent recall reports band `none` when an enforced drop empties it. Eight reads stay exempt, each with its reason in the test: `list_episodes` (the edge backfill), the two erasure scans, the Captain's two archive lookups and restore, the pure scorer `score_recall`, and `recall_for_agent_scored`, weighted recall's internal step. `bind_episodic_memory_gates` in `startup/cognitive_services.py` binds AD-610's storage gate (when enabled) and AD-607's config, store gate and emitter; startup and the rebuild command call it, and the command logs the gates' events at WARNING. Every `enforce_*` default stays false. Measured by `tests/test_bf984_recall_gate_coverage.py` (40 cases) and `tests/test_bf984_rebuild_binding.py` (6 cases) on a real ChromaDB-backed memory: each of fourteen gated reads leaves the forged episode out only when armed and reports it in every mode; with every flag false no read's result changes; the exempt reads return every episode with no event; a recency read reports only the episodes it returns; a real agent's prompt recall, at the basic tier and through the fallback, gives nothing from a store holding only a forged memory; the AST enumeration fails on a public read that is neither gated nor exempt and on a production `EpisodicMemory` that is not bound; the real rebuild command with `enforce_store` armed leaves an injection-pattern post out of the store and reports it. No live store was read. Derived artefacts, the Captain's views under enforcement, unrefilled drops, event volume and the rebuild report's count are items bf-984 F1 to F5 of #1820. Contract `prompts/bf-984-recall-gate-every-read.md`.
```

**TR2: the BF-938 Limits amendment.** A substring inside `:40`. It occurs once (`grep -c`: 1) and contains no newline.

SEARCH (substring): `binds neither gate (G1; #1830).`
REPLACE: `` binds neither gate (G1; #1830). [Amended by BF-984 (2026-11-20): every public read of episodic memory now runs the verdict except eight exempt reads, listed with their reasons in `tests/test_bf984_recall_gate_coverage.py`, and `probos rebuild-episodic` binds both gates through the helper startup uses.] ``

### 7.8 `DECISIONS.md` (M3)

**TR3: the new entry.** SEARCH (the whole line `:1661`, once): `### BF-991 -- /diagnostic reads the level from the message's params; the handler parses the LLM's text (2026-11-20, #1840)`. REPLACE:

```markdown
### BF-984 -- AD-607's recall verdict runs on every public read of episodic memory but eight exempt ones; the rebuild command binds the gates as startup does (2026-11-20, #1830)

- *Mechanism.* `_security_anomaly_drop` ran in semantic, weighted and anchor recall only. With `enforce_provenance` armed, `recall_for_agent`, `recall_for_agent_with_confidence`, `recent_for_agent`, `recent`, `recall_by_intent`, `retrieve_contrastive_episodes` and `get_by_ids(for_evidence=True)` returned a forged-source episode with no event, and the crew's prompt recall uses `recall_for_agent` at the basic tier and falls back to it and to `recent_for_agent` when weighted recall returns nothing. `probos rebuild-episodic` built its own memory and called no setter, while its comment said the gates fire.
- *D1 (the helper).* One private list filter, `EpisodicMemory._drop_security_anomalies(episodes, *, query="", anchor_query=None)`, applies the existing per-episode verdict to the list a read is about to return; unbound it returns the list unchanged. Each of the six reads calls it once, after AD-1293's exclusion, so it checks only what is returned; in agent recall it runs before the band reset, so an enforced drop that empties the recall reports band `none`. The seven reads that already reached the verdict keep their code. Rejected: the verdict in `_metadata_to_episode` (it would also filter erasure, export and the Captain's audited reads, which must see every row); checks at the prompt recall and the dream cycle only (a new caller bypasses them); a ChromaDB `where` predicate on the source (it would refill, but the default mode must report and keep, which a query predicate cannot); gating `recall_for_agent_scored` (weighted recall would report each anomaly twice).
- *D2 (the allowlist).* Exempt, each with its reason in `tests/test_bf984_recall_gate_coverage.py`: `list_episodes` (AD-689's edge backfill), `iter_live_episodes` and `iter_archived_episodes` (erasure), `lookup_archived_by_id` and `lookup_archived_by_agent` (the Captain's audited archive reads), `restore_from_archive` (the Captain's audited restore), `score_recall` (a pure scorer) and `recall_for_agent_scored` (weighted recall's internal step, whose only production caller is weighted recall, which gates its merged pool). `get_by_ids` is gated when an evidence caller passes `for_evidence=True` (AD-1293's call-site rule); the bare call stays unfiltered. The test parses the class and fails on a public method whose return annotation names `Episode`, `RecallScore` or `ArchiveLookupResult` that neither reaches the verdict through `self` calls nor is exempt, and on an exemption that is gated, missing or no longer returns episodes.
- *D3 (events).* No dedupe: each read that returns an anomalous episode reports it, as BF-938's reads do. Because the filter runs on the returned list, a read reports only what it returns (measured: `recent(k=1)` over two forged episodes reports one, with one `memory_recall_anomaly` and one `memory_provenance_gap`). Rejected: a per-process dedupe by episode and event (it changes the event contract the seven gated reads have and the counts AD-607j would take, and adds state); the census of 2026-10-27 flagged none. The volume through the recency reads with flagged episodes is not measured (#1820 bf-984 F4).
- *D4 (G1).* `bind_episodic_memory_gates(episodic_memory, config, emit_event_fn)` in `startup/cognitive_services.py` holds startup's binding unchanged: AD-610's storage gate when `storage_gate.enabled` (log-and-degrade) and AD-607's config, store gate and emitter, unconditionally and unwrapped (BF-938 D5). `init_cognitive_services` and the rebuild command call it; the command passes `_log_rebuild_memory_event`, which logs each event's type and episode id at WARNING. By default the AD-610 gate now runs on rebuilt episodes, and the report still counts a skipped one as written (#1820 bf-984 F5).
- *Defaults.* Every `enforce_*` default stays false: by default the verdict only reports, and no read's result changes (tested for all fourteen gated reads).
- *Decided by the Architect.* Inside the envelope (consult `54da016e`, recorded on #1830): it strengthens a control and adds no default, spend path, schema or boundary.
- *Reversal.* Revert the BF-984 commits.

### BF-991 -- /diagnostic reads the level from the message's params; the handler parses the LLM's text (2026-11-20, #1840)
```

**TR4: the BF-938 effects amendment.** A substring inside `:2134` (once).

SEARCH: `do not (#1830).`
REPLACE: `` do not (#1830) [amended by BF-984, 2026-11-20: every public read of episodic memory now runs the validator except eight exempt reads (maintenance, erasure, the Captain's audited archive reads and restore, a pure scorer, and weighted recall's internal step), listed with their reasons in `tests/test_bf984_recall_gate_coverage.py`]. ``

**TR5: the "Not yet covered" amendment.** A substring at the end of `:2136` (once).

SEARCH: `` and `probos rebuild-episodic` stores without the store gate. ``
REPLACE: `` and `probos rebuild-episodic` stores without the store gate. [Amended by BF-984 (2026-11-20): these reads are now checked as recall is. With `enforce_provenance` armed, a memory with a provenance gap is left out of the crew's prompt recall at the basic tier and of its fallbacks, of `recent` and `recall_by_intent` (which the dream cycle reads), and of every other read except eight exempt ones that must see every row (maintenance, erasure, the Captain's audited archive reads and restore, a pure scorer, and weighted recall's internal step). The Captain's `/memory` view and the memory graph are among the checked reads (#1820 bf-984 F2). `probos rebuild-episodic` binds the store gates through the helper startup uses.] ``

### 7.9 Generated: the ledger pair (M3)

After TR1 to TR5, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`. Both go in M3's commit; do not paste them by hand. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. **`roadmap.md`: no row** (D7).

### 7.10 `docs/research/reference-projects.md` (M3, RP1; the Architect's row update, applied by the orchestrator under the file's own rule)

The file says that, under `--read-only`, the Architect puts the row updates in its answer and the orchestrator applies them in its next docs change. This is that change: one row, the one end of section 13 names. It is not in the Architect's draft of section 10, so section 10's file list names it.

**RP1.** SEARCH (the whole row, once, `:58`):
```markdown
| RAGFlow | 2026-05-08 | absorption | `ragflow-absorption.md` |
```
REPLACE:
```markdown
| RAGFlow | 2026-11-20 | checked | `ragflow-absorption.md`; BF-984 (#1830) Prior Art, `prompts/bf-984-recall-gate-every-read.md` (a search found nothing on RAGFlow retrieval-time filtering; nothing new) |
```

## 8. Issue texts (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Comment on #1830 (at merge)

> Fixed by BF-984 (PR #...).
>
> **G8.** Every public read of `EpisodicMemory` that returns episodes now runs AD-607's recall verdict, except eight exempt reads that must see every row. The exempt reads, with their reasons, are listed in `tests/test_bf984_recall_gate_coverage.py`. The six reads that lacked the verdict call one shared filter, `_drop_security_anomalies`, on the list they return:
> - `recall_for_agent_with_confidence`, which also covers `recall_for_agent`;
> - `recent_for_agent`;
> - `recent`;
> - `recall_by_intent`;
> - `retrieve_contrastive_episodes`;
> - `get_by_ids` when the caller passes `for_evidence=True`.
>
> `recall_for_agent_scored` stays exempt as weighted recall's internal step: weighted recall gates its merged pool, and the test asserts it is the only production caller. Every `enforce_*` default stays false.
>
> **G1.** `bind_episodic_memory_gates` in `startup/cognitive_services.py` is now the single binding. `init_cognitive_services` and `probos rebuild-episodic` both call it. The command logs the gates' events at WARNING, and its comment is corrected.
>
> **Acceptance, mapped to tests:**
> - (1) Enumeration: `test_every_public_read_is_gated_or_exempt_with_a_reason`, with its controls in `test_the_enumeration_finds_the_reads_it_must_classify`, `test_every_exemption_names_a_public_read_and_gives_a_reason` and `test_weighted_recall_is_the_only_production_caller_of_its_internal_step`.
> - (2) The seam: `test_the_prompt_recall_gives_nothing_from_a_store_holding_only_a_forged_memory[basic_tier, weighted_then_fallback]`. A real `CognitiveAgent`'s prompt recall over a real memory holding only a forged memory gives nothing, and the last fallback ran.
> - G1: `test_every_production_episodic_memory_is_bound` lists every construction. `test_rebuild_episodic_stores_through_the_bound_gates` runs the real command with `enforce_store` armed: the injection-pattern post is not stored, and the event reaches the emitter.
> - Each of the fourteen gated reads leaves the forged episode out only when armed (`test_each_gated_read_leaves_out_a_forged_source_only_when_armed`). Reporting-only binding changes no result (`test_with_every_flag_false_binding_changes_no_read`).
> - The tracker amendments are made, as this issue's acceptance asks.
>
> The statements at `episodic.py:1501` and `config_models/crew.py:155-156` now hold for every read except the eight exempt ones; they are unchanged.
>
> Not shown: no live store was read, and the event volume of the newly gated reads with flagged episodes is not measured. Open items: #1820 bf-984 F1 to F5.

### 8.2 New items on #1820

`- [ ] **bf-984 F1 (P3, security class; reach: injected only): derived artefacts can carry a forged episode with no provenance gap of their own.** AD-689's edge backfill reads every row through \`list_episodes\` (exempt by BF-984, \`knowledge/backfill.py:271\`); the procedure challenger reads a promoted procedure's source episodes with a bare \`get_by_ids\` (\`cognitive/procedure_challenger.py:628\`); procedures and consolidated memories the dream cycle built before BF-984 from \`recent\` or \`recall_by_intent\` were built ungated. Evidence: the allowlist in \`tests/test_bf984_recall_gate_coverage.py\`; #1830's blind spot. Not measured. **Smallest repair:** classify each producer of a derived artefact by its source read (evidence or history), and under \`enforce_provenance\` refuse a provenance-gap source episode, or carry its verdict into the artefact.`

`- [ ] **bf-984 F2 (P3; reach: the Captain, under enforcement): the Captain's memory views leave out a provenance-gap episode when \`enforce_provenance\` is armed.** \`/memory\` (\`experience/commands/commands_memory.py:34\`, \`recent(k=10)\`) and the memory graph (\`routers/memory_graph.py:198\`, \`:205\`, \`recent_for_agent\`) are gated reads, as AD-1293 already leaves out a self-contradicted episode there; the supported profile arms the flag. The Captain sees the \`memory_provenance_gap\` event, not the episode. Evidence: \`test_each_gated_read_leaves_out_a_forged_source_only_when_armed[recent, recent_for_agent]\`. **Smallest repair:** an opt-in parameter like \`include_self_contradicted\` on those two reads, used by the Captain's views, which show the episode marked.`

`- [ ] **bf-984 F3 (P3; reach: injected only, under enforcement; extends BF-938 G3): an enforced drop on the newly gated reads is not refilled.** The filter runs after the k-cap, as AD-1293's exclusion does, so a recency or intent read whose k newest episodes include forged ones returns fewer, and the prompt recall can fall through to nothing while older clean memories exist. Read at \`episodic.py\` (\`recent_for_agent\`, \`recent\`, \`recall_by_intent\`); not measured. **Smallest repair:** over-fetch, apply the verdict, then cap, as \`recall_with_confidence\`'s dense loop does; it must keep R4's one-report-per-returned-episode bound.`

`- [ ] **bf-984 F4 (P3; reach: operational): the event volume of the newly gated reads with flagged episodes is not measured.** BF-984 keeps BF-938's report-on-every-read policy (DECISIONS BF-984 D3). BF-938 measured 14,766 events in the busiest hour when 1,224 of 1,227 episodes were flagged, through the three gated paths, against \`SYSTEM_EVENTS\`' 50,000-message window, and 0 once \`wardroom_import\` was admitted (\`DECISIONS.md\`, BF-938). \`recent_for_agent\` runs on proactive think cycles and \`recent\` in the dream cycle. **Trigger:** a census, on a read-only copy of the live store with the Captain's authorisation, that shows flagged episodes, or AD-607j's counter (#1324). **Smallest repair if needed:** a bounded per-process dedupe by (episode id, event type) in \`_security_anomaly_drop\`.`

`- [ ] **bf-984 F5 (P3; reach: operator): the rebuild report counts an episode a gate skipped as written.** \`rebuild_from_wardroom\` increments \`episodes_written\` once \`store_episode\` returns (\`maintenance/rebuild_episodic.py:226-228\`), and the command's \`_store\` discards \`store\`'s outcome (\`__main__.py\` \`_cmd_rebuild_episodic._run\`). Since BF-984 the AD-610 gate runs on rebuilt episodes by default (\`storage_gate.enabled\` defaults to true), as does AD-607h when \`enforce_store\` is armed, so a skipped episode is reported as written, and BF-288's \`episodes_written > 0\` check resets the shutdown marker. Read, not measured. **Smallest repair:** \`_store\` returns the outcome; the report counts stored and gate-skipped episodes separately.`

## 9. What this does NOT change

- `_security_anomaly_drop`, `validate_recall_result`, `validate_provenance`, `KNOWN_MEMORY_SOURCES`, `MemorySecurityConfig` and every `enforce_*` default. The seven reads already gated. `store`. `recall_for_agent_scored`. `_fuse_dense_sparse_for_agent` (its hydrated ids are covered by EP2).
- AD-1293's exclusion and its call-site rule. AD-567d's activation tracking in agent recall, which still records the dense candidates before the filter, as before. AD-981a's FoK log line.
- `MockEpisodicMemory`, which still gates nothing (BF-938 R1). Federation inbound (AD-607f, BF-938 G5).
- The docstring at `episodic.py:1501` and the comments at `crew.py:155-156`; they now hold for every read except the eight exempt ones.
- `config-profiles.yaml`, `config/system.yaml`, `event_persistence.py`, `roadmap.md`, BF-938's contract and its three test files, and `rebuild_episodic.py`.
- No config field, `EventType`, route, table or flag is added.

## 10. Mutation rows (one campaign; restore between rows; run only the listed killers)

The run after M2, with all edits applied, is the campaign's base. Record the base tree and the sha256 of `episodic.py`, `cognitive_services.py`, `__main__.py` and the two new test files. On a later tree whose five files match, do not rerun; rerun a row only if its file differs.

Equivalent mutants (not rows):
- dropping `query=query` from the filter calls (`validate_recall_result` never reads `query`);
- removing the filter's early `return` when unbound (the verdict also returns `False` then).

| # | Site | Mutate to | Killed by |
|---|---|---|---|
| M-EP2a | EP2: `episodes = self._drop_security_anomalies(episodes, query=query)` | deleted | R1[recall_for_agent], R1[recall_for_agent_with_confidence], R3[both], R5, S1[both] (**not A2**: agent recall still reaches the verdict through `get_by_ids`; section 16, O8) |
| M-EP2b | EP2: the same line | moved below the `if _pre_exclusion and not episodes:` block | R5 |
| M-EP3 | EP3: `recent_for_agent`'s return | `return self._drop_self_contradicted(episodes, include_self_contradicted)` | R1[recent_for_agent], R3[recent_for_agent], S1[basic_tier], S1[weighted_then_fallback], A2 |
| M-EP4 | EP4 | the filter removed | R1[recall_by_intent], R3[recall_by_intent], A2 |
| M-EP5a | EP5 | the filter removed | R1[recent], R3[recent], R4, A2 |
| M-EP5b | EP5 | the filter applied before the cap: `return self._drop_self_contradicted(self._drop_security_anomalies([self._metadata_to_episode(d, doc, m) for d, m, doc in paired])[:k], include_self_contradicted)` | R4 |
| M-EP6 | EP6 | the filter line deleted | R1[retrieve_contrastive_episodes], R3[retrieve_contrastive_episodes], A2 |
| M-EP7a | EP7: the evidence branch | `return self._drop_self_contradicted(ordered, False)` | R1[get_by_ids_for_evidence], R3[get_by_ids_for_evidence], A2 |
| M-EP7b | EP7 | `if not for_evidence: return self._drop_security_anomalies(ordered)` | R2[get_by_ids] |
| M-EP1a | EP1: the filter's body | `return episodes` | A2, the 7 new R1 rows, the 7 new R3 rows, R4, R5, S1[both] |
| M-EP1b | EP1: the comprehension's condition | `not self._security_anomaly_drop(...) and not validate_provenance(episode)[1]` (it drops every provenance gap whatever the flags; import inside the function) | the 7 new R3 rows, R4 |
| M-T1 | `_EXEMPT` | add `"recent": "x"` | A2 |
| M-T2 | `_EXEMPT` | delete the `"list_episodes"` entry | A2 |
| M-T3 | `_EXEMPT` | add `"no_such_read": "x"` | A3 |
| M-CS1a | CS1: the three AD-607 setter lines | deleted | `test_bf938_ad607_binding.py::test_startup_binds_the_memory_security_config_store_gate_and_emitter`, `::test_each_ad607_setter_has_a_production_caller`, B2[both], B3[both], B4, and BF-938's `::test_a_bound_store_gate_rejects_...[off, on]`, `::test_a_store_gate_or_emitter_that_raises_never_breaks_store`, `::test_the_supported_profile_drops_...[default, supported]` and `test_bf938_mock_episodic_binding.py::test_startup_binds_the_in_memory_mock_and_the_mock_gates_nothing` |
| M-CS1b | CS1: `if config.storage_gate.enabled:` | `if True:` | B2[off] |
| M-CS2 | CS2: `bind_episodic_memory_gates(episodic_memory, config, emit_event_fn)` | deleted | `test_bf938_ad607_binding.py::test_startup_binds_...`, `::test_a_bound_store_gate_rejects_...[off, on]`, `::test_the_supported_profile_drops_...[supported, default]`, `test_bf938_mock_episodic_binding.py`, B1, `test_bf938_ad607_binding.py::test_a_store_gate_or_emitter_that_raises_never_breaks_store` |
| M-MN3a | MN3: the binding call | deleted | B1, B4 |
| M-MN3b | MN3 | `bind_episodic_memory_gates(em, cfg, None)` | B4 |

**Unchanged-file check:** `git diff --stat <base> HEAD` lists exactly:
- `episodic.py`, `cognitive_services.py`, `__main__.py`;
- `tests/test_ad819_rebuild_episodic.py` and the two new test files;
- `PROGRESS.md`, `DECISIONS.md`, `docs/research/reference-projects.md` and the ledger pair;
- this prompt.

## 11. Verified Against Codebase (2026-11-20, `d57631f6`)

```
src/probos/cognitive/episodic.py
  :1201-1218 resolve_recall_tier_params (basic use_salience_weights False :1212)
  :1477-1479 _security_config/_security_gate/_security_event_emitter = None   :1496-1514 setters
  :1516-1532 _emit_security_event (no dedupe)   :1534 def _security_anomaly_drop   :1545-1547 None -> False
  :1561 MEMORY_RECALL_ANOMALY  :1569 MEMORY_PROVENANCE_GAP  :1573-1574 enforce_provenance  :1585-1587 fail open
  :1586 "AD-607: recall anomaly gate failed" (grep -c 1)   :1589 def set_retroactive_evolver
  :2009 store -> EpisodeStoreOutcome  :2093-2142 AD-610 / AD-607h store gates  :2277-2280 get_episode_metadata -> dict | None
  :2298 list_episodes  :2331 iter_live_episodes  :2371 get_by_ids  :2418-2421 evidence branch (grep -c 1)
  :3021 iter_archived_episodes  :3056 lookup_archived_by_id  :3063 lookup_archived_by_agent  :3080 restore_from_archive
  :3401-3432 _drop_self_contradicted  :3540 / :3631 / :5057 / :5281 the four verdict calls
  :3684 retrieve_contrastive_episodes  :3712-3720 band  :3729-3733 exclusion (grep "contrastive, include_self_contradicted" 1)
  :3898-3913 recall_for_agent shim  :3915 recall_for_agent_with_confidence  :4035-4042 AD-567d  :4050-4053 fusion
  :4055-4060 exclusion + band reset ("sovereign fusion" 1)  :4105-4108 hydration, no verdict
  :4132-4180 recent_for_agent (":4179 single-pass scan" 1)  :4182-4223 recall_by_intent (:4223 "...)  # AD-1293" 1)
  :4225-4253 recent (:4247 "_drop_self_contradicted(  # AD-1293 (#1200)" 1)  :4618 keyword_search -> list[tuple[str, float]]
  :4651 recall_for_agent_scored  :4741-4742 @staticmethod score_recall  :4866 recall_weighted -> recall_for_agent_scored
  :5049-5062 weighted verdict after budgeting  :5066-5079 recall_valid_at  :5083 recall_by_anchor
src/probos/cognitive/memory_security.py :188-226 validate_recall_result (query unused)
src/probos/startup/cognitive_services.py :14 Callable  :20-25 TYPE_CHECKING SystemConfig  :42-51 wire_erasure_sidecar_paths
  :54 _run_one_migration  :164 init_cognitive_services  :189 emit_event_fn  :313-340 the two binding blocks
src/probos/__main__.py :20 import logging  :28 typing (no Any)  :516-519 _load_config_with_fallback  :567 _boot_runtime  :619 EpisodicMemory(
  :2217 _cmd_rebuild_episodic  :2275 async def _run  :2290-2296 comment + imports  :2298 cfg  :2299-2308 construction  :2309-2312 start/try
  :2315-2316 em._collection (pre-existing)  :2324-2325 _store
src/probos/cognitive/storage_gate.py :37-42 StorageGate(config, emit_event_fn=None)
src/probos/config_models/cognition.py :356-363 StorageGateConfig.enabled True ; config_models/crew.py :148-161 MemorySecurityConfig
src/probos/config.py :217-218 TRUST_COMMANDER/TRUST_LIEUTENANT ; :1111-1121 recall_tiers basic
src/probos/crew_profile.py :30-47 Rank, from_trust ; earned_agency.py :61-68, :100-128, :131-147 ; crew_utils.py :58-76
src/probos/cognitive/cognitive_agent.py :677-705 _filter_query_echoes  :708-724 _dm_recall_query  :11579 _recall_relevant_memories
  :11724-11752 tier  :11814-11849 weighted/basic  :11876-11883 fallback  :12132 recent_memories  :12149-12151 BF-138  :12445-12466 anchor recall
src/probos/cognitive/source_governance.py :617-620 parse_anchor_query(query, known_callsigns=None)
src/probos/maintenance/rebuild_episodic.py :128-172 _row_to_episode_kwargs (wardroom_import)  :175-231 rebuild_from_wardroom
src/probos/cognitive/episode_archive.py :236-247 ArchiveLookupResult.episodes
src/probos/events.py :364-368 MEMORY_* ; event_persistence.py :298-302
tests/test_bf938_ad607_recall_gate.py :31-36 constants  :39-49 _Recorder  :56-66 _episode  :76-83 _standard  :86-96 _memory  :121-122 R1 exact
tests/test_bf938_ad607_binding.py :38 _INJECTED  :41-51 _Recorder(event, data=None)  :80 storage gate off  :170-181 AST guard
tests/test_bf938_mock_episodic_binding.py :18 imports the binding module (the precedent for test-module imports)
tests/test_ad819_rebuild_episodic.py :16-22 imports  :25-98 _build_wardroom_fixture  :406-419 _FakeEM (no setters)  :421-427 config=None
tests/test_ad1357_context_manifest.py :122-144 runtime + agent construction
DECISIONS.md :1661 ### BF-991 heading ; :2133 measured ; :2134 "do not (#1830)." ; :2136 "stores without the store gate."
PROGRESS.md :1 header ; :40 "binds neither gate (G1; #1830)." (grep -c 1)
roadmap.md :1139 ; open-ads-report.md :32
git ls-files --eol: i/lf w/crlf for the six edited files
```

## Absence Verified (2026-11-20)

| | CLAIM | RUN | FOUND | HOLDS |
|---|---|---|---|---|
| AV1 | The only production setter calls are startup's | Grep `\.set_storage_gate\(\|\.set_security_(config\|gate\|event_emitter)\(` over `src/probos` | `cognitive_services.py:322`, `:337`, `:338`, `:339` | yes |
| AV2 | Two production constructions | Grep `EpisodicMemory\(` over `src/probos` | `__main__.py:619`, `:2299`; `episodic_health.py:362` is a docstring | yes |
| AV3 | `recall_for_agent_scored` has one production caller | Grep `\.recall_for_agent_scored\(` over `src/probos` | `episodic.py:4866` | yes |
| AV4 | The evidence and history callers of `get_by_ids` | Grep `\.get_by_ids\(` over `src/probos` | `for_evidence=True`: `proactive.py:2194`, `diagnostic_context.py:311`, `procedure_challenger.py:614`; bare: `continuous_promotion.py:52`, `erasure.py:594`, `procedure_challenger.py:628`, `episodic.py:3628`, `:4107` | yes |
| AV5 | No test binds a config and pins an ungated new read | Grep the setters over `tests`, then each hit for `recall_for_agent\|recent\|recall_by_intent\|get_by_ids\|contrastive` | 5 files; `test_ad607_memory_security.py:359` is a string only | yes |
| AV6 | No source-scan test pins a changed line | Grep `episodic.py"\|__main__.py"\|cognitive_services.py"` over `tests` | `test_ad593:117` (threshold strings), `test_self_monitoring:744` (jaccard import), `test_bf781:376` (`wait_for`), `test_ad1341_s1_promotion:404` (`resolve_records_repo_path`), the BF-938 B4 guard (receiver kept), the AD-1346 census fixtures (whole file outside the runtime) | yes |
| AV7 | BF-984 is free and belongs to #1830 | `gh issue list --state all --search "BF-984 in:title"`; `git log --all -i --grep=BF-984`; Glob `prompts/bf-984*`, `tests/test_bf984*` | #1830 only; no commit; no files | yes |
| AV8 | The "2,500 an hour" figure has no source | The orchestrator's reads plus mine of `DECISIONS.md:2133` | 14,766/h, about 242/h and 0 are documented; 2,500 is not | the figure is withdrawn |
| AV9 | The lookups are selected only through `ArchiveLookupResult` | Read `:3056-3078` | `-> ArchiveLookupResult` | yes |

## 12. Deterministic checks, resolved up front

- `gate._memory` uses `relevance_threshold=0.0`, so the agent threshold `min(0.0, ...)` keeps every owned candidate (`:3963`). With `k=5` and 4 episodes, no k-cap bites in R1 and R3.
- Timestamps at `_T0` (2023) keep BF-039's last-hour rate limit away. `seed` writes all four (premise asserted).
- `intent_type` is `outcomes[0]["intent"]` = `"report"` (`:4353-4357`).
- The anchored store gives `recall_by_anchor(department="engineering")` all four. BF-938's R7 measured the same filter on two anchored episodes; the anchor view's department matches, so no mismatch.
- `_MidBand` keeps `count()` and real metadata. `n_results = min(5*5, 4) = 4`, and every distance is 0.5, inside [0.4, 0.65].
- S1:
  - the episode text does not contain the query (BF-631's echo filter, `:677-705`);
  - the enhanced tier's `anchor_confidence_gate` 0.3 can empty weighted recall even unbound, but the premise checks the memory reaching the prompt, not which path brought it;
  - `sovereign_id` defaults to `""` (`substrate/agent.py:44`), so `mem_id` is the agent id.
- B4 replaces `_load_config_with_fallback` and `_log_rebuild_memory_event` by name; `_run` looks both up at call time. `raising=False` lets the base run the ungated command, so the base is red for the defect itself.
- R3's ordered comparison: `recall_by_anchor_scored`'s and `recall_weighted`'s recency weight depends on `time.time()`, but over three years of age it is about 0, and the sorts are stable (BF-938 R2 compares the same).

## 13. Prior art and blind spots

**Internal:**
- **AD-1293's `_drop_self_contradicted`** (`episodic.py:3401-3432`): absorbed. It uses the same shape (one shared exclusion at the end of every evidence read, after fusion) and the same call-site rule, which is why `get_by_ids` is gated only for evidence.
- **BF-938's contract and register** (`prompts/bf-938-ad607-security-gate-binding.md`, G1 to G9): G1 and G8 are fixed here; G3 is extended by F3.
- Consult `54da016e` and the orchestrator's AST call graph and premise probe.

**External** (date used 2026-11-20):
- **Complete mediation** (Saltzer and Schroeder, 1975): every access to every object is checked. Absorbed as the enumeration test, a static proof that each read path reaches the verdict or is exempt with a stated reason (reachability, not application to the read's own result: section 16).
- **OWASP LLM08:2025, Vector and Embedding Weaknesses**: it recommends permission-aware vector stores, data validation and source authentication. Absorbed: the check sits in the store's read API, not in each consumer.
- **Permission-aware RAG guidance**: it argues for filtering inside the query (pre-filter) rather than after top-k. Considered and rejected here, because ProbOS's default mode must report and keep, which a query predicate cannot do. The refill cost is recorded as F3.

**Reference projects** (`docs/research/reference-projects.md`):
- RAGFlow (memory section, 180-day interval, last reviewed 2026-05-08, so overdue): one search found nothing specific to RAGFlow on retrieval-time filtering; nothing new. **Row update for the orchestrator (applied as pair RP1, 7.10):** `| RAGFlow | 2026-11-20 | checked | \`ragflow-absorption.md\`; BF-984 (#1830) Prior Art, \`prompts/bf-984-recall-gate-every-read.md\` (a search found nothing on RAGFlow retrieval-time filtering; nothing new) |`
- LoCoMo (overdue): considered, deferred, because it is a recall-quality benchmark, not access control.
- MCP Apps (overdue) and AG-UI (never reviewed): considered, deferred as unrelated.

**Blind spots, recorded:**
- Derived artefacts (F1).
- The Captain's views (F2).
- Unrefilled drops (F3).
- Event volume (F4).
- The rebuild report's count (F5).
- AD-567d records access for candidates that the filter then drops in agent recall. Those candidates were returned before BF-984, so this is no regression.
- `recall_by_intent` judges provenance only, with no anchor view.
- `MockEpisodicMemory` gates nothing, by design.

## 14. Diff Reviewer: properties to verify

1. Each of the six reads calls `_drop_security_anomalies` exactly once, on the list it returns, after `_drop_self_contradicted`. In agent recall the call comes before the band reset. In contrastive recall it comes before the `CONTRASTIVE_RECALL` emit. `get_by_ids`'s bare branch is unfiltered.
2. The filter returns its input unchanged when no config is bound, drops only through `_security_anomaly_drop`, and adds no exception path. The seven reads already gated are not passed through it again, so there is no second report; `recall_weighted` still calls the ungated `recall_for_agent_scored`.
3. No change to `_security_anomaly_drop`, `validate_*`, `MemorySecurityConfig`, any `enforce_*` default, `store` or `KNOWN_MEMORY_SOURCES`.
4. `bind_episodic_memory_gates` binds what the removed startup block bound, in the same order and exception tiers: AD-610 wrapped, AD-607 unwrapped. `init_cognitive_services` calls it under `if episodic_memory:`. The rebuild calls it inside the `try` after `start()`, so `stop()` still runs.
5. `_log_rebuild_memory_event` logs only the event type and episode id: never the text, pattern or reason.
6. Each `_EXEMPT` reason matches the method's docstring and callers. The enumeration pins no line numbers. Every test asserts its premise first, and no assertion pins the faulty behaviour.
7. No change outside the files of section 10. BF-938's tracker text changes only by bracketed insertions. No commit subject carries an `AD-` or `BF-` token.

## 15. Acceptance criteria and the orchestrator's first-hand checks

**Acceptance:**
1. Section 6's columns hold, and the base columns were observed and recorded.
2. The M1 and M2 focused gates are green, and every row of section 10 is killed by its named tests.
3. The tracker texts are as in 7.7 and 7.8. The ledger is regenerated and `--check` is clean. No roadmap row.
4. One broad gate with a receipt. One PR that says `Refs #1830`. The texts of section 8 are posted after the merge.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**First-hand checks on the oracle tree, before the Builder starts:**

| O | Check | Expected |
|---|---|---|
| O1 | `git rev-parse origin/main` and the tree | `d57631f6` / `6042baae`. If main has moved, `git diff --stat d57631f6 origin/main --` over the six edited files must be empty, or re-match every SEARCH block |
| O2 | Each SEARCH block (EP1 to EP7, CS1, CS2, MN1 to MN3, TA1, TR1, TR3, RP1) and each substring (TR2, TR4, TR5), matched with line endings normalised | Exactly one match each (19) |
| O3 | Only 7.1 added, run at `-n 0` | 19 red and 21 green, with the reasons of section 6. In particular, R1 and R3 for `recall_by_anchor`, `recall_by_anchor_scored`, `recall_valid_at` and (base red) `retrieve_contrastive_episodes` pass their premise of all four unbound. That closes the probe's inconclusive and skipped rows. If any premise fails, stop and report; do not loosen it |
| O4 | A1 on the base | Green. If the list of unannotated public methods is not empty, report the names; do not add annotations |
| O5 | EP1 to EP7 applied | 7.1 is 40 green. The M1 focused gate is green; BF-938's R1 still records exactly one `[_FORGED]` per event type |
| O6 | 7.2 on the M1 tree | 6 red: B1 lists `("__main__.py", "_cmd_rebuild_episodic._run")`; B2 and B3 raise `ImportError`; B4 shows the injected id persisted |
| O7 | CS1, CS2 and MN1 to MN3 applied without TA1 | `test_ad819...::test_successful_rebuild_resets_marker` red with `AttributeError ... 'set_security_config'`. With TA1 it is green, and the M2 focused gate is green |
| O8 | The campaign of section 10 on the M2 tree | Every row killed by exactly its listed tests. Record it as the campaign of record, with the five sha256 values |
| O9 | AV7 again, just before the PR | Only #1830 |
| O10 | After M3: the generator's `--check` and `tests/test_ad1184_ad_ledger.py` | Clean and green |

Sources:
- [OWASP LLM08:2025 Vector and Embedding Weaknesses](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/)
- [Saltzer and Schroeder, The Protection of Information in Computer Systems (1975)](https://www.cs.virginia.edu/evans/greatworks/saltzer.pdf)
- [Implementing Complete Mediation (Cornell CS513 notes)](https://www.cs.cornell.edu/courses/cs513/2005fa/NL05.html)
- [Permission-aware RAG: enforcing document ACLs at retrieval time](https://dev.to/venkathub/permission-aware-rag-enforcing-document-acls-at-retrieval-time-54a7)
- [Permission-aware retrieval in enterprise RAG](https://dev.to/alaikrm/permission-aware-retrieval-the-missing-layer-in-enterprise-rag-security-199f)

## 16. The orchestrator's first-hand checks (2026-11-20, an oracle tree at `d57631f6`, whose tree is `6042baae`)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py`, and every check of section 15 was run, before the Builder started. The new tests ran under the real embedding model and under `PROBOS_EMBEDDINGS=local`, as CI runs them. Results:

| O | Result |
|---|---|
| O1 | The oracle tree is `d57631f6`, tree `6042baae`. `origin/main` had not moved when the contract was assembled. |
| O2 | All 18 SEARCH blocks and substrings (EP1 to EP7, CS1, CS2, MN1 to MN3, TA1, TR1 to TR5) occur exactly once, in files that are CRLF throughout. RP1 (7.10) is the 19th. |
| O3 | The coverage file alone: 19 failed, 21 passed. Failures: A2 (seven reads, `get_by_ids`, `recall_by_intent`, `recall_for_agent`, `recall_for_agent_with_confidence`, `recent`, `recent_for_agent` and `retrieve_contrastive_episodes`, each "neither reaches the verdict nor is exempt"); R1 and R3 for the same seven (the forged id is returned, and no provenance event is reported); R4; R5; both S1 cases. The R1 and R3 premises of `recall_by_anchor`, `recall_by_anchor_scored` and `recall_valid_at` hold (all four episodes unbound), which closes the inconclusive and skipped rows of the probe, and the contrastive read's premise holds through D6's proxy. |
| O4 | A1, A3 and A4 are green on the base, and no public method lacks a return annotation. |
| O5 | EP1 to EP7 applied: the coverage file is 40 green (23 s with the real model; 58 passed together with BF-938's recall-gate file under `PROBOS_EMBEDDINGS=local`). The M1 focused gate: 335 passed, 1 skipped (the AD-981a case that needs real-model similarity). BF-938's R1 still records exactly one `[_FORGED]` per event type. |
| O6 | 7.2 on the M1 tree: 6 failed. B1 lists `[("__main__.py", "_cmd_rebuild_episodic._run")]`; B2 (two cases) and B3 (two cases) raise `ImportError: cannot import name 'bind_episodic_memory_gates'`; B4 shows the injected id persisted. |
| O7 | CS1, CS2 and MN1 to MN3 without TA1: the six cases pass and `test_ad819_rebuild_episodic.py::TestShutdownMarkerReset::test_successful_rebuild_resets_marker` fails with `AttributeError: '_FakeEM' object has no attribute 'set_security_config'`. With TA1 it passes, and the M2 focused gate gives 119 passed. |
| O8 | The campaign of section 10 (`audit\mutants_bf984.py`) on the M2 tree, whose seven test files (the two new ones, BF-938's recall-gate, binding, mock and source-guard files, and `test_ad819_rebuild_episodic.py`) give 99 cases, all green unmutated: **all 19 rows killed, none survived.** Fifteen rows are killed by exactly the cases the draft named. Four differ, and section 10 now lists the measured sets: M-EP2a is **not** killed by A2 (agent recall still reaches the verdict through `get_by_ids`' evidence branch, so the enumeration, which proves reachability, stays green; the other seven named cases fail, and R1, R3, R5 and S1 are what pin the line); M-EP1b is also killed by R4; M-CS1a is also killed by six cases of BF-938's files; M-CS2 is also killed by one. |
| O9 | AV7 (BF-984 in the issue snapshot, `git log --all`, `prompts/bf-984*` and the GitHub titles of all states): only #1830, 2026-11-20 14:15Z. It is run again before the PR. |
| O10 | The trackers TR1 to TR5 applied on the oracle, then `gen_ad_ledger.py` regenerated the ledger pair and `--check` reported "AD/BF ledger is current". The ledger test runs when M3 is built. |

The base of the campaign of record (the files after M1 and M2; blob id, sha256 of the LF text, lines):

| File | Blob | sha256 (LF text) | Lines |
|---|---|---|---|
| `src/probos/cognitive/episodic.py` | `ffc4223d0392c1368b564e1862a0a8344dcbbdfa` | `31281a2d198bc72110118c267910ea3651e279ce5c58bc8908b79af52ad9360d` | 5328 |
| `src/probos/startup/cognitive_services.py` | `9b43cbb8c6113b4113af355836881f6f1a9c9de1` | `9f9345c114fb3df2b1557b25be8bfb6e28da1ae1f95a08b6772445786621222a` | 813 |
| `src/probos/__main__.py` | `7ae76d6f2db86dc2dda10ad1aec81221bc2db416` | `145bbfa51588f4d5e1d446915494be9fe0d1c6b21bae5c6d417d66d3ffda1d22` | 4650 |
| `tests/test_ad819_rebuild_episodic.py` | `182ea142b25b0acb40bf529594907a14563102ec` | `05725f52e38a414f98a72f9f2155cb11dff5e604b11924d79e2b07df70014e8a` | 477 |
| `tests/test_bf984_recall_gate_coverage.py` | `0a8c0ac57c830e48817d7de7a0cfe63a1103532c` | `a56f3c1723de624ec55cc36e609733fe1aa9b0355e1d8573393c52aebae24aca` | 418 |
| `tests/test_bf984_rebuild_binding.py` | `b768766f53642de18bc087f88a1705974feea45e` | `f59ae10e39de1222f83710b5c56b22257efd7ba9ddeddcbb18157dcfad02081b` | 130 |

A2 and the enumeration, stated plainly: A2 proves that every public read reaches AD-607's verdict through some chain of `self` calls or is exempt with a reason. It does not prove that a read applies the verdict to its own result: `get_by_ids` is a hub that reaches the verdict on its evidence branch, so a read that calls it passes A2 even if its own filter line is deleted (M-EP2a). Each gated read's own application is pinned by its R1 and R3 cases, and a new public read that reaches the verdict by no path, or is not listed, fails A2.
