# AD-264: `probos reset` CLI Subcommand — Clean Slate Without Deleting Repo Structure

## Context

During development, self-mod creates designed agents, trust scores diverge, Hebbian weights accumulate, episodes pile up. `--fresh` only skips restore for one session — next normal boot restores everything. There's no way to permanently wipe learned state and start clean.

**Need:** `probos reset` that empties the KnowledgeStore artifacts, resets all in-memory state, and Git-commits the empty state as an auditable event.

## Design

### CLI: `probos reset` subcommand in `__main__.py`

Add a `reset` subcommand to the argparse subparsers:

```
probos reset              # Interactive confirmation, resets everything
probos reset --yes        # Skip confirmation
probos reset --keep-trust # Reset everything EXCEPT trust scores
```

This is an **offline command** — it does NOT boot the runtime. It directly manipulates the KnowledgeStore on disk, like `probos init`.

### Implementation: `_cmd_reset()` in `__main__.py`

The function should:

1. Load config via `_load_config_with_fallback(args.config)` to find the `knowledge.repo_path`
2. Resolve the data directory: `args.data_dir or _default_data_dir()`
3. Unless `--yes`, prompt: `"This will permanently delete all learned state (designed agents, trust, routing weights, episodes, workflows, QA reports). Continue? [y/N]: "` — default No
4. For each subdirectory in `_SUBDIRS` = `("episodes", "agents", "skills", "trust", "routing", "workflows", "qa")`:
   - Skip `"trust"` if `--keep-trust` was passed
   - Delete all files (`*.json`, `*.py`) inside the subdirectory but keep the directory itself
5. Also clear the ChromaDB data if it exists:
   - The ChromaDB persistence path is `data_dir / "chroma"` (check how `_boot_runtime()` constructs it — look for `EpisodicMemory` or `chromadb` in `__main__.py`)
   - Delete the chroma directory entirely if it exists (`shutil.rmtree`)
6. If the KnowledgeStore repo has `.git`, run a Git commit: `"probos reset: cleared all artifacts"`
7. Print summary: `"Reset complete. Cleared: episodes, agents, skills, trust, routing, workflows, qa. ChromaDB wiped."`

### Key details

- Import `shutil` for `rmtree`
- Use `Path.glob("*")` to delete files within subdirs, NOT `shutil.rmtree` on the subdirs themselves (preserve directory structure)
- The Git commit uses the same subprocess pattern as `KnowledgeStore._git_commit()` — run `git -C <repo_path> add -A && git -C <repo_path> commit -m "..."` via `subprocess.run`
- Do NOT import or instantiate `KnowledgeStore` — this is a standalone offline operation
- Filter files to delete: only `*.json` and `*.py` files (don't delete `.gitkeep` or other metadata)

## Files to change

### `src/probos/__main__.py`

1. Add `reset` subcommand to argparse (after `serve_parser`):
   ```python
   reset_parser = subparsers.add_parser("reset", help="Clear all learned state (designed agents, trust, episodes, etc.)")
   reset_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
   reset_parser.add_argument("--keep-trust", action="store_true", help="Preserve trust scores")
   reset_parser.add_argument("--config", "-c", type=Path, default=None, help="Path to config YAML")
   reset_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")
   ```

2. Add dispatch in `main()` (after `if args.command == "init":`):
   ```python
   if args.command == "reset":
       _cmd_reset(args)
       return
   ```

3. Add `_cmd_reset(args)` function. Use Rich console for output. Pattern follows `_cmd_init()`.

### `tests/test_distribution.py` (or create `tests/test_reset.py`)

Add tests — check which test file has the `probos init` tests and add reset tests there. If `test_distribution.py` has the init tests, add reset tests there. Tests:

1. `test_reset_clears_artifacts` — create temp KnowledgeStore dir with fake files, run reset logic, verify files gone, dirs preserved
2. `test_reset_keeps_trust_with_flag` — create fake trust files, run reset with `--keep-trust`, verify trust files survive
3. `test_reset_clears_chromadb` — create fake chroma dir, run reset, verify deleted
4. `test_reset_no_crash_empty_repo` — run reset on empty/nonexistent dir, no crash

### `PROGRESS.md`

Update:
- Status line (line 3) with new test count
- Add AD-264 section before `## Active Roadmap`:

```
### AD-264: `probos reset` CLI Subcommand

**Problem:** No way to permanently clear learned state during development. `--fresh` skips restore for one session but data persists. Manual deletion of `data/knowledge/` works but has no audit trail and can miss ChromaDB.

| AD | Decision |
|----|----------|
| AD-264 | Offline CLI command `probos reset` that clears all KnowledgeStore artifacts (episodes, agents, skills, trust, routing, workflows, QA) + ChromaDB data. Git-commits the empty state. `--yes` skips confirmation, `--keep-trust` preserves trust scores. Does NOT boot the runtime |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/__main__.py` | Added `reset` subcommand to argparse, `_cmd_reset()` implementation |
| `tests/test_distribution.py` (or `tests/test_reset.py`) | 4 new tests: clear artifacts, keep-trust flag, clear ChromaDB, empty repo safety |

NNNN/NNNN tests passing (+ 11 skipped). 4 new tests.
```

Replace NNNN with the actual test count.

## Constraints — Do NOT change

- Do NOT modify `runtime.py` — this is an offline command, not a runtime operation
- Do NOT modify `knowledge/store.py` — we're operating directly on the filesystem
- Do NOT modify any agent, mesh, consensus, or cognitive files
- Do NOT modify the HXI/UI
- Do NOT add `--reset` as a boot-time flag — it's a separate subcommand because it's destructive and should not accidentally run during normal boot
- Do NOT delete the `.git` directory — the reset itself should be a committed event
- Do NOT delete the subdirectories themselves — only their contents

## Acceptance criteria

1. `probos reset --yes` clears all artifact files from each KnowledgeStore subdirectory
2. `probos reset --yes --keep-trust` preserves files in the `trust/` subdirectory
3. ChromaDB persistence directory is deleted
4. If Git repo exists, a commit is created recording the reset
5. Without `--yes`, user is prompted for confirmation (default No)
6. All existing tests pass. 4 new tests pass.
7. Running `probos reset --yes` followed by `probos serve` boots cleanly with no restored state
