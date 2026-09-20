# Captain-approved fault reporting — AD-1206 / #1151

This is issue filing, not an autonomous repair loop. Approval creates or links a
GitHub issue; it does not execute a harness, assign Copilot, update/reopen an
issue, change source, or close the fault. The ordinary implementation candidate
still requires parent-owned review and release gates.

## Configuration and authority

- `repair.enabled` remains `false` by default.
- `repair.propose_after_occurrences` defaults to `2` and requires a strict
  integer from `1` through `9223372036854775807`. `SystemConfig.model_validate()`
  and `load_config()` reject booleans, floats, strings and out-of-range values;
  they do not coerce these into a weaker filing policy.
- `repair.github_repository` defaults to `""`. A configured value must be
  `owner/repo`, not a URL. Empty configuration boots normally and reports the
  missing prerequisite when an approved filing is attempted.
- Credentials come only through the existing
  `CredentialStore.get("github", requester="repair_issue")` policy boundary.
  The issue client adds no environment or CLI fallback.
- `repair.targets` stays in the existing approval payload for compatibility; it
  neither chooses an internal harness nor controls the issue destination.

The request is still `kind="action"`, with the exact six-key action envelope,
`tool_id="repair"` and `action="dispatch"`. Its full fault ID/signature, tool
scope and provenance must match persisted fault evidence. Rationale text, target
display strings and a `fault_id` on an unrelated action do not confer authority.

The inline decision route serializes repair decisions before checking status.
The consumer independently reads committed Captain approval, not a mutable
cache object. Retry does not call `decide()` again or award another trust
outcome. Denial records the decision and bounded decline metadata without
credential lookup or HTTP. Repair is explicitly excluded from standing grants;
ordinary actions retain their existing non-replay behavior.

If decline audit metadata cannot be committed, denial remains effective and
this denial filed no issue. Its notice identifies only that audit failure; it
does not suggest retrying the denied approval.

## Durable ordering

`FaultReportStore.issue_filings` is an owned `FaultIssueFilings` component on the
existing injected database connection. No additional worker or runtime
lifecycle is needed. One shared lock covers complete transactions for both
filing metadata and legacy fault insert/occurrence/resolution writes.

1. Verify the committed Captain decision.
2. Atomically verify the matching persisted fault and, before acquiring or
   reacquiring an attempt, require its durable occurrence count to meet the
   consumer's effective `repair.propose_after_occurrences` threshold.
3. Commit the claim, including attempt identity and configured repository.
4. Release the database lock before credential/trace/HTTP work.
5. Validate and commit the issue receipt conditionally on signature and attempt.
6. Mark the capability request fulfilled only after that receipt commits.

The companion is bound only after successful store initialization and unbound
on failed start or stop. Cache-only storage cannot authorize filing. Exceptions
and cancellation roll transactions back. The legacy 16-column fault schema,
signature calculation and `FaultReport.to_dict()` are unchanged.

`claim()` requires a positive, non-boolean signed-64-bit `minimum_occurrences`.
The fulfiller defaults to 2; startup supplies the existing configured threshold.
Startup also validates mutated/non-model thresholds before registering a
listener or assigning either repair component. Invalid or missing thresholds
do not fall back to another policy or leave partial wiring. An absent repair
section or fault store still leaves repair legitimately unwired.
The freshly SQL-read fault is the witness, not the cache, proposal count or
rationale. A failed second occurrence commit can still leave a proposal, but
cannot authorize creation: qualification failure changes no journal row and
performs no credential or HTTP work. The approval stays unfulfilled, with
guidance to retry only after durable evidence or configuration permits filing.

Legacy and new approvals use the policy effective for the instantiated
consumer. Raising the threshold blocks new creation and retryable reacquisition;
lowering it explicitly permits qualified creation. Minimum 1 and the disabled
gate remain valid. A higher threshold does not prevent receipt reuse or turn
an existing attempting/unknown attempt into permission to resend.

Readback is `await fault_store.issue_filings.get(signature)` while the store is
bound. An unbound journal raises `FilingUnavailable`, rather than pretending
there is no prior attempt.

| Journal state | Meaning on explicit approval/Retry |
|---|---|
| No row | A durable matching fault meeting the current threshold may be claimed. |
| `declined` | Denial did no remote work. A separate valid approval with qualifying durable evidence can claim it. |
| `retryable_failure` | Missing prerequisite, proven pre-send failure or definitive rejection; explicit Retry may reacquire only with currently qualifying durable evidence. |
| `attempting` | A durable attempt exists. Another caller or a restarted process treats it as uncertain, never as an expired lease. |
| `outcome_unknown` | Retry only reconciles; it cannot send another issue POST. |
| `filed` | Reuse the committed validated receipt; never create, reopen or update the issue. |

An existing receipt survives a later denial and a failed capability-fulfilment
write. A new fault ID sharing the signature also reuses it, including when the
remote issue has been closed. Filing never calls fault resolution.

Keep the companion table when rolling application code back. Deleting its
history would discard the duplicate-suppression evidence.

The existing registered `probos.storage_declarations` module declares
`fault.issue-filings`, owned by `probos.fault_issue_filings.FaultIssueFilings`,
at canonical path `fault_reports.db`. Its lifecycle owner remains
`probos.fault_report.FaultReportStore`; there is no independent companion
lifecycle or connection. Criticality is `REQUIRED`. Journal retention is
`UNBOUNDED` to retain signature-based duplicate suppression across restarts.
Backup is `included` only when snapshots are enabled; restore is `unknown` and
reconstruction is empty. No live backup/restore result is claimed. The legacy
fault-store baseline row remains unchanged: this is a declaration, not a
baseline exception or SQL relocation.

## Uncertain outcomes

`ConnectError`, `ConnectTimeout` and `PoolTimeout` are proven pre-send failures:
they record `retryable_failure / pre_send_failure`. After connection recovery,
explicit Retry can create the issue, and its receipt prevents replay.
Read/write timeouts, server failure, malformed success receipts and cancellation
after dispatch do not prove that GitHub created nothing. Their durable attempt
remains non-replayable; cancellation propagates after transport cleanup and safe
notice.

An explicit Retry searches both open and closed issues in the pinned repository
for the exact `<!-- probos-fault:FULL_SIGNATURE -->` marker. The client accepts
only bounded, complete results (at most 100), canonical repository/issue URLs,
and one exact validated match. Empty, incomplete or multiple matches remain
uncertain. There is no automatic retry, startup backfill or resend control for
uncertain attempts.

Create responses, reconciliation, completion and fulfilment readback share
structural URL validation: exact HTTPS scheme/host/fixed path and positive issue
number, with no credentials, port, query, fragment, controls, encoded substitutes,
extra segments or trailing slash. Only owner/repository comparisons are
case-insensitive. The journal keeps the pinned destination identity and accepts
the provider's canonical-case issue URL. Owner names use ASCII alphanumeric
groups separated by single hyphens, with no leading/trailing/repeated hyphens.

This provides durable local duplicate suppression and conservative handling of
remote ambiguity, **not remote exactly-once execution**.

## Report and current approval surface

The client rebuilds evidence from the persisted fault and a readable trace, not
the truncated approval preview. It sanitizes copies before summarizing,
rendering or clipping, including sensitive structured fields and the resolved
credential. Bounds are 120 title characters, 12,000 body characters, 2,000 error
characters and 4,000 trace characters. Full fault ID, signature, tool and count
precede clipped evidence. Missing traces are identified explicitly.

The named outbound policy covers nested sensitive fields and textual
assignments, including `private_key`, `passwd` and `passphrase`; embedded Basic
and Bearer values; private-key PEM blocks (including RSA/OpenSSH and unterminated
blocks); and resolved credential values. Basic values are removed before generic
token cleanup, and the boundary continues to reuse `PIIRedactor`. This is
coverage of the named formats, not detection of every conceivable secret.

Stored diagnostic identity remains unchanged. The fault-report log no longer
quotes raw errors; client status logs/notices contain no raw transport exception,
response body or authorization header. Existing synchronous `runtime.notify`
delivery tells the Captain which request needs prerequisite correction or
reconciliation.

Reports and successful notices say that filing is not a fix and does not alter
the fault's lifecycle status. A previously approved dismissed/repaired fault is
not described as open and is not reopened.

The existing approval component retains approved/unfulfilled repairs with
**Retry fulfilment**, then removes the row after confirmed fulfilment. It does
not make ordinary actions retryable. There is no new endpoint, fault panel or
visual redesign; those remain outside AD-1206.

## Candidate validation

The two AD-1206 Python suites exercise real fault/event/dispatcher/approval
stores and the real decision route with injected fake credentials and HTTP
transports. They cover concurrency, failed persistence, shared transactions,
lifecycle cleanup, cancellation, restart, reconciliation, privacy, notifications
and future-fault receipt reuse. No test resolves actual credentials or creates
an issue on GitHub.

`ui/e2e/fixtures/ad1206-repair-approvals.json` is compared against complete real
Python serialized responses, then consumed by the existing Vitest approval
component with its real store and guards. The ordinary-action negative remains
part of the same fixture contract.

### Historical pre-R1 evidence — rejected, not repaired acceptance

The original candidate reported **816 Python tests**, **10 additional
RepairConfig cases**, **72 Vitest cases**, TypeScript no-emit and cheap gates.
Three targeted mutation checks detected the missing consumer, unsafe uncertain
replay and misleading cancellation guidance; production was restored before
that original passing selection. The parent separately retained a **618-case**
Python selection and **72-case** UI run. These observations remain historical.

The rejected index `48512dd2d60d9743886b75933b6b1e0ded06633b` subsequently failed
five parent-confirmed defect-positive probes: final-body secret markers, a
failed second commit authorizing count-one creation, case-equivalent canonical
URLs rejected, ConnectTimeout marked uncertain, and inaccurate lifecycle/denial
notices. Those **5 passing reproductions** proved defects, not acceptance.
The earlier store check also missed the then-untracked companion because its
inventory uses `git ls-files`; once staged, it correctly failed
`undeclared-store`. The parent ratified the existing-root declaration as the
sole addition to the 25-path envelope, now **26 paths**, without a baseline
exception. No earlier result establishes repaired acceptance.

### Current R1 focused evidence — candidate, not release

- **1,045 passed**, no failures/errors/skips, in one combined Python selection:
  both AD-1206 owners (**131 filing-store + 195 repair-issue = 326 cases**), all
  13 ratified immediate-consumer families, and four existing fault-store
  lifecycle cases. Startup threshold wiring at 1/2/3 and the old schema,
  identity, policy and ordinary-action contracts are included.
- **11 config pins passed**: the exact facade-baseline assertion and **10**
  existing RepairConfig cases (**229 unrelated cases deselected**).
- **72 Vitest cases passed** across the two existing component/reconciliation
  suites, and the existing TypeScript no-emit check passed.
- The new exact-metadata/canonical-path/real-journal lifecycle test plus five
  existing registry checks passed (**6 cases**). Removing only the new
  declaration made that regression fail at the expected missing declaration;
  restoration passed it again and in the combined selection. These overlap
  the totals above and are not additive. No preserved R1 fix was reverted.
- All seven standalone cheap gates passed: config reference, profiles, facade,
  AD/BF ledger, seam contracts, architecture fitness and store inventory.
  Inventory sees **10 declarations**, **57 store modules**, and **48 remaining
  undeclared modules**, all **48 already baselined**. In-memory compilation
  passed for **2,433** tracked `src`/`tests` Python files without emitted
  bytecode. The first post-documentation ledger check reported stale generated
  line references; the existing pure renderer supplied the two-line correction
  offline, with the pinned snapshot unchanged.

The combined run verified **284 ProbOS module origins** and **28 test/helper
origins** inside the candidate and unchanged bytes for all 26 candidate paths
during execution. Python used the approved existing interpreter, candidate cwd,
`src` plus root on `PYTHONPATH`, and isolated owned stores. HTTP and credentials
were fake only. Counts and provenance were observed on the console; no new
log/JUnit evidence artifact was written. Editor environment/diagnostic helpers
returned tool-execution errors; terminal validation is the available evidence.
The six-path intermediate hash is not a final-byte claim. Parent-owned
independent re-review, final freeze, canonical full-suite evidence, release and
verified issue closure remain outstanding.

### R2 config alignment — candidate, not release

R2 independently verified the R1 fixes and declaration; its remaining mismatch
was the coercive, unbounded config producer. The ratified correction aligns that
producer and pre-wiring validation with the existing consumer contract.

- **72 new cases**, only in the AD-1206 repair-issue owner, cover actual
  `SystemConfig`/YAML parsing, valid minimum/default/maximum through wiring and
  approval, mutated/non-model invalid values, missing thresholds, no wiring
  side effects and legitimately unwired paths.
- **281 passed** in the final bounded selection: **267** repair-issue cases
  (195 existing plus 72 new), two existing dispatcher wiring checks, one facade
  baseline assertion, and **11** RepairConfig/numeric-pin checks. The separate
  86-case slice and three restored mutation controls overlap this total.
- Removing the strict parser/bound and pre-wiring guards made all three
  defect-positive controls fail; restoration passed all three.
- The allowed old numeric pins now count the additional signed64 ceiling
  (RepairConfig 1→2, aggregate 59→60), with inline AD-1206 rationale. Only the
  repair reference row and RepairConfig/SystemConfig schema digests changed;
  all defaults, surface counts and the canonical dump digest are unchanged.
- The final consumer run verified **215 candidate-local ProbOS/test module
  origins** with the approved interpreter and candidate cwd/`PYTHONPATH`.

No 1,045-case repeat, UI rerun, full gate, live provider/credential access or
index/release operation was performed for R2. Parent owns delta review, freeze,
preflight, commit and canonical release evidence.
