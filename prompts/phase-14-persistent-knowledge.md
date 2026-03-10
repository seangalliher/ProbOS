# Phase 14: Persistent Knowledge Store — The System Remembers

**Goal:** ProbOS survives restarts. Episodic memory, designed agent code, skills, workflow cache entries, trust snapshots, QA reports, and Hebbian routing weights are persisted to a Git-backed knowledge repository. Every meaningful state change is committed as a versioned artifact with rollback capability. The system boots warm — restoring its learned behaviors, trust judgments, and designed agents from the last session — rather than cold-starting every time.

This addresses the most impactful infrastructure gap in ProbOS: everything the system learns, designs, and remembers currently lives in a temp-dir SQLite database that is destroyed on process exit. A system that designs its own agents but cannot remember them across restarts has a fundamental limitation.

---

## Context

Right now:
1. `EpisodicMemory` uses aiosqlite in a temp directory (`tempfile.mkdtemp()`). Every episode, recall pattern, and QA record vanishes when the process exits.
2. `TrustNetwork` uses aiosqlite in a temp directory. Hard-earned trust scores (including dreaming consolidation results and QA-derived adjustments) are lost on restart.
3. `HebbianRouter` uses aiosqlite in a temp directory. Learned routing preferences from real-world usage are lost.
4. Designed agents exist only in memory — `SelfModificationPipeline._designed_agents` and the runtime's `_designed_pools`. The generated source code, the `DesignedAgentRecord`, and the registered agent class all disappear.
5. Skills added to `SkillBasedAgent` are in-memory only — the compiled handler, source code, and `Skill` object are gone on restart.
6. `WorkflowCache` is purely in-memory with no persistence.
7. QA reports (`runtime._qa_reports`) are in-memory only.

The system cold-starts every time: 25 generic agents, uniform trust priors, no routing preferences, no episodic history, no designed agents. It must re-learn everything.

---

## Design Principles

1. **Git as the storage backend.** Knowledge is stored as JSON files in a local Git repository. Git provides versioning, rollback (`git revert`), audit trail (`git log`), diff, and blame for free. No database server required. The knowledge repo is a standard Git repo that can be inspected with normal Git tools.

2. **Human-readable artifacts.** Every persisted artifact is a JSON or Python file that a developer can read, edit, or delete with standard tools. No binary blobs or proprietary formats.

3. **Auto-commit on meaningful changes.** The knowledge store commits automatically when significant state changes occur: new episode stored, agent designed, trust consolidated after dreaming, skill added. Not on every micro-change — batched where sensible.

4. **Warm boot.** On startup, `ProbOSRuntime` loads the knowledge store and restores: all designed agents (re-registered and pooled), all skills (re-attached to SkillBasedAgent), trust scores, Hebbian weights, workflow cache entries, and recent episodes. The system resumes from where it left off.

5. **Backward compatible cold boot.** If no knowledge repo exists (first run, or `--fresh` flag), the system cold-starts exactly as it does today. The knowledge store is created on first meaningful write.

6. **Non-blocking persistence.** Writes to the knowledge store happen asynchronously. A slow disk or large commit never blocks user requests. Git operations run in a thread executor.

7. **Fully test-covered.** Every deliverable has corresponding automated tests. All tests run in `uv run pytest tests/ -v`. The phase is not complete until every new code path has at least one test.

---

## AD Numbering: Start at AD-159

AD-153 through AD-158 exist from Phase 13. All architectural decisions in this phase start at **AD-159**. Pre-assigned numbers:

| AD | Decision |
|----|----------|
| AD-159 | Knowledge repo location: `~/.probos/knowledge/` by default, configurable via `knowledge.repo_path` in config. Git init on first write, not on boot |
| AD-160 | Artifact layout: `episodes/`, `agents/`, `skills/`, `trust/`, `routing/`, `workflows/`, `qa/` subdirectories. One JSON file per artifact, keyed by ID or agent_type |
| AD-161 | Auto-commit strategy: batch commits via debounce timer (default 5s). Multiple writes within the debounce window are committed together. Immediate commit on shutdown |
| AD-162 | Warm boot order: trust → routing → agents → skills → episodes → workflows → QA. Trust and routing must load before agents so probationary scores are restored correctly |
| AD-163 | Designed agent restoration: source code stored as `.py` file, metadata as `.json` sidecar. On warm boot, `importlib` dynamic loading + class registration + pool creation, identical to the self-mod pipeline's registration flow |
| AD-164 | Rollback via `/rollback <artifact-type> <identifier>`: reverts the last commit affecting that artifact. Uses `git log --follow` + `git show` to retrieve the previous version, then overwrites and re-commits. Does NOT use `git revert` (too coarse for per-artifact rollback) |
| AD-165 | `--fresh` CLI flag: ignores existing knowledge repo, cold-starts, does NOT delete the repo (user may want to inspect it) |
| AD-166 | Thread executor for Git operations: all `git add/commit/log/show` calls run via `asyncio.loop.run_in_executor()` to avoid blocking the event loop |
| AD-167 | Knowledge store is optional infrastructure: if `knowledge.enabled = False` or Git is not available, the system falls back to current behavior (temp SQLite, in-memory state). No feature depends exclusively on persistence |

---

## Pre-Build Audit: Examine These Files First

Before writing any code, read the following to understand the interfaces you'll integrate with:

1. `src/probos/cognitive/episodic.py` — `EpisodicMemory` class, `store()`, `recall()`, `recent()`, `get_stats()`, SQLite schema
2. `src/probos/cognitive/episodic_mock.py` — `MockEpisodicMemory` interface (same methods, in-memory)
3. `src/probos/types.py` — `Episode` dataclass fields, `Skill` dataclass fields, `WorkflowCacheEntry`
4. `src/probos/consensus/trust.py` — `TrustNetwork`, `_records` dict, `all_scores()`, `summary()`, `_save_to_db()`, `_load_from_db()`
5. `src/probos/mesh/routing.py` — `HebbianRouter`, `_weights` dict, SQLite persistence methods
6. `src/probos/cognitive/self_mod.py` — `SelfModificationPipeline`, `DesignedAgentRecord`, `_designed_agents` list
7. `src/probos/cognitive/workflow_cache.py` — `WorkflowCache`, `_cache` dict, `store()`, `lookup()`
8. `src/probos/substrate/skill_agent.py` — `SkillBasedAgent`, `add_skill()`, `_skills` dict
9. `src/probos/agents/system_qa.py` — `QAReport` dataclass
10. `src/probos/runtime.py` — `start()`, `stop()`, pool creation, `_register_designed_agent()`, `_create_designed_pool()`, `_set_probationary_trust()`, `_qa_reports`
11. `src/probos/config.py` — `SystemConfig`, `load_config()`
12. `src/probos/__main__.py` — CLI argument parsing, boot sequence
13. `src/probos/experience/shell.py` — slash command registration pattern

---

## Deliverables

### 1. Add `KnowledgeConfig` to `src/probos/config.py`

```python
class KnowledgeConfig(BaseModel):
    """Persistent knowledge store configuration."""

    enabled: bool = True
    repo_path: str = ""             # Empty = ~/.probos/knowledge/
    auto_commit: bool = True        # Auto-commit on writes
    commit_debounce_seconds: float = 5.0  # Batch writes within this window
    max_episodes: int = 1000        # Max episodes to persist (oldest evicted)
    max_workflows: int = 200        # Max workflow cache entries to persist
    restore_on_boot: bool = True    # Warm boot from existing repo
```

Add `knowledge: KnowledgeConfig = KnowledgeConfig()` to `SystemConfig`.

Add `knowledge:` section to `config/system.yaml` with defaults commented out (same pattern as `scaling:` and `federation:` sections).

---

### 2. Create `src/probos/knowledge/__init__.py` and `src/probos/knowledge/store.py` — KnowledgeStore

The `KnowledgeStore` is the central persistence manager. It owns the Git repo and provides typed read/write methods for each artifact category.

```python
class KnowledgeStore:
    """Git-backed persistent knowledge repository."""

    def __init__(self, config: KnowledgeConfig):
        ...

    async def initialize(self) -> None:
        """Ensure repo directory exists. Git init on first write, not here (AD-159)."""
        ...

    # --- Episode persistence ---
    async def store_episode(self, episode: Episode) -> None:
        """Write episode to episodes/{id}.json, schedule commit."""
        ...

    async def load_episodes(self, limit: int = 100) -> list[Episode]:
        """Load recent episodes from disk, sorted by timestamp desc."""
        ...

    # --- Designed agent persistence ---
    async def store_agent(self, record: DesignedAgentRecord, source_code: str) -> None:
        """Write agent source to agents/{agent_type}.py and metadata to agents/{agent_type}.json."""
        ...

    async def load_agents(self) -> list[tuple[DesignedAgentRecord, str]]:
        """Load all designed agent records + source code."""
        ...

    async def remove_agent(self, agent_type: str) -> None:
        """Delete agent files and commit removal."""
        ...

    # --- Skill persistence ---
    async def store_skill(self, intent_name: str, source_code: str, descriptor: dict) -> None:
        """Write skill source to skills/{intent_name}.py and descriptor to skills/{intent_name}.json."""
        ...

    async def load_skills(self) -> list[tuple[str, str, dict]]:
        """Load all skills: (intent_name, source_code, descriptor_dict)."""
        ...

    # --- Trust persistence ---
    async def store_trust_snapshot(self, scores: dict[str, dict]) -> None:
        """Write trust records to trust/snapshot.json. Called after dreaming consolidation and on shutdown."""
        ...

    async def load_trust_snapshot(self) -> dict[str, dict] | None:
        """Load trust snapshot. Returns {agent_id: {alpha, beta, observations}} or None."""
        ...

    # --- Hebbian routing persistence ---
    async def store_routing_weights(self, weights: list[dict]) -> None:
        """Write routing weights to routing/weights.json. Called after dreaming and on shutdown."""
        ...

    async def load_routing_weights(self) -> list[dict] | None:
        """Load routing weights. Returns list of {source, target, rel_type, weight} or None."""
        ...

    # --- Workflow cache persistence ---
    async def store_workflows(self, entries: list[dict]) -> None:
        """Write workflow cache entries to workflows/cache.json."""
        ...

    async def load_workflows(self) -> list[dict] | None:
        """Load workflow cache entries."""
        ...

    # --- QA report persistence ---
    async def store_qa_report(self, agent_type: str, report_dict: dict) -> None:
        """Write QA report to qa/{agent_type}.json."""
        ...

    async def load_qa_reports(self) -> dict[str, dict]:
        """Load all QA reports."""
        ...

    # --- Git operations ---
    async def _ensure_repo(self) -> None:
        """Git init if not already a repo (AD-159). Creates directories (AD-160)."""
        ...

    async def _schedule_commit(self, message: str) -> None:
        """Debounced commit (AD-161). Batches writes within the debounce window."""
        ...

    async def _git_commit(self, message: str) -> None:
        """Run git add + commit in thread executor (AD-166)."""
        ...

    async def flush(self) -> None:
        """Force commit any pending changes. Called on shutdown."""
        ...

    # --- Rollback ---
    async def rollback_artifact(self, artifact_type: str, identifier: str) -> bool:
        """Revert a specific artifact to its previous version (AD-164).
        Returns True if rollback succeeded, False if no history found."""
        ...

    async def artifact_history(self, artifact_type: str, identifier: str, limit: int = 10) -> list[dict]:
        """Get commit history for a specific artifact.
        Returns [{commit_hash, timestamp, message}, ...]."""
        ...

    @property
    def repo_exists(self) -> bool:
        """Whether the knowledge repo has been initialized."""
        ...
```

#### Artifact Directory Layout (AD-160)

```
~/.probos/knowledge/
├── .git/
├── episodes/
│   ├── a1b2c3d4.json          # Episode ID as filename
│   └── e5f6g7h8.json
├── agents/
│   ├── weather_agent.py       # Generated source code
│   ├── weather_agent.json     # DesignedAgentRecord metadata
│   ├── text_summarizer.py
│   └── text_summarizer.json
├── skills/
│   ├── translate_text.py      # Skill handler source
│   └── translate_text.json    # Skill descriptor metadata
├── trust/
│   └── snapshot.json           # {agent_id: {alpha, beta, observations}}
├── routing/
│   └── weights.json            # [{source, target, rel_type, weight}, ...]
├── workflows/
│   └── cache.json              # [{normalized_input, dag_json, hit_count}, ...]
└── qa/
    ├── weather_agent.json      # QAReport for designed agent
    └── text_summarizer.json
```

#### Debounced Commit Strategy (AD-161)

The `_schedule_commit()` method uses an `asyncio.TimerHandle` pattern:

```python
async def _schedule_commit(self, message: str) -> None:
    """Accumulate commit message, reset debounce timer."""
    self._pending_messages.append(message)
    if self._commit_timer is not None:
        self._commit_timer.cancel()

    loop = asyncio.get_event_loop()
    self._commit_timer = loop.call_later(
        self._config.commit_debounce_seconds,
        lambda: asyncio.ensure_future(self._flush_pending())
    )
```

On shutdown (`flush()`), the timer is cancelled and any pending changes are committed immediately with all accumulated messages joined.

#### Git Operations in Thread Executor (AD-166)

All `git` subprocess calls go through `asyncio.loop.run_in_executor()`:

```python
async def _git_run(self, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["git", "-C", str(self._repo_path), *args],
            capture_output=True, text=True, timeout=30
        )
    )
```

---

### 3. Wire into `src/probos/runtime.py`

#### 3a. Create KnowledgeStore at init and initialize at start

```python
# In __init__:
self._knowledge_store: KnowledgeStore | None = None

# In start(), after pool creation:
if self.config.knowledge.enabled:
    self._knowledge_store = KnowledgeStore(self.config.knowledge)
    await self._knowledge_store.initialize()

    if self.config.knowledge.restore_on_boot:
        await self._restore_from_knowledge()
```

#### 3b. Add `_restore_from_knowledge()` — Warm Boot (AD-162)

Load order matters:

1. **Trust snapshot** → Restore `TrustNetwork` records so that agents get their earned trust back, not uniform priors.
2. **Routing weights** → Restore `HebbianRouter` weights so the mesh routes based on learned patterns.
3. **Designed agents** → For each stored agent: `importlib` dynamic load → class registration → pool creation → trust restoration (must happen after trust snapshot is loaded). Follow the same flow as `_register_designed_agent()` and `_create_designed_pool()` in the existing self-mod code.
4. **Skills** → For each stored skill: compile handler → create `Skill` object → `add_skill()` to `SkillBasedAgent` instances. Follow the same flow as `handle_add_skill()` in `SelfModificationPipeline`.
5. **Episodes** → Seed `EpisodicMemory` with stored episodes. The decomposer will have historical context immediately.
6. **Workflow cache** → Populate `WorkflowCache` with stored entries. Repeated requests hit the cache on first try.
7. **QA reports** → Restore `_qa_reports` dict for `/qa` command.

If any individual restoration step fails (corrupted file, missing dependency in designed agent code), log a warning and continue. Partial restoration is better than no restoration. Never let a corrupt artifact block startup.

#### 3c. Hook persistence into existing write paths

Add `KnowledgeStore` calls at the points where state changes already occur:

| Existing code path | Persistence call |
|---|---|
| `EpisodicMemory.store()` (called in `process_natural_language()` after DAG execution) | `knowledge_store.store_episode(episode)` |
| `_register_designed_agent()` / `_create_designed_pool()` | `knowledge_store.store_agent(record, source_code)` |
| `_add_skill_to_agents()` | `knowledge_store.store_skill(intent_name, source_code, descriptor)` |
| `DreamingEngine.dream_cycle()` completes (trust consolidation) | `knowledge_store.store_trust_snapshot(trust_network.summary())` |
| `DreamingEngine.dream_cycle()` completes (Hebbian updates) | `knowledge_store.store_routing_weights(...)` |
| `WorkflowCache.store()` | `knowledge_store.store_workflows(...)` |
| `_run_qa_for_designed_agent()` completes | `knowledge_store.store_qa_report(agent_type, report)` |
| `stop()` (shutdown) | `knowledge_store.store_trust_snapshot(...)` + `knowledge_store.store_routing_weights(...)` + `knowledge_store.flush()` |

**Important:** These calls should be additive — wrapped in try/except so a persistence failure never blocks the primary operation. The system must continue working even if the knowledge store is unavailable.

#### 3d. Add `--fresh` CLI flag (AD-165)

In `__main__.py`, add `--fresh` argument:

```python
parser.add_argument("--fresh", action="store_true",
                    help="Cold start: ignore existing knowledge repo")
```

When `--fresh` is set, override `config.knowledge.restore_on_boot = False`. The repo is NOT deleted — only ignored for this session. New writes still go to the repo.

---

### 4. Add shell commands

#### `/knowledge` — Knowledge store status

```
/knowledge          — Show knowledge store overview (repo path, artifact counts, last commit)
/knowledge history  — Show recent commit history (last 20 commits)
```

Display as a Rich panel:

```
╭─── Knowledge Store ─────────────────────────────────────╮
│ Repository: ~/.probos/knowledge/                        │
│ Status:     active (42 commits)                         │
│                                                         │
│ Artifact Type  │ Count │ Last Modified                   │
│────────────────│───────│─────────────────────────────────│
│ Episodes       │   156 │ 2026-03-08 14:32:01             │
│ Agents         │     3 │ 2026-03-07 09:15:44             │
│ Skills         │     1 │ 2026-03-06 17:22:30             │
│ Trust          │     1 │ 2026-03-08 14:30:00 (snapshot)  │
│ Routing        │     1 │ 2026-03-08 14:30:00 (snapshot)  │
│ Workflows      │    28 │ 2026-03-08 14:25:12             │
│ QA Reports     │     3 │ 2026-03-07 09:18:01             │
╰─────────────────────────────────────────────────────────╯
```

#### `/rollback <artifact-type> <identifier>` — Artifact rollback (AD-164)

```
/rollback agent weather_agent     — Revert weather_agent to previous version
/rollback episode a1b2c3d4        — Revert episode to previous version
/rollback trust snapshot          — Revert trust scores to previous snapshot
```

Confirm before executing. Show a diff-like summary of what will change.

---

### 5. Create `src/probos/experience/knowledge_panel.py` — Knowledge rendering

```python
def render_knowledge_panel(store: KnowledgeStore) -> Panel:
    """Render knowledge store overview panel."""
    ...

def render_knowledge_history(commits: list[dict]) -> Panel:
    """Render recent commit history."""
    ...

def render_rollback_confirmation(artifact_type: str, identifier: str, diff_summary: str) -> Panel:
    """Render rollback confirmation prompt."""
    ...
```

Follow the same pattern as `qa_panel.py`: empty-state guard, Rich Table, Rich Panel with border styling.

---

### 6. Tests: `tests/test_knowledge_store.py`

**Regression mandate:** Every new code path MUST have automated test coverage. `uv run pytest tests/ -v` must show 950+ tests passing (892 existing + 60+ new) with 0 failures.

#### 6a. KnowledgeStore unit tests

| Test | What it validates |
|------|-------------------|
| `test_initialize_creates_directory` | `initialize()` creates the repo directory if it doesn't exist |
| `test_initialize_idempotent` | Calling `initialize()` twice doesn't error |
| `test_git_init_on_first_write` | Git repo is initialized on first `store_*` call, not on `initialize()` (AD-159) |
| `test_repo_exists_false_before_write` | `repo_exists` returns False before any write |
| `test_repo_exists_true_after_write` | `repo_exists` returns True after first write |
| `test_store_episode_creates_file` | `store_episode()` creates `episodes/{id}.json` with correct content |
| `test_store_episode_valid_json` | Stored episode file is valid JSON matching Episode fields |
| `test_load_episodes_returns_stored` | `load_episodes()` returns episodes previously stored |
| `test_load_episodes_sorted_by_timestamp` | Episodes are returned newest-first |
| `test_load_episodes_limit` | `load_episodes(limit=5)` returns at most 5 episodes |
| `test_load_episodes_empty_dir` | `load_episodes()` returns empty list when no episodes exist |
| `test_store_agent_creates_py_and_json` | `store_agent()` creates both `.py` and `.json` files |
| `test_store_agent_source_matches` | The `.py` file content matches the provided source code |
| `test_store_agent_metadata_matches` | The `.json` file contains correct `DesignedAgentRecord` fields |
| `test_load_agents_returns_stored` | `load_agents()` returns previously stored agent records + source |
| `test_load_agents_empty` | `load_agents()` returns empty list when no agents exist |
| `test_remove_agent_deletes_files` | `remove_agent()` deletes both `.py` and `.json` files |
| `test_remove_agent_nonexistent` | `remove_agent()` for missing agent doesn't error |
| `test_store_skill_creates_files` | `store_skill()` creates `.py` and `.json` files in skills/ |
| `test_load_skills_returns_stored` | `load_skills()` returns previously stored skills |
| `test_store_trust_snapshot` | `store_trust_snapshot()` creates `trust/snapshot.json` |
| `test_load_trust_snapshot` | `load_trust_snapshot()` returns previously stored trust data |
| `test_load_trust_snapshot_missing` | Returns None when no snapshot exists |
| `test_store_routing_weights` | `store_routing_weights()` creates `routing/weights.json` |
| `test_load_routing_weights` | `load_routing_weights()` returns previously stored weights |
| `test_store_workflows` | `store_workflows()` creates `workflows/cache.json` |
| `test_load_workflows` | `load_workflows()` returns previously stored entries |
| `test_store_qa_report` | `store_qa_report()` creates `qa/{agent_type}.json` |
| `test_load_qa_reports` | `load_qa_reports()` returns all stored reports |
| `test_max_episodes_eviction` | When `max_episodes` exceeded, oldest episodes are deleted on store |
| `test_max_workflows_eviction` | When `max_workflows` exceeded, lowest hit_count workflows are dropped |

#### 6b. Git integration tests

| Test | What it validates |
|------|-------------------|
| `test_auto_commit_after_debounce` | After storing an artifact and waiting for debounce, a git commit exists |
| `test_debounce_batches_writes` | Multiple writes within debounce window produce a single commit |
| `test_flush_commits_immediately` | `flush()` commits pending changes without waiting for debounce |
| `test_commit_message_includes_artifact_info` | Commit messages describe what was changed |
| `test_artifact_history_returns_commits` | `artifact_history()` returns commit log for a specific file |
| `test_artifact_history_empty` | `artifact_history()` returns empty list for non-existent artifact |
| `test_rollback_restores_previous_version` | `rollback_artifact()` restores the previous version of a file |
| `test_rollback_creates_new_commit` | Rollback creates a new commit (not destructive rewrite) |
| `test_rollback_no_history_returns_false` | `rollback_artifact()` returns False when artifact has no previous version |
| `test_thread_executor_no_event_loop_block` | Git operations don't block the asyncio event loop (AD-166) |
| `test_git_not_available_graceful` | If `git` binary is not found, store falls back to file-only mode (no commits, no rollback) |

#### 6c. Warm boot tests (AD-162)

| Test | What it validates |
|------|-------------------|
| `test_warm_boot_restores_trust` | Trust scores from previous session are restored on boot |
| `test_warm_boot_restores_routing` | Hebbian weights from previous session are restored |
| `test_warm_boot_restores_designed_agents` | Designed agents are re-registered and pooled |
| `test_warm_boot_restores_skills` | Skills are re-attached to SkillBasedAgent instances |
| `test_warm_boot_restores_episodes` | Episodes are seeded into EpisodicMemory |
| `test_warm_boot_restores_workflows` | WorkflowCache is populated with stored entries |
| `test_warm_boot_restores_qa_reports` | QA reports are restored into `_qa_reports` dict |
| `test_warm_boot_order_trust_before_agents` | Trust is restored before agents, so agents get correct trust scores |
| `test_warm_boot_partial_failure` | Corrupted agent file is skipped, other artifacts restore correctly |
| `test_warm_boot_empty_repo` | Empty knowledge repo doesn't error, system cold-starts normally |
| `test_fresh_flag_skips_restore` | `--fresh` flag prevents restoration but allows new writes |
| `test_fresh_flag_preserves_repo` | `--fresh` does NOT delete the existing knowledge repo (AD-165) |

#### 6d. Runtime integration tests

| Test | What it validates |
|------|-------------------|
| `test_episode_persisted_after_nl_processing` | After `process_natural_language()`, the episode is written to knowledge store |
| `test_designed_agent_persisted_after_self_mod` | After self-mod, agent source + metadata written to knowledge store |
| `test_trust_persisted_after_dreaming` | After dream cycle, trust snapshot written to knowledge store |
| `test_routing_persisted_after_dreaming` | After dream cycle, routing weights written to knowledge store |
| `test_qa_report_persisted` | After QA completion, report written to knowledge store |
| `test_persistence_failure_no_crash` | Knowledge store write failure doesn't crash the runtime |
| `test_shutdown_flushes_knowledge` | `stop()` calls `knowledge_store.flush()` for clean shutdown |
| `test_knowledge_disabled_skips_persistence` | When `knowledge.enabled = False`, no persistence calls made |

#### 6e. Config tests

| Test | What it validates |
|------|-------------------|
| `test_knowledge_config_defaults` | Default values match spec |
| `test_knowledge_config_in_system_config` | `SystemConfig` includes `knowledge: KnowledgeConfig` |
| `test_knowledge_config_from_yaml` | Custom values load from YAML |
| `test_knowledge_config_missing_uses_defaults` | Missing `knowledge:` section → defaults applied |

#### 6f. Shell and experience tests

| Test | What it validates |
|------|-------------------|
| `test_knowledge_command_registered` | `/knowledge` appears in shell COMMANDS dict |
| `test_knowledge_command_renders_panel` | `/knowledge` calls `render_knowledge_panel()` |
| `test_knowledge_history_subcommand` | `/knowledge history` shows commit log |
| `test_rollback_command_registered` | `/rollback` appears in shell COMMANDS dict |
| `test_render_knowledge_panel_populated` | Panel renders with correct artifact counts |
| `test_render_knowledge_panel_no_store` | Panel shows "Knowledge store not enabled" when disabled |
| `test_render_knowledge_history` | History panel shows commit entries |

#### 6g. Existing test regression

| Test | What it validates |
|------|-------------------|
| `test_existing_runtime_tests_pass` | All 32 existing runtime integration tests still pass |
| `test_existing_episodic_tests_pass` | All existing episodic memory tests still pass |
| `test_existing_trust_tests_pass` | All existing trust network tests still pass |
| `test_existing_shell_tests_pass` | All existing shell command tests still pass |
| `test_runtime_status_includes_knowledge` | `runtime.status()` includes `knowledge` key with enabled state and artifact counts |

---

## Test Execution Constraints

- **All tests must use `MockLLMClient`.** No `@pytest.mark.live_llm` markers.
- **Use temp directories.** All tests create knowledge repos in `tempfile.mkdtemp()`, never in `~/.probos/`. Clean up in fixtures.
- **Git must be available.** Tests that need git should check with `shutil.which("git")` and skip with `pytest.mark.skipif` if unavailable. Provide a marker `@pytest.mark.requires_git` for these tests.
- **No network, no real filesystem side effects.**
- **Target:** 60+ new tests. Phase complete when `uv run pytest tests/ -v` shows 950+ tests passing (892 existing + 60+ new) with 0 failures.

---

## What This Phase Does NOT Include

- **ChromaDB / vector embeddings.** The episodic memory recall still uses keyword-overlap bag-of-words. Upgrading to semantic similarity via vector embeddings is a separate phase that layers on top of the persistent store.

- **Cross-node knowledge sync.** The knowledge repo is local to each node. Federation-based knowledge sharing (e.g., `git push`/`git pull` between nodes) is a natural follow-up but adds distributed consistency concerns.

- **Knowledge compaction / garbage collection.** Over time, the episodes directory will grow. A future phase could add episode summarization (compress old episodes into summary episodes) or time-based pruning.

- **Schema migration.** The first version of each artifact format is v1. If fields change in future phases, a migration system will be needed. For now, the JSON format is the schema — forward-compatible by ignoring unknown fields, backward-compatible by using defaults for missing fields.

- **Encryption at rest.** Knowledge artifacts are stored as plaintext JSON. If the system handles sensitive data, encryption should be added as a separate concern (GPG-encrypted Git, or OS-level disk encryption).

---

## Build Order

1. `KnowledgeConfig` in `config.py` + config tests (verify defaults, YAML loading)
2. `KnowledgeStore` class skeleton with directory layout + file I/O (no Git yet) + unit tests for store/load of each artifact type
3. Git integration: `_ensure_repo()`, `_git_commit()`, `_schedule_commit()`, `flush()` + git integration tests
4. Rollback: `rollback_artifact()`, `artifact_history()` + rollback tests
5. Runtime wiring: `_restore_from_knowledge()` warm boot, persistence hooks into existing write paths + warm boot tests + runtime integration tests
6. `--fresh` CLI flag + test
7. Experience layer: `knowledge_panel.py`, `/knowledge` and `/rollback` shell commands + shell tests
8. Full regression: `uv run pytest tests/ -v` — all 950+ tests pass

Do NOT proceed to step N+1 until step N's tests pass.

---

## Existing Infrastructure Leveraged

| Component | How KnowledgeStore uses it |
|-----------|--------------------------|
| `EpisodicMemory.store()` | Hook point — after storing in SQLite, also persist to knowledge repo |
| `TrustNetwork.summary()` / `all_scores()` | Extracting trust data for snapshot serialization |
| `HebbianRouter._weights` | Extracting routing weights for persistence |
| `SelfModificationPipeline._designed_agents` | Source of `DesignedAgentRecord` + source code for agent persistence |
| `SkillBasedAgent._skills` | Source of skill data for persistence |
| `WorkflowCache._cache` | Source of workflow entries for persistence |
| `importlib` dynamic loading | Reuses the sandbox/self-mod pattern for designed agent restoration |
| `asyncio.run_in_executor()` | Non-blocking Git subprocess calls |
| `ResourcePool` / `AgentSpawner` | Pool creation for restored designed agents |
| `_register_designed_agent()` | Reused for warm boot agent registration (no code duplication) |

---

## Architectural Notes

- **Why Git, not SQLite?** SQLite is already used for EpisodicMemory, TrustNetwork, and HebbianRouter — but each creates its own temp-dir database. A single Git repo unifies all artifact types, provides versioning and rollback that SQLite doesn't, produces human-readable artifacts, and enables future cross-node sync via standard Git protocols. Git is universally available on developer machines.

- **Why not a database migration?** Consolidating the three existing SQLite databases into a single persistent SQLite database was considered. This would be simpler but loses versioning, rollback, and human readability. The Git approach is slightly more work upfront but pays off in debuggability.

- **Coexistence with existing SQLite.** The existing `EpisodicMemory`, `TrustNetwork`, and `HebbianRouter` continue to use their SQLite databases as the hot, in-process store. The knowledge repo is the cold, durable store. On boot, the knowledge repo seeds the SQLite databases. During operation, both are updated. This avoids changing any existing data access patterns — the hot path (SQLite queries) remains fast.

- **AD-159 — Late git init.** The repo is not git-initialized on boot because the system may run in read-only or temporary contexts where no knowledge needs to persist. Git init happens on the first write, ensuring the repo is only created when there's something to store.

- **AD-161 — Debounce, not write-through.** Committing on every `store_episode()` call would generate hundreds of commits per session. The debounce timer batches writes into logical units. A 5-second window means rapid-fire operations (like 5 DAG nodes completing in sequence) produce one commit, not five.

- **AD-162 — Trust-first warm boot.** Designed agents restored on warm boot need their earned trust scores, not the default probationary prior. Loading trust before agents ensures `_set_probationary_trust()` is skipped (or overridden) for agents that already have trust history.

- **AD-164 — Per-artifact rollback.** `git revert` operates on entire commits, which may contain changes to multiple artifacts (e.g., a dream cycle commits trust + routing + episodes together). Per-artifact rollback uses `git log --follow` to find the commit that last changed a specific file, then `git show` to retrieve the previous version. This is more surgical than `git revert`.
