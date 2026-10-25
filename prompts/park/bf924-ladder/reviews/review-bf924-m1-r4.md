## Findings — fix before commit

Reviewed `96089844ccaf390125900e9d8c87a8917910f903`, tree `226c5ded7677dba69669c6562461c4ede34a9d0d`. The checkout and index remain unchanged.

All findings below were **verified by execution**. Regression flags distinguish defects already present in the shared implementation from defects introduced by the repair.

### 1. P2 — A stale success overwrites a later NO demotion and disables validation

**Reach:** ordinary, concurrent intents  
**Regression flag:** neither — the non-atomic sequence predates the helper move; D21/D22 expose it through their new callers.

**Locations:**  
- `src/probos/cognitive/cognitive_agent.py:2739–2752`
- `src/probos/cognitive/procedure_store.py:1105`

The success path retains `new_count` and a procedure snapshot across awaits. `promote_compilation_level()` then updates by procedure id without checking whether that level/count is still current.

**Executed evidence:** `bf924r4-shared-outcome-real-ladder`, using `test_shared_outcome_order.py`, **both single-step and compound cases fail**.

The probe used real bus deliveries, two real agents sharing the store, and real **one-slot per-agent concurrency managers**. Five ordinary successful intents first produced levels:

```text
2, 2, 3, 3, 3
```

The measured interleaving was:

```text
success reads count 3 and Level 3
NO commits Level 2 / count 0
older success requests Level 4 while stored state is Level 2 / count 0
stored result becomes Level 4 / count 0
next intent makes zero LLM validation calls
```

The barriers controlled scheduling only. Store values and return values were not fabricated, and no operation failed.

**Why it matters:** the procedure becomes autonomous immediately after a validator rejected it. Per-intent accounting happens once, but the complete accounting decision is not atomic. Per-agent serialization does not protect a shared procedure.

**Smallest fix:** protect the complete per-procedure outcome transition across agents, or make promotion an atomic conditional update against the expected level and counter. The caller must receive a commit acknowledgement and announce promotion only when that conditional update succeeds. A per-agent lock is insufficient.

### 2. P2 — A healthy recovery completion is discarded by the real Counselor

**Reach:** ordinary  
**Regression flag:** neither — the recovery-context omission is pre-existing; D20 routes rejected compound replays into it.

**Locations:**  
- `src/probos/cognitive/cognitive_agent.py:7872–7876`
- `src/probos/cognitive/counselor.py:2873–2909`

The normal lifecycle adds `intent` before calling `act()` at `cognitive_agent.py:7567`. The recovery path does not.

**Executed evidence:** `bf924r4-ordinary-counselor-and-adapters-v2`, node `test_a_real_counselor_reaches_the_rejected_replay_through_normal_promotions`.

A real `CounselorAgent` completed three Guided intents, reached Level 3, then received an overall YES and a step NO. Its request limits were:

```text
100, 50, 2048
```

The recovery completion returned a nonempty answer. The decision passed to the Counselor was:

```text
action=execute, llm_output="the ordinary LLM answer", tier_used=standard
```

It lacked `intent="direct_message"`. Consequently, the Counselor did not take its conversational branch. The final result was:

```text
success=False, result=None, error=None
```

No `execution_failure` learning event was emitted.

**Smallest fix:** propagate the original intent into the recovery decision before `act()`, as the normal path already does. An independent in-memory shim adding **only that field** made the real Counselor return the answer successfully and emit the intended learning event.

### 3. P2 — The rejected-step reason disappears through `CounselorAgent.report()`

**Reach:** ordinary  
**Regression flag:** introduced by the repair’s new failure envelope

**Locations:**  
- `src/probos/cognitive/cognitive_agent.py:7729–7742`
- `src/probos/cognitive/counselor.py:2921–2926`
- `src/probos/cognitive/cognitive_agent.py:7952`

The new failure dictionary contains `success` and `error`, but no `result`. The Counselor preserves conversational dictionaries only when they contain `result`; otherwise it packages them under `data`.

**Executed evidence:** `bf924r4-ladder-and-real-counselor`, case `[no-recovery-decision]`.

The real report consumer received:

```text
{"success": False, "error": "Compound step 1 output failed Level 3 validation"}
```

It returned that dictionary nested under `data`. The lifecycle subsequently read top-level `result` and `error`, producing:

```text
success=False, result=None, error=None
```

The same empty envelope also occurred in the ordinary healthy-provider failure above.

**Why it matters:** the intent fails without the promised step reason. The production caller, `agent_chat()` → `_agent_chat_impl()` → `IntentBus.send()` (`routers/agents.py:2909`, `:3675`), takes its degraded-LLM response branch when both result and error are empty. That consequence was traced by reading the route; I did not invoke the HTTP endpoint.

**Smallest fix:** pass a complete failure envelope accepted by this consumer—for example, include `result: None`. An independent shim adding **only that field** preserved the original step error with recovery disabled.

### 4. P3 — The literal one-helper-call assertion is false

**Reach:** ordinary  
**Regression flag:** repair text

**Location:** `prompts/bf-924-trust-inputs-through-real-apis.md:3609`

A Level 3 overall NO calls the helper twice:

```text
(procedure_id, False)   # cognitive_agent.py:2529
(None, True)           # cognitive_agent.py:7863
```

`bf924r4-result-paths-v3` recorded this in every overall-rejection variant.

**There is no duplicate accounting write:** the second call is guarded and does nothing. The intended one-accounting-effect property holds; “no intent calls it twice” does not.

**Smallest fix:** describe one **per-procedure accounting effect**, explicitly acknowledging the guarded `None`-id call.

## Verification of the listed properties

Probe files are under `%TEMP%\bf924-review4-boundary`. Evidence files are beside the brief, named `evidence-<run-label>.txt`. Python/pytest execution used the required homeguard.

The probes printed and asserted:

```text
D:\ProbOS-worktrees\bf924-review1\src\probos\__init__.py
```

The reverted-fix run printed the external round-three copy’s `src\probos\__init__.py`, not the editable install in `D:\ProbOS`.

### 1. Boundary contracts and result-path sweep

`bf924r4-result-paths-v3`: **81 cases passed**, covering all 16 table rows through real `handle_intent` calls. No listed row was unreachable. Exception paths used deliberate faults; validation timeouts used a shortened real deadline.

These are the **isolated reference-consumer results** using the production base `act()`/`report()`. They do not establish the unconditional guarantees disproved above.

Here, **C/F/S** means calls to `record_completion` / `record_fallback` / `record_consecutive_success`. Demotion resets the consecutive count.

| Row | Cached decision and `act()` | C/F/S | Compilation outcome | Completion event and learning |
|---|---|---:|---|---|
| 1. Guided success | Not cached; one LLM-decision action | 1/0/1 | Promote 2→3 at threshold within cap; clamped success does not promote | `used_procedure=False`; no learning |
| 2. Guided failure | Not cached; one failed action | 0/1/0 | One reset at stored Level 2, or one demotion for a clamped higher level | False; no recovery or learning |
| 3. Overall NO/MAYBE/empty | No cached action; one LLM-decision action | 0/0/0 | One demotion to 2, count 0 | False; `validation_failure` |
| 4. Overall call raises/times out/error reply | Cached replay continues; one action for single-step, none for dispatched compound | 1/0/1 | Normal success accounting; no failure demotion | True; no learning; one warning per failed call |
| 5. Single-step YES | Cached; one action | 1/0/1 | Promote 3→4 at threshold | True; no learning |
| 6. Cached execution failure | One cached action, plus recovery action when available | 0/1/0 | One demotion to 2/count 0 | True; recovered success and `execution_failure`, otherwise failure without learning |
| 7. Level 3 compound degradation | Cached text; one action | 1/0/1 | Normal success accounting | True; unavailable-role learning only for unresolved role |
| 8. Step NO/MAYBE/empty | **No cached action**; only recovery action when available | 0/1/0 | One demotion to 2/count 0 | True; recovered `execution_failure` names step; otherwise failure with step reason for base reporter |
| 9. Dispatch failed/raised | Substituted text is validated | 1/0/1 or 0/1/0 | Accepted text promotes normally; rejected text takes row 8 | Corresponding row 11 or row 8 event/learning |
| 10. Step-validation call failure | Cached compound continues; no cached action | 1/0/1 | Normal success accounting | True; no learning; warning once |
| 11. All compound steps accepted | Cached; dispatched; no local action | 1/0/1 | Promote 3→4 at threshold | True; one compound completion event |
| 12. Level 4/5 single success | Cached; one action | 1/0/1 | 4→5 only when approved and Commander; otherwise capped | True; no learning |
| 13. Level 4/5 compound dispatch | Cached; no local action, including substituted failed-dispatch text | 1/0/1 | Same caps and threshold | True; one compound completion event |
| 14. Level 4/5 degradation | Cached text; one action | 1/0/1 | Same caps and threshold | True; unresolved-role learning only |
| 15. Level 4/5 formatting error | No cached action; one LLM-decision action | 0/0/0 | Level/count unchanged | False; `format_exception` |
| 16. Accounting exception | Hosting path continues | Hosting path’s metrics; selected accounting operation attempted once | Selected write fails and is swallowed | Hosting path’s event/recovery behavior remains |

Relevant boundaries: `cognitive_agent.py:2012`, `:2500`, and `:7680–7953`.

Additional execution:

- `bf924r4-actual-target-and-shapes`: **27 passed**—real target acceptance at Levels 3–5, plus all 24 role/resolved-type/step-count combinations. Received step fields and returned envelopes were checked, including matching intent/agent ids and a **10-second TTL**.
- The normal compound ladder was **2, 2, 3, 3, 3, 4, 4, 4, 4**, with one completion and one success-accounting call per turn.
- Level 3 two-target traffic was `[100, 50, 50]`; Level 4/5 traffic was empty.
- The approved Commander compound case reached Level 5.

A rejected step stops the compound replay; preceding deliveries remain. Recovery serves the whole intent, not merely the rejected step.

### 2. Claims and helper equivalence

`bf924r4-static-contracts-v2` verified:

- **45 nonempty stripped lines equal** the removed block, excluding the assignment.
- Exactly three call sites: `:2529`, `:7697`, `:7863`.
- No isolated intent performed two success/demotion/reset operations.

The unchanged exception policy now applies to new contexts. For example, an injected demotion failure on overall NO returned LLM success while the stored state remained **Level 3/count 2**. Compound accounting failures were swallowed too. These are operations the old early-return/NO paths did not attempt.

Measured SQLite work, with semantic ranking controlled:

| Workload | Round 3 → candidate SQL statements |
|---|---:|
| Single-step success at promotion threshold | 27 → 27 |
| Compound success below threshold | 15 → 20 |
| Compound promotion at threshold | 15 → 27 |
| Approved compound 4→5 | 16 → 27 |
| Overall NO | 12 → 17 |

The corresponding LLM call counts did not increase on that turn. These are SQL measurements, **not** provider token-savings measurements.

### 3. Reach and shared consumers

- `bf924r4-stop-and-shared-contract`: **28 passed**, including the complete AD-1343 seam inventory, Level 4 compound completion/event tests and lifecycle metadata pin.
- `bf924r4-structure-consumers`: **12 parameterized cases passed** from the identified changed-lifecycle structure pins.
- All **202 existing method names and signatures** were retained.
- Real diagnostics read the demoted Level 2.
- Real local runtime event dispatch and the actual startup listeners delivered both learning-event types.
- Step 7d was exercised with and without the production challenger. The real challenger factory and ledger saved an inactive Level 2 pending challenger; the fallback turn’s episode was not held out.
- The unhealthy overall-NO path made one reactive confirmation and caused Step 7d’s cooldown skip.
- `bf924r4-real-promotion-v4` verified one eligible compound promotion request, pending status, and persisted Ward Room thread/DM author fields.

The ordinary reach counterexamples are the real Counselor’s normal promotion sequence and two valid concurrent bus deliveries sharing a procedure.

### 4. D23 text and configuration

Verified against the real YAML-consuming ontology and Ward Room services:

- LaForge, Bones and Worf assignments exist.
- `get_post_for_agent("builder").reports_to` → `get_agents_for_post("chief_engineer")` resolved the registered LaForge id.
- Actual approver addressing matched corrected R17; it was not counted as a new finding.
- The old absence assertion is explicitly marked false and corrected.
- Both tracker entries at `refs/scratch/bf924-oracle-trk-g` match the corrected section 8 replacements.

### 5. Delta scope

Executed blob/AST comparisons confirmed:

- The other **seven M1 files** are blob-identical to `cb201c20`.
- All **nine Builder files** equal the M1 oracle.
- Repair source changes are confined to the three existing lifecycle methods plus the new helper.
- Validator and trust-helper ASTs are unchanged.
- No generated file, config model, event definition or persisted-schema file changed in the repair.

D10–D19 were not independently re-reviewed beyond paths reached by this repair.

### 6. Tests and process

- Six new cases passed **individually** and together in source order.
- The complete test file passed **32 cases in file order**.
- Against real round-three source, all six failed for the stated reasons: missing recovery call, cached action occurring, missing compound counts/promotion, missing Level 5 promotion, and unchanged Level 3/count 2 after NO.
- The previous 18 test functions are AST-unchanged; no deletion, skip or loosening was found.
- R37–R42 each match one whole stripped source line. **The mutation campaign was not repeated.**

Named stand-ins and their limits:

- `_KnownMatchStore`: real SQLite counters, snapshots and ledger; bypasses Chroma and semantic ranking.
- Scripted `complete`: real client interface, but no backend behavior or provider quality.
- Recall/episode mocks: omit memory work outside the accounting path.
- Namespace runtime/Ward Room: omit boot and real announcements; separate consumer probes covered announcements and local event dispatch.
- `ReplayTestAgent`: inherits permissive base `act()`/`report()`, masking the Counselor’s stricter contracts.
- Ordering barriers: control scheduling only; all shared-store operations return their real results.

## Follow-ups and limits

No additional follow-up-only finding was filed, and existing register entries were not duplicated.

I did **not** run the full repository gate/CI, repeat the 682-case Builder matrix or mutation census, access vessel/operator data, start the vessel, or make live provider requests. Listener enumeration found no identifiable local LLM service. Provider serialization, answer quality, billing/token savings, NATS transport, later challenger judging and all possible asynchronous interleavings remain unchecked.

The missing regression families are **shared-procedure outcome ordering** and **real-Counselor replay recovery/report integration**. Their acceptance probes fail now; the checked existing test families do not catch them.

## Verdict: **NOT READY**

Three ordinary-reach P2 defects remain, plus the inaccurate one-call acceptance statement.