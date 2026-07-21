# AD-1126 - Verified CrewSession finalization and result publication

**Verdict:** READY FOR REPAIR HANDOFF
**One-line:** Claim one durable session at `executing -> verifying`, project the ordinary governed correction capability surface without mutating the shared registry, converge every required child without learning side effects, and commit verified publication only behind one final store-owned direct-child barrier.

**Parent epic:** [#1041](https://github.com/seangalliher/ProbOS/issues/1041) - Durable Crew Work Sessions
**GitHub issue:** [#1045](https://github.com/seangalliher/ProbOS/issues/1045) - AD-1126
**Dependency:** [#1044](https://github.com/seangalliher/ProbOS/issues/1044) / AD-1125 is `CLOSED`
**Repository:** OSS `D:\ProbOS`
**Exact base HEAD / `origin/main`:** `cedd01e7d219eac39721d36decbeafd4ffc3b571`
**Exact base subject:** `AD-1125: bind crew execution to work rooms (closes #1044)`
**Exact base status before Architect artifacts:** clean `main`; no staged, modified, deleted, or untracked paths. This remains the historical comparison base, not the repair-tree status requirement.
**Authoritative repair-tree status:** the seven authorized tracked AD-1126 files are modified and the two authorized AD-1126 source/test files plus both active prompts are untracked; no path is staged. Record exact repair-input hashes before editing and preserve every unrelated byte.
**Numbering:** current top-level ceiling **AD-1125**; current bug-fix ceiling **BF-673**; build **AD-1126** only
**Issue state:** #1041 `OPEN`; #1044 `CLOSED`; #1045 `OPEN`
**Current authoritative full gate:** **19,731 passed / 33 skipped / 431 warnings / 0 failed** on the exact base, with all 431 warnings provenance-only and pre-existing and zero changed-path warnings
**License disposition:** no external code, dependency, model, or asset
**Test arithmetic:** let `N` be the exact number of cases collected and passed in `tests/test_ad1126_verified_finalization.py` only after all adjudicated repairs are complete. Discover `N`; never bind the current pre-repair count or predict the final count.

## Scope

AD-1126 owns only the foreground finalization slice after shipped AD-1125 fan-out:

1. inject one focused `CrewSessionFinalizer` into `CrewOrchestrator`;
2. atomically claim a valid durable session by moving `executing -> verifying` before verification work;
3. require a non-empty, exact set of all live child WorkItems and matching AD-1125 `SubtaskResult`s; there is no optional-child field, so every child is required;
4. converge each successful child with the live assigned producer's real `instructions`, the child's real `description or title`, and the exact bound room context;
5. use new side-effect-free session verifier APIs and an event-neutral correction capability projection built only from public registry/runtime surfaces; do not call the legacy trust-writing `verify()` / `converge()` methods;
6. persist one exact bounded round-history contract to each child's first-class `verification` column through a public store-owned exact CAS;
7. synthesize accepted child outputs through a new output-only `CrewSynthesizer` API with the session facilitator as the server-selected synthesis producer;
8. independently verify the final synthesis against the exact parent goal, all success criteria, the expected deliverable, and the available child artifact manifest;
9. persist the final UTF-8 text as versioned `crew-result.md` in the exact bound room through the existing AttachmentStore and ArtifactStore;
10. persist one bounded full provenance document to AttachmentStore by SHA-256;
11. atomically merge exact bounded `crew_synth` metadata and the `crew_session` done contract with both final refs only after one store-owned, same-lock/same-transaction re-query proves the exact required direct-child set and every exact post-verification child snapshot;
12. map authority/capability gaps to `blocked_needs_captain`, defects/refutation exhaustion to `failed`, and never complete missing, malformed, empty, partially verified, or unpublished work.

Legacy non-`crew_session` parents retain the complete AD-867 -> AD-860 -> AD-861 path byte-for-byte in behavior. AD-1126 adds no scheduler, restart recovery, ingress, dedup, trust credit, event product, API, UI, or WebSocket behavior.

---

## Authoritative repair adjudication

This section is normative. It preserves every existing decision below except where it explicitly supersedes pre-repair claim, correction-runtime, child-barrier, post-commit reconciliation, denied-tool, test-order, hash, or gate wording.

### RA-1 - Final publication owns one exact direct-child barrier

The per-child verification CAS remains the only child write. It is necessary but not sufficient for parent completion. Immediately after each successful child CAS, the finalizer must retain the exact returned post-verification row as one detached semantic snapshot. Immediately before parent publication, `CrewSessionService.publish_verified_result(...)` must pass the complete sorted snapshot tuple to a new public WorkItemStore publication API:

```python
async def publish_work_item_metadata_with_child_barrier(
    self,
    work_item_id: str,
    patch: dict[str, Any],
    *,
    expected: dict[str, Any],
    expected_absent_keys: frozenset[str],
    expected_present_keys: frozenset[str],
    expected_work_type: str,
    expected_status: str,
    expected_assigned_to: str,
    expected_direct_children: tuple[dict[str, Any], ...],
    new_status: str,
    source: str = "crew_session_verified_result",
) -> WorkItem | None:
    ...
```

Each `expected_direct_children` entry has exactly these 23 durable semantic keys, with no extras:

```text
id
title
description
work_type
status
priority
parent_id
depends_on
assigned_to
created_by
created_at
due_at
estimated_tokens
actual_tokens
trust_requirement
required_capabilities
tags
metadata
steps
verification
schedule
ttl_seconds
template_id
```

Exact snapshot semantics:

- the tuple contains `1..1000` entries in strictly increasing `id` order with unique bounded ids;
- every `parent_id` equals the publication parent, every status is exact `done`, and each snapshot is built from the authoritative WorkItem returned by that child's successful verification CAS;
- every durable WorkItem field except server-maintained `updated_at` is covered; no priority, creator, timing, estimate, trust requirement, capability, tag, step, schedule, TTL, or template drift can pass;
- scalar types are exact; booleans never alias integers, numeric values are finite, nullable fields preserve missing type/value exactly, and container subclasses are invalid;
- `depends_on`, `required_capabilities`, `tags`, and `steps` are ordered lists whose order is significant; their entries retain exact recursive JSON types;
- `metadata`, `verification`, and `schedule` are detached finite JSON objects compared recursively by exact JSON type and value: object key order is irrelevant, object key sets are exact, and array order is significant;
- canonical compact JSON uses `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, and `allow_nan=False`; invalid UTF-8/surrogates, NaN/infinity, non-string object keys, aliases, or over-bound documents reject before lock admission.
- each canonical snapshot is at most 1,572,864 UTF-8 bytes and the running sum for the complete tuple is at most 33,554,432 bytes; validate and detach one snapshot at a time, reject before lock admission on overflow, and never build a second aggregate JSON document.

The new store method validates and detaches every expected snapshot before mutation. Under the existing `_work_item_row_write_lock`, and on the same injected WorkItemStore connection/transaction as the parent update, it must:

1. execute explicit `BEGIN IMMEDIATE` after acquiring the row lock and before the first parent/child read, so proof and mutation are one real SQLite transaction on this store connection;
2. reload and validate the parent CAS preconditions inside that transaction;
3. execute a direct bounded database re-query for `parent_id = work_item_id`, ordered by child id and limited to 1,001 rows, without calling the public lock-taking list method;
4. reject zero children, 1,001 rows, any different direct-child id set, or any field mismatch against any expected snapshot with stable `ValueError("work_item_child_barrier_conflict")`;
5. perform the parent metadata/status update only after all comparisons succeed;
6. commit the proof and parent `done` update atomically, or roll back the transaction on any `BaseException`;
7. refresh caches and emit only the existing generic WorkItem events after commit.

No intermediate commit, child rewrite, retry, schema/DDL, global connection lock, or restart recovery is permitted. `BEGIN IMMEDIATE` is scoped to this one publication method on its existing connection; it does not redesign transaction ownership for booking/journal writers. The barrier is authoritative for post-CAS child state; do not add a separate per-child reconciliation loop.

Extend the public store protocol in `crew_session.py`, and extend the public service contract exactly as follows:

```python
async def publish_verified_result(
    self,
    parent_id: str,
    *,
    expected_revision: int,
    expected_direct_children: tuple[dict[str, Any], ...],
    crew_synth: CrewSynthesisMetadata,
    last_result_summary: str,
    provenance_ref: str,
    result_artifact_id: str,
) -> CrewSessionContract:
    ...
```

The service must call `publish_work_item_metadata_with_child_barrier(...)` exactly once for the success path. Generic `merge_work_item_metadata(...)` remains unchanged for all other callers and may not be used for AD-1126 success publication.

### RA-2 - Corrections receive an event-neutral governed capability projection

The current empty private registry is invalid because it silently removes the producer's ordinary correction tools. Implement the repair only in additive session-specific code in `crew_verifier.py`; `agentic_dispatch.py`, `ToolRegistry`, runtime construction, and every tool implementation remain frozen.

`_session_correction_runtime(...)` must accept the correction `agent_id`, `department`, and `rank`, and build one detached local ToolRegistry plus a narrow immutable runtime facade. It must never pass the raw runtime to `WorkItemAgenticExecutor.run()`, never install an event callback, never mutate/register/unregister against `runtime.tool_registry`, and never forward a generic `__getattr__` or raw runtime reference.

Pin the projection mechanics to existing public surfaces:

1. Read the source registry only through `get`, `list_tools`, and `check_and_invoke`; read active grants through `tool_permission_store.get_active_grants_sync`; read mesh policy through `intent_grant_store.resolve_sync`; read MCP/runtime feature gates and collaborators through their named public runtime attributes.
2. Compute the same ordered/deduplicated capability categories as the ordinary executor: active-grant static ids, the existing mesh tool ids, currently registered MCP/search ids when MCP agent tools are enabled, and the gated runtime-contributed ids `run_python`, `use_skill`, `search_capabilities`, and `delegate_task`. Bound each source scan and reject malformed/over-limit ids through the explicit-denial path; no hostile source can force unbounded projection work.
3. For a source registration that can be faithfully projected, register a local adapter that copies only its public ToolRegistration definition and delegates invocation through the source registry's public permission/LOTO/governance path using the exact correction agent/department/rank/context. The local registry has no event callback. Permission denial remains an exact denied tool; a lock held by another agent remains an explicit tool error/denial and never invokes the tool.
4. Register mesh adapters only into the detached registry against the public intent bus. Apply the public intent-grant decision before execution. An explicitly restricted mesh id remains visible as a local explicit-denial adapter rather than disappearing.
5. When MCP agent tools are enabled, inspect source `get("find_mcp_tool")` first. Only when that registration already exists may the projection call public `mcp_workbench.dispatch_tool_ids(agent_id)`, because its `register_search_tool()` branch is then an idempotent no-op; project the returned exact ordered ids through source registrations. When it is absent, do not call the mutating helper: project stable `find_mcp_tool` plus every enabled public source registration tagged/provider-classified as MCP as explicit denied definitions. Any returned id whose registration is missing also becomes explicit denied. Never read workbench private state.
6. For each enabled runtime-contributed stable id, use a source-backed adapter when its public registration exists. Otherwise pre-register an explicit-denial adapter with that exact stable id so the frozen executor neither constructs a runtime-bound tool against the facade nor silently omits it.
7. A selected static grant whose registration disappeared between grant resolution and projection likewise becomes an explicit-denial adapter. No selected capability may be silently dropped because a registration, policy dependency, or safe projection collaborator is unavailable.
8. Implement a private local `ToolRegistry` subclass in `crew_verifier.py` whose `check_and_invoke(...)` first checks an immutable explicit-denial id set and raises the existing `ToolPermissionDenied` with held permission `NONE` before consulting any grant. `DispatchToolExecutor` records that exact id in `denied_tools`; Captain grants cannot re-enable an id declared unsafe/unavailable by projection, and no second denial channel is introduced.
9. For immutable source-backed ids, the same override delegates the complete invocation to source `check_and_invoke(...)`, forwarding exact required permission, department, rank, agent types, and detached context. For local mesh ids, it delegates to `super().check_and_invoke(...)`. The id sets are disjoint, bounded, and frozen at projection construction; an unknown id fails closed through the local registry.
10. Supply a detached intent-grant facade that returns `no_opinion` for precomputed restricted mesh ids because their denial is already encoded in the local registry; all unrestricted decisions delegate to the public source policy. This changes visibility only, never authorization: restricted invocation still fails before mesh broadcast.
11. Supply a detached MCP id provider and exact named config/collaborator fields on the facade so the frozen executor observes the precomputed set without shared mutation. Set `event_emit_fn`/`emit_event` absent or `None`; the projection itself creates no event, episode, metric, trust, or capability-gap write.
12. Resolve duplicate ids deterministically in ordinary executor category order. A valid source-backed registration wins over a local mesh/runtime constructor because it preserves the already-wired governed tool. A local mesh adapter wins only when no source-backed registration exists. Mark an id explicit-denial only when every selected representation is restricted, missing, malformed, unsafe, or would require shared mutation. Never let one unavailable category hide another safe governed representation of the same id.

The projected registry must not weaken ordinary permission, rank, department, restriction, MCP risk/consensus, or exclusive-lock behavior. Source-backed invocation delegates through source `check_and_invoke(...)`, so the source registry remains authoritative for permission and lock state at invocation time; the local copy is visibility plus a fail-closed projection policy, not an authority fork. Existing tool-owned operational effects remain governed by their existing implementation; AD-1126 adds no finalization-specific event, episode, or metric. The real tool result must still reach the next AgenticLoop request exactly as in AD-1125.

### RA-3 - Local claim waiters have one bounded retry

Local ownership never changes the public state contract:

- every invocation whose first authoritative load is `verifying` raises exact `ValueError("crew_session_finalization_in_progress")`, even when `_active_claims` contains a local owner;
- an invocation that first loads `executing` and then finds a local active claim waits only for that owner's `executing -> verifying` claim attempt to settle, reloads the session exactly once, and performs zero child/result/storage work while waiting;
- if that one reload is still `executing` because the owner was cancelled before the `executing -> verifying` claim committed, the waiter receives exactly one direct claim attempt and may continue only if that attempt succeeds;
- there is no recursive `finalize()` call, retry loop, second local wait, lease, watchdog, or resume;
- if the owner was cancelled after the claim committed, the reload observes `verifying`; the waiter returns a truthful non-completed observation and performs no claim, child, verifier, synthesis, Artifact, Attachment, or publication work;
- the local event is signaled in every success/error/cancellation path immediately after the claim attempt settles; map cleanup is identity-safe at that boundary and is not held for the rest of finalization.

This is foreground same-process contention handling, not AD-1127 recovery.

### RA-4 - Commit proof is exact; post-commit siblings are not authority

The parent publication CAS still requires `expected_present_keys` for every unrelated metadata sibling observed before admission, so a sibling deleted before the store-owned commit conflicts. After a commit may have occurred, authoritative reconciliation proves only:

- parent id/work type/status `done` and exact facilitator assignment;
- exact JSON `crew_session` and `crew_synth` documents expected by this publication;
- exact `result_artifact_id` and provenance/result refs, including their cross-document equality.

Post-commit reconciliation must not require unrelated sibling keys or values to remain present, must not restore them, and must not write anything. A sibling deleted after the parent commit therefore still returns the authoritative `done` contract. Pre-commit sibling deletion remains a CAS conflict.

### RA-5 - Denied-tool validation is total and shared

Use one total validator for both correction-terminal classification and persisted `terminal_attempt.denied_tools` construction. The outer value is valid only when `type(value) is list` or `type(value) is tuple`; subclasses and every other type are invalid. It inspects at most 65 entries to enforce the 64-entry ceiling and returns either one detached ordered-unique tuple or a deterministic invalid result; it never leaks `UnicodeEncodeError`, `TypeError`, container callback errors, or raw values.

Each valid id is exact built-in `str`, non-empty, NUL-free, at most 256 code points and 1,024 strict UTF-8 bytes. Whitespace-only ids such as `"   "` are valid, preserved byte-for-byte, and never stripped or normalized. Invalid container/type, empty id, duplicate id, NUL, invalid UTF-8/unpaired surrogate, count, code-point, or byte limit maps to `correction_execution_defect` without raising. Classification and persistence consume the same validated tuple; neither path re-parses or normalizes it.

### RA-6 - Prior repaired decisions remain binding

Accepted-count computation counts only exact accepted child publication outcomes; convergence binds each verdict/history entry to the exact revision it judged; artifact evidence resolution and final-manifest authority remain exact; cancellation propagates with the RA-3 claim distinction; output-only verification/synthesis and all existing side-effect boundaries remain binding. No adjudicated repair weakens any earlier bound, identity proof, provenance rule, publication order, or legacy AST/frozen-file requirement.

---

## Resolved design questions

### DD-1 - Every child is required; optionality is not representable

The live `WorkItem` and `CrewSessionContract` expose no optional-child field, and issue #1045 requires all non-optional children. Therefore AD-1126 inspects at most 1,001 direct children with:

```python
await WorkItemStore.list_work_items(parent_id=parent_id, limit=1001)
```

It rejects a 1,001-entry result as `child_result_invalid`; otherwise every returned child is required. The independent 1,001 inspection ceiling proves overflow instead of silently truncating at 1,000. After the `verifying` claim and before any child verification, the finalizer must enforce all of the following:

- child count is in `1..1000`;
- child ids are unique bounded ids;
- the supplied AD-1125 results have exactly the same unique child-id set;
- every supplied result has `status == "done"`, `stopped_reason == "complete"`, a non-empty producer id, and non-empty output;
- every reloaded child still has the same parent id, `status == "done"`, the same `assigned_to` producer, and exact AD-1125 `metadata["crew_execution"]` identity;
- each producer resolves to the current `AgentRegistry.get(producer_id)` object with matching id and public `is_alive is True` before its verification/convergence begins;
- no failed, blocked, missing, duplicate, extra, or empty-result child is silently omitted.

There is no partial-done carveout and no prose/tag inference of optionality. A future structured optional-child contract requires a separate AD.

### DD-2 - New session verifier APIs are output-only; legacy methods remain unchanged

The live `SubtaskVerifier.verify()` records trust, and `converge()` calls it. Add separate public, fully typed APIs for AD-1126; do not route them through the trust-writing methods:

```python
async def verify_for_session(
    self,
    result: SubtaskResult,
    *,
    expected_output: str | None,
    excluded_agent_ids: frozenset[str],
) -> SessionVerificationPass:
    ...

async def converge_for_session(
    self,
    result: SubtaskResult,
    *,
    instructions: str,
    task_text: str,
    expected_output: str | None,
    parent_id: str,
    thread_id: str,
    department: str,
    rank: str,
) -> SessionConvergenceOutcome:
    ...
```

Add frozen result dataclasses in `crew_verifier.py` for the in-memory session path. They must retain all information needed to build the persisted contract without mutable aliases:

```python
@dataclass(frozen=True)
class SessionVerificationPass:
    status: Literal["accepted", "refuted", "unavailable", "malformed", "error"]
    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str
    tokens_used: int
    failure_code: SessionVerificationFailureCode | None

@dataclass(frozen=True)
class SessionVerificationRound:
    round_index: int
    result_revision: int
    result_text: str
    result_sha256: str
    result_summary: str
    stopped_reason: str
    correction_tokens: int
    verifier_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[dict[str, Any], ...]
    verdict: SessionVerificationPass

@dataclass(frozen=True)
class SessionCorrectionTerminalAttempt:
    attempt_index: int
    attempted_revision: int
    stopped_reason: str
    result_text: str
    result_sha256: str | None
    result_summary: str
    correction_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[dict[str, Any], ...]
    denied_tools: tuple[str, ...]
    failure_code: SessionVerificationFailureCode

@dataclass(frozen=True)
class SessionConvergenceOutcome:
    result: SubtaskResult
    accepted: bool
    status: str
    rounds_used: int
    failure_code: SessionVerificationFailureCode | None
    history: tuple[SessionVerificationRound, ...]
    terminal_attempt: SessionCorrectionTerminalAttempt | None
```

Define the exact public type alias:

```python
SessionVerificationFailureCode = Literal[
    "independent_verifier_unavailable",
    "verification_defect",
    "correction_capability_denied",
    "correction_budget_exhausted",
    "correction_execution_defect",
    "convergence_exhausted",
]
```

Exact session behavior:

1. `verify_for_session` selects one current registry object whose exact bounded id is not in `excluded_agent_ids`, requires `registry.get(candidate_id) is candidate`, and requires public `candidate.is_alive is True`; missing/non-bool/false liveness excludes the candidate. This proves current live identity rather than trusting a detached object.
2. The child call always excludes exactly the child producer id.
3. The parser requires one exact three-key JSON object: `accepted` is exact `bool`, `confidence` is exact non-boolean finite `int|float` in `[0,1]`, and `critique` is a string. Unknown/missing keys, `"false"`, `0`, `1`, NaN, infinity, empty accepted critique, or over-bound content is malformed and can never become acceptance.
4. `verify_for_session` returns one typed pass on every ordinary path and propagates only `asyncio.CancelledError`: exact accepted/refuted JSON maps to `accepted`/`refuted` with no failure code; a clean no-eligible-verifier result maps to `unavailable` / `independent_verifier_unavailable`; registry exceptions, LLM exceptions, malformed JSON/types, invalid response token counts, or unavailable response content map to `error|malformed` / `verification_defect`. Stable bounded critiques describe the class only and never retain raw malformed model content or exception text.
5. The new APIs perform zero `TrustNetwork.record_outcome`, Shapley, episode, event, parent-completion, or metadata writes.
6. The existing public `verify()`, `converge()`, `verdict_to_vote()`, and their tests remain behaviorally and executable-AST identical. In particular, preserve the legacy permissive parser and legacy trust writes for ordinary non-session parents.
7. Session convergence uses the existing injected `WorkItemAgenticExecutor`, preserves the real producer id/instructions/task text, and on every correction passes the same `thread_id` plus exactly:

```python
extra_context={
    "_crew_session_id": parent_id,
    "_crew_work_item_id": result.work_item_id,
}
```

8. A correction result is usable only when `stopped_reason == "complete"`, `denied_tools` is empty, and `final_text.strip()` is non-empty and within bounds. Every usable initial/corrected revision is appended to `history` with its typed verification pass, including unavailable/malformed/error passes. `denied_tools`, `token_budget`, `error`, `max_iterations`, empty/oversize/malformed outcome fields, or execution exceptions are not judged; retain exactly one `terminal_attempt` with all bounded tokens/trace/artifacts/denied-tool ids and the exact failure code. `denied_tools` or `token_budget` is a Captain-resolvable gap; all other terminal correction failures are defects.
9. Session convergence performs at most `min(configured max_convergence_rounds, 8)` correction runs. The legacy configured behavior remains unchanged.
10. Each correction's real tool result must reach the next AgenticLoop request before its final text, as shipped by AD-1125. A real scripted test must inspect that request; merely counting calls is insufficient. Session convergence clones the mutable input `SubtaskResult` and never mutates the caller's result or aliases its Artifact-ref list.
11. Root mapping is exact: accepted pass -> `converged`/accepted/no failure; refuted after the last allowed correction -> `unverified`/not accepted/`convergence_exhausted`; unavailable verifier -> `blocked`/`independent_verifier_unavailable`; denied tools -> `blocked`/`correction_capability_denied`; token budget -> `blocked`/`correction_budget_exhausted`; malformed/error verifier -> `failed`/`verification_defect`; every other unusable correction -> `failed`/`correction_execution_defect`.

### DD-3 - Facilitator produces the synthesis; final verifier excludes content producers

The live session contract names one facilitator and no separate synthesis lead. Therefore:

- `CrewSessionContract.facilitator_id` is the server-owned synthesis producer id;
- before synthesis, the finalizer requires `AgentRegistry.get(facilitator_id)` to return the current object with the same exact id and public `is_alive is True`;
- the live facilitator's `instructions` must normalize to non-empty text of at most 32,768 UTF-8 bytes; missing, non-string, NUL-bearing, or over-bound instructions are `synthesis_producer_unavailable` authority/capability gaps;
- the new output-only synthesizer receives that id for provenance and uses the existing injected LLM client; it does not impersonate a child producer and does not write trust/episodes/events/completion;
- the final verifier exclusion set is the synthesis producer plus **every child content producer**;
- child verifiers may perform final verification only if they are not also a child content producer and are not the facilitator;
- no anonymous synthesis, missing facilitator, self-verification, or contributor self-review may reach done.

Add a frozen output type and one public API in `crew_synth.py`:

```python
@dataclass(frozen=True)
class SessionSynthesisDraft:
    producer_agent_id: str
    final_text: str
    tokens_used: int

async def synthesize_for_session(
    self,
    *,
    parent_id: str,
    producer_agent_id: str,
    producer_instructions: str,
    goal: str,
    success_criteria: tuple[str, ...],
    expected_deliverable: str,
    outcomes: tuple[SessionConvergenceOutcome, ...],
) -> SessionSynthesisDraft:
    ...
```

The system prompt must combine the fixed session-synthesis safety role with the exact bounded facilitator instructions; the user prompt must contain the exact goal, numbered success criteria, expected deliverable, and each accepted child id/producer/output. It must instruct the model to return only the final human-visible result. The API rejects zero outcomes, any non-accepted outcome, missing/invalid producer instructions, empty output, over-bound input/output, malformed token counts, and LLM errors. It has **no concatenation fallback** on the session path. Keep legacy `synthesize()` and all legacy side effects unchanged.

### DD-4 - Expected deliverable policy is explicit and contains no prose-to-file inference

AD-1124 already rejects `None`, empty, NUL, duplicate/excess criteria, and an empty/None expected deliverable. AD-1126 must re-load through `CrewSessionService.get_session()` and trust only that validated strict contract.

For this AD:

1. every successful text finalization requires exactly one new version of `crew-result.md` in the bound room;
2. `crew-result.md` is the result publication contract, not an inferred representation of arbitrary prose;
3. before publication, the final verifier receives `expected_deliverable` verbatim plus a bounded manifest of child-produced artifact refs and an exact deterministic candidate descriptor containing only `thread_id`, literal name `crew-result.md`, MIME `text/markdown`, UTF-8 `size_bytes`, `content_hash`, and `created_by=facilitator_id`;
4. do not fabricate an Artifact id or version before `ArtifactStore.add_version(...)`; after acceptance, validate the real returned Artifact against that candidate descriptor and persist its real id/version only in provenance/publication;
5. AD-1126 does **not** parse words such as "spreadsheet", "PDF", extensions, MIME names, or filenames from prose into a deterministic file rule;
6. if the expected deliverable semantically requires a non-Markdown file, only an actual same-room child Artifact ref can support that claim, and the independent verifier decides whether the candidate satisfies the verbatim contract;
7. missing result-artifact or provenance storage always prevents done, regardless of deliverable prose.

No new expected-file schema is introduced. A future structured deliverable-kind contract is out of scope.

### DD-5 - Exact persisted child verification contract

Add one strict frozen Pydantic model family in the new `crew_finalizer.py`, because this is persisted untrusted JSON and the existing CrewSession contract uses strict Pydantic validation.

Persist each child's complete terminal convergence history in the first-class `WorkItem.verification` column with this exact root shape:

| Key | Exact rule |
|---|---|
| `version` | literal integer `1` |
| `parent_id` | bounded exact parent id |
| `work_item_id` | bounded exact child id |
| `thread_id` | exact bound room id |
| `producer_agent_id` | exact live assigned producer id |
| `status` | exact `converged`, `unverified`, `blocked`, or `failed` |
| `accepted` | exact bool |
| `rounds_used` | exact int `0..8` |
| `result_revision_count` | exact int equal to `len(rounds)` |
| `rounds` | ordered list of exact round records below |
| `failure_code` | exact DD-2 failure code or `None`; required for every non-converged status |
| `terminal_attempt` | exact terminal-correction object below or `None` |

Each round record has exactly:

| Key | Exact rule |
|---|---|
| `round_index` | exact int `0..8`, contiguous from zero |
| `result_revision` | exact int `round_index + 1` |
| `result_sha256` | SHA-256 of the exact UTF-8 result text judged in that round |
| `result_summary` | trimmed, deterministic max 4,096 code-point summary |
| `stopped_reason` | exact `complete` for initial/corrected usable results |
| `correction_tokens` | exact int; zero on round zero; correction AgenticLoop tokens thereafter |
| `verifier_tokens` | exact non-boolean int from the judge response |
| `tool_trace_ref` | canonical SHA-256 or `None` |
| `artifact_refs` | detached ordered 0..32 exact AD-1125 seven-key refs for that revision |
| `verdict` | exact seven-key `{status, accepted, confidence, critique, verifier_agent_id, tokens_used, failure_code}` object matching the round verifier tokens |

`terminal_attempt`, when non-None, has exactly:

| Key | Exact rule |
|---|---|
| `attempt_index` | exact int `1..8` |
| `attempted_revision` | exact int `len(rounds) + 1` |
| `stopped_reason` | exact `complete`, `error`, `max_iterations`, `token_budget`, or `execution_exception` |
| `result_sha256` | SHA-256 of non-empty bounded terminal text, else `None` |
| `result_summary` | bounded deterministic summary; may be empty only when no terminal text exists |
| `correction_tokens` | exact non-boolean int from the terminal AgenticLoop attempt |
| `tool_trace_ref` | canonical SHA-256 or `None` |
| `artifact_refs` | detached ordered 0..32 exact same-room AD-1125 refs |
| `denied_tools` | the RA-5 validator's ordered unique 0..64 exact-string tuple; non-empty whitespace-only ids are valid and preserved, while empty/NUL/invalid-type/invalid-UTF-8/unpaired-surrogate/over-limit input deterministically becomes `correction_execution_defect` |
| `failure_code` | exact correction capability/budget/execution failure code |

Persisted `terminal_attempt` intentionally omits full `result_text`; the full bounded terminal text, when any, appears only in the AttachmentStore provenance document. The in-memory dataclass retains it long enough to build that provenance.

Bounds and retention rules:

- inspect at most 1,001 child rows to detect overflow, at most 1,000 caller result entries, and at most 9 judged result revisions plus one terminal attempt per child;
- each exact result revision is non-empty and at most 65,536 UTF-8 bytes;
- each producer instruction and child task text is a string, NUL-free, and independently at most 32,768 UTF-8 bytes before a correction call;
- each critique is at most 2,048 code points and 8,192 UTF-8 bytes;
- each round keeps at most 32 validated same-room artifact refs and one trace SHA;
- the live ToolRegistry imposes no universal id regex, so do not apply the CrewSession id grammar to tool ids; use RA-5's one total validator, inspect at most 65 entries to prove the 64-entry ceiling, preserve valid whitespace exactly, and never coerce or strip;
- the compact UTF-8 child verification document is at most 262,144 bytes;
- the complete synthesis user prompt input (goal, criteria, deliverable, and all accepted child outputs/ids) is assembled only after bounded per-entry scans and must be at most 1,048,576 UTF-8 bytes; do not build an unbounded intermediate string;
- the final verification expected-output prompt, including bounded child artifact manifest and candidate descriptor, must be at most 262,144 UTF-8 bytes; inspect at most 32 Artifact refs per child and 1,000 children;
- full result revision text is retained only in the final AttachmentStore provenance document; the child column retains exact hashes, bounded summaries, verdicts, tokens, traces, and artifact refs;
- no prompt, instructions, raw tool result, stdout/stderr, exception text, artifact bytes, or trace bytes enters the child column;
- use exact JSON types throughout; Python-equal JSON-different values such as `True` and `1` conflict.

Add one narrow public WorkItemStore API rather than using generic `update_work_item()` or private database state:

```python
async def compare_and_set_work_item_verification(
    self,
    work_item_id: str,
    verification: dict[str, Any],
    *,
    expected_verification: dict[str, Any],
    expected_work_type: str,
    expected_status: str,
    expected_assigned_to: str,
    expected_parent_id: str,
    expected_title: str,
    expected_description: str,
    expected_depends_on: list[str],
    expected_metadata: dict[str, Any],
    expected_actual_tokens: int,
    actual_tokens_delta: int = 0,
    source: str = "crew_session_finalizer",
) -> WorkItem | None:
    ...
```

The method validates exact JSON, size `<=262,144` bytes, every supplied scalar/list/metadata/token precondition, and checked non-boolean token arithmetic under the existing `_work_item_row_write_lock`. It compares exact JSON types for verification, dependencies, and the complete metadata snapshot; it also requires exact title, description, work type, status, assignee, parent, and pre-correction token total. These are every persisted field used to derive task text, expected output/spec id, producer ownership, dependency validity, and AD-1125 execution evidence. It updates verification plus correction-token delta in one SQL commit. The finalizer supplies exactly the sum of `correction_tokens` across judged correction rounds plus the optional terminal attempt; initial-result tokens were already counted by AD-1125, while verifier/synthesis LLM tokens are not child execution tokens and never enter `WorkItem.actual_tokens`. It rolls back and re-raises `BaseException`, refreshes the snapshot, and emits only the existing generic `WORK_ITEM_UPDATED`. It performs no status transition and no new event. Any precondition mismatch raises stable `ValueError("work_item_verification_conflict")`; it never silently overwrites another writer.

The finalizer requires the child's initial `verification == {}`, snapshots all CAS fields immediately before convergence, and writes once after terminal convergence, including blocked/failed/unverified histories. Only after that child CAS succeeds may it transition the parent to the mapped blocked/failed state. A concurrent task-text, metadata/evidence/spec/criterion, dependency, owner, status, parent, work-type, verification, or token change therefore conflicts rather than publishing stale judgment. A child verification CAS conflict/storage failure maps to `verification_persistence_failed`; the finalizer attempts the parent failed transition but never invents a replacement child record. It does not merge histories or retry. Restart/resume of a partially written verifying session belongs to AD-1127.

### DD-6 - Final synthesis verification is strict and independent

Build one synthetic `SubtaskResult` for the final candidate using:

- `work_item_id=parent_id`;
- `spec_id="crew-session-final"`;
- `agent_id=facilitator_id`;
- `output=SessionSynthesisDraft.final_text`;
- `status="done"`;
- no fabricated trace or artifact refs before publication.

Compute the final UTF-8 bytes and DD-4 candidate descriptor before this call, then call `verify_for_session` exactly once with:

- `expected_output` composed deterministically from the exact goal, all numbered criteria, verbatim expected deliverable, bounded child artifact manifest, and exact pre-publication candidate descriptor;
- `excluded_agent_ids=frozenset({facilitator_id, *child_producer_ids})`.

There is no synthesis correction loop in AD-1126: child convergence is bounded; final synthesis receives only accepted children; one refuted final synthesis is a verification defect and transitions the session to `failed`. A missing independent verifier or unavailable facilitator/producer authority transitions to `blocked_needs_captain`. A malformed/errored final verdict transitions to `failed`. This keeps one AD bounded and leaves retry/restart policy to AD-1127.

### DD-7 - Exact failure classification

After the `verifying` claim, classify failures with stable machine reasons and bounded human summaries:

| Condition | Fine state | Stable blocked/failure reason |
|---|---|---|
| no live assigned child producer | `blocked_needs_captain` | `child_producer_unavailable` |
| no live facilitator/synthesis producer | `blocked_needs_captain` | `synthesis_producer_unavailable` |
| no eligible independent child/final verifier | `blocked_needs_captain` | `independent_verifier_unavailable` |
| correction has denied tools | `blocked_needs_captain` | `correction_capability_denied` |
| correction reaches token budget | `blocked_needs_captain` | `correction_budget_exhausted` |
| child missing/extra/not done/empty/mismatched | `failed` | `child_result_invalid` |
| registry/judge exception, malformed judge verdict/content/tokens | `failed` | `verification_defect` |
| correction error/max iterations/exception/malformed outcome | `failed` | `correction_execution_defect` |
| convergence remains refuted after budget | `failed` | `convergence_exhausted` |
| synthesis LLM error/empty/oversize | `failed` | `synthesis_defect` |
| final synthesis refuted | `failed` | `final_verification_refuted` |
| child verification CAS/storage failure | `failed` | `verification_persistence_failed` |
| result/provenance/artifact storage failure | `failed` | `result_publication_failed` |

Use `CrewSessionService.transition_session(...)` with the finalizer-owned current revision for `verifying -> blocked_needs_captain|failed`. Pass a bounded non-empty stable reason string and no fabricated evidence ref; the child verification documents live in their first-class columns and are not AttachmentStore blobs. Never include raw result/verdict content or append a hash that was not actually stored. Never raw-write parent status or metadata. If that terminal transition itself conflicts/fails, propagate the original/canonical error after a contextual log; leave the session non-done. A malformed loaded CrewSession contract cannot be safely transitioned and therefore propagates without generic repair; AD-1124 already rejects empty/None criteria and deliverables before mutation.

Strengthen the existing `CrewSessionService.transition_session(...)` store call so every fine-state transition carries `expected_assigned_to=current.facilitator_id` alongside expected work type/status/session metadata. This closes both pre-call and load-to-commit reassignment races for the `executing -> verifying` claim and all later transitions. A parent reassigned away from the validated facilitator conflicts before mutation; do not repair or silently adopt the new assignee.

Do not catch `asyncio.CancelledError`. Cancellation at convergence, synthesis, AttachmentStore write/read-back, ArtifactStore `to_thread`, provenance storage, or pre-publication propagates and leaves the claimed session in `verifying`; any already-created blob/artifact may be an orphan. AD-1127 owns restart recovery.

### DD-8 - Exact final artifact and provenance publication order

Publication occurs only after all children converged and the final synthesis verdict is exact accepted:

1. Encode `final_text` as UTF-8. Require trimmed non-empty text and at most 262,144 bytes.
2. Compute `result_content_hash = sha256(result_bytes).hexdigest()`.
3. `await AttachmentStore.write(result_content_hash, result_bytes, "text/markdown", origin="agent_artifact")`.
4. Read the blob back with `AttachmentStore.read`, require byte equality and the same SHA-256. A write return alone is not publication proof.
5. Call synchronous `ArtifactStore.add_version(...)` through `asyncio.to_thread` with exact bound `thread_id`, name `crew-result.md`, MIME `text/markdown`, byte size, and `created_by=facilitator_id`.
6. Validate the returned Artifact has the requested thread/name/hash/MIME/size/creator and a positive exact version/id. Do not reconstruct identity.
7. Build the exact provenance document below, compact-serialize with sorted keys, `ensure_ascii=False`, `allow_nan=False`, and require at most 1,048,576 UTF-8 bytes.
8. Compute `provenance_ref` from those exact bytes.
9. `await AttachmentStore.write(provenance_ref, provenance_bytes, "application/json", origin="chat_attachment")`.
10. Read back provenance, require byte equality and matching SHA-256.
11. Call one `CrewSessionService.publish_verified_result(...)` CAS that writes exact `crew_synth`, appends the provenance ref to session evidence, stores the exact Artifact id in `result_artifact_id`, stores the provenance SHA in `result_ref`, and transitions `verifying -> done` atomically.

Use only known AttachmentStore origins. Do not add an origin enum/string, store bytes inline, or publish an Artifact row before its content blob exists.

The provenance document has exactly these top-level keys:

```text
version
origin
parent_id
thread_id
goal
success_criteria
expected_deliverable
children
synthesis
final_verification
result_artifact
```

Exact rules:

- `version` is literal integer `1`;
- `origin` is literal `crew_session_finalizer`;
- ids and hashes use the established bounded grammars;
- criteria are the exact validated ordered list;
- `children` is in stable child-id order. Each entry has exactly four keys: `work_item_id`, `verification`, `result_revisions`, and `terminal_result_text`;
- each child `verification` is a detached byte-for-byte JSON-value copy of the exact document committed to that WorkItem column;
- each `result_revisions` entry has exactly `round_index`, `result_revision`, `result_text`, and `result_sha256`; list length/order equals `verification.rounds`, and every text hash equals both its entry and matching persisted round hash;
- `terminal_result_text` is `None` iff `verification.terminal_attempt` is `None` or that attempt has no text; otherwise it is the exact bounded terminal text and its SHA matches `verification.terminal_attempt.result_sha256`;
- `synthesis` has exactly four keys: `producer_agent_id`, `final_text`, `result_sha256`, and `tokens_used`;
- `final_verification` is exactly the seven-key strict serialized `SessionVerificationPass`; its `status` is `accepted`, `accepted is True`, and `failure_code is None`;
- `result_artifact` contains the exact returned seven-key AD-1125 Artifact ref;
- no instructions, prompts, raw tool result, raw trace, exception text, secret, or binary value is included.

### DD-9 - One atomic parent publication CAS; both refs are mandatory

Strengthen `CrewSessionContract` consistency so `state == "done"` requires **both** non-None `result_artifact_id` and `result_ref`; one without the other is invalid. Existing AD-1124 done tests already supply both. Non-done states continue to require both absent.

Add one strict frozen `CrewSynthesisMetadata` model in `crew_session.py` and one public service method:

```python
async def publish_verified_result(
    self,
    parent_id: str,
    *,
    expected_revision: int,
    expected_direct_children: tuple[dict[str, Any], ...],
    crew_synth: CrewSynthesisMetadata,
    last_result_summary: str,
    provenance_ref: str,
    result_artifact_id: str,
) -> CrewSessionContract:
    ...
```

`CrewSynthesisMetadata` has exactly these keys and compact UTF-8 size `<=32,768` bytes:

```text
version
completed
producer_agent_id
final_verifier_agent_id
final_confidence
final_critique
accepted_count
total_count
convergence_rounds
correction_tokens
verification_tokens
synthesis_tokens
result_artifact_id
result_content_hash
provenance_ref
```

Rules:

- `version == 1`, `completed is True`, counts/tokens are exact bounded non-boolean ints;
- accepted/total counts are equal and nonzero;
- `convergence_rounds` is the exact sum of child `rounds_used`; `correction_tokens` is the exact sum committed to child actual-token deltas; `verification_tokens` is the exact sum of every child and final verifier pass; `synthesis_tokens` is the exact output-only synthesis response count;
- ids/hashes are exact; critique is bounded; confidence is finite in `[0,1]`;
- supplied Artifact/provenance ids match the metadata fields exactly;
- current session must be exact `verifying`, expected revision must match, parent type/status/task/thread/facilitator assignment must still match, and existing top-level `crew_synth` must be absent;
- build the done contract with server time and append `provenance_ref` once to evidence refs;
- extend `WorkItemStore.merge_work_item_metadata(...)` additively with `expected_absent_keys: frozenset[str] = frozenset()`; validate an exact frozenset of string keys before lock admission, reject overlap with `expected`, and under the existing row lock require every named key to be absent from the current metadata mapping regardless of its value;
- preserve byte-identical behavior for the default empty frozenset; a present `crew_synth` key containing `None`, `{}`, or any other JSON value conflicts rather than aliasing absence;
- call `publish_work_item_metadata_with_child_barrier` once with a two-key patch `{crew_session, crew_synth}`, exact expected old `crew_session`, `expected_absent_keys=frozenset({"crew_synth"})`, `expected_present_keys` for all observed unrelated siblings, the complete RA-1 child snapshots, expected work type/status/assignee, and `new_status="done"`;
- preserve all unrelated metadata siblings (`origin`, `input_attachments`, and any other key);
- a pre-commit CAS/barrier miss never reports completion and is never retried; after a possible commit, RA-4 reconciliation may return exact authoritative done without requiring unrelated siblings.

`transition_session(..., "done", ...)` may remain for AD-1124 compatibility, but it must enforce the strengthened both-ref invariant. AD-1126 production calls only `publish_verified_result` for success.

### DD-10 - Claim, concurrency, retry, and orphan semantics

`CrewSessionFinalizer.finalize(parent_id, results)` has one runtime-local foreground invocation contract:

1. load only the validated session and require state `executing`; do not scan or validate caller-supplied child results before ownership;
2. claim ownership with `transition_session(parent_id, "verifying", expected_revision=...)` **before** child listing/validation, verifier/LLM, or storage calls;
3. exactly one same-revision concurrent caller can claim because AD-1124 uses exact metadata CAS under the shared row lock;
4. an independent CAS loser reloads once, returns a typed `claimed=False` result with the authoritative non-`executing` state, and performs zero child/result scan, synthesis, or storage work; a same-process caller that first observed `executing` follows RA-3's owner-wait plus one bounded claim retry;
5. after a successful claim, list with `limit=1001`, reject overflow/zero, bound caller-result inspection independently to 1,000 entries, and perform DD-1's exact required-child/result validation; any defect transitions the owned session `verifying -> failed` with reason `child_result_invalid`;
6. an invocation that begins in `verifying` always raises stable `crew_session_finalization_in_progress`, including when the owner is local; an executing waiter whose owner exits after the claim commit observes `verifying` and performs no work;
7. an invocation that begins terminal/blocked returns a typed no-op observation and performs no writes;
8. apart from RA-3's one pre-claim-cancellation retry for a caller that originally observed `executing`, there is no automatic whole-finalization retry, restart scan, lease, watchdog, rollback, or recovery in AD-1126.

AttachmentStore hash writes are naturally idempotent. ArtifactStore version creation and parent publication are attempted once per owning invocation. If cancellation, provenance failure, or final CAS conflict occurs after result blob/artifact creation, retain the orphan and log its exact safe ids/hashes; do **not** delete it because another process/thread may have observed or referenced it. Existing reaper/manual audit owns later cleanup. Orphans are never placed in the session contract unless the final CAS succeeds.

Add a frozen `CrewSessionFinalizationResult` with bounded scalar fields only:

```python
@dataclass(frozen=True)
class CrewSessionFinalizationResult:
    parent_id: str
    claimed: bool
    state: str
    completed: bool
    final_output: str
    accepted_count: int
    total_count: int
    result_artifact_id: str | None
    provenance_ref: str | None
    reason: str
```

No task is spawned by the finalizer, so it owns no background task registry. AD-1127 owns scheduling, held runner tasks, shutdown admission, and restart recovery.

### DD-11 - Orchestrator and startup integration

Add one optional keyword-only constructor-injected `CrewSessionFinalizer | None = None` dependency to `CrewOrchestrator` while preserving all existing named arguments and legacy behavior. For a durable session, after AD-1125 fan-out:

```python
if is_crew_session:
    if self._crew_session_finalizer is not None:
        return await self._crew_session_finalizer.finalize(parent_id, results)
    return SynthesisResult(
        parent_id=parent_id,
        final_output="",
        completed=False,
        accepted_count=0,
        total_count=len(results),
    )
```

The `None` branch is exact compatibility for shipped AD-1125 direct construction and for exceptional startup degradation: it performs no verification, publication, or completion and leaves a durable session in `executing`. Production `_wire_crew_orchestrator` injects a real finalizer when all durable dependencies are present. If only a durable-finalizer dependency is missing but all pre-existing AD-867 dependencies exist, startup logs one contextual WARNING and wires the unchanged legacy orchestrator with `finalizer=None`; ordinary task parents remain available and durable parents fail closed at the visible AD-1125 stop. There is no silent bypass or false done.

Do not change `SynthesisResult`. Map the finalizer result exactly into its existing fields:

- completed finalization -> `final_output` is the verified text, `completed=True`, `provenance_ref` is the verified provenance SHA, counts come from the finalizer, and `shapley_values={}`;
- blocked/failed/no-op finalization -> `final_output=""`, `completed=False`, `provenance_ref=None`, counts come from the finalizer, and `shapley_values={}`;
- the authoritative final Artifact id remains in `CrewSessionContract.result_artifact_id` and `CrewSessionFinalizationResult.result_artifact_id`; do not add it to the legacy synthesis result or expose unverified synthesis text.

Modify only `_wire_crew_orchestrator` in `startup/finalize.py`:

- reuse the one existing `WorkItemAgenticExecutor`, `SubtaskVerifier`, and `CrewSynthesizer` instances;
- read public `runtime.crew_session_service`, `runtime.artifact_store`, and the existing AttachmentStore resolver result;
- construct one `CrewSessionFinalizer` with explicit injected dependencies: WorkItemStore, CrewSessionService, ChatThreadStore, ArtifactStore, AttachmentStore, AgentRegistry, verifier, synthesizer;
- pass it into CrewOrchestrator;
- do not construct a second store/service/orchestrator or reach through private runtime attributes;
- gate false remains read-free/inert; enabled but missing session/artifact/attachment/thread dependency logs a contextual warning and wires the pre-existing legacy orchestrator with `finalizer=None` only when every original AD-867 dependency is available;
- legacy orchestrator composition remains available only when all its pre-existing dependencies are present; do not weaken existing dependency checks.

### DD-12 - Event, trust, and learning boundary

AD-1126 adds no EventType and emits no finalization-specific event, notification, metric, episode, Shapley value, trust update, or Hebbian update.

The only allowed event observations are the existing generic `WORK_ITEM_UPDATED` / `WORK_ITEM_STATUS_CHANGED` events emitted by the authoritative WorkItemStore writes. Do not call `emit_fn` from the finalizer and do not call legacy `CrewSynthesizer.synthesize()` or legacy `SubtaskVerifier.verify()/converge()` on the session path. Tests must prove:

- trust records are unchanged;
- episodic storage receives zero calls;
- no `CREW_TASK_COMPLETED`, `VERIFICATION_*`, or new event occurs;
- only the already-shipped generic WorkItem events caused by state/column persistence may occur.

AD-1130 owns trust/Hebbian/Shapley work. AD-1131 owns notifications, metrics, completion events, and episodes.

---

## Implementation sections

### Section 1 - Focused real-substrate adjudication repairs

The current repair tree already contains `tests/test_ad1126_verified_finalization.py` and uncommitted AD-1126 production. Preserve every existing passing contract and add/repair only the adjudicated cases. Use:

- real started `WorkItemStore` on `tmp_path`;
- real `CrewSessionService`;
- real synchronous `ChatThreadStore`;
- real synchronous `ArtifactStore`;
- real `FilesystemAttachmentStore`;
- real `WorkItemAgenticExecutor` / AgenticLoop for the correction/tool-result headline path;
- hand-written scripted protocol-faithful LLM and live agent/registry objects;
- narrow failure-injection wrappers that delegate to the real stores and preserve exact signatures;
- no `MagicMock`, `AsyncMock`, `Mock`, patching mock, or fake substrate store.

Test families and required named coverage:

1. accepted first pass, all child histories persisted, final independent acceptance, exact result/provenance bytes, and done CAS;
2. first-pass refutation -> real AgenticLoop correction -> real tool result in next LLM prompt -> corrected output -> re-verification -> done;
3. convergence exhausted -> child `unverified` history -> parent failed, never done;
4. missing/extra/duplicate child result, failed/blocked child, empty output, zero children, missing producer, missing facilitator, no child verifier, and no final verifier;
5. strict malformed verdicts including `{"accepted":"false"}`, `0`, `1`, missing/extra keys, NaN/infinity, empty/oversize critique, and malformed token count;
6. AD-1124 initialization rejects empty/None success criteria and empty/None expected deliverable using the real service; malformed persisted contract cannot be repaired or completed;
7. final verifier prompt contains exact criteria, expected deliverable, child Artifact manifest, pre-publication candidate descriptor without fabricated id/version, and excludes facilitator plus all child producers;
8. mandatory `crew-result.md` in exact room, version increments, exact bytes/hash/MIME/creator, and no prose-derived filename/extension behavior;
9. result-blob write/read-back failure, ArtifactStore failure, provenance oversize/write/read-back failure, child verification CAS failure, failure-state CAS failure, and final publication CAS loss;
10. concurrent finalizers: one claim, one no-op loser that does not scan children/results, one Artifact version, one provenance publication, one done CAS;
11. cancellation at child convergence, synthesis, result storage, ArtifactStore `to_thread`, provenance storage, and immediately before publication; cancellation propagates and no done contract appears;
12. round/child/result/critique/artifact/provenance/metadata/token strict bounds, detached aliases, JSON bool-vs-int exactness, and correction-token atomicity/overflow;
13. barrier races during child convergence independently mutate title, description, metadata/crew_execution/expected_output, dependencies, owner, parent, status, work type, verification, and actual tokens; every mutation conflicts before child verification publication and parent done;
14. orphan behavior after artifact creation plus publication failure: orphan retained, exact ids logged safely, session non-done, no cleanup race;
15. loaded `done` requires both Artifact id and provenance ref; each missing-ref combination rejects;
16. legacy parity: frozen AD-860 trust-writing verification, AD-861 empty/partial completion behavior, and AD-867 ordinary task pipeline remain unchanged;
17. no trust, Shapley, episode, finalization-specific event, notification, or metric side effect.

The adjudication adds these exact mandatory test names; do not alias them behind parametrization-only ids:

```text
test_final_publication_rejects_changed_direct_child_set_after_verification
test_final_publication_rejects_post_cas_child_row_drift
test_final_publication_child_barrier_is_atomic_with_parent_done
test_session_correction_projects_static_mesh_mcp_and_runtime_tools
test_session_correction_projected_tool_result_reaches_next_request_without_events
test_session_correction_projection_preserves_permission_and_exclusive_denial
test_finalize_starting_in_verifying_raises_during_local_owner
test_waiter_retries_claim_once_after_precommit_owner_cancellation
test_waiter_observes_verifying_after_postcommit_owner_cancellation_without_work
test_publish_verified_result_postcommit_sibling_deletion_returns_done
test_denied_tool_whitespace_is_preserved_as_exact_capability_denial
test_denied_tool_unpaired_surrogate_maps_to_correction_execution_defect
```

The barrier tests must use the real WorkItemStore connection and public CrewSessionService API. `test_final_publication_rejects_changed_direct_child_set_after_verification` must prove both a newly added direct child and a deleted required direct child conflict before done. The atomicity case must pause through a protocol-faithful connection wrapper inside the store-owned publication transaction after child proof and before parent update, race a same-store public child writer, and prove the writer cannot interleave before commit; do not reach through private locks or raw database handles from the test. The projection tests must use public registrations/policies, prove the shared registry is identity/content unchanged, distinguish executable from explicit-denial definitions, inspect the next real AgenticLoop request, and prove permission plus foreign exclusive-lock denial.

The live legacy tests whose assumptions are **obsolete only for durable `crew_session` finalization** are:

- `tests/test_ad867_crew_orchestrator.py::test_verifier_refuted_child_marked_unverified` - one-shot verification remains valid for legacy task parents only;
- `tests/test_ad867_crew_orchestrator.py::test_failed_subtask_skipped_in_verification` - partial skip remains valid for legacy task parents only;
- `tests/test_ad867_crew_orchestrator.py::test_executor_failure_degrades_to_empty` - empty synthesis remains valid for legacy task parents only;
- `tests/test_ad867_crew_orchestrator.py::test_missing_parent_degrades_to_empty_synthesis` - legacy missing-parent degradation remains valid;
- `tests/test_ad861_crew_synth.py::test_no_accepted_outcomes_degrades_to_empty_synthesis` - legacy synthesizer behavior remains valid, but the new session output-only API must reject zero accepted outcomes.

Do not delete or rewrite those legacy tests. The new AD-1126 module supplies the durable-session contract; AD-860, AD-861, AD-867, and AD-1125 files remain frozen parity oracles, while AD-1124 permits only the two exact assertion updates named below.

### Section 2 - Store-owned child verification CAS

Modify `src/probos/workforce.py` around the live `merge_work_item_metadata(...)` and shared row lock. Add the DD-5 public method with the same connection abstraction and rollback/event conventions.

Keep DD-9's optional `expected_absent_keys` and repaired `expected_present_keys` behavior on `merge_work_item_metadata`. Add RA-1's separate public `publish_work_item_metadata_with_child_barrier(...)`; do not fold the final barrier into generic merge behavior.

Verified SEARCH anchor:

```python
    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
```

Keep the child verification CAS as a sibling API after metadata merge. Place the new publication-barrier API beside the store-owned CAS methods. Do not alter schema, `_JSON_FIELDS`, generic `update_work_item`, unrelated status transitions, or generic metadata CAS semantics.

### Section 3 - Side-effect-free verifier and synthesis APIs

Modify only additive surfaces in:

- `src/probos/cognitive/crew_verifier.py`;
- `src/probos/cognitive/crew_synth.py`.

Verified SEARCH anchors:

```python
    async def verify(self, result: "SubtaskResult") -> VerificationVerdict:
```

```python
    async def converge(
        self,
        result: "SubtaskResult",
```

```python
    async def synthesize(
        self, parent_id: str, outcomes: list["ConvergenceOutcome"],
```

Add the session dataclasses/APIs without changing the executable bodies of those three legacy methods. Reuse pure prompt/registry helpers only where their current semantics are suitable; use a new strict session parser and exclusion-aware live selector. Do not call trust, Shapley, episodic, completion, or emit paths.

Repair `_session_correction_runtime` and its narrow local adapters exactly to RA-2. The frozen ordinary executor must see the same projected categories without receiving the raw runtime or mutating the shared registry. Use RA-5's one total denied-tool validator in both terminal classification and persistence.

### Section 4 - Session publication contract

Modify `src/probos/cognitive/crew_session.py`:

1. strengthen done consistency to require both refs;
2. add strict `CrewSynthesisMetadata`;
3. extend `publish_verified_result(...)` with `expected_direct_children` and delegate success to one exact RA-1 two-key metadata/status/child-barrier CAS;
4. preserve `initialize_session`, `get_session`, and every existing transition edge;
5. keep all database work delegated to the injected store protocol.

Verified SEARCH anchors:

```python
class CrewSessionContract(BaseModel):
```

```python
class CrewSessionService:
```

```python
    async def transition_session(
```

Extend `_WorkItemStoreProtocol` with the exact public RA-1 publication method and retain the repaired generic merge signature. Do not add a raw connection or import SQLite into the service.

Update only these assertions in `tests/test_ad1124_crew_session_contract.py`:

- `test_public_service_api_and_annotations_are_exact` so its public-method set includes `publish_verified_result` and its expected parameter set matches the binding signature;
- `test_transition_session_generic_status_interleaving_conflicts_without_mutation` so its recorded `expected_assigned_to` value is exact `facilitator-1`, matching the strengthened transition CAS.

Add no test function and alter no other lifecycle, CAS, validation, or source-safety assertion in that file; all new behavior, including pre-call and load-to-commit facilitator reassignment rejection, belongs in the AD-1126 module.

Extend `tests/test_ad1126_verified_finalization.py::test_public_session_apis_and_finalizer_signature_are_fully_typed` to assert the exact public `WorkItemStore.publish_work_item_metadata_with_child_barrier(...)` and `CrewSessionService.publish_verified_result(...)` parameter names, keyword-only boundary, defaults, annotations, and return types from RA-1. Do not satisfy the contract only through a Protocol annotation.

### Section 5 - Focused CrewSessionFinalizer

Create `src/probos/cognitive/crew_finalizer.py` with:

- strict models/constants/builders for DD-5/DD-8/DD-9;
- one constructor-injected `CrewSessionFinalizer`;
- one public fully typed `finalize(...)` method;
- small private methods for claim validation, child convergence/persistence, failure transition, synthesis/final verification, publication, and exact serialization;
- no runtime lookup, global store creation, background task, event emitter, trust, episode, or config reader.

The finalizer may depend only on narrow public methods of injected collaborators. It must call synchronous ChatThreadStore and ArtifactStore methods with `asyncio.to_thread`. It must never access collaborator private attributes.

Retain each successful child CAS's exact returned post-verification row, build RA-1's detached sorted snapshots, and pass the complete tuple to `publish_verified_result`. Implement RA-3 with an owner-completion event and identity-safe cleanup; do not treat local ownership as permission to resume a session loaded in `verifying`.

### Section 6 - Orchestrator and startup wiring

Modify only the durable-session branch in `src/probos/cognitive/crew_orchestrator.py` and `_wire_crew_orchestrator` in `src/probos/startup/finalize.py`.

Verified SEARCH anchor in the orchestrator:

```python
        if is_crew_session:
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
```

Replace only that AD-1125 stop with the injected finalizer call and truthful result mapping. The preceding assignment/execution path and the following legacy `_verify` / `_synthesize` path remain unchanged.

Startup must reuse:

- public `runtime.work_item_store`;
- public `runtime.chat_thread_store`;
- public `runtime.artifact_store` created in `runtime.py`;
- public `runtime.crew_session_service` wired immediately before the orchestrator;
- the existing AttachmentStore resolution;
- the same verifier/synthesizer/agentic executor instances already constructed in `_wire_crew_orchestrator`.

No second database, service, store, executor, verifier, synthesizer, or orchestrator.

### Section 7 - Closeout only after all gates and reviews

After all tests and all three Builder reviews pass:

1. prepend one AD-1126 shipped block to `PROGRESS.md` with exact `N`, gate counts, publication/failure/concurrency semantics, warning provenance, and ceilings AD-1126/BF-673;
2. prepend `### AD-1126 (2026-07-20) - verified CrewSession finalization (#1045)` under Era V in `DECISIONS.md` with Context / Decision / Tests;
3. add one AD-1126 shipped row immediately after AD-1125 in the Crew Autonomy table of `docs/development/roadmap.md`, referencing #1041/#1045;
4. move both active prompt files byte-for-byte to `prompts/archive/`, proving pre/post SHA-256 equality;
5. stage explicit allowlisted paths only;
6. commit exactly `AD-1126: add verified CrewSession finalization (closes #1045)`;
7. do not push and do not mutate GitHub.

---

## Exact file allowlist

### Production

- `src/probos/workforce.py`
- `src/probos/cognitive/crew_session.py`
- `src/probos/cognitive/crew_verifier.py`
- `src/probos/cognitive/crew_synth.py`
- `src/probos/cognitive/crew_finalizer.py` - new
- `src/probos/cognitive/crew_orchestrator.py`
- `src/probos/startup/finalize.py`

### Tests

- `tests/test_ad1126_verified_finalization.py` - new
- `tests/test_ad1124_crew_session_contract.py` - update only `test_public_service_api_and_annotations_are_exact` for additive `publish_verified_result` and `test_transition_session_generic_status_interleaving_conflicts_without_mutation` for exact facilitator assignment CAS; add no test function and change no other assertion

### Architect documents - active until closeout, then hash-preserving move

- `prompts/ad-1126-verified-crew-session-finalization.md`
- `prompts/ad-1126-verified-crew-session-finalization-execution.md`

### Conditional closeout only

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`

No other path is authorized.

---

## Exact base hashes

These are the exact `cedd01e7` reconstruction/parity hashes. The authorized repair inputs are intentionally modified and must instead match the repair-input hashes pinned in the execution companion; do not reset them to this table:

| Path | SHA-256 |
|---|---|
| `src/probos/workforce.py` | `0a7a52498e044a3cdde0a45799576b04320087afdd5f44dea0aa49bd14670697` |
| `src/probos/cognitive/crew_session.py` | `441792154ac777db8753478572f429661d56381f65bbfa76d6b1abfcee0087e9` |
| `src/probos/cognitive/crew_verifier.py` | `4c2241dc683d44690becae3092bbb1de3b30f3ebc22853c7ea926af9b77b2d1e` |
| `src/probos/cognitive/crew_synth.py` | `94c043631690f2fc9b65ab03139e85659a9cdfb8311ae62ece89691c8bacbb65` |
| `src/probos/cognitive/crew_orchestrator.py` | `198ea510935e1a0152d59db3849e5fbf5807080bf54ec7c3b782c4d38e1d99ce` |
| `src/probos/startup/finalize.py` | `2292a337607fc661a38243f87a71c7de0d1f88630619fffc6b58a016e6b5f6f7` |
| `tests/test_ad1124_crew_session_contract.py` | `eb082e14e6198a0b86a3c22c09b347a867eff0bc8f205b8c7aae911a0cf0a2f2` |

These reference/test surfaces are frozen and must retain the exact hashes:

| Path | SHA-256 |
|---|---|
| `src/probos/cognitive/crew_executor.py` | `034483327333429188f6aeeff78e63255e272be9a34ea8b7bcfbd45007cf292a` |
| `src/probos/cognitive/agentic_dispatch.py` | `a2c12332581e63109ee6703d76edc44071dc46571f804b6f3bfa6835ec64cc45` |
| `src/probos/runtime.py` | `93680b0d116044bcbeab5bc673dfd54597de408c460b762cd26bb2ceb19a441f` |
| `src/probos/artifacts/__init__.py` | `d86d82a58da5b1b5fa733812e23c615b3380c23a8d4ebdd4f9621629d4985c02` |
| `src/probos/attachments/store.py` | `fffcef4c47e3e565daa64e6a49593e2578a68a04d8ed93d5aaebf4c172bfd0fb` |
| `src/probos/attachments/filesystem_store.py` | `04828922889b7ec4434b085979a62de03b4470a0d819b9758c1d0bc4cf6588a6` |
| `src/probos/threads/__init__.py` | `88fe637aca2475b74a53fb934a30feff01ba84acd6516a2c8f277ddc367f29ff` |
| `src/probos/substrate/registry.py` | `2a86f6580942f9f8a174cd5cccd00179195a7011b12e6f6eedcaeb064fadd6d4` |
| `src/probos/substrate/agent.py` | `2d781dd585aeb35d1f30c31b04f6a70a0a292daee5a27f4b298d726ce81a3647` |
| `src/probos/config.py` | `aa7a67269da3f34cb43bb2210921211ad22e57dfbfd1f6e8117327ad02247c10` |
| `src/probos/events.py` | `02dd8a8e58da5a19abce4662c675cca254ffb799170715832aea4cde3bec046d` |
| `config/system.yaml` | `2da205cae542b9635062be8874ebb38a4019592ddc8e3ff017a9163913e65f85` |
| `tests/test_ad860_crew_verifier.py` | `c5ec4a22645d8f5db78f6c8c372c02a750de72037536e3cf7458abdb153da397` |
| `tests/test_ad861_crew_synth.py` | `d709520aec16c388629ab23db79c00acbdee02ee80f5343787d25830423c3bf0` |
| `tests/test_ad867_crew_orchestrator.py` | `7de99f6069c66e32ac25c4fece79d3de0d8923a93b62245df28023acc06344aa` |
| `tests/test_ad1125_room_bound_execution.py` | `9d49aa282e71f1be4e3b14a513318a3e21e1d06ba822ab67d2e0926509a11a19` |

`src/probos/cognitive/crew_finalizer.py` and `tests/test_ad1126_verified_finalization.py` exist in the authorized uncommitted repair tree. Record their pre-repair SHA-256 values and the hashes of every authorized modified file before further edits. The base table remains the exact `cedd01e7` reconstruction/parity reference; do not require dirty mutable files to equal their base hashes and do not reset or reconstruct them.

In addition to whole-file hashes, Builder must record and compare executable AST hashes for these legacy methods before/after:

- `SubtaskVerifier.verify`;
- `SubtaskVerifier.converge`;
- `CrewSynthesizer.synthesize`;
- `CrewOrchestrator._verify`;
- `CrewOrchestrator._synthesize`;
- `CrewTaskExecutor.run` and `_run_child`.

Only the durable branch inside `CrewOrchestrator.run_crew_task` may change.

---

## Test gates

The execution companion contains exact PowerShell commands. All executable gates use unique temporary `PROBOS_DATA_DIR`, local/offline embeddings, no pytest cache, `--timeout=90`, short tracebacks, and no `-n auto`.

Let `N` be discovered only after the adjudicated repair as the exact final passed-case count in `tests/test_ad1126_verified_finalization.py`. The current pre-repair count is not authoritative.

Use the optimized full-suite-last order:

| Gate | Scope | Required result |
|---|---|---|
| Focused repair checks | exact adjudication nodes and their owning test families, serial | all pass; zero changed-path warnings |
| Architect review | three prompt/implementation review passes after focused repair checks | APPROVED before broad gates |
| Gate 2 | workforce/artifact/attachment/thread/startup blast, serial | all pass; no new warning family |
| Gate 3 | py_compile + editor `get_errors` + scope/hash/AST/prompt audit | clean |
| Gate 4 | one authoritative full `tests/`, xdist 4 loadfile | exactly **`19,731 + N` passed / 33 skipped / 0 failed** |

Do not run a mandatory RED, Gate 0 full module, Gate 1 broad direct suite, or any full suite before focused repairs and Architect approval. Focused repair checks may be repeated while repairing. After approval, run exact Gate 2 and Gate 3, then exactly one authoritative Gate 4. A failed Gate 4 may receive only the prescribed serial failing-file triage; do not launch a second full Gate 4 without Architect adjudication.

Gate 4 warning provenance:

- baseline is exactly 431 warnings on the clean base;
- the scalar may vary only if a dependency warning family varies independently;
- every warning must be classified;
- zero warning may originate from an AD-1126 changed/new path;
- any new first-party warning or unexplained family is a hard stop;
- any xdist failure must be rerun in its file at `-n 0` before classification.

---

## Acceptance criteria

1. One valid durable session is claimed by exact `executing -> verifying` CAS before verification, and exactly one same-revision concurrent finalizer performs work.
2. The claim and every later fine-state transition require the parent to remain assigned to the validated facilitator; pre-call or load-to-commit reassignment conflicts without child scan or mutation.
3. Every direct child is required; a 1,001-entry bounded probe detects overflow, and zero, overflow, missing, extra, duplicate, failed, blocked, mismatched, or empty child work transitions the claimed session to failed and cannot reach synthesis or done.
4. Each child converges with its live producer's actual instructions, actual child task text, exact room id, and exact two-key session context.
5. A first refutation performs a real bounded AgenticLoop correction; its real tool result reaches the next LLM request; accepted correction history, tokens, traces, artifacts, critiques, verifier ids, verdicts, hashes, and revisions persist exactly.
6. Child and final verifier identities are current registry identities. A producer never verifies itself; the final verifier is neither facilitator nor any child content producer.
7. Session verdict parsing is exact JSON typed. In particular, string `"false"`, integer `0`, and integer `1` never become booleans.
8. Legacy verifier/synth/orchestrator methods retain byte-identical behavior, including trust/episode/event side effects only on the legacy non-session path.
9. The strict child verification schema and all result/critique/round/artifact/token/document bounds reject before mutation; correction tokens commit atomically with that child CAS.
10. All children must converge. Exhausted refutation reaches failed/unverified, never done.
11. The facilitator is the synthesis producer. Its live non-empty bounded instructions are used in output-only synthesis, which is non-empty, bounded, includes every accepted child, and performs no trust/Shapley/episode/event/completion write.
12. Final independent verification covers exact goal, every criterion, verbatim expected deliverable, final synthesis, bounded actual child artifact evidence, and an exact candidate result descriptor without a fabricated Artifact id/version.
13. Empty/None criteria and deliverable remain rejected by the real AD-1124 service; no finalizer repairs or completes malformed contracts.
14. Every success creates one exact versioned `crew-result.md` Artifact in the bound room, backed by byte-verified AttachmentStore content matching the verified synthesis.
15. Full bounded provenance uses the exact schema, compact canonical bytes, known `chat_attachment` origin, and content hash computed before write and verified after read-back.
16. At commit admission, the final service CAS preserves every then-present unrelated metadata sibling and atomically stores exact `crew_synth`, Artifact id, provenance ref, evidence ref, done timestamps, fine state, and generic status; RA-4 deliberately does not require those unrelated siblings to survive a later post-commit writer.
17. Final publication requires top-level `crew_synth` to be truly absent under the store row lock; an explicit JSON null or any other present value conflicts and cannot be overwritten.
18. A done CrewSession always has both `result_artifact_id` and provenance `result_ref`; either missing, storage failure, malformed Artifact, or lost final CAS leaves it non-done.
19. Authority/capability gaps map exactly to `blocked_needs_captain`; execution/verification/storage/refutation defects map exactly to `failed`; terminal transition failure never falls back to a generic writer.
20. Cancellation at every awaited finalization stage propagates and never publishes done. Post-write orphans are retained and never deleted by a racing rollback.
21. No AD-1131 event/notification/metric/episode is built. Only existing generic WorkItem update/status events may occur; trust/Hebbian/Shapley remain unchanged.
22. Direct construction or exceptional startup degradation with no finalizer preserves the exact AD-1125 non-completing `executing` stop and ordinary legacy tasks; normal enabled production injects one real finalizer. Durable return mapping never exposes refuted/unverified synthesis text and does not change `SynthesisResult`.
23. Default-off startup remains inert and reads no dependencies. Enabled startup reuses existing public stores/services and constructs one finalizer, not a second database or orchestrator.
24. The AD-1126 test module uses real WorkItemStore, CrewSessionService, ChatThreadStore, ArtifactStore, FilesystemAttachmentStore, and real AgenticLoop where required, with protocol-faithful scripted agents/LLMs and no MagicMock substrate.
25. Focused, blast, compile/editor, frozen/hash/AST, and full gates satisfy the exact execution formulas; changed-path warnings are zero.
26. Scope contains only AD-1126, the two exact obsolete AD-1124 assertions, and conditional closeout; no other production/test/tracker/GitHub change occurs outside the allowlist.
27. Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.
28. Parent `done` publication re-queries at most 1,001 direct children under the same WorkItem row lock/transaction, requires the exact expected id set and all 23 durable semantic fields from every post-verification snapshot, and commits no parent mutation on any drift.
29. Correction projection preserves the ordinary static/mesh/MCP/runtime-contributed visibility contract through executable governed local adapters or explicit denied definitions, never mutates the shared registry, never forwards the raw runtime, preserves permission/LOTO safety, and threads a real projected tool result into the next request without finalization-specific events.
30. A call loaded in `verifying` always raises in-progress; an executing local waiter receives one reload after the local claim attempt settles and at most one claim retry only when pre-claim cancellation left the session executing; post-claim cancellation leaves verifying and the waiter performs no work.
31. Publication admission requires observed sibling keys to remain present, while post-commit reconciliation proves only exact parent/session/synthesis/result authority and returns done after unrelated sibling deletion without restoration.
32. The one total denied-tool validator preserves valid whitespace exactly and maps invalid types, NUL, invalid UTF-8, unpaired surrogates, duplicates, and limits to `correction_execution_defect` without raising.
33. Every acceptance section retains this standing requirement: Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## What this does not change

- **Do not build AD-1127:** no scheduler/runner, held background finalization task, restart scan/resume, lease, watchdog, shutdown admission/drain, or retry policy.
- **Do not build AD-1128:** no Captain/agent ingress, semantic dedup, provisioning transaction, duplicate-resume update, room repair, or trigger path.
- **Do not build AD-1129:** no EventLog tool, endpoint, query, or arbitrary event access.
- **Do not build AD-1130:** no trust, Hebbian, Shapley, outcome credit, or learning update.
- **Do not build AD-1131:** no notification, metric, completion event, verification event, episode, or new EventType.
- **Do not build AD-1132:** no HXI/API/status/result projection or passive-rail removal.
- **Do not build AD-1133:** no WebSocket push or live-refresh transport.
- No schema, DDL, table, column, index, migration, new database, or second store/orchestrator.
- No `config/system.yaml` or config-model edit; reuse the existing default-off `agentic_dispatch` gate and current convergence value.
- No generic CrewSession bypass, raw status/metadata write, direct private-attribute reach-through, or raw database connection.
- No inline blob in WorkItem metadata, verification, IntentMessage, event, or return envelope.
- No `AgenticLoop`, tool-call protocol, CrewTaskExecutor, agentic-dispatch, ArtifactStore, AttachmentStore, ChatThreadStore, registry, runtime-construction, API, router, UI, desktop, manifest, dependency, or commercial-repo change.
- No prose-to-extension/MIME/filename inference and no optional-child invention.
- No new AD or BF beyond AD-1126.
- No global shared SQLite transaction ownership across booking, journal, or other WorkItem writers; file a follow-up issue later if cross-connection ownership is required.
- No cross-store Artifact/Attachment pin, reservation, or distributed commit semantics; retain the existing orphan/read-back policy and defer stronger retention to a follow-up.
- No per-child post-CAS reconciliation beyond the existing child-CAS return contract; RA-1's final store-owned child barrier is authoritative.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD/base subject, authorized dirty-status shape, issue/dependency state, AD/BF ceilings, historical baseline, prompt binding, or any frozen/reference hash differs;
2. either authorized new source/test path is missing, any unauthorized path appears, or any staged path exists;
3. a file outside the allowlist must change, or any existing test beyond the two exact AD-1124 assertions requires an edit;
4. a real child cannot be matched exactly to its live WorkItem/producer/AD-1125 evidence;
5. optionality, expected file type, or verifier identity would need prose/tag inference;
6. the session path would call a legacy trust-writing verifier/synthesizer method;
7. legacy executable AST changes beyond the one durable orchestrator branch;
8. the final direct-child proof and parent done update cannot share the existing WorkItemStore row lock/connection transaction without schema/raw connection work;
9. parent publication cannot prove an actually absent `crew_synth` key and merge `crew_session` plus `crew_synth` in one store CAS;
10. final done could occur before both blob read-backs, Artifact validation, provenance hash, and both refs exist;
11. a correction loses room context, real producer instructions/task text, tool-result iteration, trace/artifact refs, or tokens;
12. a producer/contributor could verify its own child/final content;
13. a verdict uses truthiness coercion or accepts malformed JSON/types;
14. storage/CAS/cancellation failure could emit done or clean up an artifact another actor may observe;
15. the test module uses a mock substrate, private lock/database reach-through, or omits any exact adjudication test name;
16. any focused serial regression persists outside AD-1126;
17. full-gate warnings arise from a changed/new path or a new unexplained family;
18. prompt archival changes either post-revision SHA-256;
19. closeout commit contains anything beyond AD-1126 and its trackers/archive;
20. any request to push or mutate GitHub appears.
21. correction projection requires editing frozen `agentic_dispatch.py`, ToolRegistry, runtime, or a tool implementation; mutates the shared registry; forwards raw runtime; or silently drops a selected capability.
22. parent publication can commit without the exact RA-1 child set/snapshots, or post-commit reconciliation requires/restores unrelated siblings.
23. local claim handling resumes a loaded `verifying` session, loops/retries more than once, or performs work after observing post-claim cancellation.

---

## Verified Against Codebase (2026-07-20)

- `PROGRESS.md:3` - AD-1125 is shipped, the authoritative full gate is 19,731 passed / 33 skipped / 431 warnings, AD-1125 is the top-level ceiling, and BF-673 is the BF ceiling.
- Git refs - initial local HEAD is clean `main` at `cedd01e7d219eac39721d36decbeafd4ffc3b571`; the subject is `AD-1125: bind crew execution to work rooms (closes #1044)`.
- GitHub read-only - #1041 OPEN, #1044 CLOSED, #1045 OPEN.
- `src/probos/cognitive/crew_orchestrator.py:310` - `run_crew_task` classifies `crew_session`, runs AD-1125 fan-out, then returns an incomplete result without verifier/synthesizer.
- `src/probos/cognitive/crew_orchestrator.py:473` - legacy `_verify` calls `SubtaskVerifier.verify()` once and skips failed results.
- `src/probos/cognitive/crew_orchestrator.py:502` - legacy `_synthesize` calls `CrewSynthesizer.synthesize()` and honest-degrades failures.
- `src/probos/cognitive/crew_executor.py:305` - `SubtaskResult` carries child id, spec id, producer id, output, status, trace, timestamps, stopped reason, tokens, Artifact refs, and dependency ids.
- `src/probos/cognitive/crew_executor.py:349` - `CrewTaskExecutor.run(parent_id)` resolves the exact room, moves a session to executing, and returns all terminal results.
- `src/probos/cognitive/crew_executor.py:631-642` - the producer's live `instructions`, real child `description or title`, exact room, and exact two-key context feed `WorkItemAgenticExecutor.run()`.
- `src/probos/cognitive/crew_verifier.py:89` - one injected `SubtaskVerifier` owns verifier selection and correction executor.
- `src/probos/cognitive/crew_verifier.py:124` - legacy `verify()` writes `TrustNetwork.record_outcome`.
- `src/probos/cognitive/crew_verifier.py:185` - legacy `converge()` performs bounded correction but drops correction tokens/traces/artifacts and room context from its return history.
- `src/probos/cognitive/crew_verifier.py:393` - legacy `_parse_verdict` uses `bool(payload.get(...))`, proving the session path needs a strict parser so `"false"` cannot accept.
- `src/probos/cognitive/crew_synth.py:87` - one injected `CrewSynthesizer` owns the legacy LLM synthesis collaborators.
- `src/probos/cognitive/crew_synth.py:126` - legacy `synthesize()` completes the parent, computes Shapley, writes trust/episode/provenance, and emits `CREW_TASK_COMPLETED`.
- `src/probos/cognitive/crew_synth.py:322-342` - legacy zero-accepted behavior returns an empty synthesis; this remains legacy-only.
- `src/probos/cognitive/crew_session.py:39-77` - exact fine states and legal edges include only executing -> verifying -> done|blocked|failed for this path.
- `src/probos/cognitive/crew_session.py:112` - strict frozen 27-key `CrewSessionContract` already requires non-empty criteria/deliverable and bounds ids/text/lists/refs.
- `src/probos/cognitive/crew_session.py:376` - `CrewSessionService` is the parent contract/state authority over injected WorkItem/ChatThread protocols.
- `src/probos/cognitive/crew_session.py:483` - `transition_session` requires expected revision and atomically projects fine state to generic WorkItem status.
- `src/probos/cognitive/crew_session.py:733` - every load validates parent type/task/status projection and exact one-room linkage.
- `src/probos/workforce.py:640` - `WorkItem.verification` already exists as a first-class JSON column.
- `src/probos/workforce.py:1244` - generic `update_work_item` has no expected-verification/identity CAS and is not suitable for finalization.
- `src/probos/workforce.py:1385` - `merge_work_item_metadata` owns exact JSON comparison, shared row lock, row preconditions, token arithmetic, rollback, and generic events.
- `src/probos/workforce.py:1428-1436` - the current expected-value loop treats a missing key as matching expected `None`, so exact absent-key admission is not live and DD-9 explicitly adds it at the store boundary.
- `src/probos/artifacts/__init__.py:82` - existing synchronous `ArtifactStore` owns named versioned Artifact rows; `add_version` returns authoritative identity.
- `src/probos/attachments/store.py:31` - async AttachmentStore protocol exposes idempotent hash write/read/exists/size without a new storage abstraction.
- `src/probos/threads/__init__.py:204` - synchronous ChatThreadStore is the room authority; session service already proves exactly one task-linked room.
- `src/probos/substrate/registry.py:18,58,71` - live registry exposes synchronous `get` and `all`, allowing exact current identity proof.
- `src/probos/substrate/agent.py:35` - live agents expose optional `instructions` used by AD-1125 execution.
- `src/probos/types.py:261` - LLMResponse exposes exact `tokens_used` plus prompt/completion token fields.
- `src/probos/runtime.py:521-524` - runtime already owns one public `artifact_store`; startup must inject it rather than create another.
- `src/probos/startup/finalize.py:1716` - CrewSessionService wires before CrewOrchestrator behind the existing default-off gate.
- `src/probos/startup/finalize.py:1755-1870` - one agentic executor, verifier, synthesizer, and orchestrator are composed; session/artifact/thread/attachment dependencies are available for one finalizer injection.
- `src/probos/config.py:6101-6113` - existing max parallel, max convergence rounds, and default-off orchestrator settings exist; no config/YAML edit is required.
- `tests/test_ad1124_crew_session_contract.py:567` - real-store full lifecycle already proves executing -> verifying -> done with both refs.
- `tests/test_ad1124_crew_session_contract.py:851` - same-revision concurrent session CAS admits exactly one writer.
- `tests/test_ad1124_crew_session_contract.py:1308` - result refs are done-only and terminal updates reject.
- `tests/test_ad1125_room_bound_execution.py:456` - real room-bound AgenticLoop/tool/Artifact/Attachment precedent exists and parent intentionally remains executing.
- `tests/test_ad1125_room_bound_execution.py:3095` - cancellation propagates and held execution tasks are reaped.
- `tests/test_ad1125_room_bound_execution.py:3126` - legacy ordinary-task orchestrator still verifies and synthesizes.
- `tests/test_ad860_crew_verifier.py` - existing scripted verification/convergence precedents exercise trust, independence, correction, and exhaustion.
- `tests/test_ad861_crew_synth.py:322` - exact legacy empty-completion test identified above.
- No existing `CrewSessionFinalizer`, session output-only verifier/synthesizer API, WorkItem verification CAS, or AD-1126 source/test exists at the verified base.

### Repair adjudication verified against the live uncommitted tree

- `src/probos/workforce.py:610-673` - `WorkItem` has 24 persisted fields; `updated_at` is the sole server-maintained field excluded from RA-1's exact 23-field semantic snapshot.
- `src/probos/workforce.py:956-1012` - existing metadata/verification limits and exact recursive JSON helpers establish bool-vs-int, object-key-set, array-order, finite-number, and strict-container precedent.
- `src/probos/workforce.py:1093-1113` - the public constructor accepts `connection_factory`, and the store owns one row-write lock, enabling protocol-faithful transaction barriers without test reach-through.
- `src/probos/workforce.py:1254-1290` - public child listing is bounded but lock-taking; RA-1 therefore pins the in-lock publication re-query to the same connection instead of recursively calling it.
- `src/probos/workforce.py:1437-1679` - repaired generic metadata CAS owns exact absent/present-key admission, parent row preconditions, status update, one commit, rollback, cache refresh, and generic events.
- `src/probos/workforce.py:1681-1809` - repaired child verification CAS returns the authoritative post-verification WorkItem that RA-1 snapshots.
- `src/probos/cognitive/crew_session.py:760-920` - repaired publication currently uses generic merge and post-commit sibling presence; RA-1 replaces the success writer and RA-4 removes only that post-commit sibling requirement.
- `src/probos/cognitive/crew_verifier.py:177-200` - repaired correction currently creates an empty private ToolRegistry, proving the capability-projection defect.
- `src/probos/cognitive/agentic_dispatch.py:566-811` - frozen ordinary dispatch derives active grants, mesh, MCP, and runtime-contributed ids from named runtime collaborators before constructing AgenticLoop.
- `src/probos/cognitive/agentic_dispatch.py:143-174` and `src/probos/tools/executor.py:40-126` - frozen dispatch records only `ToolPermissionDenied`; RA-2's projected registry therefore raises that existing type for explicit denials and delegates governed invocation through `check_and_invoke`.
- `src/probos/tools/registry.py:122-317,327-385` - public registry lookup/listing, permission resolution, governed invocation, and LOTO behavior are sufficient for source authority; no ToolRegistry edit is needed.
- `src/probos/cognitive/mcp_workbench.py:330-355` - `dispatch_tool_ids` mutates only when `find_mcp_tool` is absent; RA-2 permits it only after public lookup proves registration already exists.
- `src/probos/cognitive/crew_finalizer.py:650-706` - repaired local claims currently return an observation when loading `verifying` under a local owner; RA-3 replaces that branch and pins claim-attempt signaling plus the one bounded retry.
- `tests/test_ad1126_verified_finalization.py` is present in the authorized repair tree. Its pre-repair case count is deliberately not recorded as final `N`.

---

## Three-pass Architect self-review

### Pass 1 - Architectural correctness

**Verdict:** APPROVED.

- One finalizer owns one reason to change and composes only existing public authorities.
- Parent state, child verification, Artifact metadata, and blob bytes remain owned by their existing stores/services.
- Every required child converges before synthesis; the store-owned final barrier closes child-set/row drift before parent done; synthesis and final verification are independent and side-effect-free.
- Correction projection is local, event-neutral, publicly governed, shared-registry immutable, and explicit about denied capabilities.
- Failure, cancellation, concurrency, orphan, and no-false-done behavior are explicit.
- All ten known open questions are resolved without inventing optionality, file inference, a second database, or AD-1127+ behavior.

### Pass 2 - Live signatures and paths

**Verdict:** APPROVED.

- Every named existing path/class/method/constructor/field/state/config key was read on exact HEAD.
- Sync Artifact/Thread stores are called through `asyncio.to_thread`; async WorkItem/Attachment/Session APIs remain awaited.
- Runtime already exposes the one ArtifactStore; startup does not create another.
- The new methods are additive at verified owning boundaries; no phantom API is assumed.
- RA-1 binds the new store/service signatures to the existing row-lock and connection authority; RA-2 binds only public ToolRegistry/runtime surfaces available on the live repair tree.
- Exact legacy test names and method side effects are pinned as parity oracles.

### Pass 3 - Internal consistency, arithmetic, and scope

**Verdict:** APPROVED.

- `N` is measured after repair rather than inferred from the current module; because only that module adds test functions relative to `cedd01e7`, Gate 4 remains exactly `19,731 + N` passed with 33 skipped.
- The file allowlist, historical base/frozen hashes, dirty repair baseline, no-MagicMock substrate rule, focused-repair-first ordering, one-full-suite rule, warning provenance, AST parity, closeout order, exact commit, no-push, and no-GitHub constraints agree across both documents.
- AD-1127 through AD-1133 and every tempting adjacent system are fenced explicitly.

## Re-review (2026-07-20) - Authoritative adjudication

**Verdict:** APPROVED - ready for focused repair handoff.

### Pass 1 - Architecture

**Required:** none.

- RA-1 puts the final direct-child set and semantic-row proof inside the same store-owned row lock/transaction as parent done, while explicitly excluding global writer-lock redesign and per-child reconciliation.
- RA-2 preserves ordinary correction capability categories through a detached registry and narrow facade. Explicit denials are unbypassable by grants, while safe source-backed invocations retain live permission, MCP, and LOTO authority.
- RA-3 synchronizes local callers on claim-attempt settlement, which supports exactly one pre-claim-cancellation retry and zero work after a committed claim.
- RA-4 separates pre-commit sibling admission from post-commit authoritative proof; RA-5 is one total exact validator; RA-6 preserves accepted-count, convergence identity, Artifact evidence, cancellation, and output-only behavior.

### Pass 2 - Live signatures and paths

**Required:** none.

- The new store API is additive beside the live metadata/verification CAS methods and uses the existing connection abstraction, row lock, rollback, cache, and event conventions.
- The new service parameter is additive and testable through the existing public API-signature assertions.
- Correction projection uses only live public ToolRegistry, ToolPermissionStore, intent-grant, MCP workbench, and named runtime surfaces. `agentic_dispatch.py`, ToolRegistry, runtime, config, and tool implementations remain frozen.
- The 23-field snapshot matches the live WorkItem row decoder exactly except for server-maintained `updated_at`; canonical exact-JSON semantics and byte ceilings are explicit.

### Pass 3 - Internal consistency

**Required:** none.

- All twelve adjudicated test names appear exactly in both architecture and execution instructions; child-set coverage explicitly includes add and delete.
- `N` is discovered by the post-repair complete-module focused run, never hardcoded from the current tree; Gate 2 and Gate 3 follow Architect approval, followed by exactly one authoritative Gate 4.
- The execution companion pins the authorized dirty-tree hashes, historical base/frozen parity, exact allowlist, no-stage/no-push/no-GitHub constraints, and the final binding hash.
- Every acceptance section retains: Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
