"""Issue #1375 premises: what the HXI stream says about a work item's terminal state.

A promoted turn's failure is announced by exactly one ``work_item_status_changed``
frame, never by an ``updated``/``created`` frame. A native crew child's failure
never reaches the stream as a record at all: only its parent's
``crew_session_projection`` moves. In both cases the by-ID REST read serves the
same terminal status. A failure while no client is connected reaches the stream
only as the next generation's snapshot. Backend behaviour is unchanged by #1375.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import probos

from tests.fixtures import issue1375_work_state_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]


def _frames_for(frames: list[str], item_id: str) -> list[dict[str, Any]]:
    parsed = [json.loads(text) for text in frames]
    return [
        frame for frame in parsed
        if isinstance(frame["data"].get("work_item"), dict)
        and frame["data"]["work_item"].get("id") == item_id
    ]


async def test_promoted_turn_failure_reaches_the_stream_only_as_status_changed(
    tmp_path: Path,
) -> None:
    assert Path(probos.__file__).resolve().is_relative_to(ROOT / "src")
    bridge.assert_candidate_origins(ROOT)
    started = time.monotonic()

    capture = await bridge.run_scenario("promoted_failed", ["/api/work-items/{X}"], tmp_path)

    assert time.monotonic() - started < 20.0
    item_id = capture["ids"]["X"]
    promoted, failed = capture["checkpoints"]
    assert [promoted["name"], failed["name"]] == ["promoted", "failed"]
    assert json.loads(promoted["frames"][0])["type"] == "state_snapshot"
    before = _frames_for(promoted["frames"], item_id)
    assert [frame["type"] for frame in before] == ["work_item_created", "work_item_status_changed"]
    after = _frames_for(failed["frames"], item_id)
    # Exactly one status_changed and no later updated/created frame for X.
    assert [frame["type"] for frame in after] == ["work_item_status_changed"]
    assert after[0]["data"]["work_item"]["status"] == "failed"
    read = failed["rest"][f"/api/work-items/{item_id}"]
    assert read["status"] == 200
    record = json.loads(read["body"])["work_item"]
    assert record["id"] == item_id
    assert record["status"] == "failed" == after[0]["data"]["work_item"]["status"]
    assert record["metadata"]["source"] == "dm_agentic_promotion"


async def test_native_child_failure_reaches_the_stream_only_as_projection(
    tmp_path: Path,
) -> None:
    assert Path(probos.__file__).resolve().is_relative_to(ROOT / "src")
    bridge.assert_candidate_origins(ROOT)
    started = time.monotonic()

    capture = await bridge.run_scenario(
        "native_failed",
        ["/api/work-items/{X}", "/api/work-items?parent_id={P}&limit=1001"],
        tmp_path,
    )

    assert time.monotonic() - started < 20.0
    parent_id, child_id = capture["ids"]["P"], capture["ids"]["X"]
    adopted, failed = capture["checkpoints"]
    assert [adopted["name"], failed["name"]] == ["adopted", "failed"]
    scope_url = f"/api/work-items?parent_id={parent_id}&limit=1001"
    # Premise: before the failure the child was a live, open child of P on REST.
    before = json.loads(adopted["rest"][f"/api/work-items/{child_id}"]["body"])["work_item"]
    assert (before["status"], before["parent_id"]) == ("open", parent_id)
    frames = [json.loads(text) for checkpoint in capture["checkpoints"] for text in checkpoint["frames"]]
    assert [frame["type"] for frame in frames if frame["type"] == "resync_required"] == []
    # The hub never sent the child as a work-item record, so no frame carries it as failed.
    assert _frames_for([text for c in capture["checkpoints"] for text in c["frames"]], child_id) == []
    projected = [frame for frame in frames if frame["type"] == "crew_session_projection"]
    assert projected and {frame["data"]["parent_id"] for frame in projected} == {parent_id}
    assert all(
        (frame["data"]["session"]["progress"]["active_child"] or {}).get("status") != "failed"
        for frame in projected
    )
    # AD-859's subtask_completed names the child's status but carries no work-item record.
    naming = [
        frame for frame in frames
        if frame["type"] != "crew_session_projection" and child_id in json.dumps(frame["data"])
    ]
    assert [(frame["type"], sorted(frame["data"])) for frame in naming] == [
        ("subtask_completed", ["agent_id", "parent_id", "spec_id", "status", "work_item_id"]),
    ]
    after = [
        json.loads(text)["data"] for text in failed["frames"]
        if json.loads(text)["type"] == "crew_session_projection"
    ]
    assert any(data["session"]["progress"]["failed"] >= 1 for data in after)
    assert after[-1]["session"]["progress"] == after[-1]["room_summary"]["session"]["progress"] | {
        "active_child": None,
    }
    assert after[-1]["session"]["progress"]["failed"] == 1
    scope = json.loads(failed["rest"][scope_url]["body"])
    assert failed["rest"][scope_url]["status"] == 200
    assert [(row["id"], row["status"]) for row in scope["work_items"]] == [(child_id, "failed")]
    read = failed["rest"][f"/api/work-items/{child_id}"]
    assert read["status"] == 200
    assert json.loads(read["body"])["work_item"]["status"] == "failed"


async def test_restart_delivers_the_failure_only_through_the_new_generation_snapshot(
    tmp_path: Path,
) -> None:
    assert Path(probos.__file__).resolve().is_relative_to(ROOT / "src")
    bridge.assert_candidate_origins(ROOT)
    started = time.monotonic()

    capture = await bridge.run_scenario("restart", ["/api/work-items/{X}"], tmp_path)

    assert time.monotonic() - started < 20.0
    item_id = capture["ids"]["X"]
    url = f"/api/work-items/{item_id}"
    before, after = capture["checkpoints"]
    assert [before["name"], after["name"]] == ["in_progress", "restarted"]
    first = json.loads(before["frames"][0])
    assert first["type"] == "state_snapshot"
    # Premise: generation 1's last word on X, and its REST read, both say in_progress.
    said = _frames_for(before["frames"], item_id)
    assert said[-1]["type"] == "work_item_status_changed"
    assert said[-1]["data"]["work_item"]["status"] == "in_progress"
    assert json.loads(before["rest"][url]["body"])["work_item"]["status"] == "in_progress"
    # X failed with no client connected: generation 2 sent only its snapshot, and it carries X failed.
    assert [json.loads(text)["type"] for text in after["frames"]] == ["state_snapshot"]
    second = json.loads(after["frames"][0])
    assert second["stream"]["generation"] != first["stream"]["generation"]
    rows = [row for row in second["data"]["workforce"]["work_items"] if row["id"] == item_id]
    assert [row["status"] for row in rows] == ["failed"]
    assert after["rest"][url]["status"] == 200
    assert json.loads(after["rest"][url]["body"])["work_item"]["status"] == "failed"
