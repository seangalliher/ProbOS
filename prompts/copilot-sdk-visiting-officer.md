# Build Prompt: Copilot SDK Visiting Officer Integration (AD-351, AD-352, AD-353)

## Overview

Integrate the GitHub Copilot SDK (`github-copilot-sdk` Python package) as a **visiting officer** for the Builder role. The visiting Builder receives the same Standing Orders as native crew, accesses ProbOS internals via MCP tools, and is governed by the same trust/consensus pipeline. The native Builder learns from the visiting Builder via Hebbian routing.

Three ADs:
1. **AD-351: CopilotBuilderAdapter** — wraps the Copilot SDK, translates BuildSpec → Copilot session, captures file changes
2. **AD-352: ProbOS MCP Tool Server** — exposes CodebaseIndex, SystemSelfModel, and StandingOrders as MCP tools for the visiting Builder
3. **AD-353: Routing & Apprenticeship Wiring** — `_should_use_visiting_builder()` decision, Hebbian `(task_type, builder_variant)` tracking, `builder_source` tagging on BuildResult

---

## Dependency: Install the SDK

Add `github-copilot-sdk` to the project's optional dependencies. The SDK is in Technical Preview (alpha status, v0.1.32+, Python 3.11+).

In `pyproject.toml`, add an optional dependency group:

```toml
[project.optional-dependencies]
copilot = ["github-copilot-sdk>=0.1.30"]
```

The adapter must handle the case where the SDK is NOT installed (ImportError → graceful fallback to native Builder). Never make the SDK a hard dependency.

---

## AD-351: CopilotBuilderAdapter

### New File: `src/probos/cognitive/copilot_adapter.py`

This is a **standalone adapter**, NOT a CognitiveAgent subclass. It wraps the Copilot SDK and is called by the BuilderAgent when routing selects the visiting builder. It mirrors the ChannelAdapter pattern (adapter wraps an external system, ProbOS orchestrates).

#### Imports

```python
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.knowledge.codebase_index import CodebaseIndex
```

#### Constants

```python
_SDK_AVAILABLE = False
try:
    from copilot import CopilotClient, define_tool, Tool
    _SDK_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
```

#### `CopilotBuildResult` dataclass

```python
@dataclass
class CopilotBuildResult:
    """Result from a visiting Builder Copilot session."""
    success: bool = False
    file_blocks: list[dict[str, Any]] = field(default_factory=list)
    raw_output: str = ""
    error: str = ""
    session_id: str = ""
    model_used: str = ""
```

- `file_blocks` uses the same format as `BuilderAgent._parse_file_blocks()`: each dict has `{"path": str, "mode": "create"|"modify", "content": str, "replacements": [{"search": str, "replace": str}]}`

#### `CopilotBuilderAdapter` class

```python
class CopilotBuilderAdapter:
    """Wraps the GitHub Copilot SDK to execute build tasks as a visiting officer.

    The adapter:
    1. Creates a CopilotClient with ProbOS's Standing Orders as system instructions
    2. Registers ProbOS MCP tools (CodebaseIndex, SystemSelfModel, StandingOrders)
    3. Translates a BuildSpec into a Copilot session prompt
    4. Captures file changes from the session output
    5. Returns file blocks in the same format as the native Builder
    """
```

##### Constructor

```python
def __init__(
    self,
    *,
    codebase_index: CodebaseIndex | None = None,
    runtime: Any | None = None,
    model: str = "",
    cwd: str = "",
) -> None:
```

- `codebase_index` — for MCP tool queries
- `runtime` — for SystemSelfModel and Standing Orders
- `model` — Copilot model name override (default: let SDK pick)
- `cwd` — working directory for the Copilot CLI process (default: `_PROJECT_ROOT`)
- Store `self._client: CopilotClient | None = None`
- Store `self._started = False`

##### `is_available()` class method

```python
@classmethod
def is_available(cls) -> bool:
    """Check if the Copilot SDK is installed."""
    return _SDK_AVAILABLE
```

##### `start()` async method

```python
async def start(self) -> None:
    """Initialize the CopilotClient. Call once at startup."""
```

- Guard: `if not _SDK_AVAILABLE: raise RuntimeError("github-copilot-sdk not installed")`
- Create `CopilotClient` with config:
  - `cwd`: `self._cwd or str(_PROJECT_ROOT)`
  - `use_logged_in_user`: `True`
  - `log_level`: `"warning"`
- Call `await self._client.start()`
- Set `self._started = True`

##### `stop()` async method

```python
async def stop(self) -> None:
    """Shut down the CopilotClient."""
```

- If `self._client` and `self._started`: `await self._client.stop()`
- Set `self._started = False`

##### `_compose_system_message()` method

```python
def _compose_system_message(self) -> dict[str, Any]:
    """Build the system message for the Copilot session.

    Uses compose_instructions() to assemble the full Standing Orders
    hierarchy, matching what the native Builder receives.
    """
```

- Import `compose_instructions` from `probos.cognitive.standing_orders`
- Call `compose_instructions(agent_type="builder", hardcoded_instructions=_VISITING_BUILDER_INSTRUCTIONS)`
- Return `{"type": "text", "text": composed}`

Where `_VISITING_BUILDER_INSTRUCTIONS` is a module-level constant:

```python
_VISITING_BUILDER_INSTRUCTIONS = (
    "You are the ProbOS Visiting Builder — a visiting officer from the Copilot fleet, "
    "operating under ProbOS Standing Orders. You write code for ProbOS build tasks.\n\n"
    "OUTPUT FORMAT:\n"
    "For new files, use:\n"
    "===FILE: path/relative/to/project===\n"
    "file content here\n"
    "===END FILE===\n\n"
    "For modifications to existing files, use:\n"
    "===MODIFY: path/relative/to/project===\n"
    "===SEARCH===\n"
    "exact text to find\n"
    "===REPLACE===\n"
    "replacement text\n"
    "===END REPLACE===\n"
    "===END MODIFY===\n\n"
    "RULES:\n"
    "- Follow existing codebase patterns — use the codebase_query tool to find them\n"
    "- Every public function needs a test\n"
    "- Use full probos.* import paths, never relative imports\n"
    "- SEARCH blocks must match EXACTLY — character-for-character\n"
    "- Keep SEARCH blocks small — just enough context to be unique\n"
    "- Order SEARCH/REPLACE pairs top-to-bottom in the file\n"
    "- Use pytest.mark.asyncio for async test methods\n"
    "- Before writing test fixtures, check the target class __init__ signature\n"
)
```

##### `_build_mcp_tools()` method

```python
def _build_mcp_tools(self) -> list[Any]:
    """Build the MCP tools list for the Copilot session.

    Exposes ProbOS internals as tools the visiting Builder can call.
    """
```

Returns a list of `Tool` instances. See AD-352 for tool definitions. If `self._codebase_index` is None, omit CodebaseIndex tools. If `self._runtime` is None, omit SystemSelfModel tool.

##### `_build_prompt(spec)` method

```python
def _build_prompt(self, spec: "BuildSpec", file_contents: dict[str, str]) -> str:
    """Translate a BuildSpec into a prompt for the Copilot session."""
```

Constructs a prompt string containing:
1. Build spec title and AD number
2. Description
3. Target files list
4. Test files list
5. Constraints
6. Contents of existing target files (with instruction: "use MODIFY blocks for these")
7. Contents of reference files (labeled as reference only)

This mirrors `BuilderAgent._build_user_message()` formatting.

Arguments:
- `spec` — the BuildSpec
- `file_contents` — dict of `{relative_path: file_content}` for reference and target files that exist

##### `execute(spec, file_contents)` async method — THE MAIN ENTRY POINT

```python
async def execute(
    self,
    spec: "BuildSpec",
    file_contents: dict[str, str],
    *,
    timeout: float = 300.0,
) -> CopilotBuildResult:
    """Execute a build task using the Copilot SDK.

    Args:
        spec: The build specification
        file_contents: Pre-read file contents (target + reference)
        timeout: Max seconds for the session (default 5 min)

    Returns:
        CopilotBuildResult with file blocks in native Builder format
    """
```

Implementation steps:
1. Guard: `if not self._started: raise RuntimeError("Adapter not started")`
2. Build system message: `self._compose_system_message()`
3. Build MCP tools: `self._build_mcp_tools()`
4. Build prompt: `self._build_prompt(spec, file_contents)`
5. Create session config:
   ```python
   session_config = {
       "system_message": system_message,
       "tools": tools,
   }
   if self._model:
       session_config["model"] = self._model
   ```
6. Create session: `session = await self._client.create_session(session_config)`
7. Collect output using event handler:
   ```python
   collected_output = []

   def on_event(event):
       if event.type.value == "assistant.message":
           collected_output.append(event.data.content)

   session.on(on_event)
   ```
8. Send prompt: `await session.send({"prompt": prompt})`
9. Wait for `session.idle` event with timeout:
   ```python
   idle_event = asyncio.Event()

   def on_idle(event):
       if event.type.value == "session.idle":
           idle_event.set()

   session.on(on_idle)
   await asyncio.wait_for(idle_event.wait(), timeout=timeout)
   ```
10. Disconnect: `await session.disconnect()`
11. Parse output: join `collected_output`, call `BuilderAgent._parse_file_blocks()` on the full text
12. Return `CopilotBuildResult(success=bool(file_blocks), file_blocks=file_blocks, raw_output=full_output, session_id=...)`

Wrap the entire operation in try/except. On ANY exception, return `CopilotBuildResult(success=False, error=str(e))`.

**IMPORTANT:** The Copilot SDK is alpha. Wrap every SDK call in try/except. Never let a SDK error crash ProbOS.

##### `_parse_file_blocks(text)` — reuse static method

Import and reuse `BuilderAgent._parse_file_blocks()` from `probos.cognitive.builder`. Do NOT duplicate the parsing logic.

```python
from probos.cognitive.builder import BuilderAgent
blocks = BuilderAgent._parse_file_blocks(text)
```

---

## AD-352: ProbOS MCP Tool Server

### Additions to: `src/probos/cognitive/copilot_adapter.py`

The MCP tools are defined INSIDE `_build_mcp_tools()` using the Copilot SDK's `Tool` class. They are NOT a separate MCP server process — they are registered directly with the Copilot session.

Define these tools:

#### Tool 1: `codebase_query`

```python
Tool(
    name="codebase_query",
    description="Search the ProbOS codebase for files, agents, methods, and layers matching a concept keyword. Returns matching files, agents, and methods.",
    parameters={
        "type": "object",
        "properties": {
            "concept": {
                "type": "string",
                "description": "The concept or keyword to search for (e.g., 'trust', 'HebbianRouter', 'pool health')"
            }
        },
        "required": ["concept"]
    },
    handler=self._handle_codebase_query,
)
```

Handler:
```python
async def _handle_codebase_query(self, invocation: dict) -> dict:
    params = invocation.get("parameters", {})
    concept = params.get("concept", "")
    if not self._codebase_index or not concept:
        return {"textResultForLlm": "CodebaseIndex not available", "resultType": "success"}
    result = self._codebase_index.query(concept)
    return {"textResultForLlm": json.dumps(result, indent=2, default=str), "resultType": "success"}
```

#### Tool 2: `codebase_find_callers`

```python
Tool(
    name="codebase_find_callers",
    description="Find all files that call/reference a given method name in the ProbOS codebase.",
    parameters={
        "type": "object",
        "properties": {
            "method_name": {"type": "string", "description": "The method name to find callers of"}
        },
        "required": ["method_name"]
    },
    handler=self._handle_find_callers,
)
```

Handler returns `self._codebase_index.find_callers(method_name)` as JSON.

#### Tool 3: `codebase_get_imports`

```python
Tool(
    name="codebase_get_imports",
    description="Get the internal probos modules that a given source file imports.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Relative path to the source file (e.g., 'probos/cognitive/builder.py')"}
        },
        "required": ["file_path"]
    },
    handler=self._handle_get_imports,
)
```

Handler returns `self._codebase_index.get_imports(file_path)` as JSON.

#### Tool 4: `codebase_find_tests`

```python
Tool(
    name="codebase_find_tests",
    description="Find test files for a given source file, by naming convention.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Relative path to the source file"}
        },
        "required": ["file_path"]
    },
    handler=self._handle_find_tests,
)
```

Handler returns `self._codebase_index.find_tests_for(file_path)` as JSON.

#### Tool 5: `codebase_read_source`

```python
Tool(
    name="codebase_read_source",
    description="Read the source code of a file in the ProbOS codebase. Can read specific line ranges.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Relative path to the file"},
            "start_line": {"type": "integer", "description": "Optional start line (1-indexed)"},
            "end_line": {"type": "integer", "description": "Optional end line (1-indexed)"}
        },
        "required": ["file_path"]
    },
    handler=self._handle_read_source,
)
```

Handler returns `self._codebase_index.read_source(file_path, start_line, end_line)` as text.

#### Tool 6: `system_self_model`

```python
Tool(
    name="system_self_model",
    description="Get the current ProbOS system topology: pools, agents, departments, health signals.",
    parameters={"type": "object", "properties": {}},
    handler=self._handle_system_self_model,
)
```

Handler:
```python
async def _handle_system_self_model(self, invocation: dict) -> dict:
    if not self._runtime:
        return {"textResultForLlm": "Runtime not available", "resultType": "success"}
    self_model = self._runtime._build_system_self_model()
    return {"textResultForLlm": self_model.to_context(), "resultType": "success"}
```

#### Tool 7: `standing_orders_lookup`

```python
Tool(
    name="standing_orders_lookup",
    description="Look up the department protocols for a given department (engineering, science, medical, security, bridge).",
    parameters={
        "type": "object",
        "properties": {
            "department": {"type": "string", "description": "Department name"}
        },
        "required": ["department"]
    },
    handler=self._handle_standing_orders,
)
```

Handler reads and returns the content of `config/standing_orders/{department}.md`.

#### Building the tools list

In `_build_mcp_tools()`:
1. Always include `standing_orders_lookup`
2. If `self._codebase_index` is not None, include all `codebase_*` tools
3. If `self._runtime` is not None, include `system_self_model`
4. Return the list

**IMPORTANT:** The `handler` for each Tool can be a sync or async callable. The handler receives a single `invocation` dict argument with a `"parameters"` key. The handler must return a dict with `"textResultForLlm"` (string) and `"resultType"` (string, typically `"success"`).

---

## AD-353: Routing & Apprenticeship Wiring

### Changes to: `src/probos/cognitive/builder.py`

#### 1. Add `builder_source` to `BuildResult`

Add a new field to the `BuildResult` dataclass:

```python
builder_source: str = "native"  # "native" or "visiting"
```

This field is set by the BuilderAgent based on which builder executed the task.

#### 2. Add `_should_use_visiting_builder()` function

New module-level function:

```python
def _should_use_visiting_builder(
    spec: BuildSpec,
    hebbian_router: Any | None = None,
    force_native: bool = False,
    force_visiting: bool = False,
) -> bool:
    """Decide whether to route to the visiting Copilot Builder.

    Decision factors (in priority order):
    1. force_native / force_visiting overrides
    2. Copilot SDK availability
    3. Hebbian weight comparison (if enough history)
    4. Default: prefer visiting (bootstrap phase)

    Args:
        spec: The build specification
        hebbian_router: Optional HebbianRouter for weight lookup
        force_native: Force native builder (e.g., for testing)
        force_visiting: Force visiting builder

    Returns:
        True if the visiting builder should be used
    """
```

Implementation:
1. If `force_native`: return `False`
2. If `force_visiting`: return `True`
3. If `not CopilotBuilderAdapter.is_available()`: return `False`
4. If `hebbian_router is not None`:
   - Look up weight for `("build_code", "visiting", "builder_variant")` vs `("build_code", "native", "builder_variant")`
   - Use `hebbian_router.get_weight("build_code", "visiting", rel_type="builder_variant")` and same for `"native"`
   - If BOTH weights are above 0.1 (enough history), return `visiting_weight > native_weight`
5. Default: return `True` (prefer visiting in bootstrap phase, since it's more capable)

#### 3. Modify `BuilderAgent.perceive()` to support visiting builder

Add visiting builder routing BEFORE the Transporter check. The visiting builder replaces the ENTIRE native pipeline (perceive→decide→act), not just the LLM call.

In `BuilderAgent.perceive()`, after reading files but BEFORE the `_should_use_transporter()` check:

```python
# Visiting builder check
if _should_use_visiting_builder(
    spec,
    hebbian_router=getattr(self._runtime, "hebbian_router", None) if self._runtime else None,
):
    try:
        adapter = CopilotBuilderAdapter(
            codebase_index=getattr(self._runtime, "codebase_index", None) if self._runtime else None,
            runtime=self._runtime,
        )
        await adapter.start()
        try:
            copilot_result = await adapter.execute(spec, file_contents)
        finally:
            await adapter.stop()

        if copilot_result.success and copilot_result.file_blocks:
            self._transporter_result = {
                "action": "transporter_complete",
                "file_blocks": copilot_result.file_blocks,
                "llm_output": copilot_result.raw_output,
                "builder_source": "visiting",
            }
            # Record success for Hebbian learning
            if self._runtime and hasattr(self._runtime, "hebbian_router"):
                self._runtime.hebbian_router.record_interaction(
                    "build_code", "visiting", success=True, rel_type="builder_variant"
                )
            logger.info("Visiting builder produced %d file blocks", len(copilot_result.file_blocks))
            return observation  # Skip native pipeline
        else:
            logger.warning("Visiting builder failed: %s — falling back to native", copilot_result.error)
            # Record failure for Hebbian learning
            if self._runtime and hasattr(self._runtime, "hebbian_router"):
                self._runtime.hebbian_router.record_interaction(
                    "build_code", "visiting", success=False, rel_type="builder_variant"
                )
    except Exception as e:
        logger.warning("Visiting builder error: %s — falling back to native", e)
```

If the visiting builder fails or produces no output, fall through to the native pipeline (Transporter or single-pass). This is the fail-open pattern.

#### 4. Tag `builder_source` in `act()`

In `BuilderAgent.act()`, when building the result dict, include `builder_source`:

```python
# After the transporter_complete branch
if decision.get("action") == "transporter_complete":
    return {
        "success": True,
        "file_blocks": decision["file_blocks"],
        "llm_output": decision.get("llm_output", ""),
        "builder_source": decision.get("builder_source", "native"),
    }
```

#### 5. Propagate `builder_source` through `execute_approved_build()`

In `execute_approved_build()`, accept an optional `builder_source: str = "native"` parameter and set it on the returned `BuildResult`:

```python
async def execute_approved_build(
    file_changes, spec, work_dir, ...,
    builder_source: str = "native",
    ...
) -> BuildResult:
```

At the end, before returning:
```python
result.builder_source = builder_source
```

#### 6. Record Hebbian outcome after test results

In `execute_approved_build()`, after the test-fix loop completes (whether pass or fail), record the final outcome:

```python
# After test results are known
if runtime and hasattr(runtime, "hebbian_router") and builder_source in ("native", "visiting"):
    runtime.hebbian_router.record_interaction(
        "build_code", builder_source, success=result.tests_passed,
        rel_type="builder_variant",
    )
```

This records test outcomes — if the visiting builder's code passes tests, its Hebbian weight increases. If it fails, the weight decreases. Over time, the router learns which builder produces passing code more reliably.

#### 7. Add `"builder_variant"` relationship type constant

In `src/probos/mesh/routing.py`, add a new constant:

```python
REL_BUILDER_VARIANT = "builder_variant"  # build_code -> native|visiting
```

No schema migration needed — the SQLite table already stores `rel_type` as TEXT with composite primary key `(source_id, target_id, rel_type)`.

Import this constant in `builder.py` instead of using the raw string `"builder_variant"`.

---

## New Test File: `tests/test_copilot_adapter.py`

### Test Structure

```python
"""Tests for CopilotBuilderAdapter (AD-351, AD-352, AD-353)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.builder import BuildSpec, BuildResult, _should_use_visiting_builder
```

### Tests for AD-351 (CopilotBuilderAdapter)

1. **`test_is_available_when_sdk_missing`** — Patch `_SDK_AVAILABLE = False`, assert `CopilotBuilderAdapter.is_available()` returns `False`.

2. **`test_is_available_when_sdk_present`** — Patch `_SDK_AVAILABLE = True`, assert returns `True`.

3. **`test_start_raises_without_sdk`** — Patch `_SDK_AVAILABLE = False`, assert `adapter.start()` raises `RuntimeError`.

4. **`test_compose_system_message_includes_standing_orders`** — Create adapter, patch `compose_instructions` to return a known string. Assert `_compose_system_message()` returns dict with `"type"` and `"text"` keys, and the text includes both `_VISITING_BUILDER_INSTRUCTIONS` and the mocked standing orders.

5. **`test_build_prompt_includes_spec_fields`** — Create a BuildSpec with title, description, target_files, test_files, constraints, ad_number. Call `_build_prompt(spec, {})`. Assert output contains all field values.

6. **`test_build_prompt_includes_file_contents`** — Provide `file_contents={"src/foo.py": "def foo(): pass"}`. Assert the prompt includes the file content.

7. **`test_execute_success`** — Mock the CopilotClient and session. The mock session's event handler should emit an `assistant.message` event with content containing `===FILE: src/test.py===\ndef test(): pass\n===END FILE===`. Assert `execute()` returns `CopilotBuildResult(success=True, file_blocks=[...])`.

8. **`test_execute_timeout`** — Mock session that never fires `session.idle`. Assert `execute()` returns `CopilotBuildResult(success=False, error=...)` containing "timeout" or "TimeoutError".

9. **`test_execute_sdk_error`** — Mock `session.send()` to raise an exception. Assert `execute()` returns `CopilotBuildResult(success=False, error=...)`.

10. **`test_build_mcp_tools_with_codebase_index`** — Provide a mock codebase_index. Assert `_build_mcp_tools()` returns 7 tools (5 codebase + system_self_model + standing_orders_lookup).

11. **`test_build_mcp_tools_without_codebase_index`** — No codebase_index, no runtime. Assert `_build_mcp_tools()` returns 1 tool (standing_orders_lookup only).

### Tests for AD-352 (MCP Tool Handlers)

12. **`test_handle_codebase_query`** — Mock codebase_index.query() to return `{"matching_files": ["foo.py"]}`. Call handler. Assert `textResultForLlm` contains `"foo.py"`.

13. **`test_handle_codebase_query_no_index`** — codebase_index is None. Call handler. Assert `textResultForLlm` says "not available".

14. **`test_handle_find_callers`** — Mock find_callers to return results. Assert handler returns them as JSON.

15. **`test_handle_get_imports`** — Mock get_imports to return results. Assert handler returns them as JSON.

16. **`test_handle_find_tests`** — Mock find_tests_for to return results. Assert handler returns them as JSON.

17. **`test_handle_read_source`** — Mock read_source to return file content. Assert handler returns it.

18. **`test_handle_system_self_model`** — Mock `runtime._build_system_self_model()` to return a `SystemSelfModel`. Assert handler returns `to_context()` output.

19. **`test_handle_system_self_model_no_runtime`** — runtime is None. Assert "not available" response.

20. **`test_handle_standing_orders`** — Create a temp standing orders dir with `engineering.md`. Assert handler returns file content.

### Tests for AD-353 (Routing & Apprenticeship)

21. **`test_should_use_visiting_force_native`** — `force_native=True` → returns `False`.

22. **`test_should_use_visiting_force_visiting`** — `force_visiting=True` → returns `True`.

23. **`test_should_use_visiting_sdk_unavailable`** — Patch `is_available()` to return False → returns `False`.

24. **`test_should_use_visiting_default_bootstrap`** — No Hebbian history, SDK available → returns `True` (default bootstrap).

25. **`test_should_use_visiting_hebbian_prefers_native`** — Mock hebbian_router with native weight 0.8, visiting weight 0.3 → returns `False`.

26. **`test_should_use_visiting_hebbian_prefers_visiting`** — Mock hebbian_router with native weight 0.3, visiting weight 0.8 → returns `True`.

27. **`test_should_use_visiting_hebbian_insufficient_history`** — Both weights below 0.1 → returns `True` (bootstrap default).

28. **`test_build_result_has_builder_source`** — `BuildResult` has `builder_source` field defaulting to `"native"`.

29. **`test_builder_variant_relationship_constant`** — Import `REL_BUILDER_VARIANT` from `probos.mesh.routing`. Assert it equals `"builder_variant"`.

---

## Summary of Changes

### New Files
| File | Purpose |
|------|---------|
| `src/probos/cognitive/copilot_adapter.py` | CopilotBuilderAdapter + MCP tool handlers |
| `tests/test_copilot_adapter.py` | 29 tests for AD-351/352/353 |

### Modified Files
| File | Changes |
|------|---------|
| `src/probos/cognitive/builder.py` | Add `builder_source` to BuildResult, add `_should_use_visiting_builder()`, modify `perceive()` and `act()` for visiting builder routing, modify `execute_approved_build()` for builder_source propagation and Hebbian recording |
| `src/probos/mesh/routing.py` | Add `REL_BUILDER_VARIANT` constant |
| `pyproject.toml` | Add `copilot` optional dependency group |

### Do NOT Modify
- `cognitive_agent.py` — the visiting builder bypasses the CognitiveAgent lifecycle entirely
- `standing_orders.py` — `compose_instructions()` is called as-is, no changes needed
- `runtime.py` — no changes; adapter receives runtime via kwargs like other agents
- Any existing test files — the new tests go in their own file

---

## Validation Checklist

1. All 29 tests pass
2. All existing tests still pass (no regressions)
3. When the Copilot SDK is NOT installed:
   - `CopilotBuilderAdapter.is_available()` returns `False`
   - `_should_use_visiting_builder()` returns `False`
   - The native Builder pipeline works exactly as before
   - No import errors at module load time (the SDK import is guarded with try/except)
4. The visiting builder's file output format matches the native Builder's format exactly (same `_parse_file_blocks()` parser)
5. Standing Orders composition includes all 5 tiers (hardcoded identity, federation, ship, engineering department, builder personal)
6. `builder_source` propagates through the full pipeline: `perceive()` → `act()` → `execute_approved_build()` → `BuildResult`
7. Hebbian weights update correctly on success AND failure
8. The adapter fails-open: any Copilot SDK error → fallback to native Builder
9. No hardcoded API keys or tokens — authentication uses the Copilot CLI's existing login

---

## Architecture Decision Records

### AD-351: CopilotBuilderAdapter

`CopilotBuilderAdapter` wraps the GitHub Copilot SDK Python package to execute build tasks as a visiting officer. The adapter is NOT a CognitiveAgent — it's an external system wrapper (like ChannelAdapter for Discord). Creates a CopilotClient, injects ProbOS Standing Orders as system instructions, registers MCP tools, translates BuildSpec to session prompt, captures output in native file block format. Fails-open on any SDK error. SDK import guarded with try/except (optional dependency). `CopilotBuildResult` dataclass for structured output. 11 tests.

### AD-352: ProbOS MCP Tool Server

Seven MCP tools registered with Copilot sessions via the SDK's `Tool` class: `codebase_query` (CodebaseIndex.query), `codebase_find_callers` (find_callers), `codebase_get_imports` (get_imports), `codebase_find_tests` (find_tests_for), `codebase_read_source` (read_source), `system_self_model` (SystemSelfModel.to_context), `standing_orders_lookup` (department protocol files). Tools expose ProbOS internals so the visiting Builder has the same knowledge as the native Builder. Each handler returns `{"textResultForLlm": str, "resultType": "success"}`. 8 tests.

### AD-353: Routing & Apprenticeship Wiring

`_should_use_visiting_builder()` routing decision based on SDK availability, force flags, and Hebbian weight comparison. `builder_source` field added to `BuildResult` ("native" or "visiting"). Hebbian `builder_variant` relationship type tracks `(build_code, native|visiting)` success/failure. Outcomes recorded after Copilot session (immediate) and after test results (execute_approved_build). Default: prefer visiting in bootstrap phase. Over time, Hebbian weights steer toward whichever builder produces more passing code. `REL_BUILDER_VARIANT` constant in routing.py. 10 tests.
