# AD-1129: Governed Bounded EventLog Query Tool

**Status:** READY - prompt-only final adjudication approved 2026-07-21
**Issue:** #1048
**Type:** Enhancement; build AD-1129 only
**Planning origin:** `e33955a8` (initial AD-1129 draft after AD-1127)
**Exact planning/build base:** `3969c80b0a0f4a804a8528268f4561ca86887772` (`AD-1128: add unified CrewSession ingress`)
**Local ceilings at base:** AD-1128 / BF-673; batch commits are intentionally unpushed
**Broad backend baseline:** last measured after AD-1127: 20,032 passed / 33 skipped; context only
**Dependency:** AD-1125 is sufficient. Landed AD-1128 is not an implementation dependency.
**Execution authority:** `prompts/ad-1129-governed-event-log-query-execution.md`
**Supplied pre-rebase hashes:** main `c61855f02bb7222a9b020acb8de727a979af088554ff41878274b806fe89ed86`; execution `52693300ce8c9ac58df7fcf030b25467b73e288041b04f428ea6b4f071c2b671`
**Code-review adjudication input bindings:** main SHA-256 `56445af59580b149ccdf5ae8b7a1d125edd71857d42c3e27707cb3bd9f2dcbdb`; execution SHA-256 `cce1c36fb61d7cd20d117052132f640b79bf89bd215fbac9160c638d8f1cced2`; base `3969c80b0a0f4a804a8528268f4561ca86887772`
**Post-adjudication binding step:** before further production or test editing, mechanically record and report the amended SHA-256 and byte length of both active prompts. Those measured values supersede the adjudication input hashes; any later prompt-byte change is an Architect hard stop.
**Final-adjudication input bindings:** main SHA-256 `2b2467662ccbb5266ed3b6abbd19bde43536a7c926b49ff2c74630e78aae5ad2`; execution SHA-256 `4cfd997a080957a6fbb003c85635cd9132bd4460d261c4378c0cc3be7fa6fe30`. These identify the exact pre-amendment prompt bytes reviewed for this final ruling.
**Final validation input:** the completed changed-surface batch reported `220 passed / 3 failed`; all three failures are the exact AD-1072 delegation nodes bound below.
**Post-final-adjudication binding step:** before any test edit or pytest run, mechanically record and report the new SHA-256 and byte length of both active prompts. Those values supersede every earlier prompt binding; any later prompt-byte change is an Architect hard stop.

## Final Adjudication - AD-1072 Delegation Fixture Authority

This section has highest precedence over every conflicting implementation,
test, allowlist, validation, review, or closeout statement below. Preserve the
entire current tree. Ignore AD-1130. The `220 passed / 3 failed` result does not
authorize a production fallback or another changed-surface batch: the three
failures are stale AD-1072 authority fixtures exposed by AD-1129's intentional
partial-authority fail-closed contract.

### Decision

The production resolver is correct and frozen. A runtime that supplies
`runtime.registry` while omitting `runtime.ontology` or
`runtime.trust_network` is a partial authority surface and must continue to
raise `RuntimeError("agentic_identity_unresolved")`. Do not weaken that rule,
special-case delegation, infer authority from caller kwargs or agent
attributes, or add another fallback.

Authorize only `tests/test_ad1072_agentic_tools.py` as the final test repair.
Within that file, change only the shared fixture/helper surface used by the
three nodes below and, where required, those nodes' agent setup:

- `_Agent` may gain an exact non-empty `agent_type` fixture field. Keep `pool`
  as the callsign-routing key. `department` and `rank` may remain for legacy
  fixture compatibility but are not resolver authority.
- `_AgentRegistry` must add a protocol-faithful exact-ID `get(agent_id)` lookup
  while preserving `get_by_pool` and `all`. It must return the registered
  object or `None`; no dynamic or auto-created attribute is permitted.
- Add a narrow typed ontology fixture implementing only
  `get_agent_department(agent_type) -> str | None`. Back it with an explicit
  map `{"diagnostician": "medical", "counselor": "bridge"}` and return
  `None` for unknown types. Keep the target's routing `pool="bashir"` while
  setting its authoritative `agent_type="diagnostician"`; keep the parent's
  routing `pool="ezri"` while setting its authoritative
  `agent_type="counselor"`. Do not resolve by reading `agent.department`
  during the production call.
- Supply the shared delegation runtime with the complete authoritative trio:
  the existing registry, that ontology fixture, and a real `TrustNetwork()`.
  Its default Beta(2,2) score is `0.5`, so `Rank.from_trust` resolves the
  existing Lieutenant expectation without a fake rank or private mutation.
  A narrow deterministic object with a fully annotated exact `get_score`
  method is acceptable only if using the real in-memory `TrustNetwork` is
  mechanically impossible; document that reason in the handback.
- Ensure every executor subject is exactly registered. The two direct nested
  runs register the Bashir target as `diagnostician` / `medical`. The
  parent-loop node must register both `ezri-1` as `counselor` / `bridge` and
  `bashir-1` as `diagnostician` / `medical`.

Use concrete fixture classes or real services. Do not use `MagicMock`, phantom
`SimpleNamespace` members, `hasattr` authorization, private registry/trust
mutation, or a test-only production branch. Preserve all delegation behavior,
the callsign/liveness fallback, nested governed execution, transcript folding,
and `_delegation_depth` propagation. Do not change the depth-guard test, its
counting executor, registration-gating tests, test names, or behavioral
assertions except for authority setup strictly required by this ruling.

### Exact validation

After the prompt hashes/sizes are mechanically rebound and the one fixture
file is repaired, run only these three nodes together with `-n 0`:

```text
tests/test_ad1072_agentic_tools.py::test_delegate_happy_path_returns_result_and_increments_depth
tests/test_ad1072_agentic_tools.py::test_delegate_resting_agent_still_resolves
tests/test_ad1072_agentic_tools.py::test_loop_delegate_task_runs_nested_executor_and_returns_into_transcript
```

Use `-p no:cacheprovider -n 0 --timeout=90 -q --tb=short`. Do not rerun the
223-node changed-surface batch, any AD-1129 node, a broad/full suite, Gate 0-4,
or another discriminator. Then perform static scope, prompt-hash/size,
whitespace, and fixture audits only. The static evidence must prove:

1. the final repair diff is confined to the exact fixture/helper regions above;
2. no production file changed and the resolver still fails partial authority;
3. no `MagicMock` or phantom authority attribute was introduced;
4. all three subjects have exact registry/ontology/trust authority; and
5. the depth-guard test and delegation-depth assertions remain unchanged.

Any serial failure authorizes only a minimal correction in the same bound
fixture regions followed by the same three-node serial run. It never authorizes
a production change or wider test execution.

## Historical Adjudication - Authoritative Agentic Identity

This completed code-review adjudication is preserved as audit history. The
final AD-1072 adjudication above supersedes it for every further edit,
validation, allowlist, review, and closeout decision. Its production and
dedicated-test results are frozen. Ignore AD-1130.

### Required identity decision

Keep `department` and `rank` on `WorkItemAgenticExecutor.run` only as a
deprecated compatibility fallback for synthetic/event-neutral runtimes. Live
production callers must stop supplying them. Add one private cognitive-layer
resolver in `src/probos/cognitive/agentic_dispatch.py`; do not import a router
or move authority into a caller, Tool, or registry.

The resolver must produce one `(department, rank)` tuple exactly once, before
tool discovery or loop construction:

1. Read `runtime.registry`, `runtime.ontology`, and `runtime.trust_network`.
  When all three exist, require `runtime.registry.get(agent_id)` to return the
  exact registered agent whose `id == agent_id` and whose `agent_type` is a
  non-empty exact string.
2. Resolve department as
  `runtime.ontology.get_agent_department(agent.agent_type)` with
  `probos.cognitive.standing_orders.get_department(agent.agent_type)` as the
  existing-pattern fallback only when ontology returns no department. Require
  a non-empty exact string; do not infer from callsign, caller kwargs,
  `agent.department`, or a router.
3. Resolve rank only from live trust as
  `Rank.from_trust(runtime.trust_network.get_score(agent.id)).value`, using
  `probos.crew_profile.Rank`. Require one of `ensign`, `lieutenant`,
  `commander`, or `senior_officer`. Never read `agent.rank` or caller rank in
  authoritative mode.
4. A missing or partial dependency set, missing/mismatched registered agent,
  failed ontology/trust lookup, invalid department/rank, or ordinary resolver
  exception must raise `RuntimeError("agentic_identity_unresolved")` before
  any tool is offered or invoked. Do not leak the underlying exception.
5. Legacy fallback is allowed only when all three authoritative services are
  absent and the current ToolRegistry has no `event_log_query` registration.
  In that exact case only, preserve the existing `department`/`rank` kwargs so
  event-neutral projection runtimes and legacy synthetic tests remain
  compatible. If any authoritative service is present, or if
  `event_log_query` is registered, fallback is forbidden and resolution fails
  closed. Do not add another fallback.

Use the resulting tuple for both `event_log_query` discovery
(`check_permission`) and the loop context consumed by `ToolExecutor` during
invocation. Discovery and invocation must never resolve identity separately or
observe different values.

Remove obsolete live-runtime `department=` / `rank=` arguments only from:

- both executor calls in `src/probos/cognitive/cognitive_agent.py`;
- the assigned-agent call in `src/probos/cognitive/crew_executor.py`; and
- the nested delegate call in `src/probos/tools/delegate_task_tool.py`.

Do not widen constructors. The correction projection in
`src/probos/cognitive/crew_verifier.py` intentionally has no live identity
services and no EventLog Tool; it may retain its explicit legacy fallback tuple
and is not an authorized repair path.

### Reserved context decision

`extra_context` must not control identity or thread provenance. Accept only the
four reserved compatibility keys `agent_id`, `department`, `rank`, `thread_id`
and the existing private keys `_delegation_depth`, `_crew_session_id`, and
`_crew_work_item_id`; reject every other key with
`ValueError("agentic_context_invalid")`. Copy accepted extras first, then
overwrite the four reserved keys last with the run's `agent_id`, the one
resolved department/rank tuple, and explicit `thread_id`. This order is
mandatory even though forged reserved values are accepted for compatibility.
Preserve all three private values, especially `_delegation_depth`.

### Exact repair scope and tests

Preserve every existing dirty path. The only paths whose current bytes may be
changed by this adjudication are:

- `src/probos/cognitive/agentic_dispatch.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/cognitive/crew_executor.py`
- `src/probos/tools/delegate_task_tool.py`
- `tests/test_ad1129_eventlog_query_tool.py`
- `prompts/ad-1129-governed-event-log-query.md`
- `prompts/ad-1129-governed-event-log-query-execution.md`

No further edit is authorized in `src/probos/substrate/event_log.py`, any
protocol/Tool/registry/startup/runtime/Engineering file, AD-398/AD-664 tests,
trackers, or any AD-1130 prompt. Do not revert their existing AD-1129 changes.

Add all repair regressions only to `tests/test_ad1129_eventlog_query_tool.py`:

1. register a real `EngineeringAgent` in a real `AgentRegistry`, provide the
  runtime ontology and trust services, call `run` without `department` or
  `rank`, and prove the resolved `engineering` / `lieutenant` tuple both
  discovers and invokes `event_log_query`, yielding the real 61/49 aggregate;
2. prove partial/missing authoritative identity and an unregistered/mismatched
  agent fail before discovery/invocation, and prove fallback is forbidden when
  `event_log_query` exists;
3. prove a legacy synthetic runtime with all three services absent and no
  `event_log_query` retains its existing fallback behavior;
4. pass forged reserved values plus `_delegation_depth` in `extra_context`,
  prove registered identity wins at invocation/audit, prove explicit thread
  wins in loop context, and prove delegation depth survives;
5. exercise exact invalid limits `-1` and `10**100`, each returning the stable
  limit-validation result without querying rows.

This code-review repair and its changed-surface batch are complete historical
context. The final adjudication above freezes this surface and replaces all
further validation authority with the exact three-node `-n 0` run.

## Historical Adjudication - Frozen AD-398 Identity Test

This completed test adjudication is preserved as audit history and is
superseded for all further edits and validation by the final AD-1072 ruling
above. Its AD-398 correction is frozen; do not restore the phantom.

The only newly authorized existing-test edit is
`TestNewAgentInstantiation.test_engineering_agent_attributes` in
`tests/test_ad398_crew_identity.py`:

1. Preserve the three Engineering identity descriptors already covered there:
  `agent_type == "engineering_officer"`, `tier == "domain"`, and non-empty
  `instructions`. Do not delete, rename, move, or replace this identity test.
2. Replace the phantom-inclusive `len(agent.intent_descriptors) == 3` assertion
  with an exact assertion that the two legitimate descriptor names are
  `engineering_analyze` and `engineering_optimize`.
3. Replace the phantom-inclusive `_handled_intents` assertion with the exact
  set `{"engineering_analyze", "engineering_optimize"}` and explicitly assert
  that `eventlog_diagnostic_query` is absent.
4. Do not put `event_log_query` into `EngineeringAgent.intent_descriptors` or
  `_handled_intents`. Its governed registration, permission-filtered discovery,
  and callable path belong in the new AD-1129 tests through `ToolRegistry` and
  `WorkItemAgenticExecutor`.
5. No other function or fixture in `tests/test_ad398_crew_identity.py` may
  change. This adjudication adds no other test mutation: the original authority
  for the new AD-1129 test file and the AD-664 phantom-retirement assertions
  remains exactly as written.

The third legacy `IntentDescriptor` was the phantom itself. Keeping an agent
descriptor count of three would either retain that phantom or incorrectly teach
the governed Tool as a directly handled agent intent. Therefore “preserve three
Engineering descriptors” is adjudicated as preserving the test's three identity
assertions above; the exact agent intent-descriptor count is two, and the third
behavioral surface is the separately tested governed Tool discovery path.

The AD-398 correction and its changed-surface batch are complete and frozen.
The final adjudication above adds only the bound AD-1072 fixture file and exact
three-node `-n 0` validation.

## Decision

Add one deterministic, read-only Tool named `event_log_query`. It gives an
authorized AgenticLoop a bounded structured view of the existing EventLog and
one fixed cooperation-signature aggregate. It does not expose SQLite, paths,
SQL, files, network access, or an HTTP endpoint.

"Read-only" describes the subject operation: the Tool cannot mutate EventLog
records. Its sole write side effect is the mandatory append-only governance
audit required below; that is not a caller-selectable write capability.

The Tool consumes narrow injected read and audit protocols; the concrete
`EventLog` remains the only SQLite owner. `ToolRegistry` remains the primary
authorization authority. The Tool repeats a defense-in-depth check using
server-owned invocation context, redacts and bounds all output through the
public EventLog adapter, and records successful and denied attempts without
recording filter values or returned content.

AD-1129 is rebased onto the local unpushed AD-1128 HEAD but does not consume
CrewSession ingress, reservation, dedup, or resume. Do not touch or assume any
AD-1128 ingress file. The sole shared changed file is `runtime.py`, and its only
AD-1129 edit is the direct startup integration that passes the already-owned
`self.event_log` into `init_communication`.

## Problem Verified on the Live Surface

1. `EventLog` already owns async `query`, `query_structured`, and
   `get_event_chain`, but those return broad internal dicts and do not enforce a
   governed time window, output-byte ceiling, fixed aggregate, or redaction.
2. `EventLogProtocol` is write-only and its current `log(category, agent_id,
   data)` signature does not match concrete `EventLog.log(category, event,
   agent_id, agent_type, pool, detail, *, correlation_id, parent_event_id,
   data) -> int | None`.
3. At the planning base, `EngineeringAgent` advertised
  `eventlog_diagnostic_query` in instructions, capabilities, descriptors, and
  `_handled_intents`, but no production handler performed the read. The partial
  live AD-1129 implementation has correctly removed those declarations and
  updated AD-664; the frozen AD-398 identity test still requires the phantom and
  is the exact test-only conflict adjudicated above.
4. `ToolRegistry` already resolves enabled state, singular department scope,
   rank defaults, and `ToolPermissionStore` grants/restrictions before invoking
   a Tool. `WorkItemAgenticExecutor` receives server-owned agent id, department,
   and rank, builds the Tool list, and forwards them to `AgenticLoop`; its
   `DispatchToolExecutor` maps those values into `check_and_invoke`.
5. The EventLog producer for cooperation clusters stores
   `category="emergent"`, `event="cooperation_cluster"`, with signature fields
   at `data.evidence.intents` and `data.evidence.avg_weight`.
6. The #1048 forensic target is 61 cooperation-cluster rows in a Jul 13-17
   window, with 49 sharing `introspect` + `team_info` + `0.995`.
7. No `/api/system/events` route exists. A Tool is the required agentic path;
   an endpoint would be a new, unnecessary exposure.

## Exact Public Contract

### Boundary types

Add frozen, fully annotated boundary types beside the live `EventLogProtocol`
in `src/probos/protocols.py`, including the new segregated reader and audit
protocols below. Do not pass raw dict request objects across the Tool to
EventLog boundary.

```python
EventLogOrder = Literal["newest_first", "oldest_first"]
EventLogAggregateKind = Literal["none", "cooperation_signature"]
EventLogAuditOutcome = Literal["success", "denied", "invalid", "failed"]
EventLogJsonValue: TypeAlias = (
  str | int | float | bool | None
  | tuple["EventLogJsonValue", ...]
  | dict[str, "EventLogJsonValue"]
)

@dataclass(frozen=True)
class EventLogQuerySpec:
    start_time: datetime
    end_time: datetime
    category: str | None
    event: str | None
    correlation_id: str | None
    agent_id: str | None
    limit: int
    order: EventLogOrder
    aggregate: EventLogAggregateKind

@dataclass(frozen=True)
class EventLogQueryRow:
    id: int
    timestamp: datetime
    category: str
    event: str
    agent_id: str | None
    agent_type: str | None
    pool: str | None
    detail: str | None
    correlation_id: str | None
    parent_event_id: int | None
    data: EventLogJsonValue

@dataclass(frozen=True)
class CooperationSignatureGroup:
    intents: tuple[str, ...]
    avg_weight: float
    count: int

@dataclass(frozen=True)
class CooperationSignatureAggregate:
    kind: Literal["cooperation_signature"]
    total_rows: int
    valid_signature_rows: int
    groups: tuple[CooperationSignatureGroup, ...]
    truncated: bool

@dataclass(frozen=True)
class EventLogQueryBatch:
    available: bool
    rows: tuple[EventLogQueryRow, ...]
    matched_count: int
    scanned_count: int
    truncated: bool
    aggregate: CooperationSignatureAggregate | None

@dataclass(frozen=True)
class EventLogQueryAudit:
    actor_id: str
    department: str
    rank: str
    outcome: EventLogAuditOutcome
    parameter_names: tuple[str, ...]
    window_seconds: int | None
    aggregate: EventLogAggregateKind
    matched_count: int
    returned_count: int
    truncated: bool

@runtime_checkable
class EventLogReaderProtocol(Protocol):
    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch: ...

@runtime_checkable
class EventLogQueryAuditSink(Protocol):
    async def audit_governed_query(self, audit: EventLogQueryAudit) -> bool: ...
```

The adapter detaches and bounds `EventLogJsonValue` before constructing the
frozen row. `Any` is not permitted in the request, row, aggregate, or audit
contracts.

Correct the existing `EventLogProtocol.log` declaration to the concrete public
signature and `int | None` return. Do not add read methods to that writer/lifecycle
protocol; consumers needing reads depend on `EventLogReaderProtocol` only.

### Tool input

`EventLogQueryTool.input_schema` is an object with
`additionalProperties: false` and these exact fields:

| Field | Contract |
|---|---|
| `start_time` | required exact string, max 64 chars; RFC3339 timestamp with explicit UTC offset |
| `end_time` | required exact string, max 64 chars; RFC3339 timestamp with explicit UTC offset |
| `category` | optional exact non-empty string, max 128 chars |
| `event` | optional exact non-empty string, max 128 chars |
| `correlation_id` | optional exact non-empty string, max 256 chars |
| `agent_id` | optional exact non-empty string, max 256 chars |
| `limit` | optional exact integer, default 50, range 1..200; bool rejects |
| `order` | optional `newest_first` or `oldest_first`; default newest |
| `aggregate` | optional `none` or `cooperation_signature`; default none |

Runtime validation repeats the schema. Reject subclasses/hostile containers,
unknown keys, explicit nulls, empty strings, non-finite values, naive times,
`start_time >= end_time`, and windows over exactly seven days. Normalize aware
times to UTC. Query the half-open interval `start_time <= timestamp < end_time`
so adjacent windows do not double-count. Require at least one of
category/event/correlation_id/agent_id.

Require `type(params) is dict` and reject `len(params) > 9` before iterating;
then inspect only the at-most-nine exact string keys. This bounds unknown-key
rejection and denial-audit name collection independently of accepted output.

`cooperation_signature` is valid only with exact
`category="emergent"` and `event="cooperation_cluster"`. It is not a generic
JSON path, grouping, expression, or aggregation language.

Stable failures return no rows and no exception text:

- `event_log_query_invalid:<code>` for malformed input;
- `event_log_query_denied` for the Tool's defense-in-depth denial;
- `event_log_query_unavailable` when EventLog is not started;
- `event_log_query_failed` for an ordinary adapter/audit failure.

Never catch `asyncio.CancelledError` or another `BaseException`.

### Query, projection, and aggregate

Add `EventLog.query_governed(spec)` as the only new SQL-facing API. It must:

1. Return `available=False` without opening a connection when `_db is None`.
2. Revalidate all bounds even though the Tool validated them.
3. Build SQL only from fixed hard-coded column/filter fragments and one enum-
  selected hard-coded `ASC`/`DESC` token. Bind every value. Order by
  `timestamp` and then `id`, both in the selected direction, for deterministic
  ties. There is no SQL string, column name, JSON path, sort expression, or
  predicate from the model.
4. Project only the existing eleven query fields:
   `id, timestamp, category, event, agent_id, agent_type, pool, detail,
  correlation_id, parent_event_id, data`. Use fixed SQL expressions aliased to
  those names to transfer no more than each scalar cap plus one character,
  and no more than 16,384 UTF-8 bytes of raw `data`; oversized raw data becomes
  the fixed `{"_truncated":true}` marker before Python JSON decoding.
5. In either mode inspect at most `min(limit, 200) + 1` rows: the bounded usable
  rows plus one truncation sentinel. Normal mode returns at most `limit` rows.
  Aggregate mode returns no raw rows and only the fixed aggregate. A caller
  must request `limit=200` to inspect all 61 rows in the acceptance fixture.
6. Set `matched_count` to the bounded rows observed before the return limit,
   `scanned_count` to the rows inspected, and `truncated=True` if the row limit,
   aggregate scan ceiling, or final byte ceiling cut output.

Do not alter `_SCHEMA`, migrations, indexes, retention, prune, wipe, hash-chain
logic, legacy query methods, or their return shapes. The retained EventLog is
already capped; AD-1129 adds no unproven index or schema change.

Every normal-mode projected row has exactly the eleven keys above; serialize
its aware UTC `datetime` as RFC3339 with `Z`. Apply these fixed caps:

| Surface | Cap |
|---|---:|
| output rows / aggregate scan | `min(limit, 200)` / `min(limit, 200)` |
| timestamp | 64 chars |
| category, event, agent_type, pool | 128 chars each |
| agent_id, correlation_id | 256 chars each |
| detail and every surviving JSON string | 512 chars |
| raw `data` transferred for JSON decode | 16,384 UTF-8 bytes |
| JSON depth | 4 |
| dict keys or list items inspected per container | 32 |
| serialized row | 4,096 UTF-8 bytes |
| complete Tool output | 65,536 UTF-8 bytes |
| aggregate groups | 10 |

Accept only exact built-in JSON scalar/list/dict values after EventLog JSON
decode. Reject container subclasses, non-finite floats, bool-as-int aliases,
and integers outside signed 64-bit range. Redact every string with
`PIIRedactor.redact_all`. For case-insensitive keys containing `api_key`,
`authorization`, `client_secret`, `credential`, `password`, `refresh_token`,
`secret`, or `token`, replace the value with `[REDACTED]` without traversing it.
Use explicit truncation markers. If a row still exceeds 4,096 bytes, replace
`data` with `{"_truncated": true}` and keep the bounded scalar projection. Build
metadata/aggregate first, then append rows only while both compact canonical
JSON (`ensure_ascii=False`, sorted keys, compact separators) and the live
`str(envelope).encode("utf-8")` representation consumed by
`ToolCallResult.from_tool_result` remain at or below 65,536 bytes.

For `cooperation_signature`, inspect only exact dict/list/builtin numeric values
at `data.evidence.intents` and `data.evidence.avg_weight`; bool is not numeric.
Canonicalize intents as sorted unique non-empty bounded strings and round a
finite weight to three decimals. Group by `(intents, avg_weight)`, order by
count descending then intents/weight ascending, and return at most ten groups:

```json
{
  "kind": "cooperation_signature",
  "total_rows": 61,
  "valid_signature_rows": 61,
  "groups": [
    {"intents": ["introspect", "team_info"], "avg_weight": 0.995, "count": 49}
  ],
  "truncated": false
}
```

The test fixture must reproduce 61 and 49 exactly. Do not hard-code those
counts in production. Aggregate mode returns `rows=[]` and
`returned_count=0`; normal mode returns `aggregate=null`.

### Tool output and audit ordering

An aggregate success returns exactly this envelope shape:

```json
{
  "status": "ok",
  "window": {"start_time": "...Z", "end_time": "...Z"},
  "order": "newest_first",
  "matched_count": 61,
  "returned_count": 0,
  "scanned_count": 61,
  "truncated": false,
  "rows": [],
  "aggregate": {
    "kind": "cooperation_signature",
    "total_rows": 61,
    "valid_signature_rows": 61,
    "groups": [
      {"intents": ["introspect", "team_info"], "avg_weight": 0.995, "count": 49}
    ],
    "truncated": false
  }
}
```

Normal mode uses the same envelope with projected `rows` and `aggregate=null`.
Counts reflect actual bounded work; `matched_count` means matches observed
within the declared scan ceiling, never total-database cardinality after a cap.

The Tool queries first, prepares the bounded output, then awaits
`audit_governed_query`. Only after audit succeeds may it return rows. If query
succeeds but audit fails, return `event_log_query_failed` and no rows.

The concrete EventLog implements both narrow protocols. Audit with its existing
`EventLog.log`, using `category="audit"` and
`event="event_log_query"`. `detail` is a fixed outcome sentence. `data` contains
only actor id, department, rank, outcome, sorted parameter names, window seconds,
aggregate kind, counts, and truncation. It must never contain parameter values,
timestamps, SQL, detail/data from rows, the result object, exception text, or a
serialized query. Append the audit after the read, so querying prior audit rows
cannot recursively include the audit for the current response.

Bound and redact audit identity strings before persistence: actor id 256 chars,
department/rank 64 chars, each parameter name 64 chars, and at most ten names.
Invalid and ordinary failed attempts make a best-effort content-free audit;
unavailable storage cannot. A successful read must not return rows unless its
success audit commits. A denial remains denied if its audit ordinarily fails.
An invalid request also remains its stable invalid code if its best-effort audit
ordinarily fails; use `aggregate="none"` unless the raw aggregate is already an
exact allowed value, and set `window_seconds=None` unless the window fully
validates. Cancellation during query or any audit propagates unchanged and
returns no rows.

### Authorization and denial audit

Extend `ToolRegistration` and `ToolRegistry.register` with one backward-
compatible optional `allowed_departments: tuple[str, ...] | None`. Preserve the
existing singular `department` behavior. `resolve_permission`, `list_tools`,
and `to_dict` must enforce/project both fields. When non-None, serialize
`allowed_departments` as a JSON list; when None, omit that key so every existing
registration retains its exact serialized shape and behavior.

Register `event_log_query` with:

```python
provider="event_log"
tags=["event_log_query", "event_log", "diagnostics", "read_only"]
allowed_departments=("engineering", "science", "security")
default_permissions={
    "ensign": "none",
    "lieutenant": "read",
    "commander": "read",
    "senior_officer": "read",
}
```

The existing `ToolPermissionStore` may elevate an eligible-department Ensign to
READ or restrict any eligible agent to NONE. A grant never bypasses the allowed
department set. The Tool accepts only the existing exact rank values `ensign`,
`lieutenant`, `commander`, and `senior_officer`; unknown department/rank fails
closed even if a malformed grant exists.

Before Tool invocation, `ToolRegistry.check_and_invoke` must overwrite, not
`setdefault`, these context keys from its authoritative arguments:
`agent_id`, `agent_department`, `agent_rank`, `agent_types`, and `permission`.
This prevents forged context from bypassing the Tool's second check. The Tool
requires an allowed department and resolved permission including READ; it does
not trust similarly named fields in `params`.

Add a small runtime-checkable `ToolDenialAuditor` protocol in
`tools/protocol.py`. On a permission denial for a registered Tool implementing
it, `ToolRegistry` awaits `audit_denied_invocation` before raising the existing
`ToolPermissionDenied`. Pass only server-owned identity/rank/department,
required/held permission, and sorted bounded parameter names; never values. Its
exact fully annotated method is:

```python
async def audit_denied_invocation(
  self,
  *,
  actor_id: str,
  department: str,
  rank: str,
  required: ToolPermission,
  held: ToolPermission,
  parameter_names: tuple[str, ...],
) -> None: ...
```

Collect names only when `type(params) is dict`: inspect at most ten insertion-
ordered entries, accept only exact strings capped at 64 chars, then sort the
accepted names.
Ordinary audit failure is logged with context and denial still fails closed.
Cancellation propagates. Existing non-audited Tools are unchanged.

### Startup, discovery, and AgenticLoop

Thread `event_log_reader: EventLogReaderProtocol | None` and
`event_log_audit_sink: EventLogQueryAuditSink | None` into the live
`init_communication` signature and its sole caller; pass the existing
`self.event_log` for both narrow ports. Construct no adapter database and expose
no path. In `init_communication`, after the permission store is attached,
register `EventLogQueryTool(reader=event_log_reader,
audit_sink=event_log_audit_sink)` only when both ports are non-None and both
conditions hold:

1. `config.agentic_dispatch.orchestrator_enabled` is true; and
2. both `event_log_reader` and `event_log_audit_sink` are not None.

The existing Pydantic flag defaults false. Add no config field and do not edit
YAML. Gate off means no registration and no discovery entry.

In `WorkItemAgenticExecutor.run`, offer the already-registered Tool only when
`registry.check_permission` succeeds for the server-owned agent id, department,
and rank. Add it to the existing deduplicated `tool_ids`; do not create another
loop or executor. Its result returns to the same AgenticLoop for a later
reasoning turn.

Remove the live phantom `eventlog_diagnostic_query` instruction block,
capability, IntentDescriptor, and `_handled_intents` member from
`EngineeringAgent`. Replace the AD-664 descriptor-only assertions with proof of
the callable Tool path. Live source search found no `/api/system/events`
teaching to remove: do not add that route, another route, shell command,
endpoint hint, file/path hint, or fallback teaching, and do not perform
unrelated cleanup for an absent string.

Update the frozen AD-398 Engineering identity assertion exactly as authorized
in the binding continuation adjudication. Preserve its three identity
descriptors and its coverage of the two legitimate Engineering intents; never
reintroduce the phantom or teach the Tool as an agent intent.

## Implementation Sections

| Section | Work |
|---|---|
| 1 | Add typed protocols and fixed governed adapter in `protocols.py` / `substrate/event_log.py`; preserve legacy APIs. |
| 2 | Add only the specified registration/context/denial-audit behavior in `tools/protocol.py` / `tools/registry.py`; no permission rewrite or store change. |
| 3 | Create `tools/event_log_query_tool.py`, separately injecting the reader and audit-sink protocols. Imports: stdlib, boundary types, Tool types only; never SQLite, path, concrete EventLog, network, runtime/API, or private DB state. |
| 4 | Thread/register/expose through live `startup/communication.py`, its `runtime.py` caller, and `cognitive/agentic_dispatch.py`. The `runtime.py` edit is limited to passing the existing `self.event_log` through both narrow ports; do not touch `startup/finalize.py` or any CrewSession ingress path. |
| 5 | Remove only the four verified Engineering phantom declarations, update the obsolete AD-664 assertions, and correct only the frozen AD-398 Engineering identity assertion as bound above; preserve identity plus engineering analyze/optimize behavior. |

## Tests

Create `tests/test_ad1129_eventlog_query_tool.py`; update
`tests/test_ad664_eventlog_diagnostic.py` only for the obsolete phantom claims;
update only `TestNewAgentInstantiation.test_engineering_agent_attributes` in
`tests/test_ad398_crew_identity.py` under the exact continuation contract above.
Use real `EventLog(tmp_path)`, real `ToolRegistry`, real cache-only or tmp-path
`ToolPermissionStore`, real Tool/Executor boundaries, and a scripted LLM. No
MagicMock at EventLog, permission, registry, executor, or AgenticLoop edges.

Required named coverage:

1. exact filter conjunction, UTC normalization, both orders, empty result;
2. `min(limit, 200)+1` normal/aggregate truncation sentinels, including the
  aggregate 201st-row ceiling;
3. exact eleven-key projection, recursive redaction, secret-key replacement,
  hostile container/type rejection, oversized raw detail/data pre-decode caps,
  row cap, and both final byte-accounting representations including the actual
  AgenticLoop tool-result string;
4. exact 61 total / 49 top cooperation signature through the public adapter;
5. invalid/missing/None/unknown filters, bool/negative/huge limit, naive or
   malformed time, reversed/zero/over-seven-day window;
6. `_db is None` unavailable result and ordinary DB/audit failure with no raw
   exception or row leakage;
7. query and audit cancellation propagate unchanged;
8. Engineering/Science/Security rank defaults, eligible Ensign READ grant,
   restriction to NONE, wrong department, unknown rank, forged-context defeat;
9. success and registry-level denial audits contain identity/names/counts but
   no values, rows, secrets, SQL, or recursive current audit;
10. gate-off absence, gate-on central registration, list/discovery metadata,
    idempotent single registration;
11. scripted AgenticLoop calls the Tool, receives the 61/49 aggregate, and uses
    it in a later final reasoning turn;
12. legacy EventLog query/query_structured/hash-chain behavior and unrelated
    ToolRegistry registrations remain unchanged.
13. frozen AD-398 Engineering identity coverage preserves agent type, tier,
  instructions, and the exact two legitimate intent/handled names while the
  phantom is absent; governed Tool discovery remains separately proven here.

## Allowed Files

- `src/probos/protocols.py`
- `src/probos/substrate/event_log.py`
- `src/probos/tools/protocol.py`
- `src/probos/tools/registry.py`
- `src/probos/tools/event_log_query_tool.py` (new)
- `src/probos/startup/communication.py`
- `src/probos/runtime.py` (direct `self.event_log` reader/audit argument threading only)
- `src/probos/cognitive/agentic_dispatch.py`
- `src/probos/cognitive/engineering_officer.py`
- `tests/test_ad1129_eventlog_query_tool.py` (new)
- `tests/test_ad664_eventlog_diagnostic.py`
- `tests/test_ad398_crew_identity.py` (only `TestNewAgentInstantiation.test_engineering_agent_attributes`)
- `tests/test_ad1072_agentic_tools.py` (final adjudication: only the bound delegation authority fixtures/helpers and exact three-node setup)

Pre-existing Architect artifacts included unchanged in the local commit:

- `prompts/ad-1129-governed-event-log-query.md`
- `prompts/ad-1129-governed-event-log-query-execution.md`

Any other path is a hard stop for Architect adjudication.

## What This Does NOT Change

- No arbitrary SQL, SQL parameter, JSON path, global search, FTS, or export.
- No caller-selectable EventLog write, delete, prune, wipe, hash-chain, schema,
  migration, or index change; only the fixed content-free governance audit
  append specified above is added.
- No direct SQLite, DB path, filesystem, HTTP, WebSocket, route, or API endpoint
  from the Tool.
- No new agent, pool, intent, executor, loop, database, dependency, EventType,
  config field, YAML, shell command, UI, or commercial surface.
- No AD-1128 ingress/reservation/dedup/resume behavior and no AD-1130+ trust, Shapley, delivery,
  notification, metrics, HXI projection, or live-push work.
- No deletion or weakening of AD-398 crew identity coverage and no change to
  another function or fixture in `tests/test_ad398_crew_identity.py`.
- No tracker update, prompt archive move, full suite, or push before AD-1133.

## Final Static Closeout

Only after the exact three-node serial run and Architect implementation
approval:

1. keep `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, and both
  active prompt paths unchanged;
2. perform only static scope, whitespace, fixture, and prompt hash/size audits;
  do not rerun pytest; and
3. report the approved one-file AD-1072 fixture delta and three-node result.

Do not stage, commit, push, mutate GitHub, update trackers, archive prompts, or
begin AD-1130 work under this handback.

## Acceptance Criteria

- The real EventLog public adapter and Tool reproduce the 61/49 cooperation
  signature with fixed bounded semantics.
- Authorization combines allowed department, rank defaults, and existing
  grants/restrictions; forged context cannot elevate access.
- Successful and denied attempts are audited without query values or returned
  content; cancellation is never swallowed.
- All rows and aggregates are exact, redacted, deterministic, and byte-bounded.
- Unavailable DB and ordinary failures honestly degrade without leaking rows or
  exception text.
- The Tool is absent while the existing orchestrator gate is false and is
  discoverable/invokable through the existing AgenticLoop when enabled.
- The verified phantom descriptor is removed; no event HTTP endpoint or new
  endpoint/path teaching is introduced.
- The frozen AD-398 Engineering identity test retains its three identity
  descriptors and two legitimate Engineering intent names, explicitly rejects
  the phantom, and does not model the governed Tool as an agent intent.
- Only the bound AD-1072 fixture regions change after this final prompt
  amendment; all production, dedicated AD-1129 tests, AD-1128 ingress, and
  AD-1130+ remain untouched.
- The prior changed-surface batch remains recorded as `220 passed / 3 failed`;
  only the three exact AD-1072 nodes pass together under `-n 0` after their
  authority-fixture repair. Do not rerun the 223-node batch, a baseline, a
  per-AD additive equation, an AD-1129 node, or a full suite.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-07-21)

Verification used the live local AD-1128 HEAD. CrewSession ingress files are not
part of this build; `runtime.py` is a direct integration only.

```text
src/probos/protocols.py:84
  class EventLogProtocol(Protocol):
src/probos/substrate/event_log.py:51
  class EventLog:
src/probos/substrate/event_log.py:142
  async def log(
src/probos/substrate/event_log.py:203
  async def query(
src/probos/substrate/event_log.py:242
  async def query_structured(
src/probos/substrate/event_log.py:321
  def _row_to_dict(row: tuple) -> dict:
src/probos/tools/protocol.py:140
  class ToolRegistration:
src/probos/tools/registry.py:49
  class ToolRegistry:
src/probos/tools/registry.py:191
  def resolve_permission(
src/probos/tools/registry.py:269
  async def check_and_invoke(
src/probos/tools/permissions.py:39
  class ToolPermissionStore:
src/probos/cognitive/swe_harness/agentic_loop.py:207
  raw_result = await self._executor.invoke(
src/probos/cognitive/agentic_dispatch.py:533
  class WorkItemAgenticExecutor:
src/probos/startup/communication.py:38
  async def init_communication(
src/probos/startup/communication.py:335
  tool_registry = ToolRegistry()
src/probos/startup/communication.py:485
  tool_registry.set_permission_store(tool_permission_store)
src/probos/runtime.py:2294
  comm = await init_communication(
src/probos/runtime.py:2307
  nats_bus=self.nats_bus,
src/probos/cognitive/agentic_dispatch.py:142
  class DispatchToolExecutor(ToolExecutor):
planning-base evidence, superseded by the live-partial evidence below
  engineering_officer.py had four eventlog_diagnostic_query declarations;
  test_ad664_eventlog_diagnostic.py had descriptor-only phantom assertions
src/probos/dream_adapter.py:264
  async def _event_log_emergent(...)
src/probos/cognitive/emergent_detector.py:368,386,581,583
  cooperation cluster description/evidence with intents and avg_weight
logs/crew-collaboration-epic-architect-report-2026-07-17.md:687-732
  #1048 decision, acceptance, tests, and exclusions
src/probos/config.py:6113
  orchestrator_enabled: bool = False
local HEAD supplied for this rebase
  3969c80b0a0f4a804a8528268f4561ca86887772 / AD-1128 / BF-673
src/probos/cognitive/engineering_officer.py:37-52 (live partial implementation)
  only engineering_analyze / engineering_optimize capabilities, descriptors, and handled intents
tests/test_ad398_crew_identity.py:271-278
  identity assertions preserved; stale len == 3 and phantom-inclusive handled set require the exact correction above
tests/test_ad664_eventlog_diagnostic.py:196-212 (live partial implementation)
  capability, descriptor, and handled-intent phantom absence already asserted
src/probos/startup/communication.py:490-512 (live partial implementation)
  centrally registers event_log_query under the existing gate and department/rank policy
src/probos/cognitive/agentic_dispatch.py:788-799 (live partial implementation)
  offers event_log_query only after registry permission succeeds
src/probos/cognitive/agentic_dispatch.py:77-132 (final adjudication input)
  resolver treats registry/ontology/trust as one authority set, calls exact
  registry.get, ontology.get_agent_department, and trust_network.get_score,
  and normalizes every ordinary failure to agentic_identity_unresolved
src/probos/consensus/trust.py:112,406-410
  real TrustNetwork is in-memory when db_path is absent and returns its
  Beta(2,2) prior score of 0.5 for an unknown fixture agent
src/probos/crew_profile.py:30-46
  Rank.from_trust maps score 0.5 to lieutenant
tests/test_ad1072_agentic_tools.py:288-299 (final adjudication input)
  _AgentRegistry has get_by_pool/all but no exact get lookup
tests/test_ad1072_agentic_tools.py:316-334 (final adjudication input)
  _delegation_runtime supplies registry but omits ontology/trust
tests/test_ad1072_agentic_tools.py:370,400,570 (final validation nodes)
  the exact happy-path, resting-agent, and parent-loop delegation tests cross
  into nested authoritative WorkItemAgenticExecutor execution
```

The Builder must repeat these searches at the exact local HEAD before editing
and hard-stop on any mismatch. Do not reset, rebase, stash, or create a parallel
worktree; this is the intentional local batch sequence. Before production
editing, mechanically record SHA-256 and byte length for both final prompts and
freeze those bindings; the supplied initial hashes above are provenance only
and must not be reused as post-rebase values.

## Prompt Review Record

### Pass 1 - Scope and AD-1128 rebase (2026-07-21)

**Verdict: APPROVED after rebase.** Exact local AD-1128 HEAD
`3969c80b0a0f4a804a8528268f4561ca86887772`; origin retained as `e33955a8`;
CrewSession ingress remains untouched; `runtime.py` is direct injection only;
one Tool and no AD-1130+ work. Because no endpoint teaching exists, delete only
the verified phantom Engineering declarations and add no endpoint/path teaching.

### Pass 2 - Contract, security, and data bounds (2026-07-21)

**Verdict: APPROVED after correction.** Exact typed filters/rows/aggregate/audit,
half-open UTC window, order/limits, bounded input-name scans, JSON detachment,
redaction, canonical-plus-live output caps, fixed 61/49 aggregate, auth, audit,
unavailable storage, and cancellation are pinned. Read and audit protocols are
separately injected; no SQLite/path/network reaches the Tool.

### Pass 3 - Execution and readiness (2026-07-21)

**Verdict: APPROVED.** Existing default-off gate; ToolRegistry/capability
discovery/AgenticLoop invocation; caller-bounded aggregate; all coding before
one `-n 16 --dist=worksteal` changed-surface batch; Architect code review;
exact local-only commit with active prompts retained; trackers, archives, broad
gate, and push deferred through AD-1133.

### Adjudication Pass 1 - Continuation scope (2026-07-21)

**Verdict: APPROVED.** Preserve the partial live AD-1129 implementation. Add
only the frozen AD-398 Engineering identity function to the existing test-edit
surface; no other AD-398 function, fixture, production scope, or tracker changes.

### Adjudication Pass 2 - Identity and discovery contract (2026-07-21)

**Verdict: APPROVED.** Keep agent type, tier, instructions, and the exact two
legitimate Engineering intents. Assert the phantom absent; prove
`event_log_query` through governed Tool registration/discovery, never as an
Engineering intent or handled intent.

### Adjudication Pass 3 - Execution readiness (2026-07-21)

**Verdict: APPROVED.** Add the frozen identity file to the allowlist and the
single changed-surface batch. Coding remains first; the only pytest batch stays
`-n 16 --dist=worksteal`. Final prompt hashes and sizes are a required
mechanical binding step before Builder continuation.

### Code-review Adjudication Pass 1 - Authority and scope (2026-07-21)

**Verdict: APPROVED after required correction.** Preserve the live EventLog and
all completed AD-1129 query/Tool/startup work. The repair delta is exactly four
production paths plus the AD-1129 test file; AD-1130, trackers, Git/GitHub, and
all other source/tests remain outside this adjudication.

### Code-review Adjudication Pass 2 - Identity and context security (2026-07-21)

**Verdict: APPROVED after required correction.** One cognitive-layer resolver
uses exact AgentRegistry identity, ontology plus standing-orders fallback, and
`Rank.from_trust(live score)`. Its one tuple binds discovery and invocation.
Legacy privilege input is restricted to the no-resolver/no-EventLog case;
extras merge first and server-owned reserved context overwrites last.

### Code-review Adjudication Pass 3 - Execution binding (2026-07-21)

**Verdict: APPROVED.** Real registered Engineering execution proves 61/49
without injected privilege; forged reserved context and exact `-1` / `10**100`
limits are binding regressions. Validation remains one scoped
`-n 16 --dist=worksteal` batch. Mechanically report amended prompt hashes and
byte lengths before any implementation continuation.

### Final Adjudication Pass 1 - Failure classification (2026-07-21)

**Verdict: PRODUCTION APPROVED; TEST FIXTURE REPAIR REQUIRED.** The reported
`220 passed / 3 failed` batch isolates all failures to the three AD-1072
delegation nodes. Their runtimes provide `registry` but omit ontology/trust,
which is partial authority and must fail closed. This is stale fixture setup,
not evidence for weakening the AD-1129 resolver.

### Final Adjudication Pass 2 - Repair scope and authority (2026-07-21)

**Verdict: APPROVED after binding correction.** Add only
`tests/test_ad1072_agentic_tools.py` to the allowlist. Repair its shared
delegation fixtures with exact registered identity, protocol-faithful ontology,
and real in-memory trust. No MagicMock, phantom attributes, production fallback,
delegation behavior change, or depth-test mutation is authorized.

### Final Adjudication Pass 3 - Serial closeout (2026-07-21)

**Verdict: READY.** Rebind both amended prompt hashes/sizes, run only the three
exact AD-1072 nodes together under `-n 0`, then perform static audits. The
223-node batch, AD-1129 tests, broad gates, Git/GitHub, trackers, archives, and
AD-1130 remain forbidden.