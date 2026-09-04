"""BF-817 (#1281): resume re-decomposes, and now says so.

`PersistentTaskManager.resume_dag` calls `restore_dag(checkpoint)` and then
re-feeds `checkpoint.source_text` to `process_fn`. The restored DAG and its
completed results were computed and silently discarded, so the checkpoint
machinery's shape -- `checkpoint.py` faithfully serialising every node
including `use_consensus`, `restore_dag` faithfully rebuilding it -- implied a
continuation guarantee the live path never delivered. That surprise derailed a
rationale in #1242.

The decision recorded by this issue is that re-decomposition STAYS: a checkpoint
can be arbitrarily stale and re-planning against current ship state is the safer
recovery. What changes is that the cost is now surfaced instead of hidden --
completed nodes are counted, warned about, and reported on the resume event.

Same defect class as BF-763/BF-781: machinery whose existence asserts a property
the live path does not provide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from probos.events import EventType
from probos.persistent_tasks import PersistentTaskStore


def _write_checkpoint(
    directory: Path, dag_id: str, *, completed: list[str], pending: list[str]
) -> None:
    """A checkpoint with `completed` nodes already done and `pending` not.

    `restore_dag` reads status and result from `node_states`, NOT from the node
    dicts in `dag_json`. An earlier version of this fixture put them inline and
    the completed count came back 0, which is the sort of silently-empty probe
    that proves nothing.
    """
    nodes: list[dict[str, Any]] = [
        {
            "id": node_id,
            "intent": "noop",
            "params": {},
            "depends_on": [],
            "use_consensus": False,
        }
        for node_id in [*completed, *pending]
    ]
    node_states: dict[str, Any] = {
        node_id: {"status": "completed", "result": {"ok": True, "node": node_id}}
        for node_id in completed
    }
    for node_id in pending:
        node_states[node_id] = {"status": "pending", "result": None}

    payload = {
        "dag_id": dag_id,
        "source_text": "deploy the thing",
        "created_at": 0.0,
        "dag_json": {"nodes": nodes},
        "node_states": node_states,
    }
    (directory / f"{dag_id}.json").write_text(json.dumps(payload), encoding="utf-8")


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []
        self.processed: list[str] = []

    def emit(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    async def process(self, text: str, **_kw: Any) -> str:
        self.processed.append(text)
        return "reprocessed"


def _store(tmp_path: Path, recorder: _Recorder) -> PersistentTaskStore:
    return PersistentTaskStore(
        emit_event=recorder.emit,
        process_fn=recorder.process,
        checkpoint_dir=str(tmp_path),
    )


class TestResumeRedecomposesAndReportsTheCost:
    @pytest.mark.asyncio
    async def test_it_reprocesses_the_source_text_rather_than_the_plan(self, tmp_path):
        """The recorded decision: resume re-plans, it does not continue."""
        recorder = _Recorder()
        _write_checkpoint(tmp_path, "dag1", completed=["a"], pending=["b"])

        out = await _store(tmp_path, recorder).resume_dag("dag1")

        assert out["success"] is True
        assert recorder.processed == ["deploy the thing"], (
            "resume must re-feed the source text; if this ever becomes the "
            "restored plan, BF-817's recorded decision has changed and the "
            "docstring must change with it"
        )

    @pytest.mark.asyncio
    async def test_completed_nodes_that_will_be_redone_are_counted_and_warned(
        self, tmp_path, caplog
    ):
        """The cost must be visible, since a redone node repeats side effects.

        This is the assertion that fails against the pre-BF-817 code: the count
        was never computed and the event never carried it.
        """
        recorder = _Recorder()
        _write_checkpoint(tmp_path, "dag2", completed=["a", "b"], pending=["c"])

        with caplog.at_level("WARNING"):
            out = await _store(tmp_path, recorder).resume_dag("dag2")

        assert out["success"] is True
        resumed = [p for t, p in recorder.events if t is EventType.SCHEDULED_TASK_DAG_RESUMED]
        assert resumed, "a resume event must be emitted"
        assert resumed[0]["completed_nodes_redone"] == 2
        assert any("BF-817" in r.message for r in caplog.records), (
            "an operator must be told that completed work is about to repeat"
        )

    @pytest.mark.asyncio
    async def test_a_checkpoint_with_nothing_completed_does_not_warn(
        self, tmp_path, caplog
    ):
        """Control: the warning must discriminate, not fire unconditionally."""
        recorder = _Recorder()
        _write_checkpoint(tmp_path, "dag3", completed=[], pending=["a"])

        with caplog.at_level("WARNING"):
            out = await _store(tmp_path, recorder).resume_dag("dag3")

        assert out["success"] is True
        resumed = [p for t, p in recorder.events if t is EventType.SCHEDULED_TASK_DAG_RESUMED]
        assert resumed[0]["completed_nodes_redone"] == 0
        assert not any("BF-817" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_an_unrecognised_checkpoint_restores_empty_and_still_resumes(
        self, tmp_path
    ):
        """Pins the honest truth: `restore_dag` is NOT a validity check.

        An earlier draft of this test asserted that a malformed checkpoint is
        rejected before reprocessing, and the docstring claimed `restore_dag`
        validates. Both were false -- `DAGCheckpoint` fields default, so an
        unrecognised payload restores as a zero-node DAG and resume proceeds.
        Asserting the comfortable version would have repeated the exact defect
        BF-817 exists to remove, so the real behaviour is pinned instead.
        """
        recorder = _Recorder()
        (tmp_path / "bad.json").write_text('{"not": "a checkpoint"}', encoding="utf-8")

        out = await _store(tmp_path, recorder).resume_dag("bad")

        assert out["success"] is True
        resumed = [p for t, p in recorder.events if t is EventType.SCHEDULED_TASK_DAG_RESUMED]
        assert resumed[0]["completed_nodes_redone"] == 0
        assert len(recorder.processed) == 1, (
            "resume re-decomposes whatever source text the checkpoint carried, "
            "even when nothing else about it was recognisable"
        )
