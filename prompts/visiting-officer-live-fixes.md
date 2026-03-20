# Build Prompt: Visiting Officer Live Testing Fixes (AD-355)

## Context

Live HXI testing of the Visiting Officer (Copilot SDK adapter) revealed three
issues that need to be fixed to make the visiting builder reliable and
production-ready.

---

## Issue 1: SDK Agent Wastes Time Exploring Filesystem

**Problem:** The visiting builder SDK agent receives a temp directory as its
working directory. The temp dir starts with only the target files copied in
(or is empty for new-file builds). The SDK agent wastes 30-60 seconds running
`ls`, `find`, `cat`, etc. trying to discover the ProbOS codebase structure
before writing any code.

**Root cause:** The system prompt (`_VISITING_BUILDER_INSTRUCTIONS` in
`copilot_adapter.py`) doesn't tell the agent that:
- It's working in an isolated temp directory, not the project root
- It should NOT explore the filesystem — all project context comes through MCP tools
- It should write files directly to the current directory using the paths from the build spec

**Fix in `src/probos/cognitive/copilot_adapter.py`:**

Update `_VISITING_BUILDER_INSTRUCTIONS` to add a `WORKING ENVIRONMENT` section
**before** the `OUTPUT FORMAT` section. Add these directives:

```
WORKING ENVIRONMENT:
- You are operating in an ISOLATED temp directory, not the project root
- Do NOT explore the filesystem (no ls, find, tree, cat of project files)
- All project context is available through your MCP tools (codebase_query, codebase_read_source, etc.)
- Write all output files directly to the current directory using the paths from the build spec
- For existing files that need modification, their current content is provided in the prompt below
- Source files go under src/probos/ — test files go under tests/
```

Also add a `PROJECT STRUCTURE` section after `WORKING ENVIRONMENT`:

```
PROJECT STRUCTURE:
- Source code: src/probos/ (packages: cognitive/, mesh/, medical/, api.py, shell.py, etc.)
- Tests: tests/ (flat layout: tests/test_builder_agent.py, tests/test_trust.py, etc.)
- Config: config/ (standing_orders/, extension_profiles/)
- All imports use absolute paths: from probos.cognitive.builder import BuilderAgent
- Test files are named: test_{module_name}.py
```

This ensures the SDK agent knows the project layout without needing to explore.

---

## Issue 2: Reduce Diagnostic Logging

**Problem:** During debugging, verbose diagnostic logging was added to the
adapter's `execute()` method. Now that disk scan is working, the event-type
dumps and text output previews should be scaled back.

**Fix in `src/probos/cognitive/copilot_adapter.py`:**

1. The `logger.info("Visiting builder: %d messages from session", len(messages))`
   line (around line 444) — **keep this**, it's useful operational info.

2. The `logger.info("Visiting builder: found %d changed files on disk: %s", ...)`
   line (around line 474) — **keep this**, but change to `logger.debug` level.

3. The `logger.info("Captured changed file: %s (%s)", rel_path, mode)` line
   (around line 488) — change to `logger.debug`.

4. The message count log should stay at `info` but simplify to just count +
   file count:
   ```python
   logger.info("Visiting builder: %d messages, %d files captured", len(messages), len(changed_paths))
   ```
   Move this to AFTER the disk scan completes so it includes the file count.
   Remove the earlier message-count-only log line.

---

## Issue 3: Test Gate Path Issue for Visiting Officer Builds

**Problem:** When the visiting officer creates new files, it may place them at
paths that don't work with pytest's module resolution. For example, the SDK
agent wrote `hello.py` at the project root and `tests/test_hello.py` with
`from hello import greet`. When pytest runs from the project root, `hello.py`
isn't on `sys.path` because the project uses `src/` layout.

**Root cause:** Two issues:
1. The system prompt doesn't enforce the `src/probos/` source layout (fixed by Issue 1)
2. `_run_targeted_tests()` and `_run_tests()` don't add the project root to
   `PYTHONPATH`, so root-level files can't be imported

**Fix in `src/probos/cognitive/builder.py`:**

In both `_run_tests()` and `_run_targeted_tests()`, add the project root
to `PYTHONPATH` in the subprocess environment. This ensures that even if a
visiting officer places a file at the project root, tests can still import it.

In both functions, inside `_sync_run()`, before the `subprocess.run()` call,
build an env dict:

```python
import os
env = os.environ.copy()
# Ensure project root and src/ are on PYTHONPATH for imports
src_dir = str(Path(work_dir) / "src")
existing = env.get("PYTHONPATH", "")
env["PYTHONPATH"] = f"{work_dir}{os.pathsep}{src_dir}" + (f"{os.pathsep}{existing}" if existing else "")
```

Then pass `env=env` to the `subprocess.run()` call.

---

## Test Requirements

### New Tests (add to `tests/test_copilot_adapter.py`)

1. **`test_system_prompt_contains_working_environment`** — Verify that
   `_VISITING_BUILDER_INSTRUCTIONS` contains "ISOLATED temp directory" and
   "Do NOT explore the filesystem".

2. **`test_system_prompt_contains_project_structure`** — Verify that
   `_VISITING_BUILDER_INSTRUCTIONS` contains "src/probos/" and "tests/".

### Existing Tests

3. Verify all existing `test_copilot_adapter.py` tests still pass.

4. Verify all existing `test_builder_agent.py` tests still pass (test gate changes).

---

## Files to Modify

- `src/probos/cognitive/copilot_adapter.py` — Issues 1, 2
- `src/probos/cognitive/builder.py` — Issue 3
- `tests/test_copilot_adapter.py` — New tests

## Constraints

- Do NOT modify any other files
- Do NOT change the disk scan logic (it's working correctly)
- Do NOT change the MCP tool registrations
- Keep all existing tests passing
- Use `logger.debug` for verbose diagnostics, `logger.info` for operational summaries
