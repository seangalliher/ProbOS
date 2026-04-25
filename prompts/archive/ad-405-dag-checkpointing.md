# AD-405: Step-Level DAG Checkpointing

## Context

ProbOS's DAG execution pipeline (`DAGExecutor.execute()` in `decomposer.py`) runs entirely in-memory. If the process crashes mid-DAG, all progress is lost — nodes that already completed (including expensive LLM calls) must be re-executed. There is zero intermediate state persistence.

**The fix:** Persist DAG state to JSON after each node completes. On restart, detect incomplete checkpoints and log them. The DAG's existing `get_ready_nodes()` is already idempotent based on `node.status` — restoring statuses + results from a checkpoint would make the DAG resume correctly.

## Part 1: Checkpoint Module

### Create `src/probos/cognitive/checkpoint.py`

```python
"""Step-level DAG checkpoint persistence (AD-405).

Persists DAG execution state to JSON files so interrupted DAGs
can be detected and eventually resumed. Each checkpoint captures
all node statuses and results at the time of the last state change.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
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
```

**Implementation notes:**
- `_serialize_result` uses duck typing (`hasattr(result, "intent_id")`) instead of importing `IntentResult` to avoid circular imports.
- `write_checkpoint` preserves `created_at` from existing checkpoint on updates.
- `restore_dag` imports `TaskDAG`/`TaskNode` locally to avoid circular imports.
- Checkpoint files use `dag.id` as filename — one file per DAG, overwritten on each node completion.

## Part 2: Integrate into DAGExecutor

### Modify `src/probos/cognitive/decomposer.py`

**2a.** Add import at the top with other cognitive imports:

```python
from probos.cognitive.checkpoint import write_checkpoint, delete_checkpoint
```

**2b.** Add `checkpoint_dir` parameter to `DAGExecutor.__init__()`:

Find the `__init__` method (currently at line ~651). Add `checkpoint_dir: Path | None = None` as the last parameter:

```python
def __init__(
    self,
    runtime: Any,
    timeout: float = 60.0,
    attention: Any | None = None,
    escalation_manager: Any | None = None,
    checkpoint_dir: Any | None = None,  # AD-405
) -> None:
    self.runtime = runtime
    self.timeout = timeout
    self.attention = attention
    self.escalation_manager = escalation_manager
    self._checkpoint_dir = checkpoint_dir
    self._dag_start: float = 0.0
```

**2c.** Modify `execute()` to bracket with checkpoint create/delete.

Find the `execute` method (currently at line ~664). Change it so:
1. After `results: dict[str, Any] = {}` and before the try block, write the initial checkpoint.
2. In the `except asyncio.TimeoutError` block, after marking nodes failed, update checkpoint before deleting.
3. Add a `finally` that deletes the checkpoint after the try/except completes.

The key change: move the `return` outside the try/except so the `finally` can run:

```python
async def execute(self, dag, on_event=None):
    results: dict[str, Any] = {}

    if self.escalation_manager:
        self.escalation_manager.user_wait_seconds = 0.0
    self._dag_start = time.monotonic()

    # Write initial checkpoint (AD-405)
    if self._checkpoint_dir:
        write_checkpoint(self._checkpoint_dir, dag, results)

    try:
        await self._execute_dag(dag, results, on_event=on_event)
    except asyncio.TimeoutError:
        logger.error("DAG execution timed out after %.0fs", self.timeout)
        for node in dag.nodes:
            if node.status == "pending":
                node.status = "failed"
                results[node.id] = {"error": "DAG execution timed out"}
    finally:
        # Delete checkpoint on completion (AD-405)
        if self._checkpoint_dir:
            delete_checkpoint(self._checkpoint_dir, dag.id)

    return {
        "dag": dag,
        "results": results,
        "complete": dag.is_complete(),
        "node_count": len(dag.nodes),
        "completed_count": sum(1 for n in dag.nodes if n.status == "completed"),
        "failed_count": sum(1 for n in dag.nodes if n.status == "failed"),
    }
```

**Important:** Read the current `execute()` method carefully. The existing structure has the return inside the try block. You need to restructure so `finally` can clean up the checkpoint.

**2d.** Add checkpoint updates in `_execute_node()`.

Find `_execute_node()` (currently at line ~777). Add a checkpoint write after each place where `node.status` is set to `"completed"` or `"failed"`. There are several status-setting points:

After lines like `node.status = "completed"` or `node.status = "failed"`, and after the `on_event` calls, add:

```python
if self._checkpoint_dir:
    write_checkpoint(self._checkpoint_dir, dag, results)
```

**Important:** The `_execute_node` method has the `dag` parameter available (it's passed in). Add the checkpoint write at the END of the method, after all status/event handling, not at each individual status-set point. This avoids multiple writes per node:

Find the end of the try block in `_execute_node`, just before the except. After both the `on_event("node_complete")` and `on_event("node_failed")` calls, add:

```python
# Checkpoint after node state change (AD-405)
if self._checkpoint_dir:
    write_checkpoint(self._checkpoint_dir, dag, results)
```

Also add it in the `except Exception` block after the node is marked failed (whether via escalation or directly). Read the full `_execute_node` method to find all the exit paths.

## Part 3: Wire into Runtime

### Modify `src/probos/runtime.py`

**3a.** In `__init__()`, after `self._data_dir = Path(data_dir) ...` (line ~117), add:

```python
self._checkpoint_dir = self._data_dir / "checkpoints"
```

**3b.** Modify the DAGExecutor construction (line ~195) to pass `checkpoint_dir`:

```python
self.dag_executor = DAGExecutor(
    runtime=self,
    timeout=cog_cfg.dag_execution_timeout_seconds,
    attention=self.attention,
    escalation_manager=self.escalation_manager,
    checkpoint_dir=self._checkpoint_dir,  # AD-405
)
```

**3c.** In the `start()` method, after all startup initialization is complete, add checkpoint scanning. Find the end of `start()` (search for the last log message or return). Add:

```python
# Scan for abandoned DAG checkpoints from previous session (AD-405)
from probos.cognitive.checkpoint import scan_checkpoints
stale = scan_checkpoints(self._checkpoint_dir)
if stale:
    logger.info(
        "Found %d incomplete DAG checkpoint(s) from previous session",
        len(stale),
    )
    for cp in stale:
        completed = sum(
            1 for s in cp.node_states.values()
            if s.get("status") == "completed"
        )
        logger.info(
            "  - DAG %s: '%s' (%d/%d nodes completed)",
            cp.dag_id[:8], cp.source_text[:60],
            completed, len(cp.node_states),
        )
```

**Important:** Read the current `start()` method to find the right insertion point — it should go after all services are started but before the method returns.

## Files Created/Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/checkpoint.py` | **NEW** — `DAGCheckpoint`, `write_checkpoint()`, `load_checkpoint()`, `delete_checkpoint()`, `scan_checkpoints()`, `restore_dag()`, serializers |
| `src/probos/cognitive/decomposer.py` | Add `checkpoint_dir` param to `DAGExecutor`, checkpoint create/update/delete in `execute()` and `_execute_node()` |
| `src/probos/runtime.py` | Create `_checkpoint_dir`, pass to `DAGExecutor`, scan stale checkpoints on `start()` |

## Testing

### New tests in `tests/test_checkpoint.py`:

1. **write_checkpoint creates file** — Create a TaskDAG with 2 nodes, write checkpoint, verify JSON file exists at expected path with correct structure.
2. **load_checkpoint roundtrip** — Write then load, verify all fields match (dag_id, source_text, node_states, timestamps).
3. **write_checkpoint preserves created_at** — Write, read created_at, write again, verify created_at unchanged but updated_at changed.
4. **delete_checkpoint removes file** — Write, verify exists, delete, verify gone. Delete non-existent returns False.
5. **scan_checkpoints finds all** — Write 3 checkpoints, scan, verify 3 returned sorted by updated_at desc.
6. **scan_checkpoints empty dir** — Scan non-existent or empty dir → empty list.
7. **_serialize_result handles IntentResult** — Create an IntentResult, serialize, verify JSON-safe dict with correct keys.
8. **_serialize_result handles nested dicts** — Dict with list of IntentResults in "results" key.
9. **_serialize_result handles primitives** — str, int, float, bool, None all pass through.
10. **_serialize_result handles unknown types** — Custom object falls back to str().
11. **restore_dag recreates DAG** — Write checkpoint with mixed statuses, restore, verify node statuses and results match, verify `get_ready_nodes()` returns correct nodes.
12. **restore_dag with dependencies** — DAG with t1→t2 dependency, t1 completed, verify t2 shows up in `get_ready_nodes()` after restore.
13. **DAGExecutor creates and deletes checkpoint** — Mock runtime with `submit_intent` returning success. Execute DAG with `checkpoint_dir=tmp_path`. Verify checkpoint file is created during execution and deleted after completion.
14. **DAGExecutor updates checkpoint per node** — Use `on_event` callback to verify checkpoint file is updated after each node completes (read file, check node_states).

### Regression:

```
uv run pytest tests/test_checkpoint.py tests/test_decomposer.py -v
```

Then:
```
uv run pytest tests/ --tb=short
```

## What NOT to Build (Phase 1)

- **Shell `/resume` command** — Phase 2.
- **Captain approval gates** — Phase 2.
- **Builder chunk checkpointing** — Separate AD.
- **Checkpoint expiry/cleanup** — Phase 2.
- **HXI checkpoint visualization** — Phase 2.

## Commit Message

```
Add step-level DAG checkpointing for crash recovery (AD-405)

Persist DAG node states to JSON after each step completion.
Checkpoint created at DAG start, updated per-node, deleted on
completion. On startup, abandoned checkpoints logged for Captain
awareness. Foundation for Phase 2 resume command and approval gates.
```
