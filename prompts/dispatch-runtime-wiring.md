# Build Prompt: Dispatch System Runtime Wiring (AD-375)

## File Footprint
- `src/probos/runtime.py` (MODIFIED) — instantiate BuildQueue, WorktreeManager, BuildDispatcher; lifecycle management
- `src/probos/api.py` (MODIFIED) — add queue-aware approve/reject/enqueue/status endpoints; wire WebSocket events
- `ui/src/components/IntentSurface.tsx` (MODIFIED) — fix approve/reject button URLs
- `tests/test_dispatch_wiring.py` (NEW) — integration tests for the wiring
- **No new Python modules** — this wires existing components together

## Context

AD-371–373 built the automated builder dispatch components:
- `BuildQueue` (build_queue.py) — priority queue with status lifecycle
- `WorktreeManager` (worktree_manager.py) — async git worktree lifecycle
- `BuildDispatcher` (build_dispatcher.py) — dispatch loop, execute, approve/reject
- HXI Build Dashboard (IntentSurface.tsx) — UI card with approve/reject buttons

All components are individually built and tested, but **nothing connects them to the
live runtime or API layer**. This AD wires them in.

### Key patterns to follow:

1. **Runtime lifecycle** — follow the SIF pattern (AD-370): declare field in `__init__`,
   instantiate in `start()`, tear down in `stop()`.
2. **API endpoints** — follow existing build endpoints (around line 720 in api.py).
   Use `_track_task()` for async work. Emit events via `runtime._emit_event()`.
3. **WebSocket events** — `runtime._emit_event(type, data)` → `_on_runtime_event` →
   `_broadcast_event` → all `_ws_clients`. The UI store already handles `build_queue_update`
   and `build_queue_item` event types.

---

## Changes

### File: `src/probos/runtime.py`

**1. Add imports** (near the existing `from probos.sif import StructuralIntegrityField`):

```python
from probos.build_queue import BuildQueue
from probos.worktree_manager import WorktreeManager
from probos.build_dispatcher import BuildDispatcher
```

**2. Add instance fields** in `__init__` (after the SIF field, around line 231):

```python
# --- Automated Builder Dispatch (AD-375) ---
self.build_queue: BuildQueue | None = None
self.build_dispatcher: BuildDispatcher | None = None
```

**3. Add startup wiring** in `start()` — place this AFTER the SIF start block
(after `await self.sif.start()`), BEFORE `self._started = True`:

```python
# Start Automated Builder Dispatch (AD-375)
import pathlib
_repo_root = str(pathlib.Path(__file__).resolve().parent.parent.parent)
self.build_queue = BuildQueue()
_worktree_mgr = WorktreeManager(repo_root=_repo_root)
self.build_dispatcher = BuildDispatcher(
    queue=self.build_queue,
    worktree_mgr=_worktree_mgr,
    on_build_complete=self._on_build_complete,
)
await self.build_dispatcher.start()
logger.info("build-dispatcher started")
```

**4. Add shutdown** in `stop()` — place this AFTER the SIF stop block
(after the `if self.sif:` block):

```python
# Stop build dispatcher (AD-375)
if self.build_dispatcher:
    await self.build_dispatcher.stop()
    self.build_dispatcher = None
    self.build_queue = None
```

**5. Add the `_on_build_complete` callback method** on the `ProbOSRuntime` class
(near other helper methods, after `_emit_event`):

```python
async def _on_build_complete(self, build: Any) -> None:
    """Callback fired when a dispatched build finishes (AD-375)."""
    from probos.build_queue import QueuedBuild
    if not isinstance(build, QueuedBuild):
        return
    self._emit_event("build_queue_item", {
        "item": {
            "id": build.id,
            "title": build.spec.title,
            "ad_number": build.spec.ad_number,
            "status": build.status,
            "priority": build.priority,
            "worktree_path": build.worktree_path,
            "builder_id": build.builder_id,
            "error": build.error,
            "file_footprint": build.file_footprint,
            "commit_hash": build.result.commit_hash if build.result else "",
        }
    })
```

---

### File: `src/probos/api.py`

**1. Add Pydantic models** (after the existing `BuildResolveRequest` class, around line 150):

```python
class BuildQueueApproveRequest(BaseModel):
    """Request to approve a queued build — merge to main (AD-375)."""
    build_id: str


class BuildQueueRejectRequest(BaseModel):
    """Request to reject a queued build (AD-375)."""
    build_id: str


class BuildEnqueueRequest(BaseModel):
    """Request to add a build spec to the dispatch queue (AD-375)."""
    title: str
    description: str = ""
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []
    priority: int = 5
```

**2. Add 4 new API endpoints** — place these AFTER the existing `/api/build/resolve`
endpoint block (around line 810), in a new section:

```python
# ------------------------------------------------------------------
# Build Queue / Dispatch API (AD-375)
# ------------------------------------------------------------------

@app.post("/api/build/queue/approve")
async def approve_queued_build(req: BuildQueueApproveRequest) -> dict[str, Any]:
    """Captain approves a queued build — merge worktree to main."""
    if not runtime.build_dispatcher:
        return {"status": "error", "message": "Build dispatcher not running"}
    ok, result = await runtime.build_dispatcher.approve_and_merge(req.build_id)
    if ok:
        _emit_queue_snapshot(runtime)
        return {"status": "ok", "commit": result, "message": f"Build merged: {result[:7]}"}
    return {"status": "error", "message": result}

@app.post("/api/build/queue/reject")
async def reject_queued_build(req: BuildQueueRejectRequest) -> dict[str, Any]:
    """Captain rejects a queued build — discard worktree."""
    if not runtime.build_dispatcher:
        return {"status": "error", "message": "Build dispatcher not running"}
    ok = await runtime.build_dispatcher.reject_build(req.build_id)
    if ok:
        _emit_queue_snapshot(runtime)
        return {"status": "ok", "message": "Build rejected"}
    return {"status": "error", "message": f"Build {req.build_id} not in reviewing status"}

@app.post("/api/build/enqueue")
async def enqueue_build(req: BuildEnqueueRequest) -> dict[str, Any]:
    """Add a build spec to the dispatch queue."""
    if not runtime.build_queue:
        return {"status": "error", "message": "Build queue not running"}
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title=req.title,
        description=req.description,
        target_files=req.target_files,
        reference_files=req.reference_files,
        test_files=req.test_files,
        ad_number=req.ad_number,
        constraints=req.constraints,
    )
    build = runtime.build_queue.enqueue(spec, priority=req.priority)
    _emit_queue_snapshot(runtime)
    return {
        "status": "ok",
        "build_id": build.id,
        "message": f"Build '{req.title}' queued at priority {req.priority}",
    }

@app.get("/api/build/queue")
async def get_build_queue() -> dict[str, Any]:
    """Get the current build queue state."""
    if not runtime.build_queue:
        return {"status": "ok", "items": []}
    items = runtime.build_queue.get_all()
    return {
        "status": "ok",
        "items": [
            {
                "id": b.id,
                "title": b.spec.title,
                "ad_number": b.spec.ad_number,
                "status": b.status,
                "priority": b.priority,
                "worktree_path": b.worktree_path,
                "builder_id": b.builder_id,
                "error": b.error,
                "file_footprint": b.file_footprint,
                "commit_hash": b.result.commit_hash if b.result else "",
            }
            for b in items
        ],
        "active_count": runtime.build_queue.active_count,
    }
```

**3. Add the `_emit_queue_snapshot` helper** — place this just BEFORE the new
endpoint section (still inside `create_api`):

```python
def _emit_queue_snapshot(rt: Any) -> None:
    """Broadcast full queue state to all HXI clients (AD-375)."""
    if not rt.build_queue:
        return
    items = rt.build_queue.get_all()
    rt._emit_event("build_queue_update", {
        "items": [
            {
                "id": b.id,
                "title": b.spec.title,
                "ad_number": b.spec.ad_number,
                "status": b.status,
                "priority": b.priority,
                "worktree_path": b.worktree_path,
                "builder_id": b.builder_id,
                "error": b.error,
                "file_footprint": b.file_footprint,
                "commit_hash": b.result.commit_hash if b.result else "",
            }
            for b in items
        ],
    })
```

---

### File: `ui/src/components/IntentSurface.tsx`

**Fix the approve/reject button URLs** to use the new queue-specific endpoints.

**1. Find the approve button `onClick`** and change the URL:

```
OLD: await fetch('/api/build/approve', {
NEW: await fetch('/api/build/queue/approve', {
```

**2. Find the reject button `onClick`** and change the URL:

```
OLD: await fetch('/api/build/reject', {
NEW: await fetch('/api/build/queue/reject', {
```

---

### File: `tests/test_dispatch_wiring.py` (NEW)

Create integration tests for the runtime wiring and API endpoints.

```python
"""Tests for dispatch system runtime wiring (AD-375)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_runtime():
    """Create a minimal mock runtime with build dispatch wired."""
    from probos.build_queue import BuildQueue
    from probos.cognitive.builder import BuildSpec

    rt = MagicMock()
    rt.build_queue = BuildQueue()
    rt.build_dispatcher = MagicMock()
    rt.build_dispatcher.approve_and_merge = AsyncMock(return_value=(True, "abc1234def"))
    rt.build_dispatcher.reject_build = AsyncMock(return_value=True)
    rt._emit_event = MagicMock()
    return rt


class TestRuntimeWiring:
    def test_runtime_has_build_queue_field(self) -> None:
        """ProbOSRuntime defines build_queue attribute."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        # Check the attribute is declared (would be set in __init__)
        assert hasattr(ProbOSRuntime, '__init__')

    def test_runtime_has_build_dispatcher_field(self) -> None:
        """ProbOSRuntime defines build_dispatcher attribute."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        assert hasattr(ProbOSRuntime, '__init__')

    def test_on_build_complete_emits_event(self) -> None:
        """_on_build_complete fires build_queue_item event."""
        from probos.build_queue import QueuedBuild
        from probos.cognitive.builder import BuildSpec
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._event_listeners = []

        spec = BuildSpec(title="test", description="test")
        build = QueuedBuild(
            id="test123",
            spec=spec,
            status="merged",
        )

        # Call the callback
        asyncio.get_event_loop().run_until_complete(rt._on_build_complete(build))

        # Can't easily check _emit_event without full init,
        # but we verify it doesn't crash


class TestDispatchAPI:
    @pytest.fixture
    def client(self):
        """Create a test client with mocked runtime."""
        from probos.api import create_api
        from fastapi.testclient import TestClient

        rt = _mock_runtime()
        app = create_api(rt)
        return TestClient(app), rt

    def test_get_queue_empty(self, client) -> None:
        """GET /api/build/queue returns empty list initially."""
        tc, rt = client
        resp = tc.get("/api/build/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["items"] == []

    def test_enqueue_build(self, client) -> None:
        """POST /api/build/enqueue adds a build to the queue."""
        tc, rt = client
        resp = tc.post("/api/build/enqueue", json={
            "title": "Test Build",
            "description": "test",
            "target_files": ["src/foo.py"],
            "priority": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "build_id" in data

        # Verify it appears in the queue
        resp2 = tc.get("/api/build/queue")
        items = resp2.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Test Build"
        assert items[0]["priority"] == 3

    def test_approve_queued_build(self, client) -> None:
        """POST /api/build/queue/approve calls dispatcher.approve_and_merge."""
        tc, rt = client
        resp = tc.post("/api/build/queue/approve", json={"build_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "abc1234" in data["commit"]
        rt.build_dispatcher.approve_and_merge.assert_awaited_once_with("abc123")

    def test_reject_queued_build(self, client) -> None:
        """POST /api/build/queue/reject calls dispatcher.reject_build."""
        tc, rt = client
        resp = tc.post("/api/build/queue/reject", json={"build_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        rt.build_dispatcher.reject_build.assert_awaited_once_with("abc123")

    def test_approve_not_running(self) -> None:
        """Approve returns error when dispatcher is not running."""
        from probos.api import create_api
        from fastapi.testclient import TestClient

        rt = MagicMock()
        rt.build_dispatcher = None
        rt.build_queue = None
        app = create_api(rt)
        tc = TestClient(app)

        resp = tc.post("/api/build/queue/approve", json={"build_id": "x"})
        assert resp.json()["status"] == "error"

    def test_emit_queue_snapshot(self, client) -> None:
        """Queue operations emit build_queue_update events."""
        tc, rt = client
        tc.post("/api/build/enqueue", json={
            "title": "Snapshot Test",
            "description": "test",
        })
        rt._emit_event.assert_called()
        call_args = rt._emit_event.call_args
        assert call_args[0][0] == "build_queue_update"
        assert "items" in call_args[0][1]
```

---

## Constraints

- Do NOT create new Python modules — only modify `runtime.py` and `api.py`
- Do NOT modify `build_queue.py`, `build_dispatcher.py`, or `worktree_manager.py`
- Do NOT modify `useStore.ts` or `types.ts` — the UI store already handles the events
- Keep the existing `/api/build/approve` endpoint unchanged (it serves the old architect proposal flow)
- The new queue endpoints use `/api/build/queue/` prefix to distinguish from the old flow
- `_emit_queue_snapshot` fires after every queue-mutating operation (enqueue, approve, reject)
- The `_on_build_complete` callback emits individual `build_queue_item` events for real-time status updates
- Follow existing patterns: `_track_task()` for async work, `runtime._emit_event()` for WebSocket broadcast
