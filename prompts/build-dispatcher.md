# Build Prompt: BuildDispatcher + SDK Integration (AD-372)

## File Footprint
- `src/probos/build_dispatcher.py` (NEW)
- `tests/test_build_dispatcher.py` (NEW)
- **No existing files modified** — standalone, runtime wiring is a future AD

## Context

AD-372 is the core loop of the Automated Builder Dispatch system. It watches
the BuildQueue (AD-371), allocates worktrees via WorktreeManager (AD-371), and
invokes CopilotBuilderAdapter to generate code — then applies changes via
`execute_approved_build()` with all existing guardrails (syntax validation,
test-before-commit, code review).

### Pipeline flow:

```
BuildQueue.dequeue()
  → check footprint conflicts
  → WorktreeManager.create(build_id)
  → read source files from worktree
  → CopilotBuilderAdapter.execute(spec, file_contents)
  → execute_approved_build(file_blocks, spec, worktree_path)
  → update queue status (reviewing/failed)
  → emit event for Captain review
```

### Existing components (DO NOT modify these):

```python
# AD-371 — src/probos/build_queue.py
class BuildQueue:
    def enqueue(spec, priority=5, file_footprint=None) -> QueuedBuild: ...
    def dequeue() -> QueuedBuild | None: ...
    def update_status(build_id, status, **kwargs) -> bool: ...
    def has_footprint_conflict(footprint) -> bool: ...
    def active_count -> int: ...  # property

class QueuedBuild:
    id: str; spec: BuildSpec; status: str; priority: int
    worktree_path: str; builder_id: str; result: BuildResult | None
    file_footprint: list[str]; error: str

# AD-371 — src/probos/worktree_manager.py
class WorktreeManager:
    def __init__(repo_root, worktree_base=""): ...
    async def create(build_id) -> WorktreeInfo: ...
    async def remove(build_id) -> bool: ...
    async def collect_diff(build_id) -> str: ...
    async def merge_to_main(build_id) -> tuple[bool, str]: ...
    async def cleanup_all() -> int: ...

# AD-351 — src/probos/cognitive/copilot_adapter.py
class CopilotBuilderAdapter:
    def __init__(*, codebase_index=None, runtime=None, model="claude-opus-4.6", cwd="", github_token=""): ...
    @classmethod
    def is_available() -> bool: ...
    async def start() -> None: ...
    async def stop() -> None: ...
    async def execute(spec, file_contents, *, timeout=300.0) -> CopilotBuildResult: ...

class CopilotBuildResult:
    success: bool; file_blocks: list[dict]; raw_output: str
    error: str; session_id: str; model_used: str

# src/probos/cognitive/builder.py
class BuildSpec:
    title: str; description: str; target_files: list[str]
    reference_files: list[str]; test_files: list[str]
    ad_number: int; branch_name: str; constraints: list[str]

class BuildResult:
    success: bool; spec: BuildSpec; files_written: list[str]
    commit_hash: str; error: str; builder_source: str; ...

async def execute_approved_build(
    file_changes, spec, work_dir, run_tests=True,
    max_fix_attempts=2, llm_client=None,
    escalation_hook=None, builder_source="native", runtime=None,
) -> BuildResult: ...
```

---

## Changes

### File: `src/probos/build_dispatcher.py` (NEW)

```python
"""Build Dispatcher — automated builder dispatch loop (AD-372).

Watches the BuildQueue, allocates worktrees, invokes builders,
and applies changes with full guardrails (test, review, commit).
"""
```

**Constructor:**

```python
class BuildDispatcher:
    """Orchestrates automated build execution from queue to completion."""

    def __init__(
        self,
        queue: BuildQueue,
        worktree_mgr: WorktreeManager,
        *,
        max_concurrent: int = 2,
        poll_interval: float = 5.0,
        builder_model: str = "claude-opus-4.6",
        builder_timeout: float = 300.0,
        run_tests: bool = True,
        on_build_complete: Callable[[QueuedBuild], Awaitable[None]] | None = None,
    ) -> None:
```

Parameters:
- `queue` — BuildQueue instance
- `worktree_mgr` — WorktreeManager instance
- `max_concurrent` — Max simultaneous builds (default 2)
- `poll_interval` — Seconds between queue polls (default 5.0)
- `builder_model` — LLM model for the CopilotBuilderAdapter (default "claude-opus-4.6")
- `builder_timeout` — Timeout per build in seconds (default 300.0)
- `run_tests` — Whether to run tests after applying changes (default True)
- `on_build_complete` — Optional async callback when a build finishes (for HXI events). Receives the completed QueuedBuild.

Store these as private attributes: `self._queue`, `self._worktree_mgr`, etc.

Also store:
- `self._task: asyncio.Task | None = None` — the dispatch loop task
- `self._active_tasks: dict[str, asyncio.Task] = {}` — build_id → running task
- `self._running: bool = False`

**Lifecycle methods:**

```python
async def start(self) -> None:
    """Start the dispatch loop."""
    self._running = True
    self._task = asyncio.create_task(self._dispatch_loop())
    logger.info("build-dispatcher started max_concurrent=%d", self._max_concurrent)

async def stop(self) -> None:
    """Stop the dispatch loop and cancel active builds."""
    self._running = False
    # Cancel all active build tasks
    for build_id, task in list(self._active_tasks.items()):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    self._active_tasks.clear()
    # Cancel the dispatch loop
    if self._task:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
    logger.info("build-dispatcher stopped")
```

**Dispatch loop:**

```python
async def _dispatch_loop(self) -> None:
    """Poll the queue and dispatch builds."""
    while self._running:
        await asyncio.sleep(self._poll_interval)
        try:
            await self._try_dispatch()
        except Exception as exc:
            logger.error("dispatch loop error: %s", exc)

async def _try_dispatch(self) -> None:
    """Try to dispatch one queued build if capacity allows."""
    # Clean up finished tasks
    done_ids = [bid for bid, t in self._active_tasks.items() if t.done()]
    for bid in done_ids:
        del self._active_tasks[bid]

    # Check capacity
    if len(self._active_tasks) >= self._max_concurrent:
        return

    # Get next available build (skip if footprint conflicts)
    build = self._find_dispatchable()
    if build is None:
        return

    # Dispatch it
    self._queue.update_status(build.id, "dispatched")
    task = asyncio.create_task(self._execute_build(build))
    self._active_tasks[build.id] = task
    logger.info("build-dispatcher dispatched id=%s title=%r", build.id, build.spec.title)
```

**Find dispatchable build (with conflict detection — absorbs AD-374):**

```python
def _find_dispatchable(self) -> QueuedBuild | None:
    """Find the highest-priority queued build with no footprint conflicts."""
    queued = self._queue.get_by_status("queued")
    # Sort by priority (ascending) then created_at (ascending = FIFO)
    queued.sort(key=lambda b: (b.priority, b.created_at))
    for build in queued:
        if not self._queue.has_footprint_conflict(build.file_footprint):
            return build
    return None  # All queued builds conflict with active builds
```

**Execute a single build (the core pipeline):**

```python
async def _execute_build(self, build: QueuedBuild) -> None:
    """Execute a single build: worktree → adapter → apply → result."""
    worktree_info = None
    try:
        # 1. Create worktree
        worktree_info = await self._worktree_mgr.create(build.id)
        self._queue.update_status(
            build.id, "building",
            worktree_path=worktree_info.path,
        )

        # 2. Read source files from worktree
        file_contents = self._read_source_files(build.spec, worktree_info.path)

        # 3. Generate code via CopilotBuilderAdapter
        adapter = CopilotBuilderAdapter(
            model=self._builder_model,
            cwd=worktree_info.path,
        )
        if not CopilotBuilderAdapter.is_available():
            raise RuntimeError("Copilot SDK not available")

        await adapter.start()
        try:
            copilot_result = await adapter.execute(
                build.spec, file_contents, timeout=self._builder_timeout,
            )
        finally:
            await adapter.stop()

        if not copilot_result.success or not copilot_result.file_blocks:
            raise RuntimeError(
                copilot_result.error or "Adapter returned no file changes"
            )

        # 4. Apply changes via execute_approved_build (all guardrails)
        build_result = await execute_approved_build(
            file_changes=copilot_result.file_blocks,
            spec=build.spec,
            work_dir=worktree_info.path,
            run_tests=self._run_tests,
            builder_source="visiting",
        )

        # 5. Update queue with result
        if build_result.success:
            self._queue.update_status(
                build.id, "reviewing",
                result=build_result,
            )
        else:
            self._queue.update_status(
                build.id, "failed",
                result=build_result,
                error=build_result.error or "Build failed",
                completed_at=time.monotonic(),
            )

    except Exception as exc:
        logger.error("build-dispatcher build failed id=%s: %s", build.id, exc)
        self._queue.update_status(
            build.id, "failed",
            error=str(exc),
            completed_at=time.monotonic(),
        )
    finally:
        # Fire callback if provided
        updated_build = self._queue.get(build.id)
        if updated_build and self._on_build_complete:
            try:
                await self._on_build_complete(updated_build)
            except Exception as cb_exc:
                logger.warning("on_build_complete callback failed: %s", cb_exc)
```

**Read source files helper:**

```python
def _read_source_files(
    self, spec: BuildSpec, work_dir: str,
) -> dict[str, str]:
    """Read target + reference files from the worktree."""
    contents: dict[str, str] = {}
    root = Path(work_dir)
    for path in spec.target_files + spec.reference_files:
        full = root / path
        if full.exists() and full.is_file():
            try:
                contents[path] = full.read_text(encoding="utf-8")
            except Exception:
                pass
    return contents
```

**Merge helper (called by Captain after review):**

```python
async def approve_and_merge(self, build_id: str) -> tuple[bool, str]:
    """Captain approves a build — merge to main and clean up.

    Returns (success, commit_hash_or_error).
    """
    build = self._queue.get(build_id)
    if build is None or build.status != "reviewing":
        return False, f"Build {build_id} not in reviewing status"

    ok, result = await self._worktree_mgr.merge_to_main(build_id)
    if ok:
        await self._worktree_mgr.remove(build_id)
        self._queue.update_status(
            build_id, "merged",
            completed_at=time.monotonic(),
        )
        logger.info("build-dispatcher merged id=%s commit=%s", build_id, result)
    else:
        self._queue.update_status(
            build_id, "failed",
            error=f"Merge failed: {result}",
            completed_at=time.monotonic(),
        )
        logger.error("build-dispatcher merge failed id=%s: %s", build_id, result)

    return ok, result

async def reject_build(self, build_id: str) -> bool:
    """Captain rejects a build — clean up worktree."""
    build = self._queue.get(build_id)
    if build is None or build.status != "reviewing":
        return False
    await self._worktree_mgr.remove(build_id)
    self._queue.update_status(
        build_id, "failed",
        error="rejected by Captain",
        completed_at=time.monotonic(),
    )
    logger.info("build-dispatcher rejected id=%s", build_id)
    return True
```

**Properties:**

```python
@property
def is_running(self) -> bool:
    return self._running

@property
def active_builds(self) -> list[str]:
    """Build IDs currently being executed."""
    return list(self._active_tasks.keys())
```

**Import notes:** Import at the top:
```python
from probos.build_queue import BuildQueue, QueuedBuild
from probos.worktree_manager import WorktreeManager
from probos.cognitive.builder import BuildSpec, BuildResult, execute_approved_build
```

For CopilotBuilderAdapter, use conditional import:
```python
try:
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
```

In `_execute_build`, check `_SDK_AVAILABLE` instead of `CopilotBuilderAdapter.is_available()` when SDK is not importable.

---

### File: `tests/test_build_dispatcher.py` (NEW)

All tests use mocked dependencies (no real SDK, no real git repos).

**Required tests:**

```python
class TestBuildDispatcher:

    def test_find_dispatchable_returns_highest_priority(self):
        """Highest priority non-conflicting build is selected."""
        # Enqueue two specs with different priorities
        # _find_dispatchable returns the higher priority one

    def test_find_dispatchable_skips_conflicts(self):
        """Builds with footprint conflicts are skipped."""
        # Enqueue build A (dispatched, touches a.py)
        # Enqueue build B (queued, touches a.py) — conflicts
        # Enqueue build C (queued, touches b.py) — no conflict
        # _find_dispatchable returns C

    def test_find_dispatchable_empty_queue(self):
        """Returns None when no builds are dispatchable."""

    @pytest.mark.asyncio
    async def test_execute_build_success(self):
        """Successful build transitions to reviewing status."""
        # Mock WorktreeManager.create, CopilotBuilderAdapter, execute_approved_build
        # Verify status transitions: dispatched → building → reviewing

    @pytest.mark.asyncio
    async def test_execute_build_adapter_failure(self):
        """Adapter failure transitions to failed status."""
        # Mock adapter to return success=False
        # Verify status → failed with error message

    @pytest.mark.asyncio
    async def test_execute_build_worktree_failure(self):
        """Worktree creation failure transitions to failed status."""
        # Mock WorktreeManager.create to raise RuntimeError
        # Verify status → failed

    @pytest.mark.asyncio
    async def test_approve_and_merge(self):
        """approve_and_merge merges, removes worktree, sets status to merged."""
        # Set up a build in "reviewing" status
        # Mock WorktreeManager.merge_to_main to return (True, "abc123")
        # Verify status → merged

    @pytest.mark.asyncio
    async def test_reject_build(self):
        """reject_build removes worktree and sets status to failed."""

    @pytest.mark.asyncio
    async def test_on_build_complete_callback(self):
        """on_build_complete callback fires after build finishes."""
        # Provide a mock callback, run a build, verify it was called

    @pytest.mark.asyncio
    async def test_try_dispatch_respects_max_concurrent(self):
        """Does not dispatch when at max capacity."""
        # Fill active_tasks to max_concurrent
        # Verify _try_dispatch does nothing

    def test_read_source_files(self, tmp_path):
        """Reads existing target + reference files from worktree."""
        # Create files in tmp_path
        # Verify _read_source_files returns their contents
```

**Test patterns:**
- Use `unittest.mock.AsyncMock` for async methods
- Mock `CopilotBuilderAdapter` and `execute_approved_build` via `unittest.mock.patch`
- Create real `BuildQueue` instances (lightweight, no I/O)
- Mock `WorktreeManager` methods (don't need real git repos)
- Use `tmp_path` fixture for `_read_source_files` test

---

## Constraints

- Do NOT modify any existing source files
- Do NOT wire into `runtime.py` (future AD)
- CopilotBuilderAdapter import must be conditional (`try/except ImportError`)
- All async methods must handle exceptions gracefully
- The dispatch loop must survive individual build failures without stopping
- `_find_dispatchable` absorbs AD-374 (footprint conflict detection) —
  this is just a call to `queue.has_footprint_conflict()` which already exists
- Use `logger` for all operations (module-level `logging.getLogger(__name__)`)
- No direct disk I/O except in `_read_source_files` (which reads from the worktree)
