# Build Prompt: BuildQueue + WorktreeManager (AD-371)

## File Footprint
- `src/probos/build_queue.py` (NEW)
- `src/probos/worktree_manager.py` (NEW)
- `tests/test_build_queue.py` (NEW)
- `tests/test_worktree_manager.py` (NEW)
- **No existing files modified** — these are standalone utilities

## Context

AD-371 is the foundation for the Automated Builder Dispatch system (AD-371–374).
The goal: approved BuildSpecs go into a queue, builders automatically pick them
up, execute in isolated git worktrees, and submit results for review. No
copy-paste, no manual dispatch.

This AD creates two standalone utilities:
1. **BuildQueue** — a persistent queue of build specs with status tracking
2. **WorktreeManager** — git worktree lifecycle management

These are pure utilities with no runtime wiring yet (AD-372 does the wiring).

### Existing types to know about (DO NOT modify these):

```python
# In src/probos/cognitive/builder.py — import from there

@dataclass
class BuildSpec:
    title: str
    description: str
    target_files: list[str] = field(default_factory=list)
    reference_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    ad_number: int = 0
    branch_name: str = ""
    constraints: list[str] = field(default_factory=list)

@dataclass
class BuildResult:
    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""
    fix_attempts: int = 0
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    builder_source: str = "native"
```

---

## Changes

### File: `src/probos/build_queue.py` (NEW)

Create a `BuildQueue` class that tracks build specs through their lifecycle.

```python
"""Build Queue — persistent queue for automated builder dispatch (AD-371)."""
```

**QueuedBuild dataclass:**

```python
@dataclass
class QueuedBuild:
    """A build spec tracked through the dispatch lifecycle."""

    id: str                          # UUID, auto-generated
    spec: BuildSpec                  # The build specification
    status: str = "queued"           # queued → dispatched → building → reviewing → merged → failed
    priority: int = 5               # 1 (highest) to 10 (lowest), default 5
    created_at: float = 0.0         # time.monotonic()
    dispatched_at: float | None = None
    completed_at: float | None = None
    worktree_path: str = ""         # Set by dispatcher when worktree is allocated
    builder_id: str = ""            # Which builder is handling this
    result: BuildResult | None = None  # Set when build completes
    error: str = ""                 # Error message if failed
    file_footprint: list[str] = field(default_factory=list)  # Files this build will touch
```

**Valid status transitions:**

```
queued → dispatched → building → reviewing → merged
                                           → failed
         dispatched → failed (if worktree setup fails)
queued → failed (if cancelled)
```

**BuildQueue class:**

```python
class BuildQueue:
    """Persistent queue of builds awaiting execution."""
```

**Constructor:** No parameters. Queue is in-memory (list of QueuedBuild).
SQLite persistence is a future enhancement.

**Methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `enqueue` | `(spec: BuildSpec, priority: int = 5, file_footprint: list[str] | None = None) -> QueuedBuild` | Add a spec to the queue. Auto-generates UUID. Sets `created_at`. If `file_footprint` is None, uses `spec.target_files`. Returns the QueuedBuild. |
| `dequeue` | `() -> QueuedBuild | None` | Get the highest-priority queued item (lowest priority number, FIFO within same priority). Returns None if queue is empty. Does NOT change status — caller must call `update_status`. |
| `peek` | `() -> QueuedBuild | None` | Like dequeue but doesn't affect ordering. |
| `update_status` | `(build_id: str, status: str, **kwargs) -> bool` | Update status and any additional fields (worktree_path, builder_id, result, error, dispatched_at, completed_at). Validates status transitions. Returns False if invalid transition. |
| `get` | `(build_id: str) -> QueuedBuild | None` | Get a queued build by ID. |
| `get_by_status` | `(status: str) -> list[QueuedBuild]` | Get all builds with a given status. |
| `get_all` | `() -> list[QueuedBuild]` | Get all builds regardless of status. |
| `cancel` | `(build_id: str) -> bool` | Cancel a queued build (sets status to failed, error to "cancelled"). Returns False if not in queued status. |
| `has_footprint_conflict` | `(footprint: list[str]) -> bool` | Check if any active build (dispatched/building) has overlapping file footprint. Used by AD-374 for conflict detection. |
| `active_count` | `() -> int` | Property. Number of builds in dispatched/building status. |

**Status validation rules:**
- Only allow valid transitions per the diagram above
- `update_status` with invalid transition returns `False` and does not change state

---

### File: `src/probos/worktree_manager.py` (NEW)

Create a `WorktreeManager` class that manages git worktree lifecycle.

```python
"""Worktree Manager — git worktree lifecycle for parallel builds (AD-371)."""
```

**WorktreeInfo dataclass:**

```python
@dataclass
class WorktreeInfo:
    """Tracks an active git worktree."""

    path: str           # Absolute path to the worktree directory
    branch: str         # Branch name used in the worktree
    build_id: str = ""  # The QueuedBuild.id using this worktree
    created_at: float = 0.0
```

**WorktreeManager class:**

```python
class WorktreeManager:
    """Manages git worktree lifecycle for parallel builder execution."""
```

**Constructor:**

```python
def __init__(self, repo_root: str, worktree_base: str = "") -> None:
    """
    Args:
        repo_root: Path to the main git repository.
        worktree_base: Parent directory for worktrees.
                       Defaults to {repo_root}/../ProbOS-builders/
    """
```

**Methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `create` | `async (build_id: str) -> WorktreeInfo` | Create a new worktree. Branch name: `builder-{build_id[:8]}`. Path: `{worktree_base}/builder-{build_id[:8]}`. Runs `git worktree add`. Returns WorktreeInfo. Raises on failure. |
| `remove` | `async (build_id: str) -> bool` | Remove worktree and delete branch. Runs `git worktree remove --force` then `git branch -D`. Returns True on success. |
| `get` | `(build_id: str) -> WorktreeInfo | None` | Get worktree info by build ID. |
| `get_all` | `() -> list[WorktreeInfo]` | List all active worktrees. |
| `collect_diff` | `async (build_id: str) -> str` | Run `git diff main...{branch}` and return the diff output. |
| `merge_to_main` | `async (build_id: str) -> tuple[bool, str]` | Merge the worktree's branch into main. Returns (success, commit_hash_or_error). Runs: `git checkout main && git merge {branch} --no-edit`. |
| `cleanup_all` | `async () -> int` | Remove all managed worktrees. Returns count removed. For shutdown/reset. |

**Implementation notes:**
- All git commands use `asyncio.create_subprocess_exec` (not `subprocess.run`)
- Capture stdout and stderr for error reporting
- `create` should ensure the worktree_base directory exists (create if not)
- Track active worktrees in a dict: `{build_id: WorktreeInfo}`
- `merge_to_main` must be called from the main repo, not from the worktree
- Use `logger` for all operations

---

### File: `tests/test_build_queue.py` (NEW)

**Required tests:**

```python
class TestBuildQueue:
    def test_enqueue_assigns_id(self):
        """Enqueue returns a QueuedBuild with a UUID and correct status."""

    def test_dequeue_priority_order(self):
        """Higher priority (lower number) items dequeue first."""

    def test_dequeue_fifo_same_priority(self):
        """Same priority items dequeue in FIFO order."""

    def test_dequeue_empty_returns_none(self):
        """Empty queue returns None."""

    def test_update_status_valid_transition(self):
        """queued → dispatched is valid."""

    def test_update_status_invalid_transition(self):
        """queued → merged is invalid, returns False."""

    def test_update_status_sets_kwargs(self):
        """update_status(..., worktree_path='/tmp/wt') sets the field."""

    def test_cancel_queued_build(self):
        """Cancel sets status to failed with 'cancelled' error."""

    def test_cancel_non_queued_returns_false(self):
        """Cannot cancel a build that's already dispatched."""

    def test_has_footprint_conflict_overlap(self):
        """Detects overlapping file footprint with active builds."""

    def test_has_footprint_conflict_no_overlap(self):
        """No conflict when files don't overlap."""

    def test_get_by_status(self):
        """Returns only builds matching the requested status."""

    def test_active_count(self):
        """active_count reflects dispatched + building builds."""

    def test_file_footprint_defaults_to_target_files(self):
        """If file_footprint not provided, uses spec.target_files."""
```

---

### File: `tests/test_worktree_manager.py` (NEW)

**Required tests** (these use real git repos in tmp_path):

```python
class TestWorktreeManager:
    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a minimal git repo for testing."""
        # git init, configure user, make initial commit
        repo = tmp_path / "repo"
        repo.mkdir()
        # subprocess.run git commands to init, config, commit --allow-empty
        return str(repo)

    @pytest.mark.asyncio
    async def test_create_worktree(self, git_repo):
        """Create creates a worktree directory and branch."""

    @pytest.mark.asyncio
    async def test_remove_worktree(self, git_repo):
        """Remove deletes worktree directory and branch."""

    @pytest.mark.asyncio
    async def test_get_worktree(self, git_repo):
        """Get returns WorktreeInfo for known build_id."""

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, git_repo):
        """Get returns None for unknown build_id."""

    @pytest.mark.asyncio
    async def test_collect_diff(self, git_repo):
        """collect_diff returns diff output for worktree changes."""
        # Create worktree, write a file in it, commit, then collect_diff

    @pytest.mark.asyncio
    async def test_cleanup_all(self, git_repo):
        """cleanup_all removes all worktrees."""
```

**Test implementation notes:**
- Use `subprocess.run` (sync) in the fixture to set up git repos
- Use `asyncio.create_subprocess_exec` in the WorktreeManager itself
- Each test gets a fresh tmp_path git repo
- Write real files and make real git commits to test diff collection
- Skip `merge_to_main` test (requires more complex fixture with main branch
  state management — will be tested in AD-372 integration tests)

---

## Constraints

- Do NOT modify any existing source files
- Do NOT wire these into `runtime.py` (that's AD-372)
- Do NOT import from these new modules in any existing code
- These are standalone utilities — they must work independently
- Use `uuid.uuid4().hex[:12]` for build IDs (short, unique enough)
- Use `asyncio.create_subprocess_exec` for all git commands (not `subprocess.run`)
- All async methods should handle subprocess errors gracefully (return False or raise with clear message)
- No LLM calls, no SDK dependency — pure Python + git
