# Agentic event correlation and crew token provenance

AD-1152, existing issue #1079. This is an ordinary implementation candidate,
not a release or issue-closure claim.

## Activation

`SystemConfig.agentic_loop.event_correlation_enabled` is a Pydantic boolean
defaulting to `False`. It is a product feature, not an exporter or external
integration. No configuration profile arms it.

Enable it through the shared configuration and **restart** to activate all
consumers consistently. Dispatch reads the setting when constructing a loop;
the native builder harness and crew executor receive it during startup.
Changing only an already-running configuration is not supported hot reload
across those startup-owned consumers.

Disabled callers omit the new constructor keyword entirely. The existing
event-neutral session-correction facade remains event-neutral and does not
inherit unrelated settings.

## Event identity

Every enabled `AgenticLoop.run()` allocates a fresh UUID hex `run_id`, even
when its incoming context supplies `_agentic_run_id`. The loop captures the
identity before invoking observers, copies it into tool context, notifies the
existing run-start observer with that value, and passes it explicitly through
its helpers. There is no mutable current-run slot, new ambient context, or
run serialization.

The existing public runtime event envelope and listener interface are unchanged.
Additions are inside `data` on exactly these existing producers:

| Event | Existing data retained | Enabled-only additions |
| --- | --- | --- |
| `agentic_loop_iteration` | `agent_id`, `iteration`, `tools_used_so_far`, `total_tokens` | `run_id`, `token_source` |
| `agentic_tool_call_started` | `agent_id`, `tool_id`, `iteration` | `run_id`, `tool_call_id`, `tool_call_index` |
| `agentic_tool_call_completed` | Previous fields plus `is_error`, `duration_ms` | `run_id`, `tool_call_id`, `tool_call_index` |

`tool_call_id` is the provider ID **verbatim**. Providers can repeat it,
including within one response. The unambiguous invocation key is
**`(run_id, iteration, tool_call_index)`**, where `tool_call_index` is the
zero-based position in the original request's tool-call sequence, not its
execution or completion order.

Iteration events precede the next LLM request. Their `token_source` qualifies
the **already-accumulated prefix** in `total_tokens`, not that next request.
The BF-680 conventions remain: measured, estimated, or mixed; an empty prefix
is labelled measured because it contains no estimate, not because a provider
was consulted.

Concurrent and nested runs may physically interleave. Their identities remain
separate. AD-1147 concurrency limits, read-only partition, mutation barrier,
and result ordering are unchanged. Emission keeps the existing best-effort
seam. Cancellation may leave a start without a completion: no synthetic end
or new terminal event is emitted.

The existing durable tool-record hooks consume the same private run identity.
Their separate invocation IDs, schemas and per-run recording budgets are not
replaced by provider IDs or event indices.

## Durable token qualifier

The frozen `crew_execution` record remains **exactly 14 keys**. A crew result
with qualified usage, when writing is enabled, adds a sibling in the **same
metadata patch and SQLite transaction**:

```json
{
  "crew_execution_token_usage": {
    "version": 1,
    "tokens_used": 20,
    "token_source": "estimated"
  }
}
```

The sibling has exactly these three keys. Version must be the integer `1`;
count must be a nonnegative bounded integer, not a boolean or float; source
must be `measured`, `estimated`, or `mixed`. Its count must equal
**`crew_execution.tokens_used`**. It does not qualify a later
`WorkItem.actual_tokens`, the parent total, or synthesis/verification counters.
Correction work can increase the child total after original execution, while
the original record and qualifier remain unchanged.

Normal outer-loop completion retains the existing last-outcome arithmetic
and source. The identity-loss path already preserves accumulated spend; when
enabled its provenance is merged too: estimated 7 plus measured 11 becomes
18 mixed. A mixed component remains mixed. Disabled behavior is unchanged.
Invalid enabled outcome provenance fails execution rather than producing a
successful unqualified result.

The shared [builder and reader](../../src/probos/crew_execution_usage.py)
distinguish:

- **Absent sibling:** historical unknown/unqualified usage, never an inferred
  measurement. A non-executed terminal path with no supplied source may also
  remain unqualified.
- **Present sibling:** must validate. Null, malformed or extra-key shapes,
  unsupported versions, invalid sources, boolean counts, orphan records and
  count mismatches are integrity errors, not fallbacks.

Terminal reconstruction, session validation and plan projection, and finalizer
live/restart readers validate the sibling independent of the writer flag.
Only validated runtime evidence is excluded from semantic plan identity.
The key is reserved from user plan metadata. Both the runtime untouched-child
predicate and the store's transactional retry guard reject **any presence**,
including an orphan or null sibling.

The existing work-item store, `to_dict()` and GET work-item endpoint expose the
sibling after reopening. No endpoint or result-dataclass field was added.
Generic metadata transport is not a substitute for the validating reader when
interpreting the count.

## Compatibility and rollback

No schema migration or historical backfill is needed. Disabled writes do not
add the sibling. Old execution bytes, attachment hashes and plan vectors
remain compatible.

**After new records exist, rollback means disable the feature, restart, and
retain the compatible readers.** Do not delete provenance, and do not blindly
revert to the old semantic-plan reader: it would incorporate the sibling into
plan identity. OFF readers must continue to accept valid ON-written records
and reject malformed ones.

The PROV-O projection is unchanged. This qualifier does not authorize treating
unqualified totals as measurements or billing. There is no OTel exporter,
collector, semantic-convention mapping, UI progress or streaming work here.

## Validation lineage

The immutable [OFF golden](../../tests/fixtures/ad1152_agentic_off_golden.json)
was captured with production files still pristine at
`7dd9542289fbe3b574b09f4e9b5fe934c35f424c`, before production edits. It contains
the base source blob IDs, deterministic requests/results/events, seven
constructor calls, raw SQLite metadata, reopened API output and associated
hashes. Only the new default-False config leaf is removed before comparing the
pre-existing default configuration digest.
Typed path defaults are rendered in the captured Windows representation on
other platforms too; ordinary strings and all other default values are left
unchanged. The golden itself is never regenerated for this normalization.

The observation SHA-256 is
`3a95dbc861da39ef946143029abaeb431820b237747ce95a984c55ce732497f3`.
An initial non-deterministic capture was rejected, not used as an oracle.
The successful capture and baseline run are recorded in ignored
`logs/gates/ordinary-1079-base-golden-20260918-01.log` and
`logs/gates/ordinary-1079-base-focus-20260918-02.{log,xml}`.

[Event tests](../../tests/test_ad1152_agentic_correlation.py) exercise actual
public runtime listeners and local durable tool records.
[Crew tests](../../tests/test_ad1152_crew_token_usage.py) traverse real
execution, transactions, reopen, existing GET, correction and finalization,
including pre/post-commit cancellation and exact reconciliation. Scripted
providers and local tools require no production or external service.

These focused checks are implementation evidence. Independent Diff Reviewer,
canonical preflight, reviewed commit, one frozen full gate, normal PR/CI/merge
and verified issue closure remain parent-owned.

After parent-authorized configuration bookkeeping repair, the same final
combined owner/consumer/config selection ran 1,743 tests:
**1,743 passed, 0 failed, 0 skipped**. All 191 new cases passed. The measured
census records 429 booleans: 204 default-False, 225 default-True, 85 armed and
119 never armed. The existing facade test retains strict equality at 1,786
fields with an AD-1152 reason; every other assertion is unchanged. All
existing configuration checks passed, with only the new False leaf and its
consequential counts/digests changed. The 170 frozen flags, old flags,
profile activation, historical notes, admission rules and pinned ledger
snapshot are unchanged. The configuration-bookkeeping evidence is retained in
`logs/gates/ordinary-1079-final-focus-20260918-04.{log,xml}`; the earlier
failing run remains historical evidence, not the current validation status.

The subsequent ordinary admission repair adds the qualifier to the atomic
absent-key guard. Native metadata conflicts retain the legacy authoritative
reload and blocked fallback when no qualifier is present. Any qualifier
presence on the reloaded row raises the existing untouched-child integrity
error before terminal evidence is attempted. Both admission-fallback writes
also atomically require qualifier absence: the terminal-evidence commit and
its in-progress-to-failed status fallback reject a later arrival without
changing the authoritative row. These guarded conflicts propagate the same
integrity error, while preserving an already-pending cancellation.
Real-store stale-snapshot cases cover null, empty and valid-shaped orphan
qualifiers with correlation OFF and ON. They assert zero executor/tool calls,
the unchanged raw SQLite row and metadata, and no fabricated execution
evidence; both clean controls execute the real local tool successfully.
Against the unchanged pre-repair production candidate, these cases produced
6 failures and 2 passing controls, retained in
`logs/gates/ordinary-1079-repair-red-20260918-01.{log,xml}`.
After repair, the same 21-file selection passed **1,751 tests, 0 failed,
0 skipped**, with 11 warnings. JUnit comparison preserved all 1,743 prior
case identities and added exactly 8 cases; the two AD-1152 files now contain
199 passing cases. That repair's focused commands, import provenance and
results are retained in
`logs/gates/ordinary-1079-builder-repair-focus-20260918-002245-850.{log,xml}`.
The OFF golden remains byte-identical at fixture SHA-256
`29f3cde2d8b16f995c6193af0552e2410d0bdd8fdd16ec4bb1443a8fa3bc591b`.

The second ordinary follow-through verifies that a stale child with only a
live `spec_id` change still returns `blocked` / `start_transition_failed`
through `_run_children`, preserves the new spec ID, and writes legacy
execution evidence without a qualifier or executor/tool call, OFF and ON.
Those tests failed twice against the pinned candidate before production
repair. A reload-only repair then exposed both late-qualifier races:
12 failing cases changed the raw row, while 14 controls and earlier admission
cases passed. The final qualifier-only CAS guards protect both writes without
changing ordinary metadata, state or dependency conflict behavior.
Cancellation cases preserve the original cancellation object and leave a
late-qualified row untouched.

Final validation uses the same 21-file selection and the standard Windows
pytest executable: **1,777 passed, 0 failed, 0 skipped**, with 11 warnings.
JUnit identity comparison retains all original 1,743 and prior 1,751 cases
and adds exactly 26 cases; the two AD-1152 files contain 225 passing cases.
Commands, import provenance and results are retained in
`logs/gates/ordinary-1079-followthrough-focus-20260918-005031-488.{log,xml}`;
case and immutable-artifact checks are recorded in
`logs/gates/ordinary-1079-followthrough-evidence-20260918-005359-869.log`.
All 64 pre-existing artifact/fixture hashes are unchanged. The earlier
stdin-launcher run, which failed a Windows multiprocessing test because its
child could not reopen `<stdin>`, remains separate historical evidence.
