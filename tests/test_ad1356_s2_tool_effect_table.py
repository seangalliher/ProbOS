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
