# BF-900: the dispatch claim no longer undoes a park made in the same run

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21

**Status:** build-ready. **Closes #1573.** **Tier HIGH** (a governance path: a parked work item waits on a Captain decision). **Base:** `origin/main` `8c8bc4415e6279a22ffe2151cbd6cbc81b993691`. **Batch:** item 1 of 3 (BF-900, then BF-901 S1 `prompts/bf-901-s1-shared-estimator-and-usage-presence.md`, then BF-901 S2 `prompts/bf-901-s2-journal-token-provenance.md`), one broad gate for the batch. **Dependencies:** none. **Source:** the Architect's consult of 2026-10-21 (13:58Z), re-verified on this tree (section 11); section 2 lists where this contract departs from it.

**Tests:** the one statement of the count is section 6: 7 new test cases in one new file, 1 assertion added to an existing test, 4 test fakes changed.

**Line endings:** every edited file's working copy is CRLF (`git ls-files --eol`: `i/lf w/crlf`). The SEARCH blocks are written with LF; match and write with the file's own line endings.

---

## 1. Problem

`CognitiveAgent._handle_work_item_dispatch` (`src/probos/cognitive/cognitive_agent.py:2129`) runs the work item through `_run_agentic_dispatch` (`:2222`). For each tool the run was denied, `_run_agentic_dispatch` calls `gap_driver.on_capability_gap(...)` (`:2390-2396`), which files a request and parks the item through `CapabilityGapDriver.block_on_request` (`capability_gap_driver.py:135`): `open -> blocked`, with `blocked_reason` and `capability_request_id` in the same write (`:175-178`).

After the run, the AD-839 claim moves the item to `in_progress` with no expected status (`cognitive_agent.py:2289-2292`):

```python
            try:
                await store.transition_work_item(
                    work_item_id, "in_progress", source=self.id,
                )
```

`blocked -> in_progress` is legal for a `task` (`workforce.py:195`), so the parked item moves back. When the request is fulfilled, the driver acts only on a `blocked` item (the BF-878 guard, `capability_gap_driver.py:273-278`), finds it `in_progress` and does nothing. The item is never resumed or re-dispatched and keeps a `blocked_reason` and `capability_request_id` naming a request that is still open. `transition_work_item` already takes `expected_status` and checks it inside the write transaction (`workforce.py:10716-10718`, `:10747`, `:10754`); the claim does not use it. The return value of the claim is ignored, so a refused move is silent.

The test that should have caught it, `test_ad856_agentic_dispatch.py::test_run_agentic_dispatch_tool_denied_surfaces_capability_gap` (`:217`), uses `_FakeGapDriver` (`:108`), which parks nothing.

## 2. Solution overview

The claim becomes a compare-and-set on the status the BF-607 read returned:

1. `current = None` before the BF-607 `try`, so a read that raises or finds no item leaves it `None`.
2. `read_status = current.status if current is not None else None`.
3. `read_status is None`: no transition; a warning says the item could not be read and was not moved. There is no fallback to the unconditional move (on a store fault that fallback would bring the defect back).
4. `read_status == "blocked"`: no transition; an INFO line says the item stays parked for the request it waits on.
5. Otherwise: `transition_work_item(..., expected_status=read_status)`. A `None` result (the store refused: the status changed since the read, the move is illegal from that status, or the item is gone; `workforce.py:10750-10755`, `:10784-10788`) logs a warning that names the status that was read. The warning is in the `try`'s `else:` arm, so the AD-839 `except` still covers exactly the one call it covered before.

Where this contract departs from the consult:

- **The reconciler route.** The consult's blind spot said the reconciler's dead-assignee branch (`work_reconciler.py:148`) leads to `quartermaster.py:405-415`, which re-dispatches. On this tree those files are `src/probos/cognitive/work_reconciler.py` and `src/probos/agents/quartermaster.py`, and the quartermaster scans only `open` and `in_progress` items (`agents/quartermaster.py:164-165`, `:441-442`), so it does not hand the router an item that is `blocked` when it scans. The blind spot stands in a narrower form (section 9): a dispatch whose dict was read before a park, or a park made by another agent's run, reaches this claim with the item already `blocked`.
- **Three `_FakeGapDriver` copies exist**, not two: `test_ad856_agentic_dispatch.py:108`, `test_ad1328_s2c_park_and_scope.py:156` and `test_ad859a_agentic_executor.py:100`. The third serves executor tests that never reach `_handle_work_item_dispatch` (section 12, Absence Verified), so only the first two get the inline note.
- **The fakes to update** are four, not three: besides `test_ad839_work_item_dispatch.py:64-93` and `test_ad856_agentic_dispatch.py:350-355`, the `_FakeGapDriver` notes above. `test_bf773_failure_reaches_the_captain.py:65-76` needs no change (section 5).

## 3. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | The claim moves the item only from the status the BF-607 read returned (`expected_status=read_status`) | An unconditional move (the defect). A second `get_work_item` just before the move: the race moves to between the two reads; only the store's in-transaction check closes it |
| D2 | A `blocked` item is not moved | Passing `expected_status="blocked"`: that is a legal `blocked -> in_progress` and is the defect itself. Refusing `blocked -> in_progress` in the store for callers other than the driver: forbidden by Do Not Build (the transition table) |
| D3 | A `None` read (raised or no item) moves nothing, with a warning | Falling back to the unconditional move: a store fault would reintroduce the defect |
| D4 | A `None` result logs a warning naming the status read, at the tier of the claim's existing warning (log-and-degrade) | Raising: the handler's contract is Tier-2 log-and-degrade (`:2139-2141`); silent, as today: a refused claim is an event the Captain may need to see |
| D5 | The `None`-result check sits in the `try`'s `else:` arm | Inside the `try`: the AD-839 `except` would then also cover the check; it covers only the store call today |
| D6 | `CapabilityGapDriver`, the BF-878 guard, `block_on_request`, the transition table, the router and the reconciler are unchanged | Making `block_on_request` a compare-and-set to stop a later park overwriting an earlier one (crosses Do Not Build; section 9, item 2) |

## 4. Milestones (about 40 Builder tool calls in all)

| M | Work | Focused check (`-n 0`, the orchestrator's worktree environment: `PYTHONPATH=<tree>/src`) |
|---|---|---|
| M1 (about 6 calls) | Section 7.1 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad839_work_item_dispatch.py tests/test_bf773_failure_reaches_the_captain.py tests/test_ad1248_slice_a_gaps.py -n 0 -q` (red at `test_handler_transitions_and_threads_messages` until M2: the fake item has no `status`) |
| M2 (about 8 calls) | Sections 7.2 to 7.4 (the four fakes) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad839_work_item_dispatch.py tests/test_ad856_agentic_dispatch.py tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1328_s2c_resume_seam.py tests/test_ad1275_sink_side_composition.py tests/test_bf773_failure_reaches_the_captain.py -n 0 -q` |
| M3 (about 14 calls) | Section 7.5 (the new test file) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf900_dispatch_claim_keeps_the_park.py -n 0 -q`, then the M2 command again, then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_seam_registry.py tests/test_ad855_block_resume.py tests/test_bf878_settled_request_resumes_the_item.py -n 0 -q` |
| M4 (about 7 calls) | Section 8: `PROGRESS.md`, `DECISIONS.md`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` | `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -n 0 -q` |
| M5 (about 4 calls) | Section audit against this contract; stage by explicit path: `src/probos/cognitive/cognitive_agent.py`, `tests/test_ad839_work_item_dispatch.py`, `tests/test_ad856_agentic_dispatch.py`, `tests/test_ad1328_s2c_park_and_scope.py`, `tests/test_bf900_dispatch_claim_keeps_the_park.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` (never `git add -A`) | `git diff --cached --stat` |

`tests/test_ad855_block_resume.py` is the driver's own suite (the driver is unchanged; it is a consumer check only). Then the orchestrator: the scratch-tree dry run of this whole contract, the mutation rows (section 10), review, the local commit, then BF-901 S1.

## 5. Consumers of the changed value (the claim's transition)

The value that changes: after a run, the claim no longer writes `in_progress` over `blocked`, no longer writes when the read failed, and no longer moves an item whose status changed after the read. Grep run: `Grep "_handle_work_item_dispatch" tests/ src/`, `Grep "WORK_ITEM_STATUS_CHANGED|work_item_status_changed" src/probos/ ui/src/`, `Grep "\.dispatch_work_item\(|on_work_item_created\(" src/probos/`.

| Consumer | What it does with the new value | Pre-existing on the base, or added here |
|---|---|---|
| `CapabilityGapDriver.on_capability_event` (`capability_gap_driver.py:229-289`) | Finds the item still `blocked` on its request, so the BF-878 guard (`:273-278`) lets FULFILLED resume it (`_resume`, `:291-314`, compare-and-set on `blocked` and the request id) and DECIDED/denied cancel it | Added: this is the fix |
| `park_on_command_escalation` (`command_escalation_park.py:91-140`), called after the claim (`cognitive_agent.py:2306`) | With no gap park: the claim moves `open -> in_progress` as before and the command park moves `in_progress -> blocked` (P-S1, `test_ad1328_s2c_resume_seam.py:561`, unchanged). With a gap park in the same run: the claim skips, the command park writes `blocked -> blocked` with its metadata (`workforce.py:10781-10800`), last writer wins | The end state is the base's in both cases; T3 pins the second |
| `WorkItemStore` WORK_ITEM_STATUS_CHANGED listeners: crew-session delivery (`startup/finalize.py:2416-2422`, `crew_session_delivery.py:515`), task completion notifier (`startup/finalize.py:3372-3392`; acts only on `done`/`failed`, `task_completion_notifier.py:29`, `:40`), standing interests (`startup/finalize.py:3837`), event persistence (`event_persistence.py:77`), the WebSocket stream (`ws_event_stream.py:61`) and the UI store (`ui/src/store/useStore.ts`) | A parked item emits one `open -> blocked` and, later, the driver's `blocked -> in_progress`, instead of `open -> blocked`, `blocked -> in_progress` (claim), then nothing. Each consumer handles any status value; none treats the claim's event specially | Added: one event fewer per parked item |
| The board (`routers/workforce.py` via the store) | Shows `blocked` with the request while the item waits | Added (the issue's acceptance) |
| `WorkItemRouter.dispatch_work_item` (`mesh/work_item_router.py:68`), callers `agents/quartermaster.py:316`, `:415`, `capability_gap_driver.py:352`, `mesh/work_item_router.py:187` | Unchanged: none reads the claim. `is_dispatchable` checks tags and metadata only (`mesh/work_item_router.py:59-66`) | Pre-existing; section 9, item 1 |
| `test_bf773_failure_reaches_the_captain.py:65-76` (`get_work_item` returns `None`) | The claim now moves nothing and logs the BF-900 read warning; no test asserts on `transitions` there (`Grep "transitions" tests/test_bf773_failure_reaches_the_captain.py` finds only `:67`, `:75`) | Added; no edit needed |
| `test_ad1275_sink_side_composition.py:584-590` | `work_item_store = None`: the claim block is skipped, as before | Unchanged |
| Source scans of the handler: `test_ad1248_slice_a_gaps.py:245` (`failures_sink=_dispatch_failures`, `_body = str(_composed.render())`, `body=_body,`), `:374` (`and _body:`, `result=_body or reply_text or "[NO_RESPONSE]"`), `test_bf773_failure_reaches_the_captain.py:13` (a docstring) | None pins a claim line; none of those strings changes | Unchanged |

## 6. Tests

| ID | File :: test | What it proves |
|---|---|---|
| T1 | `tests/test_bf900_dispatch_claim_keeps_the_park.py::test_a_denied_tool_leaves_the_item_parked_and_its_grant_resumes_it_once` | The issue's seam with real stores and the real driver: after a run whose tool is denied, the item is `blocked` on the pending gap request, `assigned_to` is the agent (BF-607 unchanged), the only status move is `open -> blocked`, nothing is re-dispatched; `mark_fulfilled` then produces exactly one `blocked -> in_progress` and one re-dispatch of this item |
| T2 | `...::test_a_run_with_no_denial_still_claims_the_item` | The control: the same rig, no denial: `open -> in_progress` once, no request, no re-dispatch |
| T3 | `...::test_a_command_park_after_a_gap_park_in_one_run_ends_on_the_command_request` | The S2c assertion: the `blocked` skip does not suppress the command park. One run, a gap park and then the command park: the item ends `blocked` on the command request with the command reason; the only status move is `open -> blocked`; both requests stay pending (the gap request with no item parked on it, as on the base) |
| T4 | `...::test_a_move_made_after_the_read_is_not_undone` | The compare-and-set: the real store, and another writer parks the item between the claim's read and its move; the item stays `blocked`, and the warning names the item and the status read (`'open'`) |
| T5a, T5b | `...::test_an_item_that_cannot_be_read_is_not_moved[raises]`, `[missing]` | A read that raises, and a read that finds no item: no transition is attempted, and a BF-900 warning names the item |
| T6 | `...::test_an_item_parked_before_the_run_stays_parked` | Section 9, item 1, pinned: an item parked before this agent's run stays `blocked` on its earlier request after a clean run; `assigned_to` is still claimed |
| E1 | `tests/test_ad839_work_item_dispatch.py::test_handler_transitions_and_threads_messages` (one assertion added) | The claim passes the status it read: `expected_statuses == ["open"]` |

Changed fakes (no new test): `tests/test_ad839_work_item_dispatch.py` `_FakeWorkItem` (gains `status`) and `_FakeWorkItemStore.transition_work_item` (takes and records `expected_status`); `tests/test_ad856_agentic_dispatch.py` `_WorkItemStore` in `test_handle_work_item_dispatch_falls_back_when_gated_off` (gains `get_work_item`, takes `expected_status`); the `_FakeGapDriver` notes in `tests/test_ad856_agentic_dispatch.py` and `tests/test_ad1328_s2c_park_and_scope.py`.

Consumer tests run unchanged (M2, M3): `tests/test_ad1328_s2c_resume_seam.py` (P-S1 to P-S4 drive this handler with real stores; P-S1's park now follows a compare-and-set claim from `open`), `tests/test_ad1328_s2c_park_and_scope.py`, `tests/test_ad1275_sink_side_composition.py`, `tests/test_bf773_failure_reaches_the_captain.py`, `tests/test_ad1248_slice_a_gaps.py`, `tests/test_ad1343_seam_registry.py`, `tests/test_bf878_settled_request_resumes_the_item.py`.

**Platform.** Every new test runs on SQLite files in `tmp_path`, with the command gate pinned to `platform="linux"` and a `which` that finds nothing (copied from `test_ad1328_s2c_park_and_scope.py:111-125`); none starts a process. The outcome cannot differ on POSIX (CI: `ubuntu-latest`, Python 3.12).

## 7. The contract

### 7.1 `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```python
            try:
                current = await store.get_work_item(work_item_id)
                if current is not None and not current.assigned_to:
                    await store.update_work_item(work_item_id, assigned_to=self.id)
            except Exception:
                logger.warning(
                    "BF-607: failed to claim work_item %s for agent %s; "
                    "it remains unassigned",
                    work_item_id, self.id, exc_info=True,
                )
            try:
                await store.transition_work_item(
                    work_item_id, "in_progress", source=self.id,
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to transition work_item %s to in_progress; "
                    "it remains in its prior status",
                    work_item_id, exc_info=True,
                )
```
REPLACE:
```python
            # BF-900 (#1573): ``current`` stays None when this read raises or finds no item.
            current = None
            try:
                current = await store.get_work_item(work_item_id)
                if current is not None and not current.assigned_to:
                    await store.update_work_item(work_item_id, assigned_to=self.id)
            except Exception:
                logger.warning(
                    "BF-607: failed to claim work_item %s for agent %s; "
                    "it remains unassigned",
                    work_item_id, self.id, exc_info=True,
                )
            # BF-900 (#1573): the claim moves the item only from the status read above; the store
            # checks it inside its write transaction (``expected_status``). So a park made earlier in
            # this run (``on_capability_gap`` in ``_run_agentic_dispatch``), or a move another writer
            # made after the read, is not undone. A blocked item is left for the request it waits on.
            read_status = current.status if current is not None else None
            if read_status is None:
                logger.warning(
                    "BF-900: work_item %s could not be read before the claim; it is not moved "
                    "to in_progress and remains in its prior status",
                    work_item_id,
                )
            elif read_status == "blocked":
                logger.info(
                    "BF-900: work_item %s is blocked; the claim leaves it parked for the "
                    "request it waits on",
                    work_item_id,
                )
            else:
                try:
                    claimed = await store.transition_work_item(
                        work_item_id, "in_progress", source=self.id,
                        expected_status=read_status,
                    )
                except Exception:
                    logger.warning(
                        "AD-839: failed to transition work_item %s to in_progress; "
                        "it remains in its prior status",
                        work_item_id, exc_info=True,
                    )
                else:
                    if claimed is None:
                        logger.warning(
                            "BF-900: work_item %s was not moved to in_progress: it was %r when "
                            "read, and the store refused the move (its status changed since the "
                            "read, the move is not allowed from that status, or the item is gone)",
                            work_item_id, read_status,
                        )
```

**What each `try` covers** (BF-911's F6 lesson). The BF-607 `try`: on the base and here, `get_work_item` and `update_work_item`; `current = None` precedes it. The AD-839 `try`: on the base and here, the one `transition_work_item` call; the `None` check is in `else:`, outside its handler. New statements outside any `try`: `current = None`, `read_status = ...` (an attribute read on a `WorkItem`, whose `status` field is `workforce.py:949`; `WorkItemStore.get_work_item` returns `WorkItem | None`, `workforce.py:7740`), two comparisons and three logger calls. A store whose `get_work_item` returns an object without `status` would now raise out of the handler; the stores that reach it are `WorkItemStore` and the test fakes in section 7.2 and 7.3.

### 7.2 `tests/test_ad839_work_item_dispatch.py`

SEARCH:
```python
class _FakeWorkItem:
    def __init__(self, work_item_id: str, assigned_to: str | None = None) -> None:
        self.id = work_item_id
        self.assigned_to = assigned_to
```
REPLACE:
```python
class _FakeWorkItem:
    def __init__(self, work_item_id: str, assigned_to: str | None = None) -> None:
        self.id = work_item_id
        self.assigned_to = assigned_to
        # BF-900: the claim reads the status and moves the item only from it (a compare-and-set),
        # so the fake item carries one; ``open`` is a dispatched task's status before the claim.
        self.status = "open"
```

SEARCH:
```python
        self.transitions: list[tuple[str, str, str]] = []
        self.raise_on_transition = False
        # BF-607: track assignment so the claim path can be exercised.
```
REPLACE:
```python
        self.transitions: list[tuple[str, str, str]] = []
        # BF-900: the ``expected_status`` each claim passed, in order.
        self.expected_statuses: list[str | None] = []
        self.raise_on_transition = False
        # BF-607: track assignment so the claim path can be exercised.
```

SEARCH:
```python
    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system"
    ) -> Any:
        if self.raise_on_transition:
            raise RuntimeError("invalid transition")
        self.transitions.append((work_item_id, new_status, source))
        return MagicMock()
```
REPLACE:
```python
    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
        *, expected_status: str | None = None,
    ) -> Any:
        if self.raise_on_transition:
            raise RuntimeError("invalid transition")
        self.transitions.append((work_item_id, new_status, source))
        self.expected_statuses.append(expected_status)
        return MagicMock()
```

SEARCH:
```python
    # transitioned to in_progress with the agent as source
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]
```
REPLACE:
```python
    # transitioned to in_progress with the agent as source
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]
    # BF-900: only from the status the claim read, so a park made since is not undone
    assert work_item_store.expected_statuses == ["open"]
```

### 7.3 `tests/test_ad856_agentic_dispatch.py`

SEARCH:
```python
class _FakeGapDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
```
REPLACE:
```python
class _FakeGapDriver:
    """Records each gap and parks nothing. BF-900: so no test with it can show the dispatch claim undoing
    a park; ``tests/test_bf900_dispatch_claim_keeps_the_park.py`` runs the real ``CapabilityGapDriver``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
```

SEARCH:
```python
    class _WorkItemStore:
        async def transition_work_item(
            self, work_item_id: str, new_status: str, source: str = "system"
        ) -> Any:
            transitions.append((work_item_id, new_status, source))
            return None
```
REPLACE:
```python
    class _WorkItemStore:
        # BF-900: the claim reads the item and moves it only from the status it read
        # (``expected_status``), so this fake answers the read (an open item the agent already
        # holds) and takes the keyword.
        async def get_work_item(self, work_item_id: str) -> Any:
            return SimpleNamespace(id=work_item_id, status="open", assigned_to="counselor-001")

        async def transition_work_item(
            self, work_item_id: str, new_status: str, source: str = "system",
            *, expected_status: str | None = None,
        ) -> Any:
            transitions.append((work_item_id, new_status, source))
            return SimpleNamespace(id=work_item_id, status=new_status)
```

### 7.4 `tests/test_ad1328_s2c_park_and_scope.py`

SEARCH:
```python
class _FakeGapDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
```
REPLACE:
```python
class _FakeGapDriver:
    """Records each gap and parks nothing. BF-900: so no test with it can show the dispatch claim undoing
    a park; ``tests/test_bf900_dispatch_claim_keeps_the_park.py`` runs the real ``CapabilityGapDriver``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
```

### 7.5 New file

#### `tests/test_bf900_dispatch_claim_keeps_the_park.py`

```python
"""BF-900 (#1573): the dispatch claim does not undo a park made earlier in the same run.

The contract is ``prompts/bf-900-dispatch-claim-keeps-the-park.md``. ``CognitiveAgent._handle_work_item_dispatch``
claims the item after the run (AD-839). When the run was denied a tool, ``_run_agentic_dispatch`` has already parked
the item ``blocked`` on a capability request (AD-855); the claim used to move it straight back to ``in_progress``,
so the grant found it not blocked and never resumed it (BF-878's guard). The claim is now a compare-and-set on the
status it read.

Real: ``WorkItemStore``, ``CapabilityRequestStore`` (emitting through ``_EventBus``), ``ToolPermissionStore``,
``ToolRegistry`` (a tool only the captain rank may use), ``CapabilityGapDriver`` (subscribed to the bus),
``CommandPolicyGate``, ``build_command_escalations`` and ``SqliteCommandApprovalStore`` (T3), a ``CognitiveAgent``
built as test_ad856's ``_make_agent``, and the dispatch path ``_handle_work_item_dispatch`` -> ``_run_agentic_dispatch``
-> ``WorkItemAgenticExecutor``. Stand-ins, named: the model (``_ScriptedLLM``), the router (``_RecordingRouter``), the
event bus (``_EventBus``), the thread store (``_ThreadStore``); in T4 one concurrent writer (``_RacedStore``) and in T5
an unreadable store. The store records no ``source`` for a move (``transition_work_item`` does not read it), so "the
driver resumed it" is shown by the router's hand-back, which only the driver makes here.

Mutants (the contract's section 10): B1 is killed by T1 (and T3), B2 by T4, B3 by T5, B4 by T4.

Helpers are copies, because tests do not import each other: tests/test_ad1328_s2c_resume_seam.py (``_RecordingRouter``,
``_EventBus``, ``_EventLog``, ``_Runtime``, ``_ThreadStore``, ``_FakeLLMResponse``, ``_ScriptedLLM``, ``_text_response``,
``_make_agent``), tests/test_ad1328_s2c_park_and_scope.py (``_policy``, ``_rule``, ``_Which``, ``_gate``, the filing in
``_file``) and tests/test_ad856_agentic_dispatch.py (``_FakeTool``, ``_tool_use_response``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.command_escalation_park import COMMAND_ESCALATION_BLOCKED_REASON
from probos.config_models.operations import CommandPolicyConfig
from probos.events import EventType
from probos.execution.command_approvals import SqliteCommandApprovalStore
from probos.execution.command_escalation import (
    DISPATCHED_WORK_ITEM_KEY,
    CommandEscalations,
    build_command_escalations,
)
from probos.execution.command_gate import CommandPolicyGate
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult
from probos.workforce import WorkItemStore

AGENT = "counselor-001"
RESTRICTED = "restricted_tool"
PUSH = "git push origin"
CA_LOGGER = "probos.cognitive.cognitive_agent"

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    # pydantic's model_validate (not a ProbOS method) builds the policy from a dict
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


_ASK_PUSH = _rule("ask-push", ["git", "push"], "escalate", justification="a push publishes work outside this session")


class _Which:
    """A recording program lookup: it never reads the real PATH and finds nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> None:
        self.calls.append((name, path))
        return None


def _gate(config: CommandPolicyConfig) -> CommandPolicyGate:
    return CommandPolicyGate(config, platform="linux", which=_Which(), is_file=lambda path: False)


class _FakeTool:
    """Real Tool-protocol implementation that counts invocations."""

    def __init__(self, tool_id: str) -> None:
        self._tid = tool_id
        self.invocations = 0

    @property
    def tool_id(self) -> str:
        return self._tid

    @property
    def name(self) -> str:
        return self._tid

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"Fake tool {self._tid}"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        self.invocations += 1
        return ToolResult(output="ok")


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    """Returns the queued responses in order; counts its calls. A call past the script answers ``done``."""

    def __init__(self) -> None:
        self._responses: list[_FakeLLMResponse] = []
        self.calls = 0

    def queue(self, *responses: _FakeLLMResponse) -> None:
        self._responses.extend(responses)

    async def complete(self, req: Any, **_kwargs: Any) -> _FakeLLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _tool_use_response(tool_id: str) -> _FakeLLMResponse:
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    block = ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments={}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _make_agent(*, llm: Any, runtime: Any) -> Any:
    """Build a minimal CognitiveAgent without running __init__ (tests/test_ad856_agentic_dispatch.py)."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = AGENT
    agent.callsign = "Ezri"
    agent.department = "counseling"
    agent.rank = "ensign"
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = llm
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


class _RecordingRouter:
    """Stub WorkItemRouter that records re-dispatch calls (AD-855's shape)."""

    def __init__(self) -> None:
        self.dispatched: list[dict[str, Any]] = []

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        self.dispatched.append(event)

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        self.dispatched.append({"type": "work_item_created", "data": {"work_item": wi}})
        return True

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return True


class _EventBus:
    """``emit`` is synchronous and spawns a task per listener while holding the reference (BF-639)."""

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        event = {"type": type_str, "data": dict(data or {}), "timestamp": time.time()}
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            pending = tuple(self._tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._tasks.difference_update(task for task in pending if task.done())


class _EventLog:
    """``log`` answers a positive row id, which the dispatch run's AD-1224 hooks count as acknowledged."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "", **_kw: Any) -> int:
        self.events.append((category, event))
        return len(self.events)


class _Runtime(SimpleNamespace):
    """Exactly the attributes the dispatch run, the driver and the park read."""


class _ThreadStore:
    """Stands in for the chat thread store: the one default thread the handler writes to."""

    def __init__(self) -> None:
        self.thread = SimpleNamespace(id="thread-1")
        self.messages: list[dict[str, Any]] = []

    def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> Any:
        return self.thread

    def append_message(
        self, thread_id: str, *, author_id: str, role: str, body: str, metadata: dict | None = None, **_kw: Any,
    ) -> None:
        self.messages.append({"thread_id": thread_id, "author_id": author_id, "role": role, "body": body})


class _Transitions:
    """The work-item store's ``emit_event``: every status move, in order, as (item id, old, new)."""

    def __init__(self) -> None:
        self.moves: list[tuple[str, str, str]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        if event_type == EventType.WORK_ITEM_STATUS_CHANGED:
            self.moves.append((data["work_item"]["id"], data["old_status"], data["new_status"]))

    def of(self, item_id: str) -> list[tuple[str, str]]:
        return [(old, new) for wid, old, new in self.moves if wid == item_id]


class _Wired:
    def __init__(self, **parts: Any) -> None:
        self.__dict__.update(parts)


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[_Wired]:
    transitions = _Transitions()
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), emit_event=transitions, tick_interval=1000)
    await work_items.start()
    bus = _EventBus()
    requests = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=bus.emit, trust_network=MagicMock())
    await requests.start()
    perms = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    await perms.start()
    registry = ToolRegistry()
    restricted = _FakeTool(RESTRICTED)
    # Captain-only: an ensign resolves to no access, so the call raises ToolPermissionDenied (test_ad856:217).
    registry.register(restricted, provider="test", default_permissions={"captain": "full"})
    registry.set_permission_store(perms)
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        event_log=_EventLog(),
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        intent_bus=None,
        emit_event=None,
        tool_registry=registry,
        tool_permission_store=perms,
        chat_thread_store=_ThreadStore(),
    )
    driver = CapabilityGapDriver(runtime=runtime, work_item_store=work_items, capability_request_store=requests)
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    llm = _ScriptedLLM()
    try:
        yield _Wired(
            runtime=runtime, driver=driver, router=router, bus=bus, work_items=work_items, requests=requests,
            transitions=transitions, restricted=restricted, llm=llm, agent=_make_agent(llm=llm, runtime=runtime),
        )
    finally:
        await bus.drain()
        await perms.stop()
        await requests.stop()
        await work_items.stop()


async def _task(wired: _Wired, title: str, *, assigned_to: str | None = None) -> Any:
    item = await wired.work_items.create_work_item(
        title=title, description=title, work_type="task", assigned_to=assigned_to, created_by="captain",
    )
    assert (await wired.work_items.get_work_item(item.id)).status == "open"  # premise
    return item


async def _dispatch(wired: _Wired, item: Any, *script: _FakeLLMResponse) -> IntentResult:
    """One run of ``item`` through the real handler, as the router's hop builds it (``mesh/work_item_router.py``)."""
    calls_before = wired.llm.calls
    wired.llm.queue(*script)
    intent = IntentMessage(
        intent="work_item_dispatched",
        params={"work_item_id": item.id, "title": item.title, "description": item.description},
        target_agent_id=AGENT,
    )
    result = await wired.agent._handle_work_item_dispatch(intent)
    assert wired.llm.calls - calls_before == len(script), "premise: the run made exactly the scripted calls"
    return result


async def _current(wired: _Wired, item: Any) -> Any:
    current = await wired.work_items.get_work_item(item.id)
    assert current is not None
    return current


def _bf900_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage() for rec in caplog.records
        if rec.name == CA_LOGGER and rec.levelno == logging.WARNING and rec.getMessage().startswith("BF-900")
    ]


# --------------------------------------------------------------------------------------
# The seam (the issue's reproduction, with no fake gap driver)
# --------------------------------------------------------------------------------------


async def test_a_denied_tool_leaves_the_item_parked_and_its_grant_resumes_it_once(wired: _Wired) -> None:
    """T1. Dispatch an item whose agent calls a tool its rank denies: the item is still ``blocked`` on the pending
    request (the claim did not undo the park), the agent holds it (BF-607), and nothing was re-dispatched. Fulfilling
    the request then produces exactly one ``blocked -> in_progress`` and one hand-back of this item to the router."""
    item = await _task(wired, "use the restricted tool")

    result = await _dispatch(wired, item, _tool_use_response(RESTRICTED), _text_response("Waiting for access."))

    assert result.success is True
    assert wired.restricted.invocations == 0  # premise: denied at the permission check, never run
    (req,) = [r for r in await wired.requests.list_pending() if r.work_item_id == item.id]
    assert req.target == RESTRICTED  # premise: the denial reached the driver and filed a request
    parked = await _current(wired, item)
    assert parked.status == "blocked"
    assert parked.metadata["capability_request_id"] == req.id
    assert parked.metadata["blocked_reason"] == RESTRICTED
    assert parked.assigned_to == AGENT  # BF-607's claim still assigns a parked item
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    assert wired.router.dispatched == []

    await wired.requests.mark_fulfilled(req.id)
    await wired.bus.drain()

    assert wired.transitions.of(item.id) == [("open", "blocked"), ("blocked", "in_progress")]
    assert [e["data"]["work_item"]["id"] for e in wired.router.dispatched] == [item.id]
    assert (await _current(wired, item)).status == "in_progress"


async def test_a_run_with_no_denial_still_claims_the_item(wired: _Wired) -> None:
    """T2, the control: the same rig and a clean run. The claim moves the item ``open -> in_progress`` as before."""
    item = await _task(wired, "a task with nothing denied")

    result = await _dispatch(wired, item, _text_response("Done."))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "in_progress"
    assert current.assigned_to == AGENT
    assert "capability_request_id" not in (current.metadata or {})
    assert wired.transitions.of(item.id) == [("open", "in_progress")]
    assert await wired.requests.list_pending() == []
    assert wired.router.dispatched == []


async def test_a_command_park_after_a_gap_park_in_one_run_ends_on_the_command_request(
    wired: _Wired, tmp_path: Path,
) -> None:
    """T3, the S2c assertion: the claim's ``blocked`` skip does not suppress AD-1328 S2c's command park, which runs
    after the claim. One run parks the item on a capability gap and then on a pending command escalation in its scope:
    the command park writes last (``blocked -> blocked`` with its metadata), so the item ends parked on the command
    request, the same end state as on the base, where the claim's ``in_progress`` came between the two parks. The gap
    request stays pending with no item parked on it (the contract's section 9, item 2)."""
    approvals = SqliteCommandApprovalStore(db_path=str(tmp_path / "command_approvals.db"))
    await approvals.start()
    try:
        gate = _gate(_policy(_ASK_PUSH))
        escalations = build_command_escalations(
            gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
        )
        assert isinstance(escalations, CommandEscalations)  # premise: the approval route is wired
        wired.runtime.command_escalations = escalations
        wired.runtime.command_approval_store = approvals
        item = await _task(wired, "push and use the restricted tool", assigned_to=AGENT)
        verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
        assert verdict.decision == "escalate"  # premise: the policy asks about this command
        outcome = await escalations.resolve(
            verdict, command=PUSH, context={"agent_id": AGENT, DISPATCHED_WORK_ITEM_KEY: item.id},
        )
        assert outcome.verdict.approval is not None and outcome.verdict.approval["state"] == "filed"
        command_request = outcome.verdict.approval["request_id"]
        assert (await _current(wired, item)).status == "open"  # premise: filing parks nothing

        result = await _dispatch(wired, item, _tool_use_response(RESTRICTED), _text_response("Waiting."))

        assert result.success is True
        pending = {r.id: r for r in await wired.requests.list_pending()}
        (gap_request,) = [r for r in pending.values() if r.target == RESTRICTED]  # premise: the gap park ran
        assert command_request in pending
        current = await _current(wired, item)
        assert current.status == "blocked"
        assert current.metadata["capability_request_id"] == command_request
        assert current.metadata["blocked_reason"] == COMMAND_ESCALATION_BLOCKED_REASON
        assert gap_request.id != command_request
        assert wired.transitions.of(item.id) == [("open", "blocked")]
    finally:
        await approvals.stop()


# --------------------------------------------------------------------------------------
# The compare-and-set and its degrade paths
# --------------------------------------------------------------------------------------


class _RacedStore:
    """The real store with one concurrent writer: after the claim's read returns, another run parks the item."""

    def __init__(self, real: WorkItemStore) -> None:
        self._real = real
        self._raced = False

    async def get_work_item(self, work_item_id: str) -> Any:
        item = await self._real.get_work_item(work_item_id)
        if not self._raced:
            self._raced = True
            parked = await self._real.transition_work_item(
                work_item_id, "blocked", source="another-run",
                metadata_patch={"blocked_reason": "another_run", "capability_request_id": "req-other"},
            )
            assert parked is not None  # premise: the concurrent park landed
        return item

    async def update_work_item(self, work_item_id: str, **updates: Any) -> Any:
        return await self._real.update_work_item(work_item_id, **updates)

    async def transition_work_item(self, *args: Any, **kwargs: Any) -> Any:
        return await self._real.transition_work_item(*args, **kwargs)


def _gated_off_agent(store: Any) -> Any:
    """The AD-839 single-shot path: the agentic run is off, ``handle_intent`` answers, then the claim runs."""
    runtime = SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=False)),
        work_item_store=store,
        chat_thread_store=None,
    )
    agent = _make_agent(llm=AsyncMock(), runtime=runtime)
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(intent_id="dm", agent_id=AGENT, success=True, result="On it.", confidence=0.5),
    )
    return agent


def _dispatch_intent(work_item_id: str) -> IntentMessage:
    return IntentMessage(
        intent="work_item_dispatched",
        params={"work_item_id": work_item_id, "title": "a task", "description": "a task"},
        target_agent_id=AGENT,
    )


async def test_a_move_made_after_the_read_is_not_undone(wired: _Wired, caplog: pytest.LogCaptureFixture) -> None:
    """T4. Another writer parks the item between the claim's read (``open``) and its move. The store's in-transaction
    check refuses the claim, the item stays ``blocked``, and the warning names the item and the status read."""
    caplog.set_level(logging.INFO, logger=CA_LOGGER)
    item = await _task(wired, "raced")
    agent = _gated_off_agent(_RacedStore(wired.work_items))

    result = await agent._handle_work_item_dispatch(_dispatch_intent(item.id))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "blocked"
    assert current.metadata["capability_request_id"] == "req-other"
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    warnings = _bf900_warnings(caplog)
    assert len(warnings) == 1
    assert item.id in warnings[0] and "'open'" in warnings[0]


class _UnreadableStore:
    """A store whose read raises or finds nothing; it records any move it is asked for."""

    def __init__(self, *, raises: bool) -> None:
        self._raises = raises
        self.transitions: list[tuple[str, str, str | None]] = []
        self.updates: list[str] = []

    async def get_work_item(self, work_item_id: str) -> Any:
        if self._raises:
            raise RuntimeError("store down")
        return None

    async def update_work_item(self, work_item_id: str, **updates: Any) -> Any:
        self.updates.append(work_item_id)
        return None

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system", *, expected_status: str | None = None,
    ) -> Any:
        self.transitions.append((work_item_id, new_status, expected_status))
        return SimpleNamespace(id=work_item_id, status=new_status)


@pytest.mark.parametrize("raises", [True, False], ids=["raises", "missing"])
async def test_an_item_that_cannot_be_read_is_not_moved(raises: bool, caplog: pytest.LogCaptureFixture) -> None:
    """T5. With no status read there is nothing to compare against, so no move is attempted (no unconditional
    fallback), and a BF-900 warning names the item."""
    caplog.set_level(logging.INFO, logger=CA_LOGGER)
    store = _UnreadableStore(raises=raises)
    agent = _gated_off_agent(store)

    result = await agent._handle_work_item_dispatch(_dispatch_intent("wi-unreadable"))

    assert result.success is True
    assert store.transitions == []
    assert store.updates == []
    warnings = _bf900_warnings(caplog)
    assert len(warnings) == 1
    assert "wi-unreadable" in warnings[0]


async def test_an_item_parked_before_the_run_stays_parked(wired: _Wired) -> None:
    """T6, the contract's section 9 item 1, pinned: an item already ``blocked`` when this agent's claim reads it (an
    earlier run's park) stays parked on its earlier request after a clean run, and the agent still claims it."""
    item = await _task(wired, "parked earlier")
    earlier = await wired.requests.file_request(
        agent_id="another-agent", kind="grant", target="another_tool", rationale="an earlier run", work_item_id=item.id,
    )
    assert await wired.driver.block_on_request(work_item_id=item.id, request_id=earlier.id, reason="another_tool")

    result = await _dispatch(wired, item, _text_response("Nothing to do."))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "blocked"
    assert current.metadata["capability_request_id"] == earlier.id
    assert current.assigned_to == AGENT
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    assert wired.router.dispatched == []
```

## 8. Tracking (tracker pairs)

**`PROGRESS.md`** (anchored on the first line and the blank line after it):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**BF-900 (2026-10-21), closes #1573 -- the dispatch claim no longer undoes a park made in the same run.** `CognitiveAgent._handle_work_item_dispatch`'s AD-839 claim moved a dispatched work item to `in_progress` with no expected status, after the run had already parked it `blocked` on a capability request (a denied tool, AD-855), so the grant found the item not blocked (BF-878's guard) and never resumed it. The claim now moves the item only from the status the BF-607 read returned (`expected_status`, checked inside the store's write transaction); it leaves a `blocked` item parked; a read that fails or finds no item moves nothing (warning); a refused move logs a warning naming the status read. The driver, the BF-878 guard, the transition table, the router and the reconciler are unchanged. Two limits are recorded, not repaired: an item parked before this agent's claim (another run's park) stays `blocked` while this agent works it, and a gap park followed by a command park in one run ends parked on the command request, the gap request pending with no item parked on it (the base's end state too; pinned). New: `tests/test_bf900_dispatch_claim_keeps_the_park.py` (real stores and the real driver). The decisions are in DECISIONS.md (BF-900); the contract is `prompts/bf-900-dispatch-claim-keeps-the-park.md`.

```

**`DECISIONS.md`** (the new entry goes after BF-913's, the newest of the recent run, before the heading that follows it):

SEARCH:
```markdown
- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.

### BF-900 -- The dispatch claim no longer undoes a park made in the same run (2026-10-21, #1573)

- *Scope.* The AD-839 claim in `CognitiveAgent._handle_work_item_dispatch` (`cognitive/cognitive_agent.py`) and tests. Contract: `prompts/bf-900-dispatch-claim-keeps-the-park.md` (the Architect's consult of 2026-10-21, 13:58Z).
- *Cause.* `_run_agentic_dispatch` parks the item `blocked` on a capability request for each denied tool (`on_capability_gap` -> `block_on_request`). The claim that follows moved it to `in_progress` with no expected status, and `blocked -> in_progress` is legal for a `task`, so the request's FULFILLED event found the item not blocked (BF-878's guard) and nothing resumed it. The claim's return value was ignored.
- *D1-D3.* The claim is a compare-and-set on the status the BF-607 read returned (`transition_work_item(..., expected_status=...)`, checked inside the write transaction). A `blocked` item is not moved. A read that raises or finds no item moves nothing, with a warning: no fallback to the unconditional move, which on a store fault would bring the defect back.
- *D4-D5.* A refused move (the status changed since the read, the move is illegal from it, or the item is gone) logs a warning naming the status read, log-and-degrade like the claim's existing warning. The check is in the `try`'s `else:` arm, so the AD-839 handler covers the one store call it covered before.
- *Limits recorded, not repaired (Do Not Build).* (1) An item already `blocked` when this agent's claim reads it (another run's park, or a dispatch whose dict predates a park) stays `blocked` while this agent works it; the quartermaster's reconciler scans only `open` and `in_progress` items, so it does not re-dispatch a parked one. (2) A gap park and a command park in one run: the command park writes last (`blocked -> blocked` with its metadata), so the item waits on the command request and the gap request stays pending with no item parked on it, the same end state as before this fix; test T3 pins it. Repairing it means making `block_on_request` a compare-and-set, which changes `CapabilityGapDriver`.
- *Rejected.* A second read just before the move (the race only moves); refusing `blocked -> in_progress` in the store for callers other than the driver (changes the transition table); filtering `blocked` items in the router or reconciler (out of scope).
- *Reversal.* Revert the BF-900 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both belong to the commit. Then `--check` and `tests/test_ad1184_ad_ledger.py` (M4).

**Records the orchestrator adds before the commit** (a tracker change after the gate invalidates it): one bullet in the BF-900 DECISIONS entry, *Validation of record*, with the mutation campaign (rows killed, the first failing test per row, base tree, sha256 of each file in section 10), then the ledger regeneration again.

**`docs/development/roadmap.md`:** no row (its Bug Tracker has none from BF-890 on: `Grep "BF-(89\d|90\d|91\d)" docs/development/roadmap.md` finds nothing).

**Next in the batch:** BF-901 S1's tracker pairs anchor on this entry's PROGRESS head and DECISIONS *Reversal* line.

## 9. What this does NOT change

1. **An item already `blocked` when the claim reads it stays `blocked` while the agent works it.** It arrives that way when another agent's run parked it (the router can hand one item to several agents) or when the dispatched dict was read before a park. The quartermaster does not re-dispatch a parked item: it scans `open` and `in_progress` only (`agents/quartermaster.py:164-165`, `:441-442`). This matches the open request the item waits on; it is not a regression. T6 pins it.
2. **A gap park and a command park in the same run end on the command request.** The command park (`park_on_command_escalation`, after the claim, `cognitive_agent.py:2306`) writes `blocked -> blocked` with its own metadata (`workforce.py:10781-10800`), so the last writer wins; the gap request stays pending with no item parked on it. Before this fix the end state was the same (the claim's `in_progress` came between the two parks). Changing it means a compare-and-set in `block_on_request`, which Do Not Build forbids. T3 pins it.
3. `CapabilityGapDriver` (including `block_on_request`, `_resume`, `_cancel` and the BF-878 guard), the AD-855 state machine, the work-item transition table, `WorkItemRouter`, the reconciler, the BF-607 assignee claim (a parked item still gets `assigned_to`, T1), the AD-1328 S2c park, configuration (no field; `config/system.yaml` untouched), the UI, and existing items (none are stranded in the vessel's data, per the issue).
4. The thread messages and the returned `IntentResult` (`cognitive_agent.py:2252-2266`, `:2311-2317`).

## 10. Mutation rows (whole stripped lines; each occurs once in its file after section 7.1)

Run against `tests/test_bf900_dispatch_claim_keeps_the_park.py` on the contract-applied tree, after an unmutated baseline run of that file that passes. The runner mutates `src/probos/cognitive/cognitive_agent.py` in place and restores it before the next row.

| # | Line (stripped) | Mutate to | Killed by (the failing assertion) |
|---|---|---|---|
| B1 | `elif read_status == "blocked":` | `elif False:` | T1: `assert parked.status == "blocked"` (the claim moves the parked item `blocked -> in_progress`, which the read status allows); T3 fails `assert wired.transitions.of(item.id) == [("open", "blocked")]` too |
| B2 | `expected_status=read_status,` | `expected_status=None,` | T4: `assert current.status == "blocked"` (the unconditional move overwrites the concurrent park) |
| B3 | `if read_status is None:` | `if False:` | T5 (both ids): `assert store.transitions == []` (with no status read the mutant reaches the move with `expected_status=None`, the unconditional move D3 forbids) |
| B4 | `if claimed is None:` | `if False:` | T4: `assert len(warnings) == 1` (no warning for the refused move) |

Campaign of record: name the base tree and the sha256 of `src/probos/cognitive/cognitive_agent.py` and the new test file; a later run whose hashes match does not repeat it.

## 11. Verified Against Codebase (2026-10-21, tree `8c8bc441`)

None of the anchor files changed since the consult's tree: `git diff --stat 3dfb6f81 HEAD -- src/probos/cognitive/cognitive_agent.py src/probos/cognitive/capability_gap_driver.py src/probos/workforce.py src/probos/cognitive/command_escalation_park.py tests/test_ad839_work_item_dispatch.py tests/test_ad856_agentic_dispatch.py tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1328_s2c_resume_seam.py` printed nothing. BF-911 and BF-913 (the commits between, `git log --oneline 3dfb6f81..HEAD`) touched none of them.

| Consult anchor | On this tree | Evidence |
|---|---|---|
| `_handle_work_item_dispatch` | TRUE (`:2129`) | `cognitive_agent.py:2129` `async def _handle_work_item_dispatch(self, intent: IntentMessage) -> IntentResult:`; `:2222` `reply_text = await self._run_agentic_dispatch(` |
| `on_capability_gap` call | TRUE (`:2392`) | `:2390` `for denied_tool in outcome.denied_tools:`; `:2392` `await gap_driver.on_capability_gap(` |
| The BF-607 read and the claim | TRUE (`:2280`, `:2289-2298`) | `:2280` `current = await store.get_work_item(work_item_id)`; `:2290-2292` `await store.transition_work_item(` / `work_item_id, "in_progress", source=self.id,` |
| The S2c park after the claim | TRUE (`:2306`) | `:2306` `await park_on_command_escalation(` |
| `block_on_request` | TRUE (`:135`, `:175-178`) | `capability_gap_driver.py:175-177` `transitioned = await store.transition_work_item(` / `work_item_id, "blocked", source="capability_gap_driver",` / `metadata_patch={"blocked_reason": reason, "capability_request_id": request_id},` |
| BF-878 guard | TRUE (`:273-278`) | `capability_gap_driver.py:273` `if item.status != "blocked":` |
| `_resume` CAS | TRUE (`:307-311`) | `expected_status="blocked",` / `expected={"capability_request_id": request_id},` |
| `transition_work_item` CAS | TRUE | `workforce.py:10716-10718` signature with `expected_status: str | None = None`; `:10747` `async with self._booking_transaction():`; `:10754` `if expected_status is not None and item.status != expected_status:`; `:10781-10783` same-status returns the item; `source` is not read in the body (`:10735-10814`) |
| Task transitions | TRUE | `workforce.py:188` `WorkTypeTransition("open", "in_progress", requires_assignment=True),`; `:190` `("open", "blocked")`; `:195` `("blocked", "in_progress")` |
| `reason=gap_target` | TRUE | `capability_gap_driver.py:118` `reason=gap_target,` (so `blocked_reason` is the tool id, as T1 asserts) |
| Triage leaves a grant pending without a triage config | TRUE | `capability_gap_driver.py:441-443` `_triage_config` reads `config.capability_triage`; `capability_triage.py:757` `fast_path_enabled = config.grant_fast_path_enabled if config is not None else False` |
| Command park | TRUE | `command_escalation_park.py:74-75` a pending request is returned before the `since` check; `:119-122` `driver.block_on_request(...)` |
| The `_FakeGapDriver` copies | MOVED: three | `test_ad856_agentic_dispatch.py:108`, `test_ad1328_s2c_park_and_scope.py:156`, `test_ad859a_agentic_executor.py:100` |
| Fakes taking no `expected_status` that reach the handler | TRUE | `test_ad839_work_item_dispatch.py:87-89`; `test_ad856_agentic_dispatch.py:351-353` (that fake has no `get_work_item`); asserts `test_ad839...:193`, `:239`, `:268`, `:290`, `:314`, `test_ad856...:394` |
| `agentic_dispatch` default false | MOVED (`:1282`) | not re-read; the fix does not depend on it |
| Reconciler route (consult blind spot) | WRONG in detail | paths are `cognitive/work_reconciler.py:148` and `agents/quartermaster.py:405-415`; the quartermaster scans `list_work_items(status="open")` and `(status="in_progress")` (`:164-165`, `:441-442`) |
| Tests' logger | TRUE | `cognitive_agent.py:55` `logger = logging.getLogger(__name__)` |
| Rig parts | TRUE | `WorkItemStore.__init__` takes `emit_event` (`workforce.py:2727`) and `_emit` calls it (`protocols.py:47-49`); the status event carries `"work_item"` (the item's `to_dict()`, with `"id"`, `workforce.py:3244-3253`, `:995-997`), `"old_status"`, `"new_status"` (`:10804-10808`); `CapabilityRequestStore.file_request(agent_id, kind, target, rationale, work_item_id, ...)` (`capability_request.py:708-716`); `mark_fulfilled` emits FULFILLED for any known request (`:1037-1073`) |
| Tracker anchors | TRUE | `PROGRESS.md:1` `# ProbOS Progress`, `:2` blank; `DECISIONS.md:497` `- *Reversal.* Revert the BF-913 commit. Nothing persisted changes.`, `:498` blank, `:499` `### Explicit delegation models, ...` |

## Absence Verified (2026-10-21)

```
CLAIM: no source-scan test pins the claim lines
RUN:   Grep "source=self\.id|BF-607: failed to claim|AD-839: failed to transition" tests/
FOUND: nothing
RUN:   Grep "getsource\(ca\.CognitiveAgent\._handle_work_item_dispatch" tests/
FOUND: test_ad1248_slice_a_gaps.py:245, :374; test_bf773_failure_reaches_the_captain.py:13 (a docstring)
HOLDS: yes -- their strings (failures_sink=, _body = str(...), body=_body,, and _body:, result=_body or ...) are unchanged

CLAIM: the claim is the only transition_work_item call in cognitive_agent.py
RUN:   Grep "transition_work_item\(" src/probos/cognitive/cognitive_agent.py
FOUND: :2290
HOLDS: yes

CLAIM: test_ad859a's _FakeGapDriver never reaches the claim
RUN:   Grep "_handle_work_item_dispatch" tests/
FOUND: test_ad1248_slice_a_gaps.py, test_ad1275_sink_side_composition.py, test_ad1328_s2c_park_and_scope.py (docstrings),
       test_ad1328_s2c_resume_seam.py, test_ad839_work_item_dispatch.py, test_ad856_agentic_dispatch.py, test_bf773_failure_reaches_the_captain.py
HOLDS: yes -- test_ad859a_agentic_executor.py is not among them

CLAIM: the new names are free in cognitive_agent.py
RUN:   Grep "\bread_status\b|\bclaimed\b" src/probos/cognitive/cognitive_agent.py
FOUND: nothing
HOLDS: yes (so mutation rows B1-B4 are unique lines)

CLAIM: the quartermaster does not re-dispatch a blocked item
RUN:   Grep "\"blocked\"|status in|list_work_items\(" src/probos/agents/quartermaster.py
FOUND: :164, :165, :441, :442 (status="open", status="in_progress")
HOLDS: yes

CLAIM: nothing else hands the router an item
RUN:   Grep "\.dispatch_work_item\(|on_work_item_created\(" src/probos/
FOUND: agents/quartermaster.py:316, :415; cognitive/capability_gap_driver.py:352; mesh/work_item_router.py:176, :187
HOLDS: yes

CLAIM: no roadmap row since BF-890
RUN:   Grep "BF-(89\d|90\d|91\d)" docs/development/roadmap.md
FOUND: nothing
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

| Check | Result for this change |
|---|---|
| srp-size | `CognitiveAgent` is already in the baseline with `lines` and `methods` (`docs/development/architecture-baseline.yaml:407-412`, `disposition: debt`); this adds about 25 lines to one method and no method, so its triggers are unchanged. The new test file has no class near 500 lines or 15 methods |
| layer-import | No new module-scope import in `src/` |
| db-connect | No `sqlite3.connect`/`aiosqlite.connect` in `src/` |
| unowned-task | No `create_task` in `src/` (the test `_EventBus` holds its tasks, BF-639) |
| config reference and facade | No config field; `config/system.yaml` untouched |
| seam contracts | `Grep "_handle_work_item_dispatch|transition_work_item" docs/development/seams/` finds nothing |
| store registry | No table or store added |
| AD-1343 seam registry and census | No new `.complete(` call and no new public coroutine on `CognitiveAgent` (`tests/fixtures/ad1343_seam_census.py:35-39` records calls by file, function and callee, not by line); run `tests/test_ad1343_seam_registry.py` (M3) |
| Ledger | M4 |

## 13. Prior Art and Blind Spots

- **External prior art: skipped**, the defect is ProbOS plumbing: an optimistic compare-and-set on a row's status is the textbook fix, and the store already implements it (BF-878).
- **Internal:** BF-878 (#1439) built the CAS this uses; BF-606 made the same-status move a no-op, so an item the driver already resumed (`in_progress` when read) is claimed as a no-op returning the item, with no warning (`workforce.py:10781-10783`).
- **Blind spots named:** the two in section 9; a broadcast dispatch that reaches several agents now makes the later agents' claims either a same-status no-op (they read `in_progress`) or a refused move with the BF-900 warning (they read `open` before the first agent's move landed); the end state is the same `in_progress`.
- Reference projects (`docs/research/reference-projects.md`, judged against 2026-10-21): none is relevant to this fix; AG-UI (never) and MCP Apps (2026-04-08) are overdue and considered, deferred.

## 14. Diff Reviewer: properties to verify

1. The claim passes `expected_status` equal to the status the BF-607 read returned, and no code path in the handler calls `transition_work_item` without `expected_status`.
2. When the read raised or returned no item, no transition is attempted.
3. When the read status is `blocked`, no transition is attempted, and `update_work_item(assigned_to=...)` still runs for an unassigned item.
4. The AD-839 `except` covers only the `transition_work_item` call, as on the base; the `None`-result warning runs only when that call returned `None`.
5. `park_on_command_escalation` still runs after the claim in every branch (it is outside the new `if`/`elif`/`else`).
6. Each changed test fake still answers every call the handler makes on it, and each changed fake's inline comment states why it changed.
7. T1 and T3 run the real `CapabilityGapDriver`, `WorkItemStore` and `CapabilityRequestStore`; no fixture replaces `_handle_work_item_dispatch`, `_run_agentic_dispatch` or the driver.
8. The DECISIONS entry and the PROGRESS line describe the two recorded limits as unchanged behaviour, not as fixed.

## 15. Acceptance criteria

1. The claim never undoes a park made earlier in the same run: a `blocked` item is not moved; any other read status is passed as `expected_status` (T1, E1, B1, B2).
2. A compare-and-set miss is log-and-degrade with a warning naming the status read (T4, B4); a failed or empty read moves nothing (T5, B3).
3. The seam test runs the issue's reproduction with real stores and no fake gap driver: parked after dispatch, one `blocked -> in_progress` and one re-dispatch after `mark_fulfilled`, and the clean-run control ends `in_progress` (T1, T2).
4. A command-escalation park is not suppressed by the `blocked` skip (T3; P-S1 in `test_ad1328_s2c_resume_seam.py` unchanged and green).
5. The BF-607 assignee claim is unchanged (T1, T6).
6. Every test fake that reaches the claim takes `expected_status`, and each change says why inline (sections 7.2 to 7.4).
7. Every mutation row in section 10 is killed by the named assertion.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
