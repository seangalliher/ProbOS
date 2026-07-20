# AD-1125 - Room-bound agentic execution with durable child evidence

**Verdict:** APPROVED FOR BUILDER HANDOFF, CONDITIONAL ON THE ISSUE #1044 AMENDMENT BELOW
**One-line:** Resolve one authoritative task room before fan-out, run every child AgenticLoop in that room, persist bounded child execution evidence and terminal non-done outcomes, and leave a durable CrewSession in `executing` for AD-1126 verification/finalization.

**Parent epic:** [#1041](https://github.com/seangalliher/ProbOS/issues/1041) - Durable Crew Work Sessions
**GitHub issue:** [#1044](https://github.com/seangalliher/ProbOS/issues/1044) - AD-1125
**Dependency:** [#1043](https://github.com/seangalliher/ProbOS/issues/1043) / AD-1124 is `CLOSED`
**Next issue boundary:** [#1045](https://github.com/seangalliher/ProbOS/issues/1045) / AD-1126 remains `OPEN`
**Repository:** OSS `D:\ProbOS`
**Exact base HEAD / `origin/main` / remote `main`:** `31c1b648a91bdf21c27aa577d2d6000c99f61051`
**Exact base subject:** `AD-1124: add durable crew session contract (closes #1043)`
**Exact base status before Architect artifacts:** clean `main`; no staged, modified, deleted, or untracked paths
**Numbering:** current top-level ceiling **AD-1124**; current bug-fix ceiling **BF-673**; build **AD-1125** only
**License disposition:** no external code, dependency, model, or asset
**Estimated tests:** one new red-first module, approximately 24-32 cases; update assertions/signatures only in two existing modules; report exact collected count `N`

## Scope

AD-1125 delivers only the execution slice of epic #1041:

1. resolve one existing-or-created parent task room once before child execution;
2. pass that exact `thread_id` to every child `WorkItemAgenticExecutor.run(...)` and therefore every child `AgenticLoop` tool context;
3. pass only the parent/session id and child WorkItem id in bounded `extra_context`;
4. extend `WorkItemAgenticOutcome` with run-local total tokens and bounded produced-artifact refs derived from structured tool results;
5. make `CodeExecutionTool.artifact_details` identify the actual persisted Artifact rows and content hashes;
6. persist one exact bounded `metadata["crew_execution"]` record per child plus cumulative `WorkItem.actual_tokens` and the validated terminal WorkItem status;
7. durably block unassigned, unresolvable, and failed-dependency children;
8. durably fail execution exceptions, AgenticLoop errors, max-iteration stops, and token-budget stops;
9. transition an initialized AD-1124 parent `discussing -> executing` through `CrewSessionService` before any child tool call;
10. stop the durable-session orchestrator path after fan-out, leaving the parent in `executing` for AD-1126.

Legacy non-`crew_session` parents retain the existing AD-867 resolve -> delegate -> fan-out -> verify -> synthesize pipeline. AD-1125 does not create a second executor or orchestration engine.

---

## Required issue #1044 amendment before Builder start

The live issue is directionally correct but incomplete against the landed AD-1124 base:

- `CrewOrchestrator.run_crew_task()` currently performs a direct generic parent promotion before `CrewTaskExecutor` resolves a room. A `crew_session` must instead move through `CrewSessionService` after its exact bound room is resolved.
- `CrewSynthesizer` currently performs direct generic completion. Calling it for a `crew_session` in AD-1125 would produce `WorkItem.status == "done"` while the authoritative fine state remained `executing`, violating AD-1124 and prematurely building AD-1126.
- `AgenticLoop` already appends each tool result to the next LLM request. AD-1125 must prove and preserve that behavior, not redesign it.
- `CodeExecutionTool.artifact_details` currently omits Artifact id, content hash, and thread id, so the executor cannot derive truthful artifact refs from the returned result.
- `AgenticDispatchConfig` has no token-budget field and no config/YAML change is allowed. AD-1125 persists the existing `AgenticResult.stopped_reason == "token_budget"` contract when returned; it does not add a new budget policy.

Before the Builder starts, replace issue #1044's current `## Decision` section, through the line immediately before `## Acceptance`, with this exact Markdown:

```markdown
## Decision

- Refactor the existing AD-925 room helper into one resolver that returns the authoritative `ChatThread` (or `None` only for a legacy parent with no room). Query existing task-linked rooms before the auto-create flag. Exactly one existing room wins; duplicate rooms fail closed. Only a legacy non-`crew_session` parent may use the existing AD-918 create path. An initialized AD-1124 `crew_session` already owns one exact bound room and must never create or select a replacement here.
- Resolve the room once per parent before child AgenticLoop work. Pass the same `thread_id` into every `WorkItemAgenticExecutor.run(...)` call. Pass only `_crew_session_id=<parent id>` and `_crew_work_item_id=<child id>` through `extra_context`; never put blobs, full results, source files, or traces there.
- Inject the landed `CrewSessionService` into `CrewTaskExecutor`. For an initialized `crew_session`, require the resolved room id to equal the contract `thread_id`, then transition `discussing -> executing` (or accept the exact idempotent `executing` state) through `CrewSessionService` before any child starts. Do not directly update the parent status.
- Preserve the legacy AD-867 parent path. For a `crew_session`, skip the current verifier and synthesizer after fan-out and return a partial `SynthesisResult(completed=False)` while the parent remains `executing`; AD-1126 owns convergence, verification, final synthesis acceptance, final result artifact, and `executing -> verifying -> done/failed`.
- Keep all actual work in the existing `WorkItemAgenticExecutor` / `AgenticLoop`. Do not add work to `DmReplyPipeline` marker handlers and do not create another executor.
- Preserve AgenticLoop's existing multi-turn rule: a tool result is appended to the next LLM request and only a later text-only LLM turn may become the final child text. Add a real scripted multi-iteration test that inspects the second request and proves it contains the real tool result.
- Extend `CodeExecutionTool.artifact_details` additively so each entry contains exactly `artifact_id`, `content_hash`, `thread_id`, `name`, `mime`, `size_bytes`, and `version`, all taken from the persisted Artifact row. Keep the existing `artifacts` filename list and every other output key unchanged.
- Extend `WorkItemAgenticOutcome` additively with `total_tokens` and bounded `artifact_refs`, preserving existing defaults. Capture raw structured tool results through the existing `ToolExecutor` post-hook seam; do not make AgenticLoop tool-specific and do not parse Python string representations.
- Persist each terminal child run under one exact bounded `metadata["crew_execution"]` contract, plus cumulative `WorkItem.actual_tokens`, through the existing store-owned row-write lock and validated state transition. Store refs and bounded summaries only, never raw tool output, stdout/stderr, source code, artifact bytes, or trace bytes.
- Map `complete -> done`; map AgenticLoop `error`, `max_iterations`, and `token_budget`, plus an execution exception, to `failed`; map unassigned/unresolvable and failed-dependency children to `blocked`. No terminal run may silently leave a child `in_progress`, and a failed child never unblocks dependents.
- Keep fan-out bounded by `max_parallel_subtasks`. Preserve cancellation propagation and strong task references.
```

Then insert these exact bullets in `## Acceptance` after the current first bullet:

```markdown
- An initialized `crew_session` moves `discussing -> executing` through `CrewSessionService` before the first child tool call and remains `executing` after AD-1125 fan-out. Its generic status remains the exact AD-1124 projection `in_progress`.
- AD-1125 does not invoke verifier or synthesizer for a `crew_session`; legacy non-session parents keep the existing full AD-867 pipeline unchanged.
- Existing-room resolution occurs even when `group_chat.auto_task_room_enabled` is false; duplicate task-linked rooms and a contract/room mismatch fail before child execution.
- Token-budget handling in this AD is persistence of the existing AgenticResult stop reason, not a new configuration policy. No config model or YAML field is added.
```

No other issue or epic text needs amendment. The Builder verifies the amended wording read-only and does not edit, comment, label, close, or assign any GitHub issue.

---

## Live compatibility findings

### Finding 1 - AD-1124 changes parent-state ownership

`CrewSessionService.transition_session(...)` is the only valid owner of fine-state transitions and their coarse `WorkItem.status` projection. The current `CrewOrchestrator._promote_parent()` direct `open -> in_progress` path is valid only for legacy parents. Directly applying it to a `crew_session` creates a projection mismatch.

### Finding 2 - Current call order resolves the room too late

The live order is parent direct promotion, child assignment, then `CrewTaskExecutor.run()`, whose `_maybe_open_task_room()` returns `None`. The smallest correct change is:

1. keep direct parent promotion only for non-session parents;
2. let child assignment finish, because room participants are assigned children;
3. have `CrewTaskExecutor.run()` resolve one room and start the session before spawning child tasks;
4. pass the returned room id into every child call.

### Finding 3 - Tool-result reasoning already exists

`AgenticLoop.run()` builds a `ToolCallResult`, appends `[tool_result:...]` as the next user message, and calls the LLM again. No production AgenticLoop edit is required. The forcing test must inspect the second `LLMRequest.prompt`; merely asserting two calls is insufficient.

### Finding 4 - Structured artifact identity is lost at the tool boundary

`ArtifactStore.add_version(...)` returns the authoritative row, but `CodeExecutionTool._capture_artifacts()` currently returns only name/mime/size/version. The additive output extension must use values from that returned row. `WorkItemAgenticExecutor` can record the raw `ToolResult` through inherited `ToolExecutor.add_post_hook(...)`; no string parsing and no tool-specific AgenticLoop branch is needed.

### Finding 5 - Child failure is currently not durable

Unresolvable children return an in-memory failed result while the WorkItem stays `open`; loop-bound failures leave the child `in_progress`; dependency-blocked children produce no result and stay `open`. AD-1125 must persist every one of those terminal run outcomes.

---

## Pinned design decisions

### DD-1 - One room resolver, existing first, creation only for legacy parents

Replace `_maybe_open_task_room(...) -> None` with a private, fully annotated resolver whose effective contract is:

```python
async def _resolve_task_room(
    self,
    parent: WorkItem,
    children: list[WorkItem],
) -> ChatThread | None:
    ...
```

Exact behavior:

1. obtain the injected/runtime `ChatThreadStore`; if present, call `list_threads(task_id=parent.id, include_archived=True, limit=2)` through `asyncio.to_thread` before reading the auto-create flag;
2. one row: return that exact `ChatThread`, even when auto-create is disabled;
3. more than one row: raise stable `ValueError("crew_task_room_cardinality_invalid")`; never select by recency;
4. zero rows + `parent.work_type == "crew_session"`: raise stable `ValueError("crew_session_thread_not_found")`; AD-1124 initialization owns room provisioning/binding;
5. zero rows + legacy parent + flag off, missing service/store, or fewer than two distinct crew assignees: return `None` and preserve legacy execution;
6. zero rows + eligible legacy parent: call the existing `AgentGroupChatService.create_group_chat(...)`, and return `GroupChatCreateResult.thread` only when `ok` and non-`None`;
7. a rate-limited/suppressed legacy create remains a logged honest-degrade to `None`; fan-out continues without a room as before.

Do not add a second thread-creation path, unique index, cross-database transaction, repair routine, or semantic room dedup.

### DD-2 - CrewSession transition occurs before any child task

Add one optional constructor-injected `CrewSessionService` dependency to `CrewTaskExecutor`. Startup passes the already-wired `runtime.crew_session_service`.

For `parent.work_type == "crew_session"`:

1. service absence is a data-integrity/composition failure; no child runs;
2. `get_session(parent.id)` must return a contract;
3. the resolved room must be non-`None` and its id must equal `contract.thread_id`;
4. only `discussing` and `executing` are executable in AD-1125;
5. call `transition_session(parent.id, "executing", expected_revision=contract.revision)` before creating any `_guarded` task;
6. do not catch-and-continue into child execution after a service/room failure.

The service revalidates the one-room invariant; the resolver's single lookup means the room id is computed once for child context, not once per child.

### DD-3 - Exact bounded child context

Every child executor call receives:

```python
thread_id=resolved_thread.id if resolved_thread is not None else "",
extra_context={
    "_crew_session_id": parent_id,
    "_crew_work_item_id": child.id,
},
```

Both values must be strings no longer than 128 code points and must match the existing AD-1124 id grammar before dispatch. This context contains no child description, final text, tool result, artifact metadata, trace, bytes, or other blob. The four existing core context keys in `WorkItemAgenticExecutor` remain authoritative; these two underscore-prefixed keys cannot replace them.

### DD-4 - Additive outcome and artifact-ref contract

Extend `WorkItemAgenticOutcome` without changing existing defaults:

```python
total_tokens: int = 0
artifact_refs: list[dict[str, Any]] = field(default_factory=list)
```

`total_tokens` is exactly `AgenticResult.total_tokens`, normalized to a non-boolean nonnegative int. `artifact_refs` is extracted after the loop from raw successful `run_python` `ToolResult.output["artifact_details"]` values captured by a synchronous post-hook on `DispatchToolExecutor`.

Do not parse `ToolCallResult.output`, `repr(dict)`, stdout, final text, or the persisted trace blob. Ignore malformed/untrusted result entries with one contextual warning; do not fabricate a ref from a filename.

Each artifact ref has exactly these seven keys:

| Key | Exact rule |
|---|---|
| `artifact_id` | non-empty AD-1124-style id, max 128 |
| `content_hash` | lowercase 64-hex SHA-256 |
| `thread_id` | exact execution thread id; non-empty for captured artifacts |
| `name` | basename only, no slash/backslash/NUL, 1..255 code points |
| `mime` | non-empty string, max 255 code points |
| `size_bytes` | exact non-boolean int, `1..26_214_400` |
| `version` | exact non-boolean int, `1..2_147_483_647` |

Scan at most 64 candidate entries per tool result, retain at most 32 unique artifact ids in first-seen order, and require the entry thread id to equal the execution `thread_id`. Return fresh dict/list objects so a tool-owned mutable alias cannot change the outcome later.

### DD-5 - CodeExecutionTool returns authoritative persisted identity

Keep the top-level `ToolResult.output` keys and `artifacts: list[str]` behavior unchanged. Each `artifact_details` entry returned by `_capture_artifacts` becomes exactly:

```python
{
    "artifact_id": art.id,
    "content_hash": art.content_hash,
    "thread_id": art.thread_id,
    "name": art.name,
    "mime": art.mime,
    "size_bytes": art.size_bytes,
    "version": art.version,
}
```

Use the actual `Artifact` returned by `ArtifactStore.add_version`; do not reconstruct identity from requested inputs. Staged-but-unchanged documents still produce no new version and no ref. The existing artifact bytes, MIME selection, version chain, 25 MiB cap, and attachment write remain unchanged.

### DD-6 - Exact child execution evidence contract

Persist one server-owned record at `WorkItem.metadata["crew_execution"]`. It has exactly these fourteen keys:

| Key | Exact rule |
|---|---|
| `version` | exact integer `1` |
| `parent_id` | bounded id, exact parent/session id |
| `work_item_id` | bounded id, exact child id |
| `thread_id` | bounded id or `""` only for a legacy no-room run |
| `assigned_to` | bounded agent id or `None` |
| `status` | exact `done`, `failed`, or `blocked` |
| `stopped_reason` | exact normalized reason below |
| `output_summary` | trimmed string, max 4,096 code points, deterministic truncation marker when needed |
| `tool_trace_ref` | lowercase SHA-256 or `None` |
| `artifact_refs` | 0..32 exact DD-4 records |
| `tokens_used` | exact non-boolean int, `0..9_223_372_036_854_775_807` for this run |
| `started_at` | finite nonnegative server timestamp |
| `finished_at` | finite server timestamp `>= started_at` |
| `blocked_dependency_ids` | 0..64 unique bounded ids; non-empty only for `dependency_blocked` |

Allowed normalized `stopped_reason` values are:

```text
complete
error
max_iterations
token_budget
execution_exception
unassigned
agent_unresolvable
dependency_blocked
start_transition_failed
```

Map any unknown non-success AgenticLoop reason to `error`; do not persist arbitrary model/tool text as a reason. The compact UTF-8 JSON record must be at most 32,768 bytes. Store no raw tool request/result, code, stdout, stderr, artifact bytes, trace bytes, prompt, instructions, or exception text.

`SubtaskResult` gains additive defaults for `stopped_reason`, `actual_tokens`, and `artifact_refs` so downstream AD-860/861 shapes remain compatible. Its in-memory `output` may remain the final child text; only the bounded summary is persisted.

### DD-7 - Atomic metadata/status/token persistence stays store-owned

Extend the existing public `WorkItemStore.merge_work_item_metadata(...)` with one optional keyword-only parameter:

```python
actual_tokens_delta: int = 0
```

Rules:

1. exact non-boolean int in `0..9_223_372_036_854_775_807`;
2. validate inside the existing row-write lock that `item.actual_tokens + delta` does not overflow that bound;
3. when nonzero, update `actual_tokens = actual_tokens + ?` in the same SQL statement/commit as metadata and optional validated status;
4. preserve the exact existing code path, SQL behavior, events, CAS rules, and no-op behavior when `actual_tokens_delta == 0`;
5. no schema/DDL, raw connection, new lock, or new public store method.

The executor writes the `crew_execution` patch, validated target status, run token delta, expected current status, expected work type, and expected non-empty assignee (when present) through this primitive. It never calls `update_work_item(status=...)` and never writes raw SQL.

### DD-8 - Exact terminal status mapping and dependency closure

| Condition | WorkItem target | Evidence status/reason | Unblocks dependents |
|---|---|---|---|
| Agentic `complete` | `done` | `done` / `complete` | yes |
| Agentic `error` | `failed` | `failed` / `error` | no |
| `max_iterations` | `failed` | `failed` / `max_iterations` | no |
| `token_budget` | `failed` | `failed` / `token_budget` | no |
| executor raises ordinary `Exception` | `failed` | `failed` / `execution_exception` | no |
| no assignee | `blocked` | `blocked` / `unassigned` | no |
| assigned id does not resolve | `blocked` | `blocked` / `agent_unresolvable` | no |
| no runnable task remains because dependencies did not reach done | `blocked` | `blocked` / `dependency_blocked` plus exact unresolved dependency ids | no |
| child cannot enter `in_progress` | `blocked` | `blocked` / `start_transition_failed` | no |

Every terminal child appears once in the returned `SubtaskResult` list and emits the existing `SUBTASK_COMPLETED` event. Dependency-blocked children are no longer absent. Ordinary cancellation is not translated; `asyncio.CancelledError` propagates and task references are still removed by the owning wait/drain path.

If atomic evidence persistence itself fails, log an ERROR with child id/reason/next action, make one validated best-effort `in_progress -> failed` transition, and return/raise a failed result without claiming evidence was stored. Never report `done`, never unblock dependents, and never raw-update the status.

### DD-9 - Durable sessions stop after fan-out; legacy orchestration is unchanged

At the start of `CrewOrchestrator.run_crew_task`, classify the existing parent by `work_type` through `WorkItemStore.get_work_item`.

- Non-session parent: preserve current `_promote_parent`, verify, and synthesize behavior exactly.
- `crew_session` parent: skip `_promote_parent`; assignment still runs; `CrewTaskExecutor` owns the service transition and fan-out; after `_execute`, do not call `_verify` or `_synthesize`; return `SynthesisResult(parent_id=..., final_output="", completed=False, accepted_count=0, total_count=len(results))`.

This is the deliberate AD-1125/1126 boundary. Do not call `CrewSessionService.transition_session(..., "verifying"|"done"|"failed")` here. Do not modify `CrewVerifier` or `CrewSynthesizer`.

### DD-10 - Default-off and legacy parity

Reuse `agentic_dispatch.orchestrator_enabled`; add no flag. Startup already wires `CrewSessionService` immediately before `CrewOrchestrator`. Pass that exact service into `CrewTaskExecutor`; no runtime back-reference or private attribute access.

With the orchestrator gate false, existing startup remains inert. With a legacy parent, no existing/created room still yields `thread_id=""` and the full legacy pipeline remains unchanged. No `config/system.yaml` edit is permitted.

---

## Build

### Section 1 - Red-first AD-1125 module

Create only `tests/test_ad1125_room_bound_execution.py` first. Before any production edit, run one headline node that imports existing classes only and asserts the missing room/evidence behavior. It must fail on the exact base because the child run receives `thread_id=""`, the outcome has no token/artifact fields, or the child evidence/status is absent. Record command, node id, assertion, and reason.

The new module must use:

- real `WorkItemStore` with a real temporary SQLite database;
- real `ChatThreadStore`;
- real `ArtifactStore`;
- real `FilesystemAttachmentStore`;
- real `CrewSessionService`;
- real `ToolRegistry` and `ToolPermissionStore`;
- real `WorkItemAgenticExecutor`, `AgenticLoop`, `CodeExecutionTool`, and `SubprocessSandbox` on the headline path;
- real `SystemConfig` / existing Pydantic config objects;
- a hand-written scripted multi-iteration LLM and narrow hand-written agent/registry/verifier/synth recorders;
- deterministic clocks/id factories where identity/timing is asserted.

The new module must contain none of:

```text
MagicMock
AsyncMock
unittest.mock.Mock
unittest.mock.patch
```

No permissive `SimpleNamespace` may stand in for WorkItem, ChatThread, Artifact, Attachment, ToolRegistry, ToolPermissionStore, or CrewSessionService. A small runtime composition object is allowed only as the owner of those real instances.

Required named test families:

1. real orchestrator -> crew executor -> WorkItemAgenticExecutor -> AgenticLoop -> real `run_python` two-turn flow;
2. second scripted LLM request contains the actual `[tool_result:...]`, persisted artifact id/hash/thread id, and first tool result; final text comes only from the second response;
3. existing room input is staged and read when `stage_thread_artifacts=True`; output is a new real ArtifactStore row in the same room;
4. outcome tokens/artifact refs and persisted child `actual_tokens`/metadata are exact and non-empty;
5. parent is `executing` / generic `in_progress` before tool invocation and remains there; verifier/synth recorders receive zero calls;
6. every child receives the same non-empty room id and exact two-key extra context;
7. existing room resolves with auto-create disabled;
8. eligible legacy create returns and propagates the real `GroupChatCreateResult.thread.id`;
9. duplicate rooms and session-contract room mismatch fail before child LLM/tool work;
10. no-room legacy path preserves empty thread behavior;
11. exact artifact-details seven-key allowlist; malformed, cross-thread, duplicate, oversized, and over-scan entries are dropped without mutable aliasing;
12. exact fourteen-key child evidence allowlist, 32 KiB cap, summary truncation, ref/id/token/timestamp bounds, and no forbidden raw content;
13. complete, error, execution exception, max-iterations, token-budget, unassigned, unresolvable, start-transition failure, and dependency-blocked persistence;
14. failed dependency does not unblock its child; independent siblings still run; blocked child is returned and emits completion;
15. `actual_tokens_delta` exact-int validation, overflow rejection, atomic metadata/status/token write, old zero-delta path parity, rollback/cancellation lock release;
16. max concurrency remains exactly bounded;
17. cancellation propagates and leaves no leaked held child task;
18. legacy non-session orchestrator still calls verifier+synthesizer and completes as before;
19. default-off startup path remains inert and `config/system.yaml` remains unchanged.

### Section 2 - Store-owned token delta

Modify only `src/probos/workforce.py` at `merge_work_item_metadata` per DD-7.

Current anchor:

```python
    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
```

Add only the keyword and internal validation/SQL branches needed for an atomic nonnegative delta. Keep all pre-AD-1125 callers and zero-delta behavior unchanged.

### Section 3 - Structured tool evidence and additive outcome

Modify only `src/probos/tools/code_execution_tool.py` and `src/probos/cognitive/agentic_dispatch.py`.

In `CodeExecutionTool._capture_artifacts`, replace the current four-key append with the exact DD-5 seven-key row-derived shape.

In `WorkItemAgenticExecutor.run`:

1. install one synchronous post-hook on the existing `DispatchToolExecutor` before loop execution;
2. retain only raw `(tool_id, ToolResult)` observations needed for post-run artifact extraction;
3. do not mutate the result before AgenticLoop consumes it;
4. map `AgenticResult.total_tokens` and validated artifact refs into the additive outcome fields;
5. preserve `_persist_tool_trace` behavior and hash semantics; traces stay in AttachmentStore and refs stay in metadata.

Do not edit `agentic_loop.py` or `tool_call.py`.

### Section 4 - Room/session execution and child persistence

Modify only `src/probos/cognitive/crew_executor.py` per DD-1 through DD-3, DD-6 through DD-8, and DD-10.

The current anchors are:

```python
        await self._maybe_open_task_room(parent_id, children)
```

and:

```python
            outcome = await self._executor.run(
                agent_id=agent.id,
                instructions=str(getattr(agent, "instructions", "") or ""),
                task_text=task_text,
                runtime=self._runtime,
                department=str(getattr(agent, "department", "") or ""),
                rank=str(getattr(agent, "rank", "ensign") or "ensign"),
            )
```

Replace the first with one returned room plus pre-spawn session start. Extend the second with the exact room/context arguments. Centralize terminal evidence/status/token persistence in one private helper used by every path; do not duplicate metadata construction across branches.

Update only obsolete fake signatures/assertions in:

- `tests/test_ad859_crew_executor.py`;
- `tests/test_ad925_auto_task_room.py`.

Do not add new test functions there. All new behavior coverage belongs in the AD-1125 module, keeping the exact existing baseline count stable.

### Section 5 - Session-only orchestrator boundary

Modify only `src/probos/cognitive/crew_orchestrator.py` per DD-9.

Current order anchor:

```python
        await self._promote_parent(parent_id)

        children = await self._load_children(parent_id)
```

Classify the existing parent before promotion. Preserve the complete legacy branch. After `_execute`, return the exact partial result for a durable session before `_verify`.

Do not edit verifier or synthesizer code and do not manufacture an accepted/converged result.

### Section 6 - Startup injection

Modify only `_wire_crew_orchestrator` in `src/probos/startup/finalize.py`:

1. read the already-wired public `runtime.crew_session_service`;
2. pass it to `CrewTaskExecutor`;
3. preserve the existing gate, dependency list, order, and legacy honest-degrade behavior;
4. do not add a second service construction and do not edit runtime/config/startup-result/shutdown surfaces.

### Section 7 - Gates, reviews, and closeout

Run the execution prompt's exact red, focused, caller, blast, and full gates. After all gates and all three Builder review passes are approved:

1. prepend one AD-1125 shipped block to `PROGRESS.md` with exact counts, room/session ordering, child evidence/status mapping, legacy parity, AD-1125/BF-673 ceilings, and no finalization/lifecycle/config work;
2. prepend `### AD-1125 (2026-07-18) - room-bound agentic execution (#1044)` under Era V in `DECISIONS.md` with Context / Decision / Tests;
3. add one AD-1125 row immediately after AD-1124 in the Crew Autonomy table of `docs/development/roadmap.md`, referencing epic #1041 and issue #1044, priority 1, marked shipped / closes on push;
4. move both active prompt files byte-for-byte to `prompts/archive/`, verifying pre/post SHA-256 equality;
5. stage explicit allowlisted paths only;
6. commit exactly `AD-1125: bind crew execution to work rooms (closes #1044)`;
7. do not push and do not mutate GitHub.

Issue #1044 closes only after the Captain/orchestrator pushes the local commit.

---

## Exact file allowlist

### Production

- `src/probos/workforce.py`
- `src/probos/cognitive/agentic_dispatch.py`
- `src/probos/cognitive/crew_executor.py`
- `src/probos/cognitive/crew_orchestrator.py`
- `src/probos/tools/code_execution_tool.py`
- `src/probos/startup/finalize.py`

### Tests

- `tests/test_ad1125_room_bound_execution.py` - new
- `tests/test_ad859_crew_executor.py` - obsolete expectations/fake signature only; no new test function
- `tests/test_ad925_auto_task_room.py` - obsolete helper/fake signature only; no new test function

### Architect documents - active until closeout, then hash-preserving move

- `prompts/ad-1125-room-bound-agentic-execution.md`
- `prompts/ad-1125-room-bound-agentic-execution-execution.md`

### Conditional closeout only

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`

No other path is authorized. In particular, do not edit `src/probos/config.py`, `config/system.yaml`, `src/probos/runtime.py`, `src/probos/cognitive/swe_harness/agentic_loop.py`, `src/probos/cognitive/swe_harness/tool_call.py`, `src/probos/cognitive/crew_session.py`, `src/probos/cognitive/crew_verifier.py`, `src/probos/cognitive/crew_synth.py`, Artifact/Attachment/ChatThread stores, group-chat service, DmReplyPipeline, events, protocols, any API/UI/desktop file, any dependency manifest, or any other test.

---

## Exact base hashes

All existing allowlisted files must match before Builder edits:

| Path | SHA-256 |
|---|---|
| `src/probos/workforce.py` | `906beeddbf6cb150aa18500fce32f2de22d56eee6300b557c0fce788fdc88683` |
| `src/probos/cognitive/agentic_dispatch.py` | `4d072968703e13481fff9f400c128839efbb480fb87b289199b2a0c92e0ce4f9` |
| `src/probos/cognitive/crew_executor.py` | `499e5f7397a0599091e838444a907e33a7ada4ed8cfe3c3d7e2c4db7f3661936` |
| `src/probos/cognitive/crew_orchestrator.py` | `f77ca5adfae7e7abccc46a37fba824e8dfd126afe80f9eeba757266a02c5f575` |
| `src/probos/tools/code_execution_tool.py` | `4db6d48cdc5d8548f389e24adc35b08248e66b4f387fad6b4947cfd572441e28` |
| `src/probos/startup/finalize.py` | `2688dedc7875947de6bb4b6d434e45469452b5dea811eba210f704cd303242a6` |
| `tests/test_ad859_crew_executor.py` | `b629c7704d932a948c15220b8d6d4c71faba748840033882c86d3740f8280797` |
| `tests/test_ad925_auto_task_room.py` | `b9cb9c2069818c999c8a9c33ccbdb7ad2a6b62c585fe1d48bc42885bf6e378de` |

These frozen reference surfaces must remain unchanged:

| Path | SHA-256 |
|---|---|
| `src/probos/cognitive/swe_harness/agentic_loop.py` | `c14228337f4349c3013b2c491f35ea858a56a1ed99bee5f87f3e756ba5483b58` |
| `src/probos/cognitive/swe_harness/tool_call.py` | `f71e5529717cc7a1c56eac8e47bea45a7bcfc3f9f6aa6166d3579ed212ccc67c` |
| `src/probos/cognitive/crew_session.py` | `441792154ac777db8753478572f429661d56381f65bbfa76d6b1abfcee0087e9` |
| `src/probos/cognitive/crew_verifier.py` | `4c2241dc683d44690becae3092bbb1de3b30f3ebc22853c7ea926af9b77b2d1e` |
| `src/probos/cognitive/crew_synth.py` | `94c043631690f2fc9b65ab03139e85659a9cdfb8311ae62ece89691c8bacbb65` |
| `src/probos/artifacts/__init__.py` | `d86d82a58da5b1b5fa733812e23c615b3380c23a8d4ebdd4f9621629d4985c02` |
| `src/probos/attachments/filesystem_store.py` | `04828922889b7ec4434b085979a62de03b4470a0d819b9758c1d0bc4cf6588a6` |
| `src/probos/attachments/store.py` | `fffcef4c47e3e565daa64e6a49593e2578a68a04d8ed93d5aaebf4c172bfd0fb` |
| `src/probos/threads/__init__.py` | `88fe637aca2475b74a53fb934a30feff01ba84acd6516a2c8f277ddc367f29ff` |
| `src/probos/threads/agent_group_chat.py` | `2a35bfe3bec4fcb653a3976dba24e7a1e42d654c7a186813347e49f13cf2b7f1` |
| `src/probos/runtime.py` | `93680b0d116044bcbeab5bc673dfd54597de408c460b762cd26bb2ceb19a441f` |
| `src/probos/config.py` | `aa7a67269da3f34cb43bb2210921211ad22e57dfbfd1f6e8117327ad02247c10` |
| `config/system.yaml` | `2da205cae542b9635062be8874ebb38a4019592ddc8e3ff017a9163913e65f85` |
| `tests/test_ad545_agentic_loop.py` | `fb0d28aa328cea620ec47b9853539f046cb65c5f61755d38a58477c18d18b352` |
| `tests/test_ad859a_agentic_executor.py` | `3327e7fc38df9a2233aa64e08a83868c1e05c7ffae5f417553e6c84a2106b44a` |
| `tests/test_ad867_crew_orchestrator.py` | `7de99f6069c66e32ac25c4fece79d3de0d8923a93b62245df28023acc06344aa` |
| `tests/test_ad1066_code_execution_tool.py` | `9bd22815f913ec06c7548799cfd60f294b147a84790eb0d13b2c86ef42167ff5` |
| `tests/test_ad1074d_round_trip_edit.py` | `9b3ec07ffb3464024564c2a2ee25e6bc19121fedb63a50537581d19733e49bc4` |
| `tests/test_ad1124_crew_session_contract.py` | `eb082e14e6198a0b86a3c22c09b347a867eff0bc8f205b8c7aae911a0cf0a2f2` |

`tests/test_ad1125_room_bound_execution.py` must not exist before build. Any mismatch is a hard stop for Architect re-verification.

---

## Recorded exact-base gate baselines

Measured on clean `31c1b648a91bdf21c27aa577d2d6000c99f61051` with isolated temporary data, local/offline embeddings, serial pytest, and `RuntimeWarning` promoted to error:

| Gate | Exact base result |
|---|---:|
| Directly affected focused files | **127 passed**, no warnings |
| Remaining direct executor/code-tool callers | **72 passed / 1 skipped**, no warnings |
| Crew/workforce/thread/runtime blast | **349 passed**, no warnings |
| Full parallel result recorded by AD-1124 at this exact commit | **19,643 passed / 33 skipped / 0 failed / 455 warnings** |

The editor test runner reported no discovered tests for the explicit absolute paths; the pinned repository venv command produced the results above. The execution prompt contains the exact commands and additive formulas. Full-xdist warning totals are provenance-based, not a reusable scalar budget: no warning may originate from an AD-1125 changed/new path, and every additional family must be independently explained.

---

## Acceptance criteria

1. An initialized AD-1124 parent resolves its exact bound room once and transitions `discussing -> executing` through `CrewSessionService` before the first child tool call.
2. Every child receives the same exact non-empty `thread_id` plus only `_crew_session_id` and `_crew_work_item_id` in extra context.
3. A real `run_python` call stages an existing room input when enabled and persists a new ArtifactStore row plus AttachmentStore bytes in that same room.
4. The second scripted LLM request contains the real tool result, including authoritative artifact id/hash/thread id; the final child text is produced only by that later LLM turn.
5. `CodeExecutionTool.artifact_details` uses the exact seven-key DD-5 shape and values from the persisted Artifact row; the existing names list and all other output behavior remain compatible.
6. `WorkItemAgenticOutcome.total_tokens` equals the loop total and its artifact refs are exact, bounded, detached, same-thread, and derived from structured tool results.
7. Every terminal child persists the exact fourteen-key `crew_execution` record, cumulative `WorkItem.actual_tokens`, and validated status through one row-locked commit.
8. Complete reaches `done`; error/max-iterations/token-budget/execution exception reach `failed`; unassigned/unresolvable/start-transition/dependency-blocked reach `blocked`; no terminal execution silently remains `in_progress`.
9. Every dependency-blocked child is returned with exact unresolved dependency ids and cannot unblock descendants; independent siblings still run.
10. `max_parallel_subtasks` remains a hard concurrency ceiling; task references remain held; cancellation propagates and cleans up.
11. Existing room resolution works with auto-create off. Duplicate task rooms and contract/room mismatch fail before execution. Legacy eligible creation still uses AD-918 and propagates the returned thread id.
12. A durable `crew_session` returns after fan-out with `completed=False`, parent fine state `executing`, generic status `in_progress`, and zero verifier/synth calls. AD-1126 remains wholly unbuilt.
13. Every legacy non-session orchestrator test retains the existing promotion, verifier, synthesizer, trust/episode behavior, and completion result.
14. `merge_work_item_metadata(..., actual_tokens_delta=...)` is exact-int, overflow-safe, runtime-local, atomic with metadata/status, cancellation-safe, and byte-equivalent for all existing zero-delta callers.
15. No schema/table/column/index, config model, tracked YAML, runtime attribute, AgenticLoop/tool-call protocol, CrewSession API, verifier, synthesizer, Artifact/Attachment/Thread store, group-chat service, DmReplyPipeline, EventLog, trust, notifier, HXI, API, or dependency changes.
16. All new public fields/method parameters have complete modern annotations. Logs include child/parent id, what failed, why it matters, and what happens next without result/tool/blob content.
17. The new test module uses real stores/substrate and a scripted multi-iteration LLM; it contains no `MagicMock`, `Mock`, `AsyncMock`, or mock patching.
18. Focused, caller, blast, and full gates meet the execution-prompt formulas; changed-path warnings are zero and every parallel failure is serially triaged.
19. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## What this does not change

- No convergence rerun, child verification persistence, parent criteria evaluation, final synthesis acceptance, final result artifact, or `executing -> verifying -> done/failed` (AD-1126).
- No background lifecycle runner, scheduling gate, restart recovery, cancellation API, admission close, or shutdown drain (AD-1127).
- No Captain/agent ingress, semantic dedup, provisioning transaction, resume counter, or room repair (AD-1128).
- No EventLog tool or endpoint (AD-1129).
- No trust/Hebbian/conversation policy (AD-1130).
- No notifier, delivery metric, or new event type (AD-1131).
- No HXI/API projection, passive-rail removal, or live refresh (AD-1132/1133).
- No DmReplyPipeline marker execution, second orchestration engine, second session store, or bus blob.
- No config/system edit or new budget policy.
- No commercial/pricing/enterprise content.
- No new AD/BF number beyond AD-1125.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD, `origin/main`, remote `main`, base subject, clean status shape, issue amendment, dependency state, or any pinned hash differs;
2. issue #1044 does not explicitly preserve the AD-1125/1126 boundary and session-only post-fan-out stop;
3. a file outside the allowlist must change;
4. `AgenticLoop`, `ToolCallResult`, `CrewSessionService`, verifier, synthesizer, Artifact/Attachment/Thread stores, group-chat service, runtime, config, YAML, API, UI, events, or protocols appear to require edits;
5. a durable session would create/select a replacement room instead of requiring the AD-1124 bound room;
6. a child status would be raw-written or a terminal run could remain `in_progress`;
7. token persistence cannot share the existing row-write lock/commit without schema or raw-connection work;
8. artifact refs require parsing a string representation, filename inference, or scanning unbounded tool output;
9. tool results are not present in the next real LLM request on the exact base;
10. session execution would invoke verifier/synthesizer or transition beyond `executing`;
11. legacy non-session orchestration behavior changes;
12. the new test module uses a mock substrate/store/service or passes without production edits;
13. a focused/serial regression persists outside AD-1125;
14. full-gate warnings arise from a changed/new path or an unexplained new family;
15. prompt archival changes either SHA-256;
16. the requested commit contains anything beyond AD-1125 and closeout;
17. any request to push or mutate GitHub appears.

---

## Verified against live codebase (2026-07-18)

- `PROGRESS.md:3` and `DECISIONS.md:13` - AD-1124 is shipped and is the top-level ceiling; BF-673 remains the BF ceiling.
- Git refs - local HEAD, tracked `origin/main`, and live remote `main` all equal `31c1b648a91bdf21c27aa577d2d6000c99f61051`; initial status is clean.
- GitHub read-only - #1041 OPEN, #1043 CLOSED, #1044 OPEN, #1045 OPEN.
- `crew_session.py:376` - landed `CrewSessionService`; `transition_session` requires `expected_revision` and owns projection writes.
- `crew_session.py:664-686` - every load/transition revalidates parent type/status and exactly one task-linked room.
- `crew_executor.py:84-168` - executor loads children, discards the room result, owns bounded dependency scheduling, and omits blocked pending children.
- `crew_executor.py:170-251` - child execution passes no room/context, returns unpersisted failure reasons, and leaves degraded runs nonterminal.
- `crew_executor.py:264-336` - current AD-925 helper checks auto-create before existing lookup, uses `limit=1`, and logs but discards `GroupChatCreateResult.thread`.
- `crew_orchestrator.py:311-337` - direct parent promotion occurs before assignment/executor; verifier and synthesizer always follow fan-out.
- `crew_orchestrator.py:340-382` - `_promote_parent` directly assigns/promotes generic parents.
- `crew_synth.py:282-319` - current synthesizer directly transitions the parent to `done`; AD-1126 must integrate this with session finalization.
- `agentic_loop.py:95-205` - loop counts response tokens, maps budget/error stops, executes tools, appends tool-result text, and performs the next LLM call.
- `agentic_dispatch.py:44-75` - `DispatchToolExecutor` inherits the public ToolExecutor post-hook seam and records denied tools.
- `agentic_dispatch.py:426-440` - current outcome has final text, stop reason, denied tools, and trace ref only.
- `agentic_dispatch.py:460-734` - `run` already accepts `thread_id`/`extra_context`, builds the loop context, and currently drops total tokens/structured tool results.
- `agentic_dispatch.py:737-781` - tool-call requests are persisted by content hash in AttachmentStore; bytes do not enter WorkItem metadata.
- `tools/executor.py:37-110` - synchronous post-hooks receive the real `ToolResult` after registry invocation.
- `code_execution_tool.py:137-199` - thread id reaches staging/capture and top-level output already includes `artifact_details`.
- `code_execution_tool.py:292-333` - `_capture_artifacts` writes AttachmentStore bytes, creates a real Artifact row, then returns only four non-identity fields.
- `artifacts/__init__.py:82-155` - `add_version` returns the authoritative Artifact id/thread/hash/version row.
- `workforce.py:609-672` - `WorkItem` already has `actual_tokens` and metadata.
- `workforce.py:1227-1260` - generic update shares the AD-1124 row lock but bypasses transition validation for raw status writes, so AD-1125 must not use it for status.
- `workforce.py:1368-1467` - landed merge owns exact metadata CAS, parent preconditions, validated status, one row lock, one commit, and events; it is the correct token-delta extension point.
- `workforce.py:1469-1514` - `transition_work_item` is the validated status authority for fallback failure transitions.
- `threads/agent_group_chat.py:46-51,174-229` - exact `GroupChatCreateResult` shape is `ok`, `thread`, `error`, `participants_added`; create returns the real `ChatThread`.
- `threads/__init__.py:204-310` - synchronous `ChatThreadStore` create/get/list supports `task_id`, `include_archived`, and `limit`.
- `startup/finalize.py:1716-1753` - CrewSessionService is wired first behind the existing orchestrator gate.
- `startup/finalize.py:1755-1870` - one WorkItemAgenticExecutor and CrewTaskExecutor feed one CrewOrchestrator; service is not yet injected.
- Existing real-store/test precedents: `test_ad1124_crew_session_contract.py`, `test_ad925_auto_task_room.py`, `test_ad1066_code_execution_tool.py`, `test_ad1074d_round_trip_edit.py`.
- Direct construction/caller audit: four production `WorkItemAgenticExecutor` construction sites (two cognitive-agent paths, startup crew wiring, delegation); three internal executor-run call sites (crew child, orchestrator fan-out, convergence rerun); one production CrewTaskExecutor construction site; all are included in focused/caller/blast gates or frozen by defaults.
- No active AD-1125 prompt, source, test, tracker entry, or implementation existed before this document.

---

## Three-pass Architect self-review

### Pass 1 - Requirements and issue reconciliation

**Verdict:** APPROVED WITH ONE REQUIRED PRE-BUILD GITHUB BODY AMENDMENT.

- Every requested behavior maps to a DD, build section, named test family, and acceptance item.
- The live call-order/projection conflict is corrected explicitly.
- Existing tool-result iteration is preserved and tested rather than rebuilt.
- AD-1126 finalization, AD-1127 lifecycle, ingress/dedup, EventLog, trust/notifier/HXI, and config work are fenced out.

### Pass 2 - Verify-first and technical consistency

**Verdict:** APPROVED.

- Every named class, method, signature, return shape, store field, context key, and startup seam was read on exact HEAD.
- Room identity comes from the real ChatThread or GroupChatCreateResult, and artifact identity comes from the real Artifact row.
- Structured tool evidence uses the existing post-hook boundary; AgenticLoop remains tool-agnostic and frozen.
- Child status/metadata/tokens share the landed store lock and validated transition; no schema/raw DB/new store is needed.
- The durable session path cannot reach the old direct synthesizer completion before AD-1126.

### Pass 3 - Scope, safety, and execution readiness

**Verdict:** APPROVED FOR BUILDER AFTER ISSUE AMENDMENT.

- The dependency is landed and the next AD boundary is confirmed from live issue #1045.
- Exact base/hash/allowlist, red-first real-substrate tests, additive baselines, hard stops, tracker/archive/commit order, no-push, and no-GitHub rules are pinned.
- Legacy task orchestration remains the regression oracle.
- Bounded refs/summaries/context preserve the AD-731 refs-not-blobs rule.

## Pre-dispatch checklist

- [x] Current highest verified: AD-1124 / BF-673; AD-1125 is unused and sequential.
- [x] Correct OSS repository and boundary.
- [x] Issues #1041, #1043, #1044, and #1045 read live; dependency closed.
- [x] Parent rolling-week report and BF-673 root-cause report read.
- [x] AD-1124 prompt, execution prompt, decision, implementation, service tests, and final gate result read.
- [x] Every concrete API/path/signature/return shape verified against exact live base.
- [x] Room/service/orchestrator call-order conflict resolved.
- [x] Exact child evidence/artifact/context allowlists and bounds specified.
- [x] Every build item maps to acceptance/tests; public additions have boundary coverage.
- [x] Real SQLite, real room/artifact/attachment stores, scripted multi-turn LLM, and no-MagicMock-substrate rules specified.
- [x] Existing default-off gate reused; no config/YAML addition.
- [x] Exact do-not-build and hard-stop fences present.
- [x] Full annotations, log quality, async cancellation/task refs, layer discipline, and compliance line present.