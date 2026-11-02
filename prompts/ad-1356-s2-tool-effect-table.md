# AD-1356 S2 (#1722): the tool-effect table, with the routine tier running

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02
**Status:** ready to build after AD-1356 S1 merges. **Base:** drafted on S1's head `0ac7bdf3` (main `e9140fcb` + S1 M1-M4). **Dependencies:** AD-1356 S1 (#1722), in review. **Tier:** M1 HIGH (changes who authorises an agent-work call), M2 STANDARD (trackers and ledger only). **Estimated tests:** 1 new file (5 test functions), 1 edited test file.
**AD number:** AD-1356, held by the title of #1722. S2 is a slice; no new number.

**Which text describes the head.** §1 to §3 describe `0ac7bdf3`; line numbers are that commit's. The head is what the pairs and new-file blocks of §7 and §8 produce, applied in order on S1's merged head. **P1-1 quotes text S1 wrote (S1's P1-7).** Every other SEARCH quotes text from before S1. A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. Where prose differs from a block, the block wins. Head text means every docstring, comment, log message, error string, agent-facing string and test docstring in those blocks, plus §8's tracker entries and §5's commit messages.

## 1. Problem

On `0ac7bdf3`:

1. An agent-work run calls only `AGENT_WORK_READ_TOOL_IDS` directly (`agent_work_runner.py:74-77`, used at `:615`). Every other call goes to the gate. That includes the code reads that made up 16 of the 28 requests on 2026-10-31 (#1722), which the gate filed for the Captain.
2. There is no table of tool effects. The nearest classifiers are plan mode's allowlist (`cognitive/agent_mode.py:68-83`, whose test is "changes nothing", not "needs no approval"), the effect broker's classes (`execution/effect_broker.py:322-351`), and `derive_tool_permission`. #1722 rules the last one out for tiering.
3. `read_file` and `codebase_read_source` read through `resolve_for_runtime` (`swe_harness/tools.py:448`, `:754`). With `security_infra.read_roots` unset, that reaches files outside the data directory and config files (`security/file_access.py:160`, `:165-176`, `:197-206`).
4. `list_files` resolves its path with `_resolve_path` (`swe_harness/tools.py:245-248`, called at `:542`), never through the read policy.
5. The agent is told "Read-only tools run directly." (`agent_work_runner.py:234`). Before S2 that was already false for the web reads, which are read-only and filed.

## 2. Solution

- **M1:** a new module, `src/probos/tools/effect_tiers.py`, with stdlib imports only:
  - three tier names (AD-676's): `routine`, `elevated`, `critical`;
  - the routine and elevated member sets, plus the routine members bound to the read policy;
  - `tool_tier(tool_id, *, reads_confined)` and `routine_tool_ids(*, reads_confined)`.
  - `AgentWorkRunner._run` builds the confinement from `routine_tool_ids(reads_confined=bool(permitted_read_roots(runtime)))`. This is read once per run, and the set stays a frozenset.
  - `AGENT_WORK_READ_TOOL_IDS` is deleted, and the task text says "Routine reads run directly."
- **M2:** trackers and ledger. No `src` or `tests` file.

## 3. Decisions (ranked by correctness, safety, compatibility, architectural fit, reversibility, validation cost; the first option is chosen)

**D1. Where the table lives, and its shape.**
1. **Chosen: `src/probos/tools/effect_tiers.py`.**
   - Shape: stdlib only, plain `Final` string tiers, explicit frozensets, `tool_tier` and `routine_tool_ids`. Anything not listed is critical, including `mcp:` ids, str subclasses and non-str ids.
   - Why this place: it is the lowest owning layer for tool metadata (`tools/` is unranked, `check_architecture_principles.py:80-85`). The runner, S3's `delegated_approvals.classify_capability_request` (`delegated_approvals.py:168`) and AdmissionService at M4 can all import it, and no layer rule applies.
   - No class is added, so `check_dormant_classes` is not exercised.
2. `src/probos/admission/tool_tiers.py`. Rejected for now: importing it loads `probos.admission` (`admission/__init__.py:8-9` imports the service), and T14 pins what admission may import. M4 can absorb the table by import or by a move.
3. Inside `agent_work_runner.py`. Rejected: S3's classifier would then import the work runner.
4. AD-676 `governance/risk_tiers`. Rejected: #1722 "Do not build" (AD-1353 F07's scope), and its `get_tier` fails open to ROUTINE.

**D2. How `tool_ids` is computed at run start.**
1. **Chosen: the table's routine set, under D3's read-policy condition, read once at the start of `_run`.**
   - Whether a tool is registered, and whether the agent holds it, stay decided at each call. S1.1 refuses a tool id the registry does not hold (`agentic_dispatch.py:843-847`). The registry's permission check denies a tool the agent does not hold, as in an unconfined run (`tools/executor.py:832-841`).
   - A tool discovered mid-run is outside the frozenset, so it goes to the gate.
   - The routine set always has at least 11 members, so `ToolCallConfinement`'s non-empty invariant (`agentic_dispatch.py:354`) always holds. "An agent that holds none" therefore means an agent whose routine calls are each denied by the registry, as today.
   - No config field, so the AD-1152 golden does not move.
2. Intersect with `self._tools.list_ids()` at run start. Rejected: `work_item_status` and several others are registered inside `executor.run` on first use (`agentic_dispatch.py:3205-3216`). On a fresh boot the first run would file them, a regression, and the intersection decides nothing the per-call checks don't.
3. Narrow to the agent's offer inside the executor. Rejected:
   - it changes `ToolCallConfinement`'s contract (shared);
   - a routine tool the agent does not hold would be filed for an approval that cannot make it run, because the registry still denies it;
   - AD-1347 S3 D4 keeps the offer whole (`agentic_dispatch.py:3606`).

**D3. The four newly routine tools before `security_infra.read_roots` is set.**
1. **Chosen: fail closed.**
   - `read_file` and `codebase_read_source` (`READ_POLICY_TOOL_IDS`) are routine only while `permitted_read_roots(runtime)` is non-empty, and critical otherwise. ET3 and ET4 pin both states through the whole path.
   - `codebase_query` is routine whatever the roots say: it reads only the `CodebaseIndex` built from the source root (`swe_harness/tools.py:597-601`, `cognitive/codebase_index.py:143-145`).
   - `list_files` is **elevated**, because no read policy confines it (§1.4). It is filed until S3 and moves to routine after a separate BF puts it under the read policy.
   - S1.3's `_recovery_read` is kept. While roots are unset it still admits a `read_file` of a workspace result. While roots are set, `read_file` is routine and never reaches the gate, so it decides nothing.
2. Routine unconditionally, with the prerequisite stated for the Captain. Rejected: safety would rest on the order of two human actions. Enabling agent work first would let a routine read reach user files and post them.
3. All four stay filed until a later slice. Rejected: no safety gain over option 1 once the roots are set, and it withholds the Captain's main relief.

What an empty `read_roots` allows: `permitted_read_roots` returns `[]` (`file_access.py:174-176`), so `resolve_read_path` applies the floor of the data directory and config files and no allowlist (`:151-161`). When roots are set, they are the configured entries plus the workspace root (`:177-194`).

**D4. MCP tools and the elevated tier.**
1. **Chosen:**
   - S2 lists the native elevated tools: `find_mcp_tool`; `web_search`, `read_page` and `http_fetch` (Q6); and `list_files`.
   - An `mcp:` id is not listed, so it is critical.
   - The AD-1019b mapping (OPEN → elevated; CONFIRM and CONSENSUS → critical) lands in S3 with its first consumer and a whole-path test. The risk is read from `_McpTool.effective_risk()` (`agentic_dispatch.py:1741-1760`) through the registry S3's classifier already takes.
   - In S2, elevated and critical calls both go to the gate and are filed for the Captain exactly as today.
2. Add an `mcp_risk` parameter now. Rejected: no S2 caller would pass it, so it would be built, tested and inert.
3. Read the MCP `readOnlyHint` and `openWorldHint` annotations. Rejected: the MCP spec says clients MUST treat annotations as untrusted unless they come from trusted servers, and AD-1019b's operator-set risk is the decided source.

**D5. Plan mode and the table.**
1. **Chosen: not shared.**
   - Plan mode's test is "changes nothing": it admits off-ship reads and withholds `read_file`, which `test_ad1240_tool_result_delivery.py:4946` asserts.
   - Routine's test is "needs no approval": it excludes off-ship reach and admits file reads only when confined.
   - The two sets differ in both directions, and sharing would change DM plan-mode turns. ET2 pins how they relate.
2. Plan mode = the routine set. Rejected: it removes the web reads from plan mode and adds `read_file`.
3. Routine = plan mode minus off-ship reads. Rejected: a plan-mode addition would silently become routine.

**Config:** none. No method is added to `AgentWorkRunner` (it stays at 15).

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | HIGH | N1-1, P1-1 to P1-10, N1-2 | G1 |
| M2 | STANDARD | P2-1, P2-2, the ledger | G2 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1356_s2_tool_effect_table.py tests/test_ad1347_s3_execution.py tests/test_bf947_multi_call_agent_work.py tests/test_bf947_confinement_answer.py tests/test_ad1356_s1_recovery_reads.py tests/test_ad1356_s1_unknown_tools.py tests/test_ad1156_plan_execute_mode.py tests/test_bf758_file_read_confinement.py -q -n 0`, then:
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check`

**G2:**
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

## 5. Commit messages

- M1: `AD-1356 S2 M1: the tool-effect table; agent work runs its routine tier with no approval`
- M2: `AD-1356 S2 M2: trackers and ledger`

## 6. Tests

| Id | File | Test | Covers |
|---|---|---|---|
| ET1 | tool_effect_table | `test_the_table_pins_each_tier_and_anything_it_does_not_list_is_critical` | Acceptance 9; table edges |
| ET2 | tool_effect_table | `test_every_routine_tool_reads_and_none_leaves_the_ship` | Acceptance 9; read-only pin; relation to plan mode |
| ET3 | tool_effect_table | `test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed` | Whole path, reads confined |
| ET4 | tool_effect_table | `test_with_no_read_roots_the_same_read_is_filed_for_the_captain_and_does_not_run` | Whole path, fail closed |
| ET5 | tool_effect_table | `test_codebase_query_runs_without_approval_while_read_roots_are_unset` | Whole path, unconditional routine |

Edited: `tests/test_ad1347_s3_execution.py` (import, the two plan-mode relation asserts, and the X15 confinement) because `AGENT_WORK_READ_TOOL_IDS` is deleted.

## 7. The contract

### 7.1 M1

**N1-1** `src/probos/tools/effect_tiers.py` (new)

```python
"""AD-1356 S2 (#1722): the tool-effect table, the one source of agent-work tiering.

A tool's tier names who authorises an agent-work call to it, in AD-676's names: a ``routine`` call runs with no
approval; an ``elevated`` or ``critical`` call is put to the run's gate. A tool is in the table only by name. A tool id
the table does not list (a new or renamed tool, every ``mcp:`` tool) and an id that is not a str are critical.

``routine_tool_ids`` is what a run reads (``agent_work_runner``); ``tool_tier`` classifies one id. The members are
seeded from the plan-mode read set (``cognitive.agent_mode.PLAN_MODE_TOOL_IDS``, held to reads by
``tests/test_ad1156_plan_execute_mode.py``) and from ``execution.effect_broker``'s effect classes, never from the rank
grant matrix (``derive_tool_permission``), which records what a rank is granted, not what a tool does. Pinned member by
member in ``tests/test_ad1356_s2_tool_effect_table.py``. Stdlib only.
"""

from __future__ import annotations

from typing import Final

TIER_ROUTINE: Final = "routine"
TIER_ELEVATED: Final = "elevated"
TIER_CRITICAL: Final = "critical"

#: Routine: each reads, changes nothing and stays on the ship. The ten tools agent work called directly before
#: AD-1356 S2, and three code readers.
ROUTINE_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
    "codebase_query", "codebase_read_source", "read_file",
})
#: The routine tools that read a path through the operator's read policy (``security.file_access.resolve_for_runtime``).
#: With ``security_infra.read_roots`` unset that policy reaches any file outside the runtime's data directory and config
#: files, so these are routine only while the roots are set, and critical otherwise.
READ_POLICY_TOOL_IDS: Final[frozenset[str]] = frozenset({"codebase_read_source", "read_file"})
#: Elevated: reads that reach past what the ship holds or past the read policy. find_mcp_tool discovers and offers new
#: tools; web_search, read_page and http_fetch leave the ship (the Captain's Q6, 2026-10-31); list_files resolves its
#: path without the read policy (``swe_harness.tools._resolve_path``).
ELEVATED_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "find_mcp_tool", "http_fetch", "list_files", "read_page", "web_search",
})


def tool_tier(tool_id: object, *, reads_confined: bool) -> str:
    """The tier of ``tool_id``; ``reads_confined`` is whether ``security_infra.read_roots`` is set."""
    if type(tool_id) is not str:
        return TIER_CRITICAL
    if tool_id in ROUTINE_TOOL_IDS:
        return TIER_ROUTINE if reads_confined or tool_id not in READ_POLICY_TOOL_IDS else TIER_CRITICAL
    if tool_id in ELEVATED_TOOL_IDS:
        return TIER_ELEVATED
    return TIER_CRITICAL


def routine_tool_ids(*, reads_confined: bool) -> frozenset[str]:
    """The tools an agent-work run calls with no approval: the members ``tool_tier`` holds routine."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE
    )
```

**P1-1** `src/probos/agent_work_runner.py` (**quotes S1's P1-7 text**)

SEARCH:
```
Every run is confined (``ToolCallConfinement``): the executor refuses a call whose tool id its registry does not hold
(AD-1356 S1.1); the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual; and a call to any other tool is put to the
run's gate (``_gate_for``, whose docstring gives its order), which may file it as an AD-1154 ``action`` request. A run
```
REPLACE:
```
Every run is confined (``ToolCallConfinement``): the executor refuses a call whose tool id its registry does not hold
(AD-1356 S1.1); the routine tools (``tools.effect_tiers.routine_tool_ids``, read once at the run's start, AD-1356 S2)
run as usual; and a call to any other tool is put to the run's gate (``_gate_for``, whose docstring gives its order),
which may file it as an AD-1154 ``action`` request. A run
```

**P1-2** `src/probos/agent_work_runner.py`

SEARCH:
```
from probos.events import EventType
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.workforce import AGENT_WORK_METADATA_KEY, WorkItem
```
REPLACE:
```
from probos.events import EventType
from probos.tools.effect_tiers import routine_tool_ids
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.workforce import AGENT_WORK_METADATA_KEY, WorkItem
```

**P1-3** `src/probos/agent_work_runner.py`

SEARCH:
```
logger = logging.getLogger(__name__)

#: The tools an agent-created work run calls directly: the plan-mode read set (``agent_mode.PLAN_MODE_TOOL_IDS``, each
#: asserted read-only there) without the three that reach off the ship (web_search, read_page, http_fetch) and without
#: discover_work_items. Every other call is filed for the Captain's approval: a new or renamed tool is filed until
#: someone decides it only reads.
AGENT_WORK_READ_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
})
APPROVAL_ACTION: Final = AGENT_WORK_CALL_ACTION  # A1 (F1): one definition, shared with the fulfilment predicate
```
REPLACE:
```
logger = logging.getLogger(__name__)

APPROVAL_ACTION: Final = AGENT_WORK_CALL_ACTION  # A1 (F1): one definition, shared with the fulfilment predicate
```

**P1-4** `src/probos/agent_work_runner.py`

SEARCH:
```
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
```
REPLACE:
```
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the routine reads you hold"
```

**P1-5** `src/probos/agent_work_runner.py`

SEARCH:
```
        f"{earlier}"
        "Read-only tools run directly. A call to another tool may be filed for approval instead of running; this work "
        "continues when no call you filed on it awaits a decision or its fulfilment, and ends if one of them is "
```
REPLACE:
```
        f"{earlier}"
        "Routine reads run directly. A call to another tool may be filed for approval instead of running; this work "
        "continues when no call you filed on it awaits a decision or its fulfilment, and ends if one of them is "
```

**P1-6** `src/probos/agent_work_runner.py`

SEARCH:
```
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS, self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
```
REPLACE:
```
            from probos.cognitive.agentic_dispatch import ToolCallConfinement
            from probos.security.file_access import permitted_read_roots

            agent = self._agents.get(slot)
            filed: list[str] = []
            # AD-1356 S2: the routine tools, read once here; the set does not change during the run. read_file and
            # codebase_read_source are routine only while security_infra.read_roots confines reads.
            confinement = ToolCallConfinement(
                routine_tool_ids(reads_confined=bool(permitted_read_roots(self._runtime))),
                self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
```

**P1-7** `tests/test_ad1347_s3_execution.py`

SEARCH:
```
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkService, open_agent_work_service
from probos.agent_work_runner import AGENT_WORK_READ_TOOL_IDS, AgentWorkRunner
from probos.api_models import CapabilityRequestDecideRequest
```
REPLACE:
```
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkService, open_agent_work_service
from probos.agent_work_runner import AgentWorkRunner
from probos.api_models import CapabilityRequestDecideRequest
```

**P1-8** `tests/test_ad1347_s3_execution.py`

SEARCH:
```
from probos.substrate.event_log import EventLog
from probos.tools.permissions import ToolPermissionStore
```
REPLACE:
```
from probos.substrate.event_log import EventLog
from probos.tools.effect_tiers import ROUTINE_TOOL_IDS, routine_tool_ids
from probos.tools.permissions import ToolPermissionStore
```

**P1-9** `tests/test_ad1347_s3_execution.py`

SEARCH:
```
            plan_mode_tool_ids=frozenset({"event_log_query"}), confinement=ToolCallConfinement(frozenset({"x"}), broken),
        )
    assert AGENT_WORK_READ_TOOL_IDS <= PLAN_MODE_TOOL_IDS
    assert not AGENT_WORK_READ_TOOL_IDS & {"web_search", "read_page", "http_fetch", "discover_work_items"}
```
REPLACE:
```
            plan_mode_tool_ids=frozenset({"event_log_query"}), confinement=ToolCallConfinement(frozenset({"x"}), broken),
        )
    # AD-1356 S2: the routine tier draws on the plan-mode read set plus three code readers, and never leaves the ship.
    assert ROUTINE_TOOL_IDS - {"codebase_query", "codebase_read_source", "read_file"} <= PLAN_MODE_TOOL_IDS
    assert not ROUTINE_TOOL_IDS & {"web_search", "read_page", "http_fetch", "discover_work_items"}
```

**P1-10** `tests/test_ad1347_s3_execution.py`

SEARCH:
```
    try:
        session_id = await _open_session(executor, tool, _TIER_3_URL)
        executor.confine_calls(ToolCallConfinement(AGENT_WORK_READ_TOOL_IDS, gate))
```
REPLACE:
```
    try:
        session_id = await _open_session(executor, tool, _TIER_3_URL)
        executor.confine_calls(ToolCallConfinement(routine_tool_ids(reads_confined=False), gate))
```

**N1-2** `tests/test_ad1356_s2_tool_effect_table.py` (new)

```python
"""AD-1356 S2 (#1722): the tool-effect table, and agent work running its routine tier with no approval.

The table (``probos.tools.effect_tiers``) is pinned tier by tier. The whole path runs through the rig of
``tests/test_ad1347_s3_execution.py``, with the native tools registered by ``register_native_swe_tools`` and a started
AD-1240 store as the runtime's workspace (as ``tests/test_ad1240_workspace_results.py`` builds it). On the base this
file fails at import (``probos.tools.effect_tiers``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.capability_request import requests_for_work_item
from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS
from probos.cognitive.swe_harness.tools import (
    CodebaseQueryTool,
    CodebaseReadSourceTool,
    ReadFileTool,
    register_native_swe_tools,
)
from probos.tools.effect_tiers import (
    ELEVATED_TOOL_IDS,
    READ_POLICY_TOOL_IDS,
    ROUTINE_TOOL_IDS,
    TIER_CRITICAL,
    TIER_ELEVATED,
    TIER_ROUTINE,
    routine_tool_ids,
    tool_tier,
)
from tests.test_ad1240_workspace_results import make_store
from tests.test_ad1347_s1_agent_work import REASON
from tests.test_ad1347_s3_execution import _call, _final, _pump, _rig, _seen, _thread_in

NOTES = "Relay drift notes: the port coupling read 0.4 mm at 00:12."
CODE_READERS = frozenset({"codebase_query", "codebase_read_source", "read_file"})
BEFORE_S2 = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
})


class _Index:
    """A codebase index that records what it is asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def query(self, concept: str) -> dict[str, Any]:
        self.asked.append(concept)
        return {"matches": ["src/probos/relay.py"]}


async def _native(rig: Any, tmp_path: Path, *, read_roots: list[Path]) -> Any:
    """The native tools, a started AD-1240 store as the workspace root, and ``security_infra.read_roots``."""
    store = make_store(tmp_path / "workspaces").store
    execution = rig.runtime.config.execution.model_copy(update={"workspace_root": str(store.root)})
    security = rig.runtime.config.security_infra.model_copy(update={"read_roots": [str(root) for root in read_roots]})
    rig.runtime.config = rig.runtime.config.model_copy(update={"execution": execution, "security_infra": security})
    rig.runtime.workspace_results = store
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    await store.start()
    return store


async def _self_task(rig: Any, title: str) -> str:
    origin = await _thread_in(rig, "engineering", "laforge-1")
    created = await rig.service.create_self_task(
        "forge-1", title=title, description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
    )
    assert isinstance(created, AgentWorkCreated), created
    await _pump(rig)
    return created.work_item.id


def _notes(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    notes = project / "notes.txt"
    notes.write_text(NOTES, encoding="utf-8")
    return notes


# ET1
def test_the_table_pins_each_tier_and_anything_it_does_not_list_is_critical() -> None:
    """Routine: the ten tools agent work called directly before S2, and three code readers; the two path readers are
    routine only while reads are confined. Elevated: find_mcp_tool, the three web reads and list_files. Anything else
    is critical: a tool the table does not list, an MCP tool, a str subclass and an id that is not a str."""

    class _Named(str):
        pass

    assert ROUTINE_TOOL_IDS == BEFORE_S2 | CODE_READERS
    assert READ_POLICY_TOOL_IDS == {"codebase_read_source", "read_file"}
    assert ELEVATED_TOOL_IDS == {"find_mcp_tool", "web_search", "read_page", "http_fetch", "list_files"}
    assert routine_tool_ids(reads_confined=True) == ROUTINE_TOOL_IDS
    assert routine_tool_ids(reads_confined=False) == BEFORE_S2 | {"codebase_query"}
    for tool_id in ROUTINE_TOOL_IDS:
        assert tool_tier(tool_id, reads_confined=True) == TIER_ROUTINE, tool_id
    for tool_id in READ_POLICY_TOOL_IDS:
        assert tool_tier(tool_id, reads_confined=False) == TIER_CRITICAL, tool_id
    for tool_id in ELEVATED_TOOL_IDS:
        assert tool_tier(tool_id, reads_confined=True) == TIER_ELEVATED, tool_id
    for tool_id in (
        "run_python", "write_file", "edit_file", "run_command", "browser", "delegate_task", "publish_finding",
        "claim_work_item", "standing_interest", "discover_work_items", "mcp:github:list_issues", "hull_survey", "",
        _Named("read_file"), None, ["read_file"],
    ):
        assert tool_tier(tool_id, reads_confined=True) == TIER_CRITICAL, tool_id


# ET2
def test_every_routine_tool_reads_and_none_leaves_the_ship() -> None:
    """A routine member is in the plan-mode read set (held to reads by tests/test_ad1156_plan_execute_mode.py) or is one
    of the three code readers, whose parameters are pinned here so that a parameter that could carry a write is
    reviewed first. No routine member is elevated or is discover_work_items."""
    assert ROUTINE_TOOL_IDS - CODE_READERS <= PLAN_MODE_TOOL_IDS
    assert not ROUTINE_TOOL_IDS & (ELEVATED_TOOL_IDS | {"discover_work_items"})
    assert set(ReadFileTool.input_schema["properties"]) == {"path", "offset", "limit"}
    assert set(CodebaseReadSourceTool.input_schema["properties"]) == {"file_path", "start_line", "end_line"}
    assert set(CodebaseQueryTool.input_schema["properties"]) == {"concept"}


# ET3
async def test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed(
    tmp_path: Path,
) -> None:
    """With read_roots set, forge-1's read_file of a file under a root runs with nothing filed and the model is shown
    its text and the line that routine reads run directly. Its list_files in the same run is filed, and the item parks
    on that request."""
    notes = _notes(tmp_path)
    script = [
        _call("read_file", {"path": str(notes)}, "c1"),
        _call("list_files", {"pattern": "*.txt", "path": str(notes.parent)}, "c2"),
        _final("Waiting for the Captain."),
    ]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            item_id = await _self_task(rig, "Read the relay notes")
            parked = await rig.store.get_work_item(item_id)
            assert parked is not None and parked.status == "blocked"
            assert _seen(rig, NOTES)
            assert _seen(rig, "Routine reads run directly.")
            [request] = requests_for_work_item(rig.requests, item_id)
            assert (request.status, request.payload["tool_id"]) == ("pending", "list_files")
        finally:
            await store.stop()


# ET4
async def test_with_no_read_roots_the_same_read_is_filed_for_the_captain_and_does_not_run(tmp_path: Path) -> None:
    """Fail closed: with read_roots unset, read_file is critical. The call is filed, the item parks on it, and the
    file's text never reaches the model."""
    notes = _notes(tmp_path)
    async with _rig(tmp_path, [_call("read_file", {"path": str(notes)}, "c1"), _final("Waiting for the Captain.")]) as rig:
        store = await _native(rig, tmp_path, read_roots=[])
        try:
            item_id = await _self_task(rig, "Read the relay notes")
            parked = await rig.store.get_work_item(item_id)
            assert parked is not None and parked.status == "blocked"
            assert not _seen(rig, NOTES)
            [request] = requests_for_work_item(rig.requests, item_id)
            assert (request.status, request.payload["tool_id"], request.payload["params"]) == (
                "pending", "read_file", {"path": str(notes)},
            )
        finally:
            await store.stop()


# ET5
async def test_codebase_query_runs_without_approval_while_read_roots_are_unset(tmp_path: Path) -> None:
    """codebase_query reads only the codebase index, so it is routine whatever read_roots says: it runs, nothing is
    filed and the item is done."""
    index = _Index()
    async with _rig(tmp_path, [_call("codebase_query", {"concept": "relay drift"}, "c1"), _final()]) as rig:
        store = await _native(rig, tmp_path, read_roots=[])
        rig.runtime.codebase_index = index
        try:
            item_id = await _self_task(rig, "Find the relay code")
            done = await rig.store.get_work_item(item_id)
            assert done is not None and done.status == "done"
            assert index.asked == ["relay drift"]
            assert requests_for_work_item(rig.requests, item_id) == []
        finally:
            await store.stop()
```

### 7.2 M2

M2 changes no `src` or `tests` file. Its pairs are P2-1 and P2-2 (§8), plus the ledger.

## 8. Tracking (M2's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-02. If M2 is committed on a later date (`git log -1 --format=%cs`), the Builder puts that date in both heads.

**P2-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1356 S2 (2026-11-02), #1722 -- the tool-effect table; agent work runs its routine tier with no approval.** `tools/effect_tiers.py` is the one table that tiers agent-work tool calls, in AD-676's names: routine, elevated, and critical for every tool it does not list, `mcp:` tools and non-str ids included. Routine: the ten tools agent work already called directly, plus `codebase_query`, `codebase_read_source` and `read_file`; the two path readers are routine only while `security_infra.read_roots` confines reads, and critical otherwise. Elevated: `find_mcp_tool`, `web_search`, `read_page`, `http_fetch` and `list_files`, whose path no read policy confines. A run reads its routine set once at its start (`routine_tool_ids`); a call to any other tool goes to the run's gate as before, so elevated and critical calls are still filed for the Captain. `AGENT_WORK_READ_TOOL_IDS` is removed, and the run is told that routine reads run directly. Plan mode is unchanged. No config field. The contract is `prompts/ad-1356-s2-tool-effect-table.md`.

```

**P2-2** `DECISIONS.md` (anchor: BF-947's heading, which S1's P4-9 re-emits unchanged; S2's entry lands between S1's entry and BF-947's)

SEARCH:
```
### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```
REPLACE:
```
### AD-1356 S2 -- The tool-effect table, with the routine tier running (2026-11-02, #1722)

- *Scope.* `tools/effect_tiers.py` (new), `agent_work_runner.py` (`_run`, `task_text`; `AGENT_WORK_READ_TOOL_IDS` removed), tests. Contract `prompts/ad-1356-s2-tool-effect-table.md`.
- *Table.* Tiers by name only; a tool the table does not list, every `mcp:` tool and a non-str id are critical. Seeded from the plan-mode read set and the effect broker's classes, never from `derive_tool_permission`.
- *Run start.* `ToolCallConfinement.tool_ids` is `routine_tool_ids(reads_confined=bool(permitted_read_roots(runtime)))`, read once per run. Whether a tool is registered (S1.1) and whether the agent holds it (the registry's permission check) stay decided at each call.
- *Read policy.* `read_file` and `codebase_read_source` are routine only while `security_infra.read_roots` is set, and critical otherwise. `_recovery_read` still decides a `read_file` of a workspace result while they are critical. `codebase_query` reads only the codebase index and is routine either way.
- *list_files.* Elevated: it resolves its path without the read policy, so `read_roots` does not confine it.
- *MCP.* Not listed, so critical; AD-1019b's `McpToolRisk` mapping arrives with S3, its first consumer.
- *Plan mode.* Not shared: plan mode bars state change and admits off-ship reads; routine bars off-ship reach and admits confined file reads.
- *Rejected.* Intersecting with the registry at run start (tools are registered inside the run); narrowing to the agent's offer in the executor; routine file reads with no roots set; `list_files` routine; plan mode as the table; mapping `McpToolRisk` with no consumer; AD-676's `ActionRiskRegistry`.
- *Residual.* Recorded limits L1 to L11 of the contract.
- *Reversal.* Revert the AD-1356 S2 commits.

### BF-947 -- An agent-work item waits for each call it filed, and each approval admits its call once (2026-11-02, #1724)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (its Bug Tracker is for BFs).

## 9. What this does NOT change

- `ToolCallConfinement`, `_invoke_reserved_body`, S1.1's refusal, the gate (`_gate_for`), `_recovery_read`, `CarriedResults`, BF-947's park and admission.
- Plan mode (`PLAN_MODE_TOOL_IDS`), DM turns, every unconfined run, AD-1154's inbox (`_APPROVAL_INBOX_TOOL_IDS` = `{"browser"}`).
- `classify_capability_request`, AD-1213 routing, repair dispatch (S3's scope). `ActionRiskRegistry`.
- `security/file_access.py` and the swe_harness tools (`list_files`'s reach is a separate BF).
- `BLOCKED_REASON` and the filed rationale (L7). `SystemConfig`, `EventType`, persisted schemas, request kinds.
- The AD-level replay script (#1722 Acceptance 1) needs S3.

## 10. Mutation rows (one campaign of record on M1's head; M2 changes no `src` file)

The Line cells hold the source line without its leading indentation. Prefix `RX` (scoped to this contract).

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| RX-1 | `src/probos/tools/effect_tiers.py` | `return TIER_ROUTINE if reads_confined or tool_id not in READ_POLICY_TOOL_IDS else TIER_CRITICAL` | `return TIER_ROUTINE` | `test_with_no_read_roots_the_same_read_is_filed_for_the_captain_and_does_not_run` |
| RX-2 | `src/probos/tools/effect_tiers.py` | `return TIER_ROUTINE if reads_confined or tool_id not in READ_POLICY_TOOL_IDS else TIER_CRITICAL` | `return TIER_ROUTINE if tool_id not in READ_POLICY_TOOL_IDS else TIER_CRITICAL` | `test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed` |
| RX-3 | `src/probos/tools/effect_tiers.py` | `READ_POLICY_TOOL_IDS: Final[frozenset[str]] = frozenset({"codebase_read_source", "read_file"})` | `READ_POLICY_TOOL_IDS: Final[frozenset[str]] = frozenset({"codebase_query", "codebase_read_source", "read_file"})` | `test_codebase_query_runs_without_approval_while_read_roots_are_unset` |
| RX-4 | `src/probos/tools/effect_tiers.py` | `"codebase_query", "codebase_read_source", "read_file",` | `"codebase_query", "codebase_read_source", "read_file", "list_files",` | `test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed` |
| RX-5 | `src/probos/tools/effect_tiers.py` | `if tool_id in ELEVATED_TOOL_IDS:` | `if False:` | `test_the_table_pins_each_tier_and_anything_it_does_not_list_is_critical` |
| RX-6 | `src/probos/tools/effect_tiers.py` | `if type(tool_id) is not str:` | `if False:` | `test_the_table_pins_each_tier_and_anything_it_does_not_list_is_critical` |
| RX-7 | `src/probos/tools/effect_tiers.py` | `tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE` | `tool_id for tool_id in ROUTINE_TOOL_IDS` | `test_with_no_read_roots_the_same_read_is_filed_for_the_captain_and_does_not_run` |
| RX-8 | `src/probos/agent_work_runner.py` | `routine_tool_ids(reads_confined=bool(permitted_read_roots(self._runtime))),` | `routine_tool_ids(reads_confined=True),` | `test_with_no_read_roots_the_same_read_is_filed_for_the_captain_and_does_not_run` |
| RX-9 | `src/probos/agent_work_runner.py` | `routine_tool_ids(reads_confined=bool(permitted_read_roots(self._runtime))),` | `routine_tool_ids(reads_confined=False),` | `test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed` |
| RX-10 | `src/probos/agent_work_runner.py` | `"Routine reads run directly. A call to another tool may be filed for approval instead of running; this work "` | `"Read-only tools run directly. A call to another tool may be filed for approval instead of running; this work "` | `test_with_read_roots_set_a_file_read_runs_without_approval_and_list_files_is_still_filed` |

How each killer dies:
- **ET4 (RX-1, RX-7, RX-8):** the read runs, so nothing is filed, and `[request] =` raises.
- **ET3 (RX-2, RX-9):** `read_file` is filed, so there are two requests and `[request] =` raises.
- **ET3 (RX-4):** `list_files` runs, so nothing is filed.
- **ET3 (RX-10):** `_seen(rig, "Routine reads run directly.")` is False.
- **ET5 (RX-3):** `codebase_query` is filed, the item parks, and `index.asked` is `[]`.
- **ET1 (RX-5):** the elevated loop fails.
- **ET1 (RX-6):** `_Named("read_file")` is routine and `["read_file"]` raises TypeError.

**Campaign of record.** After an unmutated baseline of N1-2 and the edited `test_ad1347_s3_execution.py`, run each row against the file that holds its killer. Record the base tree and the sha256 of each mutated `src` file.

## 11. Recorded limits

- **L1.** The routine set is read once at a run's start. A change to `read_roots` takes effect at the next run (a resumed item is a new run).
- **L2.** A routine tool the agent does not hold is denied by the registry at the call (AD-856), as in an unconfined run, not filed.
- **L3.** With `read_roots` unset, `read_file` and `codebase_read_source` are critical and filed as today. S1.3's recovery read still admits a `read_file` of a workspace-result path. With roots set, `_recovery_read` decides nothing.
- **L4.** `list_files` is elevated until a BF puts it under the read policy. An absolute `path` bypasses both the floor and `read_roots`; its output and error text expose file names (not contents).
- **L5.** `mcp:` tools are critical in S2. S3 adds the `McpToolRisk` mapping.
- **L6.** `discover_work_items` is in plan mode's read set but not in the table, so it is critical and filed as before.
- **L7.** `BLOCKED_REASON` and the filed rationale still say "outside the read-only set", although some filed calls are reads (`list_files`, the web reads, `find_mcp_tool`, and `read_file` with no roots). This predates S2 for the web reads. The text is pinned by `ui/e2e/fixtures/ad1347-agent-work-approvals.json` and `test_ad1347_s3_execution.py:657`.
- **L8.** `permitted_read_roots` logs one warning per run for each unusable configured entry. An all-unusable list still confines reads to the workspace root and counts as confined.
- **L9.** `read_roots` confines the filesystem reads that resolve through `resolve_for_runtime` ship-wide (Q5), the Captain's DM reads included. S2 reads that policy and does not change it.
- **L10.** Elevated has no decider other than the Captain until S3. S3 must also give a rule for a routine tool that is filed because reads are unconfined: `tool_tier` already calls it critical, so `CAPTAIN_RESERVED`.
- **L11.** #1722's replay acceptance will count `list_files` (6 of 28) as elevated, decided by a chief after S3, not routine. The Captain-routed count stays 3.

## 12. Verified Against Codebase (2026-11-02, on `0ac7bdf3`)

```
Read src/probos/agent_work_runner.py :1-135 (13-15 docstring, S1-written; 61-63 imports; 70-77 AGENT_WORK_READ_TOOL_IDS;
  92 BLOCKED_REASON), :180-210 (185-197 _recovery_read), :212-238 (220, 234 task_text), :380-420 (396-421 __init__;
  421 self._tools = tools), :465-494 (480 self._tools.check_and_invoke), :580-739 (610-617 confinement; 691-738 _gate_for)
git diff e9140fcb 0ac7bdf3 -- src/probos/agent_work_runner.py -> S1 hunks at 13-17, 39, 125-129, 142-148, 182-198, 691-716
grep "AgentWorkRunner(" src -> startup/finalize.py:3535-3541 (3537 tools=runtime.tool_registry)
Read startup/finalize.py :3500-3535 (3509-3510 built only while runtime.agent_work is AgentWorkService)
Read cognitive/agentic_dispatch.py :296-386 (319-323 UNREGISTERED_TOOL_REFUSAL; 338-359 ToolCallConfinement, 354 non-empty),
  :800-931 (840-856 S1.1 then confinement order), :1191-1232 (_park_or_admit), :1665/:1717-1760 (_McpTool.tool_id,
  effective_risk), :2960-2988 (registry, DispatchToolExecutor), :3073-3084 (_is_mcp_id, granted_ids),
  :3196-3216 (work_item_status registered inside run), :3436-3467 (event_log_query/oracle_query offer),
  :3560-3608 (offer union; 3606 offer stays whole; 3607-3608 confine_calls); grep -> 230 _APPROVAL_INBOX_TOOL_IDS
Read tools/registry.py :85-270 (206 get; 215 list_ids; 224 list_tools); grep tools/executor.py -> 832-841 required
Read tools/__init__.py (docstring only); ls src/probos/tools
Read security/file_access.py :105-206 (160 permitted check; 165-194 permitted_read_roots; 197-206 protected), :373-411
Read cognitive/swe_harness/tools.py :245-248 _resolve_path; :320-344; :395-505 ReadFileTool (448 resolve_for_runtime;
  482 read_text); :508-604 ListFilesTool (542 _resolve_path), CodebaseQueryTool (597-601 index.query);
  :728-787 CodebaseReadSourceTool (754 resolve_for_runtime); :1367-1409 register_native_swe_tools, read_perms
grep cognitive/codebase_index.py -> 143-145 source_root; runtime.py:1703 codebase_index attribute
Read cognitive/agent_mode.py :1-90 (59-83 PLAN_MODE_TOOL_IDS); execution/effect_broker.py :322-357 (_classify)
Read integrations/mcp_bridge/risk.py (whole; 34-51 McpToolRisk, resolve_tool_risk)
Read delegated_approvals.py :150-199 (168-172 classify_capability_request; Q1)
Read admission/__init__.py (8-9 imports service); scripts/check_architecture_principles.py :40-89 (80-85 ranked packages)
Read scripts/gen_ad_ledger.py :126-142; pyproject.toml requires-python >=3.12
Read tests/test_ad1347_s3_execution.py :1-39 (35 import), :40-288 (148-239 rig; 193 SystemConfig(); 283-288 _seen),
  :560-599 (582-583), :706-742 (730); tests/test_ad1356_s1_recovery_reads.py (whole; 28-46 helpers);
  tests/test_ad1156_plan_execute_mode.py :1-100 (81-84 _WITHHELD), :905-942
Read PROGRESS.md :1-4; grep "^### (AD-1356 S1|BF-947|Explicit delegation models)" DECISIONS.md -> 1244, 1255, 1266
```

## Absence Verified (2026-11-02, on `0ac7bdf3`)

```
A1 CLAIM: outside logs/ and prompts/, AGENT_WORK_READ_TOOL_IDS is named only in agent_work_runner.py
          and tests/test_ad1347_s3_execution.py.
   RUN:   Grep "PLAN_MODE_TOOL_IDS|AGENT_WORK_READ_TOOL_IDS", glob !{logs,prompts}/**
   FOUND: agent_work_runner.py:14, :74, :615 (:70 matched PLAN_MODE_TOOL_IDS only); test_ad1347_s3_execution.py:35,
          :582, :583, :730; DECISIONS.md:11653 (a PLAN_MODE_TOOL_IDS hit; history, not edited); the
          rest are PLAN_MODE_TOOL_IDS hits (agent_mode.py, cognitive_agent.py, test_ad1156, test_ad1240, test_ad1323)
   HOLDS: yes; every src and tests hit is edited by P1-1, P1-3, P1-6, P1-7, P1-9, P1-10
A2 CLAIM: no .py, .ts or .tsx file names effect_tiers, routine_tool_ids, tool_tier, ROUTINE_TOOL_IDS, ELEVATED_TOOL_IDS,
          READ_POLICY_TOOL_IDS or TIER_ROUTINE/ELEVATED/CRITICAL.
   RUN:   Grep "effect_tiers|routine_tool_ids|ROUTINE_TOOL_IDS|ELEVATED_TOOL_IDS|READ_POLICY_TOOL_IDS|TIER_ROUTINE|
          TIER_ELEVATED|TIER_CRITICAL|def tool_tier", glob *.{py,ts,tsx}
   FOUND: none
   HOLDS: yes
A3 CLAIM: list_files resolves its path without the read policy.
   RUN:   Grep "resolve_for_runtime|permitted_read_roots|class (ListFilesTool|CodebaseQueryTool|CodebaseReadSourceTool)" src/probos
   FOUND: swe_harness/tools.py :58, :62 (imports), :340, :448 (ReadFileTool), :754 (CodebaseReadSourceTool), :914; class
          lines :508, :568, :728; ListFilesTool's body (:531-565) calls _resolve_path (:542), which returns an absolute
          path unchanged (:245-248); other hits are in agents/*, copilot_adapter.py, repository_instructions.py
   HOLDS: yes
A4 CLAIM: no test reads agent_work_runner.py's source.
   RUN:   Grep "agent_work_runner.*(read_text|getsource)|(read_text|getsource).*agent_work_runner|agent_work_runner\.py" tests
   FOUND: none
   HOLDS: yes
A5 CLAIM: "Read-only tools run directly" and "the read-only tools you hold" appear only in agent_work_runner.py;
          no test asserts "Tool named" or "run directly".
   RUN:   Grep "Read-only tools run directly|read-only tools you hold" !{logs,prompts}/**; Grep "Tool named|run directly" tests
   FOUND: agent_work_runner.py:220, :234; tests: none
   HOLDS: yes
A6 CLAIM: no agent-work test (test_ad1347_*, test_bf947_*, test_ad1356_s1_*) sets read_roots, so they all run with
          reads unconfined and S2's membership change does not move them.
   RUN:   Grep "read_roots|security_infra|AGENT_WORK_READ_TOOL_IDS|ToolCallConfinement\(" tests
   FOUND: read_roots/security_infra only in test_ad1025b, ad1185, ad1200 (x2), ad1240_tool_result_delivery, ad1270a,
          ad1278, ad1315, ad1346_admission_sink_wiring, ad456b, ad456, bf751, bf758, bf763, bf908, bf910,
          conftest_egress_policy_isolation; the rig sets SystemConfig() (test_ad1347_s3_execution.py:193) and
          test_bf758:377 asserts read_roots defaults to []
   HOLDS: yes
A7 CLAIM: AD-1154's inbox parks no routine tool.
   RUN:   Grep "^_APPROVAL_INBOX_TOOL_IDS" agentic_dispatch.py
   FOUND: :230 frozenset({"browser"})
   HOLDS: yes
```

**Correction to #1722:** "the runner holds no tool registry (`agent_work_runner.py:258`)" is wrong on this head. `finalize.py:3537` passes `tools=runtime.tool_registry`, and the runner keeps it at `:421` and uses it at `:480`.

**Not verified (the orchestrator measures):**
- ET3: an ordinary `read_file` under the AD-1347 rig returns the file's text. S1's RR1 proved only workspace-result reads.
- `SystemConfig.model_copy(update={"security_infra": ...})` in `_native` (S1 used the same call for `execution`).
- Whether `list_files` patterns with `..` escape the project tree under Python 3.12. D3 does not rest on it: the absolute-`path` case already bypasses the policy, as A3 shows.

## 13. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:**
  - No method is added to `AgentWorkRunner` (stays 15).
  - `tool_tier` and `routine_tool_ids` are module functions.
  - `agent_work_runner` imports `tools.effect_tiers` at module level and `security.file_access` lazily. Neither is a ranked package, so there is no layer finding.
  - No `create_task` and no database connect.
- **`check_dormant_classes.py --check`:** no new class in `src`.
- **Config:** no field. F-553 and the AD-1152 golden do not move, because AD-1152's observations run with no confinement.
- **`gen_ad_ledger.py --check`:** passes once M2 regenerates the ledger. The heads carry no status keyword in their first 120 characters.
- **Collection:** one new file under `tests/`.

## 14. Prior Art and Blind Spots

- **Internal prior work:**
  - AD-1156's allowlist shape (membership only; new tools withheld): adopted for the table.
  - AD-1347 S3 D4 (the offer stays whole and the call decides): kept.
  - BF-758's opt-in read policy: the routine condition reads it.
  - AD-1019b's `McpToolRisk`: arrives with S3.
  - AD-676: tier names only.
  - #1722 Q3, Q5 and Q6: applied.
- **External:**
  - MCP tool annotations separate read-only from open-world. Adopted as the axes: read-only and closed-world is routine; read-only and open-world is elevated. Rejected trusting server-declared hints, which the spec says MUST be treated as untrusted unless the server is trusted ([MCP tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools), [annotation guide](https://www.mcpbundles.com/guides/tool-annotations)).
  - Cursor's Auto-review runs allowlisted calls and sends the rest to a classifier or the user, and calls allowlists best-effort guardrails, not a boundary. Adapted: the routine tier is not the boundary here. The read policy, the registry's grant check and S1.1 stay beneath it, and the tier fails closed while the read policy is off ([Cursor run modes](https://cursor.com/docs/agent/run-modes), [Auto-review release](https://releases.sh/release/rel_CKUKVIG-gOOnIpjk0uC_x-cursor-introduces-auto-review-run-mode-for-safer-agent-execution)).
  - `docs/research/reference-projects.md`, judged on 2026-11-02:
    - Cursor was overdue (2026-06-13, 90-day interval) and was examined.
    - Considered, deferred: SWE-agent (2026-03-20; its sandboxing is not approval tiering), MCP Apps (2026-04-08; UI, not tool authority), AG-UI (never; not relevant).
- **Blind spots found:**
  1. `list_files` ignores the read policy (L4; a BF to file).
  2. Tools are registered inside the run, so intersecting with the registry at run start would file them on a fresh boot (D2).
  3. #1722's "no registry" premise is wrong (§12).
  4. The task text claimed all read-only tools run directly (P1-5).
  5. S3 needs a rule for a routine tool filed while reads are unconfined (L10).
  6. The replay count shifts `list_files` to elevated (L11).

## 15. Diff Reviewer: properties to verify (run the new file and the edited test file, then the greps)

1. `routine_tool_ids(reads_confined=False)` is exactly the ten old tools plus `codebase_query`. `routine_tool_ids(reads_confined=True)` adds `read_file` and `codebase_read_source`.
2. `tool_tier` answers `critical` for every id not in the routine or elevated sets, for every non-str id and for every str subclass.
3. `_run` builds the confinement from `routine_tool_ids(reads_confined=bool(permitted_read_roots(self._runtime)))` once per run. Nothing else in the runner, the executor or the gate changes.
4. With `read_roots` empty, no call that was filed before S2 runs unfiled, except `codebase_query`.
5. `AGENT_WORK_READ_TOOL_IDS` is gone from `src` and `tests`.
6. `effect_tiers.py` imports only the stdlib, and no `src` file imports `governance.risk_tiers` for it.
7. Every added or rewritten docstring, comment, agent-facing text and test docstring is true of the head.
8. No config field, `EventType`, request kind or persisted key is added.
9. ET3, ET4 and ET5 each start from a work item and end at the run, the filing or the board.

## 16. Acceptance criteria

1. ET3: with `read_roots` set, a `read_file` under a root runs in agent work with nothing filed, and `list_files` in the same run is filed.
2. ET4: with `read_roots` unset, the same `read_file` is filed, the item parks, and the text never reaches the model.
3. ET5: `codebase_query` runs with nothing filed while `read_roots` is unset.
4. ET1 and ET2: the table is pinned; anything it does not list is critical; routine members draw on the plan-mode read set plus three pinned code readers.
5. Every §10 mutant is killed; G1 and G2 pass; the §13 checks pass; the broad gate's receipt is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
