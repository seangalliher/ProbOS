# Bridge fault visibility (AD-1207)

Implementation candidate for existing #1152, in the Captain's #1151/#1152 wave.
#1153 is acceptance verification, not another implementation program. Parent
ratification is issue comment 5746274610. No AD was allocated.

## Read contract

The canonical `create_app()` registers `/api/faults` and
`/api/faults/{fault_id}` through the same router registration pair as the other
surfaces. Both use `require_crew_scope`: a configured token is enforced before
fault or attachment access; the existing auth-disabled default is preserved.

- The collection takes `limit=50` (1–100) and `offset=0` (nonnegative). It detaches
  **all** `list_open()` records before awaiting receipt enrichment. Ordering is
  newest-first; both `open` and `diagnosing` are included.
- `{faults, total, limit, offset}` counts records, not invocations or agents.
  An empty page with nonzero `total` is not global emptiness.
- Detail accepts the existing 12-character lowercase hexadecimal ID and returns
  `{fault: ...}`. A retained closed record is returned with its actual status;
  reads do not reopen or resolve anything.
- Summaries carry `id`, `signature`, sanitized `tool_id`, readable `summary`,
  `status`, `occurrences`, Unix-second first/last timestamps, `issue`, and
  `issue_lookup_available`. Occurrences are positive **decimal strings**, bounded
  by signed int64, rather than rounded JavaScript numbers.
- Detail adds `error_text`, `attempted`, `recorded_agent_id`, `thread_id`,
  `work_item_id`, `observed_as`, `trace_summary`, `trace_available`, and
  `clipped_fields`. No raw trace reference or unsanitized trace link is exposed.
- Missing/unreadable fault storage returns safe 503; unknown valid ID returns
  404; malformed query/ID returns 422; authorization failure retains the existing
  401. Successful responses have `Cache-Control: no-store`. Only successful total
  zero establishes authoritative emptiness.

The existing store-owned `issue_filings.get(signature)` is the sole linkage
source. Only a `filed` receipt accepted by `valid_issue_receipt()` against the
filing's **pinned repository** becomes `{repository, number, url}`. Current config
and diagnostic prose cannot supply a link. An unavailable journal leaves the
fault visible with lookup unavailable. Missing, unconfirmed or invalid receipts
mean **“No confirmed issue link,”** not that no remote issue exists.

These GETs never claim, create, reconcile, fulfil, resolve, fetch GitHub, or
retrieve credentials.

A nonblocking review measurement found that a 50-row list plus one detail read
invokes **51 journal transactions / 153 SQL statements**. The review measured
**26.88 ms in-memory only**; this is not a disk-backed or contended latency
guarantee. This slice makes no performance change.

## Shared privacy boundary

`diagnostic_safety.py` exposes `sanitise_diagnostic_value`,
`SanitisedTraceReader`, and `TraceReader`. The old `repair_issue.TraceReader`
import remains valid. #1151 now imports the helpers; its report content,
filing decisions, thresholds, writes and named redaction policy are unchanged.
Its existing tests and shared fixture are retained unchanged.

Sanitization precedes whitespace folding, summarization and clipping. Detail
uses the existing `load_trace()` and `analyse_trace()` through the public safe
reader, not a second regex policy or raw trace parser. Presentation bounds are
160 characters for the headline, 2,000 for error evidence, 1,000 for attempted
operation, 4,000 for trace summary and 128 for tool/provenance identifiers.
`clipped_fields` records additional display clipping. Stored evidence may
already be bounded. The named policy is not universal secret detection.

The UI says **Recorded agent** and **Stored trace sample**. The row reporter and
adopted trace can describe different occurrences; neither is an affected-agent
history.

## Bridge ownership and accessibility

The existing private `BridgeSection` places Faults after Approvals and before
command stations. It has no `stationId`, alerting edge/pulse, badge, approval
controls or filing action. Behavior leads; identifiers are secondary evidence.
The issue link is a sibling of the semantic disclosure button, with
`noopener noreferrer`. Diagnostics render as wrapped text, not HTML.

`useFaultReports(open)` owns the collection and selected detail requests.
Existing `requestResource` supplies timeout/abort/classification;
`nextResourcePoll` supplies healthy 10-second cadence, bounded failure backoff
and authorization pause. Open/reopen and manual retry refresh; close/unmount
abort requests and clear timers. Detail refresh does not depend on occurrence
count changes. Request ownership and selection identity reject obsolete results.
Either read's authorization denial purges all diagnostics.

Only confirmed total zero hides the section and permits the parent **No
activity** message. Idle/loading/error/auth/stale data remain visibly unknown,
with explicit last-known totals when available. Paging exposes remaining
records, corrects an out-of-range page after shrinkage and clears removed
selection. Rows are keyed by fault ID; a fresh recurrence may reuse an issue
without reusing the old row or its expanded evidence. The panel remains usable
at a 360px keyboard viewport.

## Continuous acceptance seam

The new Python test module owns stores and fake transports; it never starts a
vessel. Its bounded stdio entry point lets Vitest drive the **same live test
session**, rather than stitching together unrelated handwritten responses:

1. A real agentic loop writes a real stored trace containing controlled historical
   BF-715 evidence. Two distinct turns stay subthreshold; turns three and four
   yield occurrences one and two plus the existing approval.
2. Actual `create_app()` responses traverse real BridgePanel, hook, guards and
   detail rendering.
3. The real approval component POSTs through the actual decision route, an
   injected fake GitHub transport commits one receipt, and refreshed Bridge
   evidence exposes its canonical link.
4. The fault lifecycle is unchanged. Restart preserves the receipt; explicit
   test closure removes the section; freshly qualified same-signature recurrence
   returns a new ID and reuses the receipt after another real approval.
5. Evidence asserts eight observed sandbox calls, **one GitHub POST**, one
   approval-time credential lookup, no read-time credential/HTTP work and no
   internal Architect/Builder repair.

`ui/e2e/fixtures/ad1207-faults.json` equals the serialized pending/filed/empty/
recurrence responses. Python checks the file; the interactive Vitest crossing
checks it again. Missing approved Python fails the crossing, never skips it.
All imported ProbOS modules must originate under the candidate `src/` tree.

This builds on the existing AD-1203 trace surface (`685e5c24`) and AD-1205
logical-turn detection (`bfd00c18`). The combined selection also reruns the
unchanged AD-1205 historical-identity and real-user-script-spoof cases.
**Historical stderr is not evidence of a new generated-entry launch failure.**
Parent #1153 acceptance must retain the previously shipped #1147/#1150 evidence
and the final wave's reviewed, frozen gate/CI receipts.

## Bounded validation and handoff

- M1: 143 focused cases covered (142 passed in the milestone run; the last
  trace-clipping fixture premise was corrected and its case passed separately).
  Existing #1151 report/privacy cases were unchanged.
- M2: **496 passed** in the combined Python selection, including the complete
  #1151 journal/consumer owners and the new API/replay cases.
- Component evidence: **45 passed** in the new Bridge suite, including the
  executed Python child. The combined component run also passed **90 unchanged
  approval-consumer cases**. Only valid empty-fault transport fixtures changed
  in `ApprovalsInBridge`; all old assertions remain.
- TypeScript no-emit passed. Isolated Playwright passed **4 cases**, across
  desktop and narrow-keyboard projects.
- One targeted No activity negative control failed against the prior predicate;
  the production predicate was restored and the case passed.

The isolated Vite config binds only `127.0.0.1:5197`, `strictPort: true`, with
`proxy: {}`. Playwright refuses server reuse and owns/tears down its server child.
HTTP/WebSocket mock/deny rules are installed before navigation, fixture-handler
execution is asserted, and external navigation is not performed. No default
backend/proxy, browser profile, live credential or model is used.

Whole-app OpenAPI generation exposed an existing locally imported
`HTMLResponse` forward-reference failure outside the registration-only change.
Fault schemas are checked from the actual canonical app's fault registrations,
and all API tests use the real canonical app. No adjacent route fix was made.

The reviewed #1151 commit remains `b1e836422643ca4a74e66938457a1113c88b58e0`.
Its stopped standalone full gate is **not validation evidence**. At Builder
handoff, this slice was unstaged and uncommitted. Parent owns independent review,
staging admitted new files before inventory preflight, freeze/commit, **one**
fresh whole-wave canonical full gate, PR/CI and verified closure. No
inventory-only pass is claimed as complete candidate preflight. The ledger
report is derived offline from its unchanged snapshot.
