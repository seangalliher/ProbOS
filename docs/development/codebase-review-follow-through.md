# Codebase Review Follow-Through

**Date:** 2026-09-07

**Status:** Planned repairs and existing-program priorities, requested by the
Captain after a representative source-and-test review. This document starts no
implementation campaign, grants no live-system authority, and advances no
readiness tier. It is a planning record, not a ready-to-run build prompt.

**Reviewed source:** `2c761b6a2c7477b4a08baced61516d9fb7b10383`, clean worktree.
The review used local test fixtures and temporary data, not the running vessel.
Recheck code, issue state and every affected consumer before implementation.

## Work and Sequence

| Finding | Decision / owner | Priority | Next deliverable |
|---|---|---|---|
| Group chat loses failed-write evidence | [AD-1305 / #1358](https://github.com/seangalliher/ProbOS/issues/1358) | High | Execution -> transcript -> episode -> evidence-recall crossing |
| Crew judge never reads the carried trace | [AD-1242 / #1234](https://github.com/seangalliher/ProbOS/issues/1234) | High | Both judge requests receive bounded actual trace evidence |
| Mixed write outcomes become a total-failure claim | [AD-1306 / #1359](https://github.com/seangalliher/ProbOS/issues/1359) | Medium | Truthful shared disclosure through its real consumers |
| Concentrated ownership and source-text-test debt | [AD-1270 / #1324](https://github.com/seangalliher/ProbOS/issues/1324) | Medium | Continue accepted bounded extractions and crossing-test classification |

Land the small shared-rendering repair AD-1306 before AD-1305 relies on its
disclosure contract. AD-1242 is independent. Prioritize these behavioral repairs
before interpreting their affected workflows as learning evidence. They do not
depend on the AD-1300 through AD-1304 long-horizon contracts or Core Fabric pilot.
Do not expand AD-1270's accepted completion denominator through this review.

## AD-1305 Group Write Evidence

**Measured behavior.** The real group fan-out runs notebook/artifact effects via
the [escalation subset](../../src/probos/cognitive/dm/reply_pipeline.py#L251),
but the [fan-out consumer](../../src/probos/routers/thread_fanout.py#L695)
uses the cleaned text and generated image IDs without carrying its write ledger
into disclosure or the separately constructed group episode.

The probe reused `_build_env` and `_agent_rows` in
[the group escalation tests](../../tests/test_ad933_group_chat_escalation.py),
plus `_FakeProactiveLoop(actions=[])` and the DM context helpers in
[the write-claim tests](../../tests/test_ad1285_write_claim_guard.py).
The raw reply was:

```text
Saved the finding. [NOTEBOOK finding]Review-probe finding.[/NOTEBOOK]
```

With `WriteClaimGuardConfig` enabled, a notebook-failure DM control and a
two-participant group turn produced:

| Observation | DM | Group |
|---|---|---|
| Notebook producer calls | 1 | 1 |
| Failure disclosure | Present | Absent |
| SQLite group reply | Not applicable | `Saved the finding. Review-probe finding.` |
| Group episode `self_contradicted_channels` | Not applicable | `[]` |

The probe asserted two persisted group replies, exactly one target-agent
episode, and marker cleanup, so the failure was not an unexecuted producer.
It used the real IntentBus, pipeline and SQLite transcript store; notebook
execution and the episodic sink were recording doubles. The episode result
proves missing filter input, not that every recall policy would return it.

**Decision.** Carry the same actual turn's typed durable-write outcomes through
the group disclosure, transcript and episode. Reuse `WriteLedger` and the
existing evidence-recall marker. Unknown/unevaluated channels remain distinct
from known failure. Preserve feature gates and uncorrelatable-outcome abstention.

**Milestone acceptance:** turn the probe into a red-first regression, then extend
it through the real notebook producer with an injected store failure, real
EpisodicMemory persistence/reload, and evidence-safe recall. Under the existing
enabled policy the marked episode is excluded from evidence but remains accessible
as history; an unrelated valid episode remains usable. Cover successful saves,
deduplication, failures, partial/mixed outcomes, no marker, unwired/unknown state,
cancellation and non-duplicate transcript/episode delivery. Prove each relevant
producer and persisted result, rather than constructing only the expected marker.

**Do not build:** the full DM pipeline on group messages, group conversational
AgenticLoop support, proactive Ward Room fixes, general retraction, a new memory
store, or natural-language save detection. Task-execution success and write success
are different facts: do not change `outcomes[].success` or trust attribution just
to label a failed storage effect. Retain channel-specific anchors, classifications,
public compatibility and the other participant's valid response.

**History reconciliation.** [#1338](https://github.com/seangalliher/ProbOS/issues/1338)
item 5 called this group residual unreachable and deferred it until a durable-write
channel existed. The producer-asserting probe establishes that the notebook path
is reachable. AD-1305 is its bounded re-file, not a reopening of the completed
marker/tool/span/counting fixes in #1087 and #1338, or the earlier #1259 composition
issue. Completed #1200 remains the write-claim evidence-filtering subset.

## AD-1306 Mixed Outcome Disclosure

**Measured behavior.** The real
[ledger and renderer](../../src/probos/cognitive/dm/write_ledger.py#L127)
produced a contradiction from already-correct channel facts:

```python
ledger = (
    WriteLedger()
    .consulted_with("notebook", wrote=False)
    .consulted_with("artifact", wrote=True)
)
assert ledger.wrote == frozenset({"artifact"})
assert ledger.wrote_nothing == frozenset({"notebook"})
assert "nothing was saved" in disclosure_for(assess_write_claim(ledger))
```

All assertions passed on the reviewed source. This was a pure-value/renderer
probe, not a live save. The per-channel failure predicate is not the defect;
the global wording is.

**Decision.** Make the smallest shared-rendering change that reports the known
failure without denying known successes. A scoped failure statement may be
sufficient; do not introduce a new status system merely to repair prose. Preserve
structural inputs and public APIs or a tested additive compatibility path.

**Milestone acceptance:** test the mixed ledger, then cross actual artifact and
notebook producers through the real Captain-facing pipeline, verifying one stored
write and one attempted failure. Require the disclosure to remain present, so
silencing the renderer cannot pass. Cover all-success, total failure, cross-channel
mixed outcomes, within-channel partial writes, multiple failed channels, empty
ledger and unknown/uncorrelatable outcomes. Preserve BF-866 span exclusion,
deduplication and partial-count semantics. Check the real capability-gap detector
and reply/episode/rendering consumers. New text must be deterministic, bounded,
and free of raw payloads or sensitive data.

**Do not build:** another ledger, new LLM calls, automatic retry, reply-text claim
detection, or a change to trust/task-success semantics. Do not reopen #1338's
completed within-channel partial-write counting; this is a cross-channel wording
defect. Enumerate all renderer consumers before changing a public signature.

## AD-1242 Existing Verifier Owner

Both [session](../../src/probos/cognitive/crew_verifier.py#L1914) and
[legacy](../../src/probos/cognitive/crew_verifier.py#L2350) judge builders receive
result prose and acceptance criteria. A local probe supplied two distinct,
readable content-hashed traces (the requested repository versus an unrelated one)
to both public verifier paths, asserting module origin and evidence-store controls.

Result: **four actual judge requests; both prompt pairs byte-identical across
conflicting traces; zero trace reads.** A canned judge only allowed the path to
complete. It did not establish that an independent model would accept a false
claim. The [real finalizer](../../src/probos/cognitive/crew_finalizer.py#L2278)
is an affected production consumer.

[#1234](https://github.com/seangalliher/ProbOS/issues/1234) now carries this
evidence. Reuse the public
[trace summarizer](../../src/probos/cognitive/trace_analysis.py#L600) and preserve
the issue's no-trace compatibility and frozen evidence/plan contracts. A regression
must prove the actual trace was read and reached each judge, with a matched-trace
control. Separate deterministic transport coverage from independently authorized
semantic evaluation. Trace content is untrusted evidence, not instructions; a
request record alone does not establish that an external effect succeeded.

Do not duplicate the evaluator, broaden to DM verification, or absorb #1238's
remaining verdict semantics. The review found machinery-failure handling already
present in several branches; older issue descriptions are not current evidence
that those distinctions are wholly absent.

## AD-1270 Existing Architecture Owner

The repository checker passed against its existing debt baseline. Its measured
class-body spans (not logical lines of executable code) include:

| Owner | Class-body lines | Direct methods |
|---|---|---|
| `CognitiveAgent` | 10,707 | 190 |
| `ProbOSRuntime` | 6,072 | 109 |
| `WorkItemAgenticExecutor` | 1,027 | 4 |
| `SubtaskVerifier` | 1,234 | 31 |
| `EpisodicMemory` | 3,281 | 60 |

The scan covered 935 source modules and 1,465 tracked test files. It reported
92 oversized owners, 30 database-connection baseline rows, 15 unowned-task rows,
583 narrowed private-access candidates and 223 source-text assertion sites in
120 files. Private-access and source-text categories are report-only; they are
classification candidates, not 806 newly verified defects. Zero layer-import
findings applies to the checker's five ranked packages, not every cross-cutting
module or all dependency relationships.

Continue the [existing program](platform-maturity-program.md): AD-1270c for
runtime/lifecycle responsibilities, AD-1270d for prompt/turn-effect/cognitive
ownership, and AD-1270b for crossing tests and debt classification. Preserve its
accepted scope, compatibility facades and frozen denominators. The other measured
owners are risk context, not automatic admission of extra extraction projects.

For each accepted slice, name the complete responsibility and its real consumers,
protect behavior with a crossing test, move ownership behind a narrow public
interface, and measure whether coupling actually decreased. Classify source-text
tests individually; retain legitimate structural invariants and replace weak
behavior proxies with executable tests while preserving their intended assertions.
Do not blanket-delete tests, hide growth in baseline waivers, rewrite the runtime,
or split files without moving responsibility.

## Verification and Allocation Evidence

The **prior review**, before these planning edits, ran:

```text
D:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1284_consensus_gate_reachability.py tests/test_ad860_crew_verifier.py tests/test_ad1285_write_claim_guard.py tests/test_ad933_group_chat_escalation.py tests/test_ad1293_turn_record_reaches_episode.py -q -n 0 -p no:randomly
```

Result: **127 passed, one importlib_metadata deprecation warning, 30.38 seconds**.
Architecture command: `scripts/check_architecture_principles.py --check`, with
a temporary JSON report for the counts above. These are baseline observations,
not repair validation, full-suite evidence, or a security certification.

Future implementation requires focused and affected-consumer tests, scoped
adversarial review, and fresh canonical frozen-tree gate evidence. New API/UI
changes need the repository's required endpoint/component coverage. Preserve
public typing, storage protocols, lifecycle ownership, raw Beta trust and the
OSS/commercial boundary. No live-system changes are needed for deterministic
regressions. Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`.

The [canonical ceiling script](../../scripts/ad_ceiling.py) succeeded twice before
allocation: Git subjects AD-1304 (1,979 references); all-state GitHub titles
AD-1304 (1,357 issues, 997 AD-titled, below 4,000); 61 prompt filenames at
AD-1298. Prior highest: AD-1304, from Git and GitHub. New allocations: AD-1305
and AD-1306 only. AD-1242 and AD-1270 retain their existing numbers.

Duplicate search used authenticated `gh search issues`, repository
`seangalliher/ProbOS`, all states, limit 100. `write-claim` returned 54 matches,
`disclosure` 36, and `AD-1242` 7 including the known #1234 positive control.
All were below the limit. Earlier narrow phrase searches missed known matches
and were not used to prove absence. Direct reads of #1087, #1338, #1234, #1236
and #1259 settled the relevant ownership boundaries. New issues retain these
searches and the explicit reasons not to reopen or duplicate existing work.
