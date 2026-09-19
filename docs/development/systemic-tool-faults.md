# Systemic tool-fault observations (AD-1205)

Implementation candidate for #1150. This is detection, not automatic repair.
Independent review, canonical preflight/full-gate evidence and release remain
separate, parent-owned steps. No live-vessel or external-model measurement is
claimed.

## Generated-entry provenance (R1)

The rejected candidate promoted stderr by text shape. R1 withdrew that proof:
an entered user script can print the same diagnostic, even naming its actual
workdir. The old script-printing positive tests are retained as negative spoof
regressions rather than deleted or described as launch-origin evidence.

[SubprocessSandbox](../../src/probos/execution/isolation.py) now validates only
its generated-code launch plan, after construction and before `Popen`. It checks
the actual interpreter/flags, resolves the argv entry against the actual child
cwd, compares it with the intended `script.py` or `_probos_launch.py`, and checks
the required generated files (including `script.py` behind a launcher). Truthy
explicit argv retains precedence; a correct cwd-relative entry remains valid.
A missing/mismatched plan produces an honest existing `ExecutionResult.error`
with workdir, empty stdout/stderr, no exit code and no launched process.
`LaunchOutcome`, audit ownership, cancellation, containment and cleanup retain
their existing paths. There is no retry or new result/schema field.

[CodeExecutionTool](../../src/probos/tools/code_execution_tool.py) forwards
nonempty execution errors verbatim and never promotes stderr alone. Ordinary
user exits, import failures, diagnostic lookalikes, nested interpreter errors,
success and timeout behavior remain unchanged. Evidence is deliberately split:

1. A controlled historical `ExecutionResult.error` retains canonical signature
   `d7e439af0281014e261e38dc45f51aa8927aa2422cc67a82e94f99d5d9c5b577`
   and trace/argument recovery. It proves identity, not launch origin.
2. The real approved interpreter, given a genuinely absent/doubled entry, proves
   actual argv/cwd, exit 2, its diagnostic and no entered user script.
3. An injected bad generated plan through the real sandbox/tool/observer/store
   proves the host pre-launch error and **zero interpreter launches**. It is not
   the interpreter result from item 2.

A file can disappear after the check. Stderr cannot authenticate that origin;
the repair does not add post-launch attribution, a handshake or another
containment mechanism. A regression exercises this explicit limitation.

### Observer classification of generated-entry errors (R2)

The observer-only classifier recognizes the exact, case-sensitive prefix
`generated entry pre-launch check failed:` as category `other`, after the
existing explicit governance exclusions and before generic substring matching.
Configured paths can legitimately contain `invalid`, `permission` or
`cancelled`; those path components must not turn a host-generated launch fault
into policy noise.

The producer's full error text and canonical signature are unchanged. The
generic capability classifier still classifies its inputs as before; no
permission, confirmation, cancellation, execution or repair policy is changed.
Missing-colon, whitespace-altered, differently cased, embedded and extended
near-prefixes retain generic classification. This rule handles the existing
error channel only. It neither promotes stderr nor authenticates post-launch
failures.

## Observation owner and identity

[FaultReportStore](../../src/probos/fault_report.py) owns a process-local
[ToolFaultObserver](../../src/probos/fault_detection.py) and its existing
`file_fault` publisher. The public boundary is the typed keyword-only
`observe_tool_run(turn, batch, agent_id, thread_id="", attempted="",
tool_trace_ref=None)` method.

The collector joins unique completed call/result IDs, requires an exact boolean
error flag and nonempty normalized error, and logs/skips malformed or mismatched
evidence. Invalid evidence is never interpreted as success. Count-one evidence
uses the existing `ToolDefect` carrier, canonical ID resolver, normalizer and
digest. The shared executor passes the same memoized resolver to trace writing,
raw capture, legacy detection and observation. Identity is derived before truncation; bounded
error text is not rehashed downstream. Existing `observed_as` provenance reaches
the unchanged repair argument reader.

## Raw disposition capture

Each supported shared or native loop invocation creates its own typed
`ToolFaultCapture`; the logical-turn token and shared executor hold no scratch
capture. The optional run keyword passes through
`run -> _run_scoped -> _execute_tool_uses -> _execute_one_tool`. Capture happens
at the raw-result boundary before conversion, not by parsing rendered dicts.
Tool result fields, conversion, event payloads and measured tool duration are
unchanged; unsupported paths allocate no capture or extra run keyword.

Only actual currently registered MCP/browser adapter types supply these
structured non-invocation facts. A source-backed correction projection exposes
a narrow adapter-kind query, not the source tool or additional authority.
Arbitrary tool names, type labels and returned flags do not establish adapter
identity. MCP's exact confirmation refusal and BrowserTool's tier-3 intervention
are neutral in cross-turn aggregation.

Capture retains at most 1,024 request identities, each with an observed name
and typed disposition; IDs and names are limited to 128 characters. It retains
no result body, arguments, conversation, confirmation token or session payload.
Oversized identities are rejected, not truncated. Duplicate IDs, mismatched
identity, overflow or capture/query failure make the affected run's diagnostics
unavailable, with a handled failure, not healthy evidence or legacy fallback.
Cancellation still propagates.

## Qualification, resets and bounds

- Cross-turn qualification requires the same canonical tool/error signature in
  **three distinct logical turns within a rolling 3,600 seconds**. An observation
  exactly 3,600 seconds old is expired. The clock is injectable and monotonic.
  Three independent uncontradicted turns distinguish recurring failures from
  isolated transients; one hour accommodates longer tasks.
- The existing same-run threshold of **two** and `resolve_tool_defect` stay
  unchanged. Count-one candidates never become legacy verdicts.
- Known permission, approval, consensus, cancellation, ambiguous-not-invoked,
  pre-hook and invalid-parameter refusals do not vote **or reset** cross-turn.
  Neutral-only turns preserve a pending streak; a genuine fault plus neutral
  refusal in one batch still contributes its original vote. Exact
  `requires_confirmation` is observer-only noise. This does not rewrite the
  legacy same-run detector, its two-hit verdict (including refusal errors), or
  capability policy.
- A success for that canonical tool clears its pending streak. A different
  error starts a new streak. Mixed errors or success/failure batches clear the
  pending streak rather than contributing a pure vote. Other/no-tool turns are
  neutral except for expiry. These resets do not erase durable reports.
- Tool health is shared across agents within the store's runtime. The report
  describes the qualifying observation's agent/thread, not invented ownership
  of earlier failures.
- There are at most **1,024 tool candidates**, each retaining one bounded
  signature and at most three bounded turn identities/timestamps. Expiry runs
  before deterministic least-recently-observed eviction.
- A batch retains at most 1,024 tools. A logical turn retains at most **1,024
  combined tool-state and publication-reservation entries**. Overflow warns
  once and declines new diagnostics, never evicting a reservation to make room
  for a duplicate attempt. Execution itself is not capped by these bounds.
- A repaired/dismissed report clears its matching pending streak. Later
  independent faults require fresh qualification; existing new-report behavior
  gives them a new ID. A process/new-store-instance restart drops candidates
  while durable reports survive. Losing up to two prethreshold observations is
  an explicit bounded cost; no candidate schema or persistence is introduced.

Occurrences mean **qualified filing turns**, not failed calls. Turns one and two
are not backfilled. Turn three creates occurrence/event one; the next qualifying
distinct turn increments to occurrence/event two. Same-run and cross-turn
qualification are unioned per signature/logical turn.

## Logical-turn ownership and consumers

| Path | Observation unit | Persisted attempted context |
| --- | --- | --- |
| Shared direct/task invocation | Fresh token per invocation unless explicitly supplied | Empty by default |
| Delegated child | Fresh child invocation, not its parent's token | Empty |
| Conversational DM | One token outside continuation/promotion passes | Exact `params["captain_message"]` string only |
| Crew child | One token outside all outer continuation passes | Empty |
| Legacy correction | One token across convergence retries; next episode gets a new one | Empty |
| Session correction | Same episode rule through the frozen runtime projection | Empty |
| Native build | Fresh token for the independently owned loop invocation | Empty; missing trace remains `None` |

The session projection exposes only a `ToolFaultObservationPort` with
`observe_tool_run`. It does not expose the fault store, registry mutation,
configuration/grant authority or an ambient runtime. Its event emitters remain
neutral. Its projected registry's added public query reveals adapter kind only
for permitted, enabled source-backed definitions.

## Compatible carrier and publication

The original twelve-field `WorkItemAgenticOutcome` remains unchanged.
Supported observation returns its non-frozen, keyword-only
`ObservedWorkItemAgenticOutcome` subtype with a required, bounded, validated
`FaultObservationResult`. Inherited objects are retained without recursive
`asdict` conversion. Missing/unsupported observers return the exact base type
and allocate no token or additional observation kwargs. A non-callable method
attribute is unsupported, not a usable observer.

The public/private executor methods append only the optional keyword-only
`fault_turn=None` and `fault_attempted=""`. These are diagnostic identity/context,
not continuation controls. The authorized AD-1155 signature guard retains its
entire ordered expectation and earlier assertions, appends these names, and
checks their kind, defaults and annotations.

DM and exhaustion recognize only the exact observed subtype and validate its
result. Handled-empty, failed or malformed observed results suppress legacy
refiling without inventing an ID. Uninstrumented legacy results retain their
fallback. Exhaustion still uses only the original same-run verdict.
Its appended `fault_attempted: str | None = None` is a separate filing override:
explicit empty wins, and malformed supplied values cannot trigger a fallback.
Omitted/None preserves the older external-call display/base fallback.

Reporting is **at most one attempt per qualified signature/logical turn**.
Reservation occurs before awaiting publication. Concurrent diagnostic
transitions and closure are serialized, but tools and cognition are not.
Publication failure/cancellation retains the reservation; cancellation propagates
and releases locks. A later pass or legacy hook cannot automatically retry it.
A fresh qualifying turn can make its own attempt.

An ID is **not a durability or delivery receipt**. The existing store can return
a cached report after persistence or event-delivery degradation. The observer
does not manufacture a stronger guarantee. There is no new durable exactly-once
delivery protocol or automatic recovery worker.

Generic dataclass serialization/equality differs for the subtype; blanket wire
identity is not claimed. Existing explicit projections retain the frozen
fourteen-key crew record, ordered `SubtaskResult`, plan identity, delegation
evidence, native metadata, tool-result fields, trace schema and old goldens.

## Privacy and repair boundary

Candidates do not retain raw arguments, tool outputs, code, conversation,
assembled instructions or delegated evidence. The transient batch carries only
bounded `ToolDefect` material and outcome flags; qualified reports use the
existing bounded error/attempted fields and original trace reference. Existing
trace retention is unchanged.

The DM computes `_fault_request_text` once per logical turn and uses it for
observed, legacy per-pass and explicitly overridden exhaustion filing. Its sole
source is the exact string at `params["captain_message"]`, including empty or
whitespace-only strings. Missing/malformed params or values, lookalike keys,
enriched `text`, top-level fields and assembled prompts yield no attempted
text. Promotion, display selection and continuation prompts are unchanged.
The omitted-argument exhaustion API's old fallback remains a compatibility
boundary, not a blanket privacy guarantee for external callers.

`FAULT_REPORTED` keeps its five keys and existing store ownership. The real
RepairDispatcher remains behind its existing enabled flag, occurrence threshold
and target selection. At the existing threshold of two filing turns, enabled
repair produces one pending capability approval; disabled repair produces none.
No repair execution, routing change, new retry policy or authority expansion is
part of AD-1205.

## Historical candidate evidence -- rejected by R1

The original subprocess -> trace -> reopened SQLite -> repair-approval positive
used submitted code printing the historical diagnostic. Its claimed launch
origin is withdrawn. R1 also independently reproduced MCP confirmation filing,
browser intervention resetting pending faults, and private-context fallback for
raw-empty/raw-missing DM requests. The following original counts and artifacts
are retained as history, not acceptance or coverage evidence for the R1 repair.

Boundary coverage includes alias/digit/hex/Unicode identity, raw-request privacy,
reset/noise/malformed evidence, exact expiry, candidate/turn limits, overlapping
execution, execution/publication/lock cancellation, duplicate callbacks, internal
persistence/emitter failures, closure and fresh-store restart. A malformed
observer result cannot reopen legacy filing. The final 42-file combined focused
selection passed **2,733 cases, with zero failures, errors or skips**, including
**146 new cases** (63 observer and 83 production-path cases). Completed-DM
two-hit and both correction-path same-run controls preserve one filing attempt
per qualified logical turn. All **366 added executable statements** across the
nine production modules were covered. The new observer module covered all 275
statements and 109/110 branches. The
uncovered negative edge of `elif defect is not None` is unreachable after a
validated failing result has constructed its defect; no source-only test or
coverage exclusion was added to disguise it.

The run includes the original eight-file baseline, affected consumer families,
the unchanged AD-1191 base-field guard, AD-1152/AD-1200 goldens and the offline
ledger tests. All 331 loaded ProbOS modules and 46 test/helper modules resolved
to the candidate; the nine changed production origins were asserted before test
I/O. The exact 42-file command/arguments and complete origin enumeration are in
`logs/gates/ordinary-1150-final-focus-cli-20260919T091103834.log`; the matching
JUnit has SHA-256
`0c2aa110bfd712a6edf7b4519d2c58a553f0c2ce52f23c06200d52497bcd5724`.
The matching `.coverage.json` and `.delta-coverage.json` retain the scoped
coverage details. Coverage of the entire nine legacy modules was 39%; the
100% statement figure applies to the added executable statements, not the
whole repository.

The earlier combined run's sole failure was Windows multiprocessing trying to
reload a stdin launcher. A spawn-compatible `python -c` entry passed the
unchanged hard-kill control and then the complete selection. No old assertion
or golden was relaxed for that runner failure. Three additional qualification
controls account for the final count increase.

The derived report is rendered offline from the unchanged pinned snapshot, not
refreshed through Git/GitHub.

## R1 repair evidence and remaining limits

Parent-ratified R1 requires all three repairs together. Initial discriminating
tests reproduced 11 failures. The pre-launch guard probe reached its forbidden
`Popen` fixture in all 18 bad-plan cases before repair; four separate real-origin
cases initially needed their Windows diagnostic path assertion corrected to
CPython's `repr(path)` spelling. Those fixture errors are retained in the log.

Intermediate focused selections passed 129 capture/loop cases, 239 privacy/
legacy/approval-chain cases, 351 owner/execution/audit/cleanup cases, and 133
projection/parallel/byte-preservation cases. These selections overlap and are
not additive. The chain also caught an initial host diagnostic containing
`validation`, which matched the existing invalid-parameter classifier;
the producer now says `pre-launch check`, without changing that
classifier or its policy.

The mandatory isolated chain uses actual registered MCP/BrowserTool producers,
shared execution, a real reopened fault store, RepairDispatcher and the real
capability-request store: `F, F, neutral, F, F` yields occurrence 1 on the third
genuine failure, then occurrence 2 and one approval only when enabled. Empty/
missing raw requests keep attempted empty; private attachment/recall/visual
markers do not enter fault persistence, events or requests. No bridge/click is
performed for the refusals, and no repair is executed. The event fixture drains
listeners locally; this is not evidence of live transport.

Real correction episodes exercise neutral refusals on both correction paths.
Reused shared/native executors use independent captures even for overlapping
runs with reused provider IDs. Both transcript modes, parallel request-order
correlation, original result/event bytes, bounds, capture failures, cancellation,
aliases and unchanged old consumers are covered by focused tests.

### Final R1 focused selection

The complete selected run passed **3,729 tests, 0 failures, 0 errors, 0 skipped**
across **66 test files**: the prior 42-file selection, 20 additional complete
consumer files, and explicitly enumerated cases from four more files. The two
AD-1205 owners contain **284 passing cases** (91 observer, 193 production-path),
138 more than the rejected candidate. One `importlib_metadata` deprecation
warning remains; it is not a test failure.

Evidence is retained under
`logs/gates/ordinary-1150-r1-final-focus-20260919T113035025.*`: log, JUnit,
summary, full invocation/import provenance and coverage. JUnit SHA-256:
`cd0c985071251c8d30f6710335d0b6e903c65c5963e51b3b43738ea6ece5ee5f`.
All 582 loaded ProbOS modules and 73 test/helper modules were candidate-local.
Existing Python 3.12.13 used explicit candidate cwd and `src` plus root import
paths, asserted before test I/O and after execution.

Measured R1 added-line coverage, compared with the unchanged rejected index,
is **122/122 added executable statements** across nine edited production files.
The current observer covers **328/328 statements and 131/132 branches**; its
remaining negative defect-presence edge is the previously documented defensive
edge after validated failing-result construction. No coverage exclusion was
added. These are scoped measurements, not whole-repository or whole-module
100% claims. The matching `.r1-delta-coverage.json` records the verified
aggregate. An earlier run's null-counter aggregation artifact and corrected
version are retained separately.

Limits selected explicitly before the run (no added skip/xfail):

- POSIX memory enforcement on this Windows host:
  `test_ad993_isolation.py::test_memory_limit_enforced`.
- Opt-in real Chromium:
  `test_ad706_browser_tool.py::test_real_chromium_goto_about_blank`.
- Privileged/host-dependent symlink creation:
  `test_bf788_workdir_cleanup_retries.py::test_a_dangling_link_is_not_read_as_removed`.
- Actual offline venv/package-install machinery, outside the no-dependency
  envelope: `test_ad994_code_runner.py::test_install_package_offline_degrades_honestly`.

Generated-script/launcher success, exit/import/timeout, explicit argv precedence,
audit once, no retry and cleanup/containment controls ran through the selected
real/fake-substrate consumers. MCP tests use owned stdio fixtures, not network
servers or an external provider. No live browser/model/vessel work was performed.
Editor diagnostic tools were unavailable; no standalone editor/type-check
result is claimed.

The first expanded run passed 3,726 cases and failed only three derived-ledger
freshness checks after tracker edits. The allowed report was regenerated offline
from the unchanged pinned snapshot, and the entire unchanged 3,729-case selection
was rerun green. Earlier artifacts remain retained.

The later final-inspection pass made the new interpreter fixture portable and
asserted candidate imports before fixture I/O. Its rerun exposed two flaky
byte-comparison fixtures: the capture-OFF/ON requests independently sampled
their timestamps. R1 keeps the complete field/byte assertions and supplies an
identical explicit input timestamp instead. The focused fixture/docs selection
passed 39 cases, followed by the final unchanged 3,729-case selection above.
No old test/golden was changed for either fixture correction.

### R2 review and narrow correction

R2 independently verified all three original R1 repairs and blocked one remaining
Medium seam: valid scratch roots containing policy-classifier words suppressed
generated-entry fault observations. The parent's retained confirmation used the
real fault store: an ordinary root filed once after three turns, while
`invalid`, `permission` and `cancelled` roots filed no report.

The correction is restricted to the observer-only exact-prefix rule above.
The guarded bad-plan regression now covers missing and doubled entries under
all four root names. Each case uses exactly three distinct logical turns and
verifies no launch, unchanged producer/trace error bytes and signature, original
argument recovery, audit and cleanup behavior, occurrence 1 only on turn three,
and the reopened store.

Before the correction, the new 40-case selection had nine failures and 31
passes: three direct classification failures and six full-chain failures.
After the correction, the expanded focused regression selection passed
**48 cases**, including explicit governance and MCP controls, with zero
failures/errors/skips. Evidence is retained under
`logs/gates/ordinary-1150-r2-regression-after-20260919T122333998.*`.
The retained 66-file selection and its four documented selection limits remain
the final focused validation boundary; the parent's later canonical gate will
run its own unmodified collection.

The final retained selection passed **3,767 tests, 0 failures, 0 errors,
0 skipped**, with one `importlib_metadata` deprecation warning. The AD-1205
owners contain **322 cases** (91 observer, 231 production-path), 38 more than
the R1 selection. Both R2-added executable classifier statements were covered;
this is not a whole-module coverage claim. All 582 loaded ProbOS modules and
73 test/helper modules were candidate-local, and all 18 candidate files were
unchanged during the run.

Final log/JUnit/summary/import-origin/coverage evidence is retained under
`logs/gates/ordinary-1150-r2-final-focus-20260919T123004792.*`.
JUnit SHA-256:
`070a9fad451557715b174e2b90e6f4f04f8c9903acd057aba940f0bed787e04a`.
The R2 frozen index remains `d3fd649ec4831b4501a2fe4c1fc92b296779a087`;
earlier R1 and R2 defect-positive evidence remains retained.

No independent approval of this R2 correction, canonical preflight/full gate, staging, commit,
release, live-vessel diagnosis or verified closure is claimed. The parent owns
frozen-candidate re-review and all release steps.

Rollback removes the diagnostic wiring/capture/collector and generated-entry
guard together. There is no migration to undo: durable rows/events
already use the existing schema. Do not delete old fault rows, refresh the
pinned ledger snapshot or relax repair/capability controls as part of rollback.
