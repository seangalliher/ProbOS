"""Tests for step-level DAG checkpointing (AD-405)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.checkpoint import (
    DAGCheckpoint,
    _serialize_result,
    delete_checkpoint,
    load_checkpoint,
    restore_dag,
    scan_checkpoints,
    write_checkpoint,
)
from probos.cognitive.decomposer import DAGExecutor
from probos.types import IntentResult, TaskDAG, TaskNode


def _make_dag(
    node_count: int = 2,
    source_text: str = "test query",
    depends: dict[int, list[str]] | None = None,
) -> TaskDAG:
    """Create a TaskDAG with the given number of nodes."""
    nodes = []
    for i in range(node_count):
        node_id = f"t{i+1}"
        dep_list = depends.get(i, []) if depends else []
        nodes.append(TaskNode(
            id=node_id,
            intent=f"test_intent_{i+1}",
            params={"key": f"val{i+1}"},
            depends_on=dep_list,
        ))
    return TaskDAG(nodes=nodes, source_text=source_text, id="dag-test-001")


# ---------------------------------------------------------------------------
# write_checkpoint / load_checkpoint
# ---------------------------------------------------------------------------


class TestWriteAndLoadCheckpoint:

    def test_write_checkpoint_creates_file(self, tmp_path):
        """Write checkpoint, verify JSON file exists with correct structure."""
        dag = _make_dag(2)
        results: dict = {}

        path = write_checkpoint(tmp_path, dag, results)

        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dag_id"] == "dag-test-001"
        assert data["source_text"] == "test query"
        assert "t1" in data["node_states"]
        assert "t2" in data["node_states"]
        assert data["node_states"]["t1"]["status"] == "pending"

    def test_load_checkpoint_roundtrip(self, tmp_path):
        """Write then load, verify all fields match."""
        dag = _make_dag(2)
        dag.nodes[0].status = "completed"
        results = {"t1": {"success": True}}

        write_checkpoint(tmp_path, dag, results)
        cp = load_checkpoint(tmp_path / f"{dag.id}.json")

        assert cp.dag_id == "dag-test-001"
        assert cp.source_text == "test query"
        assert cp.node_states["t1"]["status"] == "completed"
        assert cp.node_states["t2"]["status"] == "pending"
        assert cp.created_at != ""
        assert cp.updated_at != ""

    def test_write_checkpoint_preserves_created_at(self, tmp_path):
        """Write twice, verify created_at unchanged but updated_at changed."""
        dag = _make_dag(1)
        results: dict = {}

        write_checkpoint(tmp_path, dag, results)
        cp1 = load_checkpoint(tmp_path / f"{dag.id}.json")
        created1 = cp1.created_at

        # Small delay to ensure updated_at changes
        import time
        time.sleep(0.01)

        dag.nodes[0].status = "completed"
        write_checkpoint(tmp_path, dag, results)
        cp2 = load_checkpoint(tmp_path / f"{dag.id}.json")

        assert cp2.created_at == created1
        assert cp2.updated_at >= cp1.updated_at

    def test_write_creates_directory(self, tmp_path):
        """write_checkpoint creates checkpoint_dir if it doesn't exist."""
        nested = tmp_path / "deep" / "nested" / "checkpoints"
        dag = _make_dag(1)
        path = write_checkpoint(nested, dag, {})
        assert path.exists()


# ---------------------------------------------------------------------------
# delete_checkpoint
# ---------------------------------------------------------------------------


class TestDeleteCheckpoint:

    def test_delete_removes_file(self, tmp_path):
        """Write, verify exists, delete, verify gone."""
        dag = _make_dag(1)
        write_checkpoint(tmp_path, dag, {})
        assert (tmp_path / f"{dag.id}.json").exists()

        result = delete_checkpoint(tmp_path, dag.id)
        assert result is True
        assert not (tmp_path / f"{dag.id}.json").exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        """Delete non-existent returns False."""
        result = delete_checkpoint(tmp_path, "nonexistent-id")
        assert result is False


# ---------------------------------------------------------------------------
# scan_checkpoints
# ---------------------------------------------------------------------------


class TestScanCheckpoints:

    def test_scan_finds_all(self, tmp_path):
        """Write 3 checkpoints, scan, verify 3 returned sorted by updated_at desc."""
        for i in range(3):
            dag = TaskDAG(
                nodes=[TaskNode(id="n1", intent="test")],
                source_text=f"query {i}",
                id=f"dag-{i}",
            )
            write_checkpoint(tmp_path, dag, {})
            time.sleep(0.01)  # ensure different timestamps

        checkpoints = scan_checkpoints(tmp_path)
        assert len(checkpoints) == 3
        # Should be sorted by updated_at descending
        assert checkpoints[0].updated_at >= checkpoints[1].updated_at
        assert checkpoints[1].updated_at >= checkpoints[2].updated_at

    def test_scan_empty_dir(self, tmp_path):
        """Scan empty dir → empty list."""
        assert scan_checkpoints(tmp_path) == []

    def test_scan_nonexistent_dir(self, tmp_path):
        """Scan non-existent dir → empty list."""
        assert scan_checkpoints(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# _serialize_result
# ---------------------------------------------------------------------------


class TestSerializeResult:

    def test_handles_intent_result(self):
        """IntentResult serialized to JSON-safe dict with correct keys."""
        ir = IntentResult(
            intent_id="i1",
            agent_id="a1",
            success=True,
            result={"data": "hello"},
            error=None,
            confidence=0.9,
        )
        serialized = _serialize_result(ir)
        assert serialized["intent_id"] == "i1"
        assert serialized["agent_id"] == "a1"
        assert serialized["success"] is True
        assert serialized["result"] == {"data": "hello"}
        assert serialized["confidence"] == 0.9

    def test_handles_nested_dicts(self):
        """Dict with list of IntentResults in 'results' key."""
        ir = IntentResult(intent_id="i1", agent_id="a1", success=True)
        nested = {"results": [ir], "count": 1}
        serialized = _serialize_result(nested)
        assert len(serialized["results"]) == 1
        assert serialized["results"][0]["intent_id"] == "i1"
        assert serialized["count"] == 1

    def test_handles_primitives(self):
        """str, int, float, bool, None all pass through."""
        assert _serialize_result("hello") == "hello"
        assert _serialize_result(42) == 42
        assert _serialize_result(3.14) == 3.14
        assert _serialize_result(True) is True
        assert _serialize_result(None) is None

    def test_handles_unknown_types(self):
        """Custom object falls back to str()."""
        class Custom:
            def __str__(self):
                return "custom_obj"

        result = _serialize_result(Custom())
        assert result == "custom_obj"

    def test_handles_list(self):
        """Lists are recursively serialized."""
        result = _serialize_result([1, "two", {"three": 3}])
        assert result == [1, "two", {"three": 3}]


# ---------------------------------------------------------------------------
# restore_dag
# ---------------------------------------------------------------------------


class TestRestoreDag:

    def test_restore_recreates_dag(self, tmp_path):
        """Write checkpoint with mixed statuses, restore, verify."""
        dag = _make_dag(3)
        dag.nodes[0].status = "completed"
        dag.nodes[1].status = "failed"
        # node 2 stays pending
        results = {
            "t1": {"success": True, "data": "result1"},
            "t2": {"error": "something failed"},
        }

        write_checkpoint(tmp_path, dag, results)
        cp = load_checkpoint(tmp_path / f"{dag.id}.json")
        restored_dag, restored_results = restore_dag(cp)

        assert restored_dag.id == "dag-test-001"
        assert len(restored_dag.nodes) == 3
        assert restored_dag.nodes[0].status == "completed"
        assert restored_dag.nodes[1].status == "failed"
        assert restored_dag.nodes[2].status == "pending"
        assert "t1" in restored_results
        assert "t2" in restored_results

    def test_restore_with_dependencies(self, tmp_path):
        """DAG with t1→t2 dependency, t1 completed, verify t2 in get_ready_nodes()."""
        dag = _make_dag(2, depends={1: ["t1"]})
        dag.nodes[0].status = "completed"
        results = {"t1": {"success": True}}

        write_checkpoint(tmp_path, dag, results)
        cp = load_checkpoint(tmp_path / f"{dag.id}.json")
        restored_dag, _ = restore_dag(cp)

        ready = restored_dag.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_restore_preserves_source_text(self, tmp_path):
        """Source text is preserved across write/restore cycle."""
        dag = _make_dag(1, source_text="deploy the fleet")
        write_checkpoint(tmp_path, dag, {})
        cp = load_checkpoint(tmp_path / f"{dag.id}.json")
        restored_dag, _ = restore_dag(cp)
        assert restored_dag.source_text == "deploy the fleet"


# ---------------------------------------------------------------------------
# DAGExecutor integration
# ---------------------------------------------------------------------------


class TestDAGExecutorCheckpointing:

    @pytest.mark.asyncio
    async def test_executor_creates_and_deletes_checkpoint(self, tmp_path):
        """Execute DAG with checkpoint_dir. File created during, deleted after."""
        mock_runtime = MagicMock()
        mock_runtime.submit_intent = AsyncMock(return_value=[
            IntentResult(intent_id="i", agent_id="a", success=True, result={"data": "ok"}),
        ])

        executor = DAGExecutor(
            runtime=mock_runtime,
            timeout=30.0,
            checkpoint_dir=tmp_path,
        )

        dag = _make_dag(1)
        result = await executor.execute(dag)

        assert result["completed_count"] == 1
        # Checkpoint should be deleted after completion
        assert not (tmp_path / f"{dag.id}.json").exists()

    @pytest.mark.asyncio
    async def test_executor_updates_checkpoint_per_node(self, tmp_path):
        """Verify checkpoint file is updated after each node completes."""
        checkpoint_snapshots = []

        mock_runtime = MagicMock()
        mock_runtime.submit_intent = AsyncMock(return_value=[
            IntentResult(intent_id="i", agent_id="a", success=True, result={"data": "ok"}),
        ])

        executor = DAGExecutor(
            runtime=mock_runtime,
            timeout=30.0,
            checkpoint_dir=tmp_path,
        )

        dag = _make_dag(2)

        async def capture_event(event_name, data):
            if event_name == "node_complete":
                # Read checkpoint at this point
                cp_path = tmp_path / f"{dag.id}.json"
                if cp_path.exists():
                    cp_data = json.loads(cp_path.read_text(encoding="utf-8"))
                    checkpoint_snapshots.append(cp_data)

        await executor.execute(dag, on_event=capture_event)

        # We should have captured checkpoint state during execution
        # (checkpoint is written after on_event, so the capture reads the
        # previous write — at least the initial checkpoint should exist)
        assert len(checkpoint_snapshots) >= 1
