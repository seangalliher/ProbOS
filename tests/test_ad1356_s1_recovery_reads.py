"""AD-1356 S1.3 (#1722): the agent-work gate admits a read of a workspace-result path under the workspace root, and the
tool decides whose result it is.

Through the rig of ``tests/test_ad1347_s3_execution.py`` with a real AD-1240 ``WorkspaceResultStore`` (as
``tests/test_ad1240_workspace_results.py`` builds it) as the runtime's workspace and the native tools registered by
``register_native_swe_tools``. On the base this file fails at import (``_recovery_read``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.agent_work_runner import _recovery_read
from probos.capability_request import requests_for_work_item
from probos.cognitive.swe_harness.tools import register_native_swe_tools
from tests.test_ad1240_workspace_results import _capture, make_store
from tests.test_ad1347_s1_agent_work import REASON
from tests.test_ad1347_s3_execution import _call, _final, _pump, _rig, _seen, _thread_in

OWN_TEXT = "Relay drift log: two events, at 00:12 and at 00:47."
FOREIGN_TEXT = "Security sweep notes for deck four."


async def _workspace(rig: Any, tmp_path: Path) -> Any:
    """A started AD-1240 store under ``tmp_path`` as the runtime's workspace root and owner, with the native tools."""
    store = make_store(tmp_path / "workspaces").store
    execution = rig.runtime.config.execution.model_copy(update={"workspace_root": str(store.root)})
    rig.runtime.config = rig.runtime.config.model_copy(update={"execution": execution})
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


# RR1
async def test_a_read_of_the_agents_own_workspace_result_runs_without_approval_and_another_agents_is_refused_by_the_tool(
    tmp_path: Path,
) -> None:
    """Acceptance 5: forge-1's read of its own stored result runs under agent work, the item is done and nothing is
    filed. Its read of worf-1's stored result is not filed either; the item ends done or failed (AD-1240 may end the
    run on the tool's refusal), and worf-1's text never reaches the model."""
    paths: dict[str, str] = {}

    async def read_own(request: Any) -> Any:
        return _call("read_file", {"path": paths["own"]}, "c1")

    async def read_foreign(request: Any) -> Any:
        return _call("read_file", {"path": paths["foreign"]}, "c2")

    script = [read_own, _final("Read my own result."), read_foreign, _final("Read the other result.")]
    async with _rig(tmp_path, script) as rig:
        store = await _workspace(rig, tmp_path)
        try:
            own = await store.store_tool_result(store.bind_agent("forge-1", rig.agents["forge-1"]), _capture(OWN_TEXT))
            foreign = await store.store_tool_result(store.bind_agent("worf-1", rig.agents["worf-1"]), _capture(FOREIGN_TEXT))
            paths.update(own=own.path, foreign=foreign.path)
            own_item = await _self_task(rig, "Read my stored result")
            done = await rig.store.get_work_item(own_item)
            assert done is not None and done.status == "done"
            assert requests_for_work_item(rig.requests, own_item) == []
            assert _seen(rig, OWN_TEXT)
            foreign_item = await _self_task(rig, "Read the security sweep")
            ended = await rig.store.get_work_item(foreign_item)
            assert ended is not None and ended.status in ("done", "failed")
            assert requests_for_work_item(rig.requests, foreign_item) == []
            assert not _seen(rig, FOREIGN_TEXT)
        finally:
            await store.stop()


# RR2
@pytest.mark.parametrize(("tool_id", "path", "accepted"), [
    ("read_file", "{root}/forge/.tool-results/20261011T07Z/abc/payload.jsonl", True),
    ("read_file", "{root}/forge/.TOOL-RESULTS/payload.jsonl", True),
    ("read_file", "{root}/forge/.tool-results/../notes.txt", False),
    ("read_file", "{elsewhere}/.tool-results/payload.jsonl", False),
    ("read_file", ".tool-results/payload.jsonl", False),
    ("read_file", "{root}/forge/notes.txt", False),
    ("list_files", "{root}/forge/.tool-results/payload.jsonl", False),
    ("read_file", "", False),
])
def test_only_an_absolute_result_path_under_a_workspace_root_is_a_recovery_read(
    tmp_path: Path, tool_id: str, path: str, accepted: bool,
) -> None:
    """The tool id is read_file; the path is absolute, has no ``..`` part, has a result-directory part in any case, and
    lies under a root. A non-str path or non-dict parameters are never accepted."""
    root = tmp_path / "workspaces"
    raw = path.format(root=root, elsewhere=tmp_path / "elsewhere")
    assert _recovery_read(tool_id, {"path": raw}, [root]) is accepted
    assert _recovery_read("read_file", {"path": 7}, [root]) is False
    assert _recovery_read("read_file", ["not", "a", "dict"], [root]) is False


# RR3
async def test_a_read_that_climbs_out_of_the_result_directory_is_filed_not_run(tmp_path: Path) -> None:
    """A ``read_file`` whose path names the result directory and then ``..`` is not a recovery read: the gate files it
    and the item parks on the request. The recovery read the run made first is shown to the model and is not kept on
    the parked item (a parked item keeps its results; an ended one drops them)."""
    paths: dict[str, str] = {}

    async def read_own(request: Any) -> Any:
        return _call("read_file", {"path": paths["own"]}, "c1")

    async def climb(request: Any) -> Any:
        return _call("read_file", {"path": paths["climb"]}, "c2")

    async with _rig(tmp_path, [read_own, climb, _final("Waiting for the Captain.")]) as rig:
        store = await _workspace(rig, tmp_path)
        try:
            own = await store.store_tool_result(store.bind_agent("forge-1", rig.agents["forge-1"]), _capture(OWN_TEXT))
            paths.update(own=own.path, climb=str(store.root / "forge" / ".tool-results" / ".." / "notes.txt"))
            item_id = await _self_task(rig, "Read the notes")
            parked = await rig.store.get_work_item(item_id)
            assert parked is not None and parked.status == "blocked"
            assert _seen(rig, OWN_TEXT)
            assert rig.runner.carried.for_agent(item_id, "forge-1") == ()
            [request] = requests_for_work_item(rig.requests, item_id)
            assert (request.status, request.payload["tool_id"], request.payload["params"]) == (
                "pending", "read_file", {"path": paths["climb"]},
            )
        finally:
            await store.stop()
