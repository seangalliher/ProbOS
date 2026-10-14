# AD-1326 — Procedure evolution keeps the champion until a challenger wins head-to-head (#1510)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 (execution findings: fixtures, last-resort reach, executed premises)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 (review round 1: F1-F8, doc corrections; decisions in D9)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 (review round 2: R2-1..R2-6; decisions in D10)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 (review round 3: R3-1..R3-8; decisions in D11)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-13 (review round 4: R4-1..R4-4; decisions in D12)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14 (review round 5: R5-1..R5-4; decisions in D13)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14 (review round 6: R6-1, R6-2; decisions in D14)

**Status:** Build-ready contract. Base `a71575ec` (main, AD-1327 merged). Delegated AD Execution Mode; every decision below is in-envelope (backward compatible, legacy flag, no schema change to `procedures.db`, no control weakened).
**Issue:** #1510. AD-1326 is already allocated to it (`scripts/ad_ceiling.py` on this worktree: ceiling AD-1327, next AD-1328; no new number is allocated here).
**Dependencies:** AD-1327 (#1511, merged): `VerifierJudgePolicy`, `JudgeProvenance`, `LLMResponse.answered_tier/answered_model`. AD-1324: `LLMRequest.min_tier` stakes floor.
**Estimated tests:** about 77 new, plus 14 pinned-count/fixture updates in 9 existing test files (revision: +2 fixture lines, 13h-13i). Review round 1 adds about 30 (named in Tests, marked "R1") and moves two test-side pins (the `_PROMPT` regex of `tests/test_ad1326_procedure_challenger.py`, the `min_decisions`/`held_out_episodes` bound cases of `tests/test_ad1326_config.py`). Review round 2 adds about 7 (marked "R2") and moves the expectations of about 6 existing AD-1326 tests (listed under Hidden Pins, "R2"). Review round 3 adds about 24 (marked "R3"), moves four AD-1326 premises and one fixture line outside AD-1326 (`tests/test_ad579c_validity_dream.py`, 13j), all listed under Hidden Pins, "R3". Review round 4 adds about 9 (marked "R4") and moves one AD-1326 premise (Hidden Pins, "R4"). Review round 5 adds about 8 (marked "R5", one parametrized over the five ledger reads) and moves one AD-1326 assertion and one test helper (Hidden Pins, "R5"). Review round 6 adds about 5 (marked "R6"), returns the R5 assertion to its round-4 form and gives one test helper one forwarding method (Hidden Pins, "R6").
**Milestones:** 3, a fresh Builder each (about 150 calls each).

---

## Problem

Dream consolidation promotes every FIX rewrite of a procedure the moment it is written. Three call sites save the rewrite and retire its parent with no comparison:

| Site | Path | Save | Parent retired |
|---|---|---|---|
| Step 7b degraded scan | `src/probos/cognitive/dreaming.py:1894-1926` (`_evolve_degraded_procedures`) | `:1910` | `:1920-1924` `deactivate(parent.id, superseded_by=...)` |
| Reactive / proactive | `dreaming.py:2012-2045` (`_attempt_procedure_evolution`) | `:2030` | `:2039-2043` |
| Step 7d fallback learning | `dreaming.py:2197-2232` (`_process_fallback_learning`) | `:2215` | `:2226-2230` (`execution_failure` only; near-miss types save the FIX **active beside** the parent) |

A worse rewrite therefore replaces a better procedure, and the only way back is a later rewrite that is equally unchecked. MASS (arXiv:2610.12176; `docs/research/mass-self-supervision-absorption.md`) measured exactly this regression pattern and found the guard that works: keep a champion, judge each challenger against it pairwise, replace only on a win, and run the optimizer on a stronger model.

All procedure LLM calls run on `tier="standard"` (`procedures.py:206, 515, 654, 787, 874, 1029, 1157, 1294`, verified below), including the three that *rewrite* procedures.

## Solution

1. **Challenger, not replacement.** A FIX rewrite (all three sites, including near-miss fallback FIX) is saved through the existing `ProcedureStore.save` with `is_active=False`, linked to its champion by the `parent_procedure_ids` the evolution already sets, and recorded `pending` in a new **`ProcedureChallengeLedger`** (new module, own file `procedures_challenges.db` beside `procedures.db`, `ConnectionFactory`, lifecycle owned by `ProcedureStore.start/stop`). The champion stays active, so routing (`find_matching` filters `is_active`, `procedure_store.py:780`; `list_active`, `:687`) keeps using it. `procedures.db`'s schema is not touched.
2. **Head-to-head evidence.** Before the rewrite, `ProcedureChallenger.prepare` splits the recalled episodes: held-out episodes (odd positions) never enter the rewrite prompt. Dream **Step 7d-2** (`ProcedureChallenger.run_cycle`) judges each challenger against its champion on the first `used_contexts` episodes the rewrite saw plus all held-out ones. The judge sees one real situation and both candidates' replay output (their step lists, AD-534), unlabelled as "Candidate 1/2", **in both orders**; a candidate wins a situation only when it wins in both orders. No absolute scores.
3. **Ranking.** Bradley-Terry (MM, pair pseudo-counts, champion pinned to 1.0) over the counted outcomes ranks the complete challengers of one champion; the top one is promoted only if its own record against the champion has at least `min_decisions` judgements and a win share strictly above `0.5 + margin`.
4. **Bounded and honest.** Judge calls are budgeted per dream cycle; budget exhaustion defers (never promotes). A challenger still pending after N cycles, or that loses, is retired; nothing is deleted. Every judgement (both orders, bounded reason, `JudgeProvenance`) is a ledger row; one DURABLE event `PROCEDURE_CHALLENGE_DECIDED` carries the decision and counts.
5. **Optimizer on `deep`.** The three rewriting calls request `tier="deep"` with AD-1324's floor `min_tier="standard"` (chain deep -> standard, never fast). The judge uses AD-1327's `VerifierJudgePolicy`: the `verifier` tier when configured, else `standard`, never `deep`.
6. **Legacy flag.** `dreaming.procedure_challenger_enabled` (default `True`). `False` builds no challenger service, and `DreamingEngine` keeps today's FIX handling: Step 7b, the proactive scan and an execution-failure fallback FIX deactivate the parent on save; a near-miss fallback FIX is saved active beside its parent, as today (Problem table). The three rewrites run on `deep` with the `standard` floor in both modes (item 5). DERIVED evolution is unchanged in either mode except for its rewrite tier.

---

## Design decisions (ranked; first option chosen)

### D1 — Challenger representation
1. **Chosen: ordinary `procedure_records` row saved `is_active=0`, `superseded_by=''`, `parent_procedure_ids=[champion]`; status and evidence in a new `ProcedureChallengeLedger` (own module, own file `procedures_challenges.db`, `ConnectionFactory`), opened and closed by `ProcedureStore`'s lifecycle; the store holds the ledger's connection itself (D1b).** `is_active` keeps its one meaning, "routable". Promotion uses the existing public `ProcedureStore` methods (`get`, `save`, `deactivate`, `get_evolution_metadata`) plus, since review round 1, `sync_routing_index` (D9, F1). Stores with no challengers are unaffected (the ledger is empty). `ProcedureStore` grows by one private method, one property, two attributes, the ledger's open/close lines and (review round 1) one public method; its `srp-size` row (`architecture-baseline.yaml:606-614`) keeps the same triggers (`lines`, `methods`).
2. Add `challenger_of`/`status` columns to `procedure_records` by `ALTER` migration — grows the frozen module, migrates a 15.7 MB live table, and moves three `PRAGMA table_info(procedure_records)` pins. Loses on compatibility and SRP.
3. Companion tables inside `procedures.db` on `ProcedureStore`'s connection — needs a private-connection accessor (Demeter), shares the store's `threading.Lock` held across `await` (`procedure_store.py:540`, `:992`, `:1070`) and its interleaved commits, and forces declaring `ProcedureStore` and deleting its `store-baseline.yaml:54-57` row. Loses on safety.
4. Keep the challenger only in the ledger until promotion — avoids re-saving a row on promotion, but the challenger is invisible to `store.get`, the API and Ship's Records, and contradicts the acceptance line "stored inactive, linked to the champion". Loses on correctness to the issue.

Lineage: the challenger is a child of the champion in `procedure_lineage_parents` from the moment it is saved (`_save_to_index`, `:578-583`). On promotion the champion gets `superseded_by=<challenger>` through `deactivate`, exactly as legacy. On retirement the procedure row is left as it is (inactive); the ledger says why.

### D1b — Who holds the ledger's connection (revision 2026-10-13, executed finding)
Executed: with the first draft (the ledger opened and held its own connection, `store._challenges._db`), `tests/test_issue1419_failed_start_rollback.py::test_a_real_boot_is_rolled_back_when_every_component_that_can_stop_raises[before]` failed on one leftover `Thread-NNNN (_connection_worker_thread)`. BF-882's last-resort close (`startup/shutdown.py:441-470`, `_direct_connections`) reads `vars(component)` one level deep, by design ("a connection held deeper than one attribute level ... is not found", `:455-458`), so when `ProcedureStore.stop()` raises before cleanup the ledger's connection is never closed and its non-daemon worker thread keeps a failed boot's interpreter alive.
1. **Chosen: `ProcedureStore` opens the ledger's connection through its own `connection_factory`, holds it as the direct attribute `_challenges_db`, and hands the open connection to the ledger; `_close_resources` closes it.** The ledger keeps its own `asyncio.Lock`, its schema and every method; it only stops owning the open/close (`start` applies the schema on the given connection, `detach` lets go of it). `_direct_connections(store)` then names `_challenges_db` beside `_db`, so the existing last resort closes it with no change to `shutdown.py` or any 1419 pin. A ledger that cannot open still leaves the store running (the connection is closed and cleared, one WARNING). Still one `ConnectionFactory.connect` per file (db-connect stays 30), no new `ProcedureStore` method, no new private reach in production.
2. Teach `_direct_connections` one more level (or a declared `last_resort_connections()` hook on components) — reverses BF-882's stated "one level, no deeper" contract and the residual named in the 1419 test docstring (`:2471-2474`), and adds private-attribute traversal in production for one component's convenience. Loses on scope and Demeter.
3. The ledger as its own runtime component with its own rollback step — touches at least seven pins: a runtime attribute and its startup wiring (`runtime.py:2896-2908` area), a new step in `shutdown.py`, the ordered step table `_STOPPED_COMPONENTS` in the 1419 test (`:1127-1174`, beside `("_procedure_store", "procedure store stop")` at `:1153`), `_EVERY_BREAKABLE_COMPONENT` (`:2499-2504`) and its `{attribute: 1}` call-count pin (`:2527-2529`), the store declaration's `lifecycle_owner`, and a second injection into `ProcedureChallenger`; a ledger that fails to open becomes a separate boot failure mode. Loses on pin count and SRP of the wiring.
4. Ledger tables `ATTACH`ed to the store's `procedures.db` connection — D1 option 3 again, on the store's `threading.Lock`, now a reproduced event-loop deadlock (Prior Art 7). Loses on safety.

### D2 — Where evidence lives; the event
1. **Chosen: ledger rows.** `procedure_comparisons` holds one row per judged situation: episode id, split (`used`/`held_out`), which side was shown first, combined outcome, `counted`, and both judgements (`shown_first`, `winner`, bounded `reason`, `JudgeProvenance` JSON). `procedure_challenges` holds status, `decision_reason` and `decided_at`. `procedure_challenge_cycles` holds per-cycle counts (judge calls, situations judged, deferred, promoted, retired), written only for a cycle that did something. **One DURABLE, router-written event `PROCEDURE_CHALLENGE_DECIDED`** (ids, decision, reason code and counts; no LLM text) gives events.db an audit trail of the ship changing its own routing, beside `SELF_MOD_*` and `DESIGN_GENERATED`.
2. OPERATIONAL event — no durable trace in events.db for a change that alters routing. Loses on audit.
3. `DreamReport` fields — `asdict` and `dream_adapter.py:43` mapping pins, and per-cycle counts would vanish with the report. Loses on compatibility.
4. Evidence as Ship's Records YAML — one git commit per comparison. Loses on cost.

### D3 — The head-to-head judge
1. **Chosen: replay output on a real situation, unlabelled, asked in both orders, win only on agreement.** A procedure's output is what replay hands the agent: its step list (`cognitive_agent.py:1930-1956`). The judge sees the episode's request and recorded outcome (bounded) and two candidates rendered without name, id, generation, evolution type, parents or tags. An injected `random.Random` picks which order is asked first; the second call reverses it. Both orders agree -> that side wins; a split, a tie in either order -> tie; an unreadable reply or LLM error in either -> `invalid` (recorded, not counted, the situation stays open). Situations = the first `procedure_challenger_used_contexts` episodes the rewrite saw + every held-out episode. Held-out = odd positions (1, 3, ...) of the recalled list, at most `procedure_challenger_held_out_episodes` and never more than half, so both halves span the recency order. **A pairwise win** = a counted situation whose combined outcome is `challenger`.
2. One random order per situation — a judge with a position bias promotes by chance (MT-Bench: GPT-4 position consistency about 65%). Loses on correctness.
3. Execute both procedures — real side effects with no sandbox in the dream. Loses on safety; deferred to a Holodeck AD.
4. Absolute 0-1 scores — the issue excludes them.

### D4 — Judge model (AD-1327 reuse)
1. **Chosen: `VerifierJudgePolicy.from_cognitive(config.cognitive)`.** It requests `verifier` when `cognitive.llm_model_verifier` is set, else `standard` — never `deep`, the tier the rewrite runs on (`__post_init__` admits only those two, `verifier_independence.py:104-106`). Every judgement records `policy.provenance(answered_tier=..., answered_model=...)`. **Counting rule:** when the configured judge is independent of every crew tier (`policy.assess() == "independent"`), a situation counts only if both its judgements are `independent` (a fallback answer is recorded and not counted, and the situation is retried next cycle). Otherwise (no verifier, or one of the same model or family) every valid judgement counts and its independence is recorded. With no verifier configured the judge runs on `standard` and the optimizer on `deep`: the "distinct tier where configured" of the issue. The AD-1327 client fallback still applies: a configured verifier attempt is routed exact and, when it fails, falls back to standard, fast, deep; `answered_tier` says which answered, and the counting rule reads it.
2. Record only — a configured independent judge that silently fell back to a crew tier would still decide promotions. Loses on the exact MASS failure.
3. Refuse unless independent — with the default config (no verifier) no FIX could ever be promoted, so FIX evolution would be dead by default. Loses on compatibility.
4. A separate dreaming judge-tier setting — a second knob for the same decision AD-1327 already owns. Loses on DRY.

### D5 — Ranking and the promotion rule
1. **Chosen: Bradley-Terry by Hunter's MM iteration (Ann. Statist. 32(1), 2004), deterministic.** Ties count half a win to each side. Every pair that met gets `prior=0.5` pseudo-wins on each side, so a candidate that never won keeps a finite positive strength. The champion is the reference, pinned to 1.0 after each sweep. Players are updated in sorted order (Gauss-Seidel), outcomes are folded into per-pair counts first, the cap is 1,000 sweeps and the stop tolerance 1e-12 relative. On a star (every candidate compared only with the champion, which is what the dream produces) the fit is closed-form: `p_i = (w_i + t_i/2 + 0.5) / (l_i + t_i/2 + 0.5)` — hand-computable test values — and `bradley_terry` returns it directly instead of iterating (review round 1, F4: the iteration's roundoff made two equal records unequal and overrode the tie-break). Rank: strength desc, then `created_at`, then id. Promote the top candidate only if `beats_champion(wins, decisions, min_decisions, margin)`: `decisions >= min_decisions` and `wins / decisions > 0.5 + margin` (strict; ties and losses count against). Defaults: `margin=0.1`, `min_decisions=3`.
2. Elo — order-dependent; a fixed set of outcomes would not give one answer. Loses on determinism.
3. MAP with a Gamma prior — no closed form for hand tests, and MM converges slowly for some priors (Vojnovic, Yun and Zhou, arXiv:1901.00150). Loses on validation cost.
4. Plain win rate — no multi-candidate ranking; the issue requires Bradley-Terry.

### D6 — Bounds
1. **Chosen:** `procedure_challenger_max_judge_calls_per_cycle=16` (8 situations, 2 calls each), checked before each situation; a situation that does not fit is counted `deferred` and waits. `procedure_challenger_max_pending_cycles=5`: every pending challenger's `cycles_pending` is incremented at the end of each cycle, and at 5 it is retired `expired` — never promoted. `procedure_challenger_max_pending_per_champion=2`, checked in `prepare` **before** the rewrite, so no deep call is normally spent on a challenger that could not be recorded, and enforced atomically when the challenger is recorded (D9, F5). Cost per cycle is bounded by calls x (prompt <= about 10.5k characters: system prompt + situation <= 2,000 + two candidates <= 4,000 each) + `max_tokens=512`. A "call" is one `LLMClient.complete()`; the client's own fallback chain can make more than one provider attempt per call (review round 1 measured 16 calls -> 32 HTTP attempts), so the wire bound is calls x the chain length. Retirement keeps everything: the inactive procedure row and its Ship's Records YAML, `content_diff`/`change_summary`, the challenge row with its decision text, and every comparison row with both reasons and judge records. No method of the ledger deletes.
2. A token budget — the dream has no per-call token accounting seam; calls are what the judge controls. Loses on validation cost.
3. No cap — one degraded procedure could spend unbounded deep and judge calls. Loses on safety.

### D7 — Optimizer on `deep`
Rewriting (procedure text produced from a parent): `evolve_fix_procedure` `:787`, `evolve_derived_procedure` `:874`, `evolve_fix_from_fallback` `:1294`. Not rewriting: the evolution gate `confirm_evolution_with_llm` `:206` (YES/NO), and extraction from episodes `:515`, `:654`, `:1029`, `:1157`. Only the three rewriting calls change.
1. **Chosen: `tier="deep"`, `min_tier="standard"`.** A plain request's chain is `[tier] + the other text tiers in order` (`llm_client.py:1567`), so plain `deep` would fall to **fast** before standard when deep is down or excluded. AD-1324's floor only removes lower tiers and preserves order (`:1569-1573`): the chain becomes deep -> standard, never weaker than today's standard request. A floor makes the route strict (`_resolve_route_for_tier(..., min_tier=...)`, `:1613-1615`): a model-router fault refuses the attempt instead of degrading to the configured model, and the rewrite returns `None` (retried after the cooldown). The BF-886 cost ceiling still applies per attempt (`CostCeilingExclusion`, `:1632-1639`): an excluded `deep` falls to `standard`; both excluded gives an error response and no rewrite. AD-1324's agent-chosen tier (`TierChoiceConfig`, `config_models/agentic.py:337`) applies only to armed agentic runs and does not touch these requests. `EvolutionResult` records `optimizer_tier`/`optimizer_model` from `LLMResponse.answered_tier/answered_model`, and the ledger keeps them, so a rewrite answered by `standard` is visible.
2. Plain `deep` — falls to fast on a deep outage. Loses on correctness.
3. `exact_tier=True` — no rewrite at all whenever deep is unavailable. Loses on availability.
4. Deep for FIX only — the issue names rewriting, and DERIVED is a rewrite; its persistence flow is unchanged either way.

### D8 — The legacy flag
1. **Chosen: `DreamingConfig.procedure_challenger_enabled: bool = True`**, flat beside the other `dreaming.*` controls (`config_models/cognition.py:85-158`), with seven bounded siblings and a parse-time `model_validator` that refuses a `min_decisions` above the situations one challenge can have from a full recall of `PROCEDURE_EVOLUTION_EPISODE_LIMIT` episodes (D9, F6; no challenger could ever be promoted). `False` keeps the legacy FIX handling (Solution 6): it does not make a near-miss fallback FIX supersede its parent, which it never did, and it does not change the rewrite tier. `scripts/check_config_profiles.py` gate 3 classifies only default-`False` booleans (`:12-14`), so a default-`True` flag needs no manifest row. Required regenerations: `docs/development/config-facade-baseline.yaml` (`check_config_facade.py --update-baseline`) and `docs/development/config-reference.md` (`gen_config_reference.py`). Pins: `test_ad1270e1_config_facade.py:1549`, `test_ad1270e2b_cognition_models.py` `EXPECTED_DUMPS["DreamingConfig"]`, `test_ad1152_agentic_correlation.py` pops (Section 8).
2. `legacy_immediate_supersession: bool = False` — a default-`False` boolean must be classified in the profile manifest, and the name reads as a negative. Loses on validation cost.
3. A nested `ProcedureChallengerConfig` — the cognition models are self-contained leaves (module docstring, `cognition.py:3-5`), and a new model moves four facade surface counts. Loses on validation cost.

### D9 — Review round 1 (2026-10-13, Diff Reviewer GPT-6.1 Sol; every finding reproduced by the orchestrator)

**F1 [P1] — a promotion was sealed while the routing index disagreed.** `save()` ignores `_save_to_chroma`'s result (`procedure_store.py` `save`, WARNING only) and `deactivate()` swallows an index failure (`except Exception: pass`); `find_matching` reads only the index. Pre-existing store behaviour; the new path must not seal on it.
1. **Chosen: one public store method `sync_routing_index(procedure_id) -> bool`** (Section 3f): rewrites the entry from the authoritative SQLite row and says whether it took; True also when the store runs with no index (it then matches nothing) or has no row (`find_matching` drops ids without one). `_complete_promotion` calls it for both ids after the SQLite writes and stays `promoting` until both are True; `run_cycle` already repeats `promoting` rows each cycle. `save`/`deactivate` are untouched, so every other caller behaves as before. Cost: one method (about 15 lines) on the srp-guarded `ProcedureStore`; its row keeps the triggers `lines`, `methods`. Reversible by one revert.
2. Mark the index stale on a failed write (`procedure_index_state` -> not `ready`, so the next start rebuilds) — fixes every caller, but changes two hot store methods, heals only at the next start (the ledger would say `promoted` while routing is wrong until then), and the metadata write can fail in the same outage. *Considered, deferred:* the store-wide follow-up for the legacy callers (Blind spot 9).
3. A read-only `routing_index_state(id)` check plus re-calling `save`/`deactivate` — detects but repairs only through methods that hide failure; two methods instead of one. Loses on simplicity.
4. Accept and qualify — leaves the P1 on the new path. Loses on correctness.

**F5 — the pending cap was checked in `prepare`, not reserved.**
1. **Chosen: enforce the cap in `ProcedureChallengeLedger.add_challenger` (`max_pending`), counting and inserting under the ledger's `asyncio.Lock`** (every ledger write takes it; this process is the file's only writer). A challenger over the cap is **recorded `retired` with reason `pending_limit`** instead of refused, so the inactive procedure row `submit` already saved (save, then record: a cycle never sees a ledger row without its procedure) stays accounted for, and `submit` emits its `retired` event and returns `None`. `prepare`'s check stays as the cheap pre-check. Residual: an overlapping rewrite still spends its one deep call (at most one per concurrent FIX path: 7b, proactive, 7d), never a slot.
2. In-memory reservation taken in `prepare`, released by `submit` and by every non-submit path — also saves the wasted call, but needs a release at three sites on four paths (rewrite `None`, exception, cancellation, refusal), and a leaked reservation silently blocks a champion until restart. Loses on correctness risk.
3. Record in the ledger first (a durable reservation), then save — a concurrent `run_cycle` would see a ledger row whose procedure is not yet saved and retire it `challenger_missing`. Loses on correctness.
4. Accept and document (the first draft's Blind spot 3) — the cap is broken (reproduced: 3 pending, limit 2). Loses.

**F6 — an accepted configuration could never produce a challenge.**
1. **Chosen: one constant `PROCEDURE_EVOLUTION_EPISODE_LIMIT = 10` in `config_models/cognition.py`**, used by the three producers' recall cap (`dreaming.py`, Sections 13a-2, 13d, 13e-0, 13f) and by the validator, which computes exactly what `prepare` can assemble from a full recall: `h = min(held_out, N // 2)`, `achievable = min(used, N - h) + h`. Bounds tighten to `used_contexts <= N`, `held_out_episodes <= N // 2`, `min_decisions <= N`. No import cycle: `config.py` imports `config_models.cognition`, and `dreaming.py` imports the constant from there directly (precedent: `fault_issue_filings.py:14` imports `valid_github_repository` from `config_models.agentic`); it is not re-exported, so the facade's `public_names == 305` pin does not move.
2. Raise the producers' cap to fit the configuration — changes the legacy path and the DERIVED prompt size. Loses on compatibility.
3. A literal 10 in the validator — two copies of one limit. Loses on DRY.
4. Re-export the constant through `probos.config` — moves the facade's `public_names`/`owned` pins. Loses on pin cost.

**F7 — a hot backup pair restored a routable pending challenger.**
1. **Chosen: `_reconcile`, run for every pending row at the start of `_contest`.** A challenger that is active while its champion is inactive and `superseded_by` it is a completed promotion the ledger missed: it goes `pending -> promoting -> promoted` through the existing `_complete_promotion` (index sync included), reason `restored_promotion`, with the evidence the ledger holds. Any other active pending challenger is deactivated (a pending or retired challenger never routes), then judged or retired as usual. Every pending challenger's index entry is rewritten from SQLite each cycle (bounded by the pending cap). Opposite interleaving (ledger newer than `procedures.db`): a `promoting` row is finished as today (the decision was made); a `promoted` row over an older `procedures.db` leaves the older routing (champion active, challenger inactive) — safe, and the ledger overstates; documented, not repaired, because decided rows are not rescanned.
2. Snapshot the pair consistently (the backup copies both under one ordering or lock) — cross-component change to `BackupService`. *Considered, deferred.*
3. Treat every restored active challenger as unconfirmed: deactivate it and reactivate the champion — reverses a promotion `procedures.db` already holds. Loses on correctness.
4. Retire the ledger row only — leaves a retired challenger routable (reproduced). Loses.

**One-line decisions.** F2: `render_candidate` is `cognitive_agent._format_procedure_replay`'s body after its two identifying header lines (role, expected output, fallback, postconditions; no preconditions, which replay does not show), passed through `bounded_text` at `MAX_CANDIDATE_CHARS = 4000`: equal to replay's body when that body has at most 4,000 characters and no NUL or lone surrogate, and replay's body cut at 4,000 characters otherwise (qualified in review round 2, R2-5), pinned by equality with the real formatter. F3: `prepare(..., source_correlation_id=...)`: episodes of the turn whose response the Step 7d prompt quotes go first in the rewrite set and are never held out (a reorder at the site would put a second episode of the same turn at odd position 1). F4: closed form on a star, the MM iteration only otherwise; equal records give `==` strengths. F8: every early retirement (`champion_inactive`, `challenger_missing`) tallies the ledger first.

### D10 — Review round 2 (2026-10-13, Diff Reviewer GPT-6.1 Sol; R2-1..R2-5 reproduced by the orchestrator, `logs/architect/probe-ad1326-r2-findings.out`, PREMISE FAILURES: none)

Envelope: every choice below is backward compatible, weakens no control, is bounded, adds no method to `ProcedureChallenger` (15, the srp-size limit) or `ProcedureStore`, and reverts with the commit. The ledger file is new and unreleased, so its name may change.

**R2-1 [P1] — a failed reconciliation left a retired challenger routable for good.** Activation-only restored pair, `max_pending_cycles=1`, budget 0, the challenger's index `update` and `upsert` failing: `_reconcile` deactivates it in SQLite, its sync fails (a log line), `_age` seals `expired`, and no later cycle looks at a retired row; `find_matching` (and the real `CognitiveAgent._check_procedural_memory`) still admit it after the fault is gone.
1. **Chosen: (C) both.** (B) `find_matching` admits a semantic-index match only when its SQLite row is active: `_get_index_row`, its only caller's row loader, selects `WHERE id = ? AND is_active = 1` (Section 3g). SQLite can veto at admission for every caller (it cannot admit a row the index excludes: `find_matching` filters the index on `is_active` first, which is base behaviour; review round 3, R3-6), so the hazard ends the moment SQLite says inactive, during the outage too, and the legacy callers' stale-entry case (Blind spot 9, the store follow-up) is closed in the same line. (A) `_retire` seals only after `sync_routing_index(challenger)` is True; otherwise the row keeps its status (`pending`, or `promoting` for the missing-challenger case, whose sync is True by definition) and the next cycle retries (`_age` retires it again). The index is then never left stale by the decisions `_retire` and `_complete_promotion` make, matching how promotion is sealed (D9, F1); a `pending_limit` row is recorded `retired` by `add_challenger` without this protocol (review round 3, R3-7, D11). Compatibility of (B), by caller (enumerated: `cognitive_agent.py:1738, 1764`, `dreaming.py:653, 744, 2135, 2409`, `proactive.py:2024`, `procedure_store.py:1781`): the row keys and their order are unchanged; a result differs only when the index says active and SQLite says inactive, which today returns a procedure that is not routable by its own row. The dedup caller (`:1781`) already refuses inactive rows at the merge guard (`:1849`). No test asserts a stale-entry match except two AD-1326 premises written to demonstrate the hazard (Hidden Pins, R2). Cost: none; the per-match SQL already runs.
2. (B) alone — routing is right, but a retired challenger's entry stays stale until a rebuild, and retirement would be sealed on weaker evidence than promotion. Loses on consistency.
3. (A) alone — the index heals at the first cycle after the outage, but the challenger routes for the whole outage, and the legacy callers keep the hazard. Loses on the P1.
4. Rescan retired rows each cycle — the scan grows without bound with history. Loses on cost.

**R2-2 [P1] — a promotion removed the champion before the challenger's routing was confirmed.** Chosen order in `_complete_promotion` (Section 12): (1) save the challenger active if it is not; (2) `sync_routing_index(challenger)`; on False return, still `promoting`, **before the champion is touched**, so the champion keeps routing; (3) deactivate the champion with `superseded_by`; (4) `sync_routing_index(champion)`; on False return, still `promoting` (the challenger already routes, and R2-1 (B) drops the champion's stale active entry because SQLite says inactive); (5) seal `promoted`. Every step repeats safely, so a later cycle resumes wherever it stopped. Window: between (2) and (4) both procedures route, the decided winner beside the old champion, which is the legacy near-miss state and never an undecided challenger. Considered: deactivate the champion first and roll back on a failed sync (an extra write that can fail in the same outage; loses on simplicity); confirm both before either write (the champion's inactive entry cannot be confirmed before it is deactivated). `test_promotion_is_sealed_only_when_the_routing_index_agrees[upsert_fails]` now pins the champion routing during the outage, and a third variant, `champion_index_fails`, pins step (4).

**R2-3 [P2] — a restored pending challenger routed before the first dream cycle.** The hot backup copies databases in `discover` order, sorted by relative path (`backup_inventory.py:272`, the final sort `:298`; `backup.py:284` copies in that order). `procedure_challenges.db` sorts before `procedures.db` (`_` 0x5F < `s` 0x73), so the ledger was copied first and could be older than `procedures.db`: the only pairing that holds a `pending` row with an active challenger, because a challenger becomes active only after its row is `promoting` (`_promote`, `_reconcile`'s restored path).
1. **Chosen: (a) rename the ledger file `procedures_challenges.db`** (`procedures.db` < `procedures_challenges.db`: `.` 0x2E < `_` 0x5F), so the backup copies it after `procedures.db` and, when both online backups succeed, the ledger is never older: that path cannot produce the hazardous pairing. (Review round 3, R3-5: `_backup_one`'s raw-copy fallback after an `sqlite3.Error` copies the main file without its `-wal`, so a fallback copy of the ledger can be older; D11 closes the pairing at admission instead.) Pinned by `test_backup_copies_the_ledger_after_procedures_db` (the real store's files through the real `discover`) and mutation row 48. Moves: the store's connect path (3d), the declaration's `canonical_path` (Section 4; `check_store_registry.py` checks only its uniqueness, `:1156-1162`), the backup-coverage literal (discovered, no exclusion), and the ledger tests' file names. Remains: a pair produced outside the backup (a manual copy of the two files) can still route a pending challenger until the first dream cycle, which reconciles it as before; and the ledger can now be NEWER: a `promoting` row is finished by the next cycle; a `promoted` row over a `procedures.db` copied mid-promotion (challenger active, champion not yet deactivated) leaves both routing (the decided winner beside the old champion) because decided rows are not rescanned (Blind spot 4).
2. (c) a public routing-only reconcile run from `init_dreaming` before agents route — covers manual copies too, but needs a method on the 15-method class (merge `_promote` into `_decide` to stay at 15) and a proof that no agent routes before `init_dreaming` (not established); leaves the window between store start and that call. Loses on cost and evidence.
3. (b) a quarantine in `ProcedureStore.start` — puts ledger semantics and `_reconcile`'s completed-promotion test into the srp-guarded store, a duplicate of `_reconcile`. Loses on SRP and DRY.
4. (d) accept and document — the reviewer's real backup produced it. Loses.

**R2-4 [P2] — pinning the source turn broke the validator's exactness.** `prepare` split only the non-source episodes, so the held-out ceiling was half of a smaller pool (accepted (0,5,5) over 10 episodes with the turn pinned: `None`). Chosen: `split_held_out(episodes, held_out, *, pinned=...)` computes the ceiling from the full usable recall (`min(held_out, len(episodes) // 2)`) and selects among unpinned episodes only, in this order: odd positions ascending (as before), then even positions from the oldest down to position 0 last, so a pinned episode at an odd position is replaced by the oldest unpinned even one and the newest episode stays with the rewrite unless nothing else is left. Pinned episodes lead the evolution half in recall order (F3 unchanged). With nothing pinned the split is exactly the old one (the ceiling never exceeds the odd positions). The validator's formula is then exact whenever at most `N - min(held_out, N // 2)` recalled episodes are pinned, which always holds when at most half of the recall is the source turn; above that, held-out falls short and `prepare` refuses as it does for any short recall. Considered: a pinned-aware validator (it cannot know the turn's size at parse time); holding out the pinned turn's later episodes (F3 forbids it).

**R2-5 [P2 claims].** "Exactly" and "line for line" are qualified in Section 5's docstrings and D9 (F2): the candidate is replay's body through `bounded_text` (4,000 characters, NUL removed, lone surrogates replaced); a 4,200-character description crowds every step out. The bound is not redesigned here (Blind spot 11). `test_render_candidate_is_the_bounded_replay_body_at_the_cut` pins the qualified claim at 3,999 / 4,000 / 4,001 / 4,200 characters.

**R2-6 (tests).** `test_equal_strengths_fall_to_the_creation_time_tie_break` gains the service-level layout with the champion's id between the two challengers' ids (both orders of creation), the layout in which the reverted closed form's roundoff separates equal records; mutation row 25 names it.

### D11 — Review round 3 (2026-10-13, Diff Reviewer GPT-6.1 Sol, `logs/architect/review-ad1326-r3.md`; R3-1..R3-8 reproduced by the orchestrator, `logs/architect/probe-ad1326-r3-findings.out`, PREMISE FAILURES: none)

Envelope: every choice is backward compatible, weakens no control (two tighten one), is bounded and reverts with the commit. Method counts after this round: `ProcedureChallenger` 15 (none added), `ProcedureChallengeLedger` 14 (none added; one module-level helper), `ProcedureJudge` 5 (none added), `ChallengeRecord` gains one property, `ProcedureStore` gains no method. The ledger file and schema are new and unreleased; neither changes here.

**R3-1 [P1] — the judge ignored the optimizer's reported model.** Verifier `gpt-5.1` (crew models Claude), rewrite answered by `gpt-5.1`, judge answering as `gpt-5.1`: labelled `independent`, counted, promoted.
1. **Chosen: `ProcedureJudge.compare(..., optimizer_model: str = "")`, fed `record.optimizer_model` by `_judge_record`.** For that call the judge classifies each answer against `dataclasses.replace(policy, crew_models=(*crew_models, optimizer_model))` (Section 5), so an answer by the optimizer's own model is `same_model` (same family: `same_family`; unknown family: `unknown`). Whether only independent judgements count stays the configured policy's `assess()`, computed once in `__init__`: adding the optimizer's model can only lower a label, never lift the gate, so no control is relaxed. Empty or non-`str` `optimizer_model` (not reported): nothing is added, the verdict is exactly today's (`classify_independence` also ignores empty names, `verifier_independence.py:76`). A challenger all of whose situations are uncounted is never complete (`_judge_record` returns `None` while an available situation is uncounted), so it is re-judged within the per-cycle budget and retired `expired` after `procedure_challenger_max_pending_cycles` — not `insufficient_evidence`, which needs a complete record. Consequence, accepted (safe direction): under an independent judge, an optimizer answer from a model of unknown family makes every judgement `unknown`, so that challenger expires. Under the default (no verifier) every valid judgement counts as before; only the recorded labels can change.
2. Per-call policy built in the challenger and passed to the judge — the challenger would reach into the judge's policy (Demeter) and duplicate the classification. Loses on SRP.
3. Relabel in the challenger after `compare` (`classify_independence(judge.model, [optimizer_model])`) — a second counting rule outside the judge. Loses on DRY and on the single owner of "counted".

**R3-2 [P2] — a failed ledger transaction stayed open.** Chosen: one module-level `@asynccontextmanager _write_transaction(lock, connect)` in `procedure_challenges.py` (the shape of `fault_issue_filings.fault_transaction`, `:110-130`): under the ledger lock, `BEGIN IMMEDIATE`, the writer's statements, `commit`; on any `BaseException` after `BEGIN` succeeded (cancellation included) `ROLLBACK` runs under the same lock before the error propagates. A rollback that itself fails is logged at ERROR and the original error propagates; the transaction may then stay open, the next write's `BEGIN IMMEDIATE` fails ("cannot start a transaction within a transaction") and nothing is built on it until the store restarts (residual, named). All five writers (`add_challenger`, `record_comparison`, `set_status`, `increment_cycles`, `record_cycle`) run in it and contain no `commit` of their own; `start`'s schema commit is unchanged. Reusing `fault_transaction` itself: *rejected*, its error type and log are the fault journal's. A shared storage-layer transaction helper: *considered, deferred*.

**R3-3 [P2] — routing confirmation trusted stale JSON.**
1. **Chosen: (A) `sync_routing_index` publishes `is_active` from the row's column**, not from `content_snapshot` (Section 3f): after `get`, one `SELECT is_active` on the same row overrides the freshly deserialized object's flag before `_save_to_chroma`. The index entry then agrees with what admission reads (3g), so promotion and retirement are sealed only over a correct entry. `superseded_by` is not in the index payload (`_chroma_payload`, `procedure_store.py:672-682`), so it is not read. Cost: one primary-key SELECT per sync.
2. (B) `get()` merges the columns for every caller — changes what every legacy reader of `get` sees (archive, restore, dedup, API) for a defect only the routing seam needs. Loses on blast radius.
3. (C) (A) plus `deactivate` raising on a failed snapshot UPDATE — `deactivate` is called by the three legacy dream sites (`dreaming.py:1958, 2097, 2301`), dedup (`procedure_store.py:1919`) and this AD (`procedure_challenger.py:407, 533`); a raise would abort legacy evolution mid-flow. Loses on compatibility. Stays in the store follow-up (f26): the legacy best-effort writes (`deactivate`'s snapshot `except: pass` `:1172`, archive `:1585`, restore `:1662`, `save` ignoring `_save_to_chroma`).

**R3-4 [P2] — the real Step 7d recall returned five episodes.** Chosen: `_recall_evidence_by_intent` calls `recall_by_intent(intent_type, k=PROCEDURE_EVOLUTION_EPISODE_LIMIT)` (13a-3). The three sites keep their `[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]` slice (a champion with several intents still recalls per intent). The one test fake without `k` moves (13j).

**R3-5 [P2] — the raw-copy fallback defeated the R2-3 ordering.**
1. **Chosen: (B) admission consults the ledger the store owns.** `_get_index_row` (3g) refuses a procedure whose ledger row `bars_routing` (`pending` or `retired`), whatever the index and `procedures.db` say; no ledger row, `promoting` or `promoted` admits as before. Fail-open: no open ledger, or a ledger read that raises (one WARNING), admits on SQLite alone, as before AD-1326. This closes the pending-and-active pair for every restore path (fallback copy, manual copy) and for R3-7's over-cap row, independent of copy order. Blast radius: `find_matching`'s eight callers (D10) see a result only when a match is a challenger the ledger holds undecided or lost; result shape unchanged. Cost: one ledger primary-key SELECT per SQLite-admitted match (at most `n_results`, default 5), only while the ledger is open. Counts: no method on `ProcedureStore` or the ledger; one property on `ChallengeRecord`. Cost accepted: a restored pair whose `procedures.db` already holds the completed promotion (challenger active, champion superseded, ledger `pending`) routes neither until the first dream cycle records `restored_promotion`; the agent falls through to the LLM for that lineage meanwhile.
2. (A) qualify the "never older" claims and accept — leaves a restored challenger with no judgements routing until the first cycle. Loses on the finding.
3. (C) a store-start reconcile — D10 (b): ledger semantics and a duplicate of `_reconcile` in the store's start. Loses on SRP/DRY.
4. (D) fail the snapshot instead of raw-copying (the reviewer's) — changes `BackupService` for every SQLite file (`backup.py:772-799`), outside this issue. *Considered, deferred* to a backup follow-up.
5. (E, mine) run the ledger in `journal_mode=DELETE` so the main file always holds committed state — a raw copy can then be torn mid-commit, and manual copies stay uncovered. Loses on correctness.
The "never older" text is qualified in 3d, Section 4 and D10 (true when the online backups succeed).

**R3-6 [P2, pre-existing] — SQLite is a veto at admission, not the admitter.** No retrieval redesign. Wording (3g docstring, D10, Acceptance 15/17): SQLite can veto an entry the index admits; it cannot admit one the index excludes, because `find_matching` filters the index on `is_active` (base behaviour) before SQLite is read. The reverse case is a follow-up (orchestrator).

**R3-7 [P2] — `pending_limit` retirement skips the confirmation protocol.** No new phase. The confirm-then-seal rule is stated for the decisions `_retire` and `_complete_promotion` make. An over-cap challenger needs none: `submit` saved it inactive moments before `add_challenger` recorded it `retired` in the same insert, it was never routable, SQLite-inactive rows are never admitted (3g) and, since R3-5, its `retired` row is refused at admission too. Its index entry is either absent (the save's index write failed, the reviewer's case) or says inactive (it was saved inactive); routing finds it in neither case.

**R3-8 [P2] — a crash between the terminal commit and the emit loses the event.** The ledger is the authority; the event is observational. `PROCEDURE_CHALLENGE_DECIDED` is emitted **at most once** per decision: after the terminal status commits, and never re-emitted, so a process that stops between that commit and the emit leaves the decision in the ledger with no event. Qualified in the Section 12 docstring, D11 and Acceptance 2. An outbox is a follow-up (orchestrator).

### D12 — Review round 4 (2026-10-13, Diff Reviewer GPT-6.1 Sol, `logs/architect/review-ad1326-r4.md`; R4-1..R4-4 reproduced by the orchestrator, `logs/architect/probe-ad1326-r4-findings.out`, PREMISE FAILURES: none)

Envelope: every choice is backward compatible, weakens no control, is bounded and reverts with the commit. Method counts after this round: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5, `ProcedureStore` +0 (none added anywhere; one more module-level helper in `procedure_challenges.py`). The ledger file and schema are new and unreleased; neither changes. D11's R3-1 sentence "adding the optimizer's model can only lower a label" and R3-5's "refuses a procedure whose ledger row `bars_routing` ... whatever the index and `procedures.db` say" are superseded by R4-3 and R4-2 below.

**R4-1 [P2] — a cancellation while `BEGIN IMMEDIATE` waited left a transaction open (a regression of R3-2).** aiosqlite runs one connection's calls in FIFO order on one worker thread (`aiosqlite/core.py` `_execute` :150-160: `put_nowait` then `await future`); cancelling the awaiting coroutine does not withdraw the queued call. R3-2 set `begun` only after the `BEGIN` returned, so a `BEGIN` that was cancelled while it waited on another connection's lock, and then took effect, was never rolled back.
1. **Chosen: (A), refined: roll back whenever the `BEGIN` was not answered with an error, and hold the ledger lock until that rollback has run.** `_write_transaction` (Section 2) skips the rollback only when `BEGIN IMMEDIATE` itself raised an ordinary `Exception` (SQLite opened nothing; `test_a_write_that_cannot_begin_issues_no_rollback_and_logs_nothing` keeps pinning it). On any other `BaseException` (a statement, the commit, a cancellation at any point, the `BEGIN`'s included) it starts the module-level `_roll_back(db)` as a task it keeps and waits for it under `asyncio.shield`, absorbing further cancellations, before it releases the lock. FIFO order puts that `ROLLBACK` behind the queued `BEGIN` or `COMMIT`, so it runs after they settle. `_roll_back` treats SQLite's "no transaction is active" as nothing to undo (the cancelled `BEGIN` timed out, or the cancelled `COMMIT` completed) and logs only any other rollback failure at ERROR, as before. Bound: SQLite's busy-handler budget, `busy_timeout` (5,000 ms, set in `start`), plus the rollback; a retry budget, not a wall-clock ceiling (D13, R5-3). Shape: the drain loop of `execution/workspace_results.await_result_task` (`:439-453`), written inline (not imported across layers; seven lines).
   - **A second cancellation during the cleanup** is absorbed: the lock is held until the `ROLLBACK` has run, then the writer raises `CancelledError` (the original one, or a new one chained from an ordinary original error, so a caller's timeout or task group still sees its cancellation). Pinned by `test_a_second_cancellation_during_cleanup_still_rolls_back` and `test_a_cancellation_during_rollback_waits_for_it_and_is_delivered`.
   - **A cancelled `COMMIT` that still commits** leaves the write durable while its caller saw `CancelledError`. Accepted: every ledger writer is a conditional or idempotent step whose result the next dream cycle re-reads from the ledger (a `promoting`/`pending` row is resumed, a `promoted`/`retired` one is final, a comparison row is not re-judged); the only loss is the decision event of a terminal transition, which is R3-8's at-most-once residual. Pinned by `test_a_cancelled_commit_that_still_commits_is_durable_and_logs_nothing`.
2. (B) run the `BEGIN` as its own shielded task and wait for it to settle before rolling back — equivalent for the `BEGIN`, but covers neither a cancelled statement nor a cancelled `COMMIT`, which have the same queue behaviour. Loses on coverage.
3. (A) as proposed, releasing the lock while the shielded rollback is still pending — FIFO order still runs the `ROLLBACK` before the next writer's `BEGIN`, but only if the shielded task has queued it before the next writer runs, an event-loop scheduling detail. Loses on robustness for nothing saved.
4. (C) qualify and name the window — leaves a wedge reachable by any dream-cycle cancellation under write contention (the reviewer's). Loses.

**R4-2 [P2] — with the feature disabled nothing ends the R3-5 cost.** A restored completed promotion under an older `pending` row routed neither procedure until `_reconcile` ran, and with `procedure_challenger_enabled=False` no service is built, so it never ran.
1. **Chosen: (A) `_get_index_row` (3g) does not bar a `pending` challenger whose ledger champion is inactive in `procedure_records` with `superseded_by` equal to it.** That is exactly the predicate `_reconcile` records as `restored_promotion` (Section 12, mutation row 34), so admission now routes at once the set the first dream cycle would promote, and nothing else; the ledger still catches up through `_reconcile` when the feature is on. One primary-key SELECT, only on the barred `pending` path. Against R3-5's cases: a `pending` challenger whose champion is still active (the raw-copy pair, `test_raw_copy_fallback_pair_never_routes_the_pending_challenger`; the activation-only pair), or whose champion is superseded by another id (`test_retirement_leaves_no_routable_challenger`), or whose champion row is gone, stays refused; `retired` stays refused; `promoting`/`promoted` were never barred. Against `_complete_promotion`'s order: the champion gets `superseded_by` only at step 3, after the row is `promoting` (Absence Verified, R2), so in a ledger that is current the predicate never meets a `pending` row; it meets one only in a ledger older than `procedures.db`. Writers of `superseded_by` (enumerated, Absence Verified R4): the three legacy dream sites (their new procedure has no ledger row), `_complete_promotion`, and the operator's `merge_procedures` (`procedure_store.py:1951`, reached only from `commands_procedure.py:645` and `routers/procedures.py:323`; Step 7f only detects duplicates, `dreaming.py:875`). An operator who merges a champion into its restored active pending challenger has decided for it; `_reconcile` already reads that pair as a completed promotion (Blind spot 16).
2. (B) reconcile restored challengers independently of the flag — the reviewer's suggestion; needs a service or startup step outside the 15-method class and a second copy of `_reconcile`'s completed-promotion rule (D10 option (c)/(b): SRP and DRY), and still routes nothing until it runs. Loses on cost.
3. (D) a flag-aware veto (no ledger veto while disabled) — the reviewer rejected it; it would route a restored undecided challenger whose champion is still active while the feature is off. Loses on the R3-5 control.
4. (C) accept and document — leaves a supported flag combination with a lineage that never routes. Loses.

**R4-3 [P2] — adding the optimizer's model could raise a label.** With an empty crew basis (the configuration accepts `("", "", "")`) the baseline label is `unknown`; adding the optimizer gave the classifier a basis and the label became `independent`, persisted as provenance. Chosen rule, in `ProcedureJudge._ask` (no method added): each answer is classified twice, against the configured policy (baseline) and against the policy with the optimizer's model added (augmented); when the augmented label is `independent` and the baseline is not, the baseline record is kept; every other augmented label is kept (it is the baseline or a more specific weak label, e.g. `unknown` -> `same_model` when the judge is the optimizer). The two records differ only in `independence` (same tier, model and fallback). An augmented `independent` needs a baseline `independent` or an empty baseline basis (`classify_independence`, `verifier_independence.py:76-88`: adding a model cannot remove an unknown family), so the empty basis is the only raised case. Counting is unchanged: `requires_independent` stays the configured policy's `assess()`; under an empty basis that is `unknown`, so every valid judgement counts as before and only its recorded label changes back to `unknown`. Tests: `test_optimizer_model_never_raises_a_label` (empty basis; a basis where augmentation lowers `independent` to `same_model`; one where it changes nothing).

**R4-4 [wording].** The refusal is qualified "while the ledger is open and readable" (fail-open otherwise, R3-5) and carries the R4-2 exception in: the registry note (Section 4), `ChallengeRecord.bars_routing`'s docstring and the 3g docstring (Section 2, 3g), What This Does Not Change, Acceptance 18 and Blind spot 4. Unchanged, because they describe SQLite deactivation, which does not depend on the ledger: D9 F7 (`a pending or retired challenger never routes`), Section 12's `_reconcile` docstring ("a pending or retired challenger never routes") and `_retire`'s comment ("A retired challenger never routes"). D11's text is history and is superseded here, not rewritten.

### D13 — Review round 5 (2026-10-14, Diff Reviewer GPT-6.1 Sol, `logs/architect/review-ad1326-r5.md`; R5-1..R5-4 reproduced by the orchestrator, `logs/architect/probe-ad1326-r5-findings.out`, PREMISE FAILURES: none)

Rule for this round: the smallest change that closes each finding, preferring one that removes a seam. Both P2 defects are fixed; both wording findings are reworded. Method counts after this round: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5, `ProcedureStore` +0 (no method added anywhere; `ProcedureStore` loses R3-3's extra SELECT in `sync_routing_index`). Neither the ledger file nor its schema changes; `procedures.db` changes neither.

**R5-1 [P2] — a ledger read on the writer's connection saw its uncommitted status. Fixed.** The ledger has one connection; a read issued while a writer's transaction is open (between its `UPDATE` and its `COMMIT`, or before a cleanup `ROLLBACK` has run) sees that write, and `_get_index_row` admitted a `promoting` challenger from a transition that was then rolled back. Readers that can run beside a writer in another task (enumerated, Absence Verified R5): `ledger.get` from `ProcedureStore._get_index_row` (`find_matching`: every agent's procedural-memory lookup, outside any dream); `pending_count` from `ProcedureChallenger.prepare`, reached from `DreamingEngine._attempt_procedure_evolution` in the task-execution event handler (`dreaming.py:2162`) while a dream may be writing; and `list_by_status`/`comparisons` in `run_cycle` while such a reactive `submit` writes. `recent_cycles` has no production caller.
1. **Chosen: (A) every public ledger read takes the ledger lock around its execute and fetch.** The writer holds that lock from `BEGIN IMMEDIATE` until its `COMMIT` or its cleanup `ROLLBACK` has run (R4-1), so a read sees only committed rows. No deadlock: nothing holds the lock and then calls a public read (the five writer bodies use the yielded `db` directly; `_write_transaction` is module-private), and `asyncio.Lock` is not re-entered. Cost to the routing path: an uncontended `asyncio.Lock` acquire per `_get_index_row` ledger read; behind an in-flight write it waits for that write, which is short unless the write's `BEGIN IMMEDIATE` waits on another process's lock on `procedures_challenges.db`, bounded by SQLite's busy-handler budget (R5-3); on a `RuntimeError` (ledger detached meanwhile) or any read error `_get_index_row` stays fail-open as before. Reads in the dream task take an uncontended lock. One `async with` per read (each with a distinct trailing comment, so each mutation anchor is unique), a docstring on `get`, no method.
2. (B) only `get` takes the lock — closes the routing finding but leaves `list_by_status`/`comparisons`/`pending_count` able to act on a concurrent `submit`'s row that then rolls back. Saves four lines for a second rule about which reads are safe. Loses on uniformity.
3. (C) record it as a property of the single connection — reach: a challenger (or, through a cancelled `_complete_promotion` step, a champion) admitted for the lookups that overlap one rolled-back transition, cached by replay. Loses: the fix is five lines.
4. (D) a second, read-only connection — a new connection lifecycle and a second BF-882 close path for a property the lock already gives. Loses on cost.

**R5-2 [P2] — admission and reconciliation read the champion's lineage from different sources. Fixed.** Admission (3g) reads the `is_active`/`superseded_by` columns; `_reconcile` and `_contest` read the champion through `ProcedureStore.get`, which rebuilt it from the JSON snapshot, which `deactivate` leaves stale when it swallows a failed snapshot `UPDATE` after the columns commit (`procedure_store.py:1190-1216`). The first enabled cycle then deactivated a completed winner that admission routed.
1. **Chosen: (A) `ProcedureStore.get` takes `is_active` and `superseded_by` from the columns, in the same SELECT (3f2).** Every writer of those columns also writes the snapshot (`save` from one object; `deactivate`, archive, `restore_procedure`, and `merge_procedures` through `deactivate`; enumerated, Absence Verified R5), and only a swallowed snapshot failure makes them differ, so `get` changes only for a row in that state, where the columns are what `find_matching`, `list_active` and 3g already use. Callers (enumerated, Verified R5): `procedure_challenger.py` (5: now agrees with admission, the fix), `dreaming.py` 1890/2158/2238/2476 (a parent's activity), `cognitive_agent.py` 1824/2771 (replay after `find_matching`, which already required column `is_active = 1`) and 7532/7555 (compilation-level promotion and demotion: read `compilation_level` and `name` only), `proactive.py:2029`, `diagnostic_context.py:299`, `commands_procedure.py` (8) and `routers/procedures.py` (5) (display and the operator merge's activity check: now the column's), and the store itself (`sync_routing_index`, archive's records copy, `restore_procedure`'s index re-add). In each the column is the state routing acts on. **R3-3's override in `sync_routing_index` is removed** (it re-read `is_active` after `get`; `get` now provides it): one SELECT and nine lines fewer; `test_sync_routing_index_publishes_the_activity_column` keeps pinning the property through `get`. Other snapshot fields that the same swallowed failures can leave stale (`is_archived`, `compilation_level` after `restore_procedure`) are *considered, deferred* (Blind spot 18): no routing decision reads them from `get`.
2. (B) a new public store method returning the authoritative lineage for `_reconcile` — adds a method to the store and to `ChallengeProcedureStore`, and leaves every other `get` caller on the stale JSON. Loses on SRP and on reach.
3. (C) `_reconcile` reaches the columns through an existing public method — none returns `is_active`/`superseded_by` from the columns for one id (`list_active` filters on `is_active = 1` and returns no `superseded_by`; `get_evolution_metadata` returns content fields); it would be a second read path. Loses.
4. (D) record it (double fault: a restore pair plus a failed legacy snapshot write) — reach: a restored completed promotion loses replay on its first enabled cycle. Loses: (A) is net fewer lines.

**R5-3 [wording] — the busy timeout is SQLite's busy-handler budget, not a wall-clock ceiling** (measured: 80 ms configured, `BEGIN` 156 ms; 5,000 ms configured, 5,579 ms). Reworded in `_write_transaction`'s docstring, D12 R4-1, Blind spot 15 and Acceptance 19. The cleanup stays untimed: abandoning it would leave the transaction open (R4-1).

**R5-4 [wording] — reconciliation runs only when the challenger service is enabled and a dream reaches its step.** Qualified in the registry note (Section 4) and the 3g docstring. Unchanged, because they already condition on the service or describe `_reconcile` itself: D12 R4-2 ("when the feature is on"), Section 12's module and `_reconcile` docstrings, Blind spots 4 and 16. D9-D11 are history. With the feature disabled the completed winner routes (R4-2) and the ledger stays `pending` until the service is enabled.

### D14 — Review round 6 (2026-10-14, Diff Reviewer GPT-6.1 Sol, `logs/architect/review-ad1326-r6.md`; R6-1 a regression of R5-2, R6-2 wording)

Rule for this round (the last repair round): close a regression of a repair with the smallest blast radius, preferring to restore behaviour earlier rounds accepted and to remove a seam rather than add a mechanism. Method counts after this round: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5 (none added), `ProcedureStore` +1 (`routing_state`; 56 -> 57). The `srp-size` check compares only the trigger set of a baseline row (`check_architecture_principles.py:937-943`), and `ProcedureStore`'s row already carries `lines` and `methods` (`architecture-baseline.yaml:606-614`), so one more method does not trip it and the baseline does not change. Neither the ledger file nor either schema changes. D13's R5-2 option (A), its "no routing decision reads them from `get`" sentence and Blind spot 18's first form are superseded here, not rewritten.

**R6-1 [P2, regression of R5-2] — a half-merged `get`.** R5-2 made `ProcedureStore.get` take `is_active`/`superseded_by` from the columns and every other field from the snapshot. `restore_procedure` (`procedure_store.py:1691-1733`) updates the columns (`is_active=1, is_archived=0, compilation_level=1`), swallows a refused snapshot UPDATE, then publishes `get`'s object to the index: active, at the snapshot's level 4, and `CognitiveAgent._check_procedural_memory` dispatches on the `compilation_level` it reads from `get` (`cognitive_agent.py:1824, 1848-1864`), so a procedure restored to Level 1 replayed autonomously. With base `get` the same restore published inactive and nothing replayed.
1. **Chosen: (B) revert R5-2's change to `get` (3f2 withdrawn: every one of its 40 callers sees base behaviour again) and give AD-1326 one column read, `ProcedureStore.routing_state(id) -> tuple[bool, str] | None`** (`is_active`, `superseded_by`; `None` without a row). It is the source of every lineage decision this AD makes: `_get_index_row`'s R4-2 predicate (3g: `routing_state(champion) == (False, challenger)`, replacing the inline SELECT), `sync_routing_index`'s published `is_active` (R3-3's override as accepted in rounds 3 and 4, D11, now through `routing_state`), and, in `ProcedureChallenger`, `_contest`'s champion gate, `_reconcile`'s challenger activity and completed-promotion predicate, and `_complete_promotion`'s two activity checks (Section 12; `ChallengeProcedureStore` gains the method). `get` is read only for content (judging, rendering, re-saving). R5-2's reproduction (zero judge budget, stale champion snapshot) still records `restored_promotion` and keeps the winner routed, because `_reconcile` reads the champion's columns, as admission does. R6-1's reproduction publishes inactive again (base): the restored procedure does not route until it is re-saved, the pre-existing legacy cost of a swallowed restore (Blind spot 18). Why all five service sites and not only `_reconcile`: `_contest`'s gate read the champion through `get` before R5-2; with the champion's snapshot stale-active and the restored promotion now recorded, a second open challenger would be judged against a superseded champion and could be promoted beside the first (two active in one lineage); and `_complete_promotion`'s `if not challenger.is_active` would seal a promotion whose challenger's column is inactive behind a stale-active snapshot (neither routes). R5-2's merged `get` had closed both as a side effect; `routing_state` keeps them closed without `get`.
2. (A) the reviewer's: also merge `compilation_level` and `is_archived` into `get`. `promote_compilation_level` and `demote_compilation_level` write the `compilation_level` column only, never the snapshot (`procedure_store.py:1036-1064`; `decay_stale_procedures` writes both, `:1555-1567`), so base `get` reports the level at the last `save` and the agent dispatches on it. Merging the column changes AD-535's dispatch and its promotion/demotion arithmetic (`cognitive_agent.py:7532-7559`) for every procedure ever promoted or demoted, without any swallowed failure; `promotion_status` and the counters drift the same way. It fixes a legacy defect outside this issue by changing what all 40 callers see. Loses on blast radius.
3. (C) revert and give `_reconcile` its own SELECT through a different public method — a second column reader beside admission's: the two-source seam R5-2 was about, moved. Loses on DRY.
4. (D, mine) keep R5-2 and stop `restore_procedure` from publishing on a failed snapshot write — a legacy best-effort writer changed for this AD (f26's scope), and the half-merged `get` stays for the other 39 callers. Loses on blast radius.

**R6-2 [wording] — "committed rows only" holds while cleanup succeeds.** With a `ROLLBACK` that itself fails (Blind spots 14, 17) the transaction stays open and every public read returns its uncommitted rows until the store restarts; reproduced by the reviewer, pre-existing, accepted. Qualified (no behaviour change) in: Section 2's module docstring, `ProcedureChallengeLedger.get`'s docstring and its `async with` comment (mutation row 74's anchor moves with it), Acceptance 19. Unchanged, because they already state the condition: `_write_transaction`'s docstring (it names the failed rollback), Blind spots 14 and 17, and the test helpers' "committed rows only" (an independent second connection). D11 (R3-2) and D13 (R5-1) are history; D13's "so a read sees only committed rows" is qualified by this paragraph.

---

## Implementation

Line endings: the tree is CRLF. Every SEARCH below is unique in its file at base `a71575ec` (verified by grep, see Verified). Stage by explicit path; never `git add -A`.

### Milestone 1 — ranking, ledger, store lifecycle

#### Section 1 -- `src/probos/cognitive/procedure_ranking.py` (NEW)

```python
"""AD-1326 (#1510): deterministic ranking of procedure candidates from pairwise outcomes.

A Bradley-Terry model gives each candidate a strength ``p``; ``i`` is expected to
beat ``j`` with probability ``p_i / (p_i + p_j)``. :func:`bradley_terry` fits it
with Hunter's MM iteration (Ann. Statist. 32(1), 2004). Two choices make the fit
total and deterministic:

- **Pseudo-counts.** Every pair that met at least once gets ``prior`` extra wins on
  each side, so a candidate that never won still has a finite, positive strength.
- **A reference.** The reference (the champion) is pinned to strength 1.0. On a
  star -- every candidate compared only with the reference, which is what dream
  consolidation produces -- the fit is closed-form:
  ``p_i = (w_i + t_i / 2 + prior) / (l_i + t_i / 2 + prior)``, and it is returned
  directly. With the default prior every count is a multiple of 0.5, so two equal
  records give ``==`` strengths and the caller's tie-break decides, not solver
  roundoff (``test_bradley_terry_star_equal_records_are_exactly_equal``).

A tie counts half a win to each side. Outcomes are folded into per-pair counts in
sorted order and players are updated in sorted order, so one set of outcomes gives
bit-identical strengths in whatever order it arrives
(``test_bradley_terry_is_order_independent_bit_for_bit``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PairResult = Literal["first", "second", "tie"]

DEFAULT_PRIOR = 0.5
MAX_ITERATIONS = 1000
TOLERANCE = 1e-12


@dataclass(frozen=True)
class PairOutcome:
    """One pairwise judgement between ``first`` and ``second``."""

    first: str
    second: str
    result: PairResult

    def __post_init__(self) -> None:
        if type(self.first) is not str or type(self.second) is not str:
            raise ValueError("pair_outcome_invalid")
        if not self.first or not self.second or self.first == self.second:
            raise ValueError("pair_outcome_invalid")
        if self.result not in ("first", "second", "tie"):
            raise ValueError("pair_outcome_invalid")


def _pair_wins(outcomes: Iterable[PairOutcome], prior: float) -> dict[tuple[str, str], list[float]]:
    """``(a, b)`` with ``a < b`` -> ``[wins of a, wins of b]``: ties halved, pseudo-counts added."""
    counts: dict[tuple[str, str], list[float]] = {}
    for outcome in sorted(outcomes, key=lambda o: (o.first, o.second, o.result)):
        a, b = sorted((outcome.first, outcome.second))
        wins = counts.setdefault((a, b), [prior, prior])
        if outcome.result == "tie":
            wins[0] += 0.5
            wins[1] += 0.5
        else:
            winner = outcome.first if outcome.result == "first" else outcome.second
            wins[0 if winner == a else 1] += 1.0
    return counts


def _require_connected(links: dict[str, list[tuple[str, float, float]]], reference: str) -> None:
    reached = {reference}
    frontier = [reference]
    while frontier:
        name = frontier.pop()
        for other, _, _ in links[name]:
            if other not in reached:
                reached.add(other)
                frontier.append(other)
    if len(reached) != len(links):
        raise ValueError("bradley_terry_disconnected")


def bradley_terry(
    outcomes: Iterable[PairOutcome],
    *,
    reference: str,
    prior: float = DEFAULT_PRIOR,
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = TOLERANCE,
) -> dict[str, float]:
    """Strength per player, ``reference`` pinned to 1.0.

    Raises ``ValueError`` for an empty or non-string reference, a prior that is not
    a positive finite number, ``max_iterations < 1``, a negative tolerance, or a
    player with no chain of comparisons to the reference (its scale would be
    arbitrary). No outcomes gives ``{reference: 1.0}``.
    """
    if type(reference) is not str or not reference:
        raise ValueError("bradley_terry_reference_invalid")
    if not (math.isfinite(prior) and prior > 0.0):
        raise ValueError("bradley_terry_prior_invalid")
    if max_iterations < 1 or not tolerance >= 0.0:
        raise ValueError("bradley_terry_iteration_invalid")
    counts = _pair_wins(outcomes, prior)
    players = sorted({reference, *(name for pair in counts for name in pair)})
    links: dict[str, list[tuple[str, float, float]]] = {name: [] for name in players}
    for (first, second), (first_wins, second_wins) in sorted(counts.items()):
        games = first_wins + second_wins
        links[first].append((second, first_wins, games))
        links[second].append((first, second_wins, games))
    _require_connected(links, reference)
    if all(reference in pair for pair in counts):
        # A star: each candidate met only the reference, so its strength is its wins over the
        # reference's wins in their pair, computed directly (exact; no iteration roundoff).
        star = {reference: 1.0}
        for (first, second), (first_wins, second_wins) in counts.items():
            if first == reference:
                star[second] = second_wins / first_wins
            else:
                star[first] = first_wins / second_wins
        return {name: star[name] for name in players}
    strength = dict.fromkeys(players, 1.0)
    for _ in range(max_iterations):
        previous = dict(strength)
        for name in players:
            if not links[name]:
                continue
            wins = sum(won for _, won, _ in links[name])
            spread = sum(games / (strength[name] + strength[other]) for other, _, games in links[name])
            strength[name] = wins / spread
        scale = strength[reference]
        for name in players:
            strength[name] /= scale
        if max(abs(strength[name] - previous[name]) / previous[name] for name in players) <= tolerance:
            break
    return strength


def beats_champion(*, wins: int, decisions: int, min_decisions: int, margin: float) -> bool:
    """AD-1326: whether ``wins`` of ``decisions`` counted judgements promote a challenger.

    True only with at least ``min_decisions`` (and at least one) judgements and a
    win share strictly above ``0.5 + margin``. Ties and losses count against it.
    """
    if decisions < max(min_decisions, 1) or wins < 0 or wins > decisions:
        return False
    return wins / decisions > 0.5 + margin
```

#### Section 2 -- `src/probos/cognitive/procedure_challenges.py` (NEW)

```python
"""AD-1326 (#1510): the durable record of procedure challengers and their evidence.

``ProcedureChallenger`` saves a FIX evolution inactive for routing and records it
here as a challenger of its parent, the champion. Each situation judged in both
orders is a ``procedure_comparisons`` row; the decision and its reason stay on the
challenge row; each dream cycle that judged, deferred or decided something leaves a
``procedure_challenge_cycles`` row. This module never removes a row, so a retired
challenger keeps its evidence (``test_retired_challenger_keeps_its_comparisons``,
``test_ledger_module_issues_no_delete``).

The file is ``procedures_challenges.db`` beside ``procedures.db``, on its own
connection. ``ProcedureStore`` opens that connection from its ``ConnectionFactory``,
holds it as a direct attribute (so BF-882's last-resort close reaches it when the
store's ``stop()`` fails in a startup rollback), hands it to this ledger and closes
it; the ledger applies its schema in ``start`` and lets go in ``detach``. Each status
change names the statuses it may move from, so a decided challenger cannot be moved
again (``test_set_status_is_conditional_on_expected``). Every write runs in one
transaction (``_write_transaction``) that is rolled back under the ledger lock on any
failure, cancellation included, so the connection never reads a row no other reader
can see (review round 3, R3-2; ``test_failed_ledger_write_is_rolled_back``). The lock is
held until that rollback has run, also when the cancelled statement is still queued on
the connection's worker thread (review round 4, R4-1;
``test_a_cancelled_begin_is_rolled_back_after_it_takes_effect``). Every public read takes
the same lock, so a read on this connection never sees a write that is not yet committed
or is about to be rolled back (review round 5, R5-1;
``test_every_public_ledger_read_waits_for_an_in_flight_write``). These hold while cleanup
succeeds: a ``ROLLBACK`` that itself fails leaves the transaction open, and every read on
this connection may then return its uncommitted rows until the store restarts (an accepted
residual that needs a broken connection; review round 6, R6-2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

logger = logging.getLogger(__name__)

ChallengeStatus = Literal["pending", "promoting", "promoted", "retired"]
ContextSplit = Literal["used", "held_out"]
Side = Literal["champion", "challenger"]
Outcome = Literal["champion", "challenger", "tie", "invalid"]

_STATUSES: frozenset[str] = frozenset({"pending", "promoting", "promoted", "retired"})
_SPLITS: frozenset[str] = frozenset({"used", "held_out"})
_SIDES: frozenset[str] = frozenset({"champion", "challenger"})
_OUTCOMES: frozenset[str] = frozenset({"champion", "challenger", "tie", "invalid"})

MAX_ID_CHARS = 128
MAX_MODEL_CHARS = 256
MAX_EPISODE_IDS = 20
MAX_DECISION_CHARS = 1000
MAX_JUDGEMENTS_BYTES = 8192

_SCHEMA = """
CREATE TABLE IF NOT EXISTS procedure_challenges (
    challenger_id TEXT PRIMARY KEY,
    champion_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'promoting', 'promoted', 'retired')),
    created_at REAL NOT NULL,
    cycles_pending INTEGER NOT NULL DEFAULT 0,
    used_episode_ids TEXT NOT NULL DEFAULT '[]',
    held_out_episode_ids TEXT NOT NULL DEFAULT '[]',
    context_episode_ids TEXT NOT NULL DEFAULT '[]',
    optimizer_tier TEXT NOT NULL DEFAULT '',
    optimizer_model TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    decided_at REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_procedure_challenges_status
    ON procedure_challenges(status, champion_id);

CREATE TABLE IF NOT EXISTS procedure_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id TEXT NOT NULL,
    champion_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('used', 'held_out')),
    first_shown TEXT NOT NULL CHECK (first_shown IN ('champion', 'challenger')),
    outcome TEXT NOT NULL CHECK (outcome IN ('champion', 'challenger', 'tie', 'invalid')),
    counted INTEGER NOT NULL CHECK (counted IN (0, 1)),
    judgements TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_procedure_comparisons_challenger
    ON procedure_comparisons(challenger_id);

CREATE TABLE IF NOT EXISTS procedure_challenge_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at REAL NOT NULL,
    judge_calls INTEGER NOT NULL,
    comparisons INTEGER NOT NULL,
    deferred INTEGER NOT NULL,
    promoted INTEGER NOT NULL,
    retired INTEGER NOT NULL
);
"""

_CHALLENGE_COLUMNS = (
    "challenger_id, champion_id, status, created_at, cycles_pending, used_episode_ids, "
    "held_out_episode_ids, context_episode_ids, optimizer_tier, optimizer_model, "
    "decision_reason, decided_at"
)

# A champion's open challengers: what ``pending_count`` reports and ``add_challenger`` caps.
_PENDING_COUNT_SQL = (
    "SELECT COUNT(*) FROM procedure_challenges "
    "WHERE champion_id = ? AND status IN ('pending', 'promoting')"
)


def bounded_text(value: object, limit: int) -> str:
    """AD-1326: ``value`` as text SQLite and a strict UTF-8 encoder accept, at most ``limit`` characters.

    NUL characters are removed and a lone surrogate (what a provider's JSON
    ``\\ud800`` escape decodes to, which ``json.loads`` lets through) becomes ``?``,
    so the result can be bound, ``json.dumps``-ed and ``.encode("utf-8")``-ed. A
    value that is not exactly a ``str``, or a ``limit`` below 1, gives ``""``.
    """
    if type(value) is not str or limit < 1:
        return ""
    cleaned = value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")
    return cleaned[:limit]


def _checked_id(value: object, what: str) -> str:
    if type(value) is not str or not value or bounded_text(value, MAX_ID_CHARS) != value:
        raise ValueError(f"procedure_challenge_{what}_invalid")
    return value


def _checked_ids(values: object, what: str) -> list[str]:
    if type(values) not in (list, tuple):
        raise ValueError(f"procedure_challenge_{what}_invalid")
    ids = [_checked_id(value, what) for value in values]  # type: ignore[union-attr]
    if len(ids) > MAX_EPISODE_IDS or len(set(ids)) != len(ids):
        raise ValueError(f"procedure_challenge_{what}_invalid")
    return ids


async def _roll_back(db: DatabaseConnection) -> None:
    """``ROLLBACK`` on ``db``; a failure other than "nothing to undo" is logged at ERROR.

    SQLite refuses a ``ROLLBACK`` when no transaction is open ("cannot rollback - no
    transaction is active"). For a ledger write that means the goal already holds: a
    cancelled ``BEGIN IMMEDIATE`` that then failed on the busy timeout, or a cancelled
    ``COMMIT`` that the worker thread still completed (review round 4, R4-1). Neither is logged.
    """
    try:
        await db.execute("ROLLBACK")
    except Exception as exc:
        if "no transaction is active" in str(exc):
            return
        # Propagate (the original error): this log is the only trace of the open transaction.
        logger.error(
            "AD-1326: a failed procedure challenger ledger write could not be rolled back; "
            "a transaction left open makes the ledger refuse further writes until the procedure store restarts",
            exc_info=True,
        )


@asynccontextmanager
async def _write_transaction(
    lock: asyncio.Lock, connect: Callable[[], DatabaseConnection],
) -> AsyncIterator[DatabaseConnection]:
    """One ledger write: under ``lock``, ``BEGIN IMMEDIATE``, the caller's statements, ``commit``.

    Any failure after ``BEGIN`` -- a statement, the commit, or a cancellation -- is rolled
    back under the same lock before it propagates. Left open, the transaction would let this
    connection read its own uncommitted row while every other reader sees the old one, and a
    later cycle would skip the durable transition it never made (review round 3, R3-2). A
    rollback that itself fails is logged at ERROR and the original error propagates; the next
    write's ``BEGIN IMMEDIATE`` then fails if that transaction is still open, so nothing is built on it.

    Cancelling a call does not withdraw it: aiosqlite runs one connection's calls in order on
    one worker thread, so a ``BEGIN`` cancelled while it waited for another connection's lock
    can still take effect, and a cancelled ``COMMIT`` can still commit. Only a ``BEGIN`` answered
    with an error opened nothing; on every other failure the ``ROLLBACK`` is queued behind the
    cancelled call, and the lock is held, through further cancellations, until it has run
    (review round 4, R4-1). The wait is governed by SQLite's busy handler (``busy_timeout``, set in
    ``start``): a budget for retrying a locked database, not a wall-clock ceiling, so the measured
    wait can exceed it (review round 5, R5-3). The cleanup is deliberately not time-limited:
    abandoning it would leave the transaction open. A cancellation that arrives during that wait is
    delivered afterwards.
    """
    async with lock:
        db = connect()
        begin_refused = False
        try:
            try:
                await db.execute("BEGIN IMMEDIATE")
            except Exception:
                # SQLite answered the BEGIN with an error, so no transaction was opened.
                begin_refused = True
                raise
            yield db
            await db.commit()
        except BaseException as exc:
            if begin_refused:
                raise
            cleanup = asyncio.create_task(_roll_back(db))
            cancelled_again = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled_again = True
            if cancelled_again and not isinstance(exc, asyncio.CancelledError):
                raise asyncio.CancelledError() from exc
            raise


@dataclass(frozen=True)
class ChallengeRecord:
    """One challenger and the champion it challenges (a ``procedure_challenges`` row)."""

    challenger_id: str
    champion_id: str
    status: ChallengeStatus
    created_at: float
    cycles_pending: int
    used_episode_ids: tuple[str, ...]
    held_out_episode_ids: tuple[str, ...]
    context_episode_ids: tuple[str, ...]
    optimizer_tier: str
    optimizer_model: str
    decision_reason: str
    decided_at: float

    @property
    def bars_routing(self) -> bool:
        """Whether this challenger must not route whatever ``procedures.db`` says: undecided or lost.

        ``ProcedureStore`` admits a match through this (review round 3, R3-5), so, while the ledger
        is open and readable, a restore that pairs a ``pending`` row with an active challenger does
        not route it -- unless ``procedures.db`` already holds that challenger's completed promotion
        (review round 4, R4-2; ``ProcedureStore._get_index_row``).
        """
        return self.status in ("pending", "retired")


@dataclass(frozen=True)
class ComparisonRecord:
    """One situation judged in both orders (a ``procedure_comparisons`` row)."""

    challenger_id: str
    champion_id: str
    episode_id: str
    split: ContextSplit
    first_shown: Side
    outcome: Outcome
    counted: bool
    judgements: tuple[dict[str, Any], ...]
    created_at: float


def _challenge_from_row(row: Sequence[Any]) -> ChallengeRecord:
    return ChallengeRecord(
        challenger_id=row[0],
        champion_id=row[1],
        status=row[2],
        created_at=float(row[3]),
        cycles_pending=int(row[4]),
        used_episode_ids=tuple(json.loads(row[5])),
        held_out_episode_ids=tuple(json.loads(row[6])),
        context_episode_ids=tuple(json.loads(row[7])),
        optimizer_tier=row[8],
        optimizer_model=row[9],
        decision_reason=row[10],
        decided_at=float(row[11]),
    )


class ProcedureChallengeLedger:
    """AD-1326: procedure challengers, their comparisons and per-cycle budget use."""

    def __init__(
        self,
        connection: DatabaseConnection,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """``connection`` is open and owned by the caller (``ProcedureStore``), which closes it."""
        if connection is None:
            raise ValueError("procedure_challenge_connection_missing")
        self._connection = connection
        self._db: DatabaseConnection | None = None
        self._lock = asyncio.Lock()
        self._clock = clock

    async def start(self) -> None:
        """Apply the schema on the owner's connection; a failure propagates and the owner closes it."""
        db = self._connection
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(_SCHEMA)
        await db.commit()
        self._db = db

    def detach(self) -> None:
        """Stop using the connection (its owner closes it); every later call raises ``RuntimeError``."""
        self._db = None

    def _conn(self) -> DatabaseConnection:
        if self._db is None:
            raise RuntimeError("procedure challenge ledger is not started")
        return self._db

    async def add_challenger(
        self,
        *,
        challenger_id: str,
        champion_id: str,
        used_episode_ids: Sequence[str],
        held_out_episode_ids: Sequence[str],
        context_episode_ids: Sequence[str],
        optimizer_tier: str = "",
        optimizer_model: str = "",
        max_pending: int | None = None,
    ) -> ChallengeRecord:
        """Record a new challenger, ``pending``; a duplicate id raises (the PRIMARY KEY).

        With ``max_pending``, counting the champion's ``pending``/``promoting`` challengers
        and the insert run under one lock, so overlapping submits cannot pass the cap: a
        challenger that would exceed it is recorded ``retired`` with reason
        ``pending_limit`` instead, so the inactive procedure row it names stays accounted
        for (``test_add_challenger_enforces_the_pending_cap_atomically``).
        """
        challenger = _checked_id(challenger_id, "challenger_id")
        champion = _checked_id(champion_id, "champion_id")
        if challenger == champion:
            raise ValueError("procedure_challenge_self_challenge")
        used = _checked_ids(used_episode_ids, "episode_ids")
        held_out = _checked_ids(held_out_episode_ids, "episode_ids")
        contexts = _checked_ids(context_episode_ids, "episode_ids")
        if set(used) & set(held_out) or not set(contexts) <= set(used) | set(held_out):
            raise ValueError("procedure_challenge_episode_ids_invalid")
        if max_pending is not None and (type(max_pending) is not int or max_pending < 1):
            raise ValueError("procedure_challenge_max_pending_invalid")
        tier = bounded_text(optimizer_tier, MAX_ID_CHARS)
        model = bounded_text(optimizer_model, MAX_MODEL_CHARS)
        now = self._clock()
        status: ChallengeStatus = "pending"
        reason = ""
        decided_at = 0.0
        async with _write_transaction(self._lock, self._conn) as db:
            if max_pending is not None:
                cursor = await db.execute(_PENDING_COUNT_SQL, (champion,))
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
                if count >= max_pending:
                    status, reason, decided_at = "retired", f"pending_limit: pending={count} max={max_pending}", now
            await db.execute(
                f"INSERT INTO procedure_challenges ({_CHALLENGE_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    challenger, champion, status, now, 0, json.dumps(used), json.dumps(held_out),
                    json.dumps(contexts), tier, model, reason, decided_at,
                ),
            )
        return ChallengeRecord(
            challenger, champion, status, now, 0, tuple(used), tuple(held_out), tuple(contexts),
            tier, model, reason, decided_at,
        )

    async def get(self, challenger_id: str) -> ChallengeRecord | None:
        """The committed row of ``challenger_id``; routing admission reads it (``ProcedureStore._get_index_row``).

        Committed while every rollback succeeds; after a ``ROLLBACK`` that itself failed, the open
        transaction's row (review round 6, R6-2).
        """
        async with self._lock:  # R5-1 (get): committed rows while cleanup succeeds
            cursor = await self._conn().execute(
                f"SELECT {_CHALLENGE_COLUMNS} FROM procedure_challenges WHERE challenger_id = ?",
                (challenger_id,),
            )
            row = await cursor.fetchone()
        return _challenge_from_row(row) if row else None

    async def list_by_status(self, status: ChallengeStatus) -> list[ChallengeRecord]:
        """Challengers in ``status``, oldest first (ties by id)."""
        if status not in _STATUSES:
            raise ValueError("procedure_challenge_status_invalid")
        async with self._lock:  # R5-1 (list_by_status)
            cursor = await self._conn().execute(
                f"SELECT {_CHALLENGE_COLUMNS} FROM procedure_challenges WHERE status = ? "
                "ORDER BY created_at, challenger_id",
                (status,),
            )
            rows = await cursor.fetchall()
        return [_challenge_from_row(row) for row in rows]

    async def pending_count(self, champion_id: str) -> int:
        """Challengers of ``champion_id`` that are ``pending`` or ``promoting``."""
        async with self._lock:  # R5-1 (pending_count)
            cursor = await self._conn().execute(_PENDING_COUNT_SQL, (champion_id,))
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def record_comparison(
        self,
        *,
        challenger_id: str,
        champion_id: str,
        episode_id: str,
        split: ContextSplit,
        first_shown: Side,
        outcome: Outcome,
        counted: bool,
        judgements: Sequence[dict[str, Any]],
    ) -> None:
        """Record one situation judged in both orders. An ``invalid`` outcome is never counted."""
        if split not in _SPLITS or first_shown not in _SIDES or outcome not in _OUTCOMES:
            raise ValueError("procedure_comparison_invalid")
        if type(counted) is not bool or (counted and outcome == "invalid"):
            raise ValueError("procedure_comparison_invalid")
        payload = json.dumps(list(judgements), ensure_ascii=False, sort_keys=True)
        # Strict encode: a lone surrogate raises UnicodeEncodeError (a ValueError).
        if len(payload.encode("utf-8")) > MAX_JUDGEMENTS_BYTES:
            raise ValueError("procedure_comparison_judgements_too_large")
        values = (
            _checked_id(challenger_id, "challenger_id"),
            _checked_id(champion_id, "champion_id"),
            _checked_id(episode_id, "episode_id"),
            split, first_shown, outcome, int(counted), payload, self._clock(),
        )
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "INSERT INTO procedure_comparisons (challenger_id, champion_id, episode_id, split, "
                "first_shown, outcome, counted, judgements, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    async def comparisons(self, challenger_id: str) -> list[ComparisonRecord]:
        """Every comparison of ``challenger_id``, in the order recorded."""
        async with self._lock:  # R5-1 (comparisons)
            cursor = await self._conn().execute(
                "SELECT challenger_id, champion_id, episode_id, split, first_shown, outcome, counted, "
                "judgements, created_at FROM procedure_comparisons WHERE challenger_id = ? ORDER BY id",
                (challenger_id,),
            )
            rows = await cursor.fetchall()
        return [
            ComparisonRecord(
                row[0], row[1], row[2], row[3], row[4], row[5], bool(row[6]),
                tuple(json.loads(row[7])), float(row[8]),
            )
            for row in rows
        ]

    async def set_status(
        self,
        challenger_id: str,
        status: ChallengeStatus,
        *,
        reason: str,
        expected: Sequence[ChallengeStatus],
    ) -> bool:
        """Move a challenger from one of ``expected`` to ``status``; False when it was in none of them."""
        if status not in _STATUSES or not expected or any(item not in _STATUSES for item in expected):
            raise ValueError("procedure_challenge_status_invalid")
        marks = ", ".join("?" for _ in expected)
        async with _write_transaction(self._lock, self._conn) as db:
            cursor = await db.execute(
                "UPDATE procedure_challenges SET status = ?, decision_reason = ?, decided_at = ? "
                f"WHERE challenger_id = ? AND status IN ({marks})",
                (status, bounded_text(reason, MAX_DECISION_CHARS), self._clock(), challenger_id, *expected),
            )
            changed = cursor.rowcount == 1
        return changed

    async def increment_cycles(self, challenger_id: str) -> int:
        """Add one to a ``pending`` challenger's ``cycles_pending``; return the stored value."""
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "UPDATE procedure_challenges SET cycles_pending = cycles_pending + 1 "
                "WHERE challenger_id = ? AND status = 'pending'",
                (challenger_id,),
            )
            cursor = await db.execute(
                "SELECT cycles_pending FROM procedure_challenges WHERE challenger_id = ?",
                (challenger_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def record_cycle(
        self, *, judge_calls: int, comparisons: int, deferred: int, promoted: int, retired: int,
    ) -> None:
        values = (judge_calls, comparisons, deferred, promoted, retired)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("procedure_challenge_cycle_invalid")
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "INSERT INTO procedure_challenge_cycles (recorded_at, judge_calls, comparisons, deferred, "
                "promoted, retired) VALUES (?, ?, ?, ?, ?, ?)",
                (self._clock(), *values),
            )

    async def recent_cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        """The newest ``limit`` cycle rows, newest first."""
        async with self._lock:  # R5-1 (recent_cycles)
            cursor = await self._conn().execute(
                "SELECT recorded_at, judge_calls, comparisons, deferred, promoted, retired "
                "FROM procedure_challenge_cycles ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            )
            rows = await cursor.fetchall()
        keys = ("recorded_at", "judge_calls", "comparisons", "deferred", "promoted", "retired")
        return [dict(zip(keys, row)) for row in rows]
```

#### Section 3 -- `src/probos/cognitive/procedure_store.py`

3a. `src/probos/cognitive/procedure_store.py`: type-only import.

```
<<<<<<< SEARCH
if TYPE_CHECKING:
    from probos.cognitive.procedures import Procedure
    from probos.protocols import ConnectionFactory, DatabaseConnection
=======
if TYPE_CHECKING:
    from probos.cognitive.procedure_challenges import ProcedureChallengeLedger
    from probos.cognitive.procedures import Procedure
    from probos.protocols import ConnectionFactory, DatabaseConnection
>>>>>>> REPLACE
```

3b. `src/probos/cognitive/procedure_store.py`: the ledger slot and its connection (D1b).

```
<<<<<<< SEARCH
        self._chroma_collection: Any = None
        self._chroma_client: Any = None

    async def start(self) -> None:
=======
        self._chroma_collection: Any = None
        self._chroma_client: Any = None
        # AD-1326 (D1b): the ledger's connection is held here, one attribute level deep, so
        # BF-882's last-resort close (startup/shutdown.py _direct_connections) reaches it when
        # this store's stop() fails during a startup rollback.
        self._challenges_db: DatabaseConnection | None = None
        self._challenges: ProcedureChallengeLedger | None = None  # AD-1326

    async def start(self) -> None:
>>>>>>> REPLACE
```

3c. `src/probos/cognitive/procedure_store.py`: open the ledger last in `start()`.

```
<<<<<<< SEARCH
            # AD-535: Auto-promote qualifying Level 1 procedures to Level 2
            await self._migrate_qualifying_procedures()
        except asyncio.CancelledError:
=======
            # AD-535: Auto-promote qualifying Level 1 procedures to Level 2
            await self._migrate_qualifying_procedures()
            # AD-1326: the challenger ledger shares this store's lifecycle, not its file.
            await self._start_challenge_ledger()
        except asyncio.CancelledError:
>>>>>>> REPLACE
```

3d. `src/probos/cognitive/procedure_store.py`: the opener and the public accessor.

```
<<<<<<< SEARCH
    async def stop(self) -> None:
        """Close database connections."""
        await self._close_resources()
=======
    async def _start_challenge_ledger(self) -> None:
        """AD-1326: open procedures_challenges.db; a failure leaves the store running without it.

        This store opens the connection and holds it as ``_challenges_db`` (D1b); the ledger
        only uses it. Assigned before the schema runs, so a cancellation during it is closed by
        ``start``'s own ``_close_resources``. The name sorts after ``procedures.db``, so the hot
        backup (which copies in sorted path order) copies the ledger second, and when both online
        backups succeed it is never older than ``procedures.db``
        (``test_backup_copies_the_ledger_after_procedures_db``). The backup's raw-copy fallback can
        copy an older ledger image; admission then refuses its undecided challengers (R3-5, 3g).
        """
        from probos.cognitive.procedure_challenges import ProcedureChallengeLedger

        try:
            self._challenges_db = await self._connection_factory.connect(
                str(self._data_dir / "procedures_challenges.db")
            )
            ledger = ProcedureChallengeLedger(self._challenges_db)
            await ledger.start()
        except Exception:
            opened, self._challenges_db = self._challenges_db, None
            if opened is not None:
                try:
                    await opened.close()
                except Exception:
                    # Log-and-degrade: the WARNING below already reports the ledger as unavailable.
                    logger.debug("AD-1326: closing the unopened ledger's connection failed", exc_info=True)
            logger.warning(
                "AD-1326: the procedure challenger ledger could not be opened; FIX evolution "
                "follows its legacy handling until the next start",
                exc_info=True,
            )
            return
        self._challenges = ledger

    @property
    def challenges(self) -> ProcedureChallengeLedger | None:
        """AD-1326: the challenger ledger, or ``None`` when it is not open."""
        return self._challenges

    async def stop(self) -> None:
        """Close database connections."""
        await self._close_resources()
>>>>>>> REPLACE
```

3e. `src/probos/cognitive/procedure_store.py`: close the ledger with the store.

```
<<<<<<< SEARCH
    async def _close_resources(self) -> None:
        """Close and clear all resources acquired by this store."""
        self._chroma_collection = None
=======
    async def _close_resources(self) -> None:
        """Close and clear all resources acquired by this store."""
        ledger, self._challenges = self._challenges, None
        if ledger is not None:
            ledger.detach()
        challenges_db, self._challenges_db = self._challenges_db, None
        if challenges_db is not None:
            try:
                await challenges_db.close()
            except Exception:
                logger.warning(
                    "AD-1326: failed to close the procedure challenger ledger's database; its "
                    "reference is cleared and shutdown continues",
                    exc_info=True,
                )
        self._chroma_collection = None
>>>>>>> REPLACE
```

3f. `src/probos/cognitive/procedure_store.py`: the one routing-index method promotion needs (review round 1, F1; D9) and the one column read every AD-1326 lineage decision shares, `routing_state` (review round 6, R6-1; D14). `save`, `deactivate` and `get` are not changed.

```
<<<<<<< SEARCH
                getattr(procedure, "id", "<unknown>"),
                e,
            )
            return False

    async def get(self, procedure_id: str) -> "Any | None":
=======
                getattr(procedure, "id", "<unknown>"),
                e,
            )
            return False

    async def sync_routing_index(self, procedure_id: str) -> bool:
        """AD-1326: rewrite one procedure's semantic-index entry from SQLite; whether routing agrees.

        ``find_matching`` reads only the index, and ``save``/``deactivate`` report an index
        write failure only in the log. True when the entry was rewritten from the
        authoritative row, when there is no row (``find_matching`` drops ids without one),
        or when this store runs without an index (it then matches nothing); False when the
        index is open and the write failed (``_save_to_chroma`` logs the WARNING). The entry's
        ``is_active`` comes from the row's column through ``routing_state``, not from the snapshot
        ``get`` returns (review rounds 3 and 6, R3-3, R6-1;
        ``test_sync_routing_index_publishes_the_activity_column``).
        """
        if not self._chroma_collection:
            return True
        procedure = await self.get(procedure_id)
        if procedure is None:
            return True
        state = await self.routing_state(procedure_id)
        if state is not None:
            procedure.is_active = state[0]  # R3-3/R6-1: publish the column admission reads
        return self._save_to_chroma(procedure)

    async def routing_state(self, procedure_id: str) -> tuple[bool, str] | None:
        """AD-1326: a procedure's ``is_active`` and ``superseded_by`` columns; ``None`` without a row.

        Routing admission (``_get_index_row``) reads these columns. The JSON snapshot ``get``
        rebuilds a procedure from can be older: ``deactivate``, archive and ``restore_procedure``
        swallow a failed snapshot UPDATE after the columns change. ``get`` keeps its base
        behaviour for its legacy callers; every lineage decision of AD-1326 (admission, the
        published index flag, ``ProcedureChallenger``) reads here, so they share one source
        (review round 6, R6-1; ``test_routing_state_reads_the_columns_not_the_snapshot``).
        """
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT is_active, superseded_by FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return bool(row[0]), row[1] or ""

    async def get(self, procedure_id: str) -> "Any | None":
>>>>>>> REPLACE
```

3f2. *Withdrawn in review round 6 (R6-1; D14).* `ProcedureStore.get` is not edited: it returns the base object rebuilt from the JSON snapshot for all 40 callers. AD-1326 reads lineage through `routing_state` (3f). A Builder starting from a tree that carries round 5's 3f2 restores `get` to base (`git show a71575ec:src/probos/cognitive/procedure_store.py`, the method after `sync_routing_index`).

3g. `src/probos/cognitive/procedure_store.py`: routing admission reads SQLite's `is_active` (review round 2, R2-1 (B); D10) and the ledger's verdict (review round 3, R3-5; D11). `_get_index_row` has one caller, `find_matching` (base `:814`); the row keys do not change. No method is added.

```
<<<<<<< SEARCH
    async def _get_index_row(self, procedure_id: str) -> dict[str, Any] | None:
        """Load procedure metadata from SQLite index (no full content)."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            """SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks, is_negative
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
=======
    async def _get_index_row(self, procedure_id: str) -> dict[str, Any] | None:
        """Load a routable procedure's metadata from SQLite (no full content); ``None`` otherwise.

        ``find_matching`` admits a semantic-index match only through this row. SQLite's
        ``is_active`` can veto an entry the index admits, so a stale ACTIVE entry does not route
        an inactive procedure (``save`` and ``deactivate`` report an index write failure only in
        the log; AD-1326 review round 2, R2-1, ``test_find_matching_admits_only_rows_active_in_sqlite``).
        It cannot admit one the index excludes: ``find_matching`` filters the index on
        ``is_active`` first, so a row active in SQLite whose entry is missing or says inactive is
        not found until that entry is rewritten (review round 3, R3-6). While the ledger is open
        and readable, a challenger it holds ``retired`` is refused whatever both say, and so is
        one it holds ``pending`` (R3-5,
        ``test_find_matching_refuses_a_challenger_the_ledger_holds_undecided``) unless
        ``procedures.db`` already holds its completed promotion -- its champion inactive and
        superseded by it, the pair ``ProcedureChallenger._reconcile`` records as ``restored_promotion``
        when the challenger service is enabled and a dream reaches its step -- so that winner routes
        with no dream cycle, also with the feature disabled (review round 4, R4-2; review round 5, R5-4). With no open ledger, or one that cannot be read, SQLite alone decides, as before AD-1326.
        """
        if not self._db:
            return None
        cursor = await self._db.execute(
            """SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks, is_negative
            FROM procedure_records WHERE id = ? AND is_active = 1""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        if self._challenges is not None:
            try:
                record = await self._challenges.get(procedure_id)
            except Exception:
                # Log-and-degrade (fail open): admission falls back to SQLite alone, as before AD-1326.
                logger.warning(
                    "AD-1326: the challenger ledger could not be read while routing %s; SQLite alone admits it",
                    procedure_id,
                    exc_info=True,
                )
                record = None
            if record is not None and record.bars_routing:
                if record.status != "pending":
                    return None
                # R4-2: an older ledger beside a procedures.db that holds the completed promotion.
                if await self.routing_state(record.champion_id) != (False, procedure_id):  # R6-1: _reconcile's predicate
                    return None
>>>>>>> REPLACE
```

#### Section 4 -- `src/probos/cognitive/storage_declarations.py`

```
<<<<<<< SEARCH
            "detected, and evaluators are not authenticated."
        ),
    ),
)
=======
            "detected, and evaluators are not authenticated."
        ),
    ),
    StoreDeclaration(
        id="cognitive.procedure-challenges",
        title="Procedure challengers and their head-to-head evidence (AD-1326)",
        owner_module="probos.cognitive.procedure_challenges",
        owner_symbol="ProcedureChallengeLedger",
        canonical_path="procedures/procedures_challenges.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.cognitive.procedure_store.ProcedureStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Nothing is deleted: a retired challenger keeps its evidence (#1510). Growth is one "
            "challenge row per FIX evolution, at most dreaming.procedure_challenger_max_pending_per_champion "
            "pending per champion; at most dreaming.procedure_challenger_max_judge_calls_per_cycle / 2 "
            "comparison rows per dream cycle; and one cycle row per dream cycle that judged, deferred or "
            "decided something. Archival belongs to a later lifecycle slice; this one adds none."
        ),
        notes=(
            "Opened and closed by ProcedureStore.start/stop beside procedures.db through the store's "
            "ConnectionFactory, on its own connection, so its writes never share procedures.db's "
            "transactions. ProcedureStore holds that connection as a direct attribute, which BF-882's "
            "last-resort close reaches when the store's stop() fails in a startup rollback. A ledger that fails to open leaves ProcedureStore running and FIX evolution on "
            "its legacy handling. The two files are copied separately; the backup copies in sorted path "
            "order, so this file (named to sort after procedures.db) is copied second and, when both "
            "online backups succeed, a restored ledger is never older than procedures.db; the raw-copy "
            "fallback can copy an older image. While this ledger is open and readable, "
            "ProcedureStore.find_matching refuses any challenger it holds retired, and any it holds "
            "pending unless procedures.db already holds that challenger's completed promotion (its "
            "champion inactive and superseded by it), so no undecided challenger routes; with the ledger "
            "closed or unreadable, procedures.db alone decides (fail-open). When the challenger service "
            "is enabled (dreaming.procedure_challenger_enabled) and a dream reaches its step, a pair from "
            "different moments is reconciled: the step records a promotion procedures.db already holds "
            "(restored_promotion), deactivates any other routable pending challenger and retires orphans "
            "with their evidence (challenger_missing, champion_inactive); with the service disabled the "
            "ledger is left as restored and routing still follows the rule above. A ledger newer than "
            "procedures.db leaves the older routing in place."
        ),
    ),
)
>>>>>>> REPLACE
```

**Milestone 1 focused gate:**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1326_procedure_ranking.py tests/test_ad1326_procedure_ledger.py tests/test_procedure_store.py tests/test_ad1256_store_registry.py tests/test_ad1265_backup_coverage.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_issue1419_failed_start_rollback.py -q -n 0 -p no:randomly -k "every_component_that_can_stop_raises or before_it_cleans_up"
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
```

### Milestone 2 — judge, rewrite tier, config

#### Section 5 -- `src/probos/cognitive/procedure_judge.py` (NEW)

```python
"""AD-1326 (#1510): the head-to-head judge for a procedure challenger and its champion.

A procedure's output is what replay hands the agent: its step list (AD-534 replay
replaces the LLM call with the steps, ``cognitive_agent._format_procedure_replay``).
So a comparison shows the judge one real situation -- an episode the procedure is
for -- and both candidates as "Candidate 1" and "Candidate 2", each rendered as
replay renders it after replay's two header lines, which name the procedure: the
description, every step with its agent role, expected output and fallback, and the
postconditions (``test_render_candidate_is_the_replay_body``), then bounded by
``bounded_text`` to ``MAX_CANDIDATE_CHARS``. A body of at most 4,000 characters with no
NUL or lone surrogate reaches the judge unchanged; a longer one is cut there, so steps
past the cut are not shown (``test_render_candidate_is_the_bounded_replay_body_at_the_cut``).
Replay does not show
preconditions, so neither does the judge. Nothing names or dates a candidate: no
name, id, generation, evolution type, parents or tags
(``test_render_candidate_hides_identity``).

Each situation is judged twice, once in each order; ``rng`` picks the order asked
first. A candidate wins the situation only when it wins in both orders; a split, or
a tie in either order, is a tie. A judge that always prefers one position therefore
produces ties and nothing else (``test_position_biased_judge_yields_only_ties``;
MT-Bench's swap check, Zheng et al. 2023, arXiv:2306.05685).

The judge is AD-1327's crew-verifier judge (``VerifierJudgePolicy``): it requests the
``verifier`` tier when ``cognitive.llm_model_verifier`` is set, else ``standard`` --
the policy admits no other tier, so never the ``deep`` tier the rewrite ran on.
Every judgement records its ``JudgeProvenance``. When the configured judge is
independent of every crew tier, a situation counts only if both its judgements were
answered independently; a fallback answer is recorded and not counted. The model that
answered the rewrite (``optimizer_model``) is one more model each judgement is compared
with, so a judge answering as the optimizer is not independent of it (review round 3,
R3-1); whether independence is required is still the configured policy's decision.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from probos.cognitive.crew_verdict import JudgeProvenance, judge_to_json
from probos.cognitive.procedure_challenges import bounded_text
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.procedures import Procedure
    from probos.cognitive.verifier_independence import VerifierJudgePolicy
    from probos.types import Episode, LLMResponse

logger = logging.getLogger(__name__)

Side = Literal["champion", "challenger"]
Winner = Literal["champion", "challenger", "tie", "invalid"]
Preference = Literal["1", "2", "tie", "invalid"]

MAX_REASON_CHARS = 500
MAX_CANDIDATE_CHARS = 4000
MAX_SITUATION_CHARS = 2000
JUDGE_MAX_TOKENS = 512

JUDGE_SYSTEM_PROMPT = (
    "You compare two candidate procedures for the same kind of task. Each candidate is the "
    "step list an agent would follow. Decide which candidate would better handle the situation "
    "shown. Position, length and wording style are not evidence. Answer with one JSON object "
    'only: {"preferred": "1" or "2" or "tie", "reason": "<one or two sentences>"}.'
)


class JudgeLLM(Protocol):
    """The one LLM-client method the judge uses."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


@dataclass(frozen=True)
class Judgement:
    """One call: the side shown first, the side that won it, why, and who judged."""

    shown_first: Side
    winner: Winner
    reason: str
    judge: JudgeProvenance


@dataclass(frozen=True)
class SituationVerdict:
    """One situation judged in both orders."""

    first_shown: Side
    outcome: Winner
    counted: bool
    judgements: tuple[Judgement, Judgement]


def judgement_to_json(judgement: Judgement) -> dict[str, Any]:
    return {
        "shown_first": judgement.shown_first,
        "winner": judgement.winner,
        "reason": judgement.reason,
        "judge": judge_to_json(judgement.judge),
    }


def render_candidate(procedure: Procedure) -> str:
    """The candidate as ``cognitive_agent._format_procedure_replay`` renders it, bounded.

    Replay's first two lines (``[Procedure Replay: <name>]`` and the match-score line)
    and the blank line after them are left out: they name the procedure. A role-only
    repair therefore reaches the judge as replay would hand it to the agent. The body
    then passes ``bounded_text(..., MAX_CANDIDATE_CHARS)``: it equals replay's body when
    that has at most 4,000 characters and no NUL or lone surrogate, and is replay's body
    cut at 4,000 characters otherwise (a long description can crowd out every step).
    """
    lines: list[str] = []
    if procedure.description:
        lines.append(procedure.description)
        lines.append("")
    for step in procedure.steps:
        role = step.agent_role
        head = f"**Step {step.step_number} [{role}]:**" if role else f"**Step {step.step_number}:**"
        lines.append(f"{head} {step.action}")
        if step.expected_output:
            lines.append(f"  → Expected: {step.expected_output}")
        if step.fallback_action:
            lines.append(f"  ⚠ Fallback: {step.fallback_action}")
    if procedure.postconditions:
        lines.append("")
        lines.append("**Postconditions:**")
        for item in procedure.postconditions:
            lines.append(f"  - {item}")
    return bounded_text("\n".join(lines), MAX_CANDIDATE_CHARS)


def render_situation(episode: Episode) -> str:
    """The episode's request and recorded outcome, bounded."""
    try:
        outcomes = json.dumps(episode.outcomes, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        outcomes = "<unrenderable>"
    return bounded_text(f"Request: {episode.user_input}\nRecorded outcome: {outcomes}", MAX_SITUATION_CHARS)


def build_judge_prompt(situation: str, first: str, second: str) -> str:
    return (
        "=== READ-ONLY SITUATION (a real episode; do not modify) ===\n"
        f"{situation}\n"
        "=== END SITUATION ===\n\n"
        "=== CANDIDATE 1 ===\n"
        f"{first}\n"
        "=== END CANDIDATE 1 ===\n\n"
        "=== CANDIDATE 2 ===\n"
        f"{second}\n"
        "=== END CANDIDATE 2 ==="
    )


def parse_preference(text: object) -> tuple[Preference, str]:
    """The preferred position and the reason; anything unreadable is ``invalid``."""
    if type(text) is not str:
        return "invalid", ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return "invalid", ""
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        return "invalid", ""
    if type(payload) is not dict:
        return "invalid", ""
    preferred = payload.get("preferred")
    if type(preferred) is int and preferred in (1, 2):
        preferred = str(preferred)
    reason = bounded_text(payload.get("reason"), MAX_REASON_CHARS)
    if type(preferred) is not str or preferred not in ("1", "2", "tie"):
        return "invalid", reason
    return preferred, reason  # type: ignore[return-value]


def combine_orders(one: Winner, two: Winner) -> Winner:
    """The situation's outcome from its two judgements."""
    if "invalid" in (one, two):
        return "invalid"
    if one == two:
        return one
    return "tie"  # the orders disagree: position decided it, so nobody wins


class ProcedureJudge:
    """AD-1326: judges a challenger against its champion on one situation, in both orders."""

    def __init__(self, llm_client: JudgeLLM, policy: VerifierJudgePolicy, *, rng: random.Random) -> None:
        self._llm = llm_client
        self._policy = policy
        self._rng = rng
        self._requires_independent = policy.assess() == "independent"

    @property
    def request_tier(self) -> str:
        return self._policy.request_tier

    @property
    def requires_independent(self) -> bool:
        """Whether only independently answered judgements count (an independent judge is configured)."""
        return self._requires_independent

    async def compare(
        self, *, champion: Procedure, challenger: Procedure, episode: Episode, optimizer_model: str = "",
    ) -> SituationVerdict:
        """Judge one situation in both orders.

        ``optimizer_model`` is the model that answered the challenger's rewrite (the ledger's
        ``optimizer_model``; ``""`` when not reported). It joins the crew models each answer is
        classified against, so an answer by that model is ``same_model`` and, when an
        independent judge is required, not counted
        (``test_judgement_by_the_optimizers_model_is_not_independent``). Whether independence
        is required is decided by the configured policy alone. A label is never raised by it:
        an answer the augmented policy calls ``independent`` keeps the configured policy's label
        when that is weaker, as with an empty crew basis (review round 4, R4-3,
        ``test_optimizer_model_never_raises_a_label``).
        """
        extra = (optimizer_model,) if type(optimizer_model) is str and optimizer_model else ()
        policy = replace(self._policy, crew_models=(*self._policy.crew_models, *extra))
        situation = render_situation(episode)
        rendered: dict[str, str] = {
            "champion": render_candidate(champion),
            "challenger": render_candidate(challenger),
        }
        first: Side = "champion" if self._rng.random() < 0.5 else "challenger"
        second: Side = "challenger" if first == "champion" else "champion"
        first_verdict = await self._ask(policy, situation, rendered, first, second)
        second_verdict = await self._ask(policy, situation, rendered, second, first)
        outcome = combine_orders(first_verdict.winner, second_verdict.winner)
        counted = outcome != "invalid" and (
            not self._requires_independent
            or all(j.judge.independence == "independent" for j in (first_verdict, second_verdict))
        )
        return SituationVerdict(first, outcome, counted, (first_verdict, second_verdict))

    async def _ask(
        self,
        policy: VerifierJudgePolicy,
        situation: str,
        rendered: dict[str, str],
        shown_first: Side,
        shown_second: Side,
    ) -> Judgement:
        request = LLMRequest(
            prompt=build_judge_prompt(situation, rendered[shown_first], rendered[shown_second]),
            system_prompt=JUDGE_SYSTEM_PROMPT,
            tier=policy.request_tier,
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
        try:
            response = await self._llm.complete(request)
        except Exception as exc:
            # Log-and-degrade: an unanswered judgement is recorded invalid; the situation stays open.
            logger.warning(
                "AD-1326: a procedure comparison call failed (%s); it is recorded invalid and the "
                "situation is judged again next dream cycle",
                type(exc).__name__,
            )
            return Judgement(
                shown_first, "invalid", "llm_call_failed",
                policy.provenance(answered_tier=None, answered_model=None),
            )
        judge = policy.provenance(answered_tier=response.answered_tier, answered_model=response.answered_model)
        baseline = self._policy.provenance(answered_tier=response.answered_tier, answered_model=response.answered_model)
        if judge.independence == "independent" and baseline.independence != "independent":
            judge = baseline  # R4-3: adding the optimizer's model never raises a label
        if response.error:
            return Judgement(shown_first, "invalid", bounded_text(f"llm_error: {response.error}", MAX_REASON_CHARS), judge)
        preferred, reason = parse_preference(response.content)
        if preferred == "invalid":
            return Judgement(shown_first, "invalid", reason, judge)
        if preferred == "tie":
            return Judgement(shown_first, "tie", reason, judge)
        return Judgement(shown_first, shown_first if preferred == "1" else shown_second, reason, judge)
```

#### Section 6 -- `src/probos/cognitive/procedures.py`

6a. `src/probos/cognitive/procedures.py`: import the judge-model bound.

```
<<<<<<< SEARCH
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
=======
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.crew_verdict import is_persistable_judge_model

logger = logging.getLogger(__name__)
>>>>>>> REPLACE
```

6b. `src/probos/cognitive/procedures.py`: optimizer provenance on `EvolutionResult`, the rewrite tier constants and the helper.

```
<<<<<<< SEARCH
@dataclass
class EvolutionResult:
    """Result of a FIX or DERIVED evolution (AD-532b)."""
    procedure: Procedure
    content_diff: str
    change_summary: str
=======
@dataclass
class EvolutionResult:
    """Result of a FIX or DERIVED evolution (AD-532b)."""
    procedure: Procedure
    content_diff: str
    change_summary: str
    # AD-1326: the tier and model that answered the rewrite (LLMResponse.answered_tier /
    # answered_model); "" when the response did not say or named unpersistable text.
    optimizer_tier: str = ""
    optimizer_model: str = ""


# AD-1326 (#1510): procedure REWRITING (FIX and DERIVED evolution) is the optimizer and runs
# on the strongest tier. The floor keeps a deep outage or cost-ceiling exclusion from landing
# on the fast tier: AD-1324's min_tier only removes lower tiers, so the chain is deep, then
# standard. Extraction and the evolution gate stay on standard.
PROCEDURE_REWRITE_TIER = "deep"
PROCEDURE_REWRITE_MIN_TIER = "standard"


def _optimizer_provenance(response: Any) -> tuple[str, str]:
    """AD-1326: the tier and model that answered a rewrite, each persistable text or "".

    ``getattr`` because evolution callers pass any object with ``content`` (the
    procedure tests use bare mocks); only an exact ``str`` the judge-model bound
    accepts (no NUL, at most 256 characters, strict UTF-8) is kept.
    """
    tier = getattr(response, "answered_tier", None)
    model = getattr(response, "answered_model", None)
    return (
        tier if type(tier) is str and is_persistable_judge_model(tier) else "",
        model if type(model) is str and is_persistable_judge_model(model) else "",
    )
>>>>>>> REPLACE
```

6c. `src/probos/cognitive/procedures.py`: FIX rewrite tier.

```
<<<<<<< SEARCH
            system_prompt=_FIX_SYSTEM_PROMPT,
            tier="standard",
=======
            system_prompt=_FIX_SYSTEM_PROMPT,
            tier=PROCEDURE_REWRITE_TIER,
            min_tier=PROCEDURE_REWRITE_MIN_TIER,
>>>>>>> REPLACE
```

6d. `src/probos/cognitive/procedures.py`: DERIVED rewrite tier.

```
<<<<<<< SEARCH
            system_prompt=_DERIVED_SYSTEM_PROMPT,
            tier="standard",
=======
            system_prompt=_DERIVED_SYSTEM_PROMPT,
            tier=PROCEDURE_REWRITE_TIER,
            min_tier=PROCEDURE_REWRITE_MIN_TIER,
>>>>>>> REPLACE
```

6e. `src/probos/cognitive/procedures.py`: fallback FIX rewrite tier.

```
<<<<<<< SEARCH
            system_prompt=_FALLBACK_FIX_SYSTEM_PROMPT,
            tier="standard",
=======
            system_prompt=_FALLBACK_FIX_SYSTEM_PROMPT,
            tier=PROCEDURE_REWRITE_TIER,
            min_tier=PROCEDURE_REWRITE_MIN_TIER,
>>>>>>> REPLACE
```

6f. `src/probos/cognitive/procedures.py`: FIX result carries the optimizer provenance.

```
<<<<<<< SEARCH
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("FIX evolution failed (non-critical): %s", e)
=======
        optimizer_tier, optimizer_model = _optimizer_provenance(response)
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
            optimizer_tier=optimizer_tier,
            optimizer_model=optimizer_model,
        )

    except Exception as e:
        logger.debug("FIX evolution failed (non-critical): %s", e)
>>>>>>> REPLACE
```

6g. `src/probos/cognitive/procedures.py`: DERIVED result.

```
<<<<<<< SEARCH
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("DERIVED evolution failed (non-critical): %s", e)
=======
        optimizer_tier, optimizer_model = _optimizer_provenance(response)
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
            optimizer_tier=optimizer_tier,
            optimizer_model=optimizer_model,
        )

    except Exception as e:
        logger.debug("DERIVED evolution failed (non-critical): %s", e)
>>>>>>> REPLACE
```

6h. `src/probos/cognitive/procedures.py`: fallback FIX result.

```
<<<<<<< SEARCH
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
        )

    except Exception as e:
        logger.debug("Fallback FIX evolution failed (non-critical): %s", e)
=======
        optimizer_tier, optimizer_model = _optimizer_provenance(response)
        return EvolutionResult(
            procedure=procedure,
            content_diff=content_diff,
            change_summary=change_summary,
            optimizer_tier=optimizer_tier,
            optimizer_model=optimizer_model,
        )

    except Exception as e:
        logger.debug("Fallback FIX evolution failed (non-critical): %s", e)
>>>>>>> REPLACE
```

6i. `src/probos/cognitive/procedures.py`: the FIX docstring states what the caller does in each mode (review round 1, doc correction; it replaces the earlier note that this line could stay).

```
<<<<<<< SEARCH
    """Evolve a FIX replacement for a degraded procedure.

    The parent is deactivated by the caller after successful evolution.
=======
    """Evolve a FIX replacement for a degraded procedure.

    The caller decides what replaces what. With procedure challengers on (AD-1326,
    the default) the result is saved inactive and the parent keeps routing until the
    result wins head-to-head; with them off the caller deactivates the parent.
>>>>>>> REPLACE
```

#### Section 7 -- `src/probos/config_models/cognition.py`

7a. `src/probos/config_models/cognition.py`: import, and the recall limit the producers and the validator share (review round 1, F6; D9).

```
<<<<<<< SEARCH
from pydantic import BaseModel, Field
=======
from pydantic import BaseModel, Field, model_validator

# AD-1326: the most episodes one procedure evolution recalls (dreaming.py Step 7b, the
# proactive scan and Step 7d each keep this many). The challenger controls are bounded by
# it and validated against it, so an accepted configuration can always produce a challenge.
PROCEDURE_EVOLUTION_EPISODE_LIMIT = 10
>>>>>>> REPLACE
```

7b. `src/probos/config_models/cognition.py`: the eight fields and the parse-time check.

```
<<<<<<< SEARCH
    relationship_inference_min_confidence: float = 0.6


class DreamWMConfig(BaseModel):
=======
    relationship_inference_min_confidence: float = 0.6
    # AD-1326: a FIX evolution is a challenger that replaces its champion only after winning
    # head-to-head judgements (dream Step 7d-2). False keeps the legacy FIX handling: Step 7b,
    # the proactive scan and an execution-failure fallback FIX deactivate the parent on save;
    # a near-miss fallback FIX is saved active beside it. Rewrites run on deep either way.
    procedure_challenger_enabled: bool = Field(
        default=True,
        description=(
            "AD-1326: save a FIX procedure evolution as an inactive challenger that replaces its "
            "champion only after winning head-to-head judgements. False keeps the legacy FIX "
            "handling: Step 7b, the proactive scan and an execution-failure fallback FIX deactivate "
            "the parent on save; a near-miss fallback FIX is saved active beside it. Procedure "
            "rewrites use the deep tier with a standard floor either way."
        ),
    )
    procedure_challenger_used_contexts: int = Field(
        default=2, ge=0, le=PROCEDURE_EVOLUTION_EPISODE_LIMIT,
        description="AD-1326: episodes the rewrite saw that the challenger is also judged on.",
    )
    procedure_challenger_held_out_episodes: int = Field(
        default=2, ge=0, le=PROCEDURE_EVOLUTION_EPISODE_LIMIT // 2,
        description=(
            "AD-1326: recalled episodes kept out of the rewrite prompt and used only to judge it "
            "(never more than half of the at most 10 recalled)."
        ),
    )
    procedure_challenger_min_decisions: int = Field(
        default=3, ge=1, le=PROCEDURE_EVOLUTION_EPISODE_LIMIT,
        description=(
            "AD-1326: counted judgements a challenger needs before it can be promoted; at most the "
            "situations one challenge can have from at most 10 recalled episodes (checked at parse time)."
        ),
    )
    procedure_challenger_promotion_margin: float = Field(
        default=0.1, ge=0.0, lt=0.5,
        description="AD-1326: a challenger is promoted only with a win share strictly above 0.5 plus this.",
    )
    procedure_challenger_max_judge_calls_per_cycle: int = Field(
        default=16, ge=0, le=200,
        description=(
            "AD-1326: judge LLM complete() calls per dream cycle (two per situation); the client's "
            "fallback chain can make more than one provider attempt per call. Work beyond it is "
            "deferred, never promoted; 0 defers everything."
        ),
    )
    procedure_challenger_max_pending_cycles: int = Field(
        default=5, ge=1, le=100,
        description="AD-1326: dream cycles a challenger may stay undecided before it is retired.",
    )
    procedure_challenger_max_pending_per_champion: int = Field(
        default=2, ge=1, le=5,
        description="AD-1326: pending challengers per champion; at the limit no new rewrite is attempted.",
    )

    @model_validator(mode="after")
    def _procedure_challenger_can_decide(self) -> DreamingConfig:
        # Exactly what ProcedureChallenger.prepare assembles from a full recall of
        # PROCEDURE_EVOLUTION_EPISODE_LIMIT episodes: held-out ones take odd positions, at most half.
        limit = PROCEDURE_EVOLUTION_EPISODE_LIMIT
        held_out = min(self.procedure_challenger_held_out_episodes, limit // 2)
        achievable = min(self.procedure_challenger_used_contexts, limit - held_out) + held_out
        if self.procedure_challenger_min_decisions > achievable:
            raise ValueError(
                "dreaming.procedure_challenger_min_decisions exceeds the comparison situations one "
                f"challenge can have ({achievable} from at most {limit} recalled episodes), so no "
                "challenger could ever be promoted"
            )
        return self


class DreamWMConfig(BaseModel):
>>>>>>> REPLACE
```

#### Section 8 -- config pins and regenerated artifacts

8a. `tests/test_ad1270e2b_cognition_models.py`: post-extraction addition to the pinned dump.

```
<<<<<<< SEARCH
                              'relationship_inference_min_confidence': 0.6},
=======
                              'relationship_inference_min_confidence': 0.6,
                              # AD-1326 post-extraction addition: procedure challenger controls.
                              'procedure_challenger_enabled': True,
                              'procedure_challenger_used_contexts': 2,
                              'procedure_challenger_held_out_episodes': 2,
                              'procedure_challenger_min_decisions': 3,
                              'procedure_challenger_promotion_margin': 0.1,
                              'procedure_challenger_max_judge_calls_per_cycle': 16,
                              'procedure_challenger_max_pending_cycles': 5,
                              'procedure_challenger_max_pending_per_champion': 2},
>>>>>>> REPLACE
```

8b. `tests/test_ad1270e1_config_facade.py`: field-definition count.

```
<<<<<<< SEARCH
    # AD-1327 adds the five cognitive.*_verifier fields of the crew verifier tier (1839 -> 1844).
    assert counts["field_definitions"] == 1844  # AD-1206 intentionally adds github_repository.
=======
    # AD-1327 adds the five cognitive.*_verifier fields of the crew verifier tier (1839 -> 1844).
    # AD-1326 adds the eight dreaming.procedure_challenger_* fields (1844 -> 1852).
    assert counts["field_definitions"] == 1852  # AD-1206 intentionally adds github_repository.
>>>>>>> REPLACE
```

8c. `tests/test_ad1152_agentic_correlation.py`: pop the new fields so the historical digest stays pinned.

```
<<<<<<< SEARCH
    assert config["protected_execution"].pop("effect_max_attempts") == 3
    runtime = _local_runtime()
=======
    assert config["protected_execution"].pop("effect_max_attempts") == 3
    # AD-1326's procedure-challenger controls were added after this capture too. The flag is ON
    # by default (FIX evolution as a challenger); this agentic-loop observation never dreams.
    assert config["dreaming"].pop("procedure_challenger_enabled") is True
    assert config["dreaming"].pop("procedure_challenger_used_contexts") == 2
    assert config["dreaming"].pop("procedure_challenger_held_out_episodes") == 2
    assert config["dreaming"].pop("procedure_challenger_min_decisions") == 3
    assert config["dreaming"].pop("procedure_challenger_promotion_margin") == 0.1
    assert config["dreaming"].pop("procedure_challenger_max_judge_calls_per_cycle") == 16
    assert config["dreaming"].pop("procedure_challenger_max_pending_cycles") == 5
    assert config["dreaming"].pop("procedure_challenger_max_pending_per_champion") == 2
    runtime = _local_runtime()
>>>>>>> REPLACE
```

8d. `docs/development/config-facade-baseline.yaml` and `docs/development/config-reference.md`: regenerate, do not hand-edit.
```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
```
Expected baseline diff: `surface_counts.field_definitions` 1844 -> 1852; eight field rows appended to `models.DreamingConfig.fields`; `DreamingConfig.schema_sha256`; `SystemConfig.schema_sha256` if its digest embeds the nested schema; `canonical_dump_leaves` count if present. **Hard stop** if any other model's row changes. Expected reference diff: eight rows in the `dreaming` table. Review round 1 changes three bounds (`used_contexts` le 10, `held_out_episodes` le 5, `min_decisions` le 10) and four descriptions (`enabled`, `held_out_episodes`, `min_decisions`, `max_judge_calls_per_cycle`) of those eight fields: regenerate both artifacts again; the same hard stop applies. The defaults do not change, so 8a, 8b and 8c do not move, and `PROCEDURE_EVOLUTION_EPISODE_LIMIT` is not re-exported through `probos.config`, so `test_ad1270e1_config_facade.py`'s `public_names == 305` does not move.

**Milestone 2 focused gate:**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1326_procedure_judge.py tests/test_ad1326_rewrite_tier.py tests/test_ad1326_config.py tests/test_procedure_evolution.py tests/test_procedure_extraction.py tests/test_fallback_learning.py tests/test_ad579c_validity_dream.py tests/test_ad1270e2b_cognition_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_config_reference_current.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
```

### Milestone 3 — event, service, dream wiring

#### Section 9 -- `src/probos/events.py` (Section 0: Event Types)

One new member, inserted directly after `PROCEDURE_FALLBACK_LEARNING` (`events.py:191`):

```
<<<<<<< SEARCH
    PROCEDURE_FALLBACK_LEARNING = "procedure_fallback_learning"  # AD-534b: fallback evidence
=======
    PROCEDURE_FALLBACK_LEARNING = "procedure_fallback_learning"  # AD-534b: fallback evidence
    PROCEDURE_CHALLENGE_DECIDED = "procedure_challenge_decided"  # AD-1326: a challenger promoted or retired
>>>>>>> REPLACE
```

#### Section 10 -- `src/probos/event_persistence.py`

The import of `probos.events` fails while a member is neither declared nor grandfathered (`event_persistence.py:3-7`), so this lands in the same commit as Section 9.

```
<<<<<<< SEARCH
    "DESIGN_GENERATED": _DURABLE,
    "SHIP_NAMED": _DURABLE,
=======
    "DESIGN_GENERATED": _DURABLE,
    "SHIP_NAMED": _DURABLE,
    "PROCEDURE_CHALLENGE_DECIDED": _DURABLE,  # AD-1326: the ship changing its own routing
>>>>>>> REPLACE
```

#### Section 11 -- event pins (397 members, 41 declared, 37 DURABLE, 29 routed)

11a. `tests/test_ad1195_durable_event_seam.py`:

```
<<<<<<< SEARCH
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 28
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (28, 368)
    assert {m.value for m in _ROUTED} == ROUTED_VALUES
    assert sum(1 for p in DECLARATIONS.values() if p is Persistence.DURABLE) == 36
=======
    assert len(EventType) == 397
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 368)
    assert {m.value for m in _ROUTED} == ROUTED_VALUES
    assert sum(1 for p in DECLARATIONS.values() if p is Persistence.DURABLE) == 37
>>>>>>> REPLACE
```

11b. `tests/test_ad1195_event_persistence_contract.py` (four blocks):

```
<<<<<<< SEARCH
# DECL-4: the 28 routed values of the contract's DURABLE table (section 3.8).
=======
# DECL-4: the 29 routed values of the contract's DURABLE table (section 3.8), plus AD-1326's.
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    "config_changed",
})
=======
    "config_changed",
    "procedure_challenge_decided",
})
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    """DECL-1: 396 members = 40 declared + 356 grandfathered, disjoint."""
    names = set(EventType.__members__)
    declared = set(ep.DECLARATIONS)
    assert not declared & ep.GRANDFATHERED
    assert declared | ep.GRANDFATHERED == names
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 40, 356)
=======
    """DECL-1: 397 members = 41 declared + 356 grandfathered, disjoint."""
    names = set(EventType.__members__)
    declared = set(ep.DECLARATIONS)
    assert not declared & ep.GRANDFATHERED
    assert declared | ep.GRANDFATHERED == names
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (397, 41, 356)
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    """DECL-4: 36 DURABLE (8 owner, 28 routed), 4 OPERATIONAL, 0 DIAGNOSTIC."""
    counts = Counter(ep.DECLARATIONS.values())
    assert counts == {Persistence.DURABLE: 36, Persistence.OPERATIONAL: 4}
    assert counts[Persistence.DIAGNOSTIC] == 0
    assert len(ep.OWNER_RECORDS) == 8
    assert ROUTED_VALUES == _CONTRACT_ROUTED_VALUES
    assert len(ROUTED_VALUES) == 28
=======
    """DECL-4: 37 DURABLE (8 owner, 29 routed), 4 OPERATIONAL, 0 DIAGNOSTIC."""
    counts = Counter(ep.DECLARATIONS.values())
    assert counts == {Persistence.DURABLE: 37, Persistence.OPERATIONAL: 4}
    assert counts[Persistence.DIAGNOSTIC] == 0
    assert len(ep.OWNER_RECORDS) == 8
    assert ROUTED_VALUES == _CONTRACT_ROUTED_VALUES
    assert len(ROUTED_VALUES) == 29
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    assert broken == []
    assert len(EventType) == 396
=======
    assert broken == []
    assert len(EventType) == 397
>>>>>>> REPLACE
```

11c. `tests/test_ad1195_durable_producers.py` (three blocks):

```
<<<<<<< SEARCH
    "CONFIG_CHANGED": ("runtime_config_service.py",),
}
=======
    "CONFIG_CHANGED": ("runtime_config_service.py",),
    "PROCEDURE_CHALLENGE_DECIDED": ("cognitive/procedure_challenger.py",),
}
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    assert len(_ROUTED) == 28
=======
    assert len(_ROUTED) == 29
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    assert len(durable) == 36
=======
    assert len(durable) == 37
>>>>>>> REPLACE
```

11d. `tests/test_ad1195_eventlog_pair_freeze.py`:

```
<<<<<<< SEARCH
    assert len(OWNER_RECORDS) == 8 and len(ROUTED_VALUES) == 28
=======
    assert len(OWNER_RECORDS) == 8 and len(ROUTED_VALUES) == 29
>>>>>>> REPLACE
```

#### Section 12 -- `src/probos/cognitive/procedure_challenger.py` (NEW)

```python
"""AD-1326 (#1510): a FIX evolution is a challenger; it replaces its champion only after winning.

MASS (arXiv:2610.12176; docs/research/mass-self-supervision-absorption.md) found
that text-space self-improvement regresses sharply without a guard, and that the
guard which worked is a champion that only a pairwise win replaces. Here:

1. ``prepare`` runs before a FIX rewrite. It splits the recalled episodes into the
   ones the rewrite sees and held-out ones it does not (``split_held_out``), and
   returns ``None`` -- no rewrite -- when the champion already has its maximum of
   pending challengers or there could never be enough situations to decide.
2. ``submit`` runs after the rewrite. It saves the FIX procedure inactive, so
   routing keeps the champion, linked to the champion through
   ``parent_procedure_ids``, and records it ``pending``.
3. ``run_cycle`` is dream Step 7d-2. It judges pending challengers within the
   cycle's judge-call budget, ranks the complete ones with Bradley-Terry, and
   promotes the top one only if it also beats the champion; the others are retired
   with their evidence kept. A challenger still pending after
   ``procedure_challenger_max_pending_cycles`` cycles is retired, not promoted.

``ProcedureChallengeLedger`` is the durable authority for every transition. In
``src/probos`` this module alone calls the ledger's writers and emits
``PROCEDURE_CHALLENGE_DECIDED`` (``test_ledger_writes_and_the_event_have_one_owner``).
Promotion is ``promoting`` -> challenger saved active and its routing-index entry
rewritten from SQLite -> champion deactivated with ``superseded_by`` and its entry
rewritten -> ``promoted``; the champion is not touched until the challenger's entry has
taken, so the lineage keeps routing through an index outage. Each cycle first finishes a
promotion an earlier cycle left at ``promoting``
(``test_interrupted_promotion_is_finished_next_cycle``,
``test_promotion_is_sealed_only_when_the_routing_index_agrees``). A retirement ``_retire``
decides is sealed only once the challenger's entry is rewritten from SQLite as well
(``test_retirement_is_sealed_only_when_the_routing_index_agrees``). A challenger over the
pending cap is recorded ``retired`` (``pending_limit``) by ``add_challenger`` without that
step: ``submit`` saved it inactive just before, so it was never routable, and admission
refuses a ``retired`` row anyway (review round 3, R3-7). ``PROCEDURE_CHALLENGE_DECIDED`` is
emitted at most once per decision, after the terminal status commits; a process that stops
between that commit and the emit leaves the decision in the ledger with no event (R3-8;
the ledger, not the event, is the authority). Before judging, each
pending challenger's routing is reconciled with its ledger row, because the ledger and
``procedures.db`` are separate files a restore can pair from different moments
(``_reconcile``). The pending cap is enforced where the challenger is recorded
(``ProcedureChallengeLedger.add_challenger``), not only checked in ``prepare``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from probos.cognitive.procedure_challenges import (
    ChallengeRecord,
    ComparisonRecord,
    ProcedureChallengeLedger,
)
from probos.cognitive.procedure_judge import ProcedureJudge, judgement_to_json
from probos.cognitive.procedure_ranking import PairOutcome, beats_champion, bradley_terry
from probos.cognitive.verifier_independence import VerifierJudgePolicy
from probos.events import EventType
from probos.types import episode_ran_in_plan_mode

if TYPE_CHECKING:
    from probos.cognitive.procedures import EvolutionResult, Procedure
    from probos.config import DreamingConfig, SystemConfig

logger = logging.getLogger(__name__)

JUDGE_CALLS_PER_CONTEXT = 2
_PAIR_RESULT = {"challenger": "first", "champion": "second", "tie": "tie"}


class ChallengeProcedureStore(Protocol):
    """The ``ProcedureStore`` methods the challenger service uses."""

    async def get(self, procedure_id: str) -> Any: ...

    async def save(self, procedure: Any, *, content_diff: str = "", change_summary: str = "") -> str: ...

    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None: ...

    async def get_evolution_metadata(self, procedure_id: str) -> dict[str, str]: ...

    async def sync_routing_index(self, procedure_id: str) -> bool: ...

    async def routing_state(self, procedure_id: str) -> tuple[bool, str] | None: ...


class ChallengeEpisodes(Protocol):
    """The ``EpisodicMemory`` method the challenger service uses."""

    async def get_by_ids(self, episode_ids: list[str], *, for_evidence: bool = False) -> list[Any]: ...


@dataclass(frozen=True)
class ChallengePlan:
    """What ``prepare`` decided before a FIX rewrite runs."""

    champion_id: str
    evolution_episodes: tuple[Any, ...]
    held_out_episodes: tuple[Any, ...]
    context_episode_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChallengeCycleReport:
    """One Step 7d-2 run. ``superseded_episodes`` are a promoted challenger's source episodes."""

    judge_calls: int = 0
    comparisons: int = 0
    deferred: int = 0
    promoted: int = 0
    retired: int = 0
    superseded_episodes: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Tally:
    """A challenger's counted judgements against its champion."""

    wins: int = 0
    losses: int = 0
    ties: int = 0
    held_out_wins: int = 0
    held_out_decisions: int = 0
    independence: tuple[str, ...] = ()

    @property
    def decisions(self) -> int:
        return self.wins + self.losses + self.ties


@dataclass
class _CycleCounts:
    calls: int = 0
    comparisons: int = 0
    deferred: int = 0
    promoted: int = 0
    retired: int = 0

    def any(self) -> bool:
        return any((self.calls, self.comparisons, self.deferred, self.promoted, self.retired))


def split_held_out(
    episodes: Sequence[Any], held_out: int, *, pinned: Collection[str] = frozenset(),
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """AD-1326: ``(evolution, held_out)`` episodes.

    Held-out episodes come from odd positions (1, 3, ...) so both halves span the
    recency order; at most ``held_out``, and never more than half of ``episodes``, are
    held out. An episode whose ``id`` is in ``pinned`` is never held out and leads the
    evolution half in recalled order, but it still counts toward the half: pinning does
    not lower the ceiling (review round 2, R2-4). When pinned episodes take odd positions,
    the unpinned even positions fill in from the oldest down, position 0 (the newest) last
    (``test_split_held_out_fills_around_pinned_episodes``). Held-out falls short of the
    ceiling only when fewer unpinned episodes remain than it asks for.
    """
    n = len(episodes)
    count = max(0, min(held_out, n // 2))
    order = [*range(1, n, 2), *reversed(range(0, n, 2))]
    eligible = [index for index in order if not pinned or episodes[index].id not in pinned]
    held_positions = set(eligible[:count])
    lead = tuple(ep for ep in episodes if pinned and ep.id in pinned)
    evolution = lead + tuple(
        ep for index, ep in enumerate(episodes)
        if index not in held_positions and not (pinned and ep.id in pinned)
    )
    kept = tuple(ep for index, ep in enumerate(episodes) if index in held_positions)
    return evolution, kept


def _counted(comparisons: Sequence[ComparisonRecord]) -> list[ComparisonRecord]:
    """The first counted comparison per situation, in recorded order."""
    seen: set[str] = set()
    kept: list[ComparisonRecord] = []
    for comparison in comparisons:
        if comparison.counted and comparison.episode_id not in seen:
            seen.add(comparison.episode_id)
            kept.append(comparison)
    return kept


def tally(comparisons: Sequence[ComparisonRecord]) -> Tally:
    wins = losses = ties = held_out_wins = held_out_decisions = 0
    independence: set[str] = set()
    for comparison in _counted(comparisons):
        if comparison.outcome == "challenger":
            wins += 1
        elif comparison.outcome == "champion":
            losses += 1
        else:
            ties += 1
        if comparison.split == "held_out":
            held_out_decisions += 1
            held_out_wins += int(comparison.outcome == "challenger")
        for judgement in comparison.judgements:
            judge = judgement.get("judge") if type(judgement) is dict else None
            if type(judge) is dict and type(judge.get("independence")) is str:
                independence.add(judge["independence"])
    return Tally(wins, losses, ties, held_out_wins, held_out_decisions, tuple(sorted(independence)))


def _pair_outcomes(record: ChallengeRecord, comparisons: Sequence[ComparisonRecord]) -> list[PairOutcome]:
    return [
        PairOutcome(record.challenger_id, record.champion_id, _PAIR_RESULT[comparison.outcome])  # type: ignore[arg-type]
        for comparison in _counted(comparisons)
    ]


def _threshold(config: DreamingConfig) -> float:
    """The win share a challenger must exceed: ``0.5 + procedure_challenger_promotion_margin``."""
    return 0.5 + config.procedure_challenger_promotion_margin


def _decision_text(reason: str, result: Tally, threshold: float) -> str:
    return (
        f"{reason}: wins={result.wins} losses={result.losses} ties={result.ties} "
        f"decisions={result.decisions} held_out={result.held_out_wins}/{result.held_out_decisions} "
        f"promote_above={threshold:.2f}"
    )


class ProcedureChallenger:
    """AD-1326: the single writer of challenger transitions and the single emitter of their event."""

    def __init__(
        self,
        *,
        store: ChallengeProcedureStore,
        ledger: ProcedureChallengeLedger,
        episodes: ChallengeEpisodes,
        judge: ProcedureJudge,
        config: DreamingConfig,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._episodes = episodes
        self._judge = judge
        self._config = config
        self._emit_event_fn = emit_event_fn

    async def prepare(
        self, champion: Procedure, episodes: Sequence[Any], *, source_correlation_id: str = "",
    ) -> ChallengePlan | None:
        """Split ``episodes`` for a FIX rewrite of ``champion``; ``None`` means do not rewrite.

        ``source_correlation_id`` names the turn whose LLM response the rewrite prompt quotes
        (Step 7d's fallback event). That turn's episodes are rewrite evidence already, so they
        go first in the rewrite set and are never held out
        (``test_prepare_never_holds_out_the_source_turn``). The held-out ceiling is taken from
        the whole usable recall, so pinning does not cost situations the validator counted
        (``test_source_pinned_recall_reaches_the_same_situations``).
        """
        cfg = self._config
        usable = [ep for ep in episodes if type(ep.id) is str and ep.id]
        source = source_correlation_id if type(source_correlation_id) is str else ""
        pinned_ids = {ep.id for ep in usable if source and ep.correlation_id == source}
        evolution, held_out = split_held_out(usable, cfg.procedure_challenger_held_out_episodes, pinned=pinned_ids)
        contexts = tuple(ep.id for ep in evolution[: cfg.procedure_challenger_used_contexts]) + tuple(
            ep.id for ep in held_out
        )
        if len(contexts) < cfg.procedure_challenger_min_decisions:
            logger.debug(
                "AD-1326: procedure %s has %d comparison situations, fewer than the %d a decision "
                "needs; no rewrite this time",
                champion.id, len(contexts), cfg.procedure_challenger_min_decisions,
            )
            return None
        if await self._ledger.pending_count(champion.id) >= cfg.procedure_challenger_max_pending_per_champion:
            logger.debug(
                "AD-1326: procedure %s already has %d pending challengers; no rewrite this time",
                champion.id, cfg.procedure_challenger_max_pending_per_champion,
            )
            return None
        return ChallengePlan(champion.id, evolution, held_out, contexts)

    async def submit(self, plan: ChallengePlan, result: EvolutionResult) -> Procedure | None:
        """Save ``result`` inactive and record it ``pending`` (``retired`` over the pending cap); ``None`` leaves the champion as it was."""
        procedure = result.procedure
        if procedure.evolution_type != "FIX" or list(procedure.parent_procedure_ids) != [plan.champion_id]:
            logger.warning(
                "AD-1326: refusing a challenger that is not a FIX of champion %s; nothing was saved",
                plan.champion_id,
            )
            return None
        challenger = replace(procedure, is_active=False)
        try:
            await self._store.save(
                challenger, content_diff=result.content_diff, change_summary=result.change_summary,
            )
            record = await self._ledger.add_challenger(
                challenger_id=challenger.id,
                champion_id=plan.champion_id,
                used_episode_ids=[ep.id for ep in plan.evolution_episodes],
                held_out_episode_ids=[ep.id for ep in plan.held_out_episodes],
                context_episode_ids=list(plan.context_episode_ids),
                optimizer_tier=result.optimizer_tier,
                optimizer_model=result.optimizer_model,
                max_pending=self._config.procedure_challenger_max_pending_per_champion,
            )
        except Exception:
            logger.warning(
                "AD-1326: challenger %s of champion %s could not be recorded; the champion keeps routing",
                challenger.id, plan.champion_id, exc_info=True,
            )
            return None
        if record.status != "pending":
            # Another rewrite of this champion was recorded while this one ran (prepare's check
            # is not a reservation); the ledger kept the cap and recorded this one retired.
            logger.warning(
                "AD-1326: champion %s reached its %d pending challengers while challenger %s was "
                "written; it is recorded retired (pending_limit), kept inactive, and the champion "
                "keeps routing",
                plan.champion_id, self._config.procedure_challenger_max_pending_per_champion, challenger.id,
            )
            self._emit(record, "retired", "pending_limit", Tally(), None)
            return None
        logger.info(
            "AD-1326: procedure challenger %s saved inactive against champion %s (%d situations, "
            "%d held out; rewrite answered by %s)",
            challenger.id, plan.champion_id, len(plan.context_episode_ids), len(plan.held_out_episodes),
            result.optimizer_tier or "an unreported tier",
        )
        return challenger

    async def run_cycle(self) -> ChallengeCycleReport:
        """Dream Step 7d-2: finish interrupted promotions, judge within budget, decide, age the rest."""
        counts = _CycleCounts()
        superseded: list[Any] = []
        for record in await self._ledger.list_by_status("promoting"):
            superseded.extend(await self._complete_promotion(record, counts))
        groups: dict[str, list[ChallengeRecord]] = {}
        for record in await self._ledger.list_by_status("pending"):
            groups.setdefault(record.champion_id, []).append(record)
        for champion_id, records in groups.items():
            superseded.extend(await self._contest(champion_id, records, counts))
        await self._age(counts)
        if counts.any():
            await self._ledger.record_cycle(
                judge_calls=counts.calls, comparisons=counts.comparisons, deferred=counts.deferred,
                promoted=counts.promoted, retired=counts.retired,
            )
            logger.info(
                "AD-1326: procedure challengers -- %d judge calls, %d situations judged, %d deferred by "
                "the budget, %d promoted, %d retired",
                counts.calls, counts.comparisons, counts.deferred, counts.promoted, counts.retired,
            )
        return ChallengeCycleReport(
            judge_calls=counts.calls, comparisons=counts.comparisons, deferred=counts.deferred,
            promoted=counts.promoted, retired=counts.retired, superseded_episodes=tuple(superseded),
        )

    async def _contest(self, champion_id: str, records: list[ChallengeRecord], counts: _CycleCounts) -> list[Any]:
        champion = await self._store.get(champion_id)
        # R6-1: activity and supersession come from the columns admission reads, not get's snapshot.
        champion_state = await self._store.routing_state(champion_id)
        superseded: list[Any] = []
        open_records: list[ChallengeRecord] = []
        for record in records:
            settled = await self._reconcile(champion_state, record, counts)
            if settled is None:
                open_records.append(record)
            else:
                superseded.extend(settled)
        if champion is None or champion_state is None or not champion_state[0]:
            for record in open_records:
                recorded = tally(await self._ledger.comparisons(record.challenger_id))
                await self._retire(record, "champion_inactive", recorded, counts)
            return superseded
        complete: list[tuple[ChallengeRecord, list[ComparisonRecord]]] = []
        for record in open_records:
            evidence = await self._judge_record(champion, record, counts)
            if evidence is None:
                continue
            if tally(evidence).decisions < self._config.procedure_challenger_min_decisions:
                await self._retire(record, "insufficient_evidence", tally(evidence), counts)
                continue
            complete.append((record, evidence))
        if not complete:
            return superseded
        return superseded + await self._decide(champion_id, open_records, complete, counts)

    async def _reconcile(
        self, champion_state: tuple[bool, str] | None, record: ChallengeRecord, counts: _CycleCounts,
    ) -> list[Any] | None:
        """Make a pending challenger's routing agree with its ledger row; ``None`` means still pending.

        A restore can pair this ledger with a ``procedures.db`` written after a promotion. A
        challenger that is active while its champion is inactive and superseded by it is that
        completed promotion: it is recorded ``promoted`` (reason ``restored_promotion``) with
        the evidence the ledger holds. Any other active pending challenger is deactivated, so
        a pending or retired challenger never routes. A missing one is retired with its
        evidence. The entry of a challenger that stays pending is rewritten from SQLite. Both
        procedures' activity and supersession are the columns admission reads
        (``ProcedureStore.routing_state``, ``champion_state`` from ``_contest``), so this records
        exactly the pairs routing already admits (review round 6, R6-1).
        """
        state = await self._store.routing_state(record.challenger_id)
        if state is None:
            missing = tally(await self._ledger.comparisons(record.challenger_id))
            await self._retire(record, "challenger_missing", missing, counts)
            return []
        if state[0]:  # R6-1: the challenger's column
            if champion_state == (False, record.challenger_id):
                result = tally(await self._ledger.comparisons(record.challenger_id))
                reason = _decision_text("restored_promotion", result, _threshold(self._config))
                if not await self._ledger.set_status(
                    record.challenger_id, "promoting", reason=reason, expected=("pending",),
                ):
                    return []
                promoting = replace(record, status="promoting", decision_reason=reason)
                return await self._complete_promotion(promoting, counts, result=result)
            logger.warning(
                "AD-1326: pending challenger %s of %s was routable (its ledger row and procedures.db "
                "disagree, e.g. after a restore); it is deactivated until it wins",
                record.challenger_id, record.champion_id,
            )
            await self._store.deactivate(record.challenger_id)
        if not await self._store.sync_routing_index(record.challenger_id):
            logger.warning(
                "AD-1326: the routing index entry of pending challenger %s could not be rewritten; "
                "the next dream cycle tries again",
                record.challenger_id,
            )
        return None

    async def _judge_record(
        self, champion: Procedure, record: ChallengeRecord, counts: _CycleCounts,
    ) -> list[ComparisonRecord] | None:
        """Judge ``record``'s open situations; its evidence when complete, else ``None``."""
        challenger = await self._store.get(record.challenger_id)
        if challenger is None:  # removed since _reconcile; the next cycle retires it with its evidence
            return None
        counted = {c.episode_id for c in await self._ledger.comparisons(record.challenger_id) if c.counted}
        open_ids = [eid for eid in record.context_episode_ids if eid not in counted]
        available = await self._contexts(open_ids)
        if available is None:
            return None
        budget = self._config.procedure_challenger_max_judge_calls_per_cycle
        for episode_id in open_ids:
            episode = available.get(episode_id)
            if episode is None:
                continue
            if counts.calls + JUDGE_CALLS_PER_CONTEXT > budget:
                counts.deferred += 1
                continue
            verdict = await self._judge.compare(
                champion=champion, challenger=challenger, episode=episode,
                optimizer_model=record.optimizer_model,  # R3-1: the rewrite's own model is not an independent judge
            )
            counts.calls += JUDGE_CALLS_PER_CONTEXT
            counts.comparisons += 1
            await self._ledger.record_comparison(
                challenger_id=record.challenger_id,
                champion_id=record.champion_id,
                episode_id=episode_id,
                split="held_out" if episode_id in record.held_out_episode_ids else "used",
                first_shown=verdict.first_shown,
                outcome=verdict.outcome,
                counted=verdict.counted,
                judgements=[judgement_to_json(j) for j in verdict.judgements],
            )
            if verdict.counted:
                counted.add(episode_id)
        if any(eid in available and eid not in counted for eid in open_ids):
            return None
        return await self._ledger.comparisons(record.challenger_id)

    async def _decide(
        self,
        champion_id: str,
        records: list[ChallengeRecord],
        complete: list[tuple[ChallengeRecord, list[ComparisonRecord]]],
        counts: _CycleCounts,
    ) -> list[Any]:
        outcomes = [outcome for record, evidence in complete for outcome in _pair_outcomes(record, evidence)]
        strengths = bradley_terry(outcomes, reference=champion_id)
        ranked = sorted(
            complete,
            key=lambda item: (-strengths[item[0].challenger_id], item[0].created_at, item[0].challenger_id),
        )
        top, top_evidence = ranked[0]
        top_tally = tally(top_evidence)
        if beats_champion(
            wins=top_tally.wins,
            decisions=top_tally.decisions,
            min_decisions=self._config.procedure_challenger_min_decisions,
            margin=self._config.procedure_challenger_promotion_margin,
        ):
            promoted, episodes = await self._promote(top, top_tally, strengths[top.challenger_id], counts)
            if promoted:
                for record in records:
                    if record.challenger_id != top.challenger_id:
                        others = tally(await self._ledger.comparisons(record.challenger_id))
                        await self._retire(record, "champion_replaced", others, counts)
            return episodes
        for record, evidence in complete:
            await self._retire(record, "lost", tally(evidence), counts, strength=strengths[record.challenger_id])
        return []

    async def _promote(
        self, record: ChallengeRecord, result: Tally, strength: float, counts: _CycleCounts,
    ) -> tuple[bool, list[Any]]:
        reason = _decision_text("won", result, _threshold(self._config))
        if not await self._ledger.set_status(record.challenger_id, "promoting", reason=reason, expected=("pending",)):
            return False, []
        promoting = replace(record, status="promoting", decision_reason=reason)
        return True, await self._complete_promotion(promoting, counts, result=result, strength=strength)

    async def _complete_promotion(
        self,
        record: ChallengeRecord,
        counts: _CycleCounts,
        *,
        result: Tally | None = None,
        strength: float | None = None,
    ) -> list[Any]:
        """Activate and confirm the challenger, then retire and confirm the champion, then mark ``promoted``. Safe to repeat."""
        if result is None:
            result = tally(await self._ledger.comparisons(record.challenger_id))
        challenger = await self._store.get(record.challenger_id)
        if challenger is None:
            await self._retire(record, "challenger_missing", result, counts, expected=("promoting",))
            return []
        state = await self._store.routing_state(record.challenger_id)
        if state is None or not state[0]:  # R6-1: activate unless the column says active
            meta = await self._store.get_evolution_metadata(record.challenger_id)
            await self._store.save(
                replace(challenger, is_active=True),
                content_diff=meta.get("content_diff", ""),
                change_summary=meta.get("change_summary", ""),
            )
        # Routing (find_matching) finds a procedure through the semantic index, and save()/deactivate()
        # report an index failure only in the log. The challenger's entry is confirmed BEFORE the
        # champion is deactivated, so the lineage keeps routing through an index outage (review
        # round 2, R2-2); the decision is sealed once the champion's entry is rewritten as well.
        # Until then it stays ``promoting`` and the next cycle repeats this method.
        if not await self._store.sync_routing_index(challenger.id):
            logger.warning(
                "AD-1326: the promotion of %s over %s waits: the challenger's routing index entry could "
                "not be written, so the champion keeps routing; it stays promoting and the next dream "
                "cycle retries it",
                record.challenger_id, record.champion_id,
            )
            return []
        champion_state = await self._store.routing_state(record.champion_id)
        if champion_state is not None and champion_state[0]:  # R6-1: the champion's column
            await self._store.deactivate(record.champion_id, superseded_by=record.challenger_id)
        if not await self._store.sync_routing_index(record.champion_id):
            logger.warning(
                "AD-1326: the promotion of %s over %s is in SQLite but the champion's routing index entry "
                "did not take it; it stays promoting and the next dream cycle retries it",
                record.challenger_id, record.champion_id,
            )
            return []
        if not await self._ledger.set_status(
            record.challenger_id, "promoted", reason=record.decision_reason, expected=("promoting",),
        ):
            return []
        counts.promoted += 1
        self._emit(record, "promoted", record.decision_reason.split(":", 1)[0] or "won", result, strength)
        logger.info(
            "AD-1326: procedure %s replaced champion %s after winning %d of %d judgements (%d of %d held out)",
            record.challenger_id, record.champion_id, result.wins, result.decisions,
            result.held_out_wins, result.held_out_decisions,
        )
        return await self._source_episodes(record)

    async def _retire(
        self,
        record: ChallengeRecord,
        reason: str,
        result: Tally,
        counts: _CycleCounts,
        *,
        expected: tuple[str, ...] = ("pending",),
        strength: float | None = None,
    ) -> bool:
        detail = _decision_text(reason, result, _threshold(self._config))
        # A retired challenger never routes: the decision is sealed only once its index entry is
        # rewritten from SQLite (inactive, or no row); until then the row keeps its status and a
        # later cycle retries (review round 2, R2-1).
        if not await self._store.sync_routing_index(record.challenger_id):  # R2-1: sealed only when routing agrees
            logger.warning(
                "AD-1326: challenger %s of %s is not retired (%s) yet: its routing index entry could not "
                "be rewritten; the next dream cycle tries again",
                record.challenger_id, record.champion_id, reason,
            )
            return False
        if not await self._ledger.set_status(record.challenger_id, "retired", reason=detail, expected=expected):  # type: ignore[arg-type]
            return False
        counts.retired += 1
        self._emit(record, "retired", reason, result, strength)
        logger.info(
            "AD-1326: procedure challenger %s of %s retired (%s); its evidence is kept",
            record.challenger_id, record.champion_id, reason,
        )
        return True

    async def _age(self, counts: _CycleCounts) -> None:
        for record in await self._ledger.list_by_status("pending"):
            cycles = await self._ledger.increment_cycles(record.challenger_id)
            if cycles >= self._config.procedure_challenger_max_pending_cycles:
                expired = tally(await self._ledger.comparisons(record.challenger_id))
                await self._retire(record, "expired", expired, counts)

    async def _contexts(self, ids: list[str]) -> dict[str, Any] | None:
        """Episodes for ``ids`` by id, plan-mode turns dropped; ``None`` when unreadable this cycle."""
        if not ids:
            return {}
        try:
            found = await self._episodes.get_by_ids(list(ids), for_evidence=True)
        except Exception:
            logger.warning(
                "AD-1326: comparison episodes could not be read; the challengers that need them wait "
                "for the next dream cycle",
                exc_info=True,
            )
            return None
        if not found:  # nothing came back: unreadable this cycle, not missing
            return None
        return {ep.id: ep for ep in found if not episode_ran_in_plan_mode(ep)}

    async def _source_episodes(self, record: ChallengeRecord) -> list[Any]:
        try:
            return list(await self._episodes.get_by_ids([*record.used_episode_ids, *record.held_out_episode_ids]))
        except Exception:
            logger.warning(
                "AD-1326: the source episodes of promoted procedure %s could not be read; they are not "
                "expired this cycle",
                record.challenger_id, exc_info=True,
            )
            return []

    def _emit(
        self, record: ChallengeRecord, decision: str, reason: str, result: Tally, strength: float | None,
    ) -> None:
        if self._emit_event_fn is None:
            return
        payload: dict[str, Any] = {
            "challenger_id": record.challenger_id,
            "champion_id": record.champion_id,
            "decision": decision,
            "reason": reason,
            "wins": result.wins,
            "losses": result.losses,
            "ties": result.ties,
            "decisions": result.decisions,
            "held_out_wins": result.held_out_wins,
            "held_out_decisions": result.held_out_decisions,
            "strength": None if strength is None else round(strength, 6),
            "judge_independence": list(result.independence),
        }
        try:
            self._emit_event_fn(EventType.PROCEDURE_CHALLENGE_DECIDED, payload)
        except Exception:
            logger.warning(
                "AD-1326: the %s event for challenger %s could not be emitted; the ledger holds the decision",
                decision, record.challenger_id, exc_info=True,
            )


def build_procedure_challenger(
    *,
    config: SystemConfig,
    procedure_store: Any,
    episodic_memory: Any,
    llm_client: Any,
    emit_event_fn: Callable[..., Any] | None,
    rng: random.Random | None = None,
) -> ProcedureChallenger | None:
    """AD-1326: the challenger service, or ``None`` for the legacy FIX handling."""
    dreaming = config.dreaming
    if not dreaming.procedure_challenger_enabled:
        logger.info(
            "AD-1326: procedure challengers are off (dreaming.procedure_challenger_enabled=false); "
            "FIX evolution follows its legacy handling"
        )
        return None
    if procedure_store is None or llm_client is None or episodic_memory is None:
        return None
    ledger = procedure_store.challenges
    if not isinstance(ledger, ProcedureChallengeLedger):
        logger.warning(
            "AD-1326: the procedure challenger ledger is not open; FIX evolution follows its legacy "
            "handling until it is"
        )
        return None
    policy = VerifierJudgePolicy.from_cognitive(config.cognitive)
    judge = ProcedureJudge(llm_client, policy, rng=rng or random.Random())
    logger.info(
        "AD-1326: procedure challengers are judged on the %s tier (%s); only independent judgements "
        "count: %s",
        policy.request_tier, policy.assess(), judge.requires_independent,
    )
    return ProcedureChallenger(
        store=procedure_store,
        ledger=ledger,
        episodes=episodic_memory,
        judge=judge,
        config=dreaming,
        emit_event_fn=emit_event_fn,
    )
```

#### Section 13 -- `src/probos/cognitive/dreaming.py`

13a. `src/probos/cognitive/dreaming.py`: `TYPE_CHECKING` import.

```
<<<<<<< SEARCH
from collections.abc import Callable
from typing import Any

from probos.cognitive.contradiction_detector import detect_contradictions
=======
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from probos.cognitive.contradiction_detector import detect_contradictions
>>>>>>> REPLACE
```

13a-2. `src/probos/cognitive/dreaming.py`: the shared recall limit (review round 1, F6; D9). Imported from the leaf module, not re-exported through `probos.config`; `config_models` is not a layer in `tests/test_layer_boundaries.py` (`_get_imported_layer`, `:152-165`, returns `None` for a `probos.<name>` that is neither foundation nor in `LAYER_MAP`).

```
<<<<<<< SEARCH
    OBSERVATION_WARD_ROOM_LOOKBACK_HOURS,
)
=======
    OBSERVATION_WARD_ROOM_LOOKBACK_HOURS,
)
from probos.config_models.cognition import PROCEDURE_EVOLUTION_EPISODE_LIMIT  # AD-1326: shared with the validator
>>>>>>> REPLACE
```

13a-3. `src/probos/cognitive/dreaming.py`: the evidence recall asks for the shared limit (review round 3, R3-4; D11). `EpisodicMemory.recall_by_intent(intent_type, k=5, *, include_self_contradicted=False)` (`episodic.py:3358-3361`) returned at most five, so an accepted configuration needing ten episodes never reached `prepare` in production. The three sites keep their `[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]` slice. The name is read at call time, so `test_producers_cap_recall_at_the_shared_limit`'s monkeypatch (limit 4) also lowers `k`; its expectations hold (the first intent then gives four, the slice keeps four).

```
<<<<<<< SEARCH
        conversation's episode is among them (AD-1156 A-4, :func:`_outcome_evidence`)."""
        return _outcome_evidence(await self.episodic_memory.recall_by_intent(intent_type))
=======
        conversation's episode is among them (AD-1156 A-4, :func:`_outcome_evidence`).
        AD-1326 (R3-4): asks for ``PROCEDURE_EVOLUTION_EPISODE_LIMIT`` episodes, the recall the
        challenger settings are validated against (the memory's default ``k`` is 5)."""
        return _outcome_evidence(
            await self.episodic_memory.recall_by_intent(intent_type, k=PROCEDURE_EVOLUTION_EPISODE_LIMIT)
        )
>>>>>>> REPLACE
```

13b. `src/probos/cognitive/dreaming.py`: the type-only import of the service.

```
<<<<<<< SEARCH
    episode_ran_in_plan_mode,
)

logger = logging.getLogger(__name__)
=======
    episode_ran_in_plan_mode,
)

if TYPE_CHECKING:
    from probos.cognitive.procedure_challenger import ProcedureChallenger

logger = logging.getLogger(__name__)
>>>>>>> REPLACE
```

13c. `src/probos/cognitive/dreaming.py`: constructor injection.

```
<<<<<<< SEARCH
        intent_skill_map: dict[str, str] | None = None,  # AD-428b v1: intent->skill map
    ) -> None:
=======
        intent_skill_map: dict[str, str] | None = None,  # AD-428b v1: intent->skill map
        procedure_challenger: ProcedureChallenger | None = None,  # AD-1326: FIX evolution as a challenger
    ) -> None:
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
=======
        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
        # AD-1326: None keeps the legacy FIX handling (dreaming.procedure_challenger_enabled=false).
        self._procedure_challenger = procedure_challenger
>>>>>>> REPLACE
```

13d. `src/probos/cognitive/dreaming.py`: Step 7b site (`_evolve_degraded_procedures`).

```
<<<<<<< SEARCH
            # Limit to 10 most recent
            fresh_episodes = fresh_episodes[:10]

            if not fresh_episodes:
                self._addressed_degradations[proc_id] = now
                continue

            # Dispatch to appropriate evolution function
            result = None
            if diagnosis.startswith("FIX:"):
                result = await evolve_fix_procedure(
                    parent, diagnosis, metrics, fresh_episodes, self._llm_client,
                )
            elif diagnosis.startswith("DERIVED:"):
                result = await evolve_derived_procedure(
                    [parent], fresh_episodes, self._llm_client,
                )

            # Record attempt regardless of outcome
            self._addressed_degradations[proc_id] = time.time()

            if result is None:
                continue
=======
            # Limit to 10 most recent (AD-1326: the limit the challenger controls are validated against)
            fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]

            if not fresh_episodes:
                self._addressed_degradations[proc_id] = now
                continue

            # AD-1326: a FIX result is a challenger; its held-out episodes stay out of the rewrite.
            plan = None
            if self._procedure_challenger is not None and diagnosis.startswith("FIX:"):  # AD-1326 step 7b
                plan = await self._procedure_challenger.prepare(parent, fresh_episodes)
                if plan is None:
                    self._addressed_degradations[proc_id] = now
                    continue

            # Dispatch to appropriate evolution function
            result = None
            if diagnosis.startswith("FIX:"):
                result = await evolve_fix_procedure(
                    parent, diagnosis, metrics,
                    list(plan.evolution_episodes) if plan is not None else fresh_episodes,  # AD-1326 step 7b
                    self._llm_client,
                )
            elif diagnosis.startswith("DERIVED:"):
                result = await evolve_derived_procedure(
                    [parent], fresh_episodes, self._llm_client,
                )

            # Record attempt regardless of outcome
            self._addressed_degradations[proc_id] = time.time()

            if result is None:
                continue

            if plan is not None:
                challenger = await self._procedure_challenger.submit(plan, result)
                if challenger is not None:
                    procedures.append(challenger)
                    evolved_count += 1
                continue
>>>>>>> REPLACE
```

13e-0. `src/probos/cognitive/dreaming.py`: the proactive site's recall cap uses the shared limit (review round 1, F6). The SEARCH is unique: the other two caps sit at 12 and 16 spaces, so the newline followed by exactly 8 spaces and `fresh_episodes` occurs once.

```
<<<<<<< SEARCH
            except Exception:
                continue
        fresh_episodes = fresh_episodes[:10]

        if not fresh_episodes:
=======
            except Exception:
                continue
        fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]

        if not fresh_episodes:
>>>>>>> REPLACE
```

13e. `src/probos/cognitive/dreaming.py`: reactive / proactive site (`_attempt_procedure_evolution`).

```
<<<<<<< SEARCH
        # Dispatch to appropriate evolution function with retry
        result = None
        if diagnosis.startswith("FIX:"):
            result = await evolve_with_retry(
                evolve_fix_procedure,
                parent, diagnosis, metrics, fresh_episodes, self._llm_client,
            )
        elif diagnosis.startswith("DERIVED:"):
            result = await evolve_with_retry(
                evolve_derived_procedure,
                [parent], fresh_episodes, self._llm_client,
            )

        self._addressed_degradations[proc_id] = time.time()

        if result is None:
            return False
=======
        # AD-1326: a FIX result is a challenger; its held-out episodes stay out of the rewrite.
        plan = None
        if self._procedure_challenger is not None and diagnosis.startswith("FIX:"):  # AD-1326 proactive
            plan = await self._procedure_challenger.prepare(parent, fresh_episodes)
            if plan is None:
                self._addressed_degradations[proc_id] = now
                return False

        # Dispatch to appropriate evolution function with retry
        result = None
        if diagnosis.startswith("FIX:"):
            result = await evolve_with_retry(
                evolve_fix_procedure,
                parent, diagnosis, metrics,
                list(plan.evolution_episodes) if plan is not None else fresh_episodes,  # AD-1326 proactive
                self._llm_client,
            )
        elif diagnosis.startswith("DERIVED:"):
            result = await evolve_with_retry(
                evolve_derived_procedure,
                [parent], fresh_episodes, self._llm_client,
            )

        self._addressed_degradations[proc_id] = time.time()

        if result is None:
            return False

        if plan is not None:
            challenger = await self._procedure_challenger.submit(plan, result)
            if challenger is None:
                return False
            logger.info(
                "AD-1326: procedure challenger '%s' saved for champion '%s'; the champion keeps routing",
                challenger.name, parent.name,
            )
            return True
>>>>>>> REPLACE
```

13f. `src/probos/cognitive/dreaming.py`: Step 7d site (`_process_fallback_learning`).

```
<<<<<<< SEARCH
                fresh_episodes = fresh_episodes[:10]

                # Call evolution with retry
                result = await evolve_with_retry(
                    evolve_fix_from_fallback,
                    parent,
                    fallback_type,
                    event.get("llm_response", ""),
                    event.get("rejection_reason", ""),
                    fresh_episodes,
                    self._llm_client,
                )

                # Record attempt regardless of outcome
                self._addressed_degradations[proc_id] = time.time()

                if result is None:
                    continue
=======
                fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]

                # AD-1326: every fallback FIX (failure and near-miss) is a challenger.
                plan = None
                if self._procedure_challenger is not None:  # AD-1326 step 7d
                    # The rewrite prompt quotes this turn's LLM response, so the turn's own
                    # episodes are rewrite evidence and are never held out.
                    plan = await self._procedure_challenger.prepare(
                        parent, fresh_episodes, source_correlation_id=event.get("correlation_id", ""),
                    )
                    if plan is None:
                        self._addressed_degradations[proc_id] = time.time()
                        continue

                # Call evolution with retry
                result = await evolve_with_retry(
                    evolve_fix_from_fallback,
                    parent,
                    fallback_type,
                    event.get("llm_response", ""),
                    event.get("rejection_reason", ""),
                    list(plan.evolution_episodes) if plan is not None else fresh_episodes,  # AD-1326 step 7d
                    self._llm_client,
                )

                # Record attempt regardless of outcome
                self._addressed_degradations[proc_id] = time.time()

                if result is None:
                    continue

                if plan is not None:
                    if await self._procedure_challenger.submit(plan, result) is not None:
                        evolved_count += 1
                    continue
>>>>>>> REPLACE
```

13g. `src/probos/cognitive/dreaming.py`: Step 7d-2.

```
<<<<<<< SEARCH
        except Exception as e:
            logger.debug("Step 7d fallback learning failed: %s", e)

        # Step 7e: Observational learning from Ward Room (AD-537)
=======
        except Exception as e:
            logger.debug("Step 7d fallback learning failed: %s", e)

        # Step 7d-2: Procedure challengers meet their champions (AD-1326)
        if self._procedure_challenger is not None:
            try:
                challenge_report = await self._procedure_challenger.run_cycle()
                await self._expire_superseded_episode_sources(list(challenge_report.superseded_episodes))
            except Exception as e:
                logger.warning(
                    "Step 7d-2: procedure challenger comparisons failed (%s); pending challengers wait "
                    "for the next dream cycle, which also finishes any interrupted promotion",
                    e,
                )

        # Step 7e: Observational learning from Ward Room (AD-537)
>>>>>>> REPLACE
```

`consolidate_for_shutdown` (`dreaming.py:314-403`) is not touched: it runs no LLM step, so it never runs Step 7d-2.

13h. `tests/test_dream_step_7f.py`: fixture pin (revision 2026-10-13, executed). `_build_engine` builds the engine with `object.__new__` and sets each field by hand; without this line all 7 tests fail with `AttributeError: ... '_procedure_challenger'` at Step 7d-2 of `dream_cycle`.

```
<<<<<<< SEARCH
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = mock_store
    engine._last_procedures = []
=======
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = mock_store
    engine._procedure_challenger = None  # AD-1326
    engine._last_procedures = []
>>>>>>> REPLACE
```

13i. `tests/test_fallback_learning.py`: fixture pin (revision 2026-10-13, executed). `_make_dreaming_engine` builds the engine with `object.__new__`; without this line 8 tests fail (`TestDreamStep7d`, `TestDreamCycleIntegration`), most of them silently: Step 7d swallows the `AttributeError` (`Fallback learning failed for proc-001`) and the assertion that fails is "Expected 'save' to have been called once".

```
<<<<<<< SEARCH
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = overrides.get("procedure_store", _make_store_mock())
    engine._last_procedures = []
=======
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = overrides.get("procedure_store", _make_store_mock())
    engine._procedure_challenger = None  # AD-1326
    engine._last_procedures = []
>>>>>>> REPLACE
```

**Why a fixture pin, not production tolerance (ranked).** (1) **Chosen: one line per fixture**, the repo's convention (each AD that adds an engine attribute adds it to these hand-built fixtures, e.g. `# AD-537 fields`, `# AD-557 fields`, `# AD-551 fields` at `test_fallback_learning.py:142-151`); `None` is the legacy path these tests were written against. (2) `getattr(self, "_procedure_challenger", None)` at the four read sites in `dreaming.py` — loses: it is the defensive-`getattr` anti-pattern for an attribute `__init__` always sets (13c), and it turns a real wiring fault into silent legacy supersession, the exact unchecked replacement this AD removes, with no error to see. The other eight `__new__` constructions need no line (Hidden Pins Enumerated): none of them runs code that reads the attribute.

13j. `tests/test_ad579c_validity_dream.py`: fixture pin (review round 3, R3-4). Its `_FakeEvolutionMemory.recall_by_intent` (`:67`) takes no `k`, and `test_ad579c_validity_dream.py:185` drives `_evolve_degraded_procedures`, which recalls through the helper 13a-3 changes; without this line that call raises `TypeError`. The fake keeps returning every matching episode (the real `k` default is 5; the sites slice).

```
<<<<<<< SEARCH
    async def recall_by_intent(self, intent_type: str) -> list[Episode]:
=======
    async def recall_by_intent(self, intent_type: str, k: int = 5) -> list[Episode]:  # AD-1326 R3-4: the helper passes k
>>>>>>> REPLACE
```

#### Section 14 -- `src/probos/startup/dreaming.py`

14a. `src/probos/startup/dreaming.py`: import.

```
<<<<<<< SEARCH
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.reconsolidation import ReconsolidationScheduler
=======
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.procedure_challenger import build_procedure_challenger
from probos.cognitive.reconsolidation import ReconsolidationScheduler
>>>>>>> REPLACE
```

14b. `src/probos/startup/dreaming.py`: build and inject.

```
<<<<<<< SEARCH
    if episodic_memory:
        dream_cfg = config.dreaming
        dreaming_engine = DreamingEngine(
=======
    if episodic_memory:
        dream_cfg = config.dreaming
        # AD-1326: FIX evolution saves a challenger that replaces its champion only after winning.
        procedure_challenger = build_procedure_challenger(
            config=config,
            procedure_store=procedure_store,
            episodic_memory=episodic_memory,
            llm_client=llm_client,
            emit_event_fn=emit_event_fn,
        )
        dreaming_engine = DreamingEngine(
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
            failure_distiller=failure_distiller,
        )
=======
            failure_distiller=failure_distiller,
            procedure_challenger=procedure_challenger,
        )
>>>>>>> REPLACE
```

#### Section 15 -- trackers (`PROGRESS.md`, `DECISIONS.md`)

15a. `PROGRESS.md`: one line under the current AD list: "AD-1326 (#1510): FIX procedure evolution saves an inactive challenger judged head-to-head (both orders, held-out episodes, Bradley-Terry) and promoted only on a win; rewriting on deep with a standard floor; `dreaming.procedure_challenger_enabled=false` keeps the legacy FIX handling."
15b. `DECISIONS.md`: an `AD-1326` entry with D1-D9 as one line each (D9: one line per review-round-1 finding) (chosen option and the reason the runner-up lost), and the two discovered defects named in Prior Art and Blind Spots as out-of-scope follow-ups.

**Milestone 3 focused gate:**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1326_procedure_challenger.py tests/test_ad1326_challenger_e2e.py tests/test_ad1326_dreaming_challenger.py tests/test_ad1195_durable_event_seam.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_durable_producers.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_events.py tests/test_ad1156_plan_mode_learning.py tests/test_procedure_evolution.py tests/test_fallback_learning.py tests/test_dream_step_7f.py tests/test_reactive_proactive_triggers.py tests/test_ad579c_validity_dream.py tests/test_dreaming.py tests/test_ad959_shutdown_light_consolidation.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
```
The broad gate runs once, in the main session, per `CLAUDE.md` step 5.

---

## Tests (descriptions; Builders write them)

**Doubles carry what the real seam carries.** LLM doubles receive the real `LLMRequest` and return a real `LLMResponse` with `content`, `model`, `tier`, `answered_tier` and `answered_model` set the way `OpenAICompatibleClient` sets them (a verifier attempt that fell back answers with `answered_tier="standard"`). The episodic double implements `get_by_ids(ids, *, for_evidence=False)` over real `Episode` objects, honours missing ids, and records `update_episode_validity(id, valid_until=...)`. The emit double records `(event_type, payload)`. Procedures are real `Procedure`/`ProcedureStep`. Independence fixtures reuse model ids that `model_registry.model_family` knows (take them from `tests/test_ad1327_verifier_independence.py`).

### `tests/test_ad1326_procedure_ranking.py` (Milestone 1)
- `test_bradley_terry_star_matches_closed_form` — candidate A 3 wins, 1 loss vs reference R: `{R: 1.0, A: 3.5/1.5}` (`approx(rel=1e-9)`; R exactly 1.0).
- `test_bradley_terry_star_with_ties_counts_half_each` — A 1 win, 2 ties, 0 losses: A = 2.5/1.5.
- `test_bradley_terry_candidate_that_never_won_is_finite` — B 0 wins, 4 losses: B = 0.5/4.5, finite and > 0.
- `test_bradley_terry_cycle_is_uniform` — A>B, B>C, C>A, reference A: all 1.0.
- `test_bradley_terry_two_candidates_decouple_on_a_star` — A (3-1) and B (0-4) both vs R: the two closed-form values at once.
- `test_bradley_terry_no_outcomes_returns_reference_only` — `{R: 1.0}`.
- R1 (F4) `test_bradley_terry_star_equal_records_are_exactly_equal` — parametrized over the two UUID-shaped id layouts of the reviewer's probe (`logs/architect/probe_ad1326_r1_findings.py:49-55`: reference `55555555-0000-4000-8000-000000000000`; candidates `11111111-...` and `99999999-...`, each layout giving the 2W2T record to a different one): the 2W2T and 3W1L candidates' strengths are `==` each other and `== 3.5 / 1.5` (exact, not `approx`).
- R1 (F4) `test_bradley_terry_non_star_still_iterates` — A vs B and B vs R only (A never met R): the result satisfies the MM fixed point `p_i * sum(n_ij / (p_i + p_j)) == w_i` for every player within `rel=1e-9`, and the reference is exactly 1.0 (row 3's killer: the fixed point alone is scale-free).
- `test_bradley_terry_is_order_independent_bit_for_bit` — every permutation of a 6-outcome mixed list gives `==` dicts.
- `test_bradley_terry_rejects_disconnected_players`, `test_bradley_terry_rejects_bad_arguments` (empty/non-str reference, prior 0, NaN, inf, `max_iterations=0`, negative tolerance).
- `test_pair_outcome_rejects_self_pair_empty_and_unknown_result`.
- `test_beats_champion_requires_share_strictly_above_threshold` — margin 0.1: 3/4 True, 3/5 False (exactly 0.6), 2/4 False.
- `test_beats_champion_requires_min_decisions` — 2/2 with min 3 False; 0 decisions False.
- `test_beats_champion_rejects_inconsistent_counts` — wins > decisions, negative wins.

### `tests/test_ad1326_procedure_ledger.py` (Milestone 1)
- `test_start_creates_its_tables_in_its_own_file` (a real connection from `default_factory` on `tmp_path/"procedures_challenges.db"`, handed to the ledger; the three tables exist; the test closes the connection).
- `test_start_failure_propagates_and_leaves_the_connection_to_its_owner` (a connection double whose `executescript` raises: the exception surfaces, `close` is NOT awaited by the ledger, and methods still raise `RuntimeError`).
- `test_constructor_refuses_a_missing_connection` (`None` -> `ValueError("procedure_challenge_connection_missing")`).
- `test_methods_refuse_before_start_and_after_detach` (`RuntimeError`; `detach` does not close the connection: it still answers `SELECT 1`).
- `test_add_challenger_round_trips` (all fields via `get`).
- `test_add_challenger_rejects_bad_ids` (empty, NUL, 129 chars, lone surrogate, self-challenge, overlapping used/held-out, context outside both, 21 ids, duplicate episode id, a bare `str` for a list, duplicate challenger -> integrity error).
- `test_set_status_is_conditional_on_expected` (pending->retired True; retired->promoted with expected pending False; invalid status raises).
- `test_list_by_status_orders_by_created_then_id` (injected clock).
- `test_pending_count_counts_pending_and_promoting_only`.
- R1 (F5) `test_add_challenger_enforces_the_pending_cap_atomically` — real ledger: `max_pending=1`, `asyncio.gather` of two `add_challenger` calls for the same champion: exactly one record `pending`, the other `retired` with `decision_reason` starting `pending_limit:` and `decided_at > 0`; `pending_count == 1`; a `promoting` row counts toward the cap; another champion's cap is independent; without `max_pending` no cap applies (the existing callers' behaviour).
- R1 (F5) `test_add_challenger_rejects_a_bad_cap` — `max_pending` of 0, -1, `True`, 1.5 -> `ValueError("procedure_challenge_max_pending_invalid")`; nothing inserted.
- R1 (F1) `test_sync_routing_index_rewrites_the_entry_from_sqlite` — real `ProcedureStore` with Chroma on (`tests/test_procedure_store.py:156-164`): champion saved active; the collection's `update` made to raise (monkeypatch on the live collection object, as the reviewer's probe); `deactivate(champion)`; premise asserted first: SQLite says inactive and the index entry still says active (R2: read test-side through a helper `_index_says_active(store, pid)` = `store._chroma_collection.get(ids=[pid], include=["metadatas"])["metadatas"][0]["is_active"]`; `find_matching` no longer shows the stale entry since 3g); then `sync_routing_index(champion) is True` and the entry says inactive.
- R2 (R2-1) `test_find_matching_admits_only_rows_active_in_sqlite` — real store with Chroma on: two procedures with the same description saved active (`p-stale`, `p-live`); `update` raises during `deactivate("p-stale")`; premise: SQLite says `p-stale` is inactive and `_index_says_active(store, "p-stale") is True`; `find_matching(<description>)` returns `p-live` only, and its row has exactly the keys it had at base (`id, name, evolution_type, compilation_level, intent_types, total_selections, total_applied, total_completions, total_fallbacks, is_negative, score`); after `sync_routing_index("p-stale")` the result is the same (positive control that the drop was SQLite's, not the index's).
- R2 (R2-3) `test_backup_copies_the_ledger_after_procedures_db` — a real `ProcedureStore(tmp_path / "data" / "procedures")` started and stopped; `discover([BackupRoot("data", tmp_path / "data")], backup_root=tmp_path / "data" / "backups")` (`probos.infrastructure.backup_inventory`, as `tests/test_ad1265_backup_coverage.py:100-104`): the relative paths, in order, contain `procedures/procedures.db` before `procedures/procedures_challenges.db`; and the declaration `cognitive.procedure-challenges` has `canonical_path == "procedures/procedures_challenges.db"`.
- R1 (F1) `test_sync_routing_index_reports_a_failed_index_write` — the collection's `upsert` raises: `False`, one WARNING from `_save_to_chroma`.
- R1 (F1) `test_sync_routing_index_is_true_without_an_index_or_a_row` — a store whose `_init_chroma` is monkeypatched to a no-op coroutine (no index): `True` with no write; an unknown id on an indexed store: `True`.
- `test_record_comparison_validates_enums_and_never_counts_invalid`.
- `test_record_comparison_persists_bounded_reason_with_surrogate_and_nul` — a reason built from `json.loads('"a\\ud800b\\u0000c"')` passed through `bounded_text` round-trips, and `json.dumps(record.judgements, ensure_ascii=False).encode("utf-8")` succeeds.
- `test_record_comparison_rejects_unencodable_or_oversized_judgements` (raw lone surrogate in a judgement -> `ValueError`; 9 KB -> `ValueError`).
- `test_increment_cycles_only_moves_pending`.
- `test_record_cycle_and_recent_cycles` (negative or non-int refused).
- `test_retired_challenger_keeps_its_comparisons`.
- `test_ledger_module_issues_no_delete` (source text of `procedure_challenges.py` contains no `DELETE`; raw scan, intentional).
- `test_bounded_text_removes_nul_replaces_surrogate_and_cuts` (non-`str` -> `""`, `limit=0` -> `""`, str subclass -> `""`).
- `test_procedure_store_opens_the_ledger_beside_procedures_db` (real `ProcedureStore(tmp_path/"procedures")`: `challenges` is a `ProcedureChallengeLedger`; `procedures_challenges.db` exists).
- `test_procedure_store_opens_the_ledger_on_its_own_connection` (a recording factory wrapping `default_factory`, injected as the STORE's `connection_factory`, sees exactly two `connect` calls with distinct paths ending `procedures.db` and `procedures_challenges.db`; the ledger is constructed with no factory of its own).
- `test_procedure_store_stop_closes_the_ledger` (after `stop`, `challenges is None`, the old ledger raises `RuntimeError`, and the connection the recording factory returned for `procedures_challenges.db` is closed: a further `execute` on it raises).
- `test_ledger_start_failure_leaves_the_store_running` (monkeypatch `ProcedureChallengeLedger.start` to raise; `store.start()` succeeds; `challenges is None`; the ledger's connection from the recording factory was closed and the store holds none (`vars(store)["_challenges_db"] is None`, test-side read); one WARNING naming AD-1326; the number of live `_connection_worker_thread` threads is the store's one).
- `test_last_resort_close_reaches_the_ledger_connection` (D1b; the executed finding). After a real `store.start()` on `tmp_path`: `closable, raw = _direct_connections(store)` (`from probos.startup.shutdown import _direct_connections`, a test-side import of the helper under test) names exactly `{"_db", "_challenges_db"}` and `raw == []`. Then, as in a rollback whose `store.stop()` raised before any cleanup (so `stop` is never called), `steps = _RollbackSteps(rollback=True)`; `steps.keep_failed("procedure store stop", store)`; `await steps.settle_failed()`: both connections are closed (the `_connection_worker_thread` threads started by this store are gone, compared against a snapshot of `threading.enumerate()` taken before `store.start()`), and the log has `BF-882: last-resort close of ProcedureStore._challenges_db `. Fails against the first draft (ledger-held connection): `_direct_connections` names only `_db` and one worker thread survives.
- R3 (R3-2) `test_failed_ledger_write_is_rolled_back` — parametrized over the five writers (`add_challenger`, `record_comparison`, `set_status`, `increment_cycles`, `record_cycle`, each called with valid arguments on a ledger holding one `pending` challenger) x the failure point (`execute`: the writer's data statement raises `sqlite3.OperationalError`; `commit`: `commit` raises it). The ledger runs on a test-side wrapper around a real `default_factory` connection that forwards every call and raises once at the chosen point (no `MagicMock`). Assert: the writer raises that error; the real connection's `in_transaction is False`; the ledger's own reads (`get`, `list_by_status`, `comparisons`, `recent_cycles`) and an independent `sqlite3.connect` reader of the same file both show the state before the call; and the same writer, called again with the fault gone, succeeds and both readers see it.
- R3 (R3-2) `test_cancelled_ledger_write_is_rolled_back` — the wrapper's `commit` raises `asyncio.CancelledError` during `set_status(..., "promoted", expected=("promoting",))`: `CancelledError` propagates, `in_transaction is False`, both readers see `promoting`.
- R3 (R3-2) `test_failed_rollback_is_logged_and_the_write_error_propagates` — `commit` raises and the following `ROLLBACK` raises too: the commit's error propagates (not the rollback's), one ERROR from `probos.cognitive.procedure_challenges` naming AD-1326; the next write raises (its `BEGIN IMMEDIATE` meets the open transaction) and nothing is committed.
- R3 (R3-2) `test_every_ledger_writer_runs_in_one_transaction` — AST over `procedure_challenges.py`, intentional source scan: each of the five writers contains exactly one `async with _write_transaction(` and no `.commit(` call; the only `.commit(` calls in the module are in `_write_transaction` and `ProcedureChallengeLedger.start`.
- R3 (R3-3) `test_sync_routing_index_publishes_the_activity_column` — the reviewer's case on a real store with Chroma on: a procedure saved active; during `deactivate` the `content_snapshot` UPDATE fails (test-side wrapper of the store's real `_db` that raises on the statement starting `UPDATE procedure_records SET content_snapshot`); premises: the `is_active` column is 0 and `get(...).is_active is True`; `sync_routing_index(...) is True` and `_index_says_active(store, pid) is False`. Positive control: a row whose column is 1 publishes active.
- R3 (R3-5) `test_challenge_record_bars_routing_table` — `bars_routing` is True for `pending` and `retired`, False for `promoting` and `promoted`.
- R3 (R3-5) `test_find_matching_refuses_a_challenger_the_ledger_holds_undecided` — parametrized `pending`, `retired`: real store with Chroma on and its ledger; champion saved active, challenger saved ACTIVE (the restored state) with a ledger row in that status; premises: SQLite says both active and `_index_says_active` is True for both; `find_matching(<description>)` returns the champion only, with the base keys.
- R3 (R3-5) `test_find_matching_admits_a_promoting_or_promoted_challenger` — parametrized `promoting`, `promoted`: same layout; both are returned.
- R3 (R3-5) `test_find_matching_without_a_readable_ledger_admits_on_sqlite` — parametrized `not_open` (`ProcedureChallengeLedger.start` monkeypatched to raise, as `test_ledger_start_failure_leaves_the_store_running`) and `read_fails` (the ledger's `get` monkeypatched to raise `RuntimeError`; one WARNING naming AD-1326): an active challenger with a `pending` row (written before the fault) is returned beside the champion — the fail-open path, today's behaviour.
- R4 (R4-1) rig for the five tests below: a real `default_factory` connection to `tmp_path/"procedures_challenges.db"` handed to a started ledger holding one `pending` challenger `c1`; a `blocker = sqlite3.connect(path, timeout=0, isolation_level=None)` that runs `BEGIN IMMEDIATE` (it holds the write lock) and later `ROLLBACK` and `close`; an independent reader as in `test_failed_ledger_write_is_rolled_back`; "blocked" means `await asyncio.sleep(0.05)` with the writer task not done (premise asserted). Every test ends with: the ledger connection's `in_transaction is False`, no record from `probos.cognitive.procedure_challenges` at ERROR or above, a further `set_status`/`increment_cycles` on the ledger succeeds, and a fresh `sqlite3.connect(path, timeout=0)` can `BEGIN IMMEDIATE` and `ROLLBACK` (the write lock is free).
- R4 (R4-1) `test_a_cancelled_begin_is_rolled_back_after_it_takes_effect` — the reviewer's case: `set_status("c1", "promoting", reason="r", expected=("pending",))` as a task, blocked on the blocker's lock; `task.cancel()`; after `await asyncio.sleep(0.05)` the task is still not done (it holds the ledger lock until its rollback has run; premise of the fix); the blocker rolls back and closes; `await task` raises `CancelledError`; both readers see `pending`. Fails at the round-3 tree (`in_transaction` True; the next write raises "cannot start a transaction within a transaction").
- R4 (R4-1) `test_a_cancelled_begin_that_never_takes_effect_logs_nothing` — as above, but the ledger connection's busy timeout is lowered test-side (`await conn.execute("PRAGMA busy_timeout=100")` after `start`) and the blocker keeps the lock for 0.5 s after the cancel, so the queued `BEGIN` fails with "database is locked" and the queued `ROLLBACK` meets no transaction; then the blocker releases. `CancelledError` propagates; both readers see `pending`; no ERROR (the "no transaction is active" refusal is expected).
- R4 (R4-1) `test_a_cancelled_commit_that_still_commits_is_durable_and_logs_nothing` — no blocker; the test-side forwarding wrapper's `commit` starts the real `commit()` as a task it keeps, yields once (`await asyncio.sleep(0)`, so the COMMIT is queued on the worker thread), then raises `asyncio.CancelledError`; the test awaits the kept task before asserting. `set_status("c1", "promoting", ...)` raises `CancelledError`; both readers see `promoting` (the write is durable although its caller saw the cancellation: D12, R4-1); the wrapper saw one `ROLLBACK` and it raised "no transaction is active", which is not logged.
- R4 (R4-1) `test_a_second_cancellation_during_cleanup_still_rolls_back` — as the first test, but `task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0); task.cancel()` (the second cancel reaches the writer before the cleanup task has started). After the blocker releases: `CancelledError`, `task.cancelled()` True, both readers see `pending`, and the end-of-test checks hold.
- R4 (R4-1) `test_a_cancellation_during_rollback_waits_for_it_and_is_delivered` — the wrapper's `commit` raises `sqlite3.OperationalError("injected")`, and its `execute("ROLLBACK")` sets `rollback_started` and waits on a test `asyncio.Event` before forwarding. Once `rollback_started` is set, `task.cancel()`; after `await asyncio.sleep(0.05)` the task is not done; the event is set; `await task` raises `CancelledError` (not the `OperationalError`: the cancellation is delivered after the cleanup) and `task.cancelled()` is True; both readers see `pending`.
- R4 (R4-2) `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds` — real store with Chroma on and its ledger; NO `ProcedureChallenger` is built. Champion saved active, challenger `ch-a` saved active, ledger row `pending`; then the champion is deactivated per variant. Parametrized: `completed` (`superseded_by="ch-a"`) -> `find_matching(<champion description>)` returns `ch-a` only, with the base keys; `champion_active` (not deactivated) -> the champion only; `superseded_by_another` (`superseded_by="other"`) -> `[]`; `champion_missing` (`store.delete(CHAMPION_ID)`) -> `[]`; `retired_completed` (ledger row `retired`, `superseded_by="ch-a"`) -> `[]`. Premises: SQLite says `ch-a` active and `_index_says_active(store, "ch-a") is True` in every variant.
- R4 (R4-2) `test_flag_off_routes_a_restored_completed_promotion` — the reviewer's case: `DreamingConfig(procedure_challenger_enabled=False)`; premise: `build_procedure_challenger(...)` returns `None` for it (as `test_build_returns_none_when_disabled`); the `completed` layout above with one counted comparison in the ledger, on a store started from a fresh `ProcedureStore` over the same directory (a restart, as after a restore); `find_matching` returns `ch-a` and the ledger still says `pending` (routing needs no reconciliation).
- R5 helpers (test-side only): `_QueueingConnection` gains `commit_gate: asyncio.Event | None = None` and `commit_started = asyncio.Event()`; with a gate set, `commit` appends `"COMMIT"` to `calls`, sets `commit_started` and awaits the gate before it forwards (a cancellation while it waits never forwards the COMMIT). `_FaultingFactory.__init__` gains `wrapper: type[_FaultingConnection] = _FaultingConnection`, used in `connect`; existing callers are unchanged.
- R5 (R5-1) `test_every_public_ledger_read_waits_for_an_in_flight_write` — `queueing` fixture; parametrized over the five reads: `get("c1")`, `list_by_status("pending")`, `pending_count(<c1's champion>)`, `comparisons("c1")`, `recent_cycles()`. Set `commit_gate`; start `set_status("c1", "promoting", reason="r", expected=("pending",))` as a task; `await asyncio.wait_for(connection.commit_started.wait(), 10.0)`. Premises: `queueing.in_transaction is True` (the UPDATE is applied) and the independent reader (`_file_view`) still sees `pending`. Start the read as a task; after `await asyncio.sleep(0.05)` it is not done (it waits for the writer, not for SQLite). Set the gate; both finish; `get` returns `promoting` and `list_by_status("pending")` returns `[]` (the committed state), the others return what an independent reader then sees. `finally`: set the gate and settle both tasks.
- R5 (R5-1) `test_a_read_during_a_rolled_back_write_returns_the_committed_row` — as above with `get("c1")` only, but the writer is cancelled while it waits at the commit gate (the reviewer's interleaving: the read is queued before the cleanup `ROLLBACK`). `writer.cancelled()`; the read returns status `pending` with `decision_reason == ""`; the independent reader sees `pending`; `connection.verbs` ends with `"ROLLBACK"` and holds no forwarded `COMMIT` outcome; `_assert_ledger_is_free(queueing, caplog, status="pending")`.
- R5 (R5-1) `test_find_matching_waits_for_a_rolled_back_promotion_and_routes_the_champion` — `ProcedureStore(tmp_path / "procedures", connection_factory=_FaultingFactory(wrapper=_QueueingConnection))`, started; `_stage_active_challenger(store, "pending")` (challenger `chal` active in SQLite and the index, its row `pending`); the ledger connection is `factory.connected["procedures_challenges.db"]`; gate its commit; start `store.challenges.set_status("chal", "promoting", reason="r", expected=("pending",))`; once `commit_started`, start `store.find_matching(_procedure().description)` as a task; after `asyncio.sleep(0.05)` it is not done; cancel the writer; the match ids are `["champ"]` with `_ROUTING_ROW_KEYS`, and `(await store.challenges.get("chal")).status == "pending"`. `finally`: set the gate, settle the tasks, `store.stop()`, `factory.close_all()`.
- R5 pin move (R5-2): `test_sync_routing_index_publishes_the_activity_column` (`tests/test_ad1326_procedure_ledger.py:2052-2053`): `stale = await store.get("champ")` / `assert stale is not None and stale.is_active is True` becomes a raw premise and the R5-2 assertion: a new helper beside `_is_active_column`, `_snapshot_lineage(db_path, procedure_id) -> tuple[bool, str]` (an independent `sqlite3` read of `content_snapshot`, returning its JSON `is_active` and `superseded_by`), gives `(True, "")` (the snapshot is stale), and `store.get("champ")` returns `is_active is False` and `superseded_by == "challenger"` (the columns). The docstring's "``get`` reads the snapshot" becomes "``get`` takes both from the columns (R5-2)". The rest of the test is unchanged and still pins the index publication, now through `get`.
- R6 pin move (R6-1, reverses the R5 pin move): in `test_sync_routing_index_publishes_the_activity_column` (`tests/test_ad1326_procedure_ledger.py:2083-2084` in the frozen candidate) the two `get` lines become `champion = await store.get("champ")  # get rebuilds from the stale snapshot (base behaviour; R6-1)` and `assert champion is not None and champion.is_active is True and champion.superseded_by == ""`, followed by `assert await store.routing_state("champ") == (False, "challenger")  # R6-1: the columns admission reads`. Docstring: "``get`` takes both from the columns (R5-2)" becomes "``get`` keeps reading the snapshot and ``routing_state`` reads the columns (R6-1)". `_snapshot_lineage` stays (the `:2082` premise uses it); its docstring's "before R5-2 ``ProcedureStore.get`` rebuilt a procedure from it" becomes "``ProcedureStore.get`` rebuilds a procedure from it". Everything else, the index assertions and the positive control, is unchanged: `sync_routing_index` now publishes the column through `routing_state` (mutation row 55).
- R6 (R6-1) `test_routing_state_reads_the_columns_not_the_snapshot` — `_FaultingFactory`, real store started; save `champ` active; arm `"UPDATE procedure_records SET content_snapshot"`; `deactivate("champ", superseded_by="chal")`. Premises: `_is_active_column(db_path, "champ") == 0`, `_snapshot_lineage(db_path, "champ") == (True, "")`. `await store.routing_state("champ") == (False, "chal")`; `get("champ")` returns `is_active is True` and `superseded_by == ""` (base `get`, unchanged); `routing_state("absent") is None`; a store whose `_db` is unset (after `stop()`) returns `None`. Positive control: a healthy saved row `p` gives `(True, "")`.
- R6 (R6-1) `test_restore_with_a_refused_snapshot_publishes_no_active_entry_at_a_stale_level` — the reviewer's consumer case. `_FaultingFactory`, real store with the index (`deterministic_embeddings`); save `p` with `compilation_level=4`, `last_used_at=1_000.0`; `demote_compilation_level("p", 1)` (column only); `archive_stale_procedures(now=1_000.0 + (LIFECYCLE_ARCHIVE_DAYS + 1) * 86_400)` returns `p`; then arm `"UPDATE procedure_records SET content_snapshot"` and `restore_procedure("p") is True`. Premises, independent reads: the columns say `is_active=1, is_archived=0, compilation_level=1`; the snapshot says `is_active` False, `is_archived` True, `compilation_level` 4; `len(procedures_db.fired) == 1`. Assertions: `get("p")` returns `is_active is False` and `compilation_level == 4` (base: nothing merged); `_index_says_active(store, "p") is False` (no ACTIVE entry whose replay level contradicts the column); `await store.find_matching(<p's description>, min_compilation_level=2)` holds no `p`. Under round 5's `get` the entry was active at level 4 and the agent replayed it autonomously.

### `tests/test_ad1326_procedure_judge.py` (Milestone 2)
- `test_render_candidate_hides_identity` (name, id, generation, `evolution_type`, parent ids, tags absent; steps, agent roles, expected output, fallback, postconditions present; preconditions absent, as in replay — review round 1 moved this from "present").
- R1 (F2) `test_render_candidate_is_the_replay_body` — parametrized procedures (with and without description, agent role, expected output, fallback, postconditions): `render_candidate(p) == "\n".join(CognitiveAgent._format_procedure_replay(agent, p).split("\n")[3:])`, where `agent = CognitiveAgent.__new__(CognitiveAgent)` (both formatters read only their arguments); all procedures under 4,000 characters (the cut is the next test).
- R2 (R2-5) `test_render_candidate_is_the_bounded_replay_body_at_the_cut` — parametrized on the replay body's length, 3,999 / 4,000 / 4,001 / 4,200 characters (an ASCII description padded to the length, one step `"Compute the result"`): `render_candidate(p) == body[:MAX_CANDIDATE_CHARS]` where `body` is replay's body as in the test above; at 3,999 and 4,000 that is the whole body. The 4,200 case is the reviewer's: premise asserted first that `body` holds the step.
- R1 (F2) `test_render_candidate_distinguishes_a_role_only_repair` — the reviewer's pair (one step `"Compute the result"`, `agent_role` `calculation` vs `formatting`): the replay outputs differ (premise) and so do the renderings; each contains `**Step 1 [<role>]:**`.
- `test_prompts_never_name_roles` (no `champion`/`challenger`, case-insensitive, in system or user prompt of either call).
- `test_each_situation_is_asked_in_both_orders` (two requests; candidate texts swap positions).
- `test_rng_chooses_the_first_order_deterministically` (same seed same `first_shown`; seeds 0..19 produce both).
- `test_position_biased_judge_yields_only_ties` (always `"1"`, then always `"2"`; seeds 0..19; outcome `tie` every time, counted).
- `test_content_judge_outcome_ignores_position_and_role` (a double that prefers the candidate containing a marker step: winner is that candidate for every seed, and stays with the content when the champion/challenger roles are swapped).
- `test_combine_orders_table` (all 16 pairs).
- `test_invalid_reply_error_or_exception_is_invalid_and_not_counted` (non-JSON, `preferred: "3"`, `preferred: true`, `response.error`, raised `RuntimeError`; `asyncio.CancelledError` propagates).
- `test_parse_preference_accepts_strings_and_ints`.
- `test_reason_is_bounded` (provider JSON `"reason": "x\\ud800\\u0000..."` of 2,000 chars -> 500 chars, no NUL, `?` for the surrogate, encodes as strict UTF-8).
- `test_judge_requests_the_policy_tier_never_deep` (`standard` with no verifier; `verifier` with one; `max_tokens == 512`; `temperature == 0.0`).
- `test_provenance_is_recorded_from_the_answered_fields`.
- `test_fallback_judgement_is_recorded_not_counted_when_an_independent_judge_is_configured` (policy whose `assess()` is `independent`; one response with `answered_tier="standard"` -> `counted` False, both judgements recorded).
- `test_same_model_judge_counts_when_no_independent_judge_is_configured`.
- `test_situation_and_candidates_are_bounded` (oversized `user_input`, outcomes that cannot `json.dumps` -> `<unrenderable>`).
- R3 (R3-1) `test_judgement_by_the_optimizers_model_is_not_independent` — the reviewer's case: policy `VerifierJudgePolicy("verifier", "gpt-5.1", _CREW)` (Claude crew; `assess() == "independent"`), both responses `answered_tier="verifier"`, `answered_model="gpt-5.1"`. Premise: `compare(...)` without `optimizer_model` gives both judgements `independent` and `counted` True. Parametrized `optimizer_model`: `"gpt-5.1"` -> both `same_model`, `counted` False; a model of the judge's family that is not the judge (take one from `tests/test_ad1327_verifier_independence.py`) -> `same_family`, `counted` False; `"mystery-7b"` -> `unknown`, `counted` False. In every case `judge.requires_independent is True` and the outcome is still computed (recorded, not counted).
- R3 (R3-1) `test_empty_optimizer_model_changes_nothing` — `optimizer_model=""` and a non-`str` value give a verdict `==` to the call without it, for both an independent and a same-model policy, seeds 0..4.
- R3 (R3-1) `test_optimizer_model_never_relaxes_the_counting_rule` — no verifier (`requires_independent` False): with `optimizer_model` equal to the judge's model every valid judgement still counts and the labels say `same_model`; with an independent verifier and a crew-model optimizer (`"claude-opus-4-6"`), a `gpt-5.1` judge stays `independent` and counted.
- R4 (R4-3) `test_optimizer_model_never_raises_a_label` — parametrized; each case asserts both judgements' `independence`, `counted` and `judge.requires_independent`, and compares with the call without `optimizer_model`. `empty_basis` (the reviewer's): `VerifierJudgePolicy("verifier", "gpt-5.1", ("", "", ""))`, answers `answered_tier="verifier"`, `answered_model="gpt-5.1"`, `optimizer_model="claude-opus-4-6"`: premise `classify_independence("gpt-5.1", ("", "", "", "claude-opus-4-6")) == "independent"` (the augmented basis would raise it); both labels `unknown`, `counted` True, `requires_independent` False, verdict `==` the call without the optimizer. `lowers` (the R3-1 case): `_CREW` policy, judge and optimizer `gpt-5.1`: `same_model`, `counted` False. `unchanged`: `_CREW` policy, judge `gpt-5.1`, optimizer `claude-opus-4-6`: `independent`, `counted` True, verdict `==` the call without it. `empty_basis_judge_is_optimizer`: empty crew, judge and optimizer `gpt-5.1`: `same_model` (a weak augmented label is kept).

### `tests/test_ad1326_rewrite_tier.py` (Milestone 2)
- `test_rewrite_requests_use_deep_with_a_standard_floor` — parametrized over `evolve_fix_procedure`, `evolve_derived_procedure`, `evolve_fix_from_fallback`: captured `LLMRequest.tier == "deep"`, `min_tier == "standard"`, `exact_tier is False`.
- `test_non_rewriting_calls_stay_standard_without_a_floor` — `confirm_evolution_with_llm`, `extract_procedure_from_cluster`, `extract_procedure_from_observation`, `extract_negative_procedure_from_cluster`, `extract_compound_procedure_from_cluster`: `tier == "standard"`, `min_tier is None`.
- `test_optimizer_provenance_is_recorded_from_the_response` (real `LLMResponse(answered_tier="deep", answered_model="m")`).
- `test_optimizer_provenance_is_blank_for_mocks_and_unpersistable_text` (bare `MagicMock`, NUL, lone surrogate, 300 chars).

### `tests/test_ad1326_config.py` (Milestone 2)
- `test_challenger_defaults`, `test_challenger_bounds_reject_out_of_range` (each field at both bounds; review round 1: `used_contexts` 0..10, `held_out_episodes` 0..5, `min_decisions` 1..10 — update every case that accepted `min_decisions` above 10 or `held_out_episodes` above 5, including the one that accepted `min_decisions=20`), `test_min_decisions_above_available_situations_is_rejected_at_parse_time`, `test_flag_off_validates_from_a_plain_dict`.
- R1 (F6) `test_reviewers_unreachable_configuration_is_rejected` — `used_contexts=10, held_out_episodes=10, min_decisions=20` raises `ValidationError`; `used_contexts=10, held_out_episodes=5, min_decisions=10` is accepted.
- R1 (F6) `test_validator_reads_the_shared_recall_limit` — `PROCEDURE_EVOLUTION_EPISODE_LIMIT == 10`, imported from `probos.config_models.cognition`; `probos.cognitive.dreaming.PROCEDURE_EVOLUTION_EPISODE_LIMIT is` that same object; the name is not an attribute of `probos.config` (the facade pin stays).

### `tests/test_ad1326_procedure_challenger.py` (Milestone 3; real `ProcedureStore` and ledger on `tmp_path` unless stated)
- `test_split_held_out_takes_odd_positions_and_at_most_half` (0, 1, 2, 3, 5, 10 episodes; held-out 0, 2, 10).
- `test_prepare_refuses_when_situations_are_below_min_decisions` (2 episodes, default config).
- `test_prepare_refuses_at_max_pending_per_champion`.
- `test_submit_saves_the_challenger_inactive_and_routing_keeps_the_champion` (`list_active` ids == champion; `get(challenger).is_active is False`; ledger `pending`; optimizer provenance kept).
- `test_submit_refuses_non_fix_or_wrong_parent`.
- `test_submit_failure_leaves_the_champion_unchanged` (ledger detached via `detach()` -> `None`, warning, champion active).
- `test_no_pending_challengers_cycle_is_a_no_op` (zero LLM calls, no cycle row, champion unchanged, empty report).
- `test_budget_exhaustion_defers_and_never_promotes` (budget 0: zero LLM calls, `deferred` counted, after 5 cycles `expired`, never `promoted`).
- `test_budget_of_two_judges_one_situation_per_cycle`.
- `test_unresolved_challenger_expires_after_n_cycles` (judge always invalid).
- `test_invalid_judgements_leave_situations_open_for_next_cycle`.
- `test_unreadable_episodes_defer_instead_of_retiring` (`get_by_ids` returns `[]`; then raises).
- `test_missing_episodes_retire_with_insufficient_evidence` (some ids missing, remaining below `min_decisions`).
- `test_plan_mode_episode_is_not_a_comparison_context` (an episode for which `episode_ran_in_plan_mode` is True is never judged).
- `test_two_challengers_top_by_bradley_terry_is_promoted_and_the_other_replaced`.
- `test_top_candidate_that_does_not_beat_the_champion_retires_all_complete`.
- `test_champion_inactive_retires_its_challengers`.
- `test_challenger_missing_is_retired`.
- `test_interrupted_promotion_is_finished_next_cycle` (a `promoting` row with an inactive challenger is finished: challenger active, champion superseded, `promoted`, one event).
- `test_decision_emits_one_durable_event_with_counts_only` (payload keys exactly as `_emit`; no LLM text; a second cycle emits nothing).
- `test_event_emit_failure_keeps_the_decision`.
- `test_build_returns_none_when_disabled`, `test_build_returns_none_without_a_real_ledger` (`MagicMock` store), `test_build_uses_the_verifier_policy_tier`.
- `test_ledger_writes_and_the_event_have_one_owner` (AST over `src/probos`, four enumerations, each asserted as an exact set): (a) modules importing `probos.cognitive.procedure_challenges` = {`cognitive/procedure_store.py`, `cognitive/procedure_judge.py`, `cognitive/procedure_challenger.py`}; (b) attribute reads of `.challenges` occur only in `procedure_challenger.py` (the property's own definition aside); (c) in `procedure_store.py` and `procedure_judge.py` there is no call to `add_challenger`, `set_status`, `record_comparison`, `increment_cycles` or `record_cycle` (`set_status` is also a `task_sessions`/tray method name, so the census is per module, not per name); (d) `EventType.PROCEDURE_CHALLENGE_DECIDED` is referenced only in `procedure_challenger.py`.
- R1 pin (F2): the module's `_PROMPT` regex (`tests/test_ad1326_procedure_challenger.py:70-76`) reads each candidate's first line as `Purpose: routine of <x>`; the candidate now opens with the bare description, so the two candidate patterns become `=== CANDIDATE 1 ===\nroutine of (?P<first>\S+)\n` and `=== CANDIDATE 2 ===\nroutine of (?P<second>\S+)\n` (and the comment above it says "its description"). Grep the other `test_ad1326_*` files for `Purpose`/`Precondition`/`If it fails` before running (none found at revision time).
- R1 (F1) `test_promotion_is_sealed_only_when_the_routing_index_agrees` — real store with Chroma on, a challenger that wins (budget and judge as `test_two_challengers_top_by_bradley_terry_is_promoted_and_the_other_replaced`). Variant `upsert_fails`: the live collection's `upsert` raises during the deciding cycle: after it the ledger says `promoting`, `report.promoted == 0`, no `promoted` event; R2 (R2-2), replacing the old `== []` pin and the SQLite asserts that preceded the branch for this variant: the challenger is active in SQLite, the champion is still active with `superseded_by == ""` (never touched), and `_matched_ids(store) == [CHAMPION_ID]` (the lineage keeps routing); the outage ends; the next cycle makes zero judge calls, ledger `promoted`, one event with reason `won`, the champion inactive with `superseded_by == "ch-a"`, and `find_matching(<champion description>)` returns the challenger and not the champion. Variant `update_fails`: only `update` raises (the champion's deactivation): the same cycle ends `promoted` and `find_matching` returns the challenger only, because the sync rewrote the champion's entry (the reviewer's "both versions" row). R2 variant `champion_index_fails`: `update` and `upsert` raise only for calls whose `ids` contain `CHAMPION_ID` (add an optional `only_ids` to the test helper `_index_outage`; other calls pass through to the real method): after the deciding cycle the challenger is active in SQLite and its entry says active, the champion is inactive in SQLite (`superseded_by == "ch-a"`) while `_index_says_active(store, CHAMPION_ID) is True` (the premise), the ledger says `promoting`, no event, and `_matched_ids(store) == ["ch-a"]` (3g drops the stale champion); the outage ends; the next cycle makes zero judge calls, seals `promoted` with one event, and the champion's entry says inactive.
- R1 (F4) `test_equal_strengths_fall_to_the_creation_time_tie_break` — two challengers of one champion with the probe's id layouts (parametrized as in the ranking test), the older created first with 3 wins and 1 loss, the newer 2 wins and 2 ties (`min_decisions=4`, budget 16): the older is promoted, the newer retired `champion_replaced`, in both layouts. R2 (R2-6): two more parametrizations in which `CHAMPION_ID` (`"champion-1"`) sorts between the challengers' ids: `(older, newer) = ("11111111-0000-4000-8000-000000000000", "dddddddd-0000-4000-8000-000000000000")` and the reverse, with ids `champion-between-older-low` and `champion-between-older-high`; premise asserted first: `min(older, newer) < CHAMPION_ID < max(older, newer)`. Mutation row 25 must fail at least one of them (the probe ids' layouts survived it).
- R1 (F5) `test_overlapping_submits_never_exceed_the_pending_cap` — the reviewer's interleaving: one pending challenger, limit 2; two `prepare` calls both return a plan (premise); both `submit`: the first is recorded `pending`, the second returns `None`, its ledger row is `retired` (`pending_limit`), its procedure row exists and is inactive, one `retired` event with reason `pending_limit`; `pending_count == 2`; `list_active` ids == champion.
- R1 (F3) `test_prepare_never_holds_out_the_source_turn` — six real `Episode`s, `e1` and `e3` with `correlation_id="turn-1"` (both at held-out positions without the parameter): with `source_correlation_id="turn-1"` neither is in `held_out_episodes`, both lead `evolution_episodes` in their recalled order, and `context_episode_ids` starts with them; with `""` or a non-`str` the split is `split_held_out`'s. R2 (R2-4) moves the pinned expectations (`tests/test_ad1326_procedure_challenger.py:562-564, 573-574`): the ceiling is `min(2, 6 // 2) == 2` over all six, the fill order is positions 1, 3, 5, 4, 2, 0 minus the pinned 1 and 3, so held out = `["ep-4", "ep-5"]`, evolution = `["ep-1", "ep-3", "ep-0", "ep-2"]`, contexts = `("ep-1", "ep-3", "ep-4", "ep-5")`, and the ledger records used `("ep-1", "ep-3", "ep-0", "ep-2")` and held out `("ep-4", "ep-5")`.
- R2 (R2-4) `test_split_held_out_fills_around_pinned_episodes` — ten plain objects `e0..e9` with an `id`, `held_out=5`: pinned `{e1}` -> held out `e3, e5, e7, e8, e9` (recalled order), evolution `e1, e0, e2, e4, e6`; pinned `{e1, e3, e5, e7, e9}` -> held out `e0, e2, e4, e6, e8`, evolution `e1, e3, e5, e7, e9`; pinned `{e0}` -> held out `e1, e3, e5, e7, e9`, evolution `e0, e2, e4, e6, e8`; pinned `{e0..e5}` (more than half) -> held out `e6, e7, e8, e9` (short of the ceiling: the documented limit); and for 0..10 episodes and `held_out` 0..6, `pinned=frozenset()` gives exactly the call without `pinned` and the odd-position split of `test_split_held_out_takes_odd_positions_and_at_most_half`.
- R2 (R2-4) `test_source_pinned_recall_reaches_the_same_situations` — parametrized over the source turn's positions in a recall of `PROCEDURE_EVOLUTION_EPISODE_LIMIT` real episodes: `(0,)`, `(1,)`, `(5,)`, `(9,)`, `(1, 3)`, `(1, 3, 5, 7, 9)`, `(0, 2, 4, 6, 8)` carry `correlation_id="turn-1"`. For every `used_contexts` 0..10 and `held_out_episodes` 0..5 (measured as in `test_every_accepted_configuration_can_produce_a_challenge`, `min_decisions=1` through `model_construct`), `prepare(..., source_correlation_id="turn-1")` gives as many situations as `prepare` without it and as `min(used, N - h) + h` with `h = min(held_out, N // 2)` (0 when it returns `None`); no held-out episode is of the turn; the turn's episodes lead `evolution_episodes`. Then the reviewer's six accepted configurations `(0,5,5), (1,5,6), (2,5,7), (3,5,8), (4,5,9), (5,5,10)` validate through `DreamingConfig(...)` and, with the turn at position 1, `prepare` returns a plan with exactly `min_decisions` situations.
- R1 (F7) `test_restored_pair_with_a_completed_promotion_is_recorded_promoted` — the reviewer's pair on a real store and ledger: ledger `pending` with one counted win; `procedures.db` with the challenger active and the champion inactive, `superseded_by` = challenger. One cycle: zero judge calls; ledger `promoted` with `decision_reason` starting `restored_promotion: wins=1`; one `promoted` event with reason `restored_promotion` and `wins == 1`; `find_matching` returns the challenger only; `superseded_episodes` are its source episodes.
- R1 (F7) `test_restored_pending_challenger_that_routes_is_deactivated` — ledger `pending`, challenger and champion both active: after one cycle the challenger is inactive in SQLite and absent from `find_matching`, still `pending` (or decided by the judge as usual), and the champion routes; one WARNING naming the challenger.
- R1 (F7, orchestrator-added) `test_pending_challenger_with_a_stale_index_entry_is_rewritten_from_sqlite` — pending challenger activated, then `deactivate` with the index `update` failing: SQLite says inactive. R2 moves its premise (`tests/test_ad1326_procedure_challenger.py:1329`): routing no longer shows the stale entry (3g), so assert `_index_says_active(store, "ch-a") is True` and `_matched_ids(store) == [CHAMPION_ID]` before the cycle, and `_index_says_active(store, "ch-a") is False` after it (budget 0, still `pending`). It keeps killing the mutant that skips `_reconcile`'s per-cycle sync (row 47).
- R2 (R2-1) `test_retirement_is_sealed_only_when_the_routing_index_agrees` — the reviewer's case: `max_pending_cycles=1`, budget 0; `_pend` then `_activate` the challenger (the activation-only restored pair); premise: `_matched_ids == sorted([CHAMPION_ID, "ch-a"])`. Cycle 1 inside an outage of both `update` and `upsert` (nested `_index_outage`; both `hit` lists contain `"ch-a"`): SQLite says the challenger is inactive; the ledger still says `pending` (`report.retired == 0`, no event); one WARNING containing `is not retired`; `_index_says_active(store, "ch-a") is True` (the stale entry the retry must repair) and `_matched_ids == [CHAMPION_ID]` (3g). Cycle 2 with no outage: `report.retired == 1`; ledger `retired`, `decision_reason` starting `expired:`; `_index_says_active(store, "ch-a") is False`; one event `("ch-a", "retired", "expired")`; `_matched_ids == [CHAMPION_ID]`.
- R1 (F7) `test_retirement_leaves_no_routable_challenger` — the reviewer's next-cycle case: champion inactive and superseded by another id, challenger active and `pending`: retired `champion_inactive`, inactive in SQLite and absent from `find_matching`.
- R1 (F7) `test_ledger_newer_than_procedures_keeps_the_champion_routing` — ledger `promoted`; `procedures.db` with the challenger inactive and the champion active (the opposite interleaving): a cycle changes nothing, emits nothing, and the champion routes (the documented residual, pinned).
- R1 (F8) `test_early_retirement_reports_the_recorded_evidence` — parametrized `champion_inactive` (champion deactivated after one counted win) and `challenger_missing` (challenger row removed with `store.delete` after one counted win), budget 2: the stored `decision_reason` says `wins=1` and `decisions=1`, and the event has `wins == 1`, `decisions == 1` and the recorded `judge_independence`.
- R1 (F6) `test_every_accepted_configuration_can_produce_a_challenge` — grid `used_contexts` 0..12, `held_out_episodes` 0..7, `min_decisions` 0..12: whenever `DreamingConfig(...)` accepts, `prepare` over `PROCEDURE_EVOLUTION_EPISODE_LIMIT` real episodes with an empty real ledger returns a plan with `len(context_episode_ids) >= min_decisions`; and every in-bounds combination it rejects with the can-decide message has fewer situations than `min_decisions` (measured by `prepare` under the same `used_contexts`/`held_out_episodes` with `min_decisions=1`), so the validator neither admits an unreachable configuration nor refuses a reachable one.
- R3 (R3-1) `test_challenger_judged_by_its_optimizers_model_is_never_promoted` — the reviewer's case on a real store and ledger: `llm_model_verifier="gpt-5.1"`; the challenger recorded with `optimizer_model="gpt-5.1"`; the judge double answers every call `answered_tier="verifier"`, `answered_model="gpt-5.1"`, preferring the challenger. Premise: the same rig with `optimizer_model="claude-opus-4-6"` promotes (positive control). Then: no cycle promotes; every comparison row is `counted` False with `same_model` in both judgements; after `procedure_challenger_max_pending_cycles` cycles the row is `retired` with reason `expired` and `decisions=0`; judge calls per cycle never exceed the budget; the champion routes throughout.
- R3 (R3-2) `test_failed_terminal_commit_is_finished_by_the_next_cycle` — the reviewer's case, parametrized `promoted` (a winning challenger) and `retired` (a losing one): the ledger's connection is wrapped test-side so the `commit` after the terminal `UPDATE` raises once; `run_cycle` raises (or logs, per the Step 7d-2 caller) and an independent `sqlite3` reader sees `promoting` (or `pending`); the next healthy cycle reports `promoted == 1` (or `retired == 1`), one decision event, and both the ledger's `get` and the independent reader see the terminal status.
- R3 (R3-5) `test_raw_copy_fallback_pair_never_routes_the_pending_challenger` — the reviewer's interleaving: a real store with its ledger in WAL mode; a challenger `pending` with no comparisons is checkpointed into the ledger's main file (`PRAGMA wal_checkpoint(TRUNCATE)` test-side), then comparisons and `promoting` are committed (premise: they sit in `procedures_challenges.db-wal`) and the challenger is saved active; the two main files are copied with `shutil.copyfile` (the fallback's own call, `backup.py:799`), `procedures.db` first, without `-wal`/`-shm`; a new store started on the copies: premises: its ledger says `pending` with zero comparisons and SQLite says the challenger is active; `find_matching(<champion description>)` returns the champion only; one `run_cycle` (budget 0) deactivates the challenger as `_reconcile` does.
- R3 pin moves (R3-5; each premise read the raw index or SQLite instead, since admission now also refuses `pending`/`retired` challengers): `test_restored_pending_challenger_that_routes_is_deactivated` `:1504` `_matched_ids == sorted([CHAMPION_ID, "ch-a"])` becomes `_index_says_active(store, "ch-a") is True` plus `_matched_ids == [CHAMPION_ID]` (the new veto, before the cycle); `test_retirement_is_sealed_only_when_the_routing_index_agrees` `:1555` the same; `test_retirement_leaves_no_routable_challenger` `:1595` `_matched_ids == ["ch-a"]` becomes `_index_says_active(store, "ch-a") is True` plus `_matched_ids == []`; `test_restored_pair_with_a_completed_promotion_is_recorded_promoted` gains `_matched_ids == []` before the cycle (the documented cost: neither routes until the first dream cycle) and keeps `== ["ch-a"]` after it. `_routed_ids` (`list_active`, SQLite only) assertions do not move.
- R4 pin move (R4-2): `test_restored_pair_with_a_completed_promotion_is_recorded_promoted` — the R3 premise `assert await _matched_ids(store) == []` before the cycle (`tests/test_ad1326_procedure_challenger.py:1564`, with its two-line R3 comment `:1562-1563`) becomes `assert await _matched_ids(store) == ["ch-a"]`, commented: the completed promotion `procedures.db` holds routes before the first dream cycle (D12, R4-2). Everything after the cycle is unchanged. `test_retirement_leaves_no_routable_challenger` (champion superseded by another id) keeps `_matched_ids == []` before its cycle and is now also a negative control of R4-2.
- R5 (R5-2) `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted` — the reviewer's case. `_rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})` (zero budget: a judge would otherwise promote normally and mask the defect); `_pend(rig, "ch-a")`; `_count_win(rig, "ch-a")`; `_activate(store, "ch-a")`; `store.deactivate(CHAMPION_ID, superseded_by="ch-a")`; then an independent `sqlite3` connection on the fixture store's `procedures.db` rewrites the champion's `content_snapshot` to its JSON with `is_active` True and `superseded_by` "" and commits: the state `deactivate` leaves when its snapshot `UPDATE` fails and is swallowed (the real swallow path is pinned by `test_sync_routing_index_publishes_the_activity_column`). Premises, all read independently: the champion's columns `(0, "ch-a")`, its snapshot `is_active` True and `superseded_by` ""; the ledger row `pending`; `_matched_ids(store) == ["ch-a"]`. One `run_cycle()`: `(judge_calls, comparisons, promoted, retired) == (0, 0, 1, 0)`; `rig.llm.requests == []`; the record is `promoted` with `decision_reason` starting `restored_promotion`; `(await store.get("ch-a")).is_active is True`; `_matched_ids(store) == ["ch-a"]`; no WARNING "was routable" is logged.
- R6 note (R6-1): `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted` is unchanged and must still pass: `_reconcile` now reads the champion's columns through `routing_state`, not through a merged `get`. Its `(await store.get("ch-a")).is_active is True` holds under base `get` (`_activate` re-saves, so ch-a's snapshot says active).
- R6 (R6-1) `test_a_restored_promotion_with_a_stale_champion_snapshot_retires_the_other_open_challengers` — as the R5 test (`_rig(..., dreaming={"procedure_challenger_max_judge_calls_per_cycle": 4})` and the rig's judge favouring the challenger, the setup `test_challenger_wins_and_routing_uses_it` uses), but with a second pending challenger `ch-b` (`_pend(rig, "ch-b")`, inactive) holding no comparisons. Stale champion snapshot as in the R5 test. Premises: the champion's columns `(0, "ch-a")`, its snapshot `is_active` True; both rows `pending`. One `run_cycle()`: `(judge_calls, promoted, retired) == (0, 1, 1)`; `ch-a` `promoted` (`restored_promotion`); `ch-b` `retired` with reason `champion_inactive`; `await store.routing_state("ch-b") == (False, "")`; `_matched_ids(store) == ["ch-a"]`. Kills mutation row 82 (a `_contest` gate read from `get`'s snapshot judges `ch-b` against the superseded champion).
- R6 (R6-1) `test_a_promotion_activates_a_challenger_whose_snapshot_says_active` — `_pend(rig, "ch-a")`; `_activate(store, "ch-a")`; `store.deactivate("ch-a")`; then an independent `sqlite3` connection rewrites ch-a's `content_snapshot` to `is_active` True (the state a swallowed snapshot UPDATE leaves); `rig.ledger.set_status("ch-a", "promoting", reason="won: test", expected=("pending",))`. Premises: ch-a's column 0, snapshot True, `(await store.get("ch-a")).is_active is True`. One `run_cycle()`: ch-a `promoted`; `await store.routing_state("ch-a") == (True, "")`; `await store.routing_state(CHAMPION_ID) == (False, "ch-a")`; `_matched_ids(store) == ["ch-a"]`. Kills mutation row 84 (a check read from `get` skips the re-save and seals a promotion that routes nothing).
- R6 helper (R6-1): `_CrashingStore` (`tests/test_ad1326_procedure_challenger.py:211-238`) gains `async def routing_state(self, procedure_id: str) -> tuple[bool, str] | None: return await self._inner.routing_state(procedure_id)`. No other test double implements `ChallengeProcedureStore` (Hidden Pins, R6).

### `tests/test_ad1326_challenger_e2e.py` (Milestone 3 — ACCEPTANCE)
Real `ProcedureStore` on `tmp_path` (Chroma on, as `tests/test_procedure_store.py:156-164`), its real ledger, a real `DreamingEngine` (`MagicMock` router and trust network; real `DreamingConfig()`), a real `ProcedureChallenger` from `build_procedure_challenger` with a seeded `random.Random`, the episodic double holding five real episodes `e0..e4` of the champion's intent, and one LLM double that answers `tier="deep"` with a FIX procedure JSON carrying a marker step, and judge tiers by locating the marker in Candidate 1 or 2.
- `test_challenger_wins_and_routing_uses_it` — `await engine._attempt_procedure_evolution(champion, "FIX: high fallback rate", metrics)` is True; challenger saved inactive; champion still the only `list_active` id; then `run_cycle()` (judge prefers the marker): `promoted == 1`, `judge_calls == 8`; champion inactive with `superseded_by == challenger.id`; `list_active` ids == challenger; `find_matching(<champion description>)` returns the challenger and not the champion; four counted comparison rows, two `held_out`; one `PROCEDURE_CHALLENGE_DECIDED` with `decision == "promoted"`; `superseded_episodes` are the five episodes.
- `test_challenger_loses_and_the_champion_keeps_routing` — judge prefers the champion: `retired == 1`, reason `lost`; champion active; challenger inactive; evidence kept; event `retired`.
- `test_held_out_episodes_never_reach_the_rewrite_prompt_and_are_judged` — the deep request's prompt contains `e0`, `e2`, `e4` and neither `e1` nor `e3`; the judge prompts contain the `user_input` of `e1` and `e3`.
- `test_derived_evolution_is_unchanged_under_the_challenger_flow` — `"DERIVED: ..."` diagnosis: the result is saved active, the parent stays active, the ledger is empty.
- `test_flag_off_restores_immediate_supersession` — `procedure_challenger_enabled=False`: `build_procedure_challenger` returns `None`; the engine built without it deactivates the parent with `superseded_by` on save (the proactive site; a near-miss fallback FIX never superseded, so the name covers only the sites that did); no ledger rows.
- R1 (F3) `test_fallback_rewrite_prompt_quotes_no_held_out_turn` — the reviewer's case through the real Step 7d (`_process_fallback_learning`): five episodes `e0..e4`, `e1` with `correlation_id="turn-1"`; the queued `PROCEDURE_FALLBACK_LEARNING` payload has the producer's keys (`cognitive_agent.py:7624-7635`), `correlation_id="turn-1"` and `llm_response="OBSERVATION_1"`. One challenger is recorded; `e1` is not in its `held_out_episode_ids` and is the first of its `used_episode_ids`; no held-out episode has `correlation_id == "turn-1"`; the deep request's prompt contains `OBSERVATION_1` and the `e1` episode block.

### `tests/test_ad1326_dreaming_challenger.py` (Milestone 3)
- `test_step_7d2_runs_the_cycle_and_expires_superseded_sources` (`dream_cycle` with a stub challenger whose report carries two episodes; `update_episode_validity` called for both; reuse the engine helper pattern of `tests/test_ad1156_plan_mode_learning.py`).
- `test_step_7d2_failure_is_logged_and_the_cycle_continues` (stub raises; WARNING; `dream_cycle` returns a report).
- `test_degraded_scan_fix_becomes_a_challenger` (site 7b: appended to `procedures`, counted, parent active).
- `test_fallback_fix_becomes_a_challenger_for_failure_and_near_miss` (site 7d: both `execution_failure` and a near-miss type; parent active; result inactive).
- `test_fallback_without_episodes_skips_the_rewrite_under_challengers` (no LLM call; cooldown recorded).
- `test_prepare_refusal_records_the_cooldown` (sites 7b and proactive).
- `test_shutdown_consolidation_never_runs_the_challenger_cycle` (`consolidate_for_shutdown` leaves the stub's `run_cycle` uncalled).
- R1 (F6) `test_producers_cap_recall_at_the_shared_limit` — parametrized `7b`, `proactive`, `7d`: `monkeypatch.setattr("probos.cognitive.dreaming.PROCEDURE_EVOLUTION_EPISODE_LIMIT", 4)`, eight recalled real episodes, a recording challenger stub: `prepare` receives exactly the first four at each site.
- R3 (R3-4) `test_step_7d_recalls_the_shared_limit_through_the_real_helper` — the reviewer's case through the real `_process_fallback_learning` and the real `_recall_evidence_by_intent`: ten recallable episodes of one intent (one of them the source turn) in the episodic double, whose `recall_by_intent` keeps the real default (premise: `inspect.signature(EpisodicMemory.recall_by_intent).parameters["k"].default == 5` and the double's default equals it); `DreamingConfig(procedure_challenger_used_contexts=0, procedure_challenger_held_out_episodes=5, procedure_challenger_min_decisions=5)`; a real challenger and ledger. One rewrite request, one `pending` challenge with five held-out ids (the cooldown is recorded after every rewrite, `dreaming.py` "Record attempt regardless of outcome", so it does not separate the two outcomes); the double saw `k == PROCEDURE_EVOLUTION_EPISODE_LIMIT`. Fails at the frozen candidate (rewrite calls 0, no challenge).

---

## Mutation table

Author's table, **not executed** (the Architect cannot run tests). Milestone 3's Builder runs it once on the finished tree as the campaign of record (base tree, file sha256s, results), per `.github/copilot-instructions.md` mutation rules: baseline first, in place with `.mutbak`, single-line anchors, timeout = INVALID. Each anchor is a single line unique in its file after the build.

| # | File | Anchor (exact line) | Replacement | Expected killer |
|---|---|---|---|---|
| 1 | `procedure_ranking.py` | `            wins[0] += 0.5` | `            wins[0] += 1.0` | `test_bradley_terry_star_with_ties_counts_half_each` |
| 2 | `procedure_ranking.py` | `        wins = counts.setdefault((a, b), [prior, prior])` | `        wins = counts.setdefault((a, b), [0.0, 0.0])` | `test_bradley_terry_candidate_that_never_won_is_finite` |
| 3 | `procedure_ranking.py` | `        scale = strength[reference]` | `        scale = 1.0` | `test_bradley_terry_non_star_still_iterates` (R1: a star no longer reaches the iteration, so the star test cannot kill this row) |
| 4 | `procedure_ranking.py` | `    return wins / decisions > 0.5 + margin` | `    return wins / decisions >= 0.5 + margin` | `test_beats_champion_requires_share_strictly_above_threshold` |
| 5 | `procedure_challenges.py` | `    cleaned = value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")` | `    cleaned = value.replace("\x00", "")` | `test_bounded_text_removes_nul_replaces_surrogate_and_cuts`; `test_record_comparison_persists_bounded_reason_with_surrogate_and_nul` |
| 6 | `procedure_store.py` | `                await challenges_db.close()` | `                pass` | `test_procedure_store_stop_closes_the_ledger` |
| 6b | `procedure_store.py` | `            ledger = ProcedureChallengeLedger(self._challenges_db)` | `            ledger = ProcedureChallengeLedger(self._challenges_db); self._challenges_db = None` | `test_last_resort_close_reaches_the_ledger_connection`; `test_procedure_store_stop_closes_the_ledger` |
| 6c | `procedure_store.py` | `                    await opened.close()` | `                    pass` | `test_ledger_start_failure_leaves_the_store_running` |
| 7 | `procedure_judge.py` | `    return "tie"  # the orders disagree: position decided it, so nobody wins` | `    return one` | `test_position_biased_judge_yields_only_ties`; `test_combine_orders_table` |
| 8 | `procedure_judge.py` | `        second_verdict = await self._ask(policy, situation, rendered, second, first)` | `        second_verdict = await self._ask(policy, situation, rendered, first, second)` | `test_each_situation_is_asked_in_both_orders`; `test_position_biased_judge_yields_only_ties` |
| 9 | `procedure_judge.py` | `            or all(j.judge.independence == "independent" for j in (first_verdict, second_verdict))` | `            or True` | `test_fallback_judgement_is_recorded_not_counted_when_an_independent_judge_is_configured` |
| 10 | `procedures.py` | `PROCEDURE_REWRITE_TIER = "deep"` | `PROCEDURE_REWRITE_TIER = "standard"` | `test_rewrite_requests_use_deep_with_a_standard_floor` |
| 11 | `procedures.py` | `PROCEDURE_REWRITE_MIN_TIER = "standard"` | `PROCEDURE_REWRITE_MIN_TIER = None` | `test_rewrite_requests_use_deep_with_a_standard_floor` |
| 12 | `procedure_challenger.py` | `    held_positions = set(eligible[:count])` | `    held_positions = set()` | `test_split_held_out_takes_odd_positions_and_at_most_half`; `test_held_out_episodes_never_reach_the_rewrite_prompt_and_are_judged` |
| 13 | `procedure_challenger.py` | `        challenger = replace(procedure, is_active=False)` | `        challenger = replace(procedure, is_active=True)` | `test_submit_saves_the_challenger_inactive_and_routing_keeps_the_champion`; `test_challenger_loses_and_the_champion_keeps_routing` |
| 14 | `procedure_challenger.py` | `            await self._store.deactivate(record.champion_id, superseded_by=record.challenger_id)` | `            pass` | `test_challenger_wins_and_routing_uses_it` |
| 15 | `procedure_challenger.py` | `            if counts.calls + JUDGE_CALLS_PER_CONTEXT > budget:` | `            if False:` | `test_budget_exhaustion_defers_and_never_promotes` |
| 16 | `procedure_challenger.py` | `            if cycles >= self._config.procedure_challenger_max_pending_cycles:` | `            if False:` | `test_unresolved_challenger_expires_after_n_cycles` |
| 17 | `procedure_challenger.py` | `        if not found:  # nothing came back: unreadable this cycle, not missing` | `        if False:` | `test_unreadable_episodes_defer_instead_of_retiring` |
| 18 | `procedure_challenger.py` | `        return {ep.id: ep for ep in found if not episode_ran_in_plan_mode(ep)}` | `        return {ep.id: ep for ep in found}` | `test_plan_mode_episode_is_not_a_comparison_context` |
| 19 | `procedure_challenger.py` | `            self._emit_event_fn(EventType.PROCEDURE_CHALLENGE_DECIDED, payload)` | `            pass` | `test_decision_emits_one_durable_event_with_counts_only`; `test_routed_member_has_an_emit_call_passing_its_enum_member[PROCEDURE_CHALLENGE_DECIDED]` |
| 20 | `dreaming.py` | `            if self._procedure_challenger is not None and diagnosis.startswith("FIX:"):  # AD-1326 step 7b` | `            if False:` | `test_degraded_scan_fix_becomes_a_challenger` |
| 21 | `dreaming.py` | `        if self._procedure_challenger is not None and diagnosis.startswith("FIX:"):  # AD-1326 proactive` | `        if False:` | `test_challenger_wins_and_routing_uses_it`; `test_challenger_loses_and_the_champion_keeps_routing` |
| 22 | `dreaming.py` | `                list(plan.evolution_episodes) if plan is not None else fresh_episodes,  # AD-1326 proactive` | `                fresh_episodes,  # AD-1326 proactive` | `test_held_out_episodes_never_reach_the_rewrite_prompt_and_are_judged` |
| 23 | `dreaming.py` | `                if self._procedure_challenger is not None:  # AD-1326 step 7d` | `                if False:` | `test_fallback_fix_becomes_a_challenger_for_failure_and_near_miss` |
| 24 | `dreaming.py` | `                await self._expire_superseded_episode_sources(list(challenge_report.superseded_episodes))` | `                pass` | `test_step_7d2_runs_the_cycle_and_expires_superseded_sources` |
| 25 | `procedure_ranking.py` | `    if all(reference in pair for pair in counts):` | `    if False:` | `test_bradley_terry_star_equal_records_are_exactly_equal`; `test_equal_strengths_fall_to_the_creation_time_tie_break[champion-between-older-low]` or `[champion-between-older-high]` (R2-6) |
| 26 | `procedure_ranking.py` | `    if all(reference in pair for pair in counts):` | `    if True:` | `test_bradley_terry_cycle_is_uniform`; `test_bradley_terry_non_star_still_iterates` |
| 27 | `procedure_challenges.py` | `                if count >= max_pending:` | `                if False:` | `test_add_challenger_enforces_the_pending_cap_atomically`; `test_overlapping_submits_never_exceed_the_pending_cap` |
| 28 | `procedure_store.py` | `        return self._save_to_chroma(procedure)` | `        return True` | `test_sync_routing_index_reports_a_failed_index_write`; `test_promotion_is_sealed_only_when_the_routing_index_agrees[upsert_fails]` |
| 29 | `procedure_judge.py` | `        head = f"**Step {step.step_number} [{role}]:**" if role else f"**Step {step.step_number}:**"` | `        head = f"**Step {step.step_number}:**"` | `test_render_candidate_is_the_replay_body`; `test_render_candidate_distinguishes_a_role_only_repair` |
| 30 | `procedure_challenger.py` | `        pinned_ids = {ep.id for ep in usable if source and ep.correlation_id == source}` | `        pinned_ids: set[str] = set()` | `test_prepare_never_holds_out_the_source_turn`; `test_fallback_rewrite_prompt_quotes_no_held_out_turn` |
| 31 | `procedure_challenger.py` | `        if record.status != "pending":` | `        if False:` | `test_overlapping_submits_never_exceed_the_pending_cap` |
| 32 | `procedure_challenger.py` | `                await self._retire(record, "champion_inactive", recorded, counts)` | `                await self._retire(record, "champion_inactive", Tally(), counts)` | `test_early_retirement_reports_the_recorded_evidence[champion_inactive]` |
| 33 | `procedure_challenger.py` | `            await self._retire(record, "challenger_missing", missing, counts)` | `            await self._retire(record, "challenger_missing", Tally(), counts)` | `test_early_retirement_reports_the_recorded_evidence[challenger_missing]` |
| 34 | `procedure_challenger.py` | `            if champion_state == (False, record.challenger_id):` (anchor moved in review round 6) | `            if False:` | `test_restored_pair_with_a_completed_promotion_is_recorded_promoted`; `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted` |
| 35 | `procedure_challenger.py` | `            await self._store.deactivate(record.challenger_id)` | `            pass` | `test_restored_pending_challenger_that_routes_is_deactivated`; `test_retirement_leaves_no_routable_challenger` |
| 36 | `procedure_challenger.py` | `        if not await self._store.sync_routing_index(challenger.id):` | `        if False:` | `test_promotion_is_sealed_only_when_the_routing_index_agrees[upsert_fails]` (R2-2: the champion would be deactivated during the outage) |
| 37 | `dreaming.py` | `                        parent, fresh_episodes, source_correlation_id=event.get("correlation_id", ""),` | `                        parent, fresh_episodes,` | `test_fallback_rewrite_prompt_quotes_no_held_out_turn` |
| 38 | `dreaming.py` | `            fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]` (12 spaces, Step 7b) | `            fresh_episodes = fresh_episodes[:10]` | `test_producers_cap_recall_at_the_shared_limit[7b]` |
| 39 | `dreaming.py` | `        fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]` (8 spaces, proactive) | `        fresh_episodes = fresh_episodes[:10]` | `test_producers_cap_recall_at_the_shared_limit[proactive]` |
| 40 | `dreaming.py` | `                fresh_episodes = fresh_episodes[:PROCEDURE_EVOLUTION_EPISODE_LIMIT]` (16 spaces, Step 7d) | `                fresh_episodes = fresh_episodes[:10]` | `test_producers_cap_recall_at_the_shared_limit[7d]` |
| 41 | `procedure_challenger.py` | `    order = [*range(1, n, 2), *reversed(range(0, n, 2))]` | `    order = [*range(1, n, 2)]` | `test_split_held_out_fills_around_pinned_episodes`; `test_source_pinned_recall_reaches_the_same_situations` |
| 42 | `procedure_challenger.py` | `    count = max(0, min(held_out, n // 2))` | `    count = max(0, min(held_out, (n - len(pinned)) // 2))` | `test_split_held_out_fills_around_pinned_episodes`; `test_source_pinned_recall_reaches_the_same_situations` (the R2-4 defect) |
| 43 | `procedure_challenger.py` | `        if not await self._store.sync_routing_index(record.champion_id):` | `        if False:` | `test_promotion_is_sealed_only_when_the_routing_index_agrees[champion_index_fails]` |
| 44 | `procedure_challenger.py` | `        if not await self._store.sync_routing_index(record.challenger_id):  # R2-1: sealed only when routing agrees` | `        if False:` | `test_retirement_is_sealed_only_when_the_routing_index_agrees` |
| 45 | `procedure_store.py` | `            FROM procedure_records WHERE id = ? AND is_active = 1""",` | `            FROM procedure_records WHERE id = ?""",` | `test_find_matching_admits_only_rows_active_in_sqlite`; `test_promotion_is_sealed_only_when_the_routing_index_agrees[champion_index_fails]` (R3: the retirement test no longer kills it — its challenger is `pending` in the ledger, which R3-5 refuses on its own) |
| 46 | `procedure_challenger.py` | `        evolution, held_out = split_held_out(usable, cfg.procedure_challenger_held_out_episodes, pinned=pinned_ids)` | `        evolution, held_out = split_held_out(usable, cfg.procedure_challenger_held_out_episodes)` | `test_prepare_never_holds_out_the_source_turn`; `test_fallback_rewrite_prompt_quotes_no_held_out_turn` |
| 47 | `procedure_challenger.py` | `        if not await self._store.sync_routing_index(record.challenger_id):` (no trailing comment: `_reconcile`) | `        if False:` | `test_pending_challenger_with_a_stale_index_entry_is_rewritten_from_sqlite` |
| 48 | `procedure_store.py` | `                str(self._data_dir / "procedures_challenges.db")` | `                str(self._data_dir / "procedure_challenges.db")` | `test_backup_copies_the_ledger_after_procedures_db` |
| 49 | `procedure_judge.py` | `        extra = (optimizer_model,) if type(optimizer_model) is str and optimizer_model else ()` | `        extra = ()` | `test_judgement_by_the_optimizers_model_is_not_independent`; `test_challenger_judged_by_its_optimizers_model_is_never_promoted` |
| 50 | `procedure_judge.py` | `        policy = replace(self._policy, crew_models=(*self._policy.crew_models, *extra))` | `        policy = self._policy` | `test_judgement_by_the_optimizers_model_is_not_independent` |
| 51 | `procedure_challenger.py` | `                optimizer_model=record.optimizer_model,  # R3-1: the rewrite's own model is not an independent judge` | `                optimizer_model="",` | `test_challenger_judged_by_its_optimizers_model_is_never_promoted` |
| 52 | `procedure_challenges.py` | `        await db.execute("ROLLBACK")` (8 spaces: `_roll_back`, R4) | `        pass` | `test_failed_ledger_write_is_rolled_back`; `test_failed_terminal_commit_is_finished_by_the_next_cycle`; `test_a_cancelled_begin_is_rolled_back_after_it_takes_effect` |
| 53 | `procedure_challenges.py` | `        except BaseException as exc:` (R4 anchor) | `        except Exception as exc:` | `test_cancelled_ledger_write_is_rolled_back`; `test_a_cancelled_begin_is_rolled_back_after_it_takes_effect` |
| 54 | `procedure_challenges.py` | `            await db.commit()` (12 spaces: `_write_transaction`; `start`'s is at 8) | `            pass` | `test_failed_ledger_write_is_rolled_back` (its healthy retry must be visible to the independent reader) |
| 55 | `procedure_store.py` | `            procedure.is_active = state[0]  # R3-3/R6-1: publish the column admission reads` (withdrawn in round 5, reinstated on this anchor in round 6) | `            pass` | `test_sync_routing_index_publishes_the_activity_column` |
| 56 | `procedure_store.py` | `            if record is not None and record.bars_routing:` | `            if False:` | `test_find_matching_refuses_a_challenger_the_ledger_holds_undecided`; `test_raw_copy_fallback_pair_never_routes_the_pending_challenger` |
| 57 | `procedure_challenges.py` | `        return self.status in ("pending", "retired")` | `        return self.status == "pending"` | `test_find_matching_refuses_a_challenger_the_ledger_holds_undecided[retired]`; `test_challenge_record_bars_routing_table` |
| 58 | `procedure_challenges.py` | `        return self.status in ("pending", "retired")` | `        return self.status == "retired"` | `test_find_matching_refuses_a_challenger_the_ledger_holds_undecided[pending]`; `test_raw_copy_fallback_pair_never_routes_the_pending_challenger` |
| 59 | `procedure_store.py` | `                record = None` | `                return None` | `test_find_matching_without_a_readable_ledger_admits_on_sqlite[read_fails]` |
| 60 | `dreaming.py` | `            await self.episodic_memory.recall_by_intent(intent_type, k=PROCEDURE_EVOLUTION_EPISODE_LIMIT)` | `            await self.episodic_memory.recall_by_intent(intent_type)` | `test_step_7d_recalls_the_shared_limit_through_the_real_helper` |
| 61 | `procedure_challenges.py` | `        if "no transaction is active" in str(exc):` | `        if False:` | `test_a_cancelled_begin_that_never_takes_effect_logs_nothing`; `test_a_cancelled_commit_that_still_commits_is_durable_and_logs_nothing` |
| 62 | `procedure_challenges.py` | `                begin_refused = True` | `                pass` | `test_a_write_that_cannot_begin_issues_no_rollback_and_logs_nothing` |
| 63 | `procedure_challenges.py` | `            if begin_refused:` | `            if True:` | `test_a_cancelled_begin_is_rolled_back_after_it_takes_effect`; `test_cancelled_ledger_write_is_rolled_back`; `test_failed_ledger_write_is_rolled_back` |
| 64 | `procedure_challenges.py` | `                    await asyncio.shield(cleanup)` | `                    await cleanup` | `test_a_second_cancellation_during_cleanup_still_rolls_back` |
| 65 | `procedure_challenges.py` | `                raise asyncio.CancelledError() from exc` | `                raise` | `test_a_cancellation_during_rollback_waits_for_it_and_is_delivered` |
| 66 | `procedure_store.py` | `                if record.status != "pending":` | `                if False:` | `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[retired_completed]` |
| 67 | `procedure_store.py` | `                if await self.routing_state(record.champion_id) != (False, procedure_id):  # R6-1: _reconcile's predicate` (anchor moved in review round 6; rows 67-69 share it and run separately) | `                if await self.routing_state(record.champion_id) != (False, ""):  # R6-1: _reconcile's predicate` | `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[completed]`; `test_flag_off_routes_a_restored_completed_promotion`; `test_restored_pair_with_a_completed_promotion_is_recorded_promoted` (R4 premise) |
| 68 | `procedure_store.py` | the row 67 anchor | `                if (await self.routing_state(record.champion_id) or (True, ""))[0]:  # R6-1: _reconcile's predicate` | `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[superseded_by_another]`; `test_retirement_leaves_no_routable_challenger` |
| 69 | `procedure_store.py` | the row 67 anchor | `                if False:  # R6-1: _reconcile's predicate` | `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[champion_active]`; `test_find_matching_refuses_a_challenger_the_ledger_holds_undecided[pending]`; `test_raw_copy_fallback_pair_never_routes_the_pending_challenger` |
| 70 | `procedure_judge.py` | `        if judge.independence == "independent" and baseline.independence != "independent":` | `        if False:` | `test_optimizer_model_never_raises_a_label[empty_basis]` |
| 71 | `procedure_judge.py` | `            judge = baseline  # R4-3: adding the optimizer's model never raises a label` | `            pass` | `test_optimizer_model_never_raises_a_label[empty_basis]` |
| 72 | — | withdrawn in review round 6: R6-1 withdraws 3f2, so `get` has no such line; its property is rows 79, 80 and 34's | — | — |
| 73 | — | withdrawn in review round 6 (as row 72) | — | — |
| 74 | `procedure_challenges.py` | `        async with self._lock:  # R5-1 (get): committed rows while cleanup succeeds` (anchor moved in review round 6, R6-2) | `        if True:  # R5-1 (get): committed rows while cleanup succeeds` | `test_every_public_ledger_read_waits_for_an_in_flight_write[get]`; `test_a_read_during_a_rolled_back_write_returns_the_committed_row`; `test_find_matching_waits_for_a_rolled_back_promotion_and_routes_the_champion` |
| 75 | `procedure_challenges.py` | `        async with self._lock:  # R5-1 (list_by_status)` | `        if True:  # R5-1 (list_by_status)` | `test_every_public_ledger_read_waits_for_an_in_flight_write[list_by_status]` |
| 76 | `procedure_challenges.py` | `        async with self._lock:  # R5-1 (pending_count)` | `        if True:  # R5-1 (pending_count)` | `test_every_public_ledger_read_waits_for_an_in_flight_write[pending_count]` |
| 77 | `procedure_challenges.py` | `        async with self._lock:  # R5-1 (comparisons)` | `        if True:  # R5-1 (comparisons)` | `test_every_public_ledger_read_waits_for_an_in_flight_write[comparisons]` |
| 78 | `procedure_challenges.py` | `        async with self._lock:  # R5-1 (recent_cycles)` | `        if True:  # R5-1 (recent_cycles)` | `test_every_public_ledger_read_waits_for_an_in_flight_write[recent_cycles]` |
| 79 | `procedure_store.py` | `            "SELECT is_active, superseded_by FROM procedure_records WHERE id = ?",` | `            "SELECT 1, superseded_by FROM procedure_records WHERE id = ?",` | `test_routing_state_reads_the_columns_not_the_snapshot`; `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[completed]`; `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted` |
| 80 | `procedure_store.py` | `        return bool(row[0]), row[1] or ""` | `        return bool(row[0]), ""` | `test_routing_state_reads_the_columns_not_the_snapshot`; `test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds[completed]`; `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted` |
| 81 | `procedure_challenger.py` | `        champion_state = await self._store.routing_state(champion_id)` | `        champion_state = (bool(champion and champion.is_active), getattr(champion, "superseded_by", ""))` (round 5's source, `get`'s snapshot) | `test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted`; `test_a_restored_promotion_with_a_stale_champion_snapshot_retires_the_other_open_challengers` |
| 82 | `procedure_challenger.py` | `        if champion is None or champion_state is None or not champion_state[0]:` | `        if champion is None or not champion.is_active:` | `test_a_restored_promotion_with_a_stale_champion_snapshot_retires_the_other_open_challengers` |
| 83 | `procedure_challenger.py` | `        if state[0]:  # R6-1: the challenger's column` | `        if False:  # R6-1: the challenger's column` | `test_restored_pending_challenger_that_routes_is_deactivated`; `test_restored_pair_with_a_completed_promotion_is_recorded_promoted` |
| 84 | `procedure_challenger.py` | `        if state is None or not state[0]:  # R6-1: activate unless the column says active` | `        if not challenger.is_active:  # R6-1: activate unless the column says active` | `test_a_promotion_activates_a_challenger_whose_snapshot_says_active` |
| 85 | `procedure_challenger.py` | `        if champion_state is not None and champion_state[0]:  # R6-1: the champion's column` | `        if False:  # R6-1: the champion's column` | `test_challenger_wins_and_routing_uses_it` |
| 86 | `procedure_store.py` | `        state = await self.routing_state(procedure_id)` | `        state = None` | `test_sync_routing_index_publishes_the_activity_column` |

Notes. Row 22 at the 7b and 7d sites is the same expression with a different comment, which is what keeps each anchor unique. Row 2 makes a never-won candidate's strength 0, and the next sweep divides by it: an error counts as killed only if the named test fails on that error, not on a timeout. Row 21 reaches the proactive site through the e2e tests, which call `_attempt_procedure_evolution` directly. Revision 2026-10-13 (D1b): row 6's anchor moved from `await ledger.stop()` to the store's own close of `_challenges_db`; rows 6b (the store drops its direct reference: the first draft's shape, killed by the last-resort test) and 6c (the failed-open path leaks the connection) are new. No other row changes.

Review round 1 (2026-10-13). Rows 25-40 are new; row 3's killer moved (a star returns before the iteration). Rows 38-40 are whole-line anchors told apart by indentation only (12, 8, 16 spaces); match whole lines, not substrings. Rows 25 and 26 share an anchor and run separately. Every file the earlier campaign of record pinned changes in this revision (`procedures.py` only in a docstring), so the whole table reruns once on the revised tree as the new campaign of record. F6's validator has no row: the tightened bounds and the exact formula each keep every accepted configuration reachable, so any single-line mutant of either is equivalent by design; `test_every_accepted_configuration_can_produce_a_challenge` pins the property, and rows 38-40 pin the producers' use of the shared limit.

Review round 2 (2026-10-13). Rows 41-48 are new; row 12's anchor moved (`split_held_out` rewritten), row 36's anchor moved (the challenger's sync is now its own line, before the champion is touched) and row 25 names the R2-6 parametrizations. Rows 44 and 47 differ only by row 44's trailing comment: match whole lines. Row 30 (`pinned_ids` emptied) keeps its anchor. R2-5 changes docstrings only and has no row. `procedure_challenger.py`, `procedure_store.py` and `procedure_judge.py` change again, so the whole table reruns once on the revised tree as the campaign of record; a surviving row 25 is a hard stop (report the strengths of both R2-6 layouts under the mutant).

Review round 3 (2026-10-13). Rows 49-60 are new; row 8's anchor moved (`_ask` takes the per-call `policy`); row 45 lost one killer (named in the row). Rows 57 and 58 share an anchor and run separately. Equivalent by design, no row: `_write_transaction`'s `begun` flag (dropping it only adds a failing `ROLLBACK` after a failed `BEGIN`, which is caught and logged). `procedure_judge.py`, `procedure_challenges.py`, `procedure_challenger.py`, `procedure_store.py` and `dreaming.py` change, so the whole table (1-60, with 6-6c) reruns once on the revised tree as the new campaign of record, including the orchestrator's `test_repeated_promotion_does_not_deactivate_the_champion_again` row if it is carried in this table.

Review round 4 (2026-10-13). Rows 61-71 are new; rows 52 and 53 moved their anchors (the `ROLLBACK` now lives in `_roll_back` at 8 spaces; the handler binds `exc`) and gained the R4-1 killer. Round 3's "equivalent by design" note on the `begun` flag is withdrawn: its successor `begin_refused` is row 62 (a rollback after a refused `BEGIN` now logs nothing only when SQLite says "no transaction is active", and the orchestrator's test arms a different error on `ROLLBACK`). Row 64 depends on the event-loop order the test sets up (`cancel; sleep(0); cancel` reaches the writer before the cleanup task's first step); if it survives, report the order observed rather than reshaping the code. Row 68 keeps the statement's two parameters. Rows 70 and 71 have one killer each by design: the `empty_basis` case is the only raised label (D12, R4-3). `procedure_challenges.py`, `procedure_store.py` and `procedure_judge.py` change, so the rows of those three files rerun on the revised tree (`procedure_challenges.py`: 5, 27, 52-54, 57, 58, 61-65; `procedure_store.py`: 6, 6b, 6c, 28, 45, 48, 55, 56, 59, 66-69; `procedure_judge.py`: 7-9, 29, 49, 50, 70, 71); the rows of `procedure_challenger.py`, `dreaming.py`, `procedures.py` and `procedure_ranking.py` keep the round-3 campaign of record if those files' sha256 match it.

Review round 5 (2026-10-14). Rows 72-78 are new; row 55 is withdrawn (its line is deleted). Rows 74-78 are told apart only by their trailing comments: match whole lines. Row 72's killers include the R3-3 test, whose `sync_routing_index` now takes the column through `get`. `procedure_challenges.py` and `procedure_store.py` change (the latter also loses R3-3's SELECT, which moves no other row's anchor: rows 6, 6b, 6c, 28, 45, 48, 56, 59, 66-69 anchor elsewhere), so their rows rerun on the revised tree (`procedure_challenges.py`: 5, 27, 52-54, 57, 58, 61-65, 74-78; `procedure_store.py`: 6, 6b, 6c, 28, 45, 48, 56, 59, 66-69, 72, 73); every other file keeps its campaign of record if its sha256 matches it. A surviving row 74 is a hard stop (report whether the read finished before the gate was set).

Review round 6 (2026-10-14). Rows 79-86 are new; rows 72 and 73 are withdrawn (3f2 withdrawn); row 55 is reinstated on `sync_routing_index`'s new override line; rows 34, 67-69 and 74 moved their anchors (67-69 now share one anchor and run separately; 74's comment changed, R6-2). Indentation: rows 81, 82, 83, 84, 85 and 86 are 8 spaces; row 34 is 12; rows 67-69 are 16; row 55 is 12; rows 79 (12) and 80 (8) are in `routing_state`. Row 86's anchor `        state = await self.routing_state(procedure_id)` is unique in `procedure_store.py` (`_get_index_row` calls `routing_state(record.champion_id)` inline; `_complete_promotion`'s `state = await self._store.routing_state(record.challenger_id)` is in another file). Row 81's mutant needs `champion` bound, which it is (the line above). A surviving row 82 or 84 is a hard stop: report the cycle's counts and both rows' columns. `procedure_store.py` and `procedure_challenger.py` change, so their rows rerun on the revised tree (`procedure_store.py`: 6, 6b, 6c, 28, 45, 48, 55, 56, 59, 66-69, 79, 80, 86; `procedure_challenger.py`: every row of that file, 34 and 81-85 included); `procedure_challenges.py` reruns row 74 only (one comment and one docstring changed); every other file keeps its campaign of record if its sha256 matches it.

---

## Milestones

| M | Fresh Builder | Sections | New tests | Pins | Gate |
|---|---|---|---|---|---|
| 1 | ranking, ledger, store lifecycle | 1, 2, 3a-3g, 4 | `test_ad1326_procedure_ranking.py`, `test_ad1326_procedure_ledger.py` | none (store registry, backup coverage and the 1419 rollback tests must pass unchanged) | M1 gate above |
| 2 | judge, rewrite tier, config | 5, 6a-6i, 7a-7b, 8a-8d | `test_ad1326_procedure_judge.py`, `test_ad1326_rewrite_tier.py`, `test_ad1326_config.py` | 8a, 8b, 8c, regenerated baseline and reference | M2 gate above |
| 3 | event, service, dream wiring, trackers | 9, 10, 11a-11d, 12, 13a-13j (with 13a-2, 13a-3 and 13e-0), 14a-14b, 15 | `test_ad1326_procedure_challenger.py`, `test_ad1326_challenger_e2e.py`, `test_ad1326_dreaming_challenger.py` | 11a-11d, 13h-13i (in the same commit as 13c), 13j (in the same commit as 13a-3) | M3 gate above plus `tests/test_ad579c_validity_dream.py`, then the mutation campaign of record |

Sections 9-11 land in the same commit as Section 12: the producer test (`test_producer_table_names_exactly_the_routed_members`) requires `cognitive/procedure_challenger.py` to exist once the member is DURABLE.

**Executed premise (was hard stop 1).** The promotion re-save works on a real store: champion saved active, challenger saved inactive with `parent_procedure_ids=[champion]`, then `store.save(replace(challenger, is_active=True))` and `store.deactivate(champion, superseded_by=challenger)` both succeed, lineage intact, champion inactive with `superseded_by == challenger` (orchestrator probe `probe_ad1326_promotion_resave.py`, 2026-10-13, `logs/architect/evidence-ad1326-diag.md`). No FOREIGN KEY error; no `ProcedureStore` method is needed for the re-save. (Review round 1 adds one, `sync_routing_index`, for the semantic index the re-save's `save`/`deactivate` can silently fail to update: D9, F1.)

**Hard stops for the Builder.** (1) `tests/test_issue1419_failed_start_rollback.py` fails in either variant of `test_a_real_boot_is_rolled_back_when_every_component_that_can_stop_raises`, or `test_last_resort_close_reaches_the_ledger_connection` fails: the ledger's connection is not where BF-882 reaches it; stop and report, do not change `shutdown.py` or the 1419 pins. (2) `check_config_facade.py --update-baseline` changes any model other than `DreamingConfig`/`SystemConfig`. (3) `check_architecture_principles.py --check` reports any srp-size, layer-import, db-connect or unowned-task difference; `architecture-baseline.yaml` must not change (its sha is pinned in `tests/test_ad1324_srp_layout.py`). (4) Any existing test outside the pins named here fails (executed baseline for the first draft: 16 failures, all now pinned or designed out: 15 by 13h-13i, 1 by D1b).

---

## Do Not Build

- No fine-tuning or distillation of model weights (MASS's outer loop).
- No general workflow-search engine; no change to procedure compilation levels (AD-535); nothing for elastic team recipes (AD-1290/#1337).
- No change to the `procedure_records`/`procedure_lineage_parents` schema, `config/system.yaml`, `docs/development/architecture-baseline.yaml`, `docs/development/store-baseline.yaml`, or commercial-boundary material.
- No `DreamReport` field, no API route, no HXI panel (an operator view of pending challengers is a follow-up AD).
- No change to DERIVED persistence (parents stay active), to the evolution gate or to extraction tiers.
- No fix of the pre-existing defects in Prior Art and Blind Spots (6, 7, 9, 10); they are separate BFs. In particular `save`/`deactivate` keep their silent index failure for every other caller (9; 3g only stops a stale active entry from being admitted), rewritten procedure text keeps its current parsing (10), and `MAX_CANDIDATE_CHARS` keeps cutting long candidates (11).
- No change to `BackupService` or `discover`; the ledger's file name alone sets its copy order (D10, R2-3). Its raw-copy fallback (`backup.py:794-799`) stays; admission closes the pairing instead (D11, R3-5).
- No outbox or re-emission for `PROCEDURE_CHALLENGE_DECIDED` (at most once, D11, R3-8), no retry phase for `pending_limit` rows (R3-7), and no retrieval change for a row active in SQLite whose index entry says inactive (R3-6); each is a follow-up.
- No `exact_tier` on rewrites, no new judge-tier setting, no retry of a rewrite on another tier.
- Do not refactor `capability_triage._clean` or `trace_analysis._clip` onto `bounded_text`.

## What This Does Not Change

Routing and replay (`find_matching`, `list_active`, `cognitive_agent` replay), except that `find_matching` no longer returns a match whose SQLite row is inactive (3g, review round 2) or, while the ledger is open and readable, a challenger it holds `retired`, or `pending` without the completed promotion `procedures.db` may already hold (3g, review rounds 3 and 4, R3-5, R4-2; its result keys are unchanged); procedure decay, archive, restore, dedup and merge (all operate on active rows); AD-579c expiry semantics on the legacy path; `consolidate_for_shutdown`; the AD-1327 crew verifier; events.db's router (the new member is routed by the existing `DurableEventRouter`).

---

## Acceptance Criteria

1. An evolved FIX version (Step 7b, reactive/proactive, Step 7d failure and near-miss) no longer deactivates its parent on save; it is stored inactive, linked to the champion through `parent_procedure_ids` and the ledger, and routing keeps using the champion (`test_submit_saves_the_challenger_inactive_and_routing_keeps_the_champion`, `test_fallback_fix_becomes_a_challenger_for_failure_and_near_miss`).
2. A challenger that wins is promoted: active, the champion deactivated with `superseded_by`, the evidence persisted, and one DURABLE event, emitted at most once after the decision commits (a process that stops between the commit and the emit leaves the ledger's decision with no event; D11, R3-8) (`test_challenger_wins_and_routing_uses_it`).
3. A challenger that loses, cannot gather `min_decisions` judgements, or stays undecided for `max_pending_cycles`, is retired with its evidence kept and the champion unchanged (`test_challenger_loses_and_the_champion_keeps_routing`, `test_missing_episodes_retire_with_insufficient_evidence`, `test_unresolved_challenger_expires_after_n_cycles`, `test_retired_challenger_keeps_its_comparisons`).
4. Candidates are unlabelled and judged in both orders, with the first order randomized; position and label do not decide the outcome (`test_position_biased_judge_yields_only_ties`, `test_content_judge_outcome_ignores_position_and_role`, `test_prompts_never_name_roles`).
5. Bradley-Terry is deterministic and matches hand-computed values, including ties and a never-winning candidate (the ranking tests).
6. Held-out episodes are excluded from the rewrite prompt and included in the comparison (`test_held_out_episodes_never_reach_the_rewrite_prompt_and_are_judged`).
7. Judge calls are bounded per dream cycle; exceeding the budget defers and never promotes (`test_budget_exhaustion_defers_and_never_promotes`).
8. The three rewriting calls use `deep` with a `standard` floor; the judge tier is AD-1327's (`verifier` when configured, else `standard`), recorded per judgement, and only independent judgements count when an independent judge is configured (rewrite-tier and judge tests).
9. The real-store chain evolve -> challenger saved -> comparison -> promotion -> routing uses the new version passes, and so does the losing path (`tests/test_ad1326_challenger_e2e.py`).
10. DERIVED evolution and stores with no pending challengers behave as before; `dreaming.procedure_challenger_enabled=false` keeps the legacy FIX handling (Step 7b, proactive and execution-failure FIX supersede the parent on save; a near-miss FIX is saved beside it), with rewrites on `deep`/`standard` in both modes (`test_derived_evolution_is_unchanged_under_the_challenger_flow`, `test_no_pending_challengers_cycle_is_a_no_op`, `test_flag_off_restores_immediate_supersession`).
11. Every LLM-derived string this AD adds to storage (judge reasons and error text, judge and optimizer model ids, optimizer tier) is bounded for NUL, length and strict UTF-8 (`bounded_text`, `is_persistable_judge_model`; the surrogate tests). The rewritten procedure's own text (`_build_steps_from_data`, `change_summary`) is persisted exactly as at base; its NUL/lone-surrogate gap is pre-existing and filed separately (Blind spot 10).
12. The pins in Sections 8, 11 and 13h-13i move by exactly the amounts stated; `check_store_registry.py`, `check_architecture_principles.py` (db-connect 30, srp-size 92 unchanged), `check_config_facade.py`, `check_config_profiles.py` and `gen_config_reference.py --check` pass.
13. A failed boot whose `ProcedureStore.stop()` raises before cleanup leaves no ledger worker thread: both variants of `test_issue1419_failed_start_rollback.py::test_a_real_boot_is_rolled_back_when_every_component_that_can_stop_raises` pass unchanged, and `test_last_resort_close_reaches_the_ledger_connection` pins the reach directly (D1b).
14. Review round 1 (D9): a promotion is `promoted` only when `find_matching` agrees with SQLite (`test_promotion_is_sealed_only_when_the_routing_index_agrees`); the judge sees replay's rendering, roles included (`test_render_candidate_is_the_replay_body`); the Step 7d source turn is never held out (`test_fallback_rewrite_prompt_quotes_no_held_out_turn`); equal records reach the creation-time tie-break (`test_equal_strengths_fall_to_the_creation_time_tie_break`); the pending cap holds under overlapping submits (`test_overlapping_submits_never_exceed_the_pending_cap`); every accepted configuration can produce a challenge (`test_every_accepted_configuration_can_produce_a_challenge`); a restored pair leaves no pending or retired challenger routable (the three `test_restored_*`/`test_retirement_leaves_no_routable_challenger` tests); early retirements report the recorded evidence (`test_early_retirement_reports_the_recorded_evidence`).
15. Review round 2 (D10): routing never admits a procedure whose SQLite row is inactive (`test_find_matching_admits_only_rows_active_in_sqlite`) — SQLite vetoes, it does not admit what the index excludes (R3-6); a retirement is sealed only when the challenger's index entry agrees, and a failed one is retried (`test_retirement_is_sealed_only_when_the_routing_index_agrees`); a promotion never deactivates the champion before the challenger's entry has taken, and is sealed only when both agree (`test_promotion_is_sealed_only_when_the_routing_index_agrees`, all three variants); the hot backup copies the ledger after `procedures.db`, so with both online backups succeeding the ledger is never older (`test_backup_copies_the_ledger_after_procedures_db`); pinning the source turn never costs situations the validator counted while at most half the recall is that turn (`test_source_pinned_recall_reaches_the_same_situations`); the candidate equals replay's body up to the 4,000-character cut (`test_render_candidate_is_the_bounded_replay_body_at_the_cut`); equal records reach the creation-time tie-break with the champion's id between the challengers' (`test_equal_strengths_fall_to_the_creation_time_tie_break[champion-between-*]`). `ProcedureChallenger` stays at 15 methods and `ProcedureStore` gains none in this round.
16. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
17. Review round 3 (D11): a judgement answered by the optimizer's own reported model (or its family, or an unknown family) is not counted under an independent judge, and the counting rule is never relaxed (`test_judgement_by_the_optimizers_model_is_not_independent`, `test_optimizer_model_never_relaxes_the_counting_rule`, `test_challenger_judged_by_its_optimizers_model_is_never_promoted`); a failed or cancelled ledger write is rolled back, so the next cycle finishes the transition (`test_failed_ledger_write_is_rolled_back`, `test_cancelled_ledger_write_is_rolled_back`, `test_failed_terminal_commit_is_finished_by_the_next_cycle`); the routing index's activity comes from the `is_active` column (`test_sync_routing_index_publishes_the_activity_column`); production Step 7d recalls `PROCEDURE_EVOLUTION_EPISODE_LIMIT` episodes (`test_step_7d_recalls_the_shared_limit_through_the_real_helper`); routing never admits a challenger the ledger holds `pending` or `retired` while the ledger is open and readable, whatever the restore path, except the completed promotion of Acceptance 18 (`test_find_matching_refuses_a_challenger_the_ledger_holds_undecided`, `test_raw_copy_fallback_pair_never_routes_the_pending_challenger`), and admits on SQLite alone when the ledger is unavailable (`test_find_matching_without_a_readable_ledger_admits_on_sqlite`). Confirm-then-seal holds for the decisions `_retire` and `_complete_promotion` make; a `pending_limit` row is recorded retired without it and is never routable (R3-7). `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5 methods; `ProcedureStore` gains none; `check_architecture_principles.py --check` passes with `architecture-baseline.yaml` unchanged.
18. Review round 4 (D12): a ledger write cancelled at any point, its `BEGIN IMMEDIATE` included, leaves no transaction open and holds the ledger lock until its rollback has run, through further cancellations, and the cancellation is delivered (`test_a_cancelled_begin_is_rolled_back_after_it_takes_effect`, `test_a_second_cancellation_during_cleanup_still_rolls_back`, `test_a_cancellation_during_rollback_waits_for_it_and_is_delivered`); a `BEGIN` refused by SQLite issues no rollback, and "no transaction is active" is never logged (`test_a_write_that_cannot_begin_issues_no_rollback_and_logs_nothing`, `test_a_cancelled_begin_that_never_takes_effect_logs_nothing`, `test_a_cancelled_commit_that_still_commits_is_durable_and_logs_nothing`); a restored completed promotion under an older `pending` row routes the winner with no dream cycle and with the feature disabled, while every other `pending` or `retired` challenger stays refused while the ledger is open and readable (`test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds`, `test_flag_off_routes_a_restored_completed_promotion`); adding the optimizer's model never raises a recorded label, and the counting rule is unchanged (`test_optimizer_model_never_raises_a_label`); the registry note states the fail-open qualification. Counts unchanged: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5, `ProcedureStore` +0.
19. Review round 5 (D13): every public ledger read waits for an in-flight write and returns only committed state, whether that write commits or is rolled back (while cleanup succeeds: after a `ROLLBACK` that itself fails, reads may return the open transaction's rows until the store restarts, Blind spots 14 and 17; review round 6, R6-2), and routing never admits a challenger from a transition that is rolled back (`test_every_public_ledger_read_waits_for_an_in_flight_write`, `test_a_read_during_a_rolled_back_write_returns_the_committed_row`, `test_find_matching_waits_for_a_rolled_back_promotion_and_routes_the_champion`); `ProcedureStore.get` reports `is_active` and `superseded_by` from the columns admission reads, so a completed promotion whose champion snapshot is stale is recorded `restored_promotion` and keeps routing (`test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted`, `test_sync_routing_index_publishes_the_activity_column`); the ledger's `busy_timeout` is described as SQLite's busy-handler budget, not a wall-clock bound, and its cleanup stays untimed; the registry note promises reconciliation only when the challenger service is enabled and a dream reaches its step. Counts unchanged: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5, `ProcedureStore` +0; `check_architecture_principles.py --check` passes. Review round 6 supersedes this criterion's `get` clause (Acceptance 20).
20. Review round 6 (D14): `ProcedureStore.get`'s body is unchanged from base (no added or removed line of `git diff a71575ec -- src/probos/cognitive/procedure_store.py` falls inside it); a restore whose snapshot UPDATE is refused, when the snapshot was already inactive (the single refusal), publishes no ACTIVE index entry and `get` reports the snapshot's level; with archive's UPDATE refused too the result is the base commit's (f35) (`test_restore_with_a_refused_snapshot_publishes_no_active_entry_at_a_stale_level`); admission, the published index flag and every activity or supersession decision of `ProcedureChallenger` read `ProcedureStore.routing_state` (`test_routing_state_reads_the_columns_not_the_snapshot`, `test_sync_routing_index_publishes_the_activity_column`), so a restored completed promotion with a stale champion snapshot is still recorded `restored_promotion` and keeps routing, its other open challengers are retired `champion_inactive`, and a promotion re-activates a challenger whose snapshot says active while its column does not (`test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted`, `test_a_restored_promotion_with_a_stale_champion_snapshot_retires_the_other_open_challengers`, `test_a_promotion_activates_a_challenger_whose_snapshot_says_active`); the ledger's "committed" wording carries the cleanup-success condition. Counts: `ProcedureChallenger` 15, `ProcedureChallengeLedger` 14, `ProcedureJudge` 5, `ProcedureStore` 57 (+1); `check_architecture_principles.py --check` passes with `architecture-baseline.yaml` unchanged.

---

## Prior Art and Blind Spots

**Internal.**
- MASS absorption note (`docs/research/mass-self-supervision-absorption.md`): finding 4 names AD-1326 for the optimizer upgrade, and the inner-loop description is the champion rule. *Absorbed:* champion/challenger, pairwise preference with a reason, Bradley-Terry, optimizer on the strongest tier. *Rejected:* the LoRA outer loop (Do Not Build).
- AD-1327 (`verifier_independence.py`, `crew_verdict.py`): *absorbed* whole for the judge tier, provenance and the persistable-model bound.
- AD-534 replay (`cognitive_agent.py:1930-1956`): defines a procedure's output; *absorbed* as what the judge compares.
- AD-579c expiry, AD-1156 plan-mode filter (`types.episode_ran_in_plan_mode`), AD-1195 durable events, AD-1256 store declarations, AD-1324 stakes floor: reused, not re-implemented.

**External (bounded search, 3 queries).**
- Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* ([arXiv:2306.05685](https://arxiv.org/abs/2306.05685)): position bias is large (GPT-4 consistency about 65% under a swap). *Adopted:* the swap, with a win only on agreement (the agreement rule is the common practitioner reading, e.g. [memx.app](https://memx.app/blog/llm-as-a-judge-biases-and-fixes/); not confirmed verbatim in the paper).
- Hunter, *MM algorithms for generalized Bradley-Terry models*, Ann. Statist. 32(1), 2004 ([projecteuclid](https://projecteuclid.org/journals/annals-of-statistics/volume-32/issue-1/MM-algorithms-for-generalized-Bradley-Terry-models/10.1214/aos/1079120141.full)): MLE exists only for a connected win graph. *Adopted* MM; *adapted* with pair pseudo-counts so a never-won candidate is finite. Vojnovic, Yun and Zhou ([arXiv:1901.00150](https://arxiv.org/abs/1901.00150)): MAP-by-MM can converge slowly for some priors; *rejected* a Gamma prior for pseudo-counts with a closed form on a star.
- Champion loop with holdout margin ([Forward Future loop library](https://signals.forwardfuture.ai/loop-library/loops/self-improving-champion-loop/)): promote only when the challenger beats the champion on untouched holdout cases by a margin. *Consistent* with D3/D5; *considered, deferred:* a separate held-out-only promotion bar (the held-out tally is recorded and emitted, so a later AD can gate on it).
- Review round 1 ran no new external search: its findings are repairs of this design against ProbOS's own store, recall and backup seams, with no outside analogue that changes the choice. The closed form used for F4 is Hunter's MM fixed point specialised to a star (each candidate's only pair is with the reference).
- Review round 2 ran no external search either: R2-1..R2-4 are ordering and admission repairs against ProbOS's own index, backup and recall seams. The R2-2 order (make the new entry routable before withdrawing the old) is the ordinary make-before-break handover.
- Review round 3 ran no external search: R3-1..R3-8 are repairs against ProbOS's own judge policy, ledger transactions, index, recall and backup seams. Internal precedent reused: `fault_issue_filings.fault_transaction` (`:110-130`) for the rollback-on-`BaseException` shape (R3-2); AD-1327's `classify_independence` for the optimizer comparison (R3-1). SQLite's documented behaviour that a raw copy of a WAL database's main file omits committed frames still in `-wal` is the mechanism of R3-5 (reproduced by the orchestrator, F2).
- Review round 4 ran no external search: R4-1 is aiosqlite's documented queue behaviour (one worker thread per connection, `core.py:150-160`), and the repository already drains a retained operation through cancellation before propagating it (`execution/workspace_results.await_result_task`, `:439-453`), the shape `_write_transaction` follows. R4-2 reuses `_reconcile`'s completed-promotion predicate; R4-3 reuses `classify_independence` unchanged.

**Blind spots named (not in the issue).**
1. **Verbosity and description cues.** The swap removes position bias, not length bias; a rewritten description may advertise itself. The system prompt says length is not evidence and the name is hidden; length normalisation is *considered, deferred*.
2. **Replay is not execution.** The judge rates which fixed plan better fits a real situation. Running both procedures needs a sandbox; *deferred* to a Holodeck AD.
3. **Concurrent submit — resolved in review round 1 (F5).** The proactive scan and a forced dream can run `prepare`/`submit` for one champion at once (reproduced: 3 pending, limit 2). The ledger now counts and inserts under one lock and records an over-cap challenger `retired` (`pending_limit`); the residual is one deep call spent by the overlapping rewrite, never a slot.
4. **Store pairing after restore — restated in review round 1 (F7).** The ledger and `procedures.db` are copied separately, so a hot backup can pair a `pending` row with a completed promotion (reproduced). `_reconcile` records that promotion (`restored_promotion`), deactivates any other routable pending challenger and retires orphans with their evidence. A ledger newer than `procedures.db` leaves the older routing (safe) and a `promoted` row that overstates it; a consistent pair snapshot in `BackupService` is *considered, deferred*. Review round 2 (R2-3): the reviewer's real backup produced the pending-and-routable pair before the first dream cycle; the ledger is renamed `procedures_challenges.db` so the backup copies it after `procedures.db` and that pair can no longer come from a backup. Residuals, accepted: a pair copied by other means routes a pending challenger until the first dream cycle; and a `procedures.db` copied mid-promotion (challenger active, champion not yet deactivated) under a ledger already `promoted` leaves both routing — the decided winner beside the old champion, as a legacy near-miss FIX does — until an operator deactivates the champion, because decided rows are not rescanned. Review round 3 (R3-5): the backup's raw-copy fallback can still copy an older ledger image (its newer state in `-wal`), so the copy order alone does not hold; admission now refuses any challenger the ledger holds `pending` or `retired`, so, while the ledger is open and readable, no restore path routes an undecided one (a closed or unreadable ledger admits on `procedures.db` alone, R3-5's fail-open). Its cost: a restored completed promotion over an older `pending` row routed neither procedure until the first dream cycle, and never with the feature disabled. Review round 4 (R4-2) removes that cost: admission accepts a `pending` challenger whose champion `procedures.db` holds inactive and superseded by it, the pair `_reconcile` records as `restored_promotion`.
5. **Judge reasons may quote episode text** into `procedures_challenges.db` (500 characters each), the same exposure class as the `change_summary` already stored in `procedures.db`.
6. **Pre-existing defect, out of scope (file a BF):** `on_task_execution_complete` calls `find_matching(intent_type, threshold=PROCEDURE_MATCH_THRESHOLD)` (`dreaming.py:2079-2081`), but `find_matching` takes no `threshold` and no `**kwargs` (`procedure_store.py:763-770`); the `TypeError` is swallowed at `dreaming.py:2106-2107`, so the AD-532e reactive trigger never evolves anything. *Confirmed by reading* (orchestrator, 2026-10-13): the caller also treats `find_matching`'s list result as a dict.
7. **Pre-existing defect, out of scope (file a BF): an event-loop deadlock, REPRODUCED.** `ProcedureStore` holds a `threading.Lock` across `await` (`procedure_store.py:540-584`, `:992-997`, `:1070-1093`). A second coroutine that enters a write while the first is suspended inside the lock calls a blocking `acquire()` on the event-loop thread; the first can never resume to release it, so the loop deadlocks, it does not merely stall. Orchestrator probe `probe_procedure_store_lock_deadlock.py` (2026-10-13): one save and two sequential saves complete; `asyncio.gather(store.save(a), store.save(b))` makes no progress for 25 s, with a watchdog thread reporting the loop blocked. D1/D1b keep the ledger on its own connection and `asyncio.Lock`, so it adds no holder. The challenger's writes to `procedures.db` (`save`, `deactivate` on submit and promotion) are the same calls the three evolution sites make today, so the hazard is neither added nor removed; a reactive submit concurrent with the dream (Blind spot 3) carries the same pre-existing risk.
8. **Operator control (HXI Cockpit principle).** The flag is the manual control today; a view of pending challengers and a manual promote/retire is *considered, deferred* to a follow-up AD.
9. **Pre-existing defect, out of scope (file a BF): silent semantic-index failures (review round 1, F1).** `ProcedureStore.save` ignores `_save_to_chroma`'s result and `deactivate` swallows its index update (`except Exception: pass`), while `find_matching` reads only the index, so any caller can leave routing disagreeing with SQLite until a rebuild, and the index is rebuilt only when `procedure_index_state != "ready"` at start. Reproduced by the orchestrator with no AD-1326 code. This AD closes it for its own transitions only (`sync_routing_index`, D9). A related gap: a run whose index failed to open writes nothing to it, and the next start can open the old collection still marked `ready`. Suggested BF: mark the index stale on any failed write. Review round 2 (R2-1) closes one half for every caller: `find_matching` admits a match only when its SQLite row is active (3g), so a stale ACTIVE entry no longer routes an inactive procedure. The other half stays open: a procedure active in SQLite whose entry is missing or says inactive is not found until a rebuild (review round 3, R3-6: base behaviour, `find_matching` filters the index on `is_active`; the orchestrator registers it). Review round 3 (R3-3): `deactivate` swallows a failed `content_snapshot` UPDATE after the column commits, so `get()` can disagree with the column; `sync_routing_index` now publishes the column, so this AD's seals hold. The legacy best-effort writes (`deactivate` `:1172`, archive `:1585`, restore `:1662`, `save` ignoring the index result) stay with the store follow-up (f26).
11. **Long candidates are cut (review round 2, R2-5).** `render_candidate` bounds the body at 4,000 characters, so a long description can crowd every step out of the judge's view while replay would show them. *Considered, deferred:* a step-preserving bound (description truncated first). A rewrite that grows its description past the bound is judged on what the judge sees.
10. **Pre-existing defect, out of scope (file a BF; the orchestrator files it): rewritten procedure text is not sanitised.** The reviewer persisted a 10,008-character `change_summary` with NUL and a step action with NUL plus a lone surrogate through `_build_steps_from_data` (`procedures.py`), unchanged from base; the action fails strict UTF-8 on read-back. Acceptance 11 is narrowed to the strings this AD adds.
12. **The decision event is at most once (review round 3, R3-8).** The terminal status commits before `_emit`; a process that stops between them leaves the decision in the ledger and no event, and decided rows are never re-emitted. Reproduced by the reviewer and the orchestrator. An outbox (emission intent written with the transition, delivered idempotently) is *considered, deferred* to a follow-up.
13. **Reported models are trusted as reported (R3-1).** The optimizer's and the judge's model ids come from the provider's reply (`answered_model`); a provider that misreports both defeats the comparison. An optimizer answer from a model of unknown family makes every judgement `unknown`, so under an independent judge that challenger expires (the safe direction). A judge pinned to a different provider account is *considered, deferred*.
14. **Ledger rollback failure (R3-2).** If `ROLLBACK` itself fails, the open transaction makes every later ledger write fail until the store restarts (one ERROR); reads on that connection may show the uncommitted row meanwhile. Accepted: it needs a broken SQLite connection. Review round 4 (R4-1): a cancelled statement is not such a failure any more; its `ROLLBACK` runs after it settles, and "no transaction is active" is not logged.
15. **A cancelled ledger write can still be durable (R4-1).** A `COMMIT` cancelled after aiosqlite queued it still commits, so the caller sees `CancelledError` for a write the ledger holds. Accepted: the next cycle re-reads the ledger, and a terminal transition's event is lost exactly as in Blind spot 12. Cancelling the dream mid-write (shutdown, a timeout) also waits for the queued statement and its rollback, for as long as SQLite's busy handler retries a locked file: a budget of `busy_timeout` (5,000 ms), not a wall-clock ceiling (the reviewer measured 5,579 ms; review round 5, R5-3). Since R5-1 a routing read behind that write waits as long.
16. **An operator merge can stand in for a promotion (R4-2).** `merge_procedures` (`procedure_store.py:1951`; shell and API only) deactivates the duplicate with `superseded_by` the primary. Merging a champion into its restored, still-active `pending` challenger therefore satisfies the completed-promotion predicate: admission routes the challenger and `_reconcile` records `restored_promotion`. Accepted: it needs a restored pending-and-active pair plus an explicit operator merge choosing the challenger as primary, which is an operator decision. Making `merge_procedures` consult the ledger is *considered, deferred* to the store follow-up.
17. **Ledger reads now wait for writers (R5-1).** A routing read waits for an in-flight ledger write; that is microseconds in practice, since this connection is the file's only writer in ProbOS, and is bounded by the busy-handler budget only when another process holds the file's write lock. A rollback that itself fails still releases the lock with the transaction open (Blind spot 14), so reads may see the uncommitted row until the store restarts: unchanged, it needs a broken connection. Review round 5 ran no external search: single-connection read-your-writes is documented SQLite behaviour, and the fix reuses the ledger's own lock.
18. **`get`'s snapshot can lag its columns; AD-1326 does not read lineage from it (R5-2, rewritten in review round 6, R6-1).** Round 5's form of this item claimed no routing decision reads `compilation_level` from `get`; that was false: `CognitiveAgent._check_procedural_memory` dispatches on `get`'s `compilation_level` (`cognitive_agent.py:1824, 1848-1864`), and a half-merged `get` published a restored Level-1 procedure ACTIVE at its snapshot's Level 4 (the reviewer's reproduction). Since round 6 `get` is base: every field comes from the snapshot, for all 40 callers. Legacy drift between snapshot and columns stays as at base: `promote_compilation_level`/`demote_compilation_level` write the level column only (`procedure_store.py:1036-1064`), so `get` and the agent's dispatch see the level of the last `save`; `deactivate`, archive and `restore_procedure` swallow a failed snapshot UPDATE, so a restore whose snapshot write is refused while the snapshot is still inactive publishes an inactive entry and the procedure does not route until it is re-saved; if archive's snapshot write was refused too, the snapshot stays active at its old level and restore publishes an ACTIVE entry at that level, exactly as at base, so "safe direction" holds only for the single refusal (pre-existing, f26 and f35). AD-1326's lineage decisions read the columns through `routing_state`. A store-wide "columns win" `get` is *considered, deferred* to the store follow-up (f26): it changes AD-535's dispatch for every promoted or demoted procedure.
19. **With the challenger service disabled the ledger is never reconciled (R5-4).** A restored completed promotion routes (R4-2) while its row stays `pending`; re-enabling the service records it `restored_promotion` on the first dream that reaches the step. Accepted: routing is correct meanwhile, and nothing reads the ledger's verdict for that pair except admission, which already accepts it.
20. **A row whose snapshot cannot be deserialized (R6-1).** `routing_state` returns its columns where `get` returns `None`. `_reconcile` therefore no longer retires such a challenger `challenger_missing` on sight: an inactive one stays pending (its sync writes nothing, `get` is `None`) and expires after `procedure_challenger_max_pending_cycles`; an active restored-promotion one reaches `_complete_promotion`, whose `get` is `None`, and is retired `challenger_missing` there. Accepted: it needs a corrupt snapshot. `find_matching` admits such an active row's metadata (it reads the index and the columns, not `get`), while replay reads `get`, gets `None` and fails closed; admitting unusable metadata is pre-existing (f26). Review round 6 ran no external search: R6-1 is a revert plus a read of ProbOS's own columns, and R6-2 is wording.
21. **A resumed `promoting` challenger is activated before the champion's supersession is read (review round 7, finding 1; recorded as f37, not repaired here).** `run_cycle` completes `promoting` rows before it contests `pending` ones, and `_complete_promotion` activates the challenger and then checks only that the champion is active, not whether another id already superseded it. A restored pair that is inconsistent by construction (champion inactive and superseded by `ch-a`, `ch-a` active, `ch-b` `promoting`) therefore seals a second winner on the first enabled dream, where the pending path would retire `ch-b` `champion_inactive`. Reach: injected (a restore or manual edits; two promotions of one champion cannot both happen in ordinary operation); it reproduces at the round-6 snapshot, so round 7 did not introduce it. Fix: read `routing_state(champion)` before activating and retire a challenger whose champion another id superseded.

---

## Verified Against Codebase (2026-10-13, base `a71575ec`)

```
git log --oneline -5                     -> a71575ec Merge pull request #1522 ... (AD-1327 merged)
scripts/ad_ceiling.py                    -> CEILING: AD-1327 (git log, issue titles, prompts/ad-*.md); NEXT AD-1328

Grep "procedure_store\.|evolve_fix_procedure|evolve_with_retry|evolve_derived" dreaming.py
  1894: result = await evolve_fix_procedure(   1910: await self._procedure_store.save(   1922: ...deactivate(
  2013: result = await evolve_with_retry(      2030: ...save(                             2041: ...deactivate(
  2197: result = await evolve_with_retry(      2215: ...save(                             2228: ...deactivate(
Read dreaming.py:1840-2249 (the three sites, _expire_superseded_episode_sources 1941, _attempt_procedure_evolution 1958)
Read dreaming.py:1-210 (imports 15 "from typing import Any", 49-56 probos.types incl. episode_ran_in_plan_mode,
  61-73 _outcome_evidence, 84-115 __init__ ending intent_skill_map 114, 127 self._procedure_store = procedure_store)
Read dreaming.py:683-689 (Step 7b), 813-822 (Step 7d, "Step 7d fallback learning failed" 820), 314-403 (shutdown: no LLM steps)
Grep "# Limit to 10 most recent|# Call evolution with retry" dreaming.py -> 1884, 2196 (each once)

Grep "^\s*(async )?def |CREATE TABLE|is_active|superseded_by|ConnectionFactory" procedure_store.py
  25: from probos.protocols import ConnectionFactory, DatabaseConnection   76: CREATE TABLE ... procedure_records
  104: CREATE TABLE ... procedure_lineage_parents   122: def __init__   126: connection_factory   139: async def start
  277: async def stop   281: async def _close_resources   510: async def save   652: async def get
  672: async def list_active   763: async def find_matching   969: async def get_evolution_metadata
  1066: async def deactivate   1565: async def restore_procedure
Read procedure_store.py:1-170, 277-306, 505-684, 763-825, 940-1001, 1026-1101, 1565-1607
  137: self._chroma_client: Any = None   143: procedures.db   148: PRAGMA foreign_keys=ON   161: _migrate_qualifying_procedures
  540/992/1070: with self._write_lock (threading.Lock, 135) around awaits   542: INSERT OR REPLACE   578-583: lineage rows
  687: "is_active = 1"   780: where {"is_active": True}   1575: restore requires is_archived
wc -l procedure_store.py -> 1844

Grep "tier=|^(async )?def |^class |is_active|superseded_by|parent_procedure_ids" procedures.py
  206 confirm gate, 515 extract cluster, 654 observation, 787 FIX, 874 DERIVED, 1029 negative, 1157 compound, 1294 fallback: tier="standard"
  82: is_active   84: parent_procedure_ids   86: superseded_by   168: class EvolutionResult
Read procedures.py:1-260, 440-489, 744-920, 1246-1332
Grep "system_prompt=_\w+_SYSTEM_PROMPT" procedures.py -> 786 _FIX, 873 _DERIVED, 1293 _FALLBACK_FIX (each once)
Grep 'logger\.debug\("(FIX|DERIVED|Fallback FIX) evolution failed' procedures.py -> 824, 919, 1331

Read llm_client.py:30-60 (46 VERIFIER_TIER, 53 _TIER_ORDER, 56 TEXT_TIERS), 184-191 (_floor_ok), 962-999,
  1492-1645 (1496 floor, 1558-1563 verifier chain, 1567 plain chain, 1569-1573 floor filter, 1604-1608 verifier exact,
  1613-1615 strict route, 1632-1639 CostCeilingExclusion)
Read types.py:290-345 (LLMRequest 312 min_tier, 315 exact_tier; LLMResponse 344-345 answered_tier/answered_model)
Grep "^class Episode:|user_input|outcomes" types.py -> 638, 643, 645
Read verifier_independence.py:1-165 (92 VerifierJudgePolicy, 104-106 tier guard, 109 from_cognitive, 120 assess, 124 provenance)
Read crew_verdict.py:1-20, 80-187 (105 JudgeIndependence, 106 MAX_JUDGE_MODEL_CHARS, 109 is_persistable_judge_model,
  127 JudgeProvenance, 170 judge_to_json)
Grep "VerifierJudgePolicy\.from_cognitive\(" src -> doctor/checks/verifier_check.py:37, __main__.py:349, startup/finalize.py:2242
Read episodic.py:1993-2037 (get_by_ids(ids, *, for_evidence); returns [] on failure), 3358-3399 (recall_by_intent k=5)
Grep "update_episode_validity" episodic.py -> 2259
Read cognitive_agent.py:1930-1956 (_format_procedure_replay: steps are the response)

Read events.py:180-199 (191 PROCEDURE_FALLBACK_LEARNING)
Read event_persistence.py:1-120 (47 DECLARATIONS, 59-60 DESIGN_GENERATED/SHIP_NAMED, 98 OWNER_RECORDS, 111 GRANDFATHERED)
Grep durable_events.py -> 47 DURABLE_PAYLOAD_MAX_BYTES = 4096, 59 ROUTED_VALUES
git log -- src/probos/events.py -> 8041302f (AD-1195) is the latest; no member added since

Read startup/dreaming.py:1-229 (18-19 imports, 35-61 init_dreaming, 164-192 DreamingEngine(...), 191 failure_distiller=)
Grep runtime.py "init_dreaming\(|emit_event_fn=" -> 3028, 3045 emit_event_fn=self._emit_event
Read runtime.py:2896-2908 (ProcedureStore(data_dir=self._data_dir / "procedures"))
Grep shutdown.py procedure_store -> 1781-1784 (procedure store stop)

Read config_models/cognition.py:1-161 (3-5 self-contained leaves, 10 pydantic import, 85 DreamingConfig, 158 last field)
Grep config.py -> 3858 cognitive: CognitiveConfig, 3861 dreaming: DreamingConfig
Read scripts/check_config_profiles.py:1-60 (gate 3: default-False booleans only)
Read scripts/check_config_facade.py:1706-1730 (--check, --update-baseline)
Grep config-facade-baseline.yaml -> 51 field_definitions: 1844; 1536-1591 DreamingConfig fields

Read storage_declarations (cognitive):1-48, 160-219; storage/declarations.py:66-91 (StoreCriticality, StoreRetention)
Read scripts/check_store_registry.py:1-90 (rules 9-11); store-baseline.yaml:54-57 (procedure_store baselined)
Read architecture-baseline.yaml:590-619 (606-614 ProcedureStore srp-size debt)
Grep check_architecture_principles.py -> 160-165 GATING_CATEGORIES, 187-188 SRP_MAX_BODY_LINES=500, SRP_MAX_DIRECT_METHODS=15
Read tests/test_ad1265_backup_coverage.py:55-121 (every *.db literal planted and discovered)

Revision 2026-10-13 (execution findings; orchestrator evidence logs/architect/evidence-ad1326-diag.md)
Read startup/shutdown.py:441-470 (_direct_connections: vars(component), isinstance aiosqlite.Connection,
  "One level, no deeper" 446, "a connection held deeper than one attribute level ... is not found" 455-458)
Read startup/shutdown.py:580-583 (keep_failed), 640-651 (settle_failed), 700-738 (_close_direct_connections;
  730 "BF-882: last-resort close of %s.%s (%s.%s)")
Read procedure_store.py:122-167 (131-134 connection_factory/default_factory, 144 connect, 162-167 start's
  CancelledError/Exception -> _close_resources), 277-306 (stop, _close_resources)
Read tests/fixtures/runtime_lifecycle.py:401-413 (direct_connection_attributes), 438-471 (break_stop "before")
Read tests/test_issue1419_failed_start_rollback.py:1127-1174 (_STOPPED_COMPONENTS, 1153 _procedure_store),
  2447-2452 (_BREAKABLE_BEFORE_CLEANUP: acm, identity_registry, _counselor_profile_store, ward_room),
  2487 (stop.connections == ["_db"] for those four only), 2499-2529 (_EVERY_BREAKABLE_COMPONENT,
  2525 any(stop.connections), 2527-2529 calls == 1)
Grep "broken_stop_connections" tests -> 2881, 2947 pin only acm / identity_registry
Read scripts/check_store_registry.py:70-76, 1234-1251 (connection_factory_absent is report-only, substring
  "ConnectionFactory" in the module source; the ledger's docstring keeps the word)
Grep check_architecture_principles.py "aiosqlite.connect|sqlite3.connect" -> 192 (factory.connect not counted)
Read tests/test_dream_step_7f.py:28-63 (52 engine._procedure_store = mock_store, unique)
Read tests/test_fallback_learning.py:117-159 (135 engine._procedure_store = overrides.get(...), unique;
  142-157 per-AD comments)

Review round 1 (2026-10-13; worktree with the contract installed, so src line numbers are post-build)
Read logs/architect/review-ad1326-r1.md, probe-ad1326-r1-findings.out, probe-ad1326-r1-f3.out (all 8 findings
  reproduced, PREMISE FAILURES: none); probe_ad1326_r1_findings.py:49-55 (the F4 ids and outcomes)
Read procedure_store.py:365-464 (_init_chroma; 414-420 rebuild only when procedure_index_state != "ready"),
  545-561 (rebuild marks "ready"), 567-587 (save: 586 self._save_to_chroma(procedure), result ignored),
  682-707 (_write_to_chroma raises; _save_to_chroma returns bool, WARNING), 820-881 (find_matching: 833 no
  collection -> [], 837 where is_active, 871 drops ids without a SQLite row), 1123-1158 (deactivate:
  1151-1158 index update, except Exception: pass)
Grep '"<unknown>"' procedure_store.py -> 1 (the 3f SEARCH is unique)
Grep ProcedureStore architecture-baseline.yaml -> 606-614: triggers lines, methods only (no counts)
Read cognitive_agent.py:1917-1928 (_format_single_step: "**Step N [role]:**", "→ Expected"),
  1930-1956 (_format_procedure_replay: 2 header lines + blank, description + blank, steps, "⚠ Fallback",
  "**Postconditions:**" / "  - pc"; no preconditions), 7624-7635 (PROCEDURE_FALLBACK_LEARNING payload,
  7632 llm_response, 7634 correlation_id)
Grep "correlation_id" types.py -> 659 (Episode.correlation_id: str = "")
Grep "agent_role|class ProcedureStep" procedures.py -> 29, 42 (agent_role: str = "")
Grep "deactivated by the caller|Evolve a FIX replacement" procedures.py -> 791, 793 (6i SEARCH unique)
Grep "fresh_episodes|# Limit to 10" dreaming.py -> caps at 1903 (12 sp), 2039 (8 sp), 2249 (16 sp)
Read dreaming.py:2024-2045 (13e-0 context), 2196-2255 (7d: event dict, recall, cap, prepare), 30-46
Grep "OBSERVATION_WARD_ROOM_LOOKBACK_HOURS" dreaming.py -> 45 (import), 2332 (use): 13a-2 SEARCH unique
Grep "^(EVOLUTION_COOLDOWN_SECONDS|MAX_FALLBACK_RESPONSE_CHARS|PROCEDURE_MIN_SELECTIONS)" -> config.py 243, 249, 257
Grep "from probos.config_models" config.py -> 25 (named imports from cognition: a new constant is not re-exported)
Grep "from probos\.config_models\." src (excluding config.py) -> config_models/__init__.py, fault_issue_filings.py:14
Read config_models/cognition.py:1-10 (self-contained leaves; 10 pydantic import)
Read scripts/check_config_facade.py:1015-1041 (build_surface enumerates vars(probos.config) only)
Grep tests/test_ad1270e1_config_facade.py -> 1521 public_names == 305, 1550 field_definitions == 1852
Read tests/test_layer_boundaries.py:16-27 (LAYER_MAP has no config_models), 152-165 (_get_imported_layer -> None)
Read tests/test_ad1326_procedure_challenger.py:60-76 (_PROMPT reads "Purpose: routine of <x>")

Review round 2 (2026-10-13; the candidate staged in this worktree, so src line numbers are post-build)
Read logs/architect/review-ad1326-r2.md, probe-ad1326-r2-findings.out (R2-1..R2-5 reproduced, PREMISE FAILURES: none)
Read procedure_store.py:700-744 (709 sync_routing_index; 718-723 no index / no row -> True), 836-924 (find_matching:
  853 where is_active, 887 _get_index_row per match, 888 drops a None row; 899-924 _get_index_row: SELECT ... is_negative
  FROM procedure_records WHERE id = ?, no is_active column read)
git show a71575ec:src/probos/cognitive/procedure_store.py | grep -n -> 763 find_matching, 814 _get_index_row call,
  826 def _get_index_row, 827 its docstring, 834 the only "FROM procedure_records WHERE id = ?\"\"\"," inside it (3g SEARCH unique: one def)
Grep "_get_index_row" *.py -> procedure_store.py:887 (only caller), 899 (def)
Grep "\.find_matching\(" src/probos -> cognitive_agent.py:1738, 1764; dreaming.py:653, 744, 2135, 2409; proactive.py:2024;
  procedure_store.py:1781 (dedup; Read 1770-1793: skips itself, reads id and score)
Grep "\.find_matching\(" tests -> test_procedure_store.py (3), test_ad1326_procedure_ledger.py, test_ad1326_procedure_challenger.py,
  test_ad1326_challenger_e2e.py (1 each)
Read tests/test_ad1326_procedure_challenger.py:322-427 (_rig, _pend, _routed_ids, _matched_ids 380, _activate 385,
  _index_outage 413: monkeypatch of the live collection's method, records kwargs["ids"]), 544-632 (F3 and F6 tests;
  pinned expectations 562-564, 573-574), 1173-1380 (F4 tie-break 1173-1210; F1 sealing 1213-1259, 1229-1230 and 1249
  pin the champion inactive and routing == []; F7 tests 1262-1380, stale-index premise 1329)
Grep "procedure_challenges\.db" (repo, logs excluded) -> procedure_challenges.py:11, procedure_store.py:286, 296,
  storage_declarations.py:224, tests/test_ad1326_procedure_ledger.py:103, 247, 284, 841, 863, 865, 877, 907
Read infrastructure/backup_inventory.py:250-299 (272 sorted(rglob("*.db")), 298 found.sort(key=(root_name, str(relative_path))));
  infrastructure/backup.py:271-300 (284 copies each discovered entry in order; IMMUTABLE linking only for archives/ward_room_*.db, inventory :51)
Grep "canonical_path" scripts/check_store_registry.py -> 37, 225, 1156-1162 (uniqueness only)
Read tests/test_ad1265_backup_coverage.py:32-43 (imports discover, BackupRoot from probos.infrastructure.backup_inventory), 62-121
Read procedure_challenges.py:110-121 (bounded_text: NUL removed, encode/decode "replace", then [:limit])

Review round 3 (2026-10-13; candidate e29b599d staged in this worktree, src line numbers post-build)
Read logs/architect/review-ad1326-r3.md (findings 1-8), probe-ad1326-r3-findings.out (F1-F8 reproduced; PREMISE FAILURES: none;
  F5 INFO: base find_matching filters the index on is_active: True; F6: the helper passed no k)
Read verifier_independence.py:68-88 (classify_independence; 76 ignores empty names; 80 same_model; 86 unknown family -> unknown),
  91-144 (frozen dataclass; crew_models field 102; __post_init__ 104-106; assess 120-122; provenance 124-144)
Grep procedure_judge.py / procedure_challenger.py -> judge 205 compare, 222 _ask; challenger 416 _judge_record, 436 compare call,
  496 _complete_promotion, 554 _retire
Read prompt Section 12 _judge_record: returns None while any available situation is uncounted; _contest reaches
  insufficient_evidence only for a complete record; _age retires expired at max_pending_cycles
Read protocols.py:325-358 (DatabaseConnection: execute, executemany, executescript, fetchone, fetchall, commit, close; no rollback)
Grep "ROLLBACK" src/probos -> about 30 sites use execute("ROLLBACK"); Read fault_issue_filings.py:110-130 (fault_transaction:
  lock, BEGIN IMMEDIATE, yield, commit, except BaseException -> ROLLBACK, except Exception -> logger.error, raise);
  federation_envelope_store.py:169-179 (same shape)
Read procedure_store.py:672-682 (_chroma_payload: is_active is the only activity field; no superseded_by), 711-725 (sync_routing_index),
  727-745 (get reads content_snapshot only), 838-899 (find_matching: 855 index filter is_active True, 889 _get_index_row per match),
  901-920 (_get_index_row), 1147-1182 (deactivate: column UPDATE 1153, snapshot UPDATE inside try 1164-1173, except: pass 1172)
Grep procedures.py "^@dataclass" -> 60-61 Procedure is a mutable dataclass
git show a71575ec:src/probos/cognitive/procedure_store.py | grep -n -A 28 "async def _get_index_row" -> 826-851 (837-839 fetchone,
  "if not row: return None": the extended 3g SEARCH is unique, anchored on the def)
Grep ".deactivate(" src/probos -> dreaming.py:1958, 2097, 2301; procedure_store.py:1919; procedure_challenger.py:407, 533
Read dreaming.py:1853-1857 (_recall_evidence_by_intent: recall_by_intent(intent_type), no k); Grep -> callers 1895, 2033, 2243;
  slices 1904, 2040, 2250; import 47
git show a71575ec:src/probos/cognitive/dreaming.py | grep -n -B 3 "recall_by_intent(intent_type))" -> 1835-1838 (13a-3 SEARCH)
Grep "async def recall_by_intent" src/probos -> episodic.py:3358 (k: int = 5), episodic_mock.py:219 (k: int = 5)
Grep "recall_by_intent" tests -> fakes: test_ad579c_validity_dream.py:67 (no k; :185 drives _evolve_degraded_procedures),
  test_ad1326_challenger_e2e.py:135 and test_ad1326_dreaming_challenger.py:144 (k: int = 5); the rest AsyncMock or real memory
Read tests/test_ad1326_dreaming_challenger.py:512-531 (limit monkeypatched to 4; two intents e0..e4, e5..e7)
Grep "def _backup_one|shutil.copyfile|except sqlite3.Error" backup.py -> 772, 794, 799
Grep "_routed_ids(store) ==|_matched_ids(store) ==" tests/test_ad1326_*.py; Read test_ad1326_procedure_challenger.py:365-422,
  1464-1606 (_routed_ids = list_active 367-368; _matched_ids = find_matching 380-382; R3-5 moves at 1504, 1555, 1595)

Review round 4 (2026-10-13; frozen candidate in this worktree = D11 + the orchestrator's wording edits and two tests)
Read logs/architect/review-ad1326-r4.md (findings 1-4), probe-ad1326-r4-findings.out (F1-F3 reproduced; PREMISE FAILURES: none)
Read procedure_challenges.py:143-175 (_write_transaction: begun set after BEGIN returns; ROLLBACK only if begun) -- identical
  to the contract's Section 2 block before this round; 257-258 (start: PRAGMA journal_mode=WAL, PRAGMA busy_timeout=5000)
Read .venv aiosqlite/core.py:150-160 (_execute: partial, create_future, _tx.put_nowait((future, function)), await future),
  191-197 (commit/rollback through _execute)
Read storage/sqlite_factory.py:16-24 (default_factory returns aiosqlite.connect(db_path) unwrapped)
Read tests/test_ad1326_procedure_ledger.py:1492-1521 (the orchestrator's begin test: BEGIN armed with
  OperationalError("database is locked"), ROLLBACK armed with RuntimeError; fired == ["BEGIN IMMEDIATE"]; no ERROR);
  1464 (rollback_error = OperationalError("simulated rollback failure"): its text has no "no transaction is active")
Read execution/workspace_results.py:439-453 (await_result_task: shield, loop while not done, re-raise CancelledError)
Grep "create_task|ensure_future" .github/copilot-instructions.md -> 232-233, 273 (keep a reference; ensure_future banned);
  scripts/check_architecture_principles.py:195-199, 652-677 (unowned-task = bare-expression create_task/ensure_future only;
  broad_create_task_calls 1071 is reported, not gated; no test reads it)
Grep "requires-python" pyproject.toml -> 9 (>=3.12)
Read procedure_store.py:913-952 (_get_index_row as built), 87 (superseded_by TEXT NOT NULL DEFAULT ''),
  1186 (deactivate's UPDATE sets is_active = 0, superseded_by), 1792-1877 (find_duplicate_candidates: detects only), 1879-1951
  (merge_procedures: both must be active; deactivate(duplicate_id, superseded_by=primary_id) at 1951)
Read dreaming.py:875-883 (Step 7f: "Dedup detection (flag only, no auto-merge)")
Read tests/test_ad1326_procedure_challenger.py:1551-1574 (completed-promotion test; R3 premise _matched_ids == [] at 1564),
  1686-1708 (superseded by another id: _matched_ids == [] before and after)
Read verifier_independence.py:68-88 (an empty basis -> unknown at 78-79; adding a model cannot remove a None family at 86),
  124-144 (provenance: only independence depends on crew_models)
Grep "VerifierJudgePolicy\(|_CREW =" tests/test_ad1326_*.py -> 45 (_CREW three Claude models), 136, 142, 731-743: every crew non-empty
Grep "no pairing routes|routes one" (repo, prompts excluded) -> storage_declarations.py:246 only (progress-era-5 hit unrelated)
Grep "never routes|no pairing|whatever the restore path|by any restore path" prompt + src/probos/cognitive -> D9 F7, Section 2
  bars_routing, 3g, Section 4, Section 12 (_reconcile docstring, _retire comment), Acceptance 17, Blind spot 4

Review round 5 (2026-10-14; frozen candidate in this worktree = D12 + the orchestrator's round-3 tests + the Builders' tests)
Read logs/architect/review-ad1326-r5.md (findings 1-4), probe-ad1326-r5-findings.out (F1, F2 reproduced; PREMISE FAILURES: none)
Read prompt Section 2 (as revised in D12): get/list_by_status/pending_count/comparisons/recent_cycles execute on self._conn()
  without self._lock; self._lock appears only in __init__ and the five "async with _write_transaction(self._lock, ...)" writers
Read procedure_store.py:739-757 (get: SELECT content_snapshot only; Procedure.from_dict(json)); git show a71575ec:...procedure_store.py
  | grep -> 652-670 (3f2 SEARCH: docstring 653, from_dict 667, debug log 669, each unique)
Read procedure_store.py:713-737 (sync_routing_index as built: the R3-3 SELECT is_active override at 730-736)
Read procedure_store.py:1190-1216 (deactivate: column UPDATE, then snapshot UPDATE in try/except pass), 598-623 (save: is_active and
  superseded_by columns from the same object as the snapshot), 1626-1649 (archive), 1703-1723 (restore_procedure: both swallow)
Grep "is_active = [01?]|superseded_by = \?|SET is_active" procedure_store.py -> UPDATE writers 1197, 1628, 1705 only
Grep "superseded_by|is_active" procedures.py -> 84, 88 (mutable dataclass fields), 153, 157 (from_dict)
Grep "is_active INTEGER|superseded_by TEXT" procedure_store.py -> 84 NOT NULL DEFAULT 1, 87 NOT NULL DEFAULT ''
Grep "(procedure_store|_store|store)\)?\.get\(" src/probos -> ProcedureStore callers: procedure_challenger.py 354, 393, 426, 516, 540;
  dreaming.py 1890, 2158, 2238, 2476; cognitive_agent.py 1824, 2771, 7532, 7555; proactive.py 2029; diagnostic_context.py 299;
  commands_procedure.py 180, 271, 358, 393, 401, 588, 636, 637; routers/procedures.py 57, 161, 285, 315, 319 (other hits: other stores)
Read cognitive_agent.py:7528-7559 (promotion/demotion: compilation_level and name only, no save)
Read prompt Section 12 _contest/_reconcile (champion via store.get; predicate champion.is_active / champion.superseded_by)
Grep "\.(list_by_status|pending_count|comparisons|recent_cycles)\(|_challenges\.get\(" src/probos -> procedure_challenger.py 269
  (prepare), 330, 333, 365, 395, 400, 429, 462, 489, 515, 595, 598; procedure_store.py:945 (_get_index_row); no recent_cycles caller
Grep "_challenger\.(prepare|submit|run_cycle)\(" src/probos -> dreaming.py 832 (run_cycle), 1917/1942, 2053/2079, 2261/2286
Grep "self\._attempt_procedure_evolution\(" src/probos -> dreaming.py 2162 (on_task_execution_complete, 2117-2168), 2480 (proactive scan)
Read tests/test_ad1326_procedure_ledger.py:1595-1683 (_QueueingConnection: rollback_gate, commit passthrough; queueing fixture),
  1998-2011 (_FaultingFactory.connect builds _FaultingConnection), 2025-2069 (R3-3 test: stale.is_active is True at 2053),
  2102-2110 (_stage_active_challenger), 120-127 (_running_store)
Read tests/test_ad1326_procedure_challenger.py:372-385 (_rig(..., dreaming=...)), 1551-1586 (completed-promotion test)
Grep "storage_declarations|reconciled by|cognitive.procedure-challenges" tests -> test_ad1326_procedure_ledger.py:1003-1005
  (declaration exists, canonical_path only; no notes text pinned)

Review round 6 (2026-10-14; frozen candidate in this worktree = D13 built)
Read logs/architect/review-ad1326-r6.md (findings 1-2)
Read procedure_store.py:1691-1733 (restore_procedure: column UPDATE 1706-1711 sets is_active=1, is_archived=0, compilation_level=1;
  snapshot UPDATE 1713-1724 in try/except pass; then get + _save_to_chroma 1728-1730)
Read procedure_store.py:1036-1064 (promote/demote_compilation_level: UPDATE compilation_level column only, no snapshot write)
Read procedure_store.py:1550-1569 (decay_stale_procedures: column and snapshot both)
Grep "compilation_level = \?|compilation_level = 1|is_archived = 1" src/probos -> procedure_store.py 1042, 1057, 1556, 1708, 1630
Read cognitive_agent.py:1822-1864 (procedure = store.get; effective_level = min(procedure.compilation_level, max_level) 1848;
  <=1 returns None 1851-1854; level 4+ zero-token replay 1864), 7522-7566 (next_level = proc.compilation_level + 1, from get)
Grep "is_active INTEGER|superseded_by TEXT" procedure_store.py -> 84 NOT NULL DEFAULT 1, 87 NOT NULL DEFAULT '' (routing_state's tuple
  equals the old "is_active = 0 AND superseded_by = ?" predicate exactly)
Grep "^    (last_used_at|compilation_level|is_archived|superseded_by|is_active):" procedures.py -> 80, 84, 88, 92, 93 (test fields exist)
Grep "LIFECYCLE_ARCHIVE_DAYS\s*[:=]" src/probos -> config.py:292 (90); archive_stale_procedures 1595-1633 selects level 1, active,
  last_used_at > 0 and < cutoff
Read procedure_challenger.py:73-85 (ChallengeProcedureStore: get, save, deactivate, get_evolution_metadata, sync_routing_index),
  353-420 (_contest, _reconcile), 505-561 (_complete_promotion), 425-428 (_judge_record: get None -> None)
Grep "^class |^def " procedure_challenger.py -> class ProcedureChallenger 222 .. build_procedure_challenger 657 (body about 433 lines;
  round 6 adds about 8)
Grep "def sync_routing_index|def get_evolution_metadata" tests -> test_ad1326_procedure_challenger.py:234, 237 (_CrashingStore only)
Read tests/test_ad1326_procedure_challenger.py:211-238 (_CrashingStore), 402-457 (_pend, _matched_ids, _activate re-saves through
  get + save, _count_win)
Read tests/test_ad1326_procedure_ledger.py:2036-2100 (_snapshot_lineage; R3-3 test with the R5-2 get lines at 2083-2084;
  procedures_db.arm(...) on the store's real connection)
Read docs/development/architecture-baseline.yaml:606-614 (ProcedureStore srp-size row: triggers lines, methods; no count)
Grep "srp-size|triggers" scripts/check_architecture_principles.py -> 557-577 (finding carries triggers), 937-943 (baseline compares
  the trigger tuple only)
```

## Hidden Pins Enumerated (by method, per file)

| Method | Ran | Hits | Effect |
|---|---|---|---|
| `procedures` table columns / `PRAGMA table_info` / `sqlite_master` | Grep `PRAGMA table_info\(procedure\|sqlite_master` in `tests/test_procedure*.py` | `test_procedure_last_used.py:79`, `test_procedure_learned_via.py:71`, `test_procedure_store_promotion.py:36`, `test_procedure_store.py:298,304` | None: no column or table of `procedures.db` changes (D1). |
| Dream step numbering / step counts | Grep `dream.*step.*(count\|len)\|STEP_NAMES\|_DREAM_STEPS\|steps == \[` (case-insensitive) in `tests/` | none relevant | None. |
| AD-1156 learner census of `dreaming.py` | Read `test_ad1156_plan_mode_learning.py:866-902` | `_outcome_evidence` callers, `recall_by_intent` only in `_recall_evidence_by_intent`, its three callers | None: no function added to `dreaming.py`; the service filters with `episode_ran_in_plan_mode` in its own module. |
| `EventType` size / persistence tables | Grep `len\(EventType\)\|== 28\b\|(28, 368)\|== 36\b\|396\b` in `tests/` | `test_ad1195_durable_event_seam.py:326-330`; `test_ad1195_event_persistence_contract.py:394-406, 446-451, 502-508, 586`; `test_ad1195_durable_producers.py:35-68, 161, 171`; `test_ad1195_eventlog_pair_freeze.py:495` | Section 11. `test_events.py:57-60, 404-442` (value == name, registry scan) pass unchanged. |
| Config facade | Grep `field_definitions\|1844` in `tests/`; Read `test_ad1270e1_config_facade.py:1515-1552` | `:1549` | Section 8b; baseline regenerated (8d). |
| Pinned default dumps | Grep `EXPECTED_DUMPS\|'DreamingConfig'` in `test_ad1270e2b_cognition_models.py` | `:92-140`, used at `:355`, `:384`, `:431` | Section 8a. The identity test `:296-305` reads the regenerated baseline. |
| Default-config digest | Read `test_ad1152_agentic_correlation.py:215-283, 473-484`; `git show b84591a6 -- tests/fixtures/ad1152_agentic_off_golden.json` | pops for post-capture fields; AD-1327 regenerated both digests | Section 8c pops instead of regenerating (deterministic, reviewable). |
| Config reference | Read `test_config_reference_current.py:1-50` | `gen_config_reference.py --check` | Regenerated (8d). |
| Config profiles | Read `check_config_profiles.py:1-30` | gate 3 default-False only | None (flag defaults True). |
| Store registry | Read `check_store_registry.py:1-90`; Grep `len\(\|canonical_path` in `test_ad1256_store_registry.py` | `>= 8` declarations only | Section 4 declares the new schema module; `store-baseline.yaml` unchanged. |
| Backup coverage | Read `test_ad1265_backup_coverage.py:62-121` | every `*.db` literal must be discovered | `"procedures_challenges.db"` (`procedure_store.py` 3d) is planted at `data/procedures_challenges.db` and discovered: no exclusion needed. |
| `asdict` / `fields()` of extended dataclasses | Grep `EvolutionResult\(\|asdict\(` in procedure tests; Grep `asdict` in `test_ad1325_boundaries.py` | keyword constructions only (`test_ad579c_validity_dream.py:170`, `test_fallback_learning.py:1343,1367,1406`); `asdict(request)` of `LLMRequest` at `test_ad1325_boundaries.py:226` | None: new `EvolutionResult` fields are defaulted and last; `LLMRequest` gains no field. |
| Tier pins | Grep `tier ==\|\.tier\b\|"standard"` in procedure/fallback tests | `test_procedure_extraction.py:348` (extraction standard) | None: extraction is unchanged. |
| `ProcedureStore` connection counting | Grep `ProcedureStore\([^)]*connection_factory\|connect_calls` in `tests/` | `test_procedure_evolution.py:745` (never calls `start`), `test_ad487_self_distillation.py:157` (other store) | None. |
| `init_dreaming` / `DreamingEngine` kwargs | Grep `init_dreaming\|startup\.dreaming` in `tests/` | none | None. |
| Census of AD-1327 importers | Grep `VERIFIER_TIER\|verifier_independence\|JudgeProvenance\|is_persistable_judge_model\|answered_model` in `tests/` | 5 files; no importer census | None. |
| SRP / layers | Read architecture checker gating categories and thresholds | `ProcedureStore`, `DreamingEngine` rows keep their triggers | New classes stay under 500 body lines and 15 methods (`ProcedureChallengeLedger` 14, `ProcedureChallenger` 14, `ProcedureJudge` 5; the checker fires above 15, `check_architecture_principles.py:566-569`). |
| `DreamingEngine` built without `__init__` (revision; executed) | Grep `__new__\([^)]*Dream\|Dream\w*\.__new__` in `tests/` (12 hits, 9 files; the two `DreamAdapter.__new__` hits in `test_ad567a_anchor_metadata.py:243`, `test_bf498_emergent_phase_tag.py:118` are another class); then Grep `\.(dream_cycle\|_evolve_degraded_procedures\|_attempt_procedure_evolution\|_process_fallback_learning\|on_task_execution_complete\|proactive_procedure_scan\|consolidate_for_shutdown)\(` in the seven engine files | Ten engine constructions: `test_ad541c_retrieval_practice.py:416`, `test_ad598_importance_scoring.py:366,384`, `test_dream_step_7e.py:80`, `test_dream_step_7f.py:32`, `test_fallback_learning.py:123`, `test_gap_dream_integration.py:14`, `test_trust_concurrency.py:220,266,299`. Only `test_dream_step_7f.py` (7 calls) and `test_fallback_learning.py` (15 calls) reach a method that reads `_procedure_challenger` (the four 13d-13g sites) | 13h, 13i. The other eight run none of those methods; the orchestrator's full run on the first draft agrees (they passed; the 15 failures were all in these two files). |
| Connection reach of the BF-882 last resort (revision; executed) | Read `startup/shutdown.py:441-470`; Read `tests/fixtures/runtime_lifecycle.py:401-413` (the test-side twin) | one attribute level of `vars(component)`, `aiosqlite.Connection` closed, `sqlite3.Connection` reported only | D1b: the ledger's connection is a direct attribute of `ProcedureStore` (`_challenges_db`). |
| Tests that enumerate a runtime component's connections (revision) | Grep `direct_connection_attributes\(\|_direct_connections\b\|broken_stop_connections\|\["_db"\]` in `tests/` | `test_issue1419_failed_start_rollback.py:2487` (only the four `_BREAKABLE_BEFORE_CLEANUP` components, not `_procedure_store`), `:2525` (`any(...)`), `:2881`, `:2947` (acm, identity_registry only); `:1896`, `:1913` are runtimes without a `ProcedureStore` or a synthetic component | None: `ProcedureStore` now lists `["_challenges_db", "_db"]` and no test pins its list. |
| `ProcedureStore` factory connect count (revision) | as the `connection counting` row above | unchanged by D1b: the first draft already connected `procedures_challenges.db` through the store's factory, and the full run passed those files | None. |
| R1: test-side readers of the candidate rendering (F2) | Grep `Purpose\|If it fails\|   Expected:\|Postcondition:\|Precondition:\|\*\*Step` in `tests/test_ad1326_*` | `test_ad1326_procedure_challenger.py:70-74` (`_PROMPT`) | Moves: the two candidate patterns drop `Purpose: ` (Tests, "R1 pin"). |
| R1: config bounds and descriptions (F6, doc) | Read the config facade test and checker; the Builders' `test_ad1326_config.py` | `test_challenger_bounds_reject_out_of_range` (accepts `min_decisions=20`, per the orchestrator) | Moves (Tests); baseline and reference regenerated again (8d); 8a, 8b, 8c and `public_names == 305` do not move. |
| R1: SRP of the classes this revision grows | Count methods in the revised Sections 2, 3, 12 | `ProcedureChallenger` 15 (`_reconcile` added; the checker fires above 15), `ProcedureChallengeLedger` 14 (unchanged), `ProcedureStore` +1 (`sync_routing_index`; debt row with triggers only) | None, but `ProcedureChallenger` is now at the limit: any further method trips `check_architecture_principles.py` (hard stop 3). |
| R1: event pins | Section 11 table | same member, same payload keys; new reason strings `pending_limit`, `restored_promotion` | None. |
| R1: store registry | Section 4 | `notes` text of the declaration only | None expected; `check_store_registry.py --check` runs in the M1 gate. |
| R1: `fresh_episodes[:10]` literal in tests | Grep `fresh_episodes\[:` in `tests/` | none | None. |
| R2: SRP of the classes this round touches | Count methods in the revised Sections 3 and 12 | `ProcedureChallenger` 15 (no method added: the retire and promotion gates live in `_retire`/`_complete_promotion`, the fill order in the module-level `split_held_out`), class body about 440 lines by hand (limit 500); `ProcedureStore` +0 (3g edits `_get_index_row`) | None; `check_architecture_principles.py --check` runs in the M1 and M3 gates (hard stop 3). |
| R2: the ledger's file name | Grep `procedure_challenges\.db` (repo, logs excluded) | `procedure_store.py:286, 296` (3d), `storage_declarations.py:224` (Section 4), `procedure_challenges.py:11` (Section 2 docstring), `tests/test_ad1326_procedure_ledger.py:103, 247, 284, 841, 863, 865, 877, 907` | Moves to `procedures_challenges.db` everywhere (this contract renamed every occurrence). `check_store_registry.py` checks only `canonical_path` uniqueness (`:1156-1162`); `test_ad1265_backup_coverage.py` plants the new literal and discovers it (no exclusion). The module name `procedure_challenges.py` and the declaration id `cognitive.procedure-challenges` do not change. |
| R2: backup discovery order | Read `backup_inventory.py:250-299`, `backup.py:271-300` | sort by `(root_name, str(relative_path))` at `:298`; copied in that order at `:284` | Pinned by `test_backup_copies_the_ledger_after_procedures_db` and row 48. |
| R2: tests that assert a `find_matching` result | Grep `\.find_matching\(` in `tests/`; Read the AD-1326 callers | `test_procedure_store.py:466` (no index), `:500, 535` (active rows only); `tests/test_ad1326_procedure_challenger.py:1329` (stale-entry premise), the ledger test `test_sync_routing_index_rewrites_the_entry_from_sqlite` (same premise) | Both premises move to `_index_says_active` (Tests, R2). Result keys unchanged, pinned by `test_find_matching_admits_only_rows_active_in_sqlite`. |
| R2: tests that pin the old promotion order | Read `tests/test_ad1326_procedure_challenger.py:1213-1259` | `:1229-1230` (champion inactive in both variants), `:1249` (`_matched_ids == []`) | Move for `upsert_fails` (Tests, R1 (F1) entry): the champion stays active and routes until the challenger's entry takes. |
| R2: tests that pin the pinned split | Read `tests/test_ad1326_procedure_challenger.py:544-575`; Grep `held_out_episode_ids` in `tests/test_ad1326_challenger_e2e.py` (Builder) | `:562-564`, `:573-574` | Move (Tests, R1 (F3) entry). `test_fallback_rewrite_prompt_quotes_no_held_out_turn` asserts only that `e1` is first-used and no held-out episode is of the turn; if its built form pins exact held-out ids, they become `e3, e4` (five episodes, `e1` pinned). |
| R2: event, config and registry artifacts | Section 11 table; Sections 7-8 | no new member, payload key, reason string or config field | None: no regeneration. |
| R3: SRP counts | Count methods in revised Sections 2, 3, 5, 12 | `ProcedureChallenger` 15 (unchanged), `ProcedureChallengeLedger` 14 (helper is module-level), `ProcedureJudge` 5 (`compare`/`_ask` signatures only), `ChallengeRecord` +1 property, `ProcedureStore` +0 (3f, 3g edit existing methods, about +25 lines; its row's triggers `lines`, `methods` are already set) | None; `check_architecture_principles.py --check` (hard stop 3). db-connect stays 30 (no new `connect`). |
| R3: `recall_by_intent` fakes and argument assertions (R3-4) | Grep `recall_by_intent` in `tests/`; Grep `recall_by_intent\.(assert\|call_args\|await_args)` | method fakes: `test_ad579c_validity_dream.py:67` (no `k`), `test_ad1326_challenger_e2e.py:135`, `test_ad1326_dreaming_challenger.py:144` (`k: int = 5`); every other hit is `AsyncMock`, the real memory, or the AD-1156 census (`test_ad1156_plan_mode_learning.py:884-902`, names only); no argument assertion | 13j moves `test_ad579c_validity_dream.py:67`. The AD-1156 census does not move (no function added). `test_producers_cap_recall_at_the_shared_limit` holds (13a-3 note). |
| R3: `ProcedureJudge.compare`/`_ask` callers (R3-1) | Grep `\.compare\(\|_ask\(\|def compare` in `tests/test_ad1326_*` | `test_ad1326_procedure_judge.py:179, 635, 706, 720, 753` call `compare` by keyword without `optimizer_model`; no test calls `_ask` | None: the new keyword defaults to `""` (today's verdict). |
| R3: optimizer models in AD-1326 rigs (R3-1) | Grep `optimizer_model\|_DEEP_MODEL =\|answered_model=` in `tests/test_ad1326_*` | optimizers `claude-sonnet-5.5` (`test_ad1326_procedure_challenger.py:282`), `claude-opus-4-6` (e2e `:50`, dreaming `:55`); challenger-rig judges answer `claude-sonnet-4-6` | Expected none: a Claude optimizer adds a family the Claude crew already has, so a label can change only where it was not already `same_model`/`same_family`, and counting changes only under an independent verifier whose answers are Claude (none found). The orchestrator's full run confirms. |
| R3: ledger writers' behaviour (R3-2) | Grep `commit\|in_transaction` in `tests/test_ad1326_*`; Read `test_ad1326_procedure_ledger.py:56-75` | `_FailingScriptConnection` (only `start`'s `executescript` fails; `start` unchanged) | None. `test_add_challenger_enforces_the_pending_cap_atomically` runs the count and insert inside one `BEGIN IMMEDIATE` now; same result. |
| R3: `find_matching` results (R3-5) | Grep `_matched_ids(store) ==\|_routed_ids(store) ==` in `tests/test_ad1326_*`; `.find_matching(` in `tests/` (R2 row) | moves at `test_ad1326_procedure_challenger.py:1504, 1555, 1595`, plus one new premise in the completed-promotion test (Tests, R3 pin moves); `_routed_ids` is `list_active` and does not move; non-AD-1326 callers have no ledger rows | Moves listed in Tests. Row 45 loses one killer (Mutation table). |
| R3: store registry and backup coverage | Section 4 | declaration `notes` text only; file name and `canonical_path` unchanged | None; `check_store_registry.py --check` in the M1 gate. |
| R4: SRP counts | Count methods in revised Sections 2, 3g, 5 | `ProcedureChallengeLedger` 14 (`_roll_back` is module-level, beside `_write_transaction`), `ProcedureJudge` 5 (`_ask` +3 lines), `ProcedureStore` +0 (`_get_index_row` +9 lines; its row's triggers `lines`, `methods` already set), `ProcedureChallenger` untouched (15) | None; `check_architecture_principles.py --check` (hard stop 3). db-connect stays 30. unowned-task unchanged: the one new `asyncio.create_task` is assigned and awaited (not a bare expression); `broad_create_task_calls` rises by one and is report-only (no test reads it). |
| R4: tests that assert the ledger writers' statements (R4-1) | Grep `fired ==\|open_at_fault\|in_transaction` in `tests/test_ad1326_procedure_ledger.py` | the R3 rollback tests (`fired == ["COMMIT", "ROLLBACK"]` `:1488`; the orchestrator's begin test `fired == ["BEGIN IMMEDIATE"]` `:1514`); `test_every_ledger_writer_runs_in_one_transaction` (AST: `.commit(` only in `_write_transaction` and `start`) | None: every path that issued `ROLLBACK` still issues exactly one, a refused `BEGIN` still issues none, `_roll_back` contains no `.commit(`, and the failed-rollback ERROR still carries the rollback's exception (logged inside `_roll_back`'s `except`). The `ROLLBACK` now runs in a task the writer awaits; `caplog` captures it (same thread). |
| R4: `find_matching` results (R4-2) | Grep `_matched_ids(store) ==` in `tests/test_ad1326_*`; Read the layouts with a superseded champion | moves: `test_ad1326_procedure_challenger.py:1564` (`[]` -> `["ch-a"]`, Tests "R4 pin move"); unchanged: `:1697`, `:1707` (champion superseded by another id), the raw-copy and `[pending]` refusal tests (champion active) | One premise moves. Result shape unchanged (base keys). |
| R4: judge provenance (R4-3) | Grep `VerifierJudgePolicy(\|_CREW =\|independence ==` in `tests/test_ad1326_*`; Read `classify_independence` | every policy in the AD-1326 tests has a non-empty Claude crew; a raise needs an empty basis | None: no existing label or `counted` moves. |
| R4: store registry | Section 4 | `notes` text only | None; `check_store_registry.py --check` in the M1 gate. |
| R5: ledger read behaviour (R5-1) | Grep `await (_ledger_view\|.*ledger\.(get\|list_by_status\|pending_count\|comparisons\|recent_cycles))\(` and `= asyncio\.create_task\((ledger\|queueing\|rig)` in `tests/test_ad1326_procedure_ledger.py` | every read runs after its writer task has finished (the two writer-task tests `:1761`, `:1966` read only after `_finish`/`_settle`); `:892` reads a detached ledger (`RuntimeError` is still raised, now inside the lock) | None. AST test `test_every_ledger_writer_runs_in_one_transaction` counts `_write_transaction` and `.commit(` only; the reads add neither. |
| R5: `get`'s `is_active`/`superseded_by` (R5-2) | Grep `UPDATE procedure_records SET (content_snapshot\|is_active\|superseded_by)` and `INSERT (OR REPLACE )?INTO procedure_records` in `tests/`; `fetchone.*return_value=\(json\.dumps` | `test_ad1326_procedure_ledger.py:2041` (the R3-3 test: `:2053` asserts the stale `is_active is True`); `test_procedure_store.py:558, 563` (malformed-snapshot rows inserted with default columns; only the valid saved row is read through `get`); no mocked one-column `get` cursor | One assertion moves (Tests, "R5 pin move"). `test_restored_pair_with_a_completed_promotion_is_recorded_promoted:1558-1559` reads a healthy `deactivate` (columns and snapshot agree): unchanged. |
| R5: test helpers | `_QueueingConnection`, `_FaultingFactory` | two optional switches (`commit_gate`, `wrapper`) with defaults that keep current behaviour | None for existing callers. |
| R5: SRP counts | Count methods in revised Sections 2, 3f, 3f2 | `ProcedureChallengeLedger` 14 (five `async with` lines and one docstring, no method), `ProcedureStore` +0 (`get` about +11 lines with its docstring, `sync_routing_index` -9) | None expected; `check_architecture_principles.py --check` (the `ProcedureStore` debt row's `lines` trigger sees a net increase of about 2 lines; if the baseline pins an exact count the orchestrator reports it, it is not a hard stop of this contract). |
| R5: store registry | Section 4 | `notes` text only | None; `check_store_registry.py --check` in the M1 gate. |
| R6: `get` reverted (R6-1) | Grep `store\.get\(` with `is_active\|superseded_by\|compilation_level` in `tests/test_ad1326_*`; the R5 rows above | `test_ad1326_procedure_ledger.py:2083-2084` (the R5 pin move) | Returns to its round-4 form (Tests, "R6 pin move"). The R5 stale-champion test is unchanged (its `get("ch-a")` reads a re-saved, healthy snapshot). |
| R6: `ChallengeProcedureStore` doubles | Grep `def sync_routing_index\|def get_evolution_metadata` in `tests/` | `_CrashingStore` (`test_ad1326_procedure_challenger.py:211-238`) only | Gains `routing_state` forwarding (Tests, "R6 helper"); without it every `_CrashingStore` test raises `AttributeError` in `_contest`. |
| R6: `_reconcile`'s signature | Grep `_reconcile\(` in `tests/` and `src/` | `_contest` only (Section 12) | None: private, one caller. |
| R6: SRP counts | Count methods in revised 3f and Section 12 | `ProcedureStore` 57 (+`routing_state`; debt row compares triggers only), `ProcedureChallenger` 15, body about 441 lines | None; `check_architecture_principles.py --check`. |
| R6: ledger wording (R6-2) | Grep `committed rows only` in `tests/` | `test_ad1326_procedure_ledger.py:1317`, `:2150`: docstrings of the independent-reader helpers (a second connection, which does see committed rows only, also after a failed rollback) | None: unchanged and correct; no test pins the ledger's own comment (mutation row 74 names it). |

**Could not check (Architect cannot execute):** the full suite on the revised contract (the orchestrator reruns it before any Builder); that the new last-resort unit test passes and kills mutation rows 6, 6b and 6c; that `check_store_registry.py` still passes with the ledger module's `ConnectionFactory` import removed (its rule reads source text, and the docstring keeps the word; `connection_factory_absent` is report-only either way); whether `--update-baseline` touches lines beyond those predicted; tests that boot a real runtime, degrade a procedure and count LLM calls (none found by grep, not proven absent); `check_seam_contracts.py` and `select_tests.py` rules for new modules. The promotion re-save premise (the old hard stop 1) is now executed, not assumed (Milestones).

**Could not check in review round 1 (Architect cannot execute):** that the revised contract installs from base and the full suite stays green; that rows 25-40 die and row 3 dies on its new killer; that `check_architecture_principles.py` counts `ProcedureChallenger` at 15 methods and still under 500 body lines (counted by hand); that Chroma's live collection accepts a test-side `monkeypatch.setattr` of `upsert`/`update` (the reviewer's probe injected failures there; if the object refuses attribute assignment, wrap the collection, test-side); that no existing `test_ad1326_*` test drives a promotion or `_contest` through a store double lacking `sync_routing_index` (grep found none by name, not proven absent); that `check_config_facade.py --update-baseline` touches only `DreamingConfig`/`SystemConfig` for the new bounds and descriptions; that the exact-equality claim of F4 holds bit for bit (it follows from every count being a multiple of 0.5 with the default prior, so the sums and the one division are exact).

**Could not check in review round 2 (Architect cannot execute):** that the revised contract installs from base and the suite stays green; that rows 41-48 die and rows 12, 25 and 36 die on their moved anchors and killers — in particular that the reverted closed form separates equal records in the R2-6 layout (reasoned from the reviewer's report that the ranking test with the reference between the challengers' ids kills it, not computed); that `_index_says_active` reads the live Chroma collection as written (`get(ids=..., include=["metadatas"])`, metadata key `is_active` from `_save_to_chroma`'s payload, `procedure_store.py:675`); that no test outside the AD-1326 files drives the real `CognitiveAgent._check_procedural_memory` over a deliberately stale index (grep found none by name); that `ProcedureChallenger`'s body stays under 500 lines (counted by hand, about 440); that no startup step or operator tool names the ledger file by its old name outside `src/` and `tests/` (grep of the repo, logs excluded, found none); the reviewer's real-agent seam (`r2-real-agent-admits-retired`) is not re-run by any test here: `find_matching` is the agent's only routing read (`cognitive_agent.py:1764`), and the tests assert at that seam.

**Could not check in review round 3 (Architect cannot run Python):** that the revised contract installs from base and the suite stays green; that rows 49-60 die and row 8 dies on its moved anchor; that `dataclasses.replace` on the frozen `VerifierJudgePolicy` passes `__post_init__` unchanged (standard semantics: `replace` calls `__init__`, the tier is unchanged); that explicit `BEGIN IMMEDIATE` on the `default_factory` connection behaves as at `fault_issue_filings.py:119` (same factory assumed, not traced) and that a cursor's `rowcount` is read correctly before `commit`; that a failed `ROLLBACK` leaves the next `BEGIN IMMEDIATE` failing (SQLite semantics, reasoned); that `test_ad579c_validity_dream.py:185` actually reaches the recall (13j is harmless if not); that the test-side connection wrappers can inject failures into the ledger's and the store's real connections as described (the orchestrator's probe did); the exact label changes in existing rigs under R3-1 (Hidden Pins row, reasoned); and that no test outside AD-1326 routes a procedure that also has a ledger row (none found by grep).

**Could not check in review round 4 (Architect cannot run Python):** that the revised contract installs from base and the suite stays green; that rows 61-71 die and rows 52-53 die on their moved anchors (row 64 rests on the scheduling order reasoned in the Mutation notes); that aiosqlite delivers a cancelled call's result without raising in the worker (the orchestrator's probe shows the BEGIN completing after cancellation, which implies it); that SQLite's refusal text for a `ROLLBACK` with no transaction contains "no transaction is active" in the bundled SQLite version (documented wording "cannot rollback - no transaction is active", not executed here); that a cancelled `BEGIN IMMEDIATE` which hits `busy_timeout` reaches the worker as "database is locked" and leaves no transaction (SQLite semantics, reasoned); that the test-side wrappers can queue a real `commit()` and then raise as described; that `test_flag_off_routes_a_restored_completed_promotion`'s restart keeps the Chroma entry active (the reviewer's probe did); and the full-suite effect of the R4-2 relaxation outside the AD-1326 files (grep found no non-AD-1326 test with ledger rows).

**Could not check in review round 6 (Architect cannot run Python):** that the revised contract installs from base and the suite stays green; that rows 34, 55, 67-69, 74 and 79-86 die on their killers (row 85's killer assumes `test_challenger_wins_and_routing_uses_it` asserts the champion no longer routes; row 68's assumes the `[superseded_by_another]` case leaves the champion inactive); that the rig can hold two pending challengers of one champion (`procedure_challenger_max_pending_per_champion` default, not re-read) and that its judge stub is the one `test_challenger_wins_and_routing_uses_it` uses; that `run_cycle` resumes a row set `promoting` by the test (D12's "a promoting row is resumed", not re-traced); the reviewer's restored-Level-1 probe end to end through the real `CognitiveAgent` (the new store test stops at the index and `find_matching`, which is where base `get` stops the chain); the class-body line count after the edits (by hand, about 441 of 500).

**Could not check in review round 5 (Architect cannot run Python):** that the revised contract installs from base and the suite stays green; that rows 72-78 die (74-78 rest on the read finishing before the gate is set under the mutant, reasoned from the reviewer's worker order BEGIN, UPDATE, SELECT, ROLLBACK); that a test-side `commit` wrapper cancelled while awaiting its gate never forwards the COMMIT (reasoned: the forward is after the await); that `find_matching` reaches `_get_index_row` for `champ` before any other await that the parked writer could block (it waits either way); that the `ProcedureStore` debt row in `architecture-baseline.yaml` tolerates a net change of about +2 body lines; that no non-AD-1326 test observes `get` returning column values that differ from a deliberately stale snapshot (grep found one, the R3-3 test); and that the `_contest` champion-inactive branch, which now also reads the columns, changes no existing AD-1326 outcome (every existing layout deactivates through a healthy `deactivate`, where columns and snapshot agree).

## Absence Verified (2026-10-13)

```
CLAIM: nothing compares an evolved FIX with its parent before the parent is retired
RUN:   Grep "\.deactivate\(" src/probos
FOUND: dreaming.py:1922, dreaming.py:2041, dreaming.py:2228, procedure_store.py:1838 (merge_procedures)
HOLDS: yes -- the three dreaming hits follow save() with no comparison (Read 1905-1926, 2025-2045, 2210-2232); 1838 is duplicate merging

CLAIM: no name used by this contract exists yet
RUN:   Grep "procedure_challenge|PROCEDURE_CHALLENGE|ProcedureChallenger|procedure_challenger" (repo, logs excluded)
FOUND: none
HOLDS: yes

CLAIM: no public helper transforms LLM text to NUL-free, bounded, strict-UTF-8 text
RUN:   Grep "surrogate" src/probos; Grep "def \w*(persistable|encodable|sanitize|sanitise|bound)\w*\(" src/probos/cognitive
FOUND: crew_verdict.is_persistable_judge_model (refuses, does not transform); capability_triage._clean (private, keeps NUL);
       trace_analysis._clip (private, collapses whitespace, keeps NUL); fault_report.py:136, mcp_server.py:108, repair_brief.py:58 (refusal checks)
HOLDS: yes -- bounded_text is the one public transform

CLAIM: no EventType member has been added since AD-1195
RUN:   git log --oneline -5 -- src/probos/events.py
FOUND: 8041302f (AD-1195) newest
HOLDS: yes -- this is the first; hence the pin list in Section 11

CLAIM: no consumer interprets an inactive, non-archived procedure row
RUN:   Grep "is_active = 0|is_active=0|not .*\.is_active|include_inactive" src/probos
FOUND: procedure_store.py:1073 (deactivate), 1504 (archive), 1776 (merge guard); dreaming.py:2179 (skip inactive parent); others are directives/duty
HOLDS: yes -- an inactive challenger is skipped or ignored everywhere

CLAIM: no test pins the rewrite functions' tier
RUN:   Grep "tier ==|\.tier\b|\"standard\"" tests/test_procedure*.py, test_fallback_learning.py, test_reactive_proactive_triggers.py, test_ad1156*, test_negative_*, test_compound_*, test_observational_*
FOUND: test_procedure_extraction.py:348 (extraction); test_fallback_learning.py:688,709,1627,1660 (MagicMock response fields)
HOLDS: yes

CLAIM: a plain deep request can be answered by the fast tier
RUN:   Read llm_client.py:1564-1567, 53
FOUND: fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]; _TIER_ORDER = ("fast", "standard", "deep")
HOLDS: yes -- deep, fast, standard; hence min_tier="standard"

CLAIM: nothing in src reads a `.challenges` attribute today, and the ledger writer names are free except `set_status`
RUN:   Grep "\.challenges\b" src/probos; Grep "\.(set_status|add_challenger|record_comparison|increment_cycles|record_cycle)\(" src/probos
FOUND: no `.challenges`; set_status at startup/finalize.py:145 (tray) and task_sessions/__init__.py:323,336,382,410
HOLDS: yes -- hence the per-module (not per-name) census in test_ledger_writes_and_the_event_have_one_owner

CLAIM: shutdown consolidation runs no LLM step (so never Step 7d-2)
RUN:   Read dreaming.py:314-403
FOUND: micro_dream, _prune_weights, _consolidate_trust only
HOLDS: yes

CLAIM (revision): no test other than the two fixture files builds a DreamingEngine without __init__ AND runs a method reading _procedure_challenger
RUN:   Grep "__new__\([^)]*Dream|Dream\w*\.__new__" tests/ ; Grep the seven method names (Hidden Pins row) in the seven engine files
FOUND: ten engine constructions in seven files; method calls only in test_dream_step_7f.py (7) and test_fallback_learning.py (15)
HOLDS: yes -- and executed: the orchestrator's full run failed only in those two files

CLAIM (revision): no test pins ProcedureStore's direct connection attributes or the set of last-resort log lines of a real boot
RUN:   Grep "direct_connection_attributes\(|_direct_connections\b|broken_stop_connections|\[\"_db\"\]|_last_resort_messages\(caplog\) ==" tests/
FOUND: test_issue1419_failed_start_rollback.py:2487 (four other components), 2525 (any), 2881/2947 (acm, identity_registry), 1913 (synthetic runtime); fixtures/runtime_lifecycle.py:401, 471
HOLDS: yes -- a second direct connection on ProcedureStore moves no pin

CLAIM (revision): BF-882's last resort does not traverse into a component's attributes
RUN:   Read startup/shutdown.py:441-470
FOUND: list(vars(component).items()) filtered by isinstance; no recursion; docstring 455-458 states the limit
HOLDS: yes -- hence D1b

CLAIM (R1): the names review round 1 introduces do not exist yet in src
RUN:   Grep "sync_routing_index|source_correlation_id|PROCEDURE_EVOLUTION_EPISODE_LIMIT|pending_limit|restored_promotion|_reconcile\b" src/probos
FOUND: mesh/board_reconciler_ticker.py:72, 75, 80 (_safe_reconcile, another class)
HOLDS: yes

CLAIM (R1): no test pins the recall cap literal or the legacy log wording this revision changes
RUN:   Grep "fresh_episodes\[:" tests/ ; Grep "supersedes its parent|immediate supersession|keeps the legacy" tests/
FOUND: none; test_ad1324_router_fault.py:3 (a docstring about the model router, unrelated)
HOLDS: yes

CLAIM (R1): only the _PROMPT regex reads the old candidate rendering in the AD-1326 tests
RUN:   Grep "Purpose|If it fails|   Expected:|Postcondition:|Precondition:|\*\*Step" tests/test_ad1326_*
FOUND: test_ad1326_procedure_challenger.py:70, 73, 74
HOLDS: yes -- hence the R1 pin

CLAIM (R1): importing the limit from config_models into cognitive/dreaming.py crosses no checked layer
RUN:   Read tests/test_layer_boundaries.py:16-27, 152-165; Grep "config_models" scripts/check_architecture_principles.py
FOUND: LAYER_MAP has no config_models (-> None, allowed); the architecture checker has no config_models rule

CLAIM (R2): `_get_index_row` has exactly one caller, so 3g changes only find_matching
RUN:   Grep "_get_index_row" (*.py, repo)
FOUND: procedure_store.py:887 (find_matching), 899 (def)
HOLDS: yes

CLAIM (R2): no test outside AD-1326 builds a stale semantic index that find_matching is expected to return
RUN:   Grep "_chroma_collection\s*=" tests/ ; Grep "\.find_matching\(" tests/
FOUND: test_procedure_dedup.py:56, test_procedure_evolution.py:747, 772, test_procedure_store.py:465 (all set None);
       find_matching callers in tests: test_procedure_store.py (466 no index, 500 and 535 active rows) and the three AD-1326 files
HOLDS: yes -- only the two AD-1326 premises move

CLAIM (R2): nothing but the backup's discover order decides which of the two files is copied first
RUN:   Read backup.py:271-300; Read backup_inventory.py:250-299; Grep "IMMUTABLE_PATTERNS" backup_inventory.py
FOUND: one loop over discover() (284); discover sorts by (root_name, str(relative_path)) (298); IMMUTABLE only archives/ward_room_*.db (51)
HOLDS: yes -- neither file is linked from an older snapshot

CLAIM (R2): a challenger becomes active only after its ledger row is promoting
RUN:   Grep "is_active=True" in the Section 12 block; Read _promote and _reconcile
FOUND: one replace(challenger, is_active=True), in _complete_promotion, reached from _promote and _reconcile only after
       set_status(..., "promoting", expected=("pending",)) returned True, or from run_cycle's list_by_status("promoting")
HOLDS: yes -- so a ledger copied after procedures.db cannot say pending for an active challenger
HOLDS: yes

CLAIM (R1): no public ProcedureStore method rewrites one index entry from SQLite today
RUN:   Grep "_save_to_chroma\(|_write_to_chroma\(" src/probos/cognitive/procedure_store.py
FOUND: 521 (_rebuild_chroma_from_sqlite), 586 (save), 682/693/698 (the helpers), 1661 (restore_procedure); no public single-entry resync
HOLDS: yes -- hence sync_routing_index

CLAIM (R3): the judge never compared the optimizer's model before this round
RUN:   Read prompt Section 5 (pre-R3) compare/_ask; Grep "optimizer_model" src/probos/cognitive/procedure_judge.py
FOUND: _ask classified against self._policy only; no optimizer_model in procedure_judge.py
HOLDS: yes -- reproduced by the orchestrator (F1: independent, counted 4, promoted)

CLAIM (R3): DatabaseConnection has no rollback(), so the ledger rolls back with execute("ROLLBACK")
RUN:   Read protocols.py:325-358; Grep "ROLLBACK" src/probos
FOUND: execute, executemany, executescript, fetchone, fetchall, commit, close; about 30 execute("ROLLBACK") sites
       (identity_writer.py:195 alone calls db.rollback() on its own connection type)
HOLDS: yes

CLAIM (R3): no ledger writer rolled back on failure before this round
RUN:   Read prompt Section 2 (pre-R3) add_challenger, record_comparison, set_status, increment_cycles, record_cycle
FOUND: each "async with self._lock: execute ... commit" with no except clause
HOLDS: yes -- reproduced (F3: in_transaction True, next cycle promoted=0)

CLAIM (R3): the index payload carries no superseded_by, so sync_routing_index need only publish is_active
RUN:   Read procedure_store.py:672-682 (_chroma_payload)
FOUND: evolution_type, is_active, is_negative, compilation_level, intent_types
HOLDS: yes

CLAIM (R3): the Step 7d helper passes no k
RUN:   Grep "recall_by_intent\(" src/probos/cognitive/dreaming.py
FOUND: 1857 only: recall_by_intent(intent_type)
HOLDS: yes -- and executed (F6: [((), {})])

CLAIM (R3): only one test fake of recall_by_intent lacks k
RUN:   Grep "recall_by_intent" tests/
FOUND: method fakes at test_ad579c_validity_dream.py:67 (no k), test_ad1326_challenger_e2e.py:135, test_ad1326_dreaming_challenger.py:144;
       all other hits AsyncMock, real memory or name census
HOLDS: yes -- hence 13j

CLAIM (R3): the index activity filter is base behaviour (R3-6 pre-existing)
RUN:   probe F5 INFO (base find_matching); Read procedure_store.py:855
FOUND: where_conditions = [{"is_active": True}] at base and now
HOLDS: yes

CLAIM (R4): R3-2's handler never rolled back a BEGIN that was cancelled and then took effect
RUN:   Read procedure_challenges.py:156-175; Read aiosqlite/core.py:150-160
FOUND: begun = True only after "await db.execute('BEGIN IMMEDIATE')" returns; _execute queues the call before awaiting it
HOLDS: yes -- reproduced by the orchestrator (F1: in_transaction=True, next write "within a transaction")

CLAIM (R4): nothing but _complete_promotion and an operator merge sets a champion's superseded_by to a ledger challenger
RUN:   Grep "superseded_by=" src/probos; Grep "\.merge_procedures\(" src/probos; Read dreaming.py:875-883
FOUND: dreaming.py:1963, 2102, 2306 (legacy sites: superseded_by=result.procedure.id, a fresh rewrite with no ledger row);
       procedure_challenger.py:542 (_complete_promotion, after promoting); procedure_store.py:1951 (merge_procedures);
       procedures.py:157 (from_dict); merge callers: commands_procedure.py:645, routers/procedures.py:323 (operator only);
       Step 7f detects duplicates and does not merge
HOLDS: yes -- hence R4-2 (A) and Blind spot 16

CLAIM (R4): no AD-1326 test configures an empty crew basis, so R4-3 moves no existing label
RUN:   Grep "\(\s*\"\",\s*\"\",\s*\"\"\s*\)|crew_models=\(\)" tests/test_ad1326_*.py; Grep "VerifierJudgePolicy\(|_CREW =" tests/test_ad1326_*.py
FOUND: none; policies at test_ad1326_procedure_judge.py:136, 142, 731-743, all over _CREW or ("claude-sonnet-4-6",)
HOLDS: yes

CLAIM (R4): the unconditional refusal wording appears in src only in the registry note
RUN:   Grep "no pairing routes|routes one" (repo, prompts excluded); Grep "never routes" src/probos/cognitive
FOUND: storage_declarations.py:246; progress-era-5-unification.md:26 (AD-686 text, unrelated); never routes: procedure_challenges.py:200
       (bars_routing), procedure_store.py:924 (3g, already qualified in-sentence), procedure_challenger.py:390, 574 (SQLite deactivation)
HOLDS: yes -- changed: storage_declarations note, bars_routing, 3g; kept: procedure_challenger.py's two (they do not depend on the ledger)

CLAIM (R5): nothing holds the ledger lock and then calls a public ledger read (so locking the reads cannot deadlock)
RUN:   Grep "async def |_write_transaction|self\._lock" in the contract's Section 2; Read its five writer bodies
FOUND: self._lock only in __init__ and "async with _write_transaction(self._lock, self._conn) as db" in add_challenger,
       record_comparison, set_status, increment_cycles, record_cycle; their bodies call db.execute/fetchone only
       (add_challenger: _PENDING_COUNT_SQL on db; increment_cycles: its own SELECT on db); _write_transaction is module-private
HOLDS: yes

CLAIM (R5): the ledger reads that can overlap a write in another task are get (routing), pending_count (prepare) and the
       run_cycle reads; recent_cycles has no production caller
RUN:   Grep "\.(list_by_status|pending_count|comparisons|recent_cycles)\(|_challenges\.get\(" src/probos;
       Grep "_challenger\.(prepare|submit|run_cycle)\(" and "self\._attempt_procedure_evolution\(" src/probos
FOUND: procedure_store.py:945; procedure_challenger.py 269, 330, 333, 365, 395, 400, 429, 462, 489, 515, 595, 598;
       prepare/submit reached from dreaming.py 2053/2079 inside _attempt_procedure_evolution, called at 2162 from the
       on_task_execution_complete handler; no recent_cycles call
HOLDS: yes

CLAIM (R5): only a swallowed snapshot UPDATE makes get's JSON differ from the is_active/superseded_by columns
RUN:   Grep "is_active = [01?]|superseded_by = \?|SET is_active" and "await self\.deactivate\(|superseded_by" procedure_store.py
FOUND: column writers: save (INSERT OR REPLACE from the object that is also the snapshot, 600-623), deactivate 1197 (snapshot
       1211, except: pass), archive 1628 (snapshot 1643, except: pass), restore_procedure 1705 (snapshot 1717, except: pass);
       merge_procedures reaches the columns only through deactivate (1962)
HOLDS: yes -- hence R5-2 (A); Grep "(UPDATE|INSERT[A-Z ]*INTO) procedure_records" src/probos -> procedure_store.py only
       (round 6: true for is_active/superseded_by only; compilation_level is NOT covered, see the next claim)

CLAIM (R6): merging compilation_level into get changes what get returns without any swallowed failure
RUN:   Grep "compilation_level = \?|compilation_level = 1|is_archived = 1" src/probos; Read procedure_store.py:1036-1064, 1550-1569
FOUND: promote_compilation_level 1042 and demote_compilation_level 1057 write the column only (no snapshot write in either method);
       decay 1556 writes both (snapshot 1563-1566); restore 1708 (snapshot swallowed); archive 1630 (is_archived)
HOLDS: yes -- hence option (A) is rejected (D14)

CLAIM (R6): ChallengeProcedureStore has one test double; _reconcile has one caller; no routing_state exists at base
RUN:   Grep "def sync_routing_index|def get_evolution_metadata" tests; Grep "_reconcile\(" src tests; Grep "ChallengeProcedureStore|routing_state" src
FOUND: _CrashingStore (test_ad1326_procedure_challenger.py:234, 237); procedure_challenger.py:358 (the only call); the Protocol at
       procedure_challenger.py:73 and its use at 228; routing_state: no hit
HOLDS: yes

CLAIM (R6-2): the unconditional "committed" wording appears only where this round qualifies or already states the condition
RUN:   Grep "committed rows only|only committed|sees only committed|never sees|about to be rolled back|returns only committed|committed state|committed row" in the contract and tests
FOUND: contract: Section 2 module docstring (qualified), ledger get docstring and comment (qualified; row 74 moved), Acceptance 19
       (qualified), D13 R5-1 and D9/D11 (history, superseded by D14), Blind spots 14 and 17 (already conditional), the R5 test
       descriptions (successful-cleanup cases: correct); tests: ledger.py:1317, 2150 (independent second connection: correct)
HOLDS: yes
```
