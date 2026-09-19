# Governed agent work discovery and claim (AD-1187 / #1124)

Status: ordinary implementation candidate. Independent review, canonical
preflight/full gate and release remain parent-owned; this document does not
announce issue closure.

## Publication and availability

The existing Captain create, template-overrides and patch surfaces can publish a
standalone WorkItem through its metadata:

```json
{"agent_pull": {"version": 1, "scope": "ship"}}
```

Department-only publication uses the authoritative department identifier:

```json
{"agent_pull": {"version": 1, "scope": "department", "department": "science"}}
```

These are exact shapes for the `agent_pull` member. Missing, malformed or
additional publication keys are private, not an implicit ship grant. Other
WorkItem metadata may coexist but is not exposed by either tool. Publishing is
an explicit decision to share the permitted projection, including descriptions,
with eligible peers. Existing items are not automatically published or migrated.

Both tools register during communication startup only when workforce and its
current-authority resolver exist. Workforce's existing default-OFF setting stays
unchanged. The catalog scope is engineering, science, medical, security,
operations and bridge. All four known ranks (ensign, lieutenant, commander and
senior_officer) receive READ for discovery and WRITE for claim. Unknown ranks,
out-of-scope departments, current restrictions and LOTO still deny access.

The agentic offer is explicitly permission-filtered. Raw grants do not bypass
the gate. Crew and correction bindings (`_crew_session_id` or
`_crew_work_item_id`) exclude both tools from the offer and invocation. This is
not a new queue, scheduler, poller, crew executor or completion mechanism.

## Authority and readiness

Model parameters never supply identity, rank, department, trust, capacity or
permission. The context agent ID must resolve uniquely to the live registry key,
agent ID and registered resource ID. Different UUID aliases, ambiguous mappings,
inactive resources and malformed authority fail closed. A configured resolver's
denial never falls back to a cached resource.

The runtime reuses the existing agentic identity and resource-characteristic
owners. Current trust and department are authoritative; capacity and active
status remain store-owned. Matching uses current agent type, department and
trust characteristics, not a new mesh-capability interpretation.

Ready work is open, unassigned, unexpired and has every dependency in `done`.
Parental/crew, room/session and scaffold rows are excluded. Discussing, planned
and in-progress rows are not ready. Nonempty resource-requirement department
constraints still apply. Discovery is advisory; fresh claim rechecks readiness,
visibility, current authority and uncapped scheduled/active booking capacity
inside one admission transaction.

## Tool contracts

Both successful `ToolResult.output` values are **pre-rendered strings containing
Python-literal objects**, not raw dictionaries or JSON. This is declared by the
string output schema and tool descriptions. The loop's plain renderer supplies
the string; its normal final truncation path is not exempted.

`discover_work_items` accepts only:

- optional exact `work_type` string, 1–64 characters;
- exact integer `limit`, 1–50, default 20 (booleans are not integers here);
- exact nonnegative integer `offset`, default 0.

Its logical object contains `items`, `next_offset` and `omitted_fields`. Each
item contains `id`, `title`, `title_truncated`, `work_type`, `priority`,
`description_preview`, `description_truncated` and `description_utf8_bytes`.
Titles and previews are bounded to 256 Unicode characters with explicit flags.
`items[].description` is marked `preview_only`; other nonprojected WorkItem
fields are individually marked `not_exposed`.

`claim_work_item` accepts only an exact, complete `work_item_id` string of
1–128 characters. A stale selection never falls through to another item.
Shared agent-pull readiness enforces the same ID domain, without trimming, so
discovery cannot advertise an identifier that claim cannot submit. This does not
change legacy Captain creation or previously persisted identifiers.
Its ownership object contains:

- `owned: True`;
- `work_item`: `id`, `title`, `title_truncated`, `description`,
  `description_utf8_bytes`, `work_type`, `priority`, `status`, `assigned_to`;
- `booking`: `id`, `work_item_id`, `resource_id`, `status`;
- `omitted_fields`, including every nonprojected WorkItem/Booking field.

No arbitrary metadata, steps, verification, schedule or attachment content is
projected. Ordinary misses share `{'owned': False, 'reason': 'not_claimable'}`;
authorization, projection and infrastructure failures are errors, not empty
successes. `owned` confirms ownership at that operation, not execution, a fresh
mutation or automatic resumption.

## Actual invocation budget

The frozen `ToolResultPresentation` carrier lives in `tools.protocol`. Only
these two tool IDs receive it from `AgenticLoop`, under the reserved context key
`_tool_result_presentation`. The loop copies context, overwrites an incoming
reserved value and captures its own constructor-bound result settings. There
is no runtime-config proxy, tool-instance scratch buffer or model budget knob.
Missing, malformed or untrusted carriers deny admission.

`render_complete(value)` uses the existing plain renderer with `max_chars=0`,
then the existing truncator with the captured bounds. It returns the complete
unchanged render or `None`; invalid bounds and rendering failures are errors.
Admission measures rendered characters, including escaping, keys and omission
metadata, not source bytes, tokens or total request size.

Claim descriptions follow this order:

1. Strict UTF-8 strings up to **16,384 bytes**, including empty strings, remain
   complete when the full receipt fits.
2. Larger descriptions become `None`, retaining the original byte count and
   `omitted_fields["work_item.description"] = "size_limit"`.
3. An otherwise permitted description whose full receipt exceeds a positive
   cap becomes `None`, retaining the original byte count and the reason
   `result_budget`.
4. If the complete essential receipt still does not fit, reject before any
   ownership, booking, requirement or timestamp mutation.

IDs, ownership, statuses, counts and omission reasons are not shortened or
dropped to fit. The existing 256-character title rule is not further reduced.
Invalid, non-string or unencodable text is an error, not invented empty
instructions. Cap zero is unbounded presentation, not an exemption from the
UTF-8 ceiling. Budget refusals use `work_pull_result_budget` if that token fits,
otherwise explicit `!`, with the contextual reason retained in diagnostics.

Discovery examines at most 200 authorized candidate rows per call. The frozen
`ReadyWorkPage` appends defaulted `item_offsets` aligned to eligible returned
items, preserving its first two fields and public listing signature. The adapter
selects the largest whole-row prefix that fits the actual presentation budget.
When a suffix is omitted, `next_offset` is the first omitted item's recorded
scan offset, with `omitted_fields["items"] = "result_budget"`. It does not rescan,
infer positions from item count, or reuse the scan's end cursor after dropping
rows. True empty pages can retain continuation. A first eligible row that fails
admission produces an error, not a false empty page. Offsets remain advisory
under concurrent board changes.

## Transaction, replay and event ownership

WorkItemStore owns the write lock, `BEGIN IMMEDIATE`, guarded ownership update,
booking, requirement fulfillment, timestamp, commit and post-commit events.
Shared internal helpers do not take the lock or commit independently. Public
claim does not call locking public assignment, and public booking/journal
mutations cannot split an admission transaction on the shared connection.
All scheduled/active bookings count toward capacity, not the bounded UI cache.
Pause releases active capacity; resume rechecks capacity atomically.

The appended keyword-only `prepare_claim: Callable[[WorkItem, Booking], None] |
None` preserves the existing tuple/None return. Shared assignment preparation
allocates the real booking ID and planned assigned state before invoking the
synchronous, read-only callback and before the first mutation statement.
The callback must not do I/O or reenter the store; it cannot select authority
or change the plan. The store knows validation, not LLM presentation.

The adapter keeps its accepted immutable receipt invocation-local and returns
it only after successful store completion. CAS refusal, transaction failure or
rollback failure never returns a cached success. Exceptions and cancellation
roll back and propagate. Post-commit notification failure retains the committed
outcome; cancellation/process/provider interruption is not an outbox guarantee.
Exact-ID replay recovers an interrupted acknowledgement without another booking.

Replay checks current identity, active resource and permission before ownership
and matching bookings, but before fresh-work capacity/readiness. Exactly one
matching nonterminal booking returns the existing ownership, including paused
`on_break` state, without resuming or emitting. Publication withdrawal alone
does not revoke owner readback. Terminal, reassigned or missing bookings are
uniform misses; conflicting live bookings are integrity errors. Room/child
exclusions still apply.

Fresh claims emit the existing assignment and claim UI events once after commit
and lock release. Governed self-claim suppresses only the redundant assignment
TaskEvent. Legacy Captain pull/assignment retains notification, authorization
and REST envelopes, with current trust and transactional capacity checks.
Resolver-free standalone stores retain their declared-resource legacy behavior;
agent pull requires a resolver.

`work_item_status` remains the separate assignee-only status reader. It is not
extended into a description/metadata retrieval or execution tool. Rollback is
an ordinary code revert with no schema migration or automatic publication to undo.
Status first tries the owned, nonempty raw exact ID, including short or whitespace-
bearing identities. Only afterward does its existing trimmed exact/prefix fallback
require eight characters. Short prefixes do not resolve, ownership remains scoped,
and legacy exact IDs are not given the new claim tool's maximum length.

## Measured implementation evidence

The parent independently ran the complete 23-file owner/immediate-consumer
selection: **1,272 passed, zero failed or skipped**. The run asserted that every
loaded file-backed ProbOS module came from the candidate worktree. Durable
command/stdout and JUnit are
`logs/gates/ordinary-1124-parent-focused-20260918T202502191.*`;
JUnit SHA-256 `cb7f9b7b6ee21fa17cf6cff12758a619362e6f68556d72e3519129919be1d699`.
The selection includes actual startup/registry/executor/next-request/persisted
readback, transaction/authority/pagination/projection boundaries and unchanged
adjacent consumers. These are focused implementation checks, not independent
review, canonical full-gate, release or verified closure evidence.

Independent review found two ID-domain seams; parent real-chain probes confirmed
both before repair. The final repaired 25-file focus passed **1,501 tests**, with
zero failures or skips, including **433 AD-1187 cases** and the unchanged adjacent
default-OFF/delegation contracts. Evidence:
`logs/gates/ordinary-1124-id-final-20260918T213457019.*`;
JUnit SHA-256 `5a0e67f17034e28f4455d53a2488a4abad760497d8b9c79ebe927187bddfcaff`.
Prior overlapping counts are historical, not additive.

## Scheduled quality limitation

Discovery currently issues per-item requirement/dependency queries under its
bounded scan. Review measured 200 authorized department-ineligible rows yielding
202 serialized DB calls and 23.56 ms in in-memory SQLite; dependency lists can add
calls. This is not a disk/live latency claim. Batching and deterministic query-count
evaluation remain recorded on #1124 as a Medium follow-up, preserving privacy,
ordering and offsets; no separate issue or unrelated refactor is included here.
