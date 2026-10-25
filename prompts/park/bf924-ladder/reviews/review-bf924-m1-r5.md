Agent is idle (waiting for messages). agent_id: 8ccee31f-8270-49b4-8bf2-fce07ad091dd, agent_type: Diff Reviewer, status: idle, description: BF-924 M1 round 5: delta review of A5, elapsed: 2178s, total_turns: 1, model: gpt-6.1-sol

[Turn 0]
## Review result

**One runtime blocker and one P3 evidence correction.**

Reviewed frozen commit `d93916178f42464985f242d00068d4ad51a31f6b`, tree `e576a1b8b2a6c8f51a7034e25dff4c443eccdd6d`. The checkout remained clean.

All Python execution used the home-guard script. I used a TEMP copy whose **only change was its report directory**, verified by reversing that replacement and comparing it with the supplied script. Probes and comparison checkouts were created only under `%TEMP%`. Source receipts confirmed imports from the review checkout—or the explicitly selected temporary comparison source—not `D:\ProbOS\src`.

## Must fix before acceptance

### 1. P2 — Guided outcomes can supply the Level-4 threshold without any Level-3 validation

- **Reach:** ordinary concurrent intent execution.
- **Regression:** introduced in effect by BF-924 M1; **not newly introduced by A5**.
- **Code:** `src/probos/cognitive/cognitive_agent.py:2743–2758`, caller at `:7873`; unconditional increment in `src/probos/cognitive/procedure_store.py:1075–1091`.
- **Incorrect acceptance claim:** `prompts/bf-924-trust-inputs-through-real-apis.md:4217`, R25’s assertion that “no validation is skipped.”
- **Verification:** execution against real production agent classes, real store persistence, `IntentBus`, `AgentRegistry`, `TrustNetwork`, and one-slot concurrency managers.

The success increment is not associated with the compilation level that produced the outcome. After incrementing, the helper reads the **current** snapshot level and uses that as `expected_level`. A pending Guided outcome can therefore be counted as a Level-3 success once a peer has promoted the shared procedure.

**What I ran**

TEMP probe:

`test_r5_validation_epoch.py::test_only_outcomes_from_level_3_supply_the_level_4_threshold`

Final guarded run label: `r5-validation-obligation-final`.

The probe used Engineering, Operations, Security and Training agents. It held only the existing LLM `complete()` await; every `act()` was unmodified. Two ordinary completed turns established the initial count.

Observed artifact:

| Completed outcome | Level actually executed | Committed snapshot level | Consecutive count |
|---|---:|---:|---:|
| First pending Guided outcome | 2 | 3 | 0 |
| Second | 2 | 3 | 1 |
| Third | 2 | 3 | 2 |
| Fourth | 2 | **4** | 0 |

All four decisions were Guided at effective Level 2. There were **zero validation calls**, and the next intent made **zero LLM calls**.

The companion control, `test_r5_validation_control.py`, confirmed that the same procedure really requires validation at Level 3: its real Engineering-agent dispatch issued the `max_tokens=100` validation request.

Comparison runs established the regression classification:

| Source | Result |
|---|---|
| Pre-M1 `08511361` | Property passes; snapshot remains 2; next intent calls the LLM |
| Round 4 `96089844` | Property fails; snapshot reaches 4 without validation |
| Candidate `d9391617` | Same failure |

**Why it matters**

A procedure reaches zero-token replay without the Level-3 validation runs that are supposed to earn that transition. Per-agent serialization does not protect a procedure shared across agents.

R25 cannot be accepted as a harmless counting residual: its safety premise is false.

**Smallest fix**

Carry the level actually executed with the outcome. Atomically condition the success increment on that execution level still being current, and do not credit an older-stage outcome toward a higher stage’s threshold. Keep the final conditional promotion. A later reread alone does not close this seam.

Add the four-pending-Guided-outcomes regression to `test_bf924_compilation_trust.py`.

### 2. P3 — The section-12 enumeration receipts do not reproduce

- **Reach:** ordinary review/maintenance use.
- **Regression:** introduced by the A5 contract amendment; not a runtime-code regression.
- **File:** `prompts/bf-924-trust-inputs-through-real-apis.md:4084,4099`.
- **Verification:** execution.

I ran the advertised searches against both exact revisions using `git grep -n -E`:

| Revision | `promote_compilation_level\|demote_compilation_level`, `src tests` | `async def (act\|report)\(`, `src/probos` |
|---|---:|---:|
| `96089844` | **27** | **72** |
| `d9391617` | **32** | **72** |
| Contract receipt | 22 | 74 |

The meaningful caller and override lists were confirmed; this is not evidence of an omitted production caller. But the purportedly executed census is inaccurate.

**Smallest fix:** correct the counts and identify the revision each receipt describes.

## Boundary verification

### 1. D24 — Store conditions and lifecycle interleavings

Both supplied `test_shared_outcome_order.py` cases passed. Their traces reached the promotion call with both keywords, returned `applied: false`, and retained level 2/count 0 after the peer’s NO demotion.

Additional real-store/agent probes produced:

| Intervening action/state | Held promotion | Result |
|---|---|---|
| Peer demotion, 3 → 2 | Refused | 2/count 0; no announcement/request |
| Peer reset at level 2 | Refused | 2/count 0; no announcement/request |
| Peer promotion, 3 → 4 | Refused | 4/count 0; exactly one helper promotion log and one peer `_request_procedure_promotion` invocation |
| Decay, 3 → 2 | Refused | 2/count 0 |
| Column-only AD-535 migration | Applied using snapshot level 1 | Column and snapshot become 2 |
| Column 2, snapshot 3 | Applied using snapshot | Both become 4 |
| Snapshot without level key | Applied using default 1 | Both become 2 |
| `save()` replacing the level | Refused | Replacement remains |
| Archived-row restore to level 1 | Refused | Restored level remains 1 |

The request count above is a **method-invocation count**, not a claim that a Ward Room thread was delivered.

The real connection returned cursor rowcounts **`[1, 0]`** for applied/refused conditional updates. A refusal left **all 35 persisted columns unchanged**. `json_extract` returned a Python integer with SQLite type `integer`; the missing-key case exercised the default. Held-`get` task identity and ordering were established by events, not sleeps.

These checks settle the post-read interleavings. Finding 1 concerns outcomes already executing at an earlier level.

### 2. Public return contract, callers and doubles

The candidate enumeration found 32 matching lines, with **one production promotion caller**.

Four explicit promotion `AsyncMock` assignments remain in:

- `test_dream_step_7e.py`
- `test_fallback_learning.py`
- `test_multi_agent_replay_dispatch.py`
- `test_replay_dispatch.py`

A bare awaited `AsyncMock()` returns a **truthy `AsyncMock`**, so those doubles let the announcement gate pass without proving persistence. The real-store refusal probes cover that masked behavior.

BF-891’s updated result pin passed independently and failed against round-4 source with the expected `[None, None, None]` versus `[True, None, None]` difference.

The writer enumeration covered promote, demote, migration, decay, restore and whole-snapshot `save`.

### 3. D25 — Recovery intent and duty consumers

All six additional-lifecycle cases passed with shims off. I made a TEMP copy forcing the two explicit shim-control calls to `bridge_fix=False`, rather than counting those controls as unshimmed evidence.

I also executed **40 real `act()` cases**: the five named agents, the Builder’s five specialist subclasses, and the four requested intent/duty combinations.

- Counselor, Surgeon, Builder, Architect and all five Builder specialists returned the recovered answer for the conversational combinations.
- Scout returned the answer for direct message, Ward Room and non-duty proactive thinking.
- Duty-triggered Scout thinking ran the real report chain and wrote its report under TEMP.

Search and AST enumeration confirmed five direct intent-reading `act` overrides and the five inherited Builder implementations. The base lifecycle and Calculator probes returned identical results with and without the added keys.

There is one production `_run_llm_fallback` caller. After `act`, the recovery decision supplies `llm_output` to the fallback-learning event. The real Counselor recovery emitted `execution_failure` with the rejected step’s reason.

The recreation probe confirmed `proactive_think` and duty reach recovery. Its cached-recreation premise was explicitly injected: normal recreation decision-making skips procedural matching.

### 4. D26 — Failure envelope and report consumers

The actual failure dict reached the real base, Counselor and five M365 report implementations.

- Base and Counselor preserved the top-level failure and step reason.
- M365 implementations returned `{"agent", "result"}`, retaining the failure dict **nested** while omitting top-level `success` and `error`. That confirms R24’s report-shape limitation.
- The Counselor explicitly distinguishes a missing `result` key from `result: None`. The lifecycle’s final `.get()` reads do not.

I executed the **extracted actual chat-rendering branch**, not a reimplementation. The Counselor’s complete failure envelope selected the error branch at `routers/agents.py:3688`, rather than degraded-LLM handling. This was not a full HTTP-route test.

An unrecovered rejection fails the compound intent with the step named; healthy recovery returns its answer.

### 5. D27 — Accounting effects and measured cost

The computed stripped-helper diff contained only the documented docstring, promotion-call and result-gate changes.

The three call sites are `cognitive_agent.py:2529,7706,7873`.

A real overall-NO run recorded:

```text
[[procedure_id, false], [null, true]]
```

It performed one demotion, with no success increment or second reset. Thus one per-procedure accounting effect holds; one helper invocation does not.

SQLite tracing measured the same unconditional-promotion budget on round 4 and the candidate: one UPDATE, one logging SELECT, implicit BEGIN and COMMIT—four statements. A refused conditional promotion executed BEGIN/UPDATE/COMMIT without that SELECT. I did not infer CPU or allocation cost from these counts.

### 6. Shared contracts and delta scope

Verified by execution/comparison:

- Four-file `src/tests` repair delta.
- The other six M1 files are blob-equal to round 4.
- Event-payload ASTs unchanged; no generated file, config model, facade baseline or persisted schema change in the repair.
- M2 patch-id remains `520284855eb7e14f7b3d87eec8c2decd635fda93`.
- Structure enumeration identified 183 broad source readers and six directly relevant structure-pin tests.
- Those pins, the stop-seam inventory/registry and all nine AD-1326 files passed: **613 passed**.
- Architecture fitness check passed.

### 7. Test discrimination and isolation

The twelve new cases and two updated pins:

- Passed in selected file order: **14 passed**.
- Passed separately: **14 independent one-case runs**, each with a fresh guarded home.
- Failed on isolated round-4 source: **14 failed**, for the stated missing API, return value, stale promotion, missing context and lost-error reasons.
- Added no deleted, skipped or loosened tests; the two changed pins are stricter contract assertions.

The doubles mask semantic ranking/Chroma, provider replies, episodic I/O, the deliberately selected action failure or absent recovery, and promotion-request delivery. The real-agent consumer probes supplement the action doubles; the store, cursor and refusal checks were not mocked.

## File/schedule

No additional newly verified runtime finding is proposed for scheduling. Existing register entries were not reopened, except **R25: its “no validation is skipped” claim is disproved and cannot justify deferral**.

No checked existing test family failed on the candidate. The missing concurrency regression belongs in compilation-trust tests; passing current gates does not establish this property.

## Not checked

I did not run the full repository gate/CI, repeat the mutation campaign, review M2, access protected production data, or start a vessel. I did not test live-provider behavior, real Chroma ranking, full HTTP/NATS delivery, Ward Room delivery/approver routing, every specialized business action, or performance beyond the SQL counts above.

**Verdict: the ordinary validation gap must be fixed before this commit.**

NOT READY