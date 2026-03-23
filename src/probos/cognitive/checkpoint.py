"""Step-level DAG checkpoint persistence (AD-405).

Persists DAG execution state to JSON files so interrupted DAGs
can be detected and eventually resumed. Each checkpoint captures
all node statuses and results at the time of the last state change.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DAGCheckpoint:
    """Snapshot of a DAG's execution state."""

    checkpoint_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    dag_id: str = ""
    source_text: str = ""
    created_at: str = ""
    updated_at: str = ""
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    dag_json: dict[str, Any] = field(default_factory=dict)


def write_checkpoint(
    checkpoint_dir: Path,
    dag: Any,  # TaskDAG
    results: dict[str, Any],
) -> Path:
    """Write or update a checkpoint file for the given DAG.

    Creates checkpoint_dir if it doesn't exist. The file is named
    {dag.id}.json and is overwritten on each update.

    Returns the path to the checkpoint file.
    """
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = checkpoint_dir / f"{dag.id}.json"

    # Build node states from the DAG's current state
    node_states: dict[str, dict[str, Any]] = {}
    for node in dag.nodes:
        node_state: dict[str, Any] = {
            "status": node.status,
            "result": _serialize_result(results.get(node.id)),
        }
        if node.status == "failed":
            raw = results.get(node.id)
            if isinstance(raw, dict) and "error" in raw:
                node_state["error"] = raw["error"]
        node_states[node.id] = node_state

    now = datetime.now(timezone.utc).isoformat()

    # Read existing to preserve created_at, or set it
    created_at = now
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            created_at = existing.get("created_at", now)
        except (json.JSONDecodeError, OSError):
            pass

    checkpoint = {
        "checkpoint_id": dag.id,
        "dag_id": dag.id,
        "source_text": dag.source_text,
        "created_at": created_at,
        "updated_at": now,
        "node_states": node_states,
        "dag_json": _serialize_dag(dag),
    }

    path.write_text(json.dumps(checkpoint, indent=2, default=str), encoding="utf-8")
    logger.debug("Checkpoint written: %s (%d nodes)", dag.id[:8], len(node_states))
    return path


def load_checkpoint(path: Path) -> DAGCheckpoint:
    """Load a checkpoint from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return DAGCheckpoint(
        checkpoint_id=data.get("checkpoint_id", ""),
        dag_id=data.get("dag_id", ""),
        source_text=data.get("source_text", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        node_states=data.get("node_states", {}),
        dag_json=data.get("dag_json", {}),
    )


def delete_checkpoint(checkpoint_dir: Path, dag_id: str) -> bool:
    """Delete a checkpoint file. Returns True if file existed and was deleted."""
    path = checkpoint_dir / f"{dag_id}.json"
    if path.exists():
        path.unlink()
        logger.debug("Checkpoint deleted: %s", dag_id[:8])
        return True
    return False


def scan_checkpoints(checkpoint_dir: Path) -> list[DAGCheckpoint]:
    """Scan checkpoint directory for incomplete DAG checkpoints.

    Returns a list of DAGCheckpoint objects, sorted by updated_at descending.
    """
    if not checkpoint_dir.is_dir():
        return []

    checkpoints: list[DAGCheckpoint] = []
    for path in checkpoint_dir.glob("*.json"):
        try:
            cp = load_checkpoint(path)
            checkpoints.append(cp)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("Skipping corrupt checkpoint %s: %s", path.name, e)

    # Sort by most recent first
    checkpoints.sort(key=lambda c: c.updated_at, reverse=True)
    return checkpoints


def restore_dag(checkpoint: DAGCheckpoint) -> tuple[Any, dict[str, Any]]:
    """Restore a TaskDAG and results dict from a checkpoint.

    Returns (TaskDAG, results_dict) with node statuses and results
    restored. The DAG's get_ready_nodes() will return only nodes
    that weren't yet completed.

    Import TaskDAG and TaskNode here to avoid circular imports.
    """
    from probos.types import TaskDAG, TaskNode

    dag_data = checkpoint.dag_json
    nodes: list[TaskNode] = []
    results: dict[str, Any] = {}

    for node_data in dag_data.get("nodes", []):
        node_id = node_data["id"]
        state = checkpoint.node_states.get(node_id, {})

        node = TaskNode(
            id=node_id,
            intent=node_data.get("intent", ""),
            params=node_data.get("params", {}),
            depends_on=node_data.get("depends_on", []),
            use_consensus=node_data.get("use_consensus", False),
            background=node_data.get("background", False),
            status=state.get("status", "pending"),
        )

        # Restore result for completed/failed nodes
        if state.get("result") is not None:
            node.result = state["result"]
            results[node_id] = state["result"]

        nodes.append(node)

    dag = TaskDAG(
        nodes=nodes,
        source_text=dag_data.get("source_text", checkpoint.source_text),
        response=dag_data.get("response", ""),
        reflect=dag_data.get("reflect", False),
        id=checkpoint.dag_id,
    )

    return dag, results


def _serialize_result(result: Any) -> Any:
    """Serialize a node result to a JSON-safe value.

    Handles IntentResult objects, dicts, lists, and primitives.
    Falls back to str() for unknown types.
    """
    if result is None:
        return None

    # Check for IntentResult (avoid import at module level)
    if hasattr(result, "intent_id") and hasattr(result, "agent_id"):
        return {
            "intent_id": result.intent_id,
            "agent_id": str(result.agent_id),
            "success": result.success,
            "result": _serialize_result(result.result),
            "error": result.error,
            "confidence": result.confidence,
        }

    if isinstance(result, dict):
        serialized: dict[str, Any] = {}
        for k, v in result.items():
            if k == "results" and isinstance(v, list):
                # List of IntentResult objects
                serialized[k] = [_serialize_result(item) for item in v]
            else:
                serialized[k] = _serialize_result(v)
        return serialized

    if isinstance(result, list):
        return [_serialize_result(item) for item in result]

    if isinstance(result, (str, int, float, bool)):
        return result

    # Fallback for unknown types
    return str(result)


def _serialize_dag(dag: Any) -> dict[str, Any]:
    """Serialize a TaskDAG to a JSON-safe dict."""
    nodes = []
    for node in dag.nodes:
        nodes.append({
            "id": node.id,
            "intent": node.intent,
            "params": node.params,
            "depends_on": node.depends_on,
            "use_consensus": node.use_consensus,
            "background": node.background,
        })

    return {
        "id": dag.id,
        "source_text": dag.source_text,
        "response": dag.response,
        "reflect": dag.reflect,
        "nodes": nodes,
    }
