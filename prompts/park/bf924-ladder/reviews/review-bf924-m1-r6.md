Agent is idle (waiting for messages). agent_id: 5e819834-4625-43ae-84eb-b204ea0d5a8c, agent_type: Diff Reviewer, status: idle, description: BF-924 M1 round 6: delta review of A6, elapsed: 2910s, total_turns: 1, model: gpt-6.1-sol

[Turn 0]
# BF-924 M1, round 6 — delta review

Reviewed frozen commit **`5aa7a25b5662c9b5f2d4f24b4dd6c72d91868bf3`**, tree **`66ff39c71cd640cff77bee0de3a0823e5115c38b`**. The checkout remained clean at that commit.

**Two ordinary-reach failures remain outside A6’s executable delta. They meet the brief’s condition for splitting D10’s activation.**

All Python execution used the required home guard. Below, `P` means `%TEMP%\bf924-review6-boundary`; evidence filenames refer to the brief’s `files` directory. Candidate probes printed and asserted:

```text
SOURCE D:\ProbOS-worktrees\bf924-review1\src\probos\__init__.py
```

## Findings requiring action before landing the active ladder

### 1. P2 — A metadata merge can relabel Guided successes as Level 3 successes

- **Reach:** ordinary.
- **Regression:** regression in effect of M1/D10’s activation; the stale writer predates A6. Reproduced on round five too.
- **Location:** **elsewhere in the ladder**, not A6’s executable delta.
- **Code:** `src/probos/cognitive/procedure_store.py:2062–2084`; production caller `src/probos/routers/procedures.py:326`.

`merge_procedures` reads the complete snapshot outside `_index_write`, then writes that snapshot back to update tags and intent types. It can restore an old compilation level **without resetting the counter earned at the current level**. Section 12’s closed writer list omits this writer.

**Executed:** `P\test_r6_merge_boundary.py`, through the real merge-route function, real store, and unmodified `EngineeringAgent` and `ArchitectAgent` actions/reports.

Receipts:

```text
Native Guided progression:       (column, snapshot, count)
                                (2,2,1), (2,2,2), (3,3,0)
Merge's snapshot read:           level 3
After real Architect failure:    (2,2,0)
After two Guided successes:      (2,2,1), (2,2,2)
After delayed metadata merge:    (2,3,2)
After one successful L3 replay:  (4,4,0)
Next intent's LLM calls:         []
```

Thus **two Level 2 successes supply Level 3’s threshold**, despite A6’s conditional increment. The real route returns `success: True`.

Evidence: `evidence-r6-review-merge-provenance.txt`; the same property fails in `evidence-r6-review-merge-provenance-r5.txt`.

**Smallest fix:** read the current snapshot inside the existing write block, or atomically update only tags and intent types. A metadata merge must not write a previously loaded compilation level.

---

### 2. P2 — A stale decay can restore autonomous replay after a committed failure demotion

- **Reach:** ordinary.
- **Regression:** newly relevant through D10’s live ladder; the stale AD-538 writer is unchanged by A6 and reproduces on round five.
- **Location:** **elsewhere in the ladder**.
- **Code:** `src/probos/cognitive/procedure_store.py:1657–1689`; production caller `src/probos/cognitive/dreaming.py:866`.

Decay selects eligibility and the snapshot before acquiring `_index_write`. Its later write does not recheck the level or recent use.

**Executed:**  
`P\test_r6_level_epochs.py::test_decay_does_not_raise_a_procedure_after_a_real_replay_failure`

The probe used a valid aged procedure, the real decay cursor, and an unmodified `ArchitectAgent` whose cached replay failed its actual proposal parser.

```text
Decay selected:                 level 5
After real replay failure:      (level=2, count=0)
After delayed decay:            (level=4, count=0)
Next real agent's decision:     cached=True, compilation_level=4
Next intent's LLM calls:        []
```

The decay receipt calls this “5 → 4,” but the committed transition is actually **2 → 4**.

The serial control discriminates: after the failure, a fresh decay read returns `[]`, leaves Level 2 intact, and the next intent makes the Guided `max_tokens=2048` request.

Evidence:
- `evidence-r6-review-level-epoch-and-decay.txt`
- `evidence-r6-review-level-epoch-and-decay-r5.txt`
- `evidence-r6-review-decay-control-and-failure-claim.txt`

**Smallest fix:** condition the decay write on the current eligibility/level values, skipping stale rows, or re-read and re-evaluate them under `_index_write`.

**Disposition for findings 1–2:** these cannot be filed as post-commit fixes while shipping the active candidate. Under the brief’s stated brake, **split D10’s activation into the new slice**. Fix these writers before activating that slice.

## Additional findings and claim corrections

### 3. P3 — An unconditional stale failure can raise a restored Level 1 row to Level 2

- **Reach:** **injected-only as demonstrated**: the probe saves an archived replacement while the failure holds its earlier read. I did not establish an ordinary production sequence for that replacement.
- **Regression:** the executable check-then-write race is unchanged by A6; A6 adds the unqualified safety claim.
- **Location:** **elsewhere in the failure ladder**, with an overclaim in A6’s documentation.
- **Code:** `cognitive_agent.py:2791–2795`, `procedure_store.py:1179–1180`; claim at `cognitive_agent.py:2744` and contract §18 R27, line `4658`.

**Executed:**  
`P\test_r6_level_epochs.py::test_a_stale_failure_does_not_raise_a_restored_level_one_row`

```text
Failure's read:        level 3
After real restore:   (1,0)
After stale failure:  (2,0)
```

Consequently, R27’s “it only lowers the level” claim is false across this interleaving. This does **not** produce autonomous replay.

**Smallest fix:** make demotion floor-preserving against the current persisted level atomically, while resetting the count. This need not condition failures on their executed level.

**Disposition:** schedule the runtime hardening with the activation work; correct the unqualified claim before treating R27 as verified.

---

### 4. P3 — A6 does not establish the claimed “since the level was set” invariant

- **Reach:** ordinary.
- **Regression:** A6 introduces the stronger proof claim; the numeric-level reuse behavior also occurs on round five.
- **Location:** **inside A6’s closed-list proof for the increment**, rather than a failure of its numeric equality predicate.
- **References:** contract lines `4531`, `4584`; predicate at `procedure_store.py:1096`.

**Executed:**  
`P\test_r6_level_epochs.py::test_a_return_to_the_same_level_accepts_successes_from_its_earlier_epoch`

Three real crew agents had already validated and acted successfully at Level 3, with their real completion awaits pending. A peer’s NO demoted the procedure; three Guided runs regained Level 3. Releasing the earlier successes committed:

```text
(3,1), (3,2), (4,0)
New validation calls after regaining Level 3: []
Next intent's LLM calls: []
```

**Answer to the epoch question:** successes can cross a demotion/re-promotion to the same numeric level and avoid every **new** Level 3 validation afterward. This trace is **not** a never-validated Level 4: three Level 3 validations occurred earlier.

**Smallest fix:** narrow the proof text to numeric-level equality and completion ordering. If fresh validation after every reset is required, an epoch/generation token is necessary; A6 does not provide one.

---

### 5. P3 — D29 leaves the old “Tests 18” receipt incorrect

- **Reach:** ordinary documentation use.
- **Regression:** neither; the round-five text finding is only partially closed.
- **Location:** **inside A6’s D29 text repair**.
- **Reference:** contract line `4471`.

I reproduced:

```text
git grep -n -E 'promote_compilation_level|demote_compilation_level' 96089844 -- src tests
27 hits: src 4, tests 23

git grep -n -E 'promote_compilation_level|demote_compilation_level' d9391617 -- src tests
32 hits: src 4, tests 28

git grep -n -E 'async def (act|report)\(' d9391617 -- src/probos
72 hits in 35 files
```

The corrected `RUN` paragraph agrees, but the following `FOUND` paragraph still says **“Tests 18.”**

**Smallest fix:** change that label to 23 and make the listed omissions explicit or include the two omitted test-name hits.

## Explicit property/checklist results

### Contracts at the boundary

**Store receipts verified through the real connection.**

- Matching snapshot level: increment persisted, return `1`, cursor `rowcount=1`.
- Moved level: no increment, return `None`, `rowcount=0`.
- Column/snapshot disagreement: snapshot governs.
- Missing level key: default `1` governs.
- Missing row: `None` with `expected_level`; legacy unconditional call returns `0`.
- Exactly one UPDATE and one SELECT were measured for the increment.
- The receipt SELECT runs while the write lock is held. A second same-store increment queued at the commit/read boundary; returns were `[1,2]`, not `[2,2]`.

I tested **66 writer interleavings**: eleven changes × before/after increment × executed levels 2, 3 and 4.

| Interleaving | Pending success’s observed effect |
|---|---|
| Snapshot moved away by demotion, promotion, decay or restore | Before increment: `None`, no count or pending promotion |
| Failure/reset while still at Level 2 | A later Level 2 success counts `1`; no promotion |
| Column-only change or migration | Snapshot remains authoritative; threshold promotion commits within the tested cap |
| Missing snapshot key | Defaults to 1; executed levels 2–4 do not count |
| Save to Level 2 | Counts `1` only for executed Level 2; higher executed levels do not count |
| Same-level save or return to the same numeric level | Counts `1` after the reset—hence finding 4 |
| Reset/move after the increment returned `3` | Conditional promotion refuses; the pending success announces nothing |

Exceptions in accounting remain non-fatal to the intent, as exercised by the result-path fault cases. A `None` acknowledgment exits before `get` or promotion.

### Closed lists and consumers

I ran these `git grep -n -E` enumerations:

```text
Scope                       Pattern                                      Count
src                         _record_compilation_outcome\(                    4
src                         record_consecutive_success                      2
tests                       record_consecutive_success                     36
agent                       "procedure_id": |\["procedure_id"\] =          12
src                         \.get\(["']compilation_level|\[["']compilation_level["']\]
                                                                            14
procedure_store.py          compilation_level = |consecutive_successes = 0  9
procedure_store.py          content_snapshot =|json_set\(|\["compilation_level"\] =
                                                                            11
```

The counter’s **36 test hits are in seven files**; the historical `d9391617` count is **33**, as the contract’s revision label states.

The three production call sites are:

- `cognitive_agent.py:2530`: Level 3 NO, unconditional failure.
- `:7722`: dispatched compound success.
- `:7890`: post-execution outcome.

The three procedure-associated decision producers carry their levels. I exercised **29 decision shapes** through real `handle_intent`, including Guided clamps from stored 3/4/5; Level 3 single, degraded and dispatched compound; Level 4/5 variants; Lieutenant and non-approved Commander clamps from 5 to 4.

There are now **three decision-level reads**: the pre-existing compound-dispatch read at `:7708`, plus the two accounting reads. Only the former governs dispatch, and its special branch remains `== 3`.

The writer list needs correction:

- Level-moving writers include **save, promote, demote, decay, restore, and the stale whole-snapshot merge**.
- Migration changes only the column.
- Deactivate and archive read their snapshots under the lock; executed controls preserved both level and count.

### Original round-five failure and untrusted runs

The required epoch/control, both stale-success cases and six additional-lifecycle cases passed: **10 passed**.

The four pending Guided outcomes each committed **`(3,0)`**; the next intent made the `max_tokens=100` validation request.

Clamped Ensign runs of stored Level 3/4/5 counted nothing. Lieutenant and non-approved Commander Level 4 replays of stored Level 5 counted nothing.

Ordinary recreation bypassed procedural matching and reached accounting with no procedure id/level. An explicitly injected cached recreation decision retained its level through the `proactive_think` action copy.

All three procedure-associated producers name a level. Ordinary LLM/fallback/recreation decisions may omit both id and level. An injected id-without-level decision produced the required DEBUG refusal and no count.

### Shared artifacts and production consumers

- **112 passed:** result paths, actual compound-target envelopes, real diagnostics/event/dreaming consumers.
- **602 passed:** all nine AD-1326 families plus stop inventory and seam registry.
- **44 passed:** scope/name audits and lifecycle/source-pin consumers.
- Real `CognitiveJournal` receipts for Level 4/5 single and compound replays persisted successfully and matched round five: procedure id, intent id and correlation were retained; no new journal field was passed.
- Task-event payload shapes remained unchanged in the probes.
- Method-name sets were unchanged: 203 agent methods, 58 store methods. `handle_intent` and `decide` ASTs were unchanged.
- `AsyncMock`/`MagicMock` receipt probes confirmed: `None` stops; configured integer proceeds normally; truthy mock receipts pass the `is None` check but their threshold comparison is swallowed. Those mocks do not prove the real store’s refusal behavior.

Named doubles in the new tests: `_KnownMatchStore` omits Chroma/ranking, not SQLite accounting; `ReplayTestAgent` inherits the real lifecycle/action; runtime/Ward Room doubles omit boot/routing/post persistence; memory callbacks omit recall/episode storage; LLM completion replacements supply deterministic replies. Production-agent and real-consumer probes cover the relevant seams beyond those doubles.

### Test discrimination and isolation

- Ten new cases each passed **alone in a separate guarded process**.
- The ten cases plus changed wrapper passed in actual file order: **11 passed**.
- Against round-five source: **9 failed, 2 passed**, for the stated reasons.
- The new `[unconditional]` case **does not fail when A6 is reverted**; it is a compatibility control. The changed wrapper also passes both sides.
- AST comparison found four appended functions, no removed functions, no changed old assertions, and no new skips or sleeps.
- The pending-outcomes test uses events around the real completion await, not timing sleeps.

Initial argument/collection failures were discarded; confined-root retries supplied the reported evidence.

### Cost, scope and receipts

Identical serial scenarios on candidate and round five produced:

- Single and compound ladder: **`2,2,3,3,3,4`**.
- Approved Commander: **`4,4,5`**.
- Identical measured SQL/LLM budgets. Six-turn SQL counts were **`20,20,26,20,20,27`**; Commander counts **`21,21,27`**.

No additional SQL statement or LLM call was measured on those serial paths. The receipt SELECT is now inside the lock; allocation and latency effects were not measured.

The other seven M1 files are blob-equal to round five. No generated/config/facade/event-schema file changed in A6’s delta. M2’s stable patch-id remains:

```text
520284855eb7e14f7b3d87eec8c2decd635fda93
```

R53–R59 and updated R37/R41/R47 each resolved to one whole stripped source line. I did **not** repeat the mutation campaign; **44/44 killed** is the orchestrator’s receipt, not my execution.

## Disposition and limits

**Before committing:** resolve findings 1–2 through the brief’s D10 split rule; correct the proof/receipt claims in findings 3–5. Do not ship the active ladder with findings 1–2 merely scheduled.

**Schedule with the activation slice:** the merge/decay writer repairs and the injected restored-row demotion hardening. Decide separately whether numeric-level completion ordering is sufficient or epoch freshness is required.

I did **not** run the 704-case focused matrix, full repository gate, M2 review, or mutation campaign. I did not validate live vessel state, Chroma ranking, provider transport, or allocation/latency performance. No vessel was started and neither prohibited data directory was opened. All reported guarded runs left zero redirected-home entries.

No A6-only CI break was demonstrated in the consumer families checked. The missing regression coverage belongs in AD-538 merge/lifecycle and compilation-trust concurrency tests.

**Verdict: NOT READY.**