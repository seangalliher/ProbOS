"""Issue #1375 premises: what the HXI stream says about a work item's terminal state.

A promoted turn's failure is announced by exactly one ``work_item_status_changed``
frame, never by an ``updated``/``created`` frame. A native crew child's failure
never reaches the stream as a record at all: only its parent's
``crew_session_projection`` moves. In both cases the by-ID REST read serves the
same terminal status. A failure while no client is connected reaches the stream
only as the next generation's snapshot. Backend behaviour is unchanged by #1375.
The Vitest crossings replay these captures from a committed fixture, which the
last test regenerates and compares.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import probos

from tests.fixtures import issue1375_work_state_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "tests" / "fixtures" / "issue1375_work_state_bridge.py"
FIXTURE = ROOT / bridge.FIXTURE_PATH


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


def _regenerate(out: Path) -> bytes:
    """The fixture as ``--write`` produces it now, in a fresh interpreter so its clock precedes the backend."""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PROBOS_NATS_ENABLED": "false",
        "HF_HUB_OFFLINE": "1",
    }
    run = subprocess.run(
        [sys.executable, "-u", str(BRIDGE), "--write", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert run.returncode == 0, f"issue1375 fixture generator exited {run.returncode}:\n{run.stderr}"
    return out.read_bytes()


def _wire_texts(scenario: dict[str, Any]) -> list[str]:
    return [
        text for checkpoint in scenario["checkpoints"]
        for text in [*checkpoint["frames"], *(read["body"] for read in checkpoint["rest"].values())]
    ]


def _times(value: Any) -> list[float]:
    if isinstance(value, dict):
        return [found for item in value.values() for found in _times(item)]
    if isinstance(value, list):
        return [found for item in value for found in _times(item)]
    low, high = bridge.EPOCH_BAND
    return [value] if type(value) in (int, float) and low <= value < high else []


def _assert_normalized(document: dict[str, Any]) -> None:
    """Premise: every generated token and every clock read went through its scenario's map."""
    assert sorted(document["scenarios"]) == sorted(bridge.SCENARIOS)
    leaks = ("probos-issue1375-", str(ROOT), json.dumps(str(ROOT))[1:-1])
    for number, name in enumerate(bridge.SCENARIOS, start=1):
        scenario = document["scenarios"][name]
        assert scenario["url_templates"] == list(bridge.FIXTURE_TEMPLATES[name])
        wire = _wire_texts(scenario)
        texts = [*scenario["ids"].values(), *(url for c in scenario["checkpoints"] for url in c["rest"]), *wire]
        tokens = {token for text in texts for token in bridge.TOKEN_PATTERN.findall(text)}
        assert tokens and all(token.replace("-", "").startswith(f"1375{number}") for token in tokens), name
        times = sorted({found for text in wire for found in _times(json.loads(text))})
        # A raw clock read left in any text would break this run of whole-second ranks.
        assert times == [bridge.TIME_BASE + rank for rank in range(len(times))], name
        assert not any(leak in text for leak in leaks for text in texts), name


def _assert_premises(document: dict[str, Any]) -> None:
    """Premise: the fixture still says what each Vitest crossing replays it for."""
    promoted = document["scenarios"]["promoted_failed"]
    item_id = promoted["ids"]["X"]
    first, failed = promoted["checkpoints"]
    assert [first["name"], failed["name"]] == ["promoted", "failed"]
    said = _frames_for(first["frames"] + failed["frames"], item_id)
    assert said[-1]["type"] == "work_item_status_changed"
    last = said[-1]["data"]["work_item"]
    record = json.loads(failed["rest"][f"/api/work-items/{item_id}"]["body"])["work_item"]
    assert (last["status"], record["status"]) == ("failed", "failed")
    # The maps kept the frame's record and the REST record one version.
    assert (record["id"], record["updated_at"]) == (last["id"], last["updated_at"])

    native = document["scenarios"]["native_failed"]
    parent_id, child_id, thread_id = (native["ids"][key] for key in ("P", "X", "T"))
    native_frames = [text for checkpoint in native["checkpoints"] for text in checkpoint["frames"]]
    frames = [json.loads(text) for text in native_frames]
    assert _frames_for(native_frames, child_id) == []
    assert {frame["type"] for frame in frames if child_id in json.dumps(frame["data"])} == {
        "crew_session_projection", "subtask_completed",
    }
    projected = [frame["data"] for frame in frames if frame["type"] == "crew_session_projection"]
    assert {(data["parent_id"], data["thread_id"]) for data in projected} == {(parent_id, thread_id)}
    native_failed = native["checkpoints"][1]
    scope = json.loads(native_failed["rest"][f"/api/work-items?parent_id={parent_id}&limit=1001"]["body"])
    assert [(row["id"], row["status"], row["parent_id"]) for row in scope["work_items"]] == [
        (child_id, "failed", parent_id),
    ]
    crew = json.loads(native_failed["rest"][f"/api/crew-tasks/{parent_id}"]["body"])
    assert crew["session"] == projected[-1]["session"]
    assert crew["session"]["progress"]["failed"] == 1

    restart = document["scenarios"]["restart"]
    item_id = restart["ids"]["X"]
    before, after = restart["checkpoints"]
    assert [json.loads(text)["type"] for text in after["frames"]] == ["state_snapshot"]
    first_snapshot, second_snapshot = json.loads(before["frames"][0]), json.loads(after["frames"][0])
    assert first_snapshot["stream"]["generation"] != second_snapshot["stream"]["generation"]
    rows = [row for row in second_snapshot["data"]["workforce"]["work_items"] if row["id"] == item_id]
    served = json.loads(after["rest"][f"/api/work-items/{item_id}"]["body"])["work_item"]
    held = json.loads(before["rest"][f"/api/work-items/{item_id}"]["body"])["work_item"]
    assert rows == [served] and served["status"] == "failed"
    assert (held["status"], held["updated_at"] < served["updated_at"]) == ("in_progress", True)


def _assert_current(committed: Path, produced: bytes) -> None:
    assert committed.is_file(), f"{committed} is missing; generate it with:\n  {bridge.REGENERATE}"
    # An autocrlf checkout turns the committed LF into CRLF.
    held = committed.read_bytes().replace(b"\r\n", b"\n")
    if held != produced:
        pairs = enumerate(zip(held, produced))
        at = next((i for i, (old, new) in pairs if old != new), min(len(held), len(produced)))
        line = held[:at].count(b"\n") + 1
        lines = sum(old != new for old, new in itertools.zip_longest(held.splitlines(), produced.splitlines()))
        window = slice(max(0, at - 100), at + 100)
        pytest.fail(
            f"{committed} is stale ({lines} line(s) differ, first at line {line});"
            f" regenerate it with:\n  {bridge.REGENERATE}\n"
            f"committed:   ...{held[window].decode('utf-8', 'replace')}...\n"
            f"regenerated: ...{produced[window].decode('utf-8', 'replace')}...",
            pytrace=False,
        )


def test_committed_fixture_is_what_the_bridge_produces_now(tmp_path: Path) -> None:
    assert Path(probos.__file__).resolve().is_relative_to(ROOT / "src")
    bridge.assert_candidate_origins(ROOT)

    produced = _regenerate(tmp_path / "issue1375_work_state.json")

    document = json.loads(produced)
    _assert_normalized(document)
    _assert_premises(document)
    _assert_current(FIXTURE, produced)
