# AD-302: Builder Agent — Code Generation via LLM

*"The ship builds itself — with the Captain's approval."*

This is the first step toward the automated federation northstar: a CognitiveAgent that accepts structured build specs, generates code via the deep LLM tier, writes files to disk, runs validation (pytest), creates a git branch with the changes, and surfaces results for Captain approval. It extends the self-mod pattern from "generate one agent class" to "execute a general code change."

**Current AD count:** AD-301. This prompt uses AD-302+.
**Current test count:** 1746 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/cognitive_agent.py` — CognitiveAgent base class, lifecycle methods
2. `src/probos/cognitive/self_mod.py` — existing self-mod pipeline (pattern reference for approval gate, validation, and staged execution)
3. `src/probos/cognitive/agent_designer.py` — how LLM code generation works today (prompt formatting, response cleanup)
4. `src/probos/runtime.py` lines 220-270 — agent registration, lines 525-570 — pool group registration
5. `src/probos/substrate/pool_group.py` — PoolGroup/PoolGroupRegistry
6. `src/probos/api.py` lines 302-530 — selfmod approve flow (pattern for async pipeline with WebSocket progress events)
7. `src/probos/types.py` — LLMRequest, LLMResponse, IntentDescriptor, IntentMessage, IntentResult

---

## What To Build

### Step 1: BuildSpec dataclass (AD-302)

**File:** `src/probos/cognitive/builder.py` (new file)

Create a `BuildSpec` dataclass that describes a code change to execute:

```python
@dataclass
class BuildSpec:
    """A structured specification for a code change."""
    title: str                              # Short description, e.g. "Add VectorStore ABC"
    description: str                        # Detailed spec: what to build, why, constraints
    target_files: list[str] = field(default_factory=list)  # Files to create or modify
    reference_files: list[str] = field(default_factory=list)  # Files to read for context
    test_files: list[str] = field(default_factory=list)    # Test files to create/modify
    ad_number: int = 0                      # Architectural decision number
    branch_name: str = ""                   # Git branch name (auto-generated if empty)
    constraints: list[str] = field(default_factory=list)  # "Do NOT" rules
```

Also create a `BuildResult` dataclass:

```python
@dataclass
class BuildResult:
    """Result of a builder agent execution."""
    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""                   # pytest output summary
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""                    # Raw LLM response for review
```

### Step 2: BuilderAgent class (AD-302)

**File:** `src/probos/cognitive/builder.py` (same file)

Create `BuilderAgent` as a CognitiveAgent subclass. This is a **domain-tier** agent in the Engineering team.

```python
class BuilderAgent(CognitiveAgent):
    agent_type = "builder"
    tier = "domain"
    _handled_intents = {"build_code"}
    intent_descriptors = [
        IntentDescriptor(
            name="build_code",
            params={
                "title": "Short title for the code change",
                "description": "Detailed specification of what to build",
            },
            description="Generate code changes from a build specification. Creates a git branch, writes code, runs tests, and presents results for Captain approval.",
            requires_consensus=True,    # Code generation requires consensus
            requires_reflect=False,
            tier="domain",
        ),
    ]

    instructions = """You are the Builder Agent for ProbOS, a probabilistic agent-native OS.
Your job is to execute code changes based on build specifications.

When given a build spec:
1. Read the reference files to understand the existing code patterns
2. Plan the changes needed to fulfill the specification
3. Generate the code for EACH target file, following existing patterns exactly
4. Generate test code for the test files specified
5. Present the complete set of file changes

IMPORTANT RULES:
- Follow existing code patterns in the codebase exactly (imports, naming, style)
- Every public function/method needs a test
- Use the same typing patterns as existing code (from __future__ import annotations, etc.)
- Do NOT add features beyond what the spec requests
- Do NOT modify files that aren't listed in target_files or test_files
- Include the AD number in code comments where relevant

OUTPUT FORMAT:
For each file, output a block like:
===FILE: path/to/file.py===
<complete file contents or changes>
===END FILE===

If modifying an existing file, output ONLY the new/changed functions or sections, with
markers showing where they go:
===MODIFY: path/to/file.py===
===AFTER LINE: <line content to insert after>===
<new code>
===END MODIFY===
"""
```

**Key design decisions:**

- `requires_consensus=True` — code generation is a significant action, should go through consensus
- The agent uses the **deep** LLM tier for code generation quality. Override `_resolve_tier()`:

```python
def _resolve_tier(self) -> str:
    """Builder uses deep tier for code generation quality."""
    return "deep"
```

- Override `perceive()` to read reference files and include their contents in the observation:

```python
async def perceive(self, intent: Any) -> dict:
    """Read reference files and build context for the LLM."""
    obs = await super().perceive(intent)

    # Extract build spec from intent params
    params = obs.get("params", {})
    reference_files = params.get("reference_files", [])

    # Read reference file contents via the filesystem
    file_contexts = []
    for ref_path in reference_files:
        try:
            full_path = Path(ref_path)
            if full_path.exists() and full_path.is_file():
                content = full_path.read_text(encoding="utf-8")
                file_contexts.append(f"=== {ref_path} ===\n{content}\n")
        except Exception:
            file_contexts.append(f"=== {ref_path} === (could not read)\n")

    obs["file_context"] = "\n".join(file_contexts)
    return obs
```

- Override `_build_user_message()` to format the build spec cleanly for the LLM:

```python
def _build_user_message(self, observation: dict) -> str:
    """Format the build spec and reference files into an LLM prompt."""
    params = observation.get("params", {})
    title = params.get("title", "Untitled")
    description = params.get("description", "")
    target_files = params.get("target_files", [])
    test_files = params.get("test_files", [])
    constraints = params.get("constraints", [])
    ad_number = params.get("ad_number", 0)
    file_context = observation.get("file_context", "")

    parts = [
        f"# Build Spec: {title}",
        f"AD Number: AD-{ad_number}" if ad_number else "",
        f"\n## Description\n{description}",
    ]

    if target_files:
        parts.append(f"\n## Target Files\n" + "\n".join(f"- {f}" for f in target_files))
    if test_files:
        parts.append(f"\n## Test Files\n" + "\n".join(f"- {f}" for f in test_files))
    if constraints:
        parts.append(f"\n## Constraints\n" + "\n".join(f"- {c}" for c in constraints))
    if file_context:
        parts.append(f"\n## Reference Code\n{file_context}")

    return "\n".join(p for p in parts if p)
```

- Override `act()` to parse the LLM output, write files, run tests, and create a git branch:

```python
async def act(self, decision: dict) -> dict:
    """Parse LLM output, write files, run tests, create git branch."""
    if decision.get("action") == "error":
        return {"success": False, "error": decision.get("reason")}

    llm_output = decision.get("llm_output", "")

    # Parse file blocks from LLM output
    file_changes = self._parse_file_blocks(llm_output)
    if not file_changes:
        return {
            "success": False,
            "error": "LLM output contained no file blocks",
            "llm_output": llm_output,
        }

    # Store parsed changes but do NOT write yet — return for approval
    return {
        "success": True,
        "result": {
            "file_changes": file_changes,
            "llm_output": llm_output,
            "change_count": len(file_changes),
        },
    }
```

Note: The `act()` method does **NOT** write files or create git branches directly. Instead, it returns the parsed changes for the Captain to review and approve. The actual file writing and git operations happen in a separate approval step (Step 4).

Add a `_parse_file_blocks()` static method that extracts file paths and content from the LLM's `===FILE:===` and `===MODIFY:===` markers. Return a list of dicts: `{"path": str, "content": str, "mode": "create"|"modify", "after_line": str|None}`.

### Step 3: Git operations helper (AD-303)

**File:** `src/probos/cognitive/builder.py` (same file, module-level functions)

Add module-level async helper functions for git operations. These use `asyncio.create_subprocess_exec` (NOT subprocess.run — stay async). The functions:

```python
async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
    """Create and checkout a new git branch. Returns (success, message)."""

async def _git_add_and_commit(files: list[str], message: str, work_dir: str) -> tuple[bool, str]:
    """Stage files and commit. Returns (success, commit_hash_or_error)."""

async def _git_checkout_main(work_dir: str) -> tuple[bool, str]:
    """Switch back to main branch. Returns (success, message)."""

async def _git_current_branch(work_dir: str) -> str:
    """Return the name of the current branch."""
```

Important safety rules:
- All git commands use `asyncio.create_subprocess_exec` (not `subprocess`), with `cwd=work_dir`
- Never force-push, never delete branches, never reset
- Branch names are sanitized: lowercase, alphanumeric + hyphens only, max 50 chars
- Commit messages include `Co-Authored-By: ProbOS Builder <probos@probos.dev>`
- If anything fails, return `(False, error_message)` — never raise

### Step 4: Build execution pipeline (AD-303)

**File:** `src/probos/cognitive/builder.py` (same file)

Add a standalone async function (NOT a method on BuilderAgent — keeps the agent clean) that orchestrates the full build pipeline after Captain approval:

```python
async def execute_approved_build(
    file_changes: list[dict],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    This is called AFTER the Captain reviews the BuilderAgent's output
    and approves the changes. The agent generates the plan; this function
    executes it.
    """
```

Pipeline steps:
1. Save the current branch name
2. Generate branch name from spec title if not provided: `builder/ad-{N}-{slugified-title}`
3. Create a new git branch via `_git_create_branch()`
4. Write each file change to disk (create parent dirs if needed)
5. If `run_tests` is True, run `pytest` via `asyncio.create_subprocess_exec` with a 120s timeout. Capture stdout/stderr
6. Stage all changed files and commit with message: `"{spec.title} (AD-{spec.ad_number})\n\n{spec.description[:200]}\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"`
7. Switch back to the original branch (leave the builder branch for Captain to review/merge)
8. Return `BuildResult` with all details

If any step fails, attempt to switch back to the original branch and return `BuildResult(success=False, error=...)`.

### Step 5: Register BuilderAgent in runtime (AD-302)

**File:** `src/probos/runtime.py`

1. Add import at the top with the other agent imports:
```python
from probos.cognitive.builder import BuilderAgent
```

2. Register the template alongside other agent registrations (after the medical team block, around line 261):
```python
# Engineering team (AD-302)
self.spawner.register_template("builder", BuilderAgent)
```

3. Add pool group registration in `start()` (after the security pool group, around line 567):
```python
# Engineering pool group (AD-302)
self.pool_groups.register(PoolGroup(
    name="engineering",
    display_name="Engineering",
    pool_names={"builder"},
    exclude_from_scaler=True,
))
```

4. Create the builder pool in `start()` alongside other pool creation logic. Add it after the medical pools are created. Guard it behind a config check — for now, always create it if bundled agents are enabled:

```python
# Engineering team — Builder Agent (AD-302)
if self.config.bundled_agents.enabled:
    await self.create_pool(
        "builder", "builder", target_size=1,
        llm_client=self.llm_client, runtime=self,
    )
```

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

### Step 6: Tests (AD-302)

**File:** `tests/test_builder_agent.py` (new file)

Write tests covering:

1. **BuildSpec creation** — verify default values, field population
2. **BuildResult creation** — verify default values
3. **BuilderAgent instantiation** — verify it's a CognitiveAgent subclass with correct `agent_type`, `_handled_intents`, `intent_descriptors`, `tier`
4. **BuilderAgent._resolve_tier()** — returns `"deep"`
5. **BuilderAgent._parse_file_blocks()** — test with:
   - Single `===FILE:===` block → returns correct path and content
   - Multiple file blocks → returns all
   - `===MODIFY:===` block with `===AFTER LINE:===` → correct mode and after_line
   - No blocks → returns empty list
   - Malformed input → returns empty list
6. **BuilderAgent._build_user_message()** — verify it formats spec fields correctly, handles missing fields gracefully
7. **BuilderAgent.perceive()** — mock file reads, verify file_context is populated
8. **BuilderAgent.act()** — mock decision with LLM output containing file blocks, verify parsed output
9. **Git helper function tests** (if feasible — may need to mock `asyncio.create_subprocess_exec`):
   - `_git_create_branch()` with sanitized name
   - Branch name sanitization (special chars removed, max length)
10. **execute_approved_build()** — mock git operations and file I/O, verify full pipeline flow

Use `unittest.mock.AsyncMock` for async mocking. Follow the existing test patterns (see `tests/test_cognitive_agent.py` and `tests/test_self_mod.py` for style reference).

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_builder_agent.py -x -v`

Then run the full suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-302 | BuilderAgent — CognitiveAgent subclass (domain tier, Engineering team) that accepts BuildSpec, generates code via deep LLM tier, parses file changes from LLM output. Does NOT write files directly — returns parsed changes for Captain approval. Registered as `builder` type in `builder` pool, `engineering` pool group. `requires_consensus=True` on the `build_code` intent |
| AD-303 | Git integration helpers — async git operations via `asyncio.create_subprocess_exec`. Branch creation (`builder/ad-{N}-{slug}`), staging, committing with ProbOS Builder co-author. `execute_approved_build()` orchestrates the full post-approval pipeline: branch → write files → test → commit → return to main. Never force-pushes, never deletes |

---

## Do NOT Build

- **API endpoint for triggering builds** — future step. For now, the BuilderAgent is invoked via intent bus like any other agent
- **HXI UI for build approval** — future step. Use existing approval patterns
- **Architect Agent** — separate future work. The Builder accepts specs, it doesn't create them
- **Full A2A integration** — the medium win is using the existing LLM tier, not A2A protocol
- **Automatic merging** — the Captain always merges. Builder creates the branch, Captain decides
- **File modification (MODIFY mode) implementation** — implement ONLY the `create` mode for now. Parse MODIFY blocks but log a warning and skip them. Full diff-based modification is a follow-up

---

## Constraints

- Do NOT add new dependencies to `pyproject.toml` — use only stdlib (`asyncio`, `pathlib`, `re`) and existing ProbOS imports
- Do NOT modify `self_mod.py` or `agent_designer.py` — Builder is a parallel path, not a modification of self-mod
- Do NOT import `subprocess` — use `asyncio.create_subprocess_exec` exclusively
- The `builder.py` module must be self-contained (BuildSpec, BuildResult, BuilderAgent, git helpers, execute pipeline — all in one file)
- Follow existing code style: `from __future__ import annotations`, type hints, docstrings on public methods
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## Update PROGRESS.md When Done

Add to the AD table:

```
| AD-302 | BuilderAgent — CognitiveAgent (domain/Engineering) that generates code from BuildSpec via deep LLM tier. Parses file blocks from LLM output, returns for Captain approval. Registered as `builder` in `engineering` pool group with consensus required |
| AD-303 | Git integration — async git helpers (branch, commit, checkout) via asyncio.create_subprocess_exec. `execute_approved_build()` pipeline: branch → write → test → commit. ProbOS Builder as git co-author |
```

Update the status line test count to reflect any new tests added.
