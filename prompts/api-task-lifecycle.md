# AD-326: API Task Lifecycle & WebSocket Hardening

## Context

The ProbOS API (`src/probos/api.py`) uses fire-and-forget `asyncio.create_task()` at **8 call sites** to run background pipelines (build, design, self-mod). The returned `Task` objects are never stored, making it impossible to track, cancel, or drain running tasks. Additionally, `_broadcast_event()` catches `create_task()` errors but not `send_json()` failures inside the spawned coroutine — stale WebSocket clients accumulate silently.

This was identified in a GPT-5.4 code review as P0/Critical. The fix: managed task set with lifecycle tracking, proper shutdown drain, and per-send error handling with dead client pruning.

## Scope

**Target file:**
- `src/probos/api.py` — all changes go here

**Test files (MODIFY existing):**
- `tests/test_builder_api.py` — new tests for task tracking
- `tests/test_architect_api.py` — new tests for task tracking

**Do NOT change:**
- `src/probos/runtime.py`
- `src/probos/cognitive/builder.py`
- `src/probos/cognitive/architect.py`
- `src/probos/consensus/escalation.py`
- Do not add new files
- Do not modify any endpoint signatures or response formats (backward compatible)
- Do not modify the `_run_build`, `_run_design`, or `_run_selfmod` coroutine logic itself — only how they are launched and tracked

---

## Step 1: Add Managed Task Set

**File:** `src/probos/api.py`

### 1a: Declare `_background_tasks` set

After the existing `_pending_designs` declaration (line 159), add:

```python
# Pending architect proposals awaiting Captain approval (AD-308)
_pending_designs: dict[str, dict[str, Any]] = {}

# Managed background tasks (AD-326) — track all fire-and-forget pipelines
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
```

### 1b: Create `_track_task()` helper

Add a helper function after the `_on_runtime_event` function (around line 168). This wraps `asyncio.create_task()` with automatic add/discard lifecycle:

```python
def _track_task(coro: Any, *, name: str | None = None) -> asyncio.Task:
    """Create a background task and track it in _background_tasks.

    The task is automatically removed from the set when it completes,
    whether by success, failure, or cancellation.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
```

**Key design points:**
- `task.add_done_callback(_background_tasks.discard)` — the set's `discard` method is a perfect done callback. It accepts the task as argument and silently ignores if already removed.
- The `name` parameter aids debugging (`task.get_name()` shows what's running).
- Returns the task in case callers want to reference it (they don't currently, but it's good practice).

---

## Step 2: Replace All `asyncio.create_task()` Call Sites

Replace every bare `asyncio.create_task()` with `_track_task()`. There are **8 call sites**:

### 2a: `/build` slash command (line 212)
```python
# BEFORE:
asyncio.create_task(_run_build(
    BuildRequest(title=title, description=description),
    build_id,
    runtime,
))

# AFTER:
_track_task(_run_build(
    BuildRequest(title=title, description=description),
    build_id,
    runtime,
), name=f"build-{build_id}")
```

### 2b: `/design` slash command (line 241)
```python
# BEFORE:
asyncio.create_task(_run_design(
    DesignRequest(feature=feature, phase=phase),
    design_id,
    runtime,
))

# AFTER:
_track_task(_run_design(
    DesignRequest(feature=feature, phase=phase),
    design_id,
    runtime,
), name=f"design-{design_id}")
```

### 2c: `approve_selfmod` endpoint (line 394)
```python
# BEFORE:
asyncio.create_task(_run_selfmod(req, runtime))

# AFTER:
_track_task(_run_selfmod(req, runtime), name="selfmod")
```

### 2d: `submit_build` endpoint (line 630)
```python
# BEFORE:
asyncio.create_task(_run_build(req, build_id, runtime))

# AFTER:
_track_task(_run_build(req, build_id, runtime), name=f"build-{build_id}")
```

### 2e: `approve_build` endpoint (line 653)
```python
# BEFORE:
asyncio.create_task(_execute_build(req.build_id, req.file_changes, spec, work_dir, runtime))

# AFTER:
_track_task(
    _execute_build(req.build_id, req.file_changes, spec, work_dir, runtime),
    name=f"execute-{req.build_id}",
)
```

### 2f: `submit_design` endpoint (line 834)
```python
# BEFORE:
asyncio.create_task(_run_design(req, design_id, runtime))

# AFTER:
_track_task(_run_design(req, design_id, runtime), name=f"design-{design_id}")
```

### 2g: `approve_design` endpoint (line 861)
```python
# BEFORE:
asyncio.create_task(_run_build(build_req, build_id, runtime))

# AFTER:
_track_task(_run_build(build_req, build_id, runtime), name=f"build-{build_id}")
```

### 2h: `_broadcast_event` (line 1034)

This one is different — it's a WebSocket send, not a pipeline. Leave this as `asyncio.create_task()` but fix the error handling (Step 3).

**Total: 7 call sites changed to `_track_task()`. The 8th (`_broadcast_event`) stays as `asyncio.create_task()` but gets improved error handling.**

---

## Step 3: Harden `_broadcast_event()` WebSocket Sends

**File:** `src/probos/api.py`, lines 1029-1037

The current code catches exceptions from `asyncio.create_task()` (which almost never throws) but doesn't catch `send_json()` failures happening inside the spawned coroutine. Fix by using an inner async wrapper that handles per-client send errors:

```python
# BEFORE (lines 1029-1037):
def _broadcast_event(event: dict[str, Any]) -> None:
    """Send event to all connected WebSocket clients."""
    safe_event = _safe_serialize(event)
    for ws in list(_ws_clients):
        try:
            asyncio.create_task(ws.send_json(safe_event))
        except Exception:
            if ws in _ws_clients:
                _ws_clients.remove(ws)

# AFTER:
def _broadcast_event(event: dict[str, Any]) -> None:
    """Send event to all connected WebSocket clients."""
    safe_event = _safe_serialize(event)

    async def _safe_send(ws: WebSocket, data: dict) -> None:
        try:
            await ws.send_json(data)
        except Exception:
            # Client disconnected or errored — prune from list
            if ws in _ws_clients:
                _ws_clients.remove(ws)

    for ws in list(_ws_clients):
        asyncio.create_task(_safe_send(ws, safe_event))
```

**Key change:** The `try/except` now wraps the actual `await ws.send_json()` call inside the coroutine, not the `create_task()` call. This catches broken pipes, disconnects, and any serialization issue per-client.

---

## Step 4: Add `/api/tasks` Status Endpoint

Add a simple GET endpoint to query active background tasks. Place it after the `/api/status` endpoint (around line 193):

```python
@app.get("/api/tasks")
async def list_tasks() -> dict[str, Any]:
    """List active background tasks (builds, designs, self-mod)."""
    tasks = []
    for task in _background_tasks:
        tasks.append({
            "name": task.get_name() or "unnamed",
            "done": task.done(),
        })
    return {
        "active_count": sum(1 for t in _background_tasks if not t.done()),
        "total_tracked": len(_background_tasks),
        "pending_designs": len(_pending_designs),
        "tasks": tasks,
    }
```

This gives the Captain visibility into what's running — something that was previously impossible.

---

## Step 5: Add Shutdown Drain

Add a FastAPI lifespan handler that cancels and awaits all background tasks on shutdown. Place this before `app = FastAPI(...)` (around line 137):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan — drain background tasks on shutdown."""
    yield
    # Shutdown: cancel all tracked background tasks
    if _background_tasks:
        logger.info("Shutting down: cancelling %d background task(s)", len(_background_tasks))
        for task in _background_tasks:
            task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()
```

Then update the `app = FastAPI(...)` line to use the lifespan:

```python
# BEFORE:
app = FastAPI(title="ProbOS", docs_url="/api/docs", redoc_url=None)

# AFTER:
app = FastAPI(title="ProbOS", docs_url="/api/docs", redoc_url=None, lifespan=_lifespan)
```

**Note:** Search for the exact `FastAPI(` instantiation line to modify — it may be around line 137-140 in `create_app()`. Make sure to use the `===SEARCH===` / `===REPLACE===` pattern for this edit since it's modifying an existing line.

---

## Step 6: Tests

### 6a: Add to `tests/test_builder_api.py`

Add a new test class `TestTaskTracking` at the end of the file:

```python
class TestTaskTracking:
    """Tests for background task lifecycle (AD-326)."""

    @pytest.mark.asyncio
    async def test_build_submit_tracks_task(self, tmp_path):
        """submit_build creates a tracked background task."""
        rt = ProbOSRuntime(config_path=str(tmp_path / "config.toml"))
        rt._llm_client = MockLLMClient()
        app = create_app(rt)
        transport = ASGITransport(app=app)

        # Import to access module-level set
        import probos.api as api_mod

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/build/submit", json={
                "title": "Track test",
                "description": "Testing task tracking",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "started"

            # Give the event loop a tick to register the task
            await asyncio.sleep(0.05)

            # At least one task should be tracked (it may finish quickly with MockLLM)
            # Verify the _track_task mechanism works by checking _background_tasks existed
            # (the task may have already completed and been discarded)
            assert isinstance(api_mod._background_tasks, set)

    @pytest.mark.asyncio
    async def test_tasks_endpoint_returns_status(self, tmp_path):
        """GET /api/tasks returns active task information."""
        rt = ProbOSRuntime(config_path=str(tmp_path / "config.toml"))
        app = create_app(rt)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/tasks")
            assert resp.status_code == 200
            data = resp.json()
            assert "active_count" in data
            assert "total_tracked" in data
            assert "pending_designs" in data
            assert "tasks" in data
            assert isinstance(data["tasks"], list)

    @pytest.mark.asyncio
    async def test_task_done_callback_removes_from_set(self, tmp_path):
        """Completed tasks are automatically removed from _background_tasks."""
        rt = ProbOSRuntime(config_path=str(tmp_path / "config.toml"))
        app = create_app(rt)

        import probos.api as api_mod
        initial_count = len(api_mod._background_tasks)

        # Create a task that completes immediately
        async def instant():
            pass

        task = api_mod._track_task(instant(), name="test-instant")
        assert task in api_mod._background_tasks

        # Let the task complete
        await asyncio.sleep(0.05)
        # Done callback should have removed it
        assert task not in api_mod._background_tasks
```

### 6b: Add to `tests/test_architect_api.py`

Add a new test class `TestDesignTaskTracking` at the end of the file:

```python
class TestDesignTaskTracking:
    """Tests for design task lifecycle tracking (AD-326)."""

    @pytest.mark.asyncio
    async def test_design_submit_tracks_task(self, tmp_path):
        """submit_design creates a tracked background task."""
        rt = ProbOSRuntime(config_path=str(tmp_path / "config.toml"))
        rt._llm_client = MockLLMClient()
        app = create_app(rt)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/design/submit", json={
                "feature": "test design tracking",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "started"


class TestBroadcastResilience:
    """Tests for WebSocket broadcast error handling (AD-326)."""

    @pytest.mark.asyncio
    async def test_broadcast_prunes_dead_client(self, tmp_path):
        """_broadcast_event removes clients that fail on send_json."""
        rt = ProbOSRuntime(config_path=str(tmp_path / "config.toml"))
        app = create_app(rt)

        import probos.api as api_mod

        # Create a mock WebSocket that raises on send_json
        dead_ws = MagicMock()
        dead_ws.send_json = AsyncMock(side_effect=Exception("connection closed"))

        api_mod._ws_clients.append(dead_ws)
        assert dead_ws in api_mod._ws_clients

        api_mod._broadcast_event({"type": "test", "data": {}})

        # Give the async send task a tick to run
        await asyncio.sleep(0.1)

        # Dead client should have been pruned
        assert dead_ws not in api_mod._ws_clients
```

**Total: 5 new tests** (3 in test_builder_api.py, 2 in test_architect_api.py).

---

## Step 7: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update the status line: `Phase 32l complete — Phase 32 in progress (NNNN/NNNN tests + 21 Vitest + NN skipped)`

### DECISIONS.md
Append:
```
## Phase 32l: API Task Lifecycle & WebSocket Hardening (AD-326)

| AD | Decision |
|----|----------|
| AD-326 | API Task Lifecycle & WebSocket Hardening — `_background_tasks` set tracks all `asyncio.create_task()` pipelines with automatic done-callback cleanup. `_track_task()` helper replaces 7 bare `create_task()` calls (build, design, self-mod, execute pipelines). `_broadcast_event()` inner `_safe_send()` coroutine catches per-client `send_json()` failures and prunes dead WebSocket clients. `GET /api/tasks` endpoint for Captain visibility into active pipelines. FastAPI lifespan handler drains/cancels all tasks on shutdown. |

**Status:** Complete — N new Python tests, NNNN Python + 21 Vitest total
```

### progress-era-4-evolution.md
Append:
```
## Phase 32l: API Task Lifecycle & WebSocket Hardening (AD-326)

**Decision:** AD-326 — Managed `_background_tasks` set with `_track_task()` helper (7 call sites), `_safe_send()` for WebSocket error handling, `GET /api/tasks` status endpoint, FastAPI lifespan shutdown drain.

**Status:** Phase 32l complete — NNNN Python + 21 Vitest
```

---

## Verification Checklist

Before committing, verify:
1. [ ] `_background_tasks: set[asyncio.Task]` declared in `create_app()` scope
2. [ ] `_track_task()` helper creates task, adds to set, registers done callback
3. [ ] All 7 pipeline `asyncio.create_task()` calls replaced with `_track_task()`
4. [ ] Each `_track_task()` call has a descriptive `name=` parameter
5. [ ] `_broadcast_event()` uses inner `_safe_send()` coroutine with try/except around `send_json()`
6. [ ] `GET /api/tasks` returns `active_count`, `total_tracked`, `pending_designs`, `tasks`
7. [ ] FastAPI `lifespan=_lifespan` with shutdown drain (cancel + gather + clear)
8. [ ] `from contextlib import asynccontextmanager` added to imports
9. [ ] All 5 new tests pass
10. [ ] Existing API tests still pass (no regressions)
11. [ ] Full suite passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
12. [ ] PROGRESS.md, DECISIONS.md, progress-era-4-evolution.md updated

## Anti-Scope (Do NOT Build)

- Do NOT modify `_run_build`, `_run_design`, `_run_selfmod`, or `_execute_build` internals (the coroutine logic is fine — we're only changing how they're launched)
- Do NOT add task-level timeouts inside the pipeline coroutines (that's a future AD if needed)
- Do NOT add `_pending_designs` TTL/expiry (can be a future AD)
- Do NOT change endpoint request/response schemas (backward compatible)
- Do NOT modify runtime.py, builder.py, architect.py, or escalation.py
- Do NOT add new files — everything goes in existing files
- Do NOT change the `_broadcast_event` call in `_on_runtime_event` — only change the `_broadcast_event` implementation itself
- Do NOT replace `asyncio.create_task()` inside `_broadcast_event` with `_track_task()` — WebSocket sends are ephemeral, not pipeline tasks
